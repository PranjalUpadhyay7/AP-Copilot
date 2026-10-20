"""pymavlink-backed VehicleClient."""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator

from pymavlink import mavutil

from app.comms.status_text import StatusTextBuffer
from app.comms.vehicle_client import VehicleClient
from app.knowledge.metadata_fetcher import (
    fetch_autopilot_version,
    fetch_live_param_values,
)
from app.models.telemetry import CommandResult, ParamSetResult, TelemetryEvent
from app.models.vehicle import VehicleVersionInfo

DEFAULT_SITL_CONNECTION = "tcp:127.0.0.1:5760"

_DEFAULT_TELEMETRY_FIELDS = [
    "ATTITUDE",
    "GLOBAL_POSITION_INT",
    "SYS_STATUS",
    "BATTERY_STATUS",
    "GPS_RAW_INT",
    "VFR_HUD",
    "HEARTBEAT",
    "STATUSTEXT",
]


logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_S = 1.0


def _gcs_heartbeat(conn) -> None:
    conn.mav.heartbeat_send(
        mavutil.mavlink.MAV_TYPE_GCS, mavutil.mavlink.MAV_AUTOPILOT_INVALID, 0, 0, mavutil.mavlink.MAV_STATE_ACTIVE,
    )


class MavlinkVehicleClient(VehicleClient):
    """pymavlink VehicleClient: one lock-serialised connection plus a ground-station heartbeat."""
    def __init__(self, connection_string: str = DEFAULT_SITL_CONNECTION):
        self.connection_string = connection_string
        self._conn: mavutil.mavfile | None = None
        self._conn_lock = threading.Lock()
        self._heartbeat_stop: threading.Event | None = None
        self._status_buffer = StatusTextBuffer()

    def connect(self, timeout: float = 30.0) -> None:
        """Open the link, announcing as a ground station until the vehicle's HEARTBEAT arrives."""
        if self.connection_string.startswith("/dev/"):
            from app.comms.serial_ports import port_holders

            holders = port_holders(self.connection_string)
            if holders:
                who = "; ".join(f"pid {pid} ({cmd})" for pid, cmd in holders)
                raise ConnectionError(
                    f"{self.connection_string.split(',')[0]} is already open in another process: {who}. Two programs "
                    "on one serial port each receive only part of the data. Close the other one (a second AP-Copilot "
                    "backend, Mission Planner, QGroundControl, mavproxy...) and try again."
                )
        self._conn = mavutil.mavlink_connection(self.connection_string)
        self._status_buffer = StatusTextBuffer()  # fresh per connection (a reboot starts a new client)
        self._conn.message_hooks.append(self._on_message)
        # Serial autopilots stay silent until a ground station speaks first
        deadline = time.time() + timeout
        hb = None
        try:
            while hb is None and time.time() < deadline:
                self._conn.mav.heartbeat_send(
                    mavutil.mavlink.MAV_TYPE_GCS, mavutil.mavlink.MAV_AUTOPILOT_INVALID, 0, 0,
                    mavutil.mavlink.MAV_STATE_ACTIVE,
                )
                hb = self._conn.wait_heartbeat(timeout=1)
        except OSError as e:
            self._conn.close()
            self._conn = None
            raise ConnectionError(
                f"lost the serial link to {self.connection_string} while connecting ({e}) -- the board may be "
                "rebooting or unplugged; wait a few seconds and try again"
            ) from e
        if hb is None:
            self._conn.close()
            self._conn = None
            raise TimeoutError(f"no HEARTBEAT from {self.connection_string} within {timeout:g}s")
        self._start_heartbeat()

    def _on_message(self, _conn, msg) -> None:
        if msg.get_type() == "STATUSTEXT":
            self._status_buffer.add(
                int(getattr(msg, "severity", 6)), str(getattr(msg, "text", "")),
                int(getattr(msg, "id", 0) or 0), int(getattr(msg, "chunk_seq", 0) or 0),
            )

    def recent_status_messages(self, count: int = 10) -> list[dict] | None:
        return self._status_buffer.recent(count)

    def _start_heartbeat(self) -> None:
        stop = threading.Event()
        conn = self._conn
        self._heartbeat_stop = stop

        def loop() -> None:
            while not stop.wait(HEARTBEAT_INTERVAL_S):
                if not self._conn_lock.acquire(timeout=0.5):
                    continue  # a long operation holds the lock; it sends its own beats
                try:
                    if stop.is_set() or self._conn is not conn:
                        return
                    _gcs_heartbeat(conn)
                except Exception as e:  # noqa: BLE001 -- link vanished (unplug/reboot): stop quietly
                    logger.debug("heartbeat thread stopping: %s", e)
                    return
                finally:
                    self._conn_lock.release()

        threading.Thread(target=loop, name="gcs-heartbeat", daemon=True).start()

    def disconnect(self) -> None:
        if self._heartbeat_stop is not None:
            self._heartbeat_stop.set()
            self._heartbeat_stop = None
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @property
    def is_connected(self) -> bool:
        return self._conn is not None

    def _require_conn(self) -> mavutil.mavfile:
        if self._conn is None:
            raise RuntimeError("not connected -- call connect() first")
        return self._conn

    def get_autopilot_version(self) -> VehicleVersionInfo:
        return fetch_autopilot_version(self._require_conn(), lock=self._conn_lock)

    def stream_params(self) -> dict[str, float]:
        conn = self._require_conn()
        return fetch_live_param_values(conn, lock=self._conn_lock, keepalive=lambda: _gcs_heartbeat(conn))

    def set_param(self, name: str, value: float, timeout: float = 10.0) -> ParamSetResult:
        conn = self._require_conn()
        with self._conn_lock:
            conn.param_set_send(name, value)

            deadline = time.time() + timeout
            while time.time() < deadline:
                msg = conn.recv_match(type="PARAM_VALUE", blocking=True, timeout=max(0.1, deadline - time.time()))
                if msg is None:
                    break
                if msg.param_id == name:
                    return ParamSetResult(name=name, requested_value=value, acked_value=msg.param_value, acked=True)
        return ParamSetResult(name=name, requested_value=value, acked_value=None, acked=False)

    def stream_telemetry(
        self, fields: list[str] | None = None, timeout: float = 1.0, max_wait: float | None = None,
    ) -> Iterator[TelemetryEvent]:
        conn = self._require_conn()
        wanted = fields if fields is not None else _DEFAULT_TELEMETRY_FIELDS
        deadline = time.time() + max_wait if max_wait is not None else None
        while deadline is None or time.time() < deadline:
            with self._conn_lock:
                # Lock per poll, never across the generator, or every other operation would starve
                msg = conn.recv_match(type=wanted, blocking=True, timeout=timeout)
            if msg is None:
                continue
            yield TelemetryEvent(field=msg.get_type(), value=msg.to_dict())

    def send_command(self, command: int, params: tuple[float, ...] = (), timeout: float = 5.0) -> CommandResult:
        """Send a COMMAND_LONG and wait for its COMMAND_ACK."""
        conn = self._require_conn()
        with self._conn_lock:
            padded = list(params) + [0.0] * (7 - len(params))
            conn.mav.command_long_send(conn.target_system, conn.target_component, command, 0, *padded[:7])

            msg = conn.recv_match(type="COMMAND_ACK", blocking=True, timeout=timeout)
        if msg is None or msg.command != command:
            return CommandResult(command=command, accepted=False, result_code=None)
        return CommandResult(
            command=command,
            accepted=msg.result == mavutil.mavlink.MAV_RESULT_ACCEPTED,
            result_code=msg.result,
        )

    def get_armed_state(self, timeout: float = 3.0) -> bool | None:
        conn = self._require_conn()
        with self._conn_lock:
            hb = conn.recv_match(type="HEARTBEAT", blocking=True, timeout=timeout)
        if hb is None:
            return None
        return bool(hb.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
