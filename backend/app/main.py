"""FastAPI app, route registration."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from app.api import (
    routes_confirm,
    routes_procedures,
    routes_propose,
    routes_session,
    routes_telemetry_ws,
)
from app.api.session_manager import session_manager
from app.orchestrator.tracing import configure_tracing

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if os.environ.get("AP_COPILOT_SKIP_ORPHAN_CLEANUP") != "1":
        # Sessions left open by a dead backend can never resume
        closed = session_manager.session_store.end_orphans()
        if closed:
            logger.info("marked %d abandoned session(s) from a previous backend as ended", closed)
    enabled = configure_tracing()
    logger.info("LangSmith tracing %s", "enabled" if enabled else "disabled (LANGCHAIN_TRACING_V2 not set)")
    yield
    session_manager.end_all_active_sessions()


app = FastAPI(title="AP-Copilot Backend", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes_session.router)
app.include_router(routes_propose.router)
app.include_router(routes_confirm.router)
app.include_router(routes_procedures.router)
app.include_router(routes_telemetry_ws.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
