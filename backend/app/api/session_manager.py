"""Session lifecycle glue."""
from __future__ import annotations

import logging
import os
import sqlite3
import subprocess
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from pymavlink import mavutil

from app.audit.logger import AuditEventType, AuditLogger
from app.audit.session_store import SessionStore, _serialize_message, load_messages
from app.comms.mavlink_client import DEFAULT_SITL_CONNECTION, MavlinkVehicleClient
from app.comms.serial_ports import (
    board_label_for,
    find_flight_controller,
    stable_port_path,
)
from app.comms.sitl_manager import SITLLaunchError, SITLSettings
from app.comms.sitl_manager import launch as launch_sitl
from app.comms.sitl_manager import terminate as terminate_sitl
from app.knowledge.board_registry import resolve_board_name
from app.knowledge.metadata_fetcher import (
    MetadataCache,
    frame_label,
    get_param_definitions,
    reconcile,
)
from app.knowledge.rag_store import (
    VEHICLE_DOC_SLUG,
    build_hybrid_index_from_param_definitions,
)
from app.knowledge.wiki_docs import get_wiki_index
from app.models.api import TurnStep
from app.models.proposal import ProposedChange, ValidatedProposal
from app.models.vehicle import VehicleVersionInfo
from app.orchestrator.checkpointer import DEFAULT_CHECKPOINT_DB
from app.orchestrator.graph import apply_confirmed_write, build_graph
from app.orchestrator.nim_client import get_nim_chat_model
from app.orchestrator.procedures import (
    COMPASS_CALIBRATION_TITLE,
    build_compass_calibration_procedure,
    trigger_compass_calibration,
)
from app.orchestrator.tools import ProcedureProposal, RuntimeContext
from app.orchestrator.tracing import trace_metadata
from app.telemetry import rl_log
from app.validation.safety_snapshot import compute_safety_snapshot
from app.validation.validators import validate_proposed_change

logger = logging.getLogger(__name__)

MAV_CMD_PREFLIGHT_REBOOT_SHUTDOWN = mavutil.mavlink.MAV_CMD_PREFLIGHT_REBOOT_SHUTDOWN

AP_COPILOT_HOME = Path(os.environ.get("AP_COPILOT_HOME", Path.home() / ".ap-copilot"))
if os.environ.get("ARDUPILOT_ROOT"):
    ARDUPILOT_ROOT = os.environ["ARDUPILOT_ROOT"]
else:
    from app.comms.sitl_manager import ARDUPILOT_ROOT as _SITL_ARDUPILOT_ROOT
    ARDUPILOT_ROOT = _SITL_ARDUPILOT_ROOT if os.path.isdir(_SITL_ARDUPILOT_ROOT) else None

AUDIT_DB_PATH = AP_COPILOT_HOME / "audit_log.sqlite3"
SESSION_HISTORY_DB_PATH = AP_COPILOT_HOME / "session_history.sqlite3"


@dataclass
class Session:
    """A live vehicle session and its agent state."""
    session_id: str
    started_at: datetime
    ended_at: datetime | None
    vehicle_type: str
    firmware_version: str
    read_only: bool
    context: RuntimeContext
    graph: object
    thread_config: dict
    _checkpoint_conn: sqlite3.Connection
    _sitl_process: subprocess.Popen | None = None
    pending_episode_id: str | None = None
    connection_string: str = ""
    rebooting: bool = False


class SessionManager:
    """Owns live sessions: vehicle link, agent graph, proposals, reboot and transcripts."""
    def __init__(self):
        self._sessions: dict[str, Session] = {}
        AP_COPILOT_HOME.mkdir(parents=True, exist_ok=True)
        self.session_store = SessionStore(SESSION_HISTORY_DB_PATH)

    def start_session(
        self,
        connection_string: str = DEFAULT_SITL_CONNECTION,
        *,
        mode: str = "hardware",
        sitl_settings: dict | None = None,
        chat_model=None,
        llm_config: dict | None = None,
        progress: Callable[[dict], None] | None = None,
    ) -> Session:
        """Connect, load metadata and docs, build the agent graph; reports progress via a callback."""
        def emit(stage: str, label: str, percent: float) -> None:
            if progress is not None:
                progress({"type": "progress", "stage": stage, "label": label, "percent": round(percent, 1)})

        sitl_process = None
        if mode == "simulation":
            emit("launching", "Launching the simulator (the first run can take a few minutes to build)…", 3)
            settings = SITLSettings(**(sitl_settings or {}))
            try:
                sitl_process = launch_sitl(settings)
            except SITLLaunchError as e:
                raise ConnectionError(str(e)) from e
            connection_string = settings.connection_string()

        if mode == "hardware" and connection_string == "auto":
            emit("detecting", "Looking for the flight controller on the serial ports…", 5)
            found = find_flight_controller()
            if found is None:
                raise ConnectionError(
                    "auto-detect found no flight controller answering on any serial port -- is it plugged in "
                    "and powered, and are you in the 'dialout' group? You can also pick a device or type an "
                    "address manually."
                )
            connection_string = found

        if mode == "hardware":
            connection_string = stable_port_path(connection_string)  # survives a re-enumeration after reboot

        emit("connecting", "Connecting to the flight controller…", 12)
        vehicle_client = MavlinkVehicleClient(connection_string)
        try:
            vehicle_client.connect()
            emit("firmware", "Reading the firmware version…", 20)
            version: VehicleVersionInfo = vehicle_client.get_autopilot_version()

            cache = MetadataCache()
            fw = f"{version.vehicle_type} {version.flight_sw_version}"
            if cache.get(version.vehicle_type, version.version_key) is None:
                emit("metadata", f"Looking up parameter docs for {fw}…", 25)

            def on_metadata_progress(kind: str, fraction: float | None) -> None:
                if kind == "download" and fraction is not None:
                    emit("download", f"Downloading parameter docs for {fw} ({round(fraction * 100)}%)", 25 + fraction * 45)
                elif kind == "parse":
                    emit("parse", f"Generating parameter docs for {fw} (about a minute)…", 74)

            definitions = get_param_definitions(
                version, cache=cache, ardupilot_root=ARDUPILOT_ROOT, trust_local_checkout=(mode == "simulation"),
                progress=on_metadata_progress,
            )
            read_only = definitions is None

            emit("params", "Reading all parameters from the vehicle…", 80)
            raw_values = vehicle_client.stream_params()
            live_params = reconcile(raw_values, definitions)
            emit("index", "Building the search index…", 88)
            rag_index = (
                build_hybrid_index_from_param_definitions(
                    definitions, vehicle_type=version.vehicle_type, version_key=version.version_key,
                )
                if definitions
                else None
            )

            session_id = str(uuid.uuid4())
            audit_logger = AuditLogger(db_path=str(AUDIT_DB_PATH))
            emit("wiki", "Loading the ArduPilot documentation wiki…", 94)
            wiki_slug = VEHICLE_DOC_SLUG.get(version.vehicle_type)
            wiki_index = None
            if wiki_slug:
                try:
                    wiki_index = get_wiki_index(wiki_slug)
                except Exception as e:  # noqa: BLE001 -- best-effort memory tier, must never block a session
                    logger.warning("wiki doc tier unavailable this session (%s): %s", wiki_slug, e)
            context = RuntimeContext(
                session_id=session_id, vehicle_client=vehicle_client, live_params=live_params,
                audit_logger=audit_logger, rag_index=rag_index, wiki_index=wiki_index,
                board_name=resolve_board_name(version.board_type, ARDUPILOT_ROOT),
                vehicle_info={
                    "vehicle_type": version.vehicle_type, "firmware_version": version.flight_sw_version,
                    "git_hash": version.git_hash, "mav_type": version.mav_type,
                    "frame_label": frame_label(version.mav_type),
                    "board_label": board_label_for(connection_string, simulation=(mode == "simulation")),
                },
                definitions=definitions,
            )

            emit("assistant", "Starting the assistant…", 98)
            chat_model = chat_model or get_nim_chat_model(**(llm_config or {}))
            DEFAULT_CHECKPOINT_DB.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(DEFAULT_CHECKPOINT_DB), check_same_thread=False)
            checkpointer = SqliteSaver(conn)
            graph = build_graph(context, chat_model, checkpointer)
        except Exception:
            vehicle_client.disconnect()
            if sitl_process is not None:
                terminate_sitl(sitl_process)
            raise

        session = Session(
            session_id=session_id,
            started_at=datetime.now(UTC),
            ended_at=None,
            vehicle_type=version.vehicle_type,
            firmware_version=version.flight_sw_version,
            connection_string=connection_string,
            read_only=read_only,
            context=context,
            graph=graph,
            thread_config={
                "configurable": {"thread_id": session_id},
                "metadata": trace_metadata(version.vehicle_type, version.flight_sw_version),
                "recursion_limit": 60,
            },
            _checkpoint_conn=conn,
            _sitl_process=sitl_process,
        )
        self._sessions[session_id] = session
        self.session_store.start(
            session_id, version.vehicle_type, version.flight_sw_version, read_only,
        )
        return session

    def get(self, session_id: str) -> Session:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(f"no such session: {session_id}")
        return session

    def refresh_live_params(self, session: Session) -> None:
        raw_values = session.context.vehicle_client.stream_params()
        cached_definitions = {
            name: p.definition for name, p in session.context.live_params.items() if p.definition is not None
        }
        session.context.live_params = reconcile(raw_values, cached_definitions or None)

    @staticmethod
    def _require_not_rebooting(session: Session) -> None:
        if session.rebooting:
            raise RuntimeError("the vehicle is rebooting -- wait for it to reconnect, then try again")

    def reboot_vehicle(
        self,
        session: Session,
        progress: Callable[[dict], None] | None = None,
        *,
        reconnect_timeout: float = 90.0,
        settle_s: float = 3.0,
    ) -> dict:
        """Reboot the autopilot (only when disarmed) and reconnect the same session."""
        def emit(stage: str, label: str, percent: float, link: str) -> None:
            if progress is not None:
                progress({"type": "progress", "stage": stage, "label": label, "percent": round(percent, 1), "link": link})

        if session.rebooting:
            raise RuntimeError("a reboot is already in progress")
        ctx = session.context
        pending = session.graph.get_state(session.thread_config).values.get("pending_proposal")
        if pending is not None or ctx.pending_proposals or ctx.pending_procedures:
            raise RuntimeError("resolve (confirm or reject) the pending proposal or procedure before rebooting")

        emit("checking", "Checking the vehicle is disarmed…", 5, "up")
        # Fail closed: reboot only when the vehicle is confirmed disarmed
        armed = ctx.vehicle_client.get_armed_state()
        if armed is None:
            raise RuntimeError("could not confirm whether the vehicle is armed -- not rebooting (fail closed)")
        if armed:
            raise RuntimeError("the vehicle is armed -- disarm it before rebooting")

        expected = (ctx.vehicle_info or {}).copy()
        # Blocks chat until the vehicle is back
        session.rebooting = True
        try:
            ctx.audit_logger.log_reboot(session.session_id)
            emit("sending", "Sending the reboot command…", 15, "up")
            result = ctx.vehicle_client.send_command(MAV_CMD_PREFLIGHT_REBOOT_SHUTDOWN, (1.0,))
            # No ACK is normal (the board may reset before answering); an explicit refusal is not.
            if result.result_code is not None and not result.accepted:
                raise RuntimeError(f"the vehicle refused the reboot command (MAV_RESULT {result.result_code})")

            emit("rebooting", "Vehicle is rebooting — link lost…", 25, "down")
            ctx.vehicle_client.disconnect()
            time.sleep(settle_s)

            started = time.time()
            new_client = None
            while new_client is None and time.time() - started < reconnect_timeout:
                waited = time.time() - started
                emit("waiting", f"Waiting for the vehicle to come back ({int(waited)} s)…",
                     25 + 50 * min(1.0, waited / reconnect_timeout), "down")
                candidate = MavlinkVehicleClient(session.connection_string)
                try:
                    candidate.connect(timeout=6)
                    new_client = candidate
                except (ConnectionError, TimeoutError, OSError):
                    candidate.disconnect()
                    time.sleep(1)
            if new_client is None:
                raise TimeoutError(
                    f"the vehicle did not come back within {int(reconnect_timeout)} s. Check it is powered and "
                    "connected, then end this session and connect again."
                )

            emit("reconnected", "Heartbeat received — the vehicle is back", 80, "up")
            version = new_client.get_autopilot_version()
            # A different firmware after the reboot means this chat is about another vehicle
            if expected.get("vehicle_type") != version.vehicle_type or (
                expected.get("git_hash") and expected.get("git_hash") != version.git_hash
            ):
                new_client.disconnect()
                raise ConnectionError(
                    f"after the reboot the vehicle reports {version.vehicle_type} {version.flight_sw_version} "
                    f"(commit {version.git_hash}), not the firmware this chat was about. End this session and "
                    "connect again."
                )
            ctx.vehicle_client = new_client

            emit("params", "Re-reading all parameters…", 88, "up")
            self.refresh_live_params(session)
            armed_now = new_client.get_armed_state()
            emit("done", "Reconnected", 100, "up")
            return {"param_count": len(ctx.live_params), "armed": armed_now}
        finally:
            session.rebooting = False

    def end_session(self, session_id: str) -> Session:
        session = self.get(session_id)
        session.ended_at = datetime.now(UTC)
        session.context.vehicle_client.disconnect()
        session._checkpoint_conn.close()
        if session._sitl_process is not None:
            terminate_sitl(session._sitl_process)
        self.session_store.end(session_id)
        return session

    def list_session_history(self):
        return self.session_store.list_sessions()

    def end_all_active_sessions(self) -> None:
        for session_id, session in list(self._sessions.items()):
            if session.ended_at is not None:
                continue
            try:
                self.end_session(session_id)
            except Exception as e:  # noqa: BLE001 -- best-effort shutdown cleanup
                logger.warning("failed to cleanly end session %s during shutdown: %s", session_id, e)

    def get_transcript(self, session_id: str) -> list[dict]:
        return self.transcript_with_turn_details(load_messages(session_id))

    @classmethod
    def transcript_with_turn_details(cls, messages: list) -> list[dict]:
        """Chat history with each turn's thinking steps, rejections and applied-change bubbles."""
        serialized = [_serialize_message(m) for m in messages]
        action_bubbles: dict[int, dict] = {}
        for i, m in enumerate(messages):
            if isinstance(m, ToolMessage) and m.name == "propose_param_change":
                text = str(m.content)
                try:
                    ValidatedProposal.model_validate_json(text)
                    continue
                except (ValueError, TypeError):
                    pass
                lowered = text.lower()
                outcome = (
                    "rejected" if lowered.startswith("the user rejected")
                    else "blocked_at_write_time" if ("no longer safe" in lowered or lowered.startswith("blocked"))
                    else "applied"
                )
                write_steps = (m.additional_kwargs or {}).get("write_steps") or []
                action_bubbles[i] = {
                    "role": "assistant", "content": f"[{outcome}] {text}",
                    "turn_steps": write_steps, "rejected_proposals": [],
                }
        starts = [i for i, m in enumerate(messages) if isinstance(m, HumanMessage)]
        for n, start in enumerate(starts):
            end = starts[n + 1] if n + 1 < len(starts) else len(messages)
            turn = messages[start + 1:end]
            final_idx = next(
                (start + 1 + j for j in range(len(turn) - 1, -1, -1)
                 if isinstance(turn[j], AIMessage) and turn[j].content and not turn[j].tool_calls),
                None,
            )
            if final_idx is None:
                continue  # turn ended in a pending proposal (or is still running): no reply bubble, same as live
            serialized[final_idx]["turn_steps"] = [s.model_dump() for s in cls._turn_steps_since(turn, 0)]
            serialized[final_idx]["rejected_proposals"] = [
                p.model_dump(mode="json") for p in cls._rejected_proposals_since(turn, 0)
            ]
        if not action_bubbles:
            return serialized
        merged: list[dict] = []
        for i, entry in enumerate(serialized):
            merged.append(entry)
            if i in action_bubbles:
                merged.append(action_bubbles[i])
        return merged

    def safety_snapshot_text_and_params(self, session: Session):
        snapshot = compute_safety_snapshot(session.context.live_params)
        return snapshot.as_text(), snapshot.params

    @staticmethod
    def _log_episode(
        session: Session, message: str, pending: ValidatedProposal | None, rejected: list, turn_steps: list[TurnStep],
    ) -> str | None:
        outcome = "pending_confirmation" if pending is not None else ("proposed_rejected" if rejected else "answered")
        episode_id = rl_log.log_episode(
            session_id=session.session_id, user_problem=message,
            approaches_tried=[s.model_dump() for s in turn_steps], final_outcome=outcome,
        )
        session.pending_episode_id = episode_id if pending is not None else None
        return episode_id

    def send_message(
        self, session: Session, message: str,
    ) -> tuple[str | None, ValidatedProposal | None, list[ValidatedProposal], list[TurnStep], str | None]:
        """Drives one turn of the graph for a new user message."""
        self._require_not_rebooting(session)
        existing = session.graph.get_state(session.thread_config)
        if existing.values.get("pending_proposal") is not None:
            raise RuntimeError(
                "a proposal is pending confirmation/rejection on this session -- "
                "resolve it via /proposals before continuing the conversation"
            )

        prior_message_count = len(existing.values.get("messages") or [])

        if not existing.values:
            input_state = {
                "messages": [HumanMessage(content=message)],
                "session_id": session.session_id,
                "pending_proposal": None,
                "pending_tool_call_id": None,
                "remaining_tool_calls": None,
            }
        else:
            input_state = {"messages": [HumanMessage(content=message)]}

        result = session.graph.invoke(input_state, config=session.thread_config)
        rejected = self._rejected_proposals_since(result["messages"], prior_message_count)
        turn_steps = self._turn_steps_since(result["messages"], prior_message_count)

        if result.get("pending_proposal") is not None:
            pending = ValidatedProposal.model_validate(result["pending_proposal"])
            episode_id = self._log_episode(session, message, pending, rejected, turn_steps)
            return None, pending, rejected, turn_steps, episode_id

        final = result["messages"][-1]
        reply = final.content if isinstance(final, AIMessage) else str(final.content)
        return reply, None, rejected, turn_steps, self._log_episode(session, message, None, rejected, turn_steps)

    def stream_message(self, session: Session, message: str) -> Iterator[dict]:
        """Run one chat turn, yielding thinking steps as they happen and then the final reply."""
        self._require_not_rebooting(session)
        existing = session.graph.get_state(session.thread_config)
        if existing.values.get("pending_proposal") is not None:
            raise RuntimeError(
                "a proposal is pending confirmation/rejection on this session -- "
                "resolve it via /proposals before continuing the conversation"
            )

        prior_message_count = len(existing.values.get("messages") or [])

        if not existing.values:
            input_state = {
                "messages": [HumanMessage(content=message)],
                "session_id": session.session_id,
                "pending_proposal": None,
                "pending_tool_call_id": None,
                "remaining_tool_calls": None,
            }
        else:
            input_state = {"messages": [HumanMessage(content=message)]}

        emitted = 0
        final_chunk: dict = {}
        for chunk in session.graph.stream(input_state, config=session.thread_config, stream_mode="values"):
            final_chunk = chunk
            steps_so_far = self._turn_steps_since(chunk["messages"], prior_message_count)
            for step in steps_so_far[emitted:]:
                yield {"type": "step", "step": step}
            emitted = len(steps_so_far)

        rejected = self._rejected_proposals_since(final_chunk["messages"], prior_message_count)
        turn_steps = self._turn_steps_since(final_chunk["messages"], prior_message_count)

        if final_chunk.get("pending_proposal") is not None:
            pending = ValidatedProposal.model_validate(final_chunk["pending_proposal"])
            yield {
                "type": "final", "reply": None, "pending_proposal": pending,
                "rejected_proposals": rejected, "turn_steps": turn_steps,
                "episode_id": self._log_episode(session, message, pending, rejected, turn_steps),
            }
            return

        final_msg = final_chunk["messages"][-1]
        reply = final_msg.content if isinstance(final_msg, AIMessage) else str(final_msg.content)
        yield {
            "type": "final", "reply": reply, "pending_proposal": None,
            "rejected_proposals": rejected, "turn_steps": turn_steps,
            "episode_id": self._log_episode(session, message, None, rejected, turn_steps),
        }

    @staticmethod
    def _rejected_proposals_since(messages: list, prior_message_count: int) -> list[ValidatedProposal]:
        rejected: list[ValidatedProposal] = []
        for msg in messages[prior_message_count:]:
            if not isinstance(msg, ToolMessage) or msg.name != "propose_param_change":
                continue
            try:
                proposal = ValidatedProposal.model_validate_json(msg.content)
            except (ValueError, TypeError):
                continue  # not a ValidatedProposal payload (e.g. a malformed-call error string)
            if not proposal.accepted:
                rejected.append(proposal)
        return rejected

    @staticmethod
    def _turn_steps_since(messages: list, prior_message_count: int) -> list[TurnStep]:
        calls_by_id: dict[str, dict] = {}
        steps: list[TurnStep] = []
        for msg in messages[prior_message_count:]:
            if isinstance(msg, AIMessage):
                if msg.content:
                    steps.append(TurnStep(stage="thinking", status="ok", detail=str(msg.content)))
                for call in msg.tool_calls or []:
                    calls_by_id[call["id"]] = call
            elif isinstance(msg, ToolMessage):
                call = calls_by_id.get(msg.tool_call_id)
                name = call["name"] if call else (msg.name or "unknown")
                content = str(msg.content)
                status = "ok"
                if name == "propose_param_change":
                    try:
                        status = "ok" if ValidatedProposal.model_validate_json(content).accepted else "blocked"
                    except (ValueError, TypeError):
                        status = "error"
                elif content.lower().startswith(("error", "notfound")):
                    status = "error"
                steps.append(TurnStep(stage="tool_call", tool_name=name, status=status, detail=content))
        return steps

    def resolve_proposal(
        self, session: Session, proposal_id: str, decision: str, reason: str | None = None,
    ) -> tuple[str, str, list[TurnStep], str | None]:
        """Apply the user's confirm/reject decision to a pending proposal and return the outcome."""
        state = session.graph.get_state(session.thread_config)
        pending = state.values.get("pending_proposal")
        if pending is not None and pending.get("proposal_id") == proposal_id:
            if decision == "confirm":
                self.refresh_live_params(session)

            result = session.graph.invoke(
                Command(resume={"decision": decision, "reason": reason}), config=session.thread_config,
            )

            tool_messages = [
                m for m in result["messages"]
                if isinstance(m, ToolMessage) and m.name == "propose_param_change"
            ]
            detail = tool_messages[-1].content if tool_messages else ""
            steps = [TurnStep.model_validate(d) for d in (result.get("last_action_steps") or [])]
        else:
            proposal = session.context.pending_proposals.get(proposal_id)
            if proposal is None:
                raise KeyError(f"no pending proposal with id {proposal_id} on this session")

            if decision == "confirm":
                self.refresh_live_params(session)
                detail, steps = apply_confirmed_write(session.context, proposal)
            else:
                session.context.audit_logger.log_reject(
                    session.session_id, proposal.param_name, reason=reason or "user rejected",
                )
                detail = f"The user rejected the proposed change to {proposal.param_name}"
                detail += f" ({reason}). No write was made." if reason else ". No write was made."
                steps = []
            session.context.pending_proposals.pop(proposal_id, None)

        if decision == "reject":
            outcome = "rejected"
        elif "no longer safe" in detail.lower() or detail.lower().startswith("blocked"):
            outcome = "blocked_at_write_time"
        else:
            outcome = "applied"
        if session.pending_episode_id is not None:
            rl_log.log_update(
                session.pending_episode_id,
                final_outcome="proposed_rejected" if outcome != "applied" else "proposed_accepted",
            )
            # Returned so the UI can ask "did this fix it?" about this episode.
            episode_id, session.pending_episode_id = session.pending_episode_id, None
        else:
            episode_id = None
        return outcome, detail, steps, episode_id

    def propose_rollback(self, session: Session, audit_event_id: int) -> ValidatedProposal:
        """Build a proposal that restores a previously applied change."""
        event = session.context.audit_logger.get_event(audit_event_id)
        if (
            event is None
            or event.session_id != session.session_id
            or event.event_type != AuditEventType.APPLY
        ):
            raise KeyError(f"no APPLY audit event with id {audit_event_id} on this session")
        if event.before_value is None:
            raise ValueError(f"audit event {audit_event_id} has no recorded before-value to roll back to")

        self.refresh_live_params(session)
        change = ProposedChange(
            param_name=event.param_name, new_value=event.before_value,
            reason=f"Rollback of change #{event.id} (reverting {event.after_value} back to {event.before_value})",
        )
        result = validate_proposed_change(change, session.context.live_params)
        proposal_id = str(uuid.uuid4())
        result = result.model_copy(update={"proposal_id": proposal_id})

        session.context.pending_proposals[proposal_id] = result
        session.context.audit_logger.log_proposal(session.session_id, result)
        return result

    def revise_proposal(self, session: Session, proposal_id: str, new_value: float) -> ValidatedProposal:
        """Re-validate a pending proposal with a new value."""
        pending = session.context.pending_proposals.get(proposal_id)
        if pending is None:
            raise KeyError(f"no pending proposal with id {proposal_id} on this session")

        self.refresh_live_params(session)
        change = ProposedChange(param_name=pending.param_name, new_value=new_value, reason=pending.reason)
        revised = validate_proposed_change(change, session.context.live_params)
        revised = revised.model_copy(update={"proposal_id": proposal_id})

        session.context.pending_proposals[proposal_id] = revised
        session.context.audit_logger.log_proposal(session.session_id, revised)
        session.graph.update_state(session.thread_config, {"pending_proposal": revised.model_dump()})
        return revised

    def start_compass_calibration(self, session: Session) -> ProcedureProposal:
        procedure = build_compass_calibration_procedure()
        session.context.pending_procedures[procedure.procedure_id] = procedure
        return procedure

    def resolve_procedure(self, session: Session, procedure_id: str, decision: str) -> dict:
        """Apply the user's confirm/reject decision to a pending procedure."""
        procedure = session.context.pending_procedures.get(procedure_id)
        if procedure is None:
            raise KeyError(f"no pending procedure with id {procedure_id} on this session")

        session.context.pending_procedures.pop(procedure_id, None)

        if decision != "confirm":
            return {"outcome": "rejected", "detail": f"User rejected the '{procedure.title}' procedure."}

        if procedure.title == COMPASS_CALIBRATION_TITLE:
            result = trigger_compass_calibration(session.context.vehicle_client)
            outcome = "triggered" if result["command_accepted"] else "trigger_not_acknowledged"
            return {"outcome": outcome, "detail": result}

        return {
            "outcome": "acknowledged",
            "detail": f"'{procedure.title}' has no automated step in this backend -- follow the listed steps manually.",
        }


session_manager = SessionManager()
