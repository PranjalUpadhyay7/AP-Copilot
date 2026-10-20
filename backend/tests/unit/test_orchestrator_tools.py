"""Unit tests for the tool dispatch layer."""
from collections.abc import Iterator

import pytest

from app.audit.logger import AuditLogger
from app.comms.vehicle_client import VehicleClient
from app.models.params import LiveParam, ParamDefinition
from app.models.telemetry import CommandResult, ParamSetResult, TelemetryEvent
from app.models.vehicle import VehicleVersionInfo
from app.orchestrator.tools import RuntimeContext, StepSpec, build_tools


class FakeVehicleClient(VehicleClient):
    def __init__(self):
        self.set_param_calls: list[tuple[str, float]] = []
        self.telemetry_events: list[TelemetryEvent] = []

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
        yield from self.telemetry_events

    def send_command(self, command: int, params: tuple[float, ...] = (), timeout: float = 5.0) -> CommandResult:
        raise NotImplementedError

    def get_armed_state(self, timeout: float = 3.0) -> bool | None:
        return False  # test fakes default to a disarmed, ground-safe vehicle


def _def(name: str, **kwargs) -> ParamDefinition:
    return ParamDefinition(name=name, vehicle_types=["ArduCopter"], firmware_version="4.6.0", description="d", **kwargs)


@pytest.fixture
def context():
    live_params = {
        "ATC_ANG_RLL_P": LiveParam(name="ATC_ANG_RLL_P", current_value=4.5, definition=_def("ATC_ANG_RLL_P", min_value=0.5, max_value=12.0)),
        "ARMING_SKIPCHK": LiveParam(name="ARMING_SKIPCHK", current_value=0.0, definition=_def("ARMING_SKIPCHK", bitmask={0: "All"})),
        "UNDOCUMENTED_PARAM": LiveParam(name="UNDOCUMENTED_PARAM", current_value=1.0, definition=None),
    }
    return RuntimeContext(
        session_id="test-session",
        vehicle_client=FakeVehicleClient(),
        live_params=live_params,
        audit_logger=AuditLogger(db_path=":memory:"),
    )


def _tool(context, name):
    tools = build_tools(context)
    return next(t for t in tools if t.name == name)


def test_get_current_param_found(context):
    tool = _tool(context, "get_current_param")
    result = tool.invoke({"name": "ATC_ANG_RLL_P"})
    assert result.current_value == 4.5


def test_get_current_param_not_found_returns_string_not_raise(context):
    tool = _tool(context, "get_current_param")
    result = tool.invoke({"name": "NOPE"})
    assert isinstance(result, str)
    assert "NotFound" in result


def test_list_params_matching_glob(context):
    tool = _tool(context, "list_params_matching")
    result = tool.invoke({"pattern": "ATC_*"})
    assert len(result) == 1
    assert result[0].name == "ATC_ANG_RLL_P"


def test_propose_param_change_accepted_never_touches_vehicle(context):
    tool = _tool(context, "propose_param_change")
    result = tool.invoke({"name": "ATC_ANG_RLL_P", "new_value": 6.0, "reason": "tighten roll"})

    assert result.accepted is True
    assert result.proposal_id is not None
    assert context.vehicle_client.set_param_calls == []


def test_propose_param_change_out_of_range_rejected_not_raised(context):
    tool = _tool(context, "propose_param_change")
    result = tool.invoke({"name": "ATC_ANG_RLL_P", "new_value": 9999.0, "reason": "way too much"})

    assert result.accepted is False
    assert context.vehicle_client.set_param_calls == []


def test_propose_param_change_hallucinated_param_rejected(context):
    tool = _tool(context, "propose_param_change")
    result = tool.invoke({"name": "TOTALLY_MADE_UP_PARAM", "new_value": 1.0, "reason": "the LLM guessed"})

    assert result.accepted is False
    assert result.rejection_reason.value == "not_found"


def test_propose_param_change_undocumented_param_rejected(context):
    tool = _tool(context, "propose_param_change")
    result = tool.invoke({"name": "UNDOCUMENTED_PARAM", "new_value": 2.0, "reason": "tune it"})

    assert result.accepted is False
    assert result.rejection_reason.value == "undocumented"


def test_every_proposal_logged_to_audit_regardless_of_outcome(context):
    tool = _tool(context, "propose_param_change")
    tool.invoke({"name": "ATC_ANG_RLL_P", "new_value": 6.0, "reason": "ok"})
    tool.invoke({"name": "NOPE", "new_value": 1.0, "reason": "bad"})

    events = context.audit_logger.get_events("test-session")
    assert len(events) == 2


def test_propose_multi_step_procedure_returns_id_and_steps(context):
    tool = _tool(context, "propose_multi_step_procedure")
    result = tool.invoke({
        "title": "Compass calibration",
        "steps": [{"description": "Rotate vehicle through all axes"}, {"description": "Wait for completion"}],
    })

    assert result.procedure_id in context.pending_procedures
    assert len(result.steps) == 2
    assert all(isinstance(s, StepSpec) for s in result.steps)


def test_request_vehicle_telemetry_reads_field(context):
    context.vehicle_client.telemetry_events = [
        TelemetryEvent(field="ATTITUDE", value={"roll": 0.1, "pitch": 0.2}),
    ]
    tool = _tool(context, "request_vehicle_telemetry")

    full = tool.invoke({"field": "ATTITUDE"})
    assert full == {"roll": 0.1, "pitch": 0.2}

    subfield = tool.invoke({"field": "ATTITUDE.roll"})
    assert subfield == {"roll": 0.1}


def test_request_vehicle_telemetry_never_calls_set_param(context):
    tool = _tool(context, "request_vehicle_telemetry")
    tool.invoke({"field": "ATTITUDE"})
    assert context.vehicle_client.set_param_calls == []


def test_search_ardupilot_docs_with_no_index_returns_empty(context):
    tool = _tool(context, "search_ardupilot_docs")
    result = tool.invoke({"query": "battery failsafe"})
    assert result == []


def test_get_recent_status_messages_returns_decoded_entries(context):
    context.vehicle_client.telemetry_events = [
        TelemetryEvent(field="STATUSTEXT", value={"severity": 4, "text": "PreArm: Compass not calibrated"}),
    ]
    tool = _tool(context, "get_recent_status_messages")
    result = tool.invoke({})
    assert result == [{"severity": 4, "severity_label": "WARNING", "text": "PreArm: Compass not calibrated"}]


def test_get_recent_status_messages_empty_returns_explanatory_string(context):
    tool = _tool(context, "get_recent_status_messages")
    result = tool.invoke({})
    assert isinstance(result, str)
    assert "No STATUSTEXT" in result


def test_get_recent_status_messages_never_calls_set_param(context):
    context.vehicle_client.telemetry_events = [
        TelemetryEvent(field="STATUSTEXT", value={"severity": 3, "text": "EKF variance"}),
    ]
    tool = _tool(context, "get_recent_status_messages")
    tool.invoke({})
    assert context.vehicle_client.set_param_calls == []
