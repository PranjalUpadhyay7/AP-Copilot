"""STATUSTEXT decoding helpers."""
from __future__ import annotations

import time
from collections import deque

from app.comms.vehicle_client import VehicleClient
from app.models.telemetry import TelemetryEvent

# MAV_SEVERITY enum values.
SEVERITY_LABELS = {
    0: "EMERGENCY", 1: "ALERT", 2: "CRITICAL", 3: "ERROR",
    4: "WARNING", 5: "NOTICE", 6: "INFO", 7: "DEBUG",
}


def decode_statustext(event: TelemetryEvent) -> dict | None:
    text = str(event.value.get("text", "")).rstrip("\x00").strip()
    if not text:
        return None
    severity = int(event.value.get("severity", 6))
    return {"severity": severity, "severity_label": SEVERITY_LABELS.get(severity, "UNKNOWN"), "text": text}


def collect_recent_statustext(
    vehicle_client: VehicleClient, *, window_s: float = 4.0, max_count: int = 10,
) -> list[dict]:
    entries: list[dict] = []
    for event in vehicle_client.stream_telemetry(fields=["STATUSTEXT"], timeout=0.5, max_wait=window_s):
        decoded = decode_statustext(event)
        if decoded is not None:
            entries.append(decoded)
        if len(entries) >= max_count:
            break
    return entries


class StatusTextBuffer:
    """Session-lifetime ring buffer of STATUSTEXT messages with repeat counts."""
    def __init__(self, maxlen: int = 200):
        self._entries: deque[dict] = deque(maxlen=maxlen)
        self._last_chunk: tuple[int, int] | None = None  # (id, chunk_seq) of the previous chunk

    def add(self, severity: int, text: str, chunk_id: int = 0, chunk_seq: int = 0, now: float | None = None) -> None:
        text = text.rstrip("\x00")  # keep boundary whitespace: it is meaningful between chunks
        if not text.strip():
            return
        now = time.time() if now is None else now
        continues = (
            chunk_id != 0 and self._entries and self._last_chunk is not None
            and self._last_chunk == (chunk_id, chunk_seq - 1)
        )
        self._last_chunk = (chunk_id, chunk_seq) if chunk_id != 0 else None
        if continues:
            self._entries[-1]["text"] += text
            self._entries[-1]["last_seen"] = now
            return
        text = text.lstrip() if chunk_id != 0 else text.strip()
        last = self._entries[-1] if self._entries else None
        if last is not None and last["severity"] == severity and last["text"].strip() == text.strip():
            last["count"] += 1
            last["last_seen"] = now
            return
        self._entries.append({"severity": severity, "text": text, "count": 1, "last_seen": now})

    def recent(self, count: int = 10, now: float | None = None) -> list[dict]:
        now = time.time() if now is None else now
        return [
            {
                "severity": e["severity"], "severity_label": SEVERITY_LABELS.get(e["severity"], "UNKNOWN"),
                "text": e["text"].strip(), "count": e["count"], "seconds_ago": round(now - e["last_seen"]),
            }
            for e in list(self._entries)[-count:]
        ]
