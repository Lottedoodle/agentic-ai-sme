"""Pricing quote interface — local engine now, API-compatible later.

Both backends share the same QuoteRequest / QuoteResponse JSON shape so the
agent tool can switch via PRICING_QUOTE_BACKEND without changing prompts.
"""

from __future__ import annotations

import json
import os
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Callable, Literal, Protocol

from pydantic import BaseModel, Field

Money = Decimal
_TWOPLACES = Decimal("0.01")

# Hardcoded PoC promo: subtotal over 500 THB → 10% off.
DISCOUNT_THRESHOLD = Decimal("500")
DISCOUNT_PERCENT = Decimal("10")
DISCOUNT_RULE_TH = "ซื้อเกิน 500 บาท ลด 10%"


class QuoteLineItemIn(BaseModel):
    """One line the customer wants priced (identity filters + quantity)."""

    sku: str | None = None
    name: str | None = None
    category: str | None = None
    shade: str | None = None
    qty: int = Field(default=1, ge=1)


class QuoteRequest(BaseModel):
    """Stable input contract for local engine and future quote API."""

    line_items: list[QuoteLineItemIn] = Field(default_factory=list, max_length=10)
    query: str = ""


class QuoteLineItemOut(BaseModel):
    sku: str
    name: str | None = None
    category: str | None = None
    shade: str | None = None
    qty: int
    unit_price: str
    line_total: str
    stock: int | None = None
    can_fulfill: bool | None = None


class QuoteResponse(BaseModel):
    """Stable output contract — synthesizer must use these numbers as-is."""

    source: Literal["pricing_engine", "pricing_api"]
    status: Literal["ok", "error", "not_found"]
    currency: str = "THB"
    query: str = ""
    line_items: list[QuoteLineItemOut] = Field(default_factory=list)
    subtotal: str = "0.00"
    discount: str = "0.00"
    discount_percent: str | None = None
    discount_rule: str | None = None
    total: str = "0.00"
    messages: list[str] = Field(default_factory=list)
    message: str = ""


class PricingQuoteService(Protocol):
    def quote(self, request: QuoteRequest) -> QuoteResponse: ...


def _money(value: Money) -> str:
    return str(value.quantize(_TWOPLACES, rounding=ROUND_HALF_UP))


def _to_decimal(value: Any) -> Money | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def apply_threshold_discount(subtotal: Money) -> tuple[Money, Money | None, str | None]:
    """Return (discount_amount, discount_percent, rule_label)."""
    if subtotal > DISCOUNT_THRESHOLD:
        discount = (subtotal * DISCOUNT_PERCENT / Decimal("100")).quantize(
            _TWOPLACES, rounding=ROUND_HALF_UP
        )
        return discount, DISCOUNT_PERCENT, DISCOUNT_RULE_TH
    return Money("0.00"), None, None


def compute_quote_totals(
    priced_lines: list[dict[str, Any]],
) -> tuple[Money, Money, Money | None, str | None, Money]:
    subtotal = sum(
        (line["line_total"] for line in priced_lines),
        start=Money("0.00"),
    ).quantize(_TWOPLACES, rounding=ROUND_HALF_UP)
    discount, percent, rule = apply_threshold_discount(subtotal)
    total = (subtotal - discount).quantize(_TWOPLACES, rounding=ROUND_HALF_UP)
    return subtotal, discount, percent, rule, total


ProductResolver = Callable[[QuoteLineItemIn], dict[str, Any] | None]


def _default_resolve_product(item: QuoteLineItemIn) -> dict[str, Any] | None:
    """Resolve a line against the live catalog; prices never come from the LLM."""
    from backend.repositories.product_catalog import search_products

    if not any([item.sku, item.name, item.category, item.shade]):
        return None
    payload = json.loads(
        search_products(
            query=item.sku or item.name or item.category or "",
            sku=item.sku,
            name=item.name,
            category=item.category,
            shade=item.shade,
            requested_qty=item.qty,
            requested_fields=["sku", "name", "category", "shade", "price", "stock"],
            limit=5,
        )
    )
    if payload.get("status") != "ok":
        return None
    products = payload.get("products") or []
    if not products:
        return None
    # Prefer exact SKU match when provided.
    if item.sku:
        sku_key = item.sku.strip().casefold()
        for product in products:
            if str(product.get("sku") or "").casefold() == sku_key:
                return product
    return products[0]


class LocalPricingQuoteService:
    """In-process quote engine (Decimal math + hardcoded threshold promo)."""

    def __init__(self, resolve_product: ProductResolver | None = None) -> None:
        self._resolve_product = resolve_product or _default_resolve_product

    def quote(self, request: QuoteRequest) -> QuoteResponse:
        if not request.line_items:
            return QuoteResponse(
                source="pricing_engine",
                status="error",
                query=request.query,
                message="ต้องระบุรายการสินค้าและจำนวนสำหรับการคิดราคา",
                messages=["ต้องระบุรายการสินค้าและจำนวนสำหรับการคิดราคา"],
            )

        priced: list[dict[str, Any]] = []
        missing: list[str] = []
        for item in request.line_items:
            product = self._resolve_product(item)
            if not product:
                label = item.sku or item.name or item.shade or item.category or "?"
                missing.append(str(label))
                continue
            unit = _to_decimal(product.get("price"))
            if unit is None:
                label = str(product.get("sku") or item.sku or "?")
                missing.append(label)
                continue
            line_total = (unit * item.qty).quantize(_TWOPLACES, rounding=ROUND_HALF_UP)
            stock = product.get("stock")
            stock_int = int(stock) if isinstance(stock, (int, float)) else None
            can_fulfill = product.get("can_fulfill")
            if can_fulfill is None and stock_int is not None:
                can_fulfill = stock_int >= item.qty
            priced.append(
                {
                    "sku": str(product.get("sku") or item.sku or ""),
                    "name": product.get("name"),
                    "category": product.get("category"),
                    "shade": product.get("shade"),
                    "qty": item.qty,
                    "unit_price": unit,
                    "line_total": line_total,
                    "stock": stock_int,
                    "can_fulfill": can_fulfill,
                }
            )

        if missing and not priced:
            return QuoteResponse(
                source="pricing_engine",
                status="not_found",
                query=request.query,
                message=f"ไม่พบสินค้าสำหรับคิดราคา: {', '.join(missing)}",
                messages=[f"ไม่พบสินค้าสำหรับคิดราคา: {', '.join(missing)}"],
            )

        subtotal, discount, percent, rule, total = compute_quote_totals(priced)
        messages: list[str] = []
        if missing:
            messages.append(f"ข้ามสินค้าที่ไม่พบ: {', '.join(missing)}")
        if rule and discount > 0:
            messages.append(f"ใช้โปรโมชัน: {rule}")
        elif subtotal <= DISCOUNT_THRESHOLD:
            messages.append(
                f"ยอดยังไม่เกิน {_money(DISCOUNT_THRESHOLD)} บาท จึงยังไม่ได้รับส่วนลด 10%"
            )

        return QuoteResponse(
            source="pricing_engine",
            status="ok",
            query=request.query,
            line_items=[
                QuoteLineItemOut(
                    sku=line["sku"],
                    name=line.get("name"),
                    category=line.get("category"),
                    shade=line.get("shade"),
                    qty=line["qty"],
                    unit_price=_money(line["unit_price"]),
                    line_total=_money(line["line_total"]),
                    stock=line.get("stock"),
                    can_fulfill=line.get("can_fulfill"),
                )
                for line in priced
            ],
            subtotal=_money(subtotal),
            discount=_money(discount),
            discount_percent=str(percent) if percent is not None else None,
            discount_rule=rule,
            total=_money(total),
            messages=messages,
            message="คิดราคารายการสำเร็จ",
        )


class ApiPricingQuoteService:
    """Future quote API adapter — same request/response JSON as the local engine."""

    def __init__(self, api_url: str | None = None, timeout_s: float = 10.0) -> None:
        self.api_url = (api_url or os.getenv("PRICING_QUOTE_API_URL") or "").strip()
        self.timeout_s = timeout_s

    def quote(self, request: QuoteRequest) -> QuoteResponse:
        if not self.api_url:
            return QuoteResponse(
                source="pricing_api",
                status="error",
                query=request.query,
                message="PRICING_QUOTE_API_URL ยังไม่ได้ตั้งค่า",
                messages=["PRICING_QUOTE_API_URL ยังไม่ได้ตั้งค่า"],
            )
        try:
            import urllib.error
            import urllib.request

            payload = request.model_dump(exclude_none=True)
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                self.api_url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                body = resp.read().decode("utf-8")
            parsed = json.loads(body)
            # Normalize source so synthesizer can trust either backend.
            parsed["source"] = "pricing_api"
            return QuoteResponse.model_validate(parsed)
        except Exception as exc:
            return QuoteResponse(
                source="pricing_api",
                status="error",
                query=request.query,
                message=f"เรียก pricing quote API ไม่สำเร็จ: {exc}",
                messages=[f"เรียก pricing quote API ไม่สำเร็จ: {exc}"],
            )


def get_pricing_service() -> PricingQuoteService:
    backend = (os.getenv("PRICING_QUOTE_BACKEND") or "local").strip().casefold()
    if backend == "api":
        return ApiPricingQuoteService()
    return LocalPricingQuoteService()


def calculate_quote(
    *,
    line_items: list[dict[str, Any]] | list[QuoteLineItemIn] | None = None,
    sku: str | None = None,
    name: str | None = None,
    category: str | None = None,
    shade: str | None = None,
    qty: int | None = None,
    query: str = "",
) -> str:
    """Agent-facing entrypoint — always returns QuoteResponse JSON."""
    items: list[QuoteLineItemIn] = []
    for raw in line_items or []:
        if isinstance(raw, QuoteLineItemIn):
            items.append(raw)
        elif isinstance(raw, dict):
            items.append(QuoteLineItemIn.model_validate(raw))
    if not items and any([sku, name, category, shade]):
        items.append(
            QuoteLineItemIn(
                sku=sku,
                name=name,
                category=category,
                shade=shade,
                qty=qty or 1,
            )
        )
    request = QuoteRequest(line_items=items, query=query)
    result = get_pricing_service().quote(request)
    return result.model_dump_json()
