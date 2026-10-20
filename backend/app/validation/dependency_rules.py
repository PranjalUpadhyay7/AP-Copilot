"""Cross-parameter dependency rules."""
from __future__ import annotations

from pydantic import BaseModel

from app.models.proposal import DependencyWarning


class DependencyRule(BaseModel):
    trigger_param: str
    related_params: list[str]
    message: str


DEPENDENCY_RULES: list[DependencyRule] = [
    DependencyRule(
        trigger_param="EK3_ENABLE",
        related_params=["AHRS_EKF_TYPE", "EK2_ENABLE"],
        message="Changing the active EKF requires AHRS_EKF_TYPE to match, and only one EKF should be enabled.",
    ),
    DependencyRule(
        trigger_param="EK2_ENABLE",
        related_params=["AHRS_EKF_TYPE", "EK3_ENABLE"],
        message="Changing the active EKF requires AHRS_EKF_TYPE to match, and only one EKF should be enabled.",
    ),
    DependencyRule(
        trigger_param="AHRS_EKF_TYPE",
        related_params=["EK2_ENABLE", "EK3_ENABLE"],
        message="AHRS_EKF_TYPE selects which EKF version is active -- confirm the matching EK2_ENABLE/EK3_ENABLE is set.",
    ),
    DependencyRule(
        trigger_param="ARMING_SKIPCHK",
        related_params=["ARMING_REQUIRE"],
        message="Skipping arming checks changes what ARMING_REQUIRE actually enforces at arm time -- review both together.",
    ),
    DependencyRule(
        trigger_param="FENCE_ENABLE",
        related_params=["FENCE_TYPE", "FENCE_ACTION"],
        message="The fence only triggers for the shapes selected in FENCE_TYPE (bit 0 max altitude, bit 1 circle around home, bit 2 polygon/inclusion zones, bit 3 min altitude) and then does what FENCE_ACTION says -- check both, or enabling it may do nothing or the wrong thing.",
    ),
]


def get_dependency_warnings(param_name: str) -> list[DependencyWarning]:
    return [
        DependencyWarning(related_params=rule.related_params, message=rule.message)
        for rule in DEPENDENCY_RULES
        if rule.trigger_param == param_name
    ]
