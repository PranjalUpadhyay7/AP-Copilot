"""Append-only session/change audit log."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import Enum

from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Session, SQLModel, create_engine, select

from app.models.proposal import ValidatedProposal

_GENESIS_HASH = "0" * 64


class AuditEventType(str, Enum):
    PROPOSAL = "proposal"
    CONFIRM = "confirm"
    REJECT = "reject"
    APPLY = "apply"
    REBOOT = "reboot"


class AuditEvent(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    session_id: str = Field(index=True)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    event_type: AuditEventType
    param_name: str
    before_value: float | None = None
    after_value: float | None = None
    reason: str | None = None
    criticality: str | None = None
    reboot_required: bool = False
    details_json: str | None = None
    prev_hash: str = Field(default=_GENESIS_HASH)
    hash: str = Field(default="")


def _compute_hash(event: AuditEvent) -> str:
    payload = "|".join([
        event.prev_hash,
        event.session_id,
        event.timestamp.replace(tzinfo=None).isoformat(),
        event.event_type.value,
        event.param_name,
        "" if event.before_value is None else repr(event.before_value),
        "" if event.after_value is None else repr(event.after_value),
        event.reason or "",
        event.criticality or "",
        str(event.reboot_required),
        event.details_json or "",
    ])
    return hashlib.sha256(payload.encode()).hexdigest()


def _migrate_add_hash_chain_columns(engine) -> None:
    with engine.connect() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(auditevent)").fetchall()}
        if not cols or not ({"prev_hash", "hash"} - cols):
            return
        if "prev_hash" not in cols:
            conn.exec_driver_sql(f"ALTER TABLE auditevent ADD COLUMN prev_hash TEXT DEFAULT '{_GENESIS_HASH}'")
        if "hash" not in cols:
            conn.exec_driver_sql("ALTER TABLE auditevent ADD COLUMN hash TEXT DEFAULT ''")
        conn.commit()

    with Session(engine) as session:
        events = list(session.exec(select(AuditEvent).order_by(AuditEvent.id)))
        prev = _GENESIS_HASH
        for event in events:
            event.prev_hash = prev
            event.hash = _compute_hash(event)
            session.add(event)
            prev = event.hash
        session.commit()


class AuditLogger:
    """Append-only audit log in SQLite; each event is hash-chained to the previous one."""
    def __init__(self, db_path: str = "ap_copilot_audit.db"):
        url = "sqlite://" if db_path == ":memory:" else f"sqlite:///{db_path}"
        engine_kwargs = (
            {"connect_args": {"check_same_thread": False}, "poolclass": StaticPool}
            if db_path == ":memory:" else {}
        )
        self._engine = create_engine(url, **engine_kwargs)
        SQLModel.metadata.create_all(self._engine)
        _migrate_add_hash_chain_columns(self._engine)

    def _insert(self, event: AuditEvent) -> None:
        with Session(self._engine) as session:
            last = session.exec(select(AuditEvent).order_by(AuditEvent.id.desc())).first()
            # Chaining makes any later edit or deletion detectable
            event.prev_hash = last.hash if last is not None else _GENESIS_HASH
            event.hash = _compute_hash(event)
            session.add(event)
            session.commit()

    def log_proposal(self, session_id: str, proposal: ValidatedProposal) -> None:
        details = {
            "accepted": proposal.accepted,
            "rejection_reason": proposal.rejection_reason.value if proposal.rejection_reason else None,
            "rejection_message": proposal.rejection_message,
        }
        self._insert(AuditEvent(
            session_id=session_id,
            event_type=AuditEventType.PROPOSAL,
            param_name=proposal.param_name,
            before_value=proposal.current_value,
            after_value=proposal.proposed_value,
            reason=proposal.reason,
            criticality=proposal.criticality.value if proposal.criticality else None,
            reboot_required=proposal.reboot_required,
            details_json=json.dumps(details),
        ))

    def log_confirm(self, session_id: str, param_name: str) -> None:
        self._insert(AuditEvent(session_id=session_id, event_type=AuditEventType.CONFIRM, param_name=param_name))

    def log_reboot(self, session_id: str, reason: str = "user-requested reboot from the UI") -> None:
        self._insert(AuditEvent(
            session_id=session_id, event_type=AuditEventType.REBOOT, param_name="REBOOT", reason=reason,
        ))

    def log_reject(self, session_id: str, param_name: str, reason: str | None = None) -> None:
        self._insert(AuditEvent(
            session_id=session_id, event_type=AuditEventType.REJECT, param_name=param_name, reason=reason,
        ))

    def log_apply(
        self, session_id: str, param_name: str, before_value: float, after_value: float,
        reboot_required: bool = False,
    ) -> None:
        self._insert(AuditEvent(
            session_id=session_id,
            event_type=AuditEventType.APPLY,
            param_name=param_name,
            before_value=before_value,
            after_value=after_value,
            reboot_required=reboot_required,
        ))

    def get_event(self, event_id: int) -> AuditEvent | None:
        with Session(self._engine) as session:
            return session.get(AuditEvent, event_id)

    def get_events(self, session_id: str | None = None) -> list[AuditEvent]:
        with Session(self._engine) as session:
            statement = select(AuditEvent).order_by(AuditEvent.id)
            if session_id is not None:
                statement = statement.where(AuditEvent.session_id == session_id)
            return list(session.exec(statement))

    def verify_chain(self) -> tuple[bool, int | None]:
        with Session(self._engine) as session:
            events = list(session.exec(select(AuditEvent).order_by(AuditEvent.id)))

        expected_prev = _GENESIS_HASH
        for event in events:
            if event.prev_hash != expected_prev:
                return False, event.id
            if _compute_hash(event) != event.hash:
                return False, event.id
            expected_prev = event.hash
        return True, None

    def export_json(self, session_id: str | None = None) -> str:
        """Export a session's events as JSON."""
        events = self.get_events(session_id)
        return json.dumps(
            [
                {
                    "id": e.id,
                    "session_id": e.session_id,
                    "timestamp": e.timestamp.isoformat(),
                    "event_type": e.event_type.value,
                    "param_name": e.param_name,
                    "before_value": e.before_value,
                    "after_value": e.after_value,
                    "reason": e.reason,
                    "criticality": e.criticality,
                    "reboot_required": e.reboot_required,
                    "details": json.loads(e.details_json) if e.details_json else None,
                    "prev_hash": e.prev_hash,
                    "hash": e.hash,
                }
                for e in events
            ],
            indent=2,
        )
