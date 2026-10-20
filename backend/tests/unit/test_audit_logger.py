import inspect
import json

from sqlmodel import Session

from app.audit.logger import _GENESIS_HASH, AuditEvent, AuditEventType, AuditLogger
from app.models.proposal import Criticality, RejectionReason, ValidatedProposal


def _accepted_proposal() -> ValidatedProposal:
    return ValidatedProposal(
        param_name="ATC_ANG_RLL_P", current_value=4.5, proposed_value=6.0,
        reason="tighten roll response", accepted=True, criticality=Criticality.MEDIUM,
    )


def _rejected_proposal() -> ValidatedProposal:
    return ValidatedProposal(
        param_name="MYSTERY", current_value=None, proposed_value=5.0,
        reason="tune it", accepted=False, rejection_reason=RejectionReason.UNDOCUMENTED,
        rejection_message="no verified metadata",
    )


def test_log_proposal_recorded():
    logger = AuditLogger(db_path=":memory:")
    logger.log_proposal("session-1", _accepted_proposal())

    events = logger.get_events("session-1")
    assert len(events) == 1
    e = events[0]
    assert e.event_type == AuditEventType.PROPOSAL
    assert e.param_name == "ATC_ANG_RLL_P"
    assert e.before_value == 4.5
    assert e.after_value == 6.0
    assert e.criticality == "medium"


def test_log_rejected_proposal_records_rejection_details():
    logger = AuditLogger(db_path=":memory:")
    logger.log_proposal("session-1", _rejected_proposal())

    events = logger.get_events("session-1")
    details = json.loads(events[0].details_json)
    assert details["accepted"] is False
    assert details["rejection_reason"] == "undocumented"


def test_confirm_and_apply_logged_with_before_after_values():
    logger = AuditLogger(db_path=":memory:")
    logger.log_proposal("session-1", _accepted_proposal())
    logger.log_confirm("session-1", "ATC_ANG_RLL_P")
    logger.log_apply("session-1", "ATC_ANG_RLL_P", before_value=4.5, after_value=6.0)

    events = logger.get_events("session-1")
    assert [e.event_type for e in events] == [
        AuditEventType.PROPOSAL, AuditEventType.CONFIRM, AuditEventType.APPLY,
    ]
    apply_event = events[-1]
    assert apply_event.before_value == 4.5
    assert apply_event.after_value == 6.0


def test_reject_logged():
    logger = AuditLogger(db_path=":memory:")
    logger.log_proposal("session-1", _accepted_proposal())
    logger.log_reject("session-1", "ATC_ANG_RLL_P", reason="user declined")

    events = logger.get_events("session-1")
    reject_event = events[-1]
    assert reject_event.event_type == AuditEventType.REJECT
    assert reject_event.reason == "user declined"


def test_events_scoped_by_session_id():
    logger = AuditLogger(db_path=":memory:")
    logger.log_proposal("session-A", _accepted_proposal())
    logger.log_proposal("session-B", _accepted_proposal())

    assert len(logger.get_events("session-A")) == 1
    assert len(logger.get_events("session-B")) == 1
    assert len(logger.get_events()) == 2


def test_events_returned_in_insertion_order():
    logger = AuditLogger(db_path=":memory:")
    logger.log_confirm("session-1", "A")
    logger.log_confirm("session-1", "B")
    logger.log_confirm("session-1", "C")

    events = logger.get_events("session-1")
    assert [e.param_name for e in events] == ["A", "B", "C"]


def test_export_json_is_valid_and_ordered():
    logger = AuditLogger(db_path=":memory:")
    logger.log_proposal("session-1", _accepted_proposal())
    logger.log_confirm("session-1", "ATC_ANG_RLL_P")
    logger.log_apply("session-1", "ATC_ANG_RLL_P", before_value=4.5, after_value=6.0)

    exported = json.loads(logger.export_json("session-1"))
    assert len(exported) == 3
    assert [e["event_type"] for e in exported] == ["proposal", "confirm", "apply"]
    assert exported[2]["before_value"] == 4.5
    assert exported[2]["after_value"] == 6.0


def test_verify_chain_is_intact_on_an_empty_log():
    logger = AuditLogger(db_path=":memory:")
    assert logger.verify_chain() == (True, None)


def test_hash_chain_links_events_and_verifies_intact():
    logger = AuditLogger(db_path=":memory:")
    logger.log_proposal("session-1", _accepted_proposal())
    logger.log_confirm("session-1", "ATC_ANG_RLL_P")
    logger.log_apply("session-1", "ATC_ANG_RLL_P", before_value=4.5, after_value=6.0)

    events = logger.get_events("session-1")
    assert events[0].prev_hash == _GENESIS_HASH
    assert events[1].prev_hash == events[0].hash
    assert events[2].prev_hash == events[1].hash
    assert all(e.hash for e in events)

    assert logger.verify_chain() == (True, None)


def test_hash_chain_detects_a_directly_edited_row():
    logger = AuditLogger(db_path=":memory:")
    logger.log_proposal("session-1", _accepted_proposal())
    logger.log_confirm("session-1", "ATC_ANG_RLL_P")
    tampered_id = logger.get_events("session-1")[0].id

    with Session(logger._engine) as session:
        row = session.get(AuditEvent, tampered_id)
        row.before_value = 999.0  # tampered, hash not recomputed -- exactly what a raw SQL UPDATE would do
        session.add(row)
        session.commit()

    intact, broken_at = logger.verify_chain()
    assert intact is False
    assert broken_at == tampered_id


def test_hash_chain_detects_a_deleted_row():
    logger = AuditLogger(db_path=":memory:")
    logger.log_proposal("session-1", _accepted_proposal())
    logger.log_confirm("session-1", "ATC_ANG_RLL_P")
    logger.log_apply("session-1", "ATC_ANG_RLL_P", before_value=4.5, after_value=6.0)
    events = logger.get_events("session-1")
    middle_id, last_id = events[1].id, events[2].id

    with Session(logger._engine) as session:
        row = session.get(AuditEvent, middle_id)
        session.delete(row)
        session.commit()

    intact, broken_at = logger.verify_chain()
    assert intact is False
    assert broken_at == last_id


def test_append_only_no_mutation_api_exposed():
    public_methods = {
        name for name, _ in inspect.getmembers(AuditLogger, predicate=inspect.isfunction)
        if not name.startswith("_")
    }
    forbidden_verbs = ("update", "delete", "remove", "edit", "clear", "truncate")
    offenders = {m for m in public_methods if any(v in m.lower() for v in forbidden_verbs)}
    assert not offenders, f"AuditLogger must be append-only, found mutating methods: {offenders}"
