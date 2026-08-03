---
name: add-agent-tool
description: >-
  Checklist for adding a new LangGraph agent tool in Glow Beauty Shop.
  Use when creating a new @tool, extending ToolName/PlanStep, or wiring
  planner/react/synthesizer for a new data source.
---

# Add an agent tool

Follow this order so the Plan → ReAct → Synthesizer loop stays grounded.

## 1. Repository / pure logic first

- Put side effects in `backend/repositories/` (or `backend/rag/`)
- Return **JSON-serializable** evidence with:
  - `source` (stable string)
  - `status`: `ok` | `error` | `not_found`
  - domain payload + `message`
- Prefer deterministic computation (money, stock checks) over LLM math
- Unit-test the repository without the LLM

## 2. Register the tool

In `backend/agent/graph.py`:

1. Add name to `ToolName` Literal
2. Extend `PlanStep` with structured fields if needed (like `product_filters` / `quote_filters`) — avoid free-text-only contracts for facts
3. Implement `@tool def ...` that calls the repository and returns a JSON string
4. Append to `AGENT_TOOLS` (rebinds `_react_llm`)

## 3. Plan args pipeline

1. `_normalize_plan` — sanitize/ground structured filters; dedupe by tool name
2. `_tool_args_for_step` — map plan step → tool kwargs (**forced**; do not trust ReAct-invented args for facts)
3. Bump step cap only if needed (`normalized[:4]`)

## 4. Prompts

Update all three:

| Prompt | Add |
|--------|-----|
| `PLANNER_PROMPT` | When to use the tool + few-shot structured filters |
| `REACT_PROMPT` | Tool boundary one-liner |
| `SYNTHESIZER_PROMPT` | How to read evidence; forbid inventing fields |

## 5. Tests

- Args mapping via `_tool_args_for_step`
- Normalize/sanitize behavior
- Synthesizer/deterministic fallback if the tool drives a fixed customer phrase
- Run: `uv run --project backend python -m unittest discover -s backend/tests -v`

## 6. Docs / env

- README tool table + example questions
- `.env.example` for any new backend URL/flag

## Anti-patterns

- Keyword-only routing in Python that fights the planner
- Letting ReAct pass unit prices or totals it invented
- Editing `frontend/backend/**` instead of root `backend/`
- Skipping `not_found` / `error` status handling in the synthesizer
