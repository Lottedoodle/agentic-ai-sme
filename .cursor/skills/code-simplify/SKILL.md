---
name: code-simplify
description: >-
  Simplify Glow Beauty code for clarity without changing behavior. Use after
  features land or when graph.py / repositories become hard to follow.
---

# Code simplify

Simplify recently changed code (or a named scope) while preserving behavior:

1. Read project skills (`shop-agent`, `pricing-quote`) and surrounding tests
2. Identify target code
3. Understand callers, edge cases, and coverage before editing
4. Look for:
   - Deep nesting → guard clauses / helpers
   - Long functions → split by responsibility
   - Duplicated catalog/pricing parsing → shared helpers
   - Dead code → remove after confirming unused
5. Change incrementally; run tests after each step
6. Finish only when `unittest discover -s backend/tests` is green

Do not “simplify” away grounding checks, Decimal money paths, or deterministic OOS/admin templates.
