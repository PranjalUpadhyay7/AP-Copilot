from collections.abc import Iterator

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.audit.logger import AuditLogger
from app.comms.vehicle_client import VehicleClient
from app.models.params import LiveParam, ParamDefinition
from app.models.telemetry import CommandResult, ParamSetResult, TelemetryEvent
from app.models.vehicle import VehicleVersionInfo
from app.orchestrator.tools import RuntimeContext


class FakeVehicleClient(VehicleClient):
    def __init__(self):
        self.set_param_calls: list[tuple[str, float]] = []

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
        self.set_param_calls.append((name, value))
        return ParamSetResult(name=name, requested_value=value, acked_value=value, acked=True)

    def stream_telemetry(self, fields: list[str] | None = None, timeout: float = 1.0, max_wait: float | None = None) -> Iterator[TelemetryEvent]:
        return iter([])

    def send_command(self, command: int, params: tuple[float, ...] = (), timeout: float = 5.0) -> CommandResult:
        raise NotImplementedError

    def get_armed_state(self, timeout: float = 3.0) -> bool | None:
        return False  # test fakes default to a disarmed, ground-safe vehicle


def _def(name: str, **kwargs) -> ParamDefinition:
    return ParamDefinition(name=name, vehicle_types=["ArduCopter"], firmware_version="4.6.0", description="d", **kwargs)


@pytest.fixture
def live_params() -> dict[str, LiveParam]:
    return {
        "ATC_ANG_RLL_P": LiveParam(
            name="ATC_ANG_RLL_P", current_value=4.5,
            definition=_def("ATC_ANG_RLL_P", min_value=0.5, max_value=12.0),
        ),
        "ATC_ANG_PIT_P": LiveParam(
            name="ATC_ANG_PIT_P", current_value=4.5,
            definition=_def("ATC_ANG_PIT_P", min_value=0.5, max_value=12.0),
        ),
        "UNDOCUMENTED": LiveParam(name="UNDOCUMENTED", current_value=1.0, definition=None),
        "FENCE_ENABLE": LiveParam(
            name="FENCE_ENABLE", current_value=0.0,
            definition=_def("FENCE_ENABLE", values={"0": "Disabled", "1": "Enabled"}),
        ),
    }


@pytest.fixture
def context(live_params) -> RuntimeContext:
    return RuntimeContext(
        session_id="test-session",
        vehicle_client=FakeVehicleClient(),
        live_params=live_params,
        audit_logger=AuditLogger(db_path=":memory:"),
    )


@pytest.fixture
def checkpointer():
    return MemorySaver()


@pytest.fixture
def thread_config():
    return {"configurable": {"thread_id": "test-thread"}}
