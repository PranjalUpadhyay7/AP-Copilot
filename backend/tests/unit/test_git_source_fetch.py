"""Unit tests for the git-pinned metadata fetch."""
import subprocess
from unittest.mock import patch

from app.knowledge.metadata_fetcher import fetch_definitions_from_git_source
from app.models.vehicle import VehicleVersionInfo


def _version(git_hash: str | None) -> VehicleVersionInfo:
    return VehicleVersionInfo(
        vehicle_type="ArduCopter", mav_type=2, board_type=0,
        flight_sw_version="4.6.0", git_hash=git_hash,
    )


def test_no_git_hash_returns_none_without_any_subprocess_call():
    with patch("subprocess.run") as mock_run:
        result = fetch_definitions_from_git_source("ArduCopter", _version(None))
    assert result is None
    mock_run.assert_not_called()


def test_git_fetch_failure_returns_none_not_raises():
    with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "git")):
        result = fetch_definitions_from_git_source("ArduCopter", _version("deadbeef"))
    assert result is None


def test_git_fetch_timeout_returns_none_not_raises():
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 60)):
        result = fetch_definitions_from_git_source("ArduCopter", _version("deadbeef"))
    assert result is None


def test_successful_checkout_delegates_to_local_checkout_generation():
    with patch("subprocess.run") as mock_run, patch(
        "app.knowledge.metadata_fetcher.generate_definitions_from_local_checkout"
    ) as mock_generate:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        mock_generate.return_value = {"ARMING_SKIPCHK": object()}

        result = fetch_definitions_from_git_source("ArduCopter", _version("a" * 40))

    assert "ARMING_SKIPCHK" in result
    mock_generate.assert_called_once()
    # exactly 4 git subprocess calls: init, remote add, fetch, checkout
    assert mock_run.call_count == 4
    fetch_call = mock_run.call_args_list[2].args[0]
    assert fetch_call[:2] == ["git", "-C"]
    assert "a" * 40 in fetch_call
