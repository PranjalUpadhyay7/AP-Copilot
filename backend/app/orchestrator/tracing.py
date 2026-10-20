"""LangSmith tracing setup/env wiring."""
from __future__ import annotations

import os

PROJECT_DEV = "ap-copilot-dev"
PROJECT_SITL_TEST = "ap-copilot-sitl-test"


def configure_tracing(project: str = PROJECT_DEV) -> bool:
    """Returns True if tracing is actually active after this call."""
    enabled = os.environ.get("LANGCHAIN_TRACING_V2", "false").lower() == "true"
    if not enabled:
        return False
    if not os.environ.get("LANGCHAIN_API_KEY"):
        raise RuntimeError(
            "LANGCHAIN_TRACING_V2=true but LANGCHAIN_API_KEY is not set -- "
            "set it in backend/.env or disable tracing."
        )
    os.environ["LANGCHAIN_PROJECT"] = project
    return True


def trace_metadata(vehicle_type: str, firmware_version: str) -> dict:
    return {"vehicle_type": vehicle_type, "firmware_version": firmware_version}
