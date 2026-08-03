from __future__ import annotations

import os
import re

import boto3
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from backend.core.llm import create_chat_llm

load_dotenv()

_REWRITE_ENABLED = os.getenv("AWS_KB_QUERY_REWRITE", "true").lower() in ("1", "true", "yes")
_REWRITE_VARIANTS = int(os.getenv("AWS_KB_QUERY_VARIANTS", "3"))
_SOURCE_FALLBACK_ENABLED = os.getenv("AWS_KB_SOURCE_FALLBACK", "false").lower() in ("1", "true", "yes")
_SOURCE_BUCKET = os.getenv("AWS_KB_S3_BUCKET", "glow-beauty-shop-base-syd")
_SOURCE_KEY = os.getenv("AWS_KB_S3_KEY", "glow-beauty-shop-key.txt")
_SOURCE_CACHE: str | None = None

_INTERACTION_QUERY = re.compile(
    r"ส่งผล|ผลกระทบ|interaction|อันตรกิริยา|ร่วมกับ|combine|concomitant|adverse",
    re.IGNORECASE,
)
_DRUG_TOKEN = re.compile(r"[A-Za-z]{4,}|[\u0E00-\u0E7F]{3,}")


def _kb_id() -> str:
    kb_id = os.getenv("AWS_KNOWLEDGE_BASE_ID", "").strip()
    if not kb_id:
        raise RuntimeError("AWS_KNOWLEDGE_BASE_ID is not configured")
    return kb_id


def _region() -> str:
    return os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "ap-southeast-1"))


def _result_limit(limit: int | None = None) -> int:
    if limit is not None:
        return limit
    return int(os.getenv("AWS_KB_NUMBER_OF_RESULTS", "5"))


def _create_rewrite_llm():
    return create_chat_llm(temperature=0)


REWRITE_SYSTEM_PROMPT = """\
You rewrite Glow Beauty Shop customer questions into search queries for the shop knowledge base
(product/service menu, pricing/promotions, booking/appointment policy, delivery/payment/refund policy, store hours/location, and FAQ — Thai and English).

Produce 3-4 search queries optimized for semantic retrieval over document chunks.

Critical disambiguation (from context — never assume product/service details unless explicitly named):
- If the question names ONE product/service, include at least one query targeting:
  name, category (e.g., skincare/haircare), and relevant policy sections (price, promotion, booking, usage details if present).
- If the question asks about pricing/promotions, include queries targeting: price, promotion, package, and any eligibility/conditions.
- If the question asks about ordering/shipping/delivery/payment/refund, include queries targeting those exact policy terms.
- If the question compares TWO products/services, include at least one query targeting both items and a comparison angle.
- If the question asks about availability/“does it have/has stock/when”, include queries targeting the store’s availability/booking/lead time policy.

Each query: 5-20 words, document-style wording, preserve entity names, add English terms when useful.\
"""


class RetrievalQueries(BaseModel):
    queries: list[str] = Field(
        min_length=2,
        max_length=4,
        description="Search queries for vector retrieval",
    )


def rewrite_kb_queries(question: str, *, max_variants: int = _REWRITE_VARIANTS) -> list[str]:
    """LLM-based query expansion — ไม่ hardcode ชื่อยา/คำศัพท์เฉพาะ"""
    question = question.strip()
    if not question:
        return []

    if not _REWRITE_ENABLED:
        return [question]

    try:
        llm = _create_rewrite_llm().with_structured_output(
            RetrievalQueries,
            method="function_calling",
        )
        result: RetrievalQueries = llm.invoke([
            SystemMessage(content=REWRITE_SYSTEM_PROMPT),
            HumanMessage(content=question),
        ])
        variants = [q.strip() for q in result.queries if q.strip()]
    except Exception:
        variants = []

    seen: set[str] = set()
    out: list[str] = []
    for item in [question, *variants]:
        key = item.casefold()
        if key not in seen:
            seen.add(key)
            out.append(item)
        if len(out) >= max_variants + 1:
            break
    return out or [question]


def _retrieve_raw(query: str, *, limit: int) -> list[dict]:
    client = boto3.client("bedrock-agent-runtime", region_name=_region())
    response = client.retrieve(
        knowledgeBaseId=_kb_id(),
        retrievalQuery={"text": query},
        retrievalConfiguration={
            "vectorSearchConfiguration": {
                "numberOfResults": limit,
            }
        },
    )
    return response.get("retrievalResults", [])


def _load_kb_source_text() -> str:
    global _SOURCE_CACHE
    if _SOURCE_CACHE is not None:
        return _SOURCE_CACHE

    client = boto3.client("s3", region_name=_region())
    obj = client.get_object(Bucket=_SOURCE_BUCKET, Key=_SOURCE_KEY)
    _SOURCE_CACHE = obj["Body"].read().decode("utf-8", errors="replace")
    return _SOURCE_CACHE


def _extract_markdown_section(text: str, section_number: int) -> str:
    start_match = re.search(rf"^##\s*{section_number}\.", text, flags=re.MULTILINE)
    if not start_match:
        return ""
    start = start_match.start()
    next_match = re.search(rf"^##\s*{section_number + 1}\.", text[start + 1 :], flags=re.MULTILINE)
    end = start + 1 + next_match.start() if next_match else len(text)
    return text[start:end].strip()


def _query_drug_tokens(query: str) -> list[str]:
    stop = {
        "ส่งผล", "ยังไง", "กับ", "และ", "the", "with", "drug", "interaction",
        "vancomycin", "aminoglycoside", "แวนโคมัยซิน",
    }
    tokens: list[str] = []
    for match in _DRUG_TOKEN.findall(query):
        token = match.strip()
        if len(token) < 3 or token.casefold() in stop:
            continue
        if token not in tokens:
            tokens.append(token)
    if re.search(r"(?i)aminoglycoside|แวนโคมัยซิน|vancomycin", query):
        for forced in ("Aminoglycoside", "แวนโคมัยซิน"):
            if forced not in tokens:
                tokens.append(forced)
    return tokens


def _interaction_line_matches(line: str, query: str) -> bool:
    normalized = line.casefold()
    paired_drugs = [
        token
        for token in _query_drug_tokens(query)
        if token.casefold() not in {"แวนโคมัยซิน", "vancomycin"}
    ]
    if paired_drugs:
        return any(token.casefold() in normalized for token in paired_drugs)
    return "แวนโคมัยซิน" in normalized or "vancomycin" in normalized


def _source_fallback_hits(query: str) -> list[tuple[str, float, dict]]:
    """Lexical fallback when vector index misses chunks that exist in the S3 source file."""
    if not _SOURCE_FALLBACK_ENABLED:
        return []

    try:
        source_text = _load_kb_source_text()
    except Exception:
        return []

    snippets: list[str] = []
    if _INTERACTION_QUERY.search(query):
        section = _extract_markdown_section(source_text, 10)
        tokens = _query_drug_tokens(query)
        if section:
            matching_lines = [
                line.strip()
                for line in section.splitlines()
                if line.strip().startswith("- ") and _interaction_line_matches(line, query)
            ]
            if matching_lines:
                snippets.append("\n".join(matching_lines))
            else:
                snippets.append(section)
        elif section:
            snippets.append(section)

    if not snippets:
        return []

    uri = f"s3://{_SOURCE_BUCKET}/{_SOURCE_KEY}"
    hits: list[tuple[str, float, dict]] = []
    seen: set[str] = set()
    for snippet in snippets:
        key = snippet[:500]
        if key in seen:
            continue
        seen.add(key)
        hits.append(
            (
                "source-fallback",
                0.99,
                {
                    "content": {"text": snippet},
                    "location": {"s3Location": {"uri": uri}},
                },
            )
        )
    return hits


def _hit_source_uri(hit: dict) -> str:
    location = hit.get("location") or {}
    return str((location.get("s3Location") or {}).get("uri") or "")


def _is_product_catalog_source(uri: str, content: str) -> bool:
    """Product CSV belongs to Supabase catalog tool, not store-policy KB answers."""
    lowered_uri = uri.casefold()
    if lowered_uri.endswith("catalog.csv") or "/catalog.csv" in lowered_uri:
        return True
    head = (content or "").lstrip()[:180].casefold()
    return head.startswith("sku,") or "price_thb,stock_qty" in head


def _merge_hits(all_hits: list[tuple[str, dict]]) -> list[tuple[str, float, dict]]:
    """Merge duplicate chunks; keep highest vector score."""
    best: dict[str, tuple[str, float, dict]] = {}
    for source_query, hit in all_hits:
        content = hit.get("content", {}).get("text", "")
        if not content.strip():
            continue
        uri = _hit_source_uri(hit)
        if _is_product_catalog_source(uri, content):
            continue
        score = float(hit.get("score") or 0.0)
        key = content.strip()[:500]
        prev = best.get(key)
        if prev is None or score > prev[1]:
            best[key] = (source_query, score, hit)
    merged = list(best.values())
    merged.sort(key=lambda x: x[1], reverse=True)
    return merged


def search_store_knowledge(query: str, *, limit: int | None = None) -> str:
    """
    ค้นหาข้อมูล Glow Beauty Shop จาก AWS Bedrock Knowledge Base.
    ใช้ LLM rewrite คำถามเป็นหลาย search query.
    """
    query = query.strip()
    if not query:
        return "ไม่มีคำค้นหา"

    search_queries = rewrite_kb_queries(query)
    per_query_limit = max(3, _result_limit(limit))

    try:
        all_hits: list[tuple[str, dict]] = []
        for sq in search_queries:
            for hit in _retrieve_raw(sq, limit=per_query_limit):
                all_hits.append((sq, hit))
    except Exception as exc:
        return f"[Knowledge Base error] {exc}"

    merged = _merge_hits(all_hits)
    fallback = _source_fallback_hits(query)
    if fallback:
        existing = {content.strip()[:500] for _, _, hit in merged for content in [hit.get("content", {}).get("text", "")]}
        merged = [
            *fallback,
            *(item for item in merged if item[2].get("content", {}).get("text", "").strip()[:500] not in existing),
        ]
    max_total = _result_limit(limit) * 2
    merged = merged[:max_total]

    if not merged:
        return f"ไม่พบเอกสารที่เกี่ยวข้องกับ: {query}"

    parts = [
        f"ผลจาก Glow Beauty Shop Knowledge Base สำหรับ: {query}",
        f"(search queries: {len(search_queries)})\n",
    ]
    for i, (source_query, score, hit) in enumerate(merged, 1):
        content = hit.get("content", {}).get("text", "")
        location = hit.get("location", {})
        s3_uri = location.get("s3Location", {}).get("uri", "")

        header = f"--- [{i}] score {score:.3f}"
        if s3_uri:
            header += f" source: {s3_uri}"
        if source_query != query:
            header += f" (query: {source_query[:72]})"
        header += " ---"
        parts.append(f"{header}\n{content}\n")

    return "\n".join(parts)


# Backward-compatible alias while callers migrate to the shop-specific name.
search_medical_knowledge = search_store_knowledge
