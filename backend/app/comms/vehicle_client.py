"""Vehicle Comms Layer abstract interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator

from app.models.telemetry import CommandResult, ParamSetResult, TelemetryEvent
from app.models.vehicle import VehicleVersionInfo


class VehicleClient(ABC):
    @abstractmethod
    def connect(self) -> None:
        """Establish the link and block until a HEARTBEAT is seen."""

    @abstractmethod
    def disconnect(self) -> None:
        """Close the link."""

    @property
    @abstractmethod
    def is_connected(self) -> bool: ...

    @abstractmethod
    def get_autopilot_version(self) -> VehicleVersionInfo:
        """Query AUTOPILOT_VERSION on every new connection; never cached across reconnects."""

    @abstractmethod
    def stream_params(self) -> dict[str, float]:
        """Full live PARAM_REQUEST_LIST/PARAM_VALUE sweep."""

    @abstractmethod
    def set_param(self, name: str, value: float, timeout: float = 10.0) -> ParamSetResult:
        """PARAM_SET + wait for the vehicle's PARAM_VALUE ack."""

    @abstractmethod
    def stream_telemetry(
        self, fields: list[str] | None = None, timeout: float = 1.0, max_wait: float | None = None,
    ) -> Iterator[TelemetryEvent]:
        """Yields telemetry events as they arrive."""

    @abstractmethod
    def send_command(self, command: int, params: tuple[float, ...] = (), timeout: float = 5.0) -> CommandResult:
        """MAV_CMD COMMAND_LONG + wait for COMMAND_ACK."""

    @abstractmethod
    def get_armed_state(self, timeout: float = 3.0) -> bool | None:
        """Armed state from a fresh HEARTBEAT; None means unconfirmed and must be treated as unsafe."""

    def recent_status_messages(self, count: int = 10) -> list[dict] | None:
        return None
