from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from backend.repositories.db import get_database_url

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_COLUMN_ALIASES = {
    "sku": ("sku", "product_sku", "code", "product_code"),
    "name": ("name_th", "name", "product_name", "title"),
    "stock": ("stock_qty", "stock", "stock_quantity", "quantity", "qty", "inventory"),
    "shade": ("shade", "color", "colour", "colors", "colour_name", "color_name"),
    "price": ("price_thb", "price", "unit_price", "sale_price", "selling_price"),
    "category": ("category", "product_category", "type"),
    "description": ("description", "details", "short_description"),
}


class ProductCatalogError(RuntimeError):
    pass


def _configured_table() -> tuple[str, str]:
    raw = os.getenv("SUPABASE_PRODUCTS_TABLE", "products").strip()
    parts = raw.split(".", 1)
    schema, table = ("public", parts[0]) if len(parts) == 1 else (parts[0], parts[1])
    if not _IDENTIFIER.fullmatch(schema) or not _IDENTIFIER.fullmatch(table):
        raise ProductCatalogError("SUPABASE_PRODUCTS_TABLE must be a valid schema/table name")
    return schema, table


def _table_columns(conn: psycopg.Connection, schema: str, table: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
            """,
            (schema, table),
        )
        return [
            str(row["column_name"] if isinstance(row, dict) else row[0])
            for row in cur.fetchall()
        ]


def _resolve_columns(columns: list[str]) -> dict[str, str]:
    lookup = {column.casefold(): column for column in columns}
    resolved: dict[str, str] = {}
    for field, aliases in _COLUMN_ALIASES.items():
        match = next((lookup[alias] for alias in aliases if alias in lookup), None)
        if match:
            resolved[field] = match
    return resolved


def _serialize_result(
    *,
    status: str,
    query: str,
    filters: dict[str, Any],
    rows: list[dict[str, Any]] | None = None,
    similar_products: list[dict[str, Any]] | None = None,
    message: str,
) -> str:
    return json.dumps(
        {
            "source": "supabase_products",
            "status": status,
            "query": query,
            "filters": filters,
            "message": message,
            "products": rows or [],
            "similar_products": similar_products or [],
        },
        ensure_ascii=False,
        default=str,
    )


def _run_product_query(
    conn: psycopg.Connection,
    *,
    schema: str,
    table: str,
    resolved: dict[str, str],
    sku: str | None,
    name: str | None,
    category: str | None,
    shade: str | None,
    in_stock_only: bool,
    exclude_skus: list[str] | None = None,
    limit: int,
) -> list[dict[str, Any]]:
    selected = list(dict.fromkeys(resolved.values()))
    conditions: list[sql.Composed] = []
    params: list[Any] = []
    for field, value in (
        ("sku", sku),
        ("name", name),
        ("category", category),
        ("shade", shade),
    ):
        if not value:
            continue
        if field not in resolved:
            raise ProductCatalogError(f"ตารางสินค้าไม่มีคอลัมน์สำหรับ filter: {field}")
        conditions.append(
            sql.SQL("{}::text ILIKE %s").format(sql.Identifier(resolved[field]))
        )
        params.append(f"%{value.strip()}%")
    if in_stock_only:
        if "stock" not in resolved:
            raise ProductCatalogError("ตารางสินค้าไม่มีคอลัมน์ stock")
        conditions.append(sql.SQL("{} > 0").format(sql.Identifier(resolved["stock"])))
    if exclude_skus and "sku" in resolved:
        conditions.append(
            sql.SQL("{}::text NOT IN ({})").format(
                sql.Identifier(resolved["sku"]),
                sql.SQL(", ").join(sql.Placeholder() * len(exclude_skus)),
            )
        )
        params.extend(exclude_skus)

    statement = sql.SQL("SELECT {} FROM {}.{}").format(
        sql.SQL(", ").join(sql.Identifier(column) for column in selected),
        sql.Identifier(schema),
        sql.Identifier(table),
    )
    if conditions:
        statement += sql.SQL(" WHERE ") + sql.SQL(" AND ").join(conditions)
    statement += sql.SQL(" LIMIT %s")
    params.append(max(1, min(limit, 50)))

    with conn.cursor() as cur:
        cur.execute(statement, params)
        raw_rows = list(cur.fetchall())

    return [
        {
            field: row[column]
            for field, column in resolved.items()
            if column in row
        }
        for row in raw_rows
    ]


def _infer_category_from_query(
    query: str,
    *,
    known_categories: list[str] | None = None,
) -> str | None:
    """Best-effort category hint when the planner omitted category on a miss."""
    text = query.casefold()
    if not text:
        return None
    for category in known_categories or []:
        token = str(category).strip()
        if token and token.casefold() in text:
            return token
    # Common Thai/English product-family cues used in this shop catalog.
    aliases = (
        ("lipstick", ("lipstick", "ลิป", "ลิปสติก", "ลิปแมตต์", "ลิปแมท")),
        ("mascara", ("mascara", "มาสคาร่า")),
        ("cushion", ("cushion", "คุชชั่น")),
        ("foundation", ("foundation", "รองพื้น")),
        ("eyeshadow", ("eyeshadow", "อายแชโดว์", "อายแชดโดว์")),
        ("serum", ("serum", "เซรั่ม")),
        ("sunscreen", ("sunscreen", "กันแดด")),
    )
    for category, cues in aliases:
        if any(cue in text for cue in cues):
            return category
    return None


def _product_is_unavailable(
    product: dict[str, Any],
    requested_qty: int | None = None,
) -> bool:
    stock = product.get("stock")
    if isinstance(stock, (int, float)):
        if stock <= 0:
            return True
        if requested_qty and stock < requested_qty:
            return True
    return product.get("can_fulfill") is False


def _find_similar_products(
    conn: psycopg.Connection,
    *,
    schema: str,
    table: str,
    resolved: dict[str, str],
    category: str | None,
    name: str | None,
    query: str = "",
    in_stock_only: bool = False,
    exclude_skus: list[str] | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Broaden a failed exact lookup — prefer same category, then name fragment."""
    category_candidates: list[str] = []
    if category:
        category_candidates.append(category)
    inferred = _infer_category_from_query(query)
    if inferred and inferred not in category_candidates:
        category_candidates.append(inferred)

    if "category" in resolved:
        for candidate in category_candidates:
            rows = _run_product_query(
                conn,
                schema=schema,
                table=table,
                resolved=resolved,
                sku=None,
                name=None,
                category=candidate,
                shade=None,
                in_stock_only=in_stock_only,
                exclude_skus=exclude_skus,
                limit=limit,
            )
            if rows:
                return rows

    # Drop precise shade/SKU-style name numbers; keep longer name tokens if any.
    name_token = (name or "").strip()
    if name_token and not re.fullmatch(r"0*\d{1,3}", name_token) and "name" in resolved:
        return _run_product_query(
            conn,
            schema=schema,
            table=table,
            resolved=resolved,
            sku=None,
            name=name_token,
            category=None,
            shade=None,
            in_stock_only=in_stock_only,
            exclude_skus=exclude_skus,
            limit=limit,
        )
    return []


@lru_cache(maxsize=1)
def _load_product_catalog_metadata() -> dict[str, Any]:
    schema, table = _configured_table()
    with psycopg.connect(
        get_database_url(),
        row_factory=dict_row,
        connect_timeout=10,
    ) as conn:
        resolved = _resolve_columns(_table_columns(conn, schema, table))
        metadata: dict[str, Any] = {}
        for field in ("category", "shade"):
            column = resolved.get(field)
            if not column:
                continue
            statement = sql.SQL(
                "SELECT DISTINCT {}::text AS value FROM {}.{} "
                "WHERE {} IS NOT NULL ORDER BY value LIMIT 100"
            ).format(
                sql.Identifier(column),
                sql.Identifier(schema),
                sql.Identifier(table),
                sql.Identifier(column),
            )
            with conn.cursor() as cur:
                cur.execute(statement)
                metadata[f"{field}_values"] = [
                    str(row["value"])
                    for row in cur.fetchall()
                    if row.get("value") not in (None, "")
                ]

        sample_fields = [
            field
            for field in ("sku", "name", "category", "shade")
            if field in resolved
        ]
        if sample_fields:
            statement = sql.SQL("SELECT {} FROM {}.{} ORDER BY {} LIMIT 40").format(
                sql.SQL(", ").join(
                    sql.Identifier(resolved[field]) for field in sample_fields
                ),
                sql.Identifier(schema),
                sql.Identifier(table),
                sql.Identifier(resolved.get("sku") or resolved[sample_fields[0]]),
            )
            with conn.cursor() as cur:
                cur.execute(statement)
                metadata["sample_products"] = [
                    {
                        field: row[resolved[field]]
                        for field in sample_fields
                        if resolved[field] in row
                    }
                    for row in cur.fetchall()
                ]
    return metadata


def get_product_catalog_metadata() -> dict[str, Any]:
    """Return live canonical categories, shades, and sample products for planner extraction."""
    try:
        return _load_product_catalog_metadata()
    except (psycopg.Error, RuntimeError):
        return {}


def search_products(
    query: str = "",
    *,
    sku: str | None = None,
    name: str | None = None,
    category: str | None = None,
    shade: str | None = None,
    in_stock_only: bool = False,
    requested_qty: int | None = None,
    requested_fields: list[str] | None = None,
    limit: int = 20,
) -> str:
    """Search trusted product facts using structured filters from the planner."""
    query = query.strip()
    filters: dict[str, Any] = {
        key: value
        for key, value in {
            "sku": sku,
            "name": name,
            "category": category,
            "shade": shade,
            "in_stock_only": in_stock_only,
            "requested_qty": requested_qty,
            "requested_fields": requested_fields or [],
        }.items()
        if value not in (None, "", [], False)
    }

    schema, table = _configured_table()
    try:
        with psycopg.connect(
            get_database_url(),
            row_factory=dict_row,
            connect_timeout=10,
        ) as conn:
            columns = _table_columns(conn, schema, table)
            if not columns:
                return _serialize_result(
                    status="error",
                    query=query,
                    filters=filters,
                    message=f"ไม่พบตารางสินค้า {schema}.{table}",
                )

            resolved = _resolve_columns(columns)
            if not resolved:
                return _serialize_result(
                    status="error",
                    query=query,
                    filters=filters,
                    message=(
                        f"ตาราง {schema}.{table} ไม่มีคอลัมน์สินค้าที่รองรับ "
                        "(sku/name/stock/color/price)"
                    ),
                )

            try:
                products = _run_product_query(
                    conn,
                    schema=schema,
                    table=table,
                    resolved=resolved,
                    sku=sku,
                    name=name,
                    category=category,
                    shade=shade,
                    in_stock_only=in_stock_only,
                    limit=limit,
                )
            except ProductCatalogError as exc:
                return _serialize_result(
                    status="error",
                    query=query,
                    filters=filters,
                    message=str(exc),
                )

            if requested_qty:
                for product in products:
                    stock = product.get("stock")
                    if isinstance(stock, (int, float)):
                        product["requested_qty"] = requested_qty
                        product["can_fulfill"] = stock >= requested_qty

            if not products:
                similar = _find_similar_products(
                    conn,
                    schema=schema,
                    table=table,
                    resolved=resolved,
                    category=category,
                    name=name,
                    query=query,
                    in_stock_only=True,
                    limit=5,
                )
                return _serialize_result(
                    status="not_found",
                    query=query,
                    filters=filters,
                    similar_products=similar,
                    message=(
                        "ไม่พบสินค้าที่ตรงกับ structured filters ใน Supabase"
                        + (
                            f" แต่พบสินค้าใกล้เคียง {len(similar)} รายการ"
                            if similar
                            else ""
                        )
                    ),
                )

            unavailable = [
                product
                for product in products
                if _product_is_unavailable(product, requested_qty)
            ]
            similar_products: list[dict[str, Any]] = []
            if unavailable:
                # Prefer other in-stock matches from this result, then broaden by category.
                in_stock_matches = [
                    product
                    for product in products
                    if not _product_is_unavailable(product, requested_qty)
                ]
                exclude_skus = [
                    str(product["sku"])
                    for product in products
                    if product.get("sku") not in (None, "")
                ]
                product_category = category
                if not product_category:
                    product_category = next(
                        (
                            str(product["category"])
                            for product in products
                            if product.get("category") not in (None, "")
                        ),
                        None,
                    )
                broadened = _find_similar_products(
                    conn,
                    schema=schema,
                    table=table,
                    resolved=resolved,
                    category=product_category,
                    name=name,
                    query=query,
                    in_stock_only=True,
                    exclude_skus=exclude_skus or None,
                    limit=5,
                )
                seen_skus: set[str] = set()
                for product in [*in_stock_matches, *broadened]:
                    sku_key = str(product.get("sku") or "")
                    if sku_key and sku_key in seen_skus:
                        continue
                    if sku_key:
                        seen_skus.add(sku_key)
                    similar_products.append(product)
                    if len(similar_products) >= 5:
                        break

            return _serialize_result(
                status="ok",
                query=query,
                filters=filters,
                rows=products,
                similar_products=similar_products,
                message=f"พบข้อมูลสินค้า {len(products)} รายการ",
            )
    except (psycopg.Error, RuntimeError) as exc:
        return _serialize_result(
            status="error",
            query=query,
            filters=filters,
            message=f"ไม่สามารถค้นหาตารางสินค้าได้: {exc}",
        )
