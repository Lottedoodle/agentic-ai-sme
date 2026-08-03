---
name: test
description: >-
  TDD workflow for Glow Beauty Shop — failing tests first, Prove-It for bugs,
  unittest under backend/tests. Use when adding features, fixing bugs, or
  changing agent/pricing/catalog behavior.
---

# Test (TDD)

## Commands

```bash
# Full suite (preferred)
npm test
# or
uv run --project backend python -m unittest discover -s backend/tests -v

# Focused
uv run --project backend python -m unittest backend.tests.test_pricing -v
uv run --project backend python -m unittest backend.tests.test_shop_agent -v
```

Primary test modules:
- `backend/tests/test_shop_agent.py` — planner, tools, grounding, OOS
- `backend/tests/test_pricing.py` — quote math and API adapter

## New features

1. Write tests for expected behavior (**must FAIL**)
2. Implement until green
3. Refactor while staying green
4. Re-run full discover suite

## Bug fixes (Prove-It)

1. Add a test that reproduces the bug (**must FAIL**)
2. Confirm failure
3. Fix
4. Confirm pass + full suite

## Project-specific expectations

- Money: assert string amounts (`"580.00"`), not floats
- Agent: prefer testing deterministic helpers (`_normalize_plan`, `_tool_args_for_step`, synthesizer fallbacks) over live LLM calls
- Catalog/pricing: inject fakes/resolvers instead of requiring `DATABASE_URL` when possible

For browser-only UI bugs, use browser DevTools verification if available.
