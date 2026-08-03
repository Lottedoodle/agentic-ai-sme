from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock

from langchain_core.messages import ToolMessage

from backend.agent.graph import (
    ExecutionPlan,
    PlanStep,
    ProductSearchFilters,
    QuoteFilters,
    QuoteLineItemPlan,
    _KB_NOT_FOUND_ANSWER,
    _ambiguous_shade_candidates,
    _fallback_plan,
    _normalize_plan,
    _product_not_found_with_similar_answer,
    _safe_no_evidence_answer,
    _sanitize_product_filters,
    _tool_args_for_step,
    _tool_evidence,
    format_agent_result,
    synthesizer_node,
)
from backend.repositories.order_tracking import extract_order_id, lookup_order
from backend.repositories.product_catalog import (
    _find_similar_products,
    _resolve_columns,
    _serialize_result,
    _table_columns,
)


class ShopAgentRoutingTests(unittest.TestCase):
    def test_normalized_plan_preserves_structured_product_filters(self) -> None:
        plan = ExecutionPlan(
            intent="product_data",
            summary="Check product availability",
            steps=[
                PlanStep(
                    tool="search_product_catalog",
                    query="",
                    product_filters=ProductSearchFilters(
                        category="lipstick",
                        requested_fields=["shade", "stock"],
                    ),
                    purpose="List lipstick shades and stock",
                )
            ],
        )

        normalized = _normalize_plan(plan, "ขอดูเฉดลิปสติกที่มีขาย")

        filters = normalized.steps[0].product_filters
        self.assertIsNotNone(filters)
        self.assertEqual(filters.category, "lipstick")
        self.assertEqual(filters.requested_fields, ["shade", "stock"])

    def test_sanitize_replaces_translated_name_with_product_number(self) -> None:
        filters = _sanitize_product_filters(
            "ลิปเบอร์ 3 ราคาเท่าไร",
            ProductSearchFilters(name="lip 3", requested_fields=["price"]),
        )

        self.assertEqual(filters.name, "03")
        self.assertNotEqual(filters.name, "lip 3")
        self.assertEqual(filters.category, "lipstick")

    def test_sanitize_drops_invented_number_when_question_has_none(self) -> None:
        filters = _sanitize_product_filters(
            "ลิปแมตต์เบอร์ ๆ ราคาเท่าไหร่คะ",
            ProductSearchFilters(
                name="05",
                category="lipstick",
                requested_fields=["price"],
            ),
        )

        self.assertIsNone(filters.name)
        self.assertEqual(filters.sku, "MISSING-PRODUCT-NUMBER")

    def test_normalize_plan_forces_not_found_when_number_missing(self) -> None:
        plan = ExecutionPlan(
            intent="product_data",
            summary="Guessed shade 05",
            steps=[
                PlanStep(
                    tool="search_product_catalog",
                    query="",
                    product_filters=ProductSearchFilters(name="05"),
                    purpose="Invented lookup",
                )
            ],
            needs_user_input=True,
            clarification_options=["01 Nude Beige", "05 Orange Pop"],
        )

        normalized = _normalize_plan(plan, "ลิปแมตต์เบอร์ ๆ ราคาเท่าไหร่คะ")

        self.assertFalse(normalized.needs_user_input)
        self.assertEqual(normalized.clarification_options, [])
        self.assertEqual(len(normalized.steps), 1)
        self.assertEqual(
            normalized.steps[0].product_filters.sku,
            "MISSING-PRODUCT-NUMBER",
        )

    def test_sanitize_keeps_explicit_missing_number_as_not_found_lookup(self) -> None:
        filters = _sanitize_product_filters(
            "ลิปแมตต์เบอร์ 99 ราคาเท่าไหร่",
            ProductSearchFilters(category="lipstick", requested_fields=["price"]),
        )

        self.assertEqual(filters.name, "99")
        self.assertIsNone(filters.sku)

    def test_ambiguous_red_shades_ask_for_clarification(self) -> None:
        recent = (
            "Assistant: ลิปแมตต์มี Nude Beige, Coral Red, Cherry Red, Pink Rose ค่ะ"
        )
        candidates = _ambiguous_shade_candidates(
            "เอาตัวสีแดงเมื่อกี้ ยังมีของอยู่มั้ย ขอ 2 แท่ง",
            recent,
            planned_shade="Cherry Red",
        )

        self.assertEqual(candidates, ["Coral Red", "Cherry Red"])

    def test_normalize_plan_marks_ambiguous_shades_for_user_input(self) -> None:
        recent = (
            "Assistant: ลิปแมตต์มี Nude Beige, Coral Red, Cherry Red, Pink Rose ค่ะ"
        )
        plan = ExecutionPlan(
            intent="product_data",
            summary="Check red lipstick stock",
            steps=[
                PlanStep(
                    tool="search_product_catalog",
                    query="",
                    product_filters=ProductSearchFilters(
                        category="lipstick",
                        shade="Cherry Red",
                        requested_qty=2,
                        requested_fields=["stock"],
                    ),
                    purpose="Check stock",
                )
            ],
        )

        normalized = _normalize_plan(
            plan,
            "เอาตัวสีแดงเมื่อกี้ ยังมีของอยู่มั้ย ขอ 2 แท่ง",
            recent,
        )

        self.assertTrue(normalized.needs_user_input)
        self.assertEqual(normalized.clarification_options, ["Coral Red", "Cherry Red"])
        self.assertEqual(normalized.steps, [])

    def test_explicit_cherry_red_is_not_ambiguous(self) -> None:
        recent = (
            "Assistant: ลิปแมตต์มี Nude Beige, Coral Red, Cherry Red, Pink Rose ค่ะ"
        )
        candidates = _ambiguous_shade_candidates(
            "เอา Cherry Red เมื่อกี้ ขอ 2 แท่ง",
            recent,
            planned_shade="Cherry Red",
        )

        self.assertEqual(candidates, [])

    def test_product_tool_args_come_from_structured_plan(self) -> None:
        step = {
            "tool": "search_product_catalog",
            "query": "",
            "product_filters": {
                "sku": "SUN-001",
                "requested_qty": 3,
                "requested_fields": ["price", "stock"],
            },
        }

        args = _tool_args_for_step(step, "คำถามต้นฉบับ")

        self.assertEqual(
            args,
            {
                "query": "คำถามต้นฉบับ",
                "sku": "SUN-001",
                "requested_qty": 3,
                "requested_fields": ["price", "stock"],
            },
        )

    def test_order_status_tool_args_include_order_id(self) -> None:
        args = _tool_args_for_step(
            {
                "tool": "lookup_order_status",
                "query": "ออเดอร์ถึงไหน",
                "order_id": "GB-1001",
            },
            "ออเดอร์ GB-1001 ถึงไหนแล้ว",
        )
        self.assertEqual(
            args,
            {"query": "ออเดอร์ถึงไหน", "order_id": "GB-1001"},
        )

    def test_pricing_tool_args_come_from_quote_filters(self) -> None:
        args = _tool_args_for_step(
            {
                "tool": "calculate_pricing",
                "query": "",
                "quote_filters": {
                    "line_items": [
                        {"category": "lipstick", "name": "01", "qty": 2},
                    ]
                },
            },
            "ลิปแมตต์เบอร์ 1 ขอ 2 แท่ง ราคารวมเท่าไหร่",
        )
        self.assertEqual(
            args,
            {
                "query": "ลิปแมตต์เบอร์ 1 ขอ 2 แท่ง ราคารวมเท่าไหร่",
                "line_items": [
                    {"category": "lipstick", "name": "01", "qty": 2},
                ],
            },
        )

    def test_normalize_plan_keeps_pricing_with_product_number(self) -> None:
        plan = ExecutionPlan(
            intent="product_data",
            summary="ราคารวมลิปเบอร์ 1",
            steps=[
                PlanStep(
                    tool="search_product_catalog",
                    query="",
                    product_filters=ProductSearchFilters(
                        category="lipstick",
                        name="01",
                        requested_qty=2,
                        requested_fields=["price", "stock"],
                    ),
                    purpose="เช็กสต็อกและราคาต่อชิ้น",
                ),
                PlanStep(
                    tool="calculate_pricing",
                    query="",
                    quote_filters=QuoteFilters(
                        line_items=[
                            QuoteLineItemPlan(category="lipstick", name="01", qty=2)
                        ]
                    ),
                    purpose="คิดราคารวม",
                ),
            ],
        )
        normalized = _normalize_plan(
            plan, "ลิปแมตต์เบอร์ 1 ขอ 2 แท่ง ราคารวมเท่าไหร่"
        )
        tools = [step.tool for step in normalized.steps]
        self.assertEqual(tools, ["search_product_catalog", "calculate_pricing"])
        quote = normalized.steps[1].quote_filters
        assert quote is not None
        self.assertEqual(quote.line_items[0].name, "01")
        self.assertEqual(quote.line_items[0].qty, 2)

    def test_fallback_checks_both_sources_without_keyword_routing(self) -> None:
        plan = _fallback_plan("ช่วยตรวจสอบข้อมูลนี้ให้หน่อย")

        self.assertEqual(plan.intent, "mixed")
        self.assertEqual(
            [step.tool for step in plan.steps],
            ["search_product_catalog", "search_store_knowledge"],
        )

    def test_forbidden_questions_are_not_embedded_as_few_shots(self) -> None:
        from backend.agent import graph as graph_module

        forbidden = [
            "มีลิปแมตต์สีอะไรบ้าง",
            "ลิปเบอร์ 3 ราคาเท่าไร",
            "เอาตัวสีแดงเมื่อกี้ ขอ 2 แท่ง",
        ]
        for question in forbidden:
            self.assertNotIn(question, graph_module.PLANNER_PROMPT)

    def test_format_result_marks_clarification_as_awaiting_user(self) -> None:
        payload = format_agent_result(
            {
                "execution_result": "ต้องการ Coral Red หรือ Cherry Red คะ?",
                "needs_user_input": True,
                "clarification_options": ["Coral Red", "Cherry Red"],
                "next_step": "awaiting_user",
            }
        )

        self.assertTrue(payload["awaiting_user"])
        self.assertFalse(payload["done"])


class GroundingTests(unittest.TestCase):
    def test_tool_evidence_parses_json_payload(self) -> None:
        payload = {
            "source": "supabase_products",
            "status": "not_found",
            "products": [],
        }
        messages = [
            ToolMessage(
                content=json.dumps(payload),
                tool_call_id="test-call",
                name="search_product_catalog",
            )
        ]

        self.assertEqual(_tool_evidence(messages), [payload])

    def test_tool_evidence_deduplicates_identical_payloads(self) -> None:
        payload = {
            "source": "supabase_products",
            "status": "not_found",
            "products": [],
        }
        messages = [
            ToolMessage(
                content=json.dumps(payload),
                tool_call_id="call-1",
                name="search_product_catalog",
            ),
            ToolMessage(
                content=json.dumps(payload),
                tool_call_id="call-2",
                name="search_product_catalog",
            ),
        ]

        self.assertEqual(_tool_evidence(messages), [payload])

    def test_synthesizer_does_not_invent_when_no_data_found(self) -> None:
        state = {
            "user_input": "SKU UNKNOWN ราคาเท่าไร",
            "messages": [
                ToolMessage(
                    content=json.dumps(
                        {
                            "source": "supabase_products",
                            "status": "not_found",
                            "products": [],
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="test-call",
                    name="search_product_catalog",
                )
            ],
            "audit_log": [],
        }

        result = synthesizer_node(state)

        self.assertIn("ไม่พบสินค้า", result["execution_result"])
        self.assertTrue(result["verification"]["grounded_in_sources"])

    def test_product_not_found_recommends_similar_products(self) -> None:
        evidence = [
            {
                "source": "supabase_products",
                "status": "not_found",
                "products": [],
                "similar_products": [
                    {
                        "sku": "LIP-001",
                        "name": "ลิปแมตต์ เบอร์ 01",
                        "category": "lipstick",
                        "price": 290,
                    },
                    {
                        "sku": "LIP-002",
                        "name": "ลิปแมตต์ เบอร์ 02",
                        "category": "lipstick",
                        "price": 290,
                    },
                ],
            }
        ]
        formatted = _product_not_found_with_similar_answer(evidence)
        self.assertIsNotNone(formatted)
        assert formatted is not None
        self.assertIn("ยังไม่มีสินค้าที่ตรงตามรายการ", formatted)
        self.assertIn("1234567890", formatted)
        self.assertIn("LIP-001", formatted)

        state = {
            "user_input": "ลิปแมตต์เบอร์ 6 ราคาเท่าไหร่คะ",
            "messages": [
                ToolMessage(
                    content=json.dumps(evidence[0], ensure_ascii=False),
                    tool_call_id="product-call",
                    name="search_product_catalog",
                )
            ],
            "audit_log": [],
        }
        result = synthesizer_node(state)
        self.assertIn("ยังไม่มีสินค้าที่ตรงตามรายการ", result["execution_result"])
        self.assertIn("LIP-002", result["execution_result"])
        self.assertTrue(result["verification"]["grounded_in_sources"])

    def test_out_of_stock_apologizes_recommends_similar_and_admin_contact(self) -> None:
        evidence = {
            "source": "supabase_products",
            "status": "ok",
            "products": [
                {
                    "sku": "SUN-002",
                    "name": "กันแดดสเปรย์ SPF50 150ml",
                    "category": "sunscreen",
                    "price": 350,
                    "stock": 0,
                    "requested_qty": 2,
                    "can_fulfill": False,
                }
            ],
            "similar_products": [
                {
                    "sku": "SUN-001",
                    "name": "กันแดด SPF50 PA++++ 40ml",
                    "category": "sunscreen",
                    "price": 390,
                    "stock": 50,
                }
            ],
        }
        result = synthesizer_node(
            {
                "user_input": "กันแดดสเปรย์ยังมีของไหมคะ อยากได้สัก 2 ขวด",
                "messages": [
                    ToolMessage(
                        content=json.dumps(evidence, ensure_ascii=False),
                        tool_call_id="product-call",
                        name="search_product_catalog",
                    )
                ],
                "audit_log": [],
            }
        )
        answer = result["execution_result"]
        self.assertIn("ขออภัย", answer)
        self.assertIn("SUN-002", answer)
        self.assertIn("หมดสต็อก", answer)
        self.assertIn("1234567890", answer)
        self.assertIn("SUN-001", answer)
        self.assertIn("สินค้าใกล้เคียง", answer)
        self.assertTrue(result["verification"]["grounded_in_sources"])

    def test_partial_out_of_stock_focuses_asked_item_and_recommends_in_stock(self) -> None:
        """When search returns mixed stock, still apologize for the OOS item."""
        evidence = {
            "source": "supabase_products",
            "status": "ok",
            "products": [
                {
                    "sku": "SUN-001",
                    "name": "กันแดด SPF50 PA++++ 40ml",
                    "category": "sunscreen",
                    "price": 390,
                    "stock": 50,
                    "requested_qty": 2,
                    "can_fulfill": True,
                },
                {
                    "sku": "SUN-002",
                    "name": "กันแดดสเปรย์ SPF50 150ml",
                    "category": "sunscreen",
                    "price": 350,
                    "stock": 0,
                    "requested_qty": 2,
                    "can_fulfill": False,
                },
            ],
            "similar_products": [],
        }
        result = synthesizer_node(
            {
                "user_input": "กันแดดสเปรย์ยังมีของไหมคะ อยากได้สัก 2 ขวด",
                "messages": [
                    ToolMessage(
                        content=json.dumps(evidence, ensure_ascii=False),
                        tool_call_id="product-call",
                        name="search_product_catalog",
                    )
                ],
                "audit_log": [],
            }
        )
        answer = result["execution_result"]
        self.assertIn("ขออภัย", answer)
        self.assertIn("SUN-002", answer)
        self.assertIn("หมดสต็อก", answer)
        self.assertIn("1234567890", answer)
        self.assertIn("SUN-001", answer)
        self.assertIn("สินค้าใกล้เคียง", answer)

    def test_kb_not_found_points_customer_to_admin(self) -> None:
        evidence = [
            {
                "source": "glow_beauty_knowledge_base",
                "status": "not_found",
                "query": "ผ่อน 0% KBANK",
                "content": "ไม่พบเอกสารที่เกี่ยวข้องกับ: ผ่อน 0% KBANK",
            }
        ]
        self.assertEqual(_safe_no_evidence_answer(evidence), _KB_NOT_FOUND_ANSWER)

        state = {
            "user_input": "ผ่อน 0% 3 เดือนได้ป่าวคะ บัตร kbank",
            "messages": [
                ToolMessage(
                    content=json.dumps(evidence[0], ensure_ascii=False),
                    tool_call_id="kb-call",
                    name="search_store_knowledge",
                )
            ],
            "audit_log": [],
        }
        result = synthesizer_node(state)
        self.assertEqual(result["execution_result"], _KB_NOT_FOUND_ANSWER)
        self.assertIn("1234567890", result["execution_result"])


class OrderTrackingTests(unittest.TestCase):
    def test_extract_order_id_from_question(self) -> None:
        self.assertEqual(extract_order_id("เช็กออเดอร์ GB-1001 ให้หน่อย"), "GB-1001")
        self.assertEqual(extract_order_id("track KER123456789TH"), "KER123456789TH")

    def test_lookup_default_customer_order(self) -> None:
        payload = json.loads(lookup_order(query="พัสดุของฉันถึงไหนแล้ว"))
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["order"]["order_id"], "GB-1001")
        self.assertIn("kerryexpress.com", payload["order"]["tracking_url"])

    def test_lookup_unknown_order_is_not_found(self) -> None:
        payload = json.loads(lookup_order("GB-9999"))
        self.assertEqual(payload["status"], "not_found")


class ProductSchemaTests(unittest.TestCase):
    def test_serialize_result_includes_similar_products(self) -> None:
        payload = json.loads(
            _serialize_result(
                status="not_found",
                query="เบอร์ 6",
                filters={"category": "lipstick", "name": "06"},
                similar_products=[{"sku": "LIP-001", "name": "เบอร์ 01"}],
                message="miss",
            )
        )
        self.assertEqual(payload["status"], "not_found")
        self.assertEqual(payload["similar_products"][0]["sku"], "LIP-001")

    def test_find_similar_products_uses_category_when_exact_misses(self) -> None:
        conn = MagicMock()
        cursor = conn.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [
            {
                "sku": "LIP-001",
                "name_th": "ลิปแมตต์ เบอร์ 01",
                "category": "lipstick",
                "price_thb": 290,
                "stock_qty": 3,
                "shade": None,
            }
        ]
        resolved = {
            "sku": "sku",
            "name": "name_th",
            "category": "category",
            "price": "price_thb",
            "stock": "stock_qty",
            "shade": "shade",
        }
        rows = _find_similar_products(
            conn,
            schema="public",
            table="products",
            resolved=resolved,
            category="lipstick",
            name="06",
            limit=5,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["sku"], "LIP-001")
        self.assertEqual(rows[0]["name"], "ลิปแมตต์ เบอร์ 01")

    def test_table_columns_supports_dict_row_connection(self) -> None:
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [
            {"column_name": "sku"},
            {"column_name": "name_th"},
        ]

        columns = _table_columns(connection, "public", "products")

        self.assertEqual(columns, ["sku", "name_th"])

    def test_glow_beauty_csv_columns_are_resolved(self) -> None:
        resolved = _resolve_columns(
            ["sku", "name_th", "category", "shade", "price_thb", "stock_qty"]
        )

        self.assertEqual(
            resolved,
            {
                "sku": "sku",
                "name": "name_th",
                "stock": "stock_qty",
                "shade": "shade",
                "price": "price_thb",
                "category": "category",
            },
        )

    def test_common_product_columns_are_resolved(self) -> None:
        resolved = _resolve_columns(
            ["product_sku", "product_name", "stock_quantity", "colour", "sale_price"]
        )

        self.assertEqual(
            resolved,
            {
                "sku": "product_sku",
                "name": "product_name",
                "stock": "stock_quantity",
                "shade": "colour",
                "price": "sale_price",
            },
        )


if __name__ == "__main__":
    unittest.main()
