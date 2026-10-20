"""LangChain chat model wrapper around NVIDIA NIM."""
from __future__ import annotations

import os

from langchain_openai import ChatOpenAI

DEFAULT_NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_REQUEST_TIMEOUT_S = 60.0


def get_nim_chat_model(
    *,
    temperature: float = 0.0,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> ChatOpenAI:
    """Chat model for NVIDIA NIM or any OpenAI-compatible endpoint, with bounded timeouts."""
    api_key = api_key or os.environ.get("NIM_API_KEY")
    if not api_key:
        raise RuntimeError(
            "No API key configured. Either copy backend/.env.example to "
            "backend/.env and fill in NIM_API_KEY/NIM_BASE_URL/NIM_MODEL, or "
            "supply your own key via the session start request's llm_config."
        )
    base_url = base_url or os.environ.get("NIM_BASE_URL", DEFAULT_NIM_BASE_URL)
    model = model or os.environ.get("NIM_MODEL")
    if not model:
        raise RuntimeError(
            "No model configured (e.g. 'meta/llama-3.1-70b-instruct'). Set "
            "NIM_MODEL in backend/.env, or supply one via llm_config."
        )
    timeout = float(os.environ.get("NIM_REQUEST_TIMEOUT_S", DEFAULT_REQUEST_TIMEOUT_S))

    return ChatOpenAI(
        model=model,
        base_url=base_url,
        api_key=api_key,
        temperature=temperature,
        timeout=timeout,
        max_retries=int(os.environ.get("NIM_MAX_RETRIES", "1")),
    )
