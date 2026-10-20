"""Real-shaped vehicle fixtures for the benchmark."""
from __future__ import annotations

import gzip
import json
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path

from app.comms.vehicle_client import VehicleClient
from app.models.params import LiveParam, ParamDefinition
from app.models.telemetry import CommandResult, ParamSetResult, TelemetryEvent
from app.models.vehicle import VehicleVersionInfo


def _def(name: str, **kwargs) -> ParamDefinition:
    return ParamDefinition(
        name=name, vehicle_types=["ArduCopter"], firmware_version="4.8.0",
        description=kwargs.pop("description", "real ArduCopter parameter"), **kwargs,
    )


_BASE_PARAMS: dict[str, tuple[float, ParamDefinition | None]] = {
    "ATC_ANG_RLL_P": (4.5, _def("ATC_ANG_RLL_P", min_value=3.0, max_value=12.0, description="Roll axis angle controller P gain")),
    "ATC_ANG_PIT_P": (4.5, _def("ATC_ANG_PIT_P", min_value=3.0, max_value=12.0, description="Pitch axis angle controller P gain")),
    "ATC_ANG_YAW_P": (4.5, _def("ATC_ANG_YAW_P", min_value=3.0, max_value=12.0, description="Yaw axis angle controller P gain")),
    "ATC_RAT_RLL_P": (0.135, _def("ATC_RAT_RLL_P", min_value=0.01, max_value=0.5, description="Roll axis rate controller P gain")),
    "ATC_RAT_PIT_P": (0.135, _def("ATC_RAT_PIT_P", min_value=0.01, max_value=0.5, description="Pitch axis rate controller P gain")),
    "BATT_LOW_VOLT": (10.5, _def("BATT_LOW_VOLT", min_value=0.0, max_value=60.0, unit="V", description="Battery low voltage failsafe threshold")),
    "BATT_CRT_VOLT": (9.6, _def("BATT_CRT_VOLT", min_value=0.0, max_value=60.0, unit="V", description="Battery critical voltage failsafe threshold")),
    "ARMING_SKIPCHK": (0.0, _def(
        "ARMING_SKIPCHK", reboot_required=False,
        bitmask={0: "All", 1: "Barometer", 2: "Compass", 3: "GPS Lock", 4: "INS", 5: "Voltage", 6: "Battery", 7: "Logging", 8: "Hardware", 9: "GPS Config"},
        description="Bitmask of arming checks to skip",
    )),
    "ARMING_REQUIRE": (1.0, _def("ARMING_REQUIRE", values={"0": "Disabled", "1": "Enabled (no min voltage)", "2": "Enabled (min voltage)"}, description="Arming requirement level")),
    "FENCE_ENABLE": (0.0, _def("FENCE_ENABLE", values={"0": "Disabled", "1": "Enabled"}, description="Enable fence")),
    "FENCE_TYPE": (3.0, _def("FENCE_TYPE", bitmask={0: "Max altitude", 1: "Circle", 2: "Polygon", 3: "Min altitude"}, description="Fence type bitmask")),
    "FENCE_ACTION": (1.0, _def("FENCE_ACTION", values={"0": "Report only", "1": "RTL or land", "2": "Always land", "4": "SmartRTL or RTL or land"}, description="Fence breach action")),
    "GPS_TYPE": (1.0, _def("GPS_TYPE", values={"0": "None", "1": "AUTO", "2": "uBlox", "5": "NMEA"}, description="GPS type")),
    "EK2_ENABLE": (0.0, _def("EK2_ENABLE", values={"0": "Disabled", "1": "Enabled"}, description="Enable EKF2")),
    "EK3_ENABLE": (1.0, _def("EK3_ENABLE", values={"0": "Disabled", "1": "Enabled"}, description="Enable EKF3")),
    "AHRS_EKF_TYPE": (3.0, _def("AHRS_EKF_TYPE", values={"0": "DCM", "2": "EKF2", "3": "EKF3", "10": "SITL"}, description="Which EKF is primary")),
    "CAM1_TYPE": (0.0, _def("CAM1_TYPE", values={"0": "None", "1": "Servo", "2": "Relay", "5": "MAVLink"}, description="How to trigger the camera")),
    "RC_FS_TIMEOUT": (1.0, _def("RC_FS_TIMEOUT", min_value=0.0, max_value=10.0, unit="s", description="RC failsafe hold time before triggering")),
    "MOT_SPIN_ARM": (0.1, _def("MOT_SPIN_ARM", min_value=0.0, max_value=0.3, description="Motor spin value on arming")),
    "MOT_SPIN_MIN": (0.15, _def("MOT_SPIN_MIN", min_value=0.0, max_value=0.3, description="Minimum motor spin value while armed")),
    "SCHED_LOOP_RATE": (400.0, _def("SCHED_LOOP_RATE", min_value=50, max_value=1000, unit="Hz", description="Main loop rate")),
    "WPNAV_SPEED": (500.0, _def("WPNAV_SPEED", min_value=20.0, max_value=2000.0, unit="cm/s", description="Waypoint horizontal speed")),
    "PILOT_SPEED_UP": (250.0, _def("PILOT_SPEED_UP", min_value=50.0, max_value=500.0, unit="cm/s", description="Max pilot-commanded climb rate")),
    "MYSTERY_VENDOR_PARAM": (42.0, None),
}


def _build(overrides: dict[str, float]) -> dict[str, LiveParam]:
    live: dict[str, LiveParam] = {}
    for name, (value, definition) in _BASE_PARAMS.items():
        value = overrides.get(name, value)
        live[name] = LiveParam(name=name, current_value=value, definition=definition)
    return live


FIXTURES: dict[str, dict[str, LiveParam]] = {
    "default_copter": _build({}),
    "pre_rename_arming_check": _build({}) | {
        "ARMING_CHECK": LiveParam(
            name="ARMING_CHECK", current_value=1.0,
            definition=_def("ARMING_CHECK", bitmask={0: "All"}, description="Bitmask of arming checks to run (pre-4.1 name)"),
        ),
    },
}
del FIXTURES["pre_rename_arming_check"]["ARMING_SKIPCHK"]


REAL_SNAPSHOT = Path(__file__).parent / "data" / "arducopter_4.6.3_92b0cd78_params.json.gz"
REAL_VEHICLE_INFO = {
    "vehicle_type": "ArduCopter", "firmware_version": "4.6.3", "git_hash": "92b0cd78",
    "mav_type": 2, "frame_label": "Quadcopter", "board_label": "Hex ProfiCNC CubeBlack",
}
_REAL_LIVE_VALUES: dict[str, float] = {
    "RTL_ALT": 1500.0, "ANGLE_MAX": 4500.0, "LOIT_SPEED": 1250.0, "MOT_THST_HOVER": 0.39, "LAND_SPEED": 50.0,
    "FENCE_ENABLE": 0.0, "FENCE_ALT_MAX": 100.0, "FENCE_RADIUS": 300.0, "BATT_FS_LOW_ACT": 2.0,
    "BATT_FS_CRT_ACT": 1.0, "BATT_LOW_VOLT": 10.5, "BATT_CRT_VOLT": 9.6, "FS_THR_ENABLE": 0.0, "FS_THR_VALUE": 975.0,
    "FS_EKF_ACTION": 2.0, "CAM1_TYPE": 0.0, "LOG_BITMASK": 176126.0, "PILOT_SPEED_UP": 250.0, "WPNAV_SPEED": 500.0,
    "RTL_ALT_FINAL": 0.0, "RTL_LOIT_TIME": 5000.0, "FS_GCS_ENABLE": 0.0, "ATC_ANG_RLL_P": 4.5, "MOT_SPIN_ARM": 0.1,
    "COMPASS_USE": 1.0, "EK3_ENABLE": 1.0, "SERIAL1_BAUD": 57.0,
}
REAL_ABSENT_UNTIL_REBOOT = ["CAM1_FEEDBAK_PIN", "CAM1_FEEDBAK_POL", "CAM1_RELAY_ON"]


@lru_cache(maxsize=1)
def real_definitions() -> dict[str, ParamDefinition]:
    raw = json.loads(gzip.decompress(REAL_SNAPSHOT.read_bytes()))
    return {name: ParamDefinition.model_validate(d) for name, d in raw.items()}


def _real_live() -> dict[str, LiveParam]:
    defs = real_definitions()
    return {
        name: LiveParam(name=name, current_value=value, definition=defs[name])
        for name, value in _REAL_LIVE_VALUES.items()
    }


FIXTURES["real_copter_463"] = _real_live()
# FIXTURE_CONTEXT: fixtures that carry the real corpus + connected-vehicle info.
FIXTURE_CONTEXT = {"real_copter_463": REAL_VEHICLE_INFO}


class FakeVehicleClient(VehicleClient):
    def __init__(self, statustext: list[tuple[int, str]] | None = None):
        self.set_param_calls: list[tuple[str, float]] = []
        self._statustext = statustext or []

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    @property
    def is_connected(self) -> bool:
        return True

    def get_autopilot_version(self) -> VehicleVersionInfo:
        return VehicleVersionInfo(vehicle_type="ArduCopter", mav_type=2, board_type=0, flight_sw_version="4.8.0")

    def stream_params(self) -> dict[str, float]:
        raise NotImplementedError("benchmark tasks construct LiveParam state directly, not via a param sweep")

    def set_param(self, name: str, value: float, timeout: float = 10.0) -> ParamSetResult:
        self.set_param_calls.append((name, value))
        return ParamSetResult(name=name, requested_value=value, acked_value=value, acked=True)

    def stream_telemetry(
        self, fields: list[str] | None = None, timeout: float = 1.0, max_wait: float | None = None,
    ) -> Iterator[TelemetryEvent]:
        if fields and "STATUSTEXT" not in fields:
            return
        for severity, text in self._statustext:
            yield TelemetryEvent(field="STATUSTEXT", value={"severity": severity, "text": text})

    def send_command(self, command: int, params: tuple[float, ...] = (), timeout: float = 5.0) -> CommandResult:
        raise NotImplementedError("no benchmark task issues a raw MAVLink command")

    def get_armed_state(self, timeout: float = 3.0) -> bool | None:
        return False  # benchmark fixtures always simulate a disarmed, ground-safe vehicle
