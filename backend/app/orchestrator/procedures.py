"""Concrete multi-step procedures."""
from __future__ import annotations

from pymavlink import mavutil

from app.orchestrator.tools import ProcedureProposal, StepSpec

COMPASS_CALIBRATION_TITLE = "Compass calibration"

COMPASS_CALIBRATION_STEPS: list[StepSpec] = [
    StepSpec(description="Move the vehicle away from other metal objects and magnetic interference.", manual=True),
    StepSpec(description="Ensure the vehicle is disarmed and safe to handle.", manual=True),
    StepSpec(
        description="Trigger compass calibration on the flight controller (MAV_CMD_DO_START_MAG_CAL).",
        manual=False,
    ),
    StepSpec(
        description="Rotate the vehicle slowly through all orientations (roll, pitch, yaw) "
                    "until the flight controller reports each compass's calibration as complete.",
        manual=True,
    ),
    StepSpec(description="Review the calibration report (fitness score per compass) before continuing to fly.", manual=True),
]


def build_compass_calibration_procedure() -> ProcedureProposal:
    import uuid

    return ProcedureProposal(
        procedure_id=str(uuid.uuid4()), title=COMPASS_CALIBRATION_TITLE, steps=list(COMPASS_CALIBRATION_STEPS),
    )


def trigger_compass_calibration(vehicle_client, retries: int = 4, retry_delay: float = 2.0) -> dict:
    """Sends MAV_CMD_DO_START_MAG_CAL."""
    import time

    last_result = None
    for attempt in range(retries):
        result = vehicle_client.send_command(mavutil.mavlink.MAV_CMD_DO_START_MAG_CAL, params=(0, 0, 0), timeout=5.0)
        last_result = result
        if result.accepted:
            break
        if attempt < retries - 1:
            time.sleep(retry_delay)
    return {"command_accepted": last_result.accepted, "result_code": last_result.result_code}
