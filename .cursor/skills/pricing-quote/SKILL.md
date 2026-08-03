---
name: pricing-quote
description: >-
  Pricing quote interface for Glow Beauty — Decimal math, hardcoded threshold
  discount, local engine vs API quote with identical I/O. Use when changing
  calculate_pricing, backend/repositories/pricing.py, cart totals, ส่วนลด,
  ราคารวม, or PRICING_QUOTE_* env vars.
---

# Pricing quote

## Principle

LLM must not add/multiply money. Resolve unit prices from the catalog inside the quote service, compute with `Decimal`, return stable JSON for the synthesizer.

## Contract (do not break)

**Input** `QuoteRequest`:
- `line_items[]`: `sku` / `name` / `category` / `shade` + `qty`
- `query` (optional)

**Output** `QuoteResponse`:
- `source`: `pricing_engine` | `pricing_api`
- `status`: `ok` | `error` | `not_found`
- `currency`, `line_items[]` (`unit_price`, `line_total` as strings)
- `subtotal`, `discount`, `discount_percent`, `discount_rule`, `total`, `messages`

Same JSON for local and future API so agent prompts stay unchanged.

## Backends

| `PRICING_QUOTE_BACKEND` | Implementation |
|-------------------------|----------------|
| `local` (default) | `LocalPricingQuoteService` |
| `api` | `ApiPricingQuoteService` → `POST PRICING_QUOTE_API_URL` |

Factory: `get_pricing_service()` in `backend/repositories/pricing.py`.  
Agent entry: `calculate_quote()` → tool `calculate_pricing` in `backend/agent/graph.py`.

## PoC discount (hardcoded)

- Rule: **ซื้อเกิน 500 บาท ลด 10%**
- Condition: `subtotal > 500` (not `>=`)
- Constants: `DISCOUNT_THRESHOLD`, `DISCOUNT_PERCENT`, `DISCOUNT_RULE_TH`
- Use `ROUND_HALF_UP` to 2 decimal places; serialize money as strings (`"580.00"`)

## Agent wiring checklist

When changing pricing behavior:

1. Update engine math / rules in `pricing.py` (+ unit tests in `backend/tests/test_pricing.py`)
2. Keep `quote_filters` / `QuoteLineItemPlan` in the planner schema
3. `_tool_args_for_step` must pass `line_items` from the plan
4. Synthesizer prompt rule 5c: use quote numbers exactly
5. Do not teach the LLM the 10% rule as free-form arithmetic — evidence must carry `discount_rule`

## Tests

```bash
uv run --project backend python -m unittest backend.tests.test_pricing -v
uv run --project backend python -m unittest discover -s backend/tests -v
```

Cover at least: below threshold, over threshold, missing SKU, stable JSON shape, API-missing-URL error.
