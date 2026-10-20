"""Firmware-aware metadata pipeline."""
from __future__ import annotations

import contextlib
import gzip
import json
import logging
import lzma
import os
import re
import select
import subprocess
import tempfile
import time
import urllib.request
import xml.etree.ElementTree as ET
from contextlib import AbstractContextManager
from pathlib import Path

from pymavlink import mavutil

from app.knowledge.metadata_parser import (
    extract_param_suffixes,
    parse_param_definitions_file,
    parse_pdef_xml,
    pdef_xml_commit,
)
from app.models.params import LiveParam, ParamDefinition
from app.models.vehicle import VehicleVersionInfo

logger = logging.getLogger(__name__)

DEFAULT_CACHE_ROOT = Path(os.environ.get("AP_COPILOT_HOME", Path.home() / ".ap-copilot")) / "metadata_cache"

SITL_PYTHON = os.environ.get("SITL_PYTHON", "/usr/bin/python3")

_MAV_TYPE_TO_VEHICLE: dict[int, str] = {}


def _build_mav_type_map() -> dict[int, str]:
    m = mavutil.mavlink
    copter_types = [
        "MAV_TYPE_QUADROTOR", "MAV_TYPE_HEXAROTOR", "MAV_TYPE_OCTOROTOR",
        "MAV_TYPE_TRICOPTER", "MAV_TYPE_COAXIAL", "MAV_TYPE_HELICOPTER",
        "MAV_TYPE_DODECAROTOR", "MAV_TYPE_DECAROTOR",
    ]
    plane_types = ["MAV_TYPE_FIXED_WING", "MAV_TYPE_VTOL_TAILSITTER_DUOROTOR",
                   "MAV_TYPE_VTOL_TAILSITTER_QUADROTOR", "MAV_TYPE_VTOL_TILTROTOR",
                   "MAV_TYPE_VTOL_FIXEDROTOR", "MAV_TYPE_VTOL_TAILSITTER",
                   "MAV_TYPE_VTOL_TILTWING", "MAV_TYPE_VTOL_RESERVED5"]
    rover_types = ["MAV_TYPE_GROUND_ROVER", "MAV_TYPE_SURFACE_BOAT"]
    sub_types = ["MAV_TYPE_SUBMARINE"]
    tracker_types = ["MAV_TYPE_ANTENNA_TRACKER"]
    blimp_types = ["MAV_TYPE_AIRSHIP"]

    mapping: dict[int, str] = {}
    for names, vehicle in (
        (copter_types, "ArduCopter"),
        (plane_types, "ArduPlane"),
        (rover_types, "Rover"),
        (sub_types, "ArduSub"),
        (tracker_types, "AntennaTracker"),
        (blimp_types, "Blimp"),
    ):
        for name in names:
            value = getattr(m, name, None)
            if value is not None:
                mapping[value] = vehicle
    return mapping


_FRAME_LABELS = {
    "MAV_TYPE_QUADROTOR": "Quadcopter", "MAV_TYPE_HEXAROTOR": "Hexacopter", "MAV_TYPE_OCTOROTOR": "Octocopter",
    "MAV_TYPE_TRICOPTER": "Tricopter", "MAV_TYPE_COAXIAL": "Coaxial copter", "MAV_TYPE_HELICOPTER": "Helicopter",
    "MAV_TYPE_DODECAROTOR": "Dodecacopter", "MAV_TYPE_DECAROTOR": "Decacopter",
    "MAV_TYPE_FIXED_WING": "Plane", "MAV_TYPE_VTOL_TAILSITTER_DUOROTOR": "VTOL plane",
    "MAV_TYPE_VTOL_TAILSITTER_QUADROTOR": "VTOL plane", "MAV_TYPE_VTOL_TILTROTOR": "VTOL plane",
    "MAV_TYPE_VTOL_FIXEDROTOR": "VTOL plane", "MAV_TYPE_VTOL_TAILSITTER": "VTOL plane",
    "MAV_TYPE_VTOL_TILTWING": "VTOL plane", "MAV_TYPE_GROUND_ROVER": "Rover", "MAV_TYPE_SURFACE_BOAT": "Boat",
    "MAV_TYPE_SUBMARINE": "Submarine", "MAV_TYPE_ANTENNA_TRACKER": "Antenna tracker", "MAV_TYPE_AIRSHIP": "Blimp",
}


def frame_label(mav_type: int) -> str | None:
    for name, label in _FRAME_LABELS.items():
        if getattr(mavutil.mavlink, name, None) == mav_type:
            return label
    return None


def vehicle_type_from_heartbeat(mav_type: int) -> str | None:
    global _MAV_TYPE_TO_VEHICLE
    if not _MAV_TYPE_TO_VEHICLE:
        _MAV_TYPE_TO_VEHICLE = _build_mav_type_map()
    return _MAV_TYPE_TO_VEHICLE.get(mav_type)


_GIT_PCT_RE = re.compile(rb"(Receiving objects|Unpacking objects|Resolving deltas):\s+(\d+)%")


def _git_fetch_with_progress(cmd: list[str], timeout: float, on_fraction) -> None:
    assert cmd[3] == "fetch", cmd
    proc = subprocess.Popen(
        [*cmd[:4], "--progress", *cmd[4:]], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    deadline = time.time() + timeout
    buf = b""
    tail = b""
    try:
        while True:
            if time.time() > deadline:
                proc.kill()
                proc.wait()
                raise subprocess.TimeoutExpired(cmd, timeout)
            ready, _, _ = select.select([proc.stderr], [], [], 1.0)
            if ready:
                chunk = os.read(proc.stderr.fileno(), 4096)
                if not chunk:
                    break
                buf += chunk
                tail = (tail + chunk)[-2000:]
                *parts, buf = re.split(rb"[\r\n]", buf)
                for part in parts:
                    m = _GIT_PCT_RE.search(part)
                    if m:
                        pct = int(m.group(2)) / 100
                        on_fraction(0.9 + pct * 0.1 if m.group(1) == b"Resolving deltas" else pct * 0.9)
            elif proc.poll() is not None:
                break
        if proc.wait() != 0:
            raise subprocess.CalledProcessError(proc.returncode, cmd, stderr=tail.decode(errors="ignore"))
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


class UnsupportedAutopilotError(ConnectionError):
    def __init__(self, firmware_name: str):
        super().__init__(
            f"the connected flight controller is running {firmware_name}, not ArduPilot. AP-Copilot only "
            "supports ArduPilot (ArduCopter/ArduPlane/Rover/ArduSub): its parameter names, documentation and "
            "safety validation are ArduPilot-specific. Flash ArduPilot firmware to this board (e.g. with "
            "Mission Planner or QGroundControl), then connect again."
        )


def autopilot_name(autopilot: int) -> str:
    return {12: "PX4", 0: "a generic MAVLink autopilot", 8: "an unidentified autopilot"}.get(
        autopilot, f"an unsupported autopilot (MAV_AUTOPILOT {autopilot})",
    )


def fetch_autopilot_version(
    conn: mavutil.mavfile, timeout: float = 30.0, lock: AbstractContextManager | None = None,
) -> VehicleVersionInfo:
    """Read AUTOPILOT_VERSION; refuses firmware that is not ArduPilot."""
    lock = lock if lock is not None else contextlib.nullcontext()
    with lock:
        hb = conn.recv_match(type="HEARTBEAT", blocking=True, timeout=timeout)
        if hb is None:
            raise TimeoutError("no HEARTBEAT received")
        mav_type = hb.type
        autopilot = getattr(hb, "autopilot", mavutil.mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA)
        if autopilot != mavutil.mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA:
            # Parameter names and validation here are ArduPilot-specific
            raise UnsupportedAutopilotError(autopilot_name(autopilot))

        vehicle_type = vehicle_type_from_heartbeat(mav_type)
        if vehicle_type is None:
            raise ValueError(f"unrecognized HEARTBEAT.type={mav_type}, cannot map to a vehicle type")

        conn.mav.command_long_send(
            conn.target_system, conn.target_component,
            mavutil.mavlink.MAV_CMD_REQUEST_MESSAGE, 0,
            mavutil.mavlink.MAVLINK_MSG_ID_AUTOPILOT_VERSION, 0, 0, 0, 0, 0, 0,
        )
        msg = conn.recv_match(type="AUTOPILOT_VERSION", blocking=True, timeout=timeout)
        if msg is None:
            raise TimeoutError("no AUTOPILOT_VERSION received")

    sw = msg.flight_sw_version
    flight_sw_version = f"{(sw >> 24) & 0xFF}.{(sw >> 16) & 0xFF}.{(sw >> 8) & 0xFF}"

    git_bytes = bytes(msg.flight_custom_version).rstrip(b"\x00")
    git_hash = git_bytes.decode("ascii", errors="ignore") or None

    return VehicleVersionInfo(
        vehicle_type=vehicle_type,
        mav_type=mav_type,
        board_type=msg.board_version,
        flight_sw_version=flight_sw_version,
        git_hash=git_hash,
    )


_PARAM_REQUEST_READ_BATCH_SIZE = 8
KEEPALIVE_INTERVAL_S = 1.0  # GCS heartbeat cadence while a long parameter sweep holds the connection lock


def fetch_live_param_values(
    conn: mavutil.mavfile, timeout: float = 90.0, max_retry_rounds: int = 5, lock: AbstractContextManager | None = None,
    keepalive=None,
) -> dict[str, float]:
    """Read every parameter from the vehicle, re-requesting dropped ones by index."""
    import time

    lock = lock if lock is not None else contextlib.nullcontext()
    with lock:
        conn.mav.param_request_list_send(conn.target_system, conn.target_component)
        values: dict[str, float] = {}
        received_indices: set[int] = set()
        expected_count: int | None = None
        deadline = time.time() + timeout

        last_beat = time.time()

        def _drain() -> None:
            nonlocal expected_count, last_beat
            while time.time() < deadline:
                if keepalive is not None and time.time() - last_beat >= KEEPALIVE_INTERVAL_S:
                    keepalive()
                    last_beat = time.time()
                msg = conn.recv_match(type="PARAM_VALUE", blocking=True, timeout=2.0)
                if msg is None:
                    return
                expected_count = msg.param_count
                values[msg.param_id] = msg.param_value
                received_indices.add(msg.param_index)
                if len(received_indices) >= expected_count:
                    return

        _drain()

        for _ in range(max_retry_rounds):
            if expected_count is None or len(received_indices) >= expected_count or time.time() >= deadline:
                break
            missing = sorted(set(range(expected_count)) - received_indices)
            for batch_start in range(0, len(missing), _PARAM_REQUEST_READ_BATCH_SIZE):
                if time.time() >= deadline:
                    break
                batch = missing[batch_start : batch_start + _PARAM_REQUEST_READ_BATCH_SIZE]
                for idx in batch:
                    if time.time() >= deadline:
                        break
                    conn.mav.param_request_read_send(conn.target_system, conn.target_component, b"", idx)
                _drain()

        if expected_count is None or len(received_indices) < expected_count:
            raise TimeoutError(
                f"only received {len(received_indices)}/{expected_count if expected_count else '?'} params "
                f"even after retrying missing ones individually -- the link may be too lossy or slow right now"
            )
        return values


class MetadataCache:
    """On-disk cache at `<root>/<vehicle_type>/<version_key>.json`."""

    def __init__(self, root: Path | str = DEFAULT_CACHE_ROOT):
        self.root = Path(root)

    def _path(self, vehicle_type: str, version_key: str) -> Path:
        return self.root / vehicle_type / f"{version_key}.json"

    def get(self, vehicle_type: str, version_key: str) -> dict[str, ParamDefinition] | None:
        path = self._path(vehicle_type, version_key)
        if not path.exists():
            return None
        raw = json.loads(path.read_text())
        return {name: ParamDefinition.model_validate(d) for name, d in raw.items()}

    def put(self, vehicle_type: str, version_key: str, definitions: dict[str, ParamDefinition]) -> None:
        path = self._path(vehicle_type, version_key)
        if path.exists():
            logger.info("metadata cache already has %s/%s, not overwriting", vehicle_type, version_key)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {name: d.model_dump() for name, d in definitions.items()}
        tmp_fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "w") as f:
                json.dump(payload, f)
            os.replace(tmp_path, path)
        finally:
            Path(tmp_path).unlink(missing_ok=True)


_PARAM_COMMENT_NAME_RE = re.compile(r"@Param(?:\{[^}]+\})?:\s*(\w+)")


def _index_param_comments(checkout_root: Path, vehicle_type: str) -> dict[str, set[tuple[str, int]]]:
    index: dict[str, set[tuple[str, int]]] = {}
    for base in (checkout_root / vehicle_type, checkout_root / "libraries"):
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.suffix not in (".cpp", ".h"):
                continue
            try:
                lines = path.read_text(errors="ignore").splitlines()
            except OSError:
                continue
            rel = str(path.relative_to(checkout_root))
            for line_no, line in enumerate(lines, start=1):
                m = _PARAM_COMMENT_NAME_RE.search(line)
                if m:
                    index.setdefault(m.group(1), set()).add((rel, line_no))
    return index


def _locate_param_source(
    checkout_root: Path, vehicle_type: str, suffix: str,
    index: dict[str, set[tuple[str, int]]] | None = None,
) -> tuple[str, int] | None:
    if index is None:
        index = _index_param_comments(checkout_root, vehicle_type)
    candidates = index.get(suffix, set())
    if len(candidates) == 1:
        return next(iter(candidates))
    return None


def _current_head_commit(checkout_root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(checkout_root), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip() or None
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return None


def attach_github_source_urls(
    definitions: dict[str, ParamDefinition],
    checkout_root: Path,
    vehicle_type: str,
    commit_ref: str,
    suffixes: dict[str, str],
    *,
    repo_url: str = "https://github.com/ArduPilot/ardupilot",
) -> None:
    """Attach each parameter's exact source-line GitHub URL."""
    index = _index_param_comments(checkout_root, vehicle_type)
    for name, definition in definitions.items():
        suffix = suffixes.get(name, name)
        location = _locate_param_source(checkout_root, vehicle_type, suffix, index)
        if location is None:
            continue
        rel_path, line_no = location
        definitions[name] = definition.model_copy(
            update={"github_source_url": f"{repo_url}/blob/{commit_ref}/{rel_path}#L{line_no}"},
        )


def generate_definitions_from_local_checkout(
    vehicle_type: str,
    ardupilot_root: str | Path,
    firmware_version: str,
) -> dict[str, ParamDefinition]:
    """Regenerates param metadata straight from the checked-out C++ source."""
    ardupilot_root = Path(ardupilot_root)
    script = ardupilot_root / "Tools/autotest/param_metadata/param_parse.py"
    if not script.exists():
        raise FileNotFoundError(f"param_parse.py not found at {script}")

    with tempfile.TemporaryDirectory() as tmp_dir:
        subprocess.run(
            [SITL_PYTHON, str(script), "--vehicle", vehicle_type, "--format", "json"],
            cwd=tmp_dir,
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        out_path = Path(tmp_dir) / "apm.pdef.json"
        if not out_path.exists():
            raise FileNotFoundError(f"param_parse.py did not produce {out_path}")
        definitions = parse_param_definitions_file(
            out_path, vehicle_types=[vehicle_type], firmware_version=firmware_version
        )

        commit_ref = _current_head_commit(ardupilot_root)
        if commit_ref is not None:
            raw_json = json.loads(out_path.read_text())
            suffixes = extract_param_suffixes(raw_json)
            attach_github_source_urls(definitions, ardupilot_root, vehicle_type, commit_ref, suffixes)
        return definitions


MANIFEST_URL = "https://firmware.ardupilot.org/manifest.json.gz"
_MANIFEST_VEHICLE = {
    "ArduCopter": "Copter", "ArduPlane": "Plane", "Rover": "Rover", "ArduSub": "Sub",
    "AntennaTracker": "AntennaTracker", "Blimp": "Blimp",
}
# Release-pinned folders only: 'stable/' and 'latest/' move and would mislabel versions
_PINNED_PDEF_URL_RE = re.compile(r"/(stable|beta)-\d+\.\d+\.\d+/__METADATA__/apm\.pdef\.xml\.xz$")
_MANIFEST_TTL_S = 3600.0
_manifest_cache: tuple[float, dict] | None = None


def _load_manifest(timeout: float = 30.0) -> dict:
    global _manifest_cache
    if _manifest_cache is not None and time.time() - _manifest_cache[0] < _MANIFEST_TTL_S:
        return _manifest_cache[1]
    with urllib.request.urlopen(MANIFEST_URL, timeout=timeout) as resp:
        raw = resp.read(20_000_000)  # ~2 MB today; bounded
    manifest = json.loads(gzip.decompress(raw))
    _manifest_cache = (time.time(), manifest)
    return manifest


def find_official_pdef_url(manifest: dict, vehicle_type: str, git_hash: str) -> str | None:
    vehicle = _MANIFEST_VEHICLE.get(vehicle_type)
    prefix = git_hash.lower()
    urls = {
        e["parameters"] for e in manifest.get("firmware", [])
        if e.get("vehicletype") == vehicle and str(e.get("git-sha", "")).lower().startswith(prefix)
        and e.get("parameters") and _PINNED_PDEF_URL_RE.search(e["parameters"])
    }
    return next(iter(urls)) if len(urls) == 1 else None


def fetch_definitions_from_public_source(
    vehicle_type: str, version_info: VehicleVersionInfo, *, progress=None,
) -> dict[str, ParamDefinition] | None:
    """Official per-release apm.pdef.xml from firmware.ardupilot.org."""
    git_hash = version_info.git_hash
    if not git_hash:
        return None
    try:
        manifest = _load_manifest()
        url = find_official_pdef_url(manifest, vehicle_type, git_hash)
        if url is None:
            logger.info("no official per-release metadata published for %s@%s", vehicle_type, git_hash)
            return None
        if progress is not None:
            progress("download", 0.3)
        with urllib.request.urlopen(url, timeout=60) as resp:
            xml_text = lzma.decompress(resp.read(20_000_000), memlimit=200_000_000).decode("utf-8")
        commit = pdef_xml_commit(xml_text)
        # The file's own header must name the vehicle's commit
        if commit is None or not commit.startswith(git_hash.lower()):
            logger.warning("official metadata at %s is for commit %s, not %s; not using it", url, commit, git_hash)
            return None
        if progress is not None:
            progress("parse", None)
        definitions = parse_pdef_xml(xml_text, vehicle_type=vehicle_type, firmware_version=version_info.flight_sw_version)
        logger.info("loaded %d official parameter definitions from %s", len(definitions), url)
        return definitions or None
    except (OSError, ValueError, lzma.LZMAError, ET.ParseError, KeyError, json.JSONDecodeError) as e:
        logger.warning("official metadata fetch failed for %s@%s: %s", vehicle_type, git_hash, e)
        return None


DEFAULT_ARDUPILOT_REPO_URL = "https://github.com/ArduPilot/ardupilot.git"


def fetch_definitions_from_git_source(
    vehicle_type: str,
    version_info: VehicleVersionInfo,
    *,
    repo_url: str = DEFAULT_ARDUPILOT_REPO_URL,
    tmp_root: str | Path | None = None,
    fetch_timeout: float = 300,
    progress=None,
) -> dict[str, ParamDefinition] | None:
    """Version-pinned fetch via a shallow fetch of the vehicle's own git commit."""
    git_hash = version_info.git_hash
    if not git_hash:
        logger.info(
            "no git hash reported by vehicle for %s, cannot pin a version-exact "
            "source; falling back to read-only", vehicle_type,
        )
        return None

    # Vehicles report 8 hex characters; resolve the full SHA through official release tags
    if len(git_hash) < 40:
        from app.knowledge.firmware_sync import (
            list_release_tags,  # lazy: firmware_sync imports this module
        )

        try:
            matches = {sha for sha in list_release_tags(repo_url).values() if sha.startswith(git_hash.lower())}
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as e:
            logger.warning("could not list release tags to resolve %s: %s", git_hash, e)
            return None
        if len(matches) != 1:
            logger.info("short hash %s is not a unique official release commit; cannot pin metadata", git_hash)
            return None
        git_hash = matches.pop()

    if tmp_root is None:
        tmp_root = Path(os.environ.get("AP_COPILOT_HOME", Path.home() / ".ap-copilot")) / "tmp"
    Path(tmp_root).mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(dir=tmp_root) as tmp_dir:
        clone_dir = Path(tmp_dir) / "ardupilot"
        try:
            subprocess.run(["git", "init", str(clone_dir)], check=True, capture_output=True, text=True, timeout=30)
            subprocess.run(
                ["git", "-C", str(clone_dir), "remote", "add", "origin", repo_url],
                check=True, capture_output=True, text=True, timeout=30,
            )
            fetch_cmd = ["git", "-C", str(clone_dir), "fetch", "--depth", "1", "origin", git_hash]
            if progress is not None:
                _git_fetch_with_progress(fetch_cmd, fetch_timeout, lambda f: progress("download", f))
            else:
                subprocess.run(fetch_cmd, check=True, capture_output=True, text=True, timeout=fetch_timeout)
            subprocess.run(
                ["git", "-C", str(clone_dir), "checkout", "FETCH_HEAD"],
                check=True, capture_output=True, text=True, timeout=60,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logger.warning("git-pinned metadata fetch failed for %s@%s: %s", vehicle_type, git_hash, e)
            return None

        if progress is not None:
            progress("parse", None)
        try:
            return generate_definitions_from_local_checkout(vehicle_type, clone_dir, version_info.flight_sw_version)
        except Exception as e:  # noqa: BLE001
            logger.warning("param_parse against git-pinned checkout failed for %s@%s: %s", vehicle_type, git_hash, e)
            return None


def _checkout_matches(version_info: VehicleVersionInfo, ardupilot_root: str | Path) -> bool:
    head = _current_head_commit(Path(ardupilot_root))
    git_hash = version_info.git_hash
    if not (head and git_hash):
        return False
    return head.lower().startswith(git_hash.lower())


def get_param_definitions(
    version_info: VehicleVersionInfo,
    *,
    cache: MetadataCache | None = None,
    ardupilot_root: str | Path | None = None,
    allow_git_fetch: bool = True,
    trust_local_checkout: bool = False,
    progress=None,
) -> dict[str, ParamDefinition] | None:
    """Parameter definitions for a firmware: cache, matching checkout, official file, then git."""
    cache = cache or MetadataCache()
    vehicle_type = version_info.vehicle_type
    version_key = version_info.version_key

    cached = cache.get(vehicle_type, version_key)
    if cached is not None:
        return cached

    # Use a local checkout only when it is provably this firmware
    if ardupilot_root is not None and (trust_local_checkout or _checkout_matches(version_info, ardupilot_root)):
        try:
            definitions = generate_definitions_from_local_checkout(
                vehicle_type, ardupilot_root, version_info.flight_sw_version
            )
            cache.put(vehicle_type, version_key, definitions)
            return definitions
        except Exception as e:  # noqa: BLE001
            logger.warning("local-checkout metadata generation failed: %s", e)

    if not allow_git_fetch:  # offline/tests: no network strategies at all
        return None

    for fetch in (fetch_definitions_from_public_source, fetch_definitions_from_git_source):
        definitions = fetch(vehicle_type, version_info, progress=progress)
        if definitions is not None:
            cache.put(vehicle_type, version_key, definitions)
            return definitions
    return None


def reconcile(
    live_values: dict[str, float],
    definitions: dict[str, ParamDefinition] | None,
) -> dict[str, LiveParam]:
    """Intersects live vehicle params with known definitions."""
    definitions = definitions or {}
    return {
        name: LiveParam(name=name, current_value=value, definition=definitions.get(name))
        for name, value in live_values.items()
    }
