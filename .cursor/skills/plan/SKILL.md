---
name: plan
description: >-
  Break Glow Beauty work into small verifiable tasks with acceptance criteria
  and dependency order. Use before large changes to the agent, pricing, catalog,
  or multi-file features.
---

# Plan

Read any existing SPEC.md / README and the relevant code, then:

1. Stay read-only until the plan is accepted
2. Map dependencies (catalog → pricing → agent prompts → tests)
3. Slice **vertically** (one customer-visible path per task)
4. Each task needs: goal, files, acceptance criteria, verification command
5. Add checkpoints between phases
6. Present for human review before coding

Save to `tasks/plan.md` and `tasks/todo.md` when the user wants artifacts on disk.

## Vertical slice examples (this repo)

- OOS answer: catalog similar_products → synthesizer fallback → test
- Quote total: pricing engine rule → `calculate_pricing` tool → planner prompt → test
- New tool: repository → `@tool` → normalize/args → three prompts → tests → README
