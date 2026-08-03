---
name: spec
description: >-
  Spec-driven development for Glow Beauty Shop — write a structured SPEC before
  coding new features. Use when starting a new capability (tools, pricing rules,
  KB flows) or when requirements are unclear.
---

# Spec

Before writing code, clarify:

1. Objective and who the customer is (shopper in chat)
2. Core behaviors + acceptance criteria
3. Stack constraints (LangGraph agent, Supabase products, Bedrock KB, Next.js UI)
4. Boundaries: always / ask first / never

Generate a SPEC covering: objective, commands, project structure, code style, testing, boundaries.

Save as `SPEC.md` at the repo root and confirm with the user before implementing.

## Boundaries to remember for this PoC

- Always: ground answers in tool evidence; Decimal for money; admin `1234567890` on KB/product misses when required
- Ask first: changing hardcoded promo rules, calling external quote API in prod, schema migrations
- Never: invent prices/stock; medical advice; commit `.env`; edit `frontend/backend/**` as source of truth
