from __future__ import annotations

import json
import re
import uuid
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, Field

from backend.core.llm import create_chat_llm, message_content_to_text


ToolName = Literal[
    "search_product_catalog",
    "search_store_knowledge",
    "lookup_order_status",
    "calculate_pricing",
]
ProductField = Literal["sku", "name", "category", "shade", "price", "stock"]
_PRODUCT_NUMBER = re.compile(
    r"(?:เบอร์|number|no\.?)\s*0*(\d{1,3})",
    re.IGNORECASE,
)
_PRODUCT_NUMBER_MENTION = re.compile(r"(?:เบอร์|number|no\.?)", re.IGNORECASE)
_NUMERIC_NAME = re.compile(r"^0*\d{1,3}$")
_LATIN_NAME_ONLY = re.compile(r"^[A-Za-z][A-Za-z\s'-]*$")
_THAI_RUN = re.compile(r"[\u0E00-\u0E7F]+")
_REFERENCE_SIGNAL = re.compile(
    r"เมื่อกี้|เมื่อก่อน|ตัวนั้น|อันนั้น|ชิ้นนั้น|ตัวสี|สีเดิม|the one|that one|previous",
    re.IGNORECASE,
)
_GENERIC_CATALOG_TOKENS = {
    "เบอร์",
    "สี",
    "ชิ้น",
    "กล่อง",
    "ขวด",
    "แท่ง",
    "shade",
    "number",
}
# Language synonyms for color-family tokens that appear in live shade names.
# Not product-specific; only used to detect ambiguous references.
_COLOR_FAMILY_ALIASES: dict[str, tuple[str, ...]] = {
    "red": ("red", "แดง"),
    "pink": ("pink", "rose", "ชมพู"),
    "orange": ("orange", "ส้ม"),
    "peach": ("peach", "พีช"),
    "beige": ("beige", "nude", "นู้ด", "เบจ"),
    "black": ("black", "ดำ"),
    "berry": ("berry", "เบอร์รี", "เบอร์รี่"),
    "coral": ("coral", "คอรัล"),
    "cherry": ("cherry", "เชอร์รี", "เชอร์รี่"),
}


class ProductSearchFilters(BaseModel):
    """Structured SQL filters extracted by the planner."""

    sku: str | None = None
    name: str | None = None
    category: str | None = None
    shade: str | None = None
    in_stock_only: bool = False
    requested_qty: int | None = Field(default=None, ge=1)
    requested_fields: list[ProductField] = Field(default_factory=list)


class QuoteLineItemPlan(BaseModel):
    """One priced line for calculate_pricing (catalog identity + quantity)."""

    sku: str | None = None
    name: str | None = None
    category: str | None = None
    shade: str | None = None
    qty: int = Field(default=1, ge=1)


class QuoteFilters(BaseModel):
    """Structured quote input — same shape as the pricing quote API contract."""

    line_items: list[QuoteLineItemPlan] = Field(default_factory=list, max_length=10)


class PlanStep(BaseModel):
    """One grounded lookup required to answer the customer."""

    tool: ToolName
    query: str = Field(
        default="",
        description=(
            "Free-text query for search_store_knowledge; original question for "
            "product/order fallback"
        ),
    )
    product_filters: ProductSearchFilters | None = Field(
        default=None,
        description="Required when tool=search_product_catalog",
    )
    quote_filters: QuoteFilters | None = Field(
        default=None,
        description="Required when tool=calculate_pricing",
    )
    order_id: str | None = Field(
        default=None,
        description="Optional order id / tracking number when tool=lookup_order_status",
    )
    purpose: str = Field(description="Why this lookup is needed")


class ExecutionPlan(BaseModel):
    """Plan produced before the ReAct reasoning/action loop."""

    intent: Literal["product_data", "store_knowledge", "order_status", "mixed"]
    summary: str
    steps: list[PlanStep] = Field(default_factory=list, max_length=4)
    needs_user_input: bool = False
    clarification_options: list[str] = Field(default_factory=list)


class SynthesisResult(BaseModel):
    """Answer plus the verifier's grounding checks."""

    answer: str
    addresses_question: bool
    grounded_in_sources: bool
    missing_information: list[str] = Field(default_factory=list)


class AgentState(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    user_input: str
    conversation_summary: str
    recent_conversation: str
    intent: str
    plan: list[dict]
    plan_summary: str
    route_mode: str
    route_reason: str
    audit_log: list[str]
    execution_result: str
    clarifying_question: str
    needs_user_input: bool
    clarification_options: list[str]
    next_step: str
    verification: dict


PLANNER_PROMPT = """\
You are the planning node for Glow Beauty Shop. Build a short, grounded execution plan.

Available tools:
1. search_product_catalog
   Use ONLY for facts stored in the Supabase product table:
   SKU, product list/catalog, stock/quantity/availability, colors, and prices.
2. search_store_knowledge
   Use ONLY for the AWS Knowledge Base:
   promotions, product properties/benefits/how-to-use, and store information/policies/FAQ.
3. lookup_order_status
   Use ONLY for customer order / shipment status (mock order store):
   order id, packing/shipping status, Kerry tracking number, and Kerry tracking URL.
4. calculate_pricing
   Use for cart totals / "ราคารวม" / "คิดเงิน" / quantity × price / discount after purchase
   threshold. Fill quote_filters.line_items with sku/name/category/shade + qty.
   This tool resolves catalog unit prices itself — never invent unit prices.

Routing rules:
- SKU, stock, products sold, colors, unit price lookup -> search_product_catalog.
- Cart total / รวมราคา / กี่บาทถ้าซื้อ N ชิ้น / ได้ส่วนลดไหมจากยอดซื้อ
  -> calculate_pricing (and optionally search_product_catalog first for stock).
- Promotion copy / FAQ / product properties -> search_store_knowledge.
  Do NOT use KB to compute numeric discounts or totals.
- Order status / tracking / "พัสดุถึงไหน" / "ออเดอร์ของฉัน" / Kerry tracking
  -> lookup_order_status (intent=order_status). Do NOT use product catalog or KB for this.
- If the customer provides an order id (e.g. GB-1001) or Kerry tracking number, set order_id.
- If they ask about their order status without an id, still plan lookup_order_status with
  order_id empty; the tool returns the mock default customer order.
- If the question contains both categories, use both tools in separate steps.
- Product comparison / "อันไหนดีกว่า" / "ต่างกันยังไง" questions that need both
  price/stock and product traits: plan search_product_catalog for price/stock AND
  search_store_knowledge for product properties/benefits of each item compared.
  For the knowledge step, query product names/traits (e.g. "Vitamin C serum Hyaluronic
  serum คุณสมบัติ ลักษณะเด่น") — do not make the knowledge query only about
  sensitive skin / medical suitability, or retrieval will miss product properties.
- Do not route SKU/stock/color/price to the knowledge base.
- Do not route promotions/store policy to the SQL product catalog.
- Do not route order/shipping status to product catalog or knowledge base.
- For search_product_catalog, ALWAYS fill product_filters. Do not rely on free-text keywords.
- Use the supplied live catalog metadata (category_values, shade_values, sample_products)
  to choose canonical category/shade/name fragments that actually exist in the catalog.
- Use category for a product family. Never invent English product paraphrases in name.
- When the customer refers to a model/shade number (เบอร์ / number / no.), put the
  zero-padded digits in name (e.g. "03") and set category from live metadata/samples.
- Never invent a product/shade number. Only use digits that appear in the customer message.
  If they say เบอร์ without a number, do not guess (do not pick 01/05/etc.).
- Preserve exact SKU and product entities from the current or recent conversation.
- Resolve references such as a prior item, shade, or model from recent conversation semantically,
  in either Thai or English, using sample_products / shade_values as the source of truth.
- If the customer's shade/color reference matches multiple recent shades, set
  needs_user_input=true, put the candidate canonical shade names in clarification_options,
  leave shade empty, and use an empty steps list. Do not guess which shade they meant.
- If the customer requests a quantity, plan a stock lookup and keep the requested quantity
  in requested_qty so the final answer can compare it with stock_qty.
- If they ask for a total / รวม / คิดเงิน / ส่วนลดจากยอด, ALSO plan calculate_pricing with
  quote_filters.line_items (same identity filters + qty). Prefer SKU when known.
- requested_fields must contain only the fields needed to answer the question.
- Never answer the customer in this node. Output only the structured plan.

Few-shot examples (patterns only — do not memorize these as customer questions):

Example A
Customer: "เช็ก SKU SUN-001 ให้หน่อยว่าราคาเท่าไรและพอส่ง 3 ชิ้นไหม"
Product filters:
{"sku":"SUN-001","requested_qty":3,"requested_fields":["price","stock"]}

Example B
Customer: "ขอดูเฉดและราคาของคุชชั่นทั้งหมด"
Live catalog metadata contains category "cushion".
Product filters:
{"category":"cushion","requested_fields":["name","shade","price","stock"]}

Example C
Recent conversation names a foundation shade "C2 Natural".
Customer: "ขอเฉดธรรมชาติที่พูดถึงก่อนหน้า 2 ขวด"
Product filters:
{"category":"foundation","shade":"C2 Natural","requested_qty":2,"requested_fields":["name","stock"]}

Example D
Customer: "มาสคาร่าเบอร์ 1 ราคาเท่าไร"
sample_products include a mascara named with "เบอร์ 01".
Product filters:
{"category":"mascara","name":"01","requested_fields":["sku","name","price","stock"]}

Example E
Customer: "อายแชโดว์มีเฉดอะไรบ้าง"
Live catalog metadata contains category "eyeshadow".
Product filters:
{"category":"eyeshadow","requested_fields":["name","shade","stock"]}

Example F
Recent conversation listed two cushion shades that share a color family token.
Customer refers vaguely to that color without naming one shade.
Plan:
{"needs_user_input":true,"clarification_options":["21 Light","23 Natural"],"steps":[]}

Example G
Customer: "ออเดอร์ GB-1001 ส่งถึงไหนแล้วคะ"
Plan:
{"intent":"order_status","steps":[{"tool":"lookup_order_status","order_id":"GB-1001","purpose":"ตรวจสถานะจัดส่งและลิงก์ Kerry"}]}

Example H
Customer: "พัสดุของฉันถึงไหนแล้ว"
Plan:
{"intent":"order_status","steps":[{"tool":"lookup_order_status","order_id":null,"purpose":"ดึงสถานะออเดอร์ mock ของลูกค้า"}]}

Example I
Customer: "ลิปแมตต์เบอร์ 1 ขอ 2 แท่ง ราคารวมเท่าไหร่ ได้ส่วนลดไหม"
Plan steps:
1) search_product_catalog with product_filters
{"category":"lipstick","name":"01","requested_qty":2,"requested_fields":["sku","name","price","stock"]}
2) calculate_pricing with quote_filters
{"line_items":[{"category":"lipstick","name":"01","qty":2}]}
"""

REACT_PROMPT = """\
You are the Reasoning and Action node for Glow Beauty Shop.

Follow the supplied plan and use the tools to collect evidence before drafting an answer.
Tool boundaries are strict:
- search_product_catalog: use structured SKU/name/category/shade/quantity filters from the plan.
- search_store_knowledge: promotions, product properties, store information/policies.
- lookup_order_status: order/shipment status, Kerry tracking number and tracking URL.
- calculate_pricing: cart subtotal/discount/total from quote_filters; never invent money math.

Rules:
- Call every tool required by the plan, but do not call unrelated tools.
- If the plan has needs_user_input=true, do not call tools. Draft nothing factual; the
  Synthesizer will ask the customer to clarify using clarification_options.
- For product comparisons, gather both catalog facts (price/stock) and Knowledge Base
  product properties for each item when the plan requires both.
- Never invent facts.
- A tool result with status=not_found means the requested data does not exist in that source.
- A tool result with status=error means the source could not be verified.
- Your draft is internal; the Synthesizer/Verifier node produces the customer-facing answer.
- Do not draft medical advice or clinical suitability claims.
- Do not compute totals/discounts yourself; rely on calculate_pricing evidence.
"""

SYNTHESIZER_PROMPT = """\
You are the final Synthesizer and Verifier for Glow Beauty Shop.

Given the customer's question, execution plan, internal draft, and tool evidence:
1. Answer the exact question in natural, concise Thai.
2. Use ONLY facts explicitly present in tool evidence.
3. For SKU/product/stock/color/price, SQL evidence is the only source of truth.
4. For promotion/product properties/store information, Knowledge Base evidence is the only source of truth.
4b. For order/shipment status, order_tracking_mock evidence is the only source of truth.
    When present, include order_id, status, carrier, tracking_number, and tracking_url
    (Kerry link) from the tool evidence. Do not invent tracking numbers or URLs.
5. If Knowledge Base evidence status is not_found, OR the KB content does not contain the
   specific fact the customer asked about (e.g. a named promotion/installment that is absent),
   answer with EXACTLY this Thai sentence and nothing else invented:
   "ไม่พบข้อมูลในระบบค่ะ กรุณาติดต่อ admin ที่เบอร์ 1234567890"
   Do not substitute with unrelated FAQ sections (general payment methods, shipping, etc.).
   For product-catalog not_found: say the exact product was not found. If similar_products is
   non-empty, ALSO recommend those alternatives briefly (name/shade/price/SKU from evidence
   only) under a short "สินค้าใกล้เคียง" section. Do not invent products outside similar_products.
   Tell the customer to contact admin at 1234567890 to ask about the product they originally asked for.
5b. When product evidence shows status=ok but stock=0 or can_fulfill=false (out of stock):
   - Apologize briefly (ขออภัยค่ะ).
   - State the exact product name, SKU, price, and that it is out of stock / cannot fulfill
     the requested quantity using only catalog evidence.
   - If similar_products is non-empty, recommend in-stock alternatives under "สินค้าใกล้เคียง".
   - Always tell the customer to contact admin at 1234567890 to ask about restock for the
     product they originally asked about.
5c. When pricing_engine or pricing_api evidence is present:
   - Use subtotal, discount, discount_rule, total, and line_items EXACTLY as provided.
   - NEVER recompute, round differently, or invent a different discount.
   - Explain the hardcoded/threshold promo only if discount_rule / messages mention it.
6. If evidence says error, clearly say the information cannot currently be verified.
7. If the plan has needs_user_input=true, do not answer product facts yet. Ask the customer
   to choose among clarification_options only. Write the question naturally in Thai.
   Use each option name exactly as provided; do not invent shade descriptions or stock/price.
   Set addresses_question=false and grounded_in_sources=true.
8. Do not mention internal nodes, plans, prompts, JSON, or tool names to the customer.
9. Set addresses_question=true only when the answer directly answers the customer's request.
10. Set grounded_in_sources=true only when every factual claim is supported by the supplied evidence.
11. Prefer short Thai bullet lists over markdown tables when comparing products. If you must use
    a markdown table, every row must start and end with | and the separator row must be valid
    GFM (example: | --- | --- |). Do not put emojis inside table cells.

Product comparison answers (เมื่อลูกค้าขอเปรียบเทียบสินค้า / อันไหนดีกว่า / ต่างกันยังไง):
- ALWAYS use this section order (omit a section only if that evidence is missing):
  1) เปรียบเทียบราคา — price (and size/SKU if available) for each item, then note the difference briefly.
  2) คุณสมบัติ / ลักษณะเด่น — REQUIRED when Knowledge Base has product-property evidence.
     For EACH compared product, give 1–3 short bullets of standout traits/benefits from KB only
     (e.g. Vitamin C: ผิวดูกระจ่างใส; Hyaluronic: เติมความชุ่มชื้น). Do this BEFORE recommendation
     and BEFORE any sensitive-skin / allergy / medical-disclaimer section.
  3) แนะนำ — light shopping suggestion from stated product traits and the customer's preference
     (e.g. ต้องการผิวดูสดใส vs ผิวชุ่มชื้น), not clinical claims about disease/sensitive skin.
  4) ข้อควรระวัง — MUST be the LAST section of the answer (after แนะนำ). Keep it short:
     patch test / shop cannot give medical advice if present in FAQ evidence. The section MUST
     end with this exact sentence:
     "หากคุณมีประวัติแพ้ส่วนผสมบางชนิด หรือมีโรคผิวหนัง ควรปรึกษาแพทย์หรือเภสัชกรก่อนใช้ผลิตภัณฑ์"
     Do NOT put ข้อควรระวัง before แนะนำ. Do NOT replace the properties section with this disclaimer.
- Do NOT give medical advice: do not diagnose, prescribe, claim treatment/cure, or say a product
  is "safe/suitable for sensitive skin / eczema / allergy" unless that exact claim appears in
  Knowledge Base evidence.
- Never invent benefits, ingredients, or suitability claims missing from tool evidence.
- If KB has product properties, skipping section 2 is incorrect even when the customer also
  asked about sensitive skin.

If information is incomplete, answer only the verified portion and list missing_information.
"""

def build_llm_user_context(state: AgentState) -> str:
    parts: list[str] = []
    summary = (state.get("conversation_summary") or "").strip()
    recent = (state.get("recent_conversation") or "").strip()
    if summary:
        parts.append(f"[สรุปการสนทนาก่อนหน้า]\n{summary}")
    if recent:
        parts.append(f"[ข้อความล่าสุด]\n{recent}")
    parts.append(f"[คำถามปัจจุบัน]\n{state.get('user_input', '')}")
    return "\n\n".join(parts)


@tool
def search_product_catalog(
    query: str = "",
    sku: str | None = None,
    name: str | None = None,
    category: str | None = None,
    shade: str | None = None,
    in_stock_only: bool = False,
    requested_qty: int | None = None,
    requested_fields: list[str] | None = None,
) -> str:
    """Search Supabase products with structured catalog filters."""
    from backend.repositories.product_catalog import search_products

    return search_products(
        query,
        sku=sku,
        name=name,
        category=category,
        shade=shade,
        in_stock_only=in_stock_only,
        requested_qty=requested_qty,
        requested_fields=requested_fields,
    )


@tool
def search_store_knowledge(query: str) -> str:
    """Search Glow Beauty Shop knowledge for promotions, product properties, and store FAQs."""
    from backend.rag.knowledge_base import search_store_knowledge as kb_search

    result = kb_search(query)
    if result.startswith("[Knowledge Base error]"):
        status = "error"
    elif result.startswith("ไม่พบเอกสาร"):
        status = "not_found"
    else:
        status = "ok"
    return json.dumps(
        {
            "source": "glow_beauty_knowledge_base",
            "status": status,
            "query": query,
            "content": result,
        },
        ensure_ascii=False,
    )


@tool
def lookup_order_status(
    order_id: str | None = None,
    query: str = "",
) -> str:
    """Look up mock customer order / shipment status and Kerry Express tracking URL."""
    from backend.repositories.order_tracking import lookup_order

    return lookup_order(order_id, query=query)


@tool
def calculate_pricing(
    line_items: list[dict] | None = None,
    sku: str | None = None,
    name: str | None = None,
    category: str | None = None,
    shade: str | None = None,
    qty: int | None = None,
    query: str = "",
) -> str:
    """Compute subtotal, threshold discount, and total from catalog unit prices.

    Uses the shared quote interface (local engine now; API quote when configured).
    """
    from backend.repositories.pricing import calculate_quote

    return calculate_quote(
        line_items=line_items,
        sku=sku,
        name=name,
        category=category,
        shade=shade,
        qty=qty,
        query=query,
    )


AGENT_TOOLS = [
    search_product_catalog,
    search_store_knowledge,
    lookup_order_status,
    calculate_pricing,
]
TOOL_BY_NAME = {item.name: item for item in AGENT_TOOLS}
_llm = create_chat_llm()
_planner = _llm.with_structured_output(ExecutionPlan, method="function_calling")
_react_llm = _llm.bind_tools(AGENT_TOOLS)
_synthesizer = _llm.with_structured_output(SynthesisResult, method="function_calling")


def _fallback_plan(question: str) -> ExecutionPlan:
    return ExecutionPlan(
        intent="mixed",
        summary="Planner unavailable; verify against both trusted sources",
        steps=[
            PlanStep(
                tool="search_product_catalog",
                query=question,
                product_filters=ProductSearchFilters(),
                purpose="ตรวจสอบข้อมูลสินค้าใน Supabase แบบไม่เดา keyword",
            ),
            PlanStep(
                tool="search_store_knowledge",
                query=question,
                purpose="ตรวจสอบข้อมูลร้านจาก Knowledge Base",
            ),
        ],
        needs_user_input=False,
        clarification_options=[],
    )


def _product_number_from_text(text: str) -> str | None:
    match = _PRODUCT_NUMBER.search(text or "")
    if not match:
        return None
    return f"{int(match.group(1)):02d}"


def _mentions_product_number_without_digits(question: str) -> bool:
    """True when the customer referenced เบอร์/number but provided no digits."""
    text = question or ""
    return bool(_PRODUCT_NUMBER_MENTION.search(text)) and not _product_number_from_text(
        text
    )


def _infer_category_from_samples(question: str, samples: list[dict[str, Any]]) -> str | None:
    """Map Thai/English product fragments in the question to a live category via samples."""
    q = (question or "").casefold()
    if not q or not samples:
        return None

    question_runs = _THAI_RUN.findall(question)
    best_category: str | None = None
    best_score = 0
    tied = False
    for sample in samples:
        category = sample.get("category")
        name = str(sample.get("name") or "")
        if not category or not name:
            continue
        score = 0
        for token in re.findall(r"[A-Za-z0-9_-]{3,}", name.casefold()):
            if token in _GENERIC_CATALOG_TOKENS:
                continue
            if token in q:
                score = max(score, len(token))
        for name_run in _THAI_RUN.findall(name):
            if name_run in _GENERIC_CATALOG_TOKENS:
                continue
            for question_run in question_runs:
                common = 0
                for left, right in zip(question_run, name_run):
                    if left != right:
                        break
                    common += 1
                if common >= 3:
                    score = max(score, common)
        if score > best_score:
            best_score = score
            best_category = str(category)
            tied = False
        elif score and score == best_score and str(category) != best_category:
            tied = True
    if tied or best_score < 3:
        return None
    return best_category


def _name_exists_in_samples(name: str, samples: list[dict[str, Any]]) -> bool:
    needle = name.casefold().strip()
    if not needle:
        return False
    for sample in samples:
        haystack = str(sample.get("name") or "").casefold()
        if needle in haystack:
            return True
    return False


def _shade_tokens(shade: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[A-Za-z]{3,}", (shade or "").casefold())
        if token not in _GENERIC_CATALOG_TOKENS
    }


def _shades_mentioned_in_text(text: str, shade_values: list[str]) -> list[str]:
    haystack = text or ""
    lower = haystack.casefold()
    hits: list[tuple[int, str]] = []
    for shade in shade_values:
        if not shade or shade == "-" or len(shade) < 2:
            continue
        index = lower.find(shade.casefold())
        if index >= 0:
            hits.append((index, shade))
    hits.sort(key=lambda item: (item[0], -len(item[1])))
    return list(dict.fromkeys(shade for _, shade in hits))


def _question_selects_shade(
    question: str,
    candidates: list[str],
    samples: list[dict[str, Any]],
) -> str | None:
    """Return a candidate when the current question uniquely identifies it."""
    q = (question or "").casefold()
    exact = [shade for shade in candidates if shade.casefold() in q]
    if len(exact) == 1:
        return exact[0]

    unique_hits: list[str] = []
    for shade in candidates:
        own = _shade_tokens(shade)
        others: set[str] = set()
        for other in candidates:
            if other != shade:
                others |= _shade_tokens(other)
        distinguishing = own - others
        if any(token in q for token in distinguishing):
            unique_hits.append(shade)
        else:
            for family, aliases in _COLOR_FAMILY_ALIASES.items():
                if family not in distinguishing:
                    continue
                if any(alias.casefold() in q for alias in aliases):
                    unique_hits.append(shade)
                    break
    if len(unique_hits) == 1:
        return unique_hits[0]

    product_number = _product_number_from_text(question)
    if product_number:
        numbered = [
            shade
            for shade in candidates
            for sample in samples
            if str(sample.get("shade") or "") == shade
            and product_number in str(sample.get("name") or "")
        ]
        numbered = list(dict.fromkeys(numbered))
        if len(numbered) == 1:
            return numbered[0]
    return None


def _color_families_in_question(question: str) -> set[str]:
    q = (question or "").casefold()
    families: set[str] = set()
    for family, aliases in _COLOR_FAMILY_ALIASES.items():
        if any(alias.casefold() in q for alias in aliases):
            families.add(family)
    return families


def _ambiguous_shade_candidates(
    question: str,
    recent_context: str,
    planned_shade: str | None = None,
) -> list[str]:
    """Detect vague shade references that match multiple recently mentioned shades."""
    metadata: dict[str, Any] = {}
    try:
        from backend.repositories.product_catalog import get_product_catalog_metadata

        metadata = get_product_catalog_metadata() or {}
    except Exception:
        metadata = {}

    shade_values = [str(value) for value in metadata.get("shade_values") or []]
    samples = list(metadata.get("sample_products") or [])
    recent_shades = _shades_mentioned_in_text(recent_context, shade_values)
    if len(recent_shades) < 2:
        return []

    if _question_selects_shade(question, recent_shades, samples):
        return []

    families_in_question = _color_families_in_question(question)
    referential = bool(_REFERENCE_SIGNAL.search(question or ""))

    candidates: list[str] = []
    if planned_shade and planned_shade in recent_shades:
        planned_tokens = _shade_tokens(planned_shade)
        candidates = [
            shade
            for shade in recent_shades
            if _shade_tokens(shade) & planned_tokens
        ]
    if len(candidates) < 2 and families_in_question:
        family_matches: list[str] = []
        for shade in recent_shades:
            tokens = _shade_tokens(shade)
            if tokens & families_in_question:
                family_matches.append(shade)
        if len(family_matches) >= 2:
            candidates = family_matches
    if len(candidates) < 2 and referential and families_in_question:
        candidates = [
            shade
            for shade in recent_shades
            if _shade_tokens(shade) & families_in_question
        ]
    if len(candidates) < 2:
        return []
    appearance = {shade: index for index, shade in enumerate(recent_shades)}
    return sorted(
        dict.fromkeys(candidates),
        key=lambda shade: appearance.get(shade, len(appearance)),
    )


def _sanitize_product_filters(
    question: str,
    filters: ProductSearchFilters | None,
    recent_context: str = "",
) -> ProductSearchFilters:
    """Keep structured filters grounded in live catalog values, not translated keywords."""
    cleaned = (filters or ProductSearchFilters()).model_copy(deep=True)
    metadata: dict[str, Any] = {}
    try:
        from backend.repositories.product_catalog import get_product_catalog_metadata

        metadata = get_product_catalog_metadata() or {}
    except Exception:
        metadata = {}

    samples = list(metadata.get("sample_products") or [])
    shade_values = [str(value) for value in metadata.get("shade_values") or []]
    category_values = {
        str(value).casefold(): str(value)
        for value in metadata.get("category_values") or []
    }

    if cleaned.category:
        canonical = category_values.get(cleaned.category.casefold())
        cleaned.category = canonical
    if not cleaned.category:
        cleaned.category = _infer_category_from_samples(question, samples)

    if cleaned.shade:
        shade_lookup = {value.casefold(): value for value in shade_values}
        cleaned.shade = shade_lookup.get(cleaned.shade.casefold(), cleaned.shade)

    if cleaned.name and _LATIN_NAME_ONLY.fullmatch(cleaned.name.strip()):
        if not _name_exists_in_samples(cleaned.name, samples) and not any(
            cleaned.name.casefold() in shade.casefold() for shade in shade_values
        ):
            cleaned.name = None

    product_number = _product_number_from_text(question)
    # Never keep LLM-invented numeric name filters that are not in the question.
    if cleaned.name and _NUMERIC_NAME.fullmatch(cleaned.name.strip()):
        if product_number:
            cleaned.name = product_number
        else:
            cleaned.name = None

    if product_number and not cleaned.sku:
        cleaned.name = product_number
        if not cleaned.category:
            matched_categories = {
                str(sample.get("category"))
                for sample in samples
                if product_number in str(sample.get("name") or "")
                and sample.get("category")
            }
            if len(matched_categories) == 1:
                cleaned.category = matched_categories.pop()
    elif _mentions_product_number_without_digits(question) and not cleaned.sku:
        # Force a catalog miss instead of listing unrelated products / inventing a number.
        cleaned.sku = "MISSING-PRODUCT-NUMBER"
        cleaned.name = None
        cleaned.shade = None

    if cleaned.requested_fields:
        cleaned.requested_fields = list(dict.fromkeys(cleaned.requested_fields))
    return cleaned


_QTY_IN_QUESTION = re.compile(
    r"(?:ขอ|เอา|อยากได้|จำนวน)?\s*(\d{1,3})\s*(?:ชิ้น|แท่ง|ขวด|กล่อง|อัน|ชุด)",
    re.IGNORECASE,
)


def _qty_from_question(question: str) -> int | None:
    match = _QTY_IN_QUESTION.search(question or "")
    if not match:
        return None
    qty = int(match.group(1))
    return qty if qty >= 1 else None


def _sanitize_quote_filters(
    question: str,
    filters: QuoteFilters | None,
    recent_context: str = "",
) -> QuoteFilters:
    """Ground quote line identity filters; keep qty from plan or question."""
    source = filters or QuoteFilters()
    qty_fallback = _qty_from_question(question) or 1
    lines: list[QuoteLineItemPlan] = []

    raw_lines = list(source.line_items or [])
    if not raw_lines:
        # Fall back to a catalog step's filters when planner omitted quote lines.
        return QuoteFilters(line_items=[])

    for raw in raw_lines:
        as_product = _sanitize_product_filters(
            question,
            ProductSearchFilters(
                sku=raw.sku,
                name=raw.name,
                category=raw.category,
                shade=raw.shade,
            ),
            recent_context,
        )
        qty = raw.qty if raw.qty and raw.qty >= 1 else qty_fallback
        if not any([as_product.sku, as_product.name, as_product.category, as_product.shade]):
            continue
        lines.append(
            QuoteLineItemPlan(
                sku=as_product.sku,
                name=as_product.name,
                category=as_product.category,
                shade=as_product.shade,
                qty=qty,
            )
        )
    return QuoteFilters(line_items=lines)


def _quote_step_from_product_filters(
    question: str,
    product_filters: ProductSearchFilters,
    *,
    planned_quote: QuoteFilters | None,
    purpose: str,
    recent_context: str = "",
) -> PlanStep | None:
    qty = product_filters.requested_qty or _qty_from_question(question) or 1
    seed = planned_quote or QuoteFilters(
        line_items=[
            QuoteLineItemPlan(
                sku=product_filters.sku,
                name=product_filters.name,
                category=product_filters.category,
                shade=product_filters.shade,
                qty=qty,
            )
        ]
    )
    # Ensure identity comes from grounded product filters when quote lines are thin.
    if seed.line_items:
        first = seed.line_items[0]
        seed = QuoteFilters(
            line_items=[
                QuoteLineItemPlan(
                    sku=first.sku or product_filters.sku,
                    name=first.name or product_filters.name,
                    category=first.category or product_filters.category,
                    shade=first.shade or product_filters.shade,
                    qty=first.qty if first.qty >= 1 else qty,
                ),
                *seed.line_items[1:],
            ]
        )
    cleaned = _sanitize_quote_filters(question, seed, recent_context)
    if not cleaned.line_items:
        return None
    return PlanStep(
        tool="calculate_pricing",
        query=question,
        quote_filters=cleaned,
        purpose=purpose,
    )


def _normalize_plan(
    plan: ExecutionPlan,
    question: str,
    recent_context: str = "",
) -> ExecutionPlan:
    """Normalize tool contracts without keyword-based intent or entity mappings."""
    if _mentions_product_number_without_digits(question):
        return ExecutionPlan(
            intent=plan.intent or "product_data",
            summary=plan.summary,
            steps=[
                PlanStep(
                    tool="search_product_catalog",
                    query=question,
                    product_filters=ProductSearchFilters(
                        sku="MISSING-PRODUCT-NUMBER",
                        requested_fields=["sku", "name", "price", "stock"],
                    ),
                    purpose="Product number missing/invalid; confirm not found in catalog",
                )
            ],
            needs_user_input=False,
            clarification_options=[],
        )

    product_number = _product_number_from_text(question)
    if product_number:
        planned_filters = next(
            (
                step.product_filters
                for step in plan.steps
                if step.tool == "search_product_catalog" and step.product_filters
            ),
            ProductSearchFilters(),
        )
        grounded = _sanitize_product_filters(question, planned_filters, recent_context)
        grounded.name = product_number
        grounded.sku = None
        steps = [
            PlanStep(
                tool="search_product_catalog",
                query=question,
                product_filters=grounded,
                purpose=(
                    next(
                        (
                            step.purpose
                            for step in plan.steps
                            if step.tool == "search_product_catalog"
                        ),
                        "Lookup product number in catalog",
                    )
                ),
            )
        ]
        wants_pricing = any(step.tool == "calculate_pricing" for step in plan.steps)
        asks_total = any(
            token in (question or "")
            for token in ("ราคารวม", "รวมเท่า", "คิดเงิน", "ส่วนลด", "เท่าไหร่ทั้งหมด")
        )
        if wants_pricing or asks_total:
            planned_quote = next(
                (
                    step.quote_filters
                    for step in plan.steps
                    if step.tool == "calculate_pricing"
                ),
                None,
            )
            pricing_purpose = next(
                (
                    step.purpose
                    for step in plan.steps
                    if step.tool == "calculate_pricing"
                ),
                "คิดราคารวมและส่วนลดจากยอดซื้อ",
            )
            quote_step = _quote_step_from_product_filters(
                question,
                grounded,
                planned_quote=planned_quote,
                purpose=pricing_purpose,
                recent_context=recent_context,
            )
            if quote_step:
                steps.append(quote_step)
        return ExecutionPlan(
            intent=plan.intent or "product_data",
            summary=plan.summary,
            steps=steps,
            needs_user_input=False,
            clarification_options=[],
        )

    if plan.needs_user_input and plan.clarification_options:
        options = list(dict.fromkeys(plan.clarification_options))
        return ExecutionPlan(
            intent=plan.intent,
            summary=plan.summary,
            steps=[],
            needs_user_input=True,
            clarification_options=options,
        )

    normalized: list[PlanStep] = []
    seen_tools: set[str] = set()
    planned_shade: str | None = None
    for step in plan.steps:
        if step.tool in seen_tools:
            continue
        seen_tools.add(step.tool)
        product_filters = None
        quote_filters = None
        order_id = None
        if step.tool == "search_product_catalog":
            product_filters = _sanitize_product_filters(
                question,
                step.product_filters,
                recent_context,
            )
            planned_shade = product_filters.shade
        elif step.tool == "calculate_pricing":
            quote_filters = _sanitize_quote_filters(
                question,
                step.quote_filters,
                recent_context,
            )
            if not quote_filters.line_items:
                catalog_filters = next(
                    (
                        candidate.product_filters
                        for candidate in plan.steps
                        if candidate.tool == "search_product_catalog"
                        and candidate.product_filters
                    ),
                    None,
                )
                if catalog_filters:
                    grounded_catalog = _sanitize_product_filters(
                        question,
                        catalog_filters,
                        recent_context,
                    )
                    rebuilt = _quote_step_from_product_filters(
                        question,
                        grounded_catalog,
                        planned_quote=step.quote_filters,
                        purpose=step.purpose,
                        recent_context=recent_context,
                    )
                    if rebuilt and rebuilt.quote_filters:
                        quote_filters = rebuilt.quote_filters
            if not quote_filters.line_items:
                continue
        elif step.tool == "lookup_order_status":
            from backend.repositories.order_tracking import extract_order_id

            order_id = (step.order_id or "").strip() or extract_order_id(question)
        normalized.append(
            PlanStep(
                tool=step.tool,
                query=question,
                product_filters=product_filters,
                quote_filters=quote_filters,
                order_id=order_id,
                purpose=step.purpose,
            )
        )

    ambiguous = _ambiguous_shade_candidates(question, recent_context, planned_shade)
    if ambiguous:
        return ExecutionPlan(
            intent=plan.intent or "product_data",
            summary=plan.summary,
            steps=[],
            needs_user_input=True,
            clarification_options=ambiguous,
        )

    if not normalized:
        return _fallback_plan(question)
    return ExecutionPlan(
        intent=plan.intent,
        summary=plan.summary,
        steps=normalized[:4],
        needs_user_input=False,
        clarification_options=[],
    )


def _catalog_metadata_context() -> str:
    """Expose live canonical values to the planner instead of hardcoding mappings."""
    try:
        from backend.repositories.product_catalog import get_product_catalog_metadata

        metadata = get_product_catalog_metadata()
        if not metadata:
            return ""
        return (
            "\n\n[Live product catalog metadata]\n"
            + json.dumps(metadata, ensure_ascii=False)
        )
    except Exception:
        return ""


def planner_node(state: AgentState) -> dict:
    question = state.get("user_input", "").strip()
    recent = state.get("recent_conversation", "")
    try:
        plan = _planner.invoke(
            [
                SystemMessage(content=PLANNER_PROMPT),
                HumanMessage(
                    content=build_llm_user_context(state) + _catalog_metadata_context()
                ),
            ]
        )
        plan = _normalize_plan(plan, question, recent)
        reason = "LLM plan validated against deterministic source-routing rules"
    except Exception:
        plan = _fallback_plan(question)
        reason = "Planner fallback used deterministic source-routing rules"

    audit = [f"[plan] {step.tool}: {step.purpose}" for step in plan.steps]
    if plan.needs_user_input:
        audit.append(
            "[plan] needs_user_input: "
            + ", ".join(plan.clarification_options)
        )

    return {
        "intent": plan.intent,
        "plan": [step.model_dump() for step in plan.steps],
        "plan_summary": plan.summary,
        "route_mode": "plan_execute",
        "route_reason": reason,
        "audit_log": audit,
        "needs_user_input": plan.needs_user_input,
        "clarification_options": plan.clarification_options,
        "clarifying_question": "",
        "next_step": "reason_and_act",
    }


def prepare_reasoning_node(state: AgentState) -> dict:
    plan_payload = {
        "steps": state.get("plan") or [],
        "needs_user_input": bool(state.get("needs_user_input")),
        "clarification_options": state.get("clarification_options") or [],
        "summary": state.get("plan_summary") or "",
    }
    plan_json = json.dumps(plan_payload, ensure_ascii=False)
    return {
        "messages": [
            SystemMessage(content=f"{REACT_PROMPT}\n\nExecution plan:\n{plan_json}"),
            HumanMessage(content=build_llm_user_context(state)),
        ]
    }


def _completed_tool_names(messages: list) -> set[str]:
    return {
        str(message.name)
        for message in messages
        if isinstance(message, ToolMessage) and message.name
    }


def _tool_args_for_step(step: dict, question: str) -> dict:
    """Build tool arguments from the validated plan, not a rewritten keyword query."""
    tool_name = step.get("tool")
    if tool_name == "lookup_order_status":
        args: dict[str, Any] = {"query": step.get("query") or question}
        order_id = step.get("order_id")
        if order_id:
            args["order_id"] = order_id
        return args
    if tool_name == "calculate_pricing":
        quote = step.get("quote_filters") or {}
        line_items = quote.get("line_items") or []
        return {
            "query": step.get("query") or question,
            "line_items": line_items,
        }
    if tool_name != "search_product_catalog":
        return {"query": step.get("query") or question}

    filters = step.get("product_filters") or {}
    args = {
        key: value
        for key, value in filters.items()
        if value is not None and value != []
    }
    args["query"] = question
    return {"query": args.pop("query"), **args}


def reasoning_action_node(state: AgentState) -> dict:
    messages = state.get("messages") or []
    if state.get("needs_user_input"):
        return {"messages": [AIMessage(content="")]}

    response = _react_llm.invoke(messages)
    completed = _completed_tool_names(messages)
    planned_tools = {
        str(step.get("tool"))
        for step in state.get("plan") or []
        if step.get("tool") in TOOL_BY_NAME
    }
    plan_by_tool = {
        str(step.get("tool")): step
        for step in state.get("plan") or []
        if step.get("tool") in TOOL_BY_NAME
    }
    allowed_calls = []
    for call in getattr(response, "tool_calls", None) or []:
        name = call.get("name")
        if name not in planned_tools or name in completed:
            continue
        allowed_calls.append(
            {
                **call,
                "args": _tool_args_for_step(
                    plan_by_tool[name],
                    state.get("user_input", ""),
                ),
            }
        )
    if allowed_calls:
        return {
            "messages": [
                AIMessage(
                    content=message_content_to_text(response.content),
                    tool_calls=allowed_calls,
                )
            ]
        }

    missing_steps = [
        step
        for step in state.get("plan") or []
        if step.get("tool") not in completed
    ]
    if missing_steps:
        forced_calls = [
            {
                "name": step["tool"],
                "args": _tool_args_for_step(step, state.get("user_input", "")),
                "id": f"forced-{uuid.uuid4()}",
                "type": "tool_call",
            }
            for step in missing_steps
            if step.get("tool") in TOOL_BY_NAME
        ]
        return {"messages": [AIMessage(content="", tool_calls=forced_calls)]}
    return {"messages": [response]}


def route_after_reasoning(state: AgentState) -> Literal["tools", "synthesize"]:
    last = (state.get("messages") or [])[-1]
    return "tools" if getattr(last, "tool_calls", None) else "synthesize"


def _tool_evidence(messages: list) -> list[dict]:
    evidence: list[dict] = []
    seen: set[str] = set()
    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        text = message_content_to_text(message.content)
        try:
            payload = json.loads(text)
        except (TypeError, json.JSONDecodeError):
            payload = {
                "source": message.name or "unknown",
                "status": "error",
                "message": "Tool returned an invalid response",
            }
        fingerprint = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        evidence.append(payload)
    return evidence


_KB_NOT_FOUND_ANSWER = (
    "ไม่พบข้อมูลในระบบค่ะ กรุณาติดต่อ admin ที่เบอร์ 1234567890"
)
_ADMIN_CONTACT_LINE = "กรุณาติดต่อ admin ที่เบอร์ 1234567890"


def _format_similar_product_line(product: dict) -> str:
    parts: list[str] = []
    name = product.get("name")
    shade = product.get("shade")
    sku = product.get("sku")
    price = product.get("price")
    stock = product.get("stock")
    if name not in (None, ""):
        parts.append(str(name))
    if shade not in (None, ""):
        parts.append(f"เฉด {shade}")
    if sku not in (None, ""):
        parts.append(f"SKU {sku}")
    if price not in (None, ""):
        parts.append(f"ราคา {price} บาท")
    if isinstance(stock, (int, float)) and stock > 0:
        parts.append(f"มีสต็อก {int(stock)} ชิ้น")
    return " — ".join(parts) if parts else str(product)


def _format_requested_product_brief(product: dict) -> str:
    parts: list[str] = []
    name = product.get("name")
    sku = product.get("sku")
    price = product.get("price")
    if name not in (None, ""):
        parts.append(str(name))
    if sku not in (None, ""):
        parts.append(f"(SKU: {sku})")
    if price not in (None, ""):
        parts.append(f"ราคา {price} บาท/ชิ้น")
    return " ".join(parts) if parts else str(product)


def _product_cannot_fulfill(product: dict) -> bool:
    if product.get("can_fulfill") is False:
        return True
    stock = product.get("stock")
    if isinstance(stock, (int, float)) and stock <= 0:
        return True
    requested_qty = product.get("requested_qty")
    if (
        isinstance(requested_qty, int)
        and isinstance(stock, (int, float))
        and stock < requested_qty
    ):
        return True
    return False


def _unfulfillable_products(item: dict) -> list[dict]:
    if item.get("source") != "supabase_products" or item.get("status") != "ok":
        return []
    return [
        product
        for product in (item.get("products") or [])
        if isinstance(product, dict) and _product_cannot_fulfill(product)
    ]


def _is_out_of_stock_evidence(item: dict) -> bool:
    """True when catalog matched products but none can fulfill the request."""
    if item.get("source") != "supabase_products" or item.get("status") != "ok":
        return False
    products = [p for p in (item.get("products") or []) if isinstance(p, dict)]
    if not products:
        return False
    unfulfillable = _unfulfillable_products(item)
    if not unfulfillable:
        return False
    # All matched products unavailable, or customer qty cannot be fulfilled for
    # at least one matched item while alternatives are only in similar_products.
    return len(unfulfillable) == len(products) or any(
        product.get("can_fulfill") is False for product in unfulfillable
    )


def _pick_focus_unavailable_product(products: list[dict], question: str) -> dict:
    """Prefer the unavailable SKU whose name overlaps the customer question."""
    text = (question or "").casefold()
    if text:
        scored: list[tuple[int, dict]] = []
        for product in products:
            name = str(product.get("name") or "").casefold()
            score = 0
            if name and name in text:
                score += 10
            for token in ("สเปรย์", "spray", "ลิป", "คุชชั่น", "cushion", "เซรั่ม"):
                if token in text and token in name:
                    score += 5
            if score:
                scored.append((score, product))
        if scored:
            scored.sort(key=lambda item: item[0], reverse=True)
            return scored[0][1]
    return products[0]


def _product_unavailable_with_similar_answer(
    evidence: list[dict],
    question: str = "",
) -> str | None:
    for item in evidence:
        if item.get("source") != "supabase_products":
            continue

        similar = item.get("similar_products") or []
        status = item.get("status")
        products = item.get("products") or []

        if status == "not_found" and similar:
            lines = [
                "ขออภัยค่ะ ทางเรายังไม่มีสินค้าที่ตรงตามรายการที่คุณลูกค้าสอบถาม",
                f"หากต้องการสินค้านี้โดยเฉพาะ {_ADMIN_CONTACT_LINE} เพื่อสอบถามเพิ่มเติมค่ะ",
                "",
                "ทางร้านขอแนะนำสินค้าใกล้เคียงที่มีสต็อกอยู่ค่ะ:",
            ]
            for product in similar[:5]:
                lines.append(f"- {_format_similar_product_line(product)}")
            return "\n".join(lines)

        if status == "ok" and _is_out_of_stock_evidence(item):
            unavailable = _unfulfillable_products(item)
            product = _pick_focus_unavailable_product(unavailable, question)
            headline = (
                f"ขออภัยค่ะ 😔 {_format_requested_product_brief(product)} "
                "ขณะนี้หมดสต็อกแล้ว"
            )
            requested_qty = product.get("requested_qty")
            if requested_qty:
                headline += (
                    f" ไม่สามารถจัดเตรียมได้ตามจำนวนที่คุณต้องการ ({requested_qty} ชิ้น)"
                )
            lines = [
                headline,
                f"หากต้องการสินค้านี้โดยเฉพาะ {_ADMIN_CONTACT_LINE} เพื่อสอบถามเรื่องสต็อกค่ะ",
            ]
            # Also surface other in-stock matches that were returned with the OOS item.
            recommendations = list(similar)
            seen = {
                str(alt.get("sku"))
                for alt in recommendations
                if alt.get("sku") not in (None, "")
            }
            for candidate in products:
                if not isinstance(candidate, dict) or _product_cannot_fulfill(candidate):
                    continue
                sku = candidate.get("sku")
                sku_key = str(sku) if sku not in (None, "") else ""
                if sku_key and sku_key in seen:
                    continue
                if sku_key:
                    seen.add(sku_key)
                recommendations.append(candidate)
            if recommendations:
                lines.extend(
                    [
                        "",
                        "ทางร้านขอแนะนำสินค้าใกล้เคียงที่มีสต็อกอยู่ค่ะ:",
                    ]
                )
                for alt in recommendations[:5]:
                    lines.append(f"- {_format_similar_product_line(alt)}")
            return "\n".join(lines)
    return None


def _product_not_found_with_similar_answer(
    evidence: list[dict],
    question: str = "",
) -> str | None:
    return _product_unavailable_with_similar_answer(evidence, question)


def _has_answerable_evidence(evidence: list[dict]) -> bool:
    for item in evidence:
        if item.get("status") == "ok":
            # Out-of-stock matches are handled by the deterministic unavailable path.
            if _is_out_of_stock_evidence(item):
                continue
            return True
        if item.get("source") == "supabase_products" and item.get("similar_products"):
            return True
    return False


def _safe_no_evidence_answer(evidence: list[dict], question: str = "") -> str:
    statuses = {str(item.get("status", "error")) for item in evidence}
    if "error" in statuses:
        return "ขออภัยค่ะ ขณะนี้ไม่สามารถตรวจสอบข้อมูลจากระบบของร้านได้ กรุณาลองใหม่หรือติดต่อร้านโดยตรงค่ะ"
    similar_answer = _product_not_found_with_similar_answer(evidence, question)
    if similar_answer:
        return similar_answer
    if any(item.get("source") == "supabase_products" for item in evidence):
        return "ไม่พบสินค้าในระบบค่ะ"
    if any(item.get("source") == "order_tracking_mock" for item in evidence):
        return (
            "ไม่พบออเดอร์ในระบบค่ะ "
            "กรุณาตรวจสอบหมายเลขคำสั่งซื้อ (เช่น GB-1001) หรือติดต่อ admin ที่เบอร์ 1234567890"
        )
    # Knowledge Base miss (or empty evidence after store-knowledge lookup).
    return _KB_NOT_FOUND_ANSWER


def synthesizer_node(state: AgentState) -> dict:
    messages = state.get("messages") or []
    evidence = _tool_evidence(messages)
    question = state.get("user_input", "")
    needs_user_input = bool(state.get("needs_user_input"))
    clarification_options = list(state.get("clarification_options") or [])

    if needs_user_input and clarification_options:
        synthesis_input = {
            "question": state.get("user_input", ""),
            "plan": {
                "needs_user_input": True,
                "clarification_options": clarification_options,
                "summary": state.get("plan_summary") or "",
                "steps": state.get("plan") or [],
            },
            "internal_draft": "",
            "tool_evidence": [],
        }
        try:
            result = _synthesizer.invoke(
                [
                    SystemMessage(content=SYNTHESIZER_PROMPT),
                    HumanMessage(content=json.dumps(synthesis_input, ensure_ascii=False)),
                ]
            )
            answer = result.answer.strip()
            verification = result.model_dump(exclude={"answer"})
        except Exception:
            # Fallback lists live options only; wording comes from synthesizer when available.
            answer = " / ".join(clarification_options)
            verification = {
                "addresses_question": False,
                "grounded_in_sources": True,
                "missing_information": clarification_options,
            }
        audit = list(state.get("audit_log") or [])
        audit.append("[verify] needs_user_input=True")
        return {
            "execution_result": answer,
            "clarifying_question": answer,
            "verification": verification,
            "audit_log": audit,
            "next_step": "awaiting_user",
        }

    similar_product_answer = _product_unavailable_with_similar_answer(
        evidence, question
    )
    usable = _has_answerable_evidence(evidence)
    # When the requested item cannot be fulfilled, always use the deterministic
    # apology + similar products + admin contact path (do not let the LLM skip it).
    if similar_product_answer:
        answer = similar_product_answer
        verification = {
            "addresses_question": True,
            "grounded_in_sources": True,
            "missing_information": ["สินค้าที่ถามไม่พร้อมจำหน่ายหรือหมดสต็อก"],
        }
    elif not usable:
        answer = _safe_no_evidence_answer(evidence, question)
        verification = {
            "addresses_question": True,
            "grounded_in_sources": True,
            "missing_information": ["ไม่พบข้อมูลที่ยืนยันได้จากแหล่งข้อมูล"],
        }
    else:
        last = messages[-1] if messages else None
        draft = (
            message_content_to_text(last.content)
            if isinstance(last, AIMessage)
            else ""
        )
        synthesis_input = {
            "question": state.get("user_input", ""),
            "plan": state.get("plan") or [],
            "internal_draft": draft,
            "tool_evidence": evidence,
        }
        try:
            result = _synthesizer.invoke(
                [
                    SystemMessage(content=SYNTHESIZER_PROMPT),
                    HumanMessage(content=json.dumps(synthesis_input, ensure_ascii=False)),
                ]
            )
            if not result.grounded_in_sources:
                answer = "พบข้อมูลบางส่วน แต่ยังไม่เพียงพอที่จะตอบคำถามนี้อย่างถูกต้อง กรุณาติดต่อร้านเพื่อยืนยันค่ะ"
            elif not result.addresses_question:
                # Prefer the model answer when it already explains partial/missing coverage.
                answer = result.answer.strip() or (
                    "พบข้อมูลบางส่วน แต่ยังไม่เพียงพอที่จะตอบคำถามนี้อย่างถูกต้อง "
                    "กรุณาติดต่อร้านเพื่อยืนยันค่ะ"
                )
            else:
                answer = result.answer.strip()
            verification = result.model_dump(exclude={"answer"})
        except Exception:
            answer = "พบข้อมูลจากระบบ แต่ไม่สามารถตรวจสอบและสรุปคำตอบได้ กรุณาลองใหม่อีกครั้งค่ะ"
            verification = {
                "addresses_question": False,
                "grounded_in_sources": False,
                "missing_information": ["Synthesizer/Verifier failed"],
            }

    audit = list(state.get("audit_log") or [])
    audit.extend(
        f"[evidence] {item.get('source', 'unknown')}: {item.get('status', 'error')}"
        for item in evidence
    )
    audit.append(
        "[verify] "
        f"addresses={verification['addresses_question']} "
        f"grounded={verification['grounded_in_sources']}"
    )
    return {
        "execution_result": answer,
        "clarifying_question": "",
        "verification": verification,
        "audit_log": audit,
        "next_step": "done",
    }


def build_graph():
    workflow = StateGraph(AgentState)
    workflow.add_node("planner_node", planner_node)
    workflow.add_node("prepare_reasoning_node", prepare_reasoning_node)
    workflow.add_node("reasoning_action_node", reasoning_action_node)
    workflow.add_node("tools_node", ToolNode(AGENT_TOOLS))
    workflow.add_node("synthesizer_node", synthesizer_node)

    workflow.add_edge(START, "planner_node")
    workflow.add_edge("planner_node", "prepare_reasoning_node")
    workflow.add_edge("prepare_reasoning_node", "reasoning_action_node")
    workflow.add_conditional_edges(
        "reasoning_action_node",
        route_after_reasoning,
        {"tools": "tools_node", "synthesize": "synthesizer_node"},
    )
    workflow.add_edge("tools_node", "reasoning_action_node")
    workflow.add_edge("synthesizer_node", END)
    return workflow.compile()


def fresh_state() -> AgentState:
    return {
        "messages": [],
        "user_input": "",
        "conversation_summary": "",
        "recent_conversation": "",
        "intent": "",
        "plan": [],
        "plan_summary": "",
        "route_mode": "",
        "route_reason": "",
        "audit_log": [],
        "execution_result": "",
        "clarifying_question": "",
        "needs_user_input": False,
        "clarification_options": [],
        "next_step": "",
        "verification": {},
    }


def format_agent_result(result: AgentState) -> dict:
    awaiting_user = result.get("next_step") == "awaiting_user" or bool(
        result.get("needs_user_input")
    )
    return {
        "content": result.get("execution_result", ""),
        "intent": result.get("intent", ""),
        "route_mode": result.get("route_mode", ""),
        "route_mode_label": "Plan → ReAct → Synthesizer",
        "route_reason": result.get("route_reason", ""),
        "plan_summary": result.get("plan_summary", ""),
        "audit_log": result.get("audit_log") or [],
        "next_step": result.get("next_step", ""),
        "awaiting_user": awaiting_user,
        "done": result.get("next_step") == "done",
    }


def next_agent_state(result: AgentState) -> AgentState:
    if result.get("next_step") in {"done", "awaiting_user"}:
        return fresh_state()
    return result
