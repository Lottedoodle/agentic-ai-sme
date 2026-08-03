from __future__ import annotations

import json
import os
import unittest
from decimal import Decimal
from unittest.mock import patch

from backend.repositories.pricing import (
    DISCOUNT_RULE_TH,
    ApiPricingQuoteService,
    LocalPricingQuoteService,
    QuoteLineItemIn,
    QuoteRequest,
    QuoteResponse,
    apply_threshold_discount,
    calculate_quote,
    compute_quote_totals,
)


class ThresholdDiscountTests(unittest.TestCase):
    def test_no_discount_at_or_below_500(self) -> None:
        discount, percent, rule = apply_threshold_discount(Decimal("500.00"))
        self.assertEqual(discount, Decimal("0.00"))
        self.assertIsNone(percent)
        self.assertIsNone(rule)

        discount, percent, rule = apply_threshold_discount(Decimal("499.99"))
        self.assertEqual(discount, Decimal("0.00"))

    def test_ten_percent_when_over_500(self) -> None:
        discount, percent, rule = apply_threshold_discount(Decimal("500.01"))
        self.assertEqual(discount, Decimal("50.00"))
        self.assertEqual(percent, Decimal("10"))
        self.assertEqual(rule, DISCOUNT_RULE_TH)

        discount, _, _ = apply_threshold_discount(Decimal("1000"))
        self.assertEqual(discount, Decimal("100.00"))


class LocalPricingEngineTests(unittest.TestCase):
    def test_quote_applies_discount_and_keeps_stable_shape(self) -> None:
        catalog = {
            "LIP-001": {"sku": "LIP-001", "name": "ลิปแมตต์ เบอร์ 01", "price": 290, "stock": 20},
        }

        def resolve(item: QuoteLineItemIn):
            return catalog.get((item.sku or "").upper()) or catalog.get(item.sku or "")

        service = LocalPricingQuoteService(resolve_product=resolve)
        result = service.quote(
            QuoteRequest(
                line_items=[QuoteLineItemIn(sku="LIP-001", qty=2)],
                query="ราคารวม",
            )
        )

        self.assertEqual(result.source, "pricing_engine")
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.currency, "THB")
        self.assertEqual(result.subtotal, "580.00")
        self.assertEqual(result.discount, "58.00")
        self.assertEqual(result.total, "522.00")
        self.assertEqual(result.discount_rule, DISCOUNT_RULE_TH)
        self.assertEqual(result.line_items[0].unit_price, "290.00")
        self.assertEqual(result.line_items[0].line_total, "580.00")

    def test_quote_below_threshold_has_zero_discount(self) -> None:
        def resolve(item: QuoteLineItemIn):
            return {"sku": "LIP-001", "name": "lip", "price": 290, "stock": 5}

        service = LocalPricingQuoteService(resolve_product=resolve)
        result = service.quote(
            QuoteRequest(line_items=[QuoteLineItemIn(sku="LIP-001", qty=1)])
        )
        self.assertEqual(result.subtotal, "290.00")
        self.assertEqual(result.discount, "0.00")
        self.assertEqual(result.total, "290.00")
        self.assertIsNone(result.discount_rule)

    def test_missing_product_is_not_found(self) -> None:
        service = LocalPricingQuoteService(resolve_product=lambda _item: None)
        result = service.quote(
            QuoteRequest(line_items=[QuoteLineItemIn(sku="NOPE", qty=1)])
        )
        self.assertEqual(result.status, "not_found")

    def test_calculate_quote_json_roundtrip(self) -> None:
        def resolve(item: QuoteLineItemIn):
            return {"sku": "SUN-001", "name": "sunscreen", "price": 390, "stock": 10}

        with patch(
            "backend.repositories.pricing.get_pricing_service",
            return_value=LocalPricingQuoteService(resolve_product=resolve),
        ):
            raw = calculate_quote(line_items=[{"sku": "SUN-001", "qty": 2}], query="รวม")
        payload = json.loads(raw)
        self.assertEqual(payload["subtotal"], "780.00")
        self.assertEqual(payload["discount"], "78.00")
        self.assertEqual(payload["total"], "702.00")
        QuoteResponse.model_validate(payload)


class ApiPricingAdapterTests(unittest.TestCase):
    def test_api_backend_requires_url(self) -> None:
        with patch.dict(os.environ, {"PRICING_QUOTE_API_URL": ""}, clear=False):
            result = ApiPricingQuoteService(api_url="").quote(
                QuoteRequest(line_items=[QuoteLineItemIn(sku="X", qty=1)])
            )
        self.assertEqual(result.source, "pricing_api")
        self.assertEqual(result.status, "error")

    def test_compute_totals_helper(self) -> None:
        subtotal, discount, percent, rule, total = compute_quote_totals(
            [
                {"line_total": Decimal("300.00")},
                {"line_total": Decimal("250.00")},
            ]
        )
        self.assertEqual(subtotal, Decimal("550.00"))
        self.assertEqual(discount, Decimal("55.00"))
        self.assertEqual(percent, Decimal("10"))
        self.assertEqual(rule, DISCOUNT_RULE_TH)
        self.assertEqual(total, Decimal("495.00"))


if __name__ == "__main__":
    unittest.main()
