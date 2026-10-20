from app.comms import serial_ports


def test_list_ports_labels_by_id_and_skips_duplicates(monkeypatch):
    by_id = ["/dev/serial/by-id/usb-CubePilot_CubeOrange_0-if00", "/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A1-if00-port0"]
    monkeypatch.setattr(serial_ports.glob, "glob", lambda pat: {
        "/dev/serial/by-id/*": by_id, "/dev/ttyACM*": ["/dev/ttyACM0", "/dev/ttyACM1"], "/dev/ttyUSB*": [],
    }[pat])
    monkeypatch.setattr(
        serial_ports.os.path, "realpath",
        lambda p: "/dev/ttyACM0" if "CubeOrange" in p else ("/dev/ttyUSB0" if "FTDI" in p else p),
    )
    ports = serial_ports.list_ports()
    assert [(p["path"], p["label"], p["likely_fc"]) for p in ports] == [
        (by_id[0], "CubePilot CubeOrange", True),
        (by_id[1], "FTDI FT232R USB UART A1", False),
        ("/dev/ttyACM1", "ttyACM1", True),  # ttyACM0 is the by-id one: not listed twice
    ]


class _Conn:
    def __init__(self, answers):
        self.answers, self.mav, self.closed = answers, self, False

    def heartbeat_send(self, *a):
        pass

    def wait_heartbeat(self, timeout):
        return object() if self.answers else None

    def close(self):
        self.closed = True


def test_find_flight_controller_tries_likely_first_and_closes_each(monkeypatch):
    monkeypatch.setattr(serial_ports, "list_ports", lambda: [
        {"path": "/dev/ttyUSB0", "label": "x", "likely_fc": False},
        {"path": "/dev/ttyACM0", "label": "y", "likely_fc": True},
    ])
    conns = {"/dev/ttyUSB0": _Conn(False), "/dev/ttyACM0": _Conn(True)}
    monkeypatch.setattr(serial_ports.mavutil, "mavlink_connection", lambda path: conns[path])
    assert serial_ports.find_flight_controller(timeout_per_port=0.05) == "/dev/ttyACM0"
    assert conns["/dev/ttyACM0"].closed and not conns["/dev/ttyUSB0"].closed  # likely FC was tried first and won


def test_find_flight_controller_returns_none_and_skips_unopenable(monkeypatch):
    monkeypatch.setattr(serial_ports, "list_ports", lambda: [
        {"path": "/dev/ttyACM0", "label": "a", "likely_fc": True}, {"path": "/dev/ttyACM1", "label": "b", "likely_fc": True},
    ])
    silent = _Conn(False)

    def fake(path):
        if path == "/dev/ttyACM0":
            raise PermissionError(path)
        return silent

    monkeypatch.setattr(serial_ports.mavutil, "mavlink_connection", fake)
    assert serial_ports.find_flight_controller(timeout_per_port=0.05) is None and silent.closed


def test_port_holders_finds_other_processes_and_ignores_self(tmp_path, monkeypatch):
    import importlib
    import subprocess
    import sys

    from app.comms import mavlink_client

    real = importlib.import_module("app.comms.serial_ports")
    monkeypatch.undo()  # conftest stubs port_holders; this test needs the real scan
    serial_ports = real

    dev = tmp_path / "fake_tty"
    dev.write_text("")
    mine = dev.open()
    child = subprocess.Popen(
        [sys.executable, "-c", f"import time; f=open({str(dev)!r}); time.sleep(30)"], stdout=subprocess.DEVNULL,
    )
    try:
        import time

        for _ in range(50):
            holders = serial_ports.port_holders(str(dev))
            if holders:
                break
            time.sleep(0.1)
        assert [pid for pid, _ in holders] == [child.pid]
        assert serial_ports.port_holders(str(dev) + ",57600")  # ",baud" suffix tolerated
    finally:
        child.kill()
        child.wait()
        mine.close()
    assert serial_ports.port_holders(str(dev)) == []
    assert mavlink_client  # client imports the same helper


def test_connect_refuses_a_serial_port_another_process_holds(monkeypatch):
    import pytest

    from app.comms import mavlink_client

    monkeypatch.setattr(serial_ports, "port_holders", lambda p: [(4242, "uvicorn app.main:app")])
    opened = []
    monkeypatch.setattr(mavlink_client.mavutil, "mavlink_connection", lambda s: opened.append(s))
    with pytest.raises(ConnectionError, match=r"already open in another process: pid 4242"):
        mavlink_client.MavlinkVehicleClient("/dev/ttyACM0").connect()
    assert opened == []  # never touched the port
    mavlink_client.MavlinkVehicleClient("tcp:127.0.0.1:5760")  # non-serial strings are not checked


def test_auto_detect_skips_busy_ports(monkeypatch):
    monkeypatch.setattr(serial_ports, "list_ports", lambda: [{"path": "/dev/ttyACM0", "label": "a", "likely_fc": True}])
    monkeypatch.setattr(serial_ports, "port_holders", lambda p: [(1, "x")])
    monkeypatch.setattr(serial_ports.mavutil, "mavlink_connection", lambda p: (_ for _ in ()).throw(AssertionError("touched")))
    assert serial_ports.find_flight_controller(timeout_per_port=0.05) is None


def test_stable_port_path_prefers_by_id_alias_and_keeps_baud(monkeypatch):
    by_id = "/dev/serial/by-id/usb-Hex_ProfiCNC_CubeBlack_1-if00"
    monkeypatch.setattr(serial_ports.glob, "glob", lambda pat: [by_id])
    monkeypatch.setattr(serial_ports.os.path, "realpath", lambda p: "/dev/ttyACM0" if p in (by_id, "/dev/ttyACM0") else p)
    assert serial_ports.stable_port_path("/dev/ttyACM0") == by_id
    assert serial_ports.stable_port_path("/dev/ttyACM0,57600") == by_id + ",57600"
    assert serial_ports.stable_port_path(by_id) == by_id  # already stable
    assert serial_ports.stable_port_path("tcp:127.0.0.1:5760") == "tcp:127.0.0.1:5760"
    assert serial_ports.stable_port_path("/dev/ttyUSB3") == "/dev/ttyUSB3"  # no alias: unchanged


def test_abandoned_sessions_are_closed_at_startup_but_ended_ones_keep_their_time(tmp_path):
    from app.audit.session_store import SessionStore

    store = SessionStore(tmp_path / "h.sqlite3")
    store.start("dead", "ArduCopter", "4.6.3", False)
    store.start("done", "ArduCopter", "4.6.3", False)
    store.end("done")
    ended_before = store.get("done").ended_at
    assert store.end_orphans() == 1
    assert store.get("dead").ended_at is not None and store.get("done").ended_at == ended_before
    assert store.end_orphans() == 0  # idempotent


def test_startup_closes_orphans_only_when_not_skipped(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from app.api.session_manager import session_manager
    from app.main import app

    calls = []
    monkeypatch.setattr(session_manager.session_store, "end_orphans", lambda: calls.append(1) or 0)
    with TestClient(app):  # conftest sets AP_COPILOT_SKIP_ORPHAN_CLEANUP=1
        pass
    assert calls == []
    monkeypatch.delenv("AP_COPILOT_SKIP_ORPHAN_CLEANUP")
    with TestClient(app):
        pass
    assert calls == [1]


def test_friendly_label_drops_the_serial_number_and_board_label_covers_each_connection_kind(monkeypatch):
    assert serial_ports.friendly_label("usb-Hex_ProfiCNC_CubeBlack_0A1B2C3D4E5F60718293A4B5-if00") == "Hex ProfiCNC CubeBlack"
    assert serial_ports.friendly_label("usb-CubePilot_CubeOrange_0-if00") == "CubePilot CubeOrange"
    assert serial_ports.friendly_label("usb-FTDI_FT232R_USB_UART_A1B2C3D4-if00-port0") == "FTDI FT232R USB UART"
    assert serial_ports.board_label_for("tcp:127.0.0.1:5760", simulation=True) == "Simulator (SITL)"
    assert serial_ports.board_label_for("/dev/serial/by-id/usb-Hex_ProfiCNC_CubeBlack_0A1B2C3D4E5F60718293A4B5-if00") == "Hex ProfiCNC CubeBlack"
    assert serial_ports.board_label_for("tcp:10.0.0.5:5760") is None
