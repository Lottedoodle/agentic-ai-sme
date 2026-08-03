from __future__ import annotations

from typing import Any

from langchain_aws import ChatBedrockConverse
from langchain_core.language_models.chat_models import BaseChatModel

from backend.core.config import bedrock_model_id, bedrock_region


def create_chat_llm(*, temperature: float = 0) -> BaseChatModel:
    """Shared Bedrock Converse chat model for agent, RAG rewrite, and summarization."""
    return ChatBedrockConverse(
        model=bedrock_model_id(),
        region_name=bedrock_region(),
        temperature=temperature,
    )


def message_content_to_text(content: Any) -> str:
    """Normalize LangChain/Bedrock message content to plain text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                if block.get("type") == "text" or "text" in block:
                    parts.append(str(block.get("text", "")))
            else:
                text = getattr(block, "text", None)
                if text is not None:
                    parts.append(str(text))
        return "".join(parts)
    return str(content)
