# AI Engineer — Take-Home Assignment

Welcome, and thanks for your interest. This task is designed to take **about 4–6 hours of real work**. Please **don't over-polish** — we care about your thinking and working code, not a finished product.

> **Important:** You will walk us through this code live in the interview **and modify it in front of us**. Build something you fully understand. Submit at least **2 days before your interview** (within 1 week of receiving this).
>
> **AI tools are allowed and expected.** Use them as you would on the job.

---

## Context

Our platform lets Thai SMEs manage customer chats across LINE, Facebook, and Instagram. A **cosmetics merchant** wants an AI that auto-replies to customer questions about their products.

Real customers write in **informal Thai**, mix in English and emoji, and reference earlier messages (e.g. *"เอาตัวสีแดงเมื่อกี้"*). Your system has to cope with that.

---

## What's provided (`/data`)

| File | What it is |
|------|-----------|
| `catalog.csv` | Product catalog — ~30 SKUs with **price** and **stock**. This is the source of truth for anything about products. |
| `faq.md` | The shop's FAQ — shipping, payment, returns, etc. **Intentionally messy**, just like a real merchant would hand you. |
| `conversations.json` | Sample customer conversations for testing. Each ends on a customer message your bot should answer. |

> Treat `catalog.csv` as **live data**: prices and stock can change at any time. Don't bake them into your code or prompts.

---

## Part A — Build it

Build a service that takes a **customer message** (plus minimal conversation history) and returns a **reply grounded in the FAQ and catalog**.

**Minimum bar**
- Runs locally with a clear `README`/instructions — ideally **one command to start**.
- Answers **product** questions using the catalog; **general** questions using the FAQ.
- Quotes **prices and stock correctly** — never invents them.
- When it doesn't know, or shouldn't answer, it **says so and/or signals handoff to a human** instead of guessing.

**Free choices**
- Any language, stack, and libraries you like.
- CLI or a single HTTP endpoint is fine — **no UI required**.
- Any model/provider. If a key is needed, read it from an env var and document it; don't commit secrets.

### Expected behaviour (a few examples)

- *"ลิปแมตต์เบอร์ 3 ราคาเท่าไหร่"* → look up the right SKU and quote the **exact** price.
- *"กันแดดสเปรย์ยังมีของไหม"* → it's **out of stock**; say so, don't invent availability.
- *"ผ่อน 0% ได้ไหม"* → not covered by the FAQ; **don't guess** — say you're not sure / hand off.

---

## Part B — Decision log (required, ~1 page)

Keep a short running log as you build — **`DECISION_LOG.md`** (template provided). Cover:

1. Your architecture in a few sentences + one sketch (ASCII/diagram/photo of a whiteboard — anything).
2. Your **3 most important decisions**, the alternatives you rejected, and **why**.
3. Where you chose **not** to use an LLM, and why.
4. The single **biggest production risk** of this system, and how you'd mitigate it.
5. What you'd do **with another week** — and what you deliberately skipped.

We'll base much of the interview on this. Be ready to defend it.

---

## What to submit

A **git repo** (or zip) containing:
- your code,
- a `README` with run instructions,
- `DECISION_LOG.md`.

No slides. No write-up beyond the decision log.

---

## How we evaluate

We are **not** testing how much you can produce or recall. We're testing **judgment**: how you separate facts (price/stock) from language, how you ground answers, how you handle "I don't know," and how clearly you can explain *why*.

A sharp *"it depends, and here's why"* beats a confident generic answer. Good luck — we're looking forward to seeing how you think.
