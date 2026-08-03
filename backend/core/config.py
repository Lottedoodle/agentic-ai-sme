from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

DEFAULT_CORS_ORIGINS = (
    "http://localhost:3000,http://127.0.0.1:3000,"
    "http://localhost:3001,http://127.0.0.1:3001"
)
DEFAULT_BEDROCK_MODEL_ID = "au.anthropic.claude-haiku-4-5-20251001-v1:0"
DEFAULT_AWS_REGION = "ap-southeast-2"


def get_env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def cors_origins() -> list[str]:
    raw = get_env("CORS_ORIGINS", DEFAULT_CORS_ORIGINS)
    return [origin for origin in raw.split(",") if origin.strip()]


def cors_origin_regex() -> str:
    return get_env("CORS_ORIGIN_REGEX", r"https?://(localhost|127\.0\.0\.1)(:\d+)?")


def bedrock_model_id() -> str:
    return get_env("AWS_BEDROCK_MODEL_ID", DEFAULT_BEDROCK_MODEL_ID) or DEFAULT_BEDROCK_MODEL_ID


def bedrock_region() -> str:
    return get_env("AWS_REGION", get_env("AWS_DEFAULT_REGION", DEFAULT_AWS_REGION))
