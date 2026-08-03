---
name: shop-agent
description: >-
  Glow Beauty Shop LangGraph agent conventions — Plan → ReAct → Synthesizer,
  tool boundaries, grounding, out-of-stock answers, and admin contact.
  Use when changing backend/agent/graph.py, agent tools, planner/react/synthesizer
  prompts, product catalog search, similar products, or chatbot answer rules.
---

# Shop agent (Glow Beauty)

## Architecture

```text
Planner → ReAct (+ ToolNode) → Synthesizer
```

- **Planner**: structured `ExecutionPlan` only — never answers the customer.
- **ReAct**: calls only planned tools; args come from `_tool_args_for_step` (plan), not free LLM args.
- **Synthesizer**: Thai answer from tool evidence only. Prefer deterministic fallbacks for OOS / not_found.

Key files:
- `backend/agent/graph.py` — prompts, tools, nodes
- `backend/repositories/product_catalog.py` — Supabase products
- `backend/rag/knowledge_base.py` — Bedrock KB
- `backend/repositories/order_tracking.py` — mock orders
- `backend/repositories/pricing.py` — quote engine
- `backend/tests/test_shop_agent.py`

## Tool boundaries (strict)

| Tool | Source of truth | Use for |
|------|-----------------|---------|
| `search_product_catalog` | Supabase `products` | SKU, name, shade, unit price, stock |
| `search_store_knowledge` | Bedrock KB | FAQ, promo copy, product properties |
| `lookup_order_status` | mock store | order / Kerry tracking |
| `calculate_pricing` | pricing engine/API | subtotal, discount, total |

Never:
- Route unit price/stock to KB
- Route order status to catalog/KB
- Let the LLM invent catalog facts or money math
- Put medical / “safe for sensitive skin” claims unless KB evidence says so

## Grounding rules

1. Facts only from tool evidence JSON.
2. Catalog `status=not_found` → say not found; if `similar_products` present, list under สินค้าใกล้เคียง + admin contact.
3. Out of stock / `can_fulfill=false` → use deterministic path in `_product_unavailable_with_similar_answer`:
   - ขออภัย
   - state product + หมดสต็อก
   - admin `1234567890` for the asked SKU
   - recommend in-stock `similar_products` (and other fulfillable matches)
4. KB miss for a named promo/fact → exact admin sentence (`_KB_NOT_FOUND_ANSWER`).
5. Pricing evidence (`pricing_engine` / `pricing_api`) → copy `subtotal` / `discount` / `total` as-is; never recompute.

## When adding behavior

1. Prefer deterministic Python for money, OOS templates, and admin lines.
2. Keep planner filters structured (`product_filters`, `quote_filters`) — no keyword-only routing.
3. Deduplicate tools in `_normalize_plan`; max ~4 steps.
4. Add/adjust tests in `backend/tests/test_shop_agent.py`.
5. Run: `uv run --project backend python -m unittest discover -s backend/tests -v`

## Product comparison answer order

1. เปรียบเทียบราคา  
2. คุณสมบัติ (from KB)  
3. แนะนำ  
4. ข้อควรระวัง (last; medical disclaimer sentence from prompt)

## Do not touch casually

- `frontend/backend/**` — duplicate/stale copy; edit root `backend/` only unless user asks otherwise.
