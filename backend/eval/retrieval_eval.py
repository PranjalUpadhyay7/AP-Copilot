"""Retrieval-quality benchmark (hit@5) against real parameter metadata."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.knowledge.metadata_fetcher import MetadataCache
from app.knowledge.rag_store import (
    build_hybrid_index_from_param_definitions,
    family_key,
    search_ardupilot_docs,
)
from app.models.params import ParamDefinition

K = 5

# (query, expected param names -- any one in the top K counts, why this case exists)
CASES: list[tuple[str, set[str], str]] = [
    ("strobe output of a camera feedback to pixhawk so mavlink shows it", {"CAM1_FEEDBAK_PIN", "CAM1_FEEDBAK_POL"}, "live miss: 17 searches, then 'no such parameter'"),
    ("camera feedback pin", {"CAM1_FEEDBAK_PIN"}, "BTN_FUNC1-4 outranked the real parameter"),
    ("camera hotshoe flash feedback polarity", {"CAM1_FEEDBAK_POL"}, "user's own words for the same feature"),
    ("polarity of the camera trigger signal high or low", {"CAM1_RELAY_ON", "CAM1_FEEDBAK_POL"}, "live: 'firmware does not expose a polarity parameter'"),
    ("hardware triggered camera relay output", {"CAM1_TYPE", "CAM1_RELAY_ON"}, "live: user setting up a hardware camera trigger"),
    ("kill switch", {"RC1_OPTION", "RC10_OPTION", "RC9_OPTION", "RC8_OPTION", "RC7_OPTION", "RC6_OPTION", "RC5_OPTION"}, "THR_KILL_* hid RCx_OPTION=31 (motor emergency stop)"),
    ("return to launch altitude", {"RTL_ALT"}, "control"),
    ("what happens when the radio signal is lost failsafe", {"FS_THR_ENABLE"}, "control"),
    ("which pre-arm checks are enabled", {"ARMING_SKIPCHK", "ARMING_CHECK"}, "control (parameter renamed across versions)"),
    ("distance between camera triggers", {"CAM1_TRIGG_DIST"}, "control"),
    ("battery low failsafe action", {"BATT_FS_LOW_ACT", "BATT_LOW_VOLT"}, "control"),
    ("how high should the vehicle fly during return to launch", {"RTL_ALT"}, "breadth"),
    ("land when the battery is critically low", {"BATT_FS_CRT_ACT"}, "breadth"),
    ("minimum battery voltage before failsafe", {"BATT_LOW_VOLT"}, "breadth"),
    ("what happens when the EKF loses its position estimate", {"FS_EKF_ACTION", "FS_EKF_THRESH"}, "breadth"),
    ("maximum lean angle the copter can tilt", {"ANGLE_MAX"}, "breadth"),
    ("how fast can the copter climb", {"PILOT_SPEED_UP"}, "breadth"),
    ("geofence maximum altitude", {"FENCE_ALT_MAX"}, "breadth"),
    ("allow arming without a GPS lock", {"ARMING_SKIPCHK", "ARMING_NEED_LOC", "ARMING_CHECK"}, "breadth"),
    ("telemetry port baud rate", {"SERIAL1_BAUD", "SERIAL2_BAUD"}, "breadth"),
    ("compass calibration offsets", {"COMPASS_OFS_X", "COMPASS_OFS_Y"}, "breadth"),
    ("motor spin speed when armed", {"MOT_SPIN_ARM"}, "breadth"),
    ("hover throttle", {"MOT_THST_HOVER"}, "breadth"),
    ("loiter mode speed", {"LOIT_SPEED"}, "breadth"),
    ("flight mode switch positions", {"FLTMODE1", "FLTMODE_CH"}, "breadth"),
    ("disable the safety switch", {"BRD_SAFETY_DEFLT"}, "breadth"),
    ("rangefinder maximum distance", {"RNGFND1_MAX_CM"}, "breadth"),
    ("which source does the EKF use for horizontal position", {"EK3_SRC1_POSXY"}, "breadth"),
    ("which messages are written to the log", {"LOG_BITMASK"}, "breadth"),
]


def load_definitions(path: str | None) -> tuple[dict[str, ParamDefinition], str]:
    if path:
        raw = json.loads(Path(path).read_text())
        return {n: ParamDefinition.model_validate(d) for n, d in raw.items()}, Path(path).stem
    files = sorted(MetadataCache().root.glob("ArduCopter/*.json"), key=lambda p: p.stat().st_mtime)
    if not files:
        raise SystemExit("no cached ArduCopter definitions found; connect once or run sync_firmware_metadata.py")
    return load_definitions(str(files[-1]))


def evaluate(definitions, version_key: str, search=search_ardupilot_docs) -> list[tuple[str, bool, int | None]]:
    index = build_hybrid_index_from_param_definitions(definitions, vehicle_type="ArduCopter", version_key=version_key)
    results = []
    for query, expected, _why in CASES:
        ranked = [c.source for c in search(query, index, k=K)]
        wanted = {family_key(e) for e in expected}
        rank = next((i + 1 for i, s in enumerate(ranked) if family_key(s) in wanted), None)
        results.append((query, rank is not None, rank))
    return results


if __name__ == "__main__":
    defs, key = load_definitions(sys.argv[1] if len(sys.argv) > 1 else None)
    rows = evaluate(defs, key)
    for (query, ok, rank), (_, _, why) in zip(rows, CASES, strict=True):
        print(f"{'PASS' if ok else 'MISS'}  rank={rank or '-':>2}  {query[:62]:62}  # {why[:50]}")
    print(f"\nhit@{K}: {sum(ok for _, ok, _ in rows)}/{len(rows)}")
