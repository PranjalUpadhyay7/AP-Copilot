"""Critical-parameter classification."""
from __future__ import annotations

import re

from app.models.proposal import Criticality

_CRITICAL_PREFIXES = (
    "ARMING_",
    "FS_",       # all failsafe params
    "MOT_",      # motor/ESC
    "FENCE_",
    "COMPASS_",  # calibration-affecting
)

_CRITICAL_EXACT = frozenset({
    "EK2_ENABLE",
    "EK3_ENABLE",
    "AHRS_EKF_TYPE",
})

_CRITICAL_PATTERNS = (
    re.compile(r"^BATT\d*_(LOW|CRT)_(VOLT|MAH)$"),      # battery failsafe thresholds
    re.compile(r"^ATC_(RAT|ANG)_(RLL|PIT|YAW)_"),        # core attitude/rate PIDs
    re.compile(r"^RC\d*_FS_"),                           # per-channel RC failsafe
    re.compile(r"^RC_FS_"),                              # vehicle-level RC failsafe
    re.compile(r"^GPS\d*_TYPE$"),                        # GPS type (affects failsafe eligibility)
    re.compile(r"^GPS_(FAILSAFE|PRIMARY)"),
)

_REVIEW_SIGNAL_SUBSTRINGS = ("ARM", "FAIL", "_FS", "FS_")


def classify_criticality(name: str, *, reboot_required: bool = False) -> Criticality:
    if name in _CRITICAL_EXACT:
        return Criticality.CRITICAL
    if name.startswith(_CRITICAL_PREFIXES):
        return Criticality.CRITICAL
    if any(p.match(name) for p in _CRITICAL_PATTERNS):
        return Criticality.CRITICAL
    if reboot_required:
        return Criticality.MEDIUM
    return Criticality.LOW


def suggests_review(name: str, criticality: Criticality) -> bool:
    if criticality == Criticality.CRITICAL:
        return False
    return any(s in name for s in _REVIEW_SIGNAL_SUBSTRINGS)
