from __future__ import annotations

import sqlite3

from app.audit.logger import _GENESIS_HASH, AuditLogger, _compute_hash


def _make_pre_hash_chain_db(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE auditevent (
            id INTEGER PRIMARY KEY,
            session_id VARCHAR NOT NULL,
            timestamp DATETIME NOT NULL,
            event_type VARCHAR NOT NULL,
            param_name VARCHAR NOT NULL,
            before_value FLOAT,
            after_value FLOAT,
            reason VARCHAR,
            criticality VARCHAR,
            reboot_required BOOLEAN NOT NULL,
            details_json VARCHAR
        )
        """
    )
    conn.execute(
        "INSERT INTO auditevent (session_id, timestamp, event_type, param_name, before_value, after_value, "
        "reason, criticality, reboot_required, details_json) VALUES "
        "('s1', '2026-01-01T00:00:00', 'PROPOSAL', 'ATC_ANG_RLL_P', 4.5, 6.0, 'tune it', 'critical', 0, NULL)"
    )
    conn.execute(
        "INSERT INTO auditevent (session_id, timestamp, event_type, param_name, before_value, after_value, "
        "reason, criticality, reboot_required, details_json) VALUES "
        "('s1', '2026-01-01T00:01:00', 'CONFIRM', 'ATC_ANG_RLL_P', NULL, NULL, NULL, NULL, 0, NULL)"
    )
    conn.commit()
    conn.close()


def test_opening_a_pre_hash_chain_db_does_not_raise(tmp_path):
    db_path = str(tmp_path / "old_audit.sqlite3")
    _make_pre_hash_chain_db(db_path)

    logger = AuditLogger(db_path=db_path)
    events = logger.get_events()
    assert len(events) == 2


def test_migration_backfills_a_real_verifiable_chain(tmp_path):
    db_path = str(tmp_path / "old_audit.sqlite3")
    _make_pre_hash_chain_db(db_path)

    logger = AuditLogger(db_path=db_path)
    intact, broken_at = logger.verify_chain()
    assert intact is True
    assert broken_at is None

    events = logger.get_events()
    assert events[0].prev_hash == _GENESIS_HASH
    assert events[0].hash == _compute_hash(events[0])
    assert events[1].prev_hash == events[0].hash
    assert events[1].hash == _compute_hash(events[1])


def test_new_events_chain_correctly_onto_the_backfilled_history(tmp_path):
    db_path = str(tmp_path / "old_audit.sqlite3")
    _make_pre_hash_chain_db(db_path)

    logger = AuditLogger(db_path=db_path)
    logger.log_reject("s1", "ATC_ANG_RLL_P", reason="test")

    intact, broken_at = logger.verify_chain()
    assert intact is True
    assert broken_at is None
    events = logger.get_events()
    assert len(events) == 3
    assert events[2].prev_hash == events[1].hash


def test_reopening_an_already_migrated_db_is_a_fast_no_op(tmp_path):
    db_path = str(tmp_path / "old_audit.sqlite3")
    _make_pre_hash_chain_db(db_path)

    AuditLogger(db_path=db_path)  # first open: migrates
    first_events = AuditLogger(db_path=db_path).get_events()  # second open: must not re-migrate/re-hash

    assert len(first_events) == 2
    intact, _ = AuditLogger(db_path=db_path).verify_chain()
    assert intact is True


def test_a_fresh_database_is_unaffected_by_the_migration_check(tmp_path):
    db_path = str(tmp_path / "fresh_audit.sqlite3")
    logger = AuditLogger(db_path=db_path)
    logger.log_confirm("s1", "SOME_PARAM")

    intact, broken_at = logger.verify_chain()
    assert intact is True
    assert broken_at is None
