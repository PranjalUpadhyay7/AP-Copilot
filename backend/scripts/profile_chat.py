#!/usr/bin/env python3
"""Chat-latency profiler."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver

from app.audit.logger import AuditLogger
from app.comms.mavlink_client import MavlinkVehicleClient
from app.comms.sitl_manager import ARDUPILOT_ROOT, SITLSettings
from app.comms.sitl_manager import launch as launch_sitl
from app.comms.sitl_manager import terminate as terminate_sitl
from app.knowledge.metadata_fetcher import (
    MetadataCache,
    get_param_definitions,
    reconcile,
)
from app.knowledge.rag_store import (
    VEHICLE_DOC_SLUG,
    build_hybrid_index_from_param_definitions,
)
from app.knowledge.wiki_docs import get_wiki_index
from app.orchestrator.graph import build_graph
from app.orchestrator.nim_client import get_nim_chat_model
from app.orchestrator.tools import RuntimeContext

PROFILE_INSTANCE = 90

DEFAULT_PROMPTS = [
    ("narrow single-topic", "What does BATT_LOW_VOLT do on this vehicle?"),
    ("broad multi-part", "I want to add a hardware triggered camera on the setup, help me configure the pixhawk parameters for this"),
    ("diagnostic", "Why won't my copter arm right now?"),
]


def _payload_bytes(msg) -> int:
    if isinstance(msg, ToolMessage):
        return len(str(msg.content).encode())
    return len(str(getattr(msg, "content", "")).encode())


def run_one(graph, thread_id: str, label: str, prompt: str) -> dict:
    print(f"\n=== [{label}] {prompt!r} ===", flush=True)
    t0 = time.time()
    node_times: list[tuple[str, float]] = []
    tool_calls_made: list[str] = []
    total_payload_bytes = 0
    last_t = t0

    for event in graph.stream(
        {
            "messages": [HumanMessage(content=prompt)],
            "session_id": thread_id,
            "pending_proposal": None,
            "pending_tool_call_id": None,
            "remaining_tool_calls": None,
        },
        config={"configurable": {"thread_id": thread_id}},
    ):
        now = time.time()
        for node, payload in event.items():
            elapsed_here = now - last_t
            last_t = now
            node_times.append((node, elapsed_here))
            msgs = payload.get("messages", []) if isinstance(payload, dict) else []
            for m in msgs:
                if isinstance(m, AIMessage):
                    for c in m.tool_calls or []:
                        tool_calls_made.append(c["name"])
                elif isinstance(m, ToolMessage):
                    total_payload_bytes += _payload_bytes(m)
            print(f"  [{now - t0:6.1f}s] {node:16s} (+{elapsed_here:5.1f}s)  tool_calls_so_far={len(tool_calls_made)}", flush=True)

    total = time.time() - t0
    print(f"  TOTAL: {total:.1f}s, {len(tool_calls_made)} tool call(s): {tool_calls_made}", flush=True)
    print(f"  tool-result payload fed back to the LLM: {total_payload_bytes} bytes", flush=True)
    return {
        "label": label,
        "prompt": prompt,
        "total_seconds": round(total, 1),
        "tool_call_count": len(tool_calls_made),
        "tool_calls": tool_calls_made,
        "tool_payload_bytes": total_payload_bytes,
        "llm_round_trips": sum(1 for n, _ in node_times if n == "agent_node"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vehicle", default="copter", choices=["copter", "plane"])
    parser.add_argument("--prompt", action="append", help="run only this prompt (repeatable); default runs the built-in set")
    args = parser.parse_args()

    prompts = [("custom", p) for p in args.prompt] if args.prompt else DEFAULT_PROMPTS

    settings = SITLSettings(vehicle=args.vehicle, instance=PROFILE_INSTANCE, wipe_eeprom=True, speedup=1)
    print(f"Launching SITL ({args.vehicle}, instance {PROFILE_INSTANCE})...", flush=True)
    sitl_process = launch_sitl(settings)
    vehicle_client = MavlinkVehicleClient(settings.connection_string())
    try:
        vehicle_client.connect()
        version = vehicle_client.get_autopilot_version()
        print(f"Connected: {version.vehicle_type} {version.flight_sw_version}", flush=True)

        cache = MetadataCache()
        definitions = get_param_definitions(version, cache=cache, ardupilot_root=ARDUPILOT_ROOT)
        live_params = reconcile(vehicle_client.stream_params(), definitions)
        rag_index = (
            build_hybrid_index_from_param_definitions(
                definitions, vehicle_type=version.vehicle_type, version_key=version.version_key,
            )
            if definitions else None
        )
        wiki_slug = VEHICLE_DOC_SLUG.get(version.vehicle_type)
        wiki_index = get_wiki_index(wiki_slug) if wiki_slug else None

        context = RuntimeContext(
            session_id="profile", vehicle_client=vehicle_client, live_params=live_params,
            audit_logger=AuditLogger(db_path=":memory:"), rag_index=rag_index, wiki_index=wiki_index,
        )
        model = get_nim_chat_model()
        graph = build_graph(context, model, MemorySaver())

        results = []
        for i, (label, prompt) in enumerate(prompts):
            results.append(run_one(graph, f"profile-{i}", label, prompt))

        print("\n=== SUMMARY ===", flush=True)
        print(json.dumps(results, indent=2), flush=True)
    finally:
        vehicle_client.disconnect()
        terminate_sitl(sitl_process)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
