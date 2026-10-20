from collections.abc import Iterator

from app.comms.status_text import collect_recent_statustext, decode_statustext
from app.comms.vehicle_client import VehicleClient
from app.models.telemetry import CommandResult, ParamSetResult, TelemetryEvent
from app.models.vehicle import VehicleVersionInfo


def _statustext(severity: int, text: str) -> TelemetryEvent:
    return TelemetryEvent(field="STATUSTEXT", value={"severity": severity, "text": text})


class FakeVehicleClient(VehicleClient):
    def __init__(self, events: list[TelemetryEvent]):
        self._events = events

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    @property
    def is_connected(self) -> bool:
        return True

    def get_autopilot_version(self) -> VehicleVersionInfo:
        raise NotImplementedError

    def stream_params(self) -> dict[str, float]:
        raise NotImplementedError

    def set_param(self, name: str, value: float, timeout: float = 10.0) -> ParamSetResult:
        raise NotImplementedError

    def stream_telemetry(
        self, fields: list[str] | None = None, timeout: float = 1.0, max_wait: float | None = None,
    ) -> Iterator[TelemetryEvent]:
        yield from self._events

    def send_command(self, command: int, params: tuple[float, ...] = (), timeout: float = 5.0) -> CommandResult:
        raise NotImplementedError

    def get_armed_state(self, timeout: float = 3.0) -> bool | None:
        return False  # test fakes default to a disarmed, ground-safe vehicle


def test_decode_statustext_maps_severity_label():
    decoded = decode_statustext(_statustext(4, "PreArm: Compass not calibrated"))
    assert decoded == {"severity": 4, "severity_label": "WARNING", "text": "PreArm: Compass not calibrated"}


def test_decode_statustext_strips_null_padding():
    decoded = decode_statustext(_statustext(6, "GPS lock\x00\x00\x00\x00"))
    assert decoded["text"] == "GPS lock"


def test_decode_statustext_returns_none_for_blank_text():
    assert decode_statustext(_statustext(6, "   \x00\x00")) is None


def test_decode_statustext_unknown_severity_labeled_unknown():
    decoded = decode_statustext(_statustext(99, "weird"))
    assert decoded["severity_label"] == "UNKNOWN"


def test_collect_recent_statustext_returns_decoded_entries_in_order():
    client = FakeVehicleClient([
        _statustext(4, "PreArm: Compass not calibrated"),
        _statustext(3, "EKF variance"),
    ])
    entries = collect_recent_statustext(client)
    assert [e["text"] for e in entries] == ["PreArm: Compass not calibrated", "EKF variance"]


def test_collect_recent_statustext_skips_blank_entries():
    client = FakeVehicleClient([_statustext(6, "\x00\x00\x00"), _statustext(6, "real message")])
    entries = collect_recent_statustext(client)
    assert len(entries) == 1
    assert entries[0]["text"] == "real message"


def test_collect_recent_statustext_respects_max_count():
    client = FakeVehicleClient([_statustext(6, f"msg {i}") for i in range(5)])
    entries = collect_recent_statustext(client, max_count=2)
    assert len(entries) == 2


def test_collect_recent_statustext_empty_stream_returns_empty_list():
    client = FakeVehicleClient([])
    assert collect_recent_statustext(client) == []
