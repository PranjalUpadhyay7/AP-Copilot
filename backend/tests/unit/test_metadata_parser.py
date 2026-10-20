from app.knowledge.metadata_parser import parse_param_definitions


def test_parses_basic_fields():
    raw = {
        "ARMING_": {
            "ARMING_CHECK": {
                "Description": "Bitmask of arming checks",
                "DisplayName": "Arm Checks",
                "Bitmask": {"0": "All", "1": "Barometer"},
            },
            "ARMING_ACCTHRESH": {
                "Description": "Accelerometer error threshold",
                "Units": "m/s/s",
                "Increment": "0.01",
                "Range": {"low": "0.25", "high": "3.0"},
                "RebootRequired": "True",
            },
        },
        "json": {"version": 0},
    }

    defs = parse_param_definitions(raw, vehicle_types=["ArduCopter"], firmware_version="4.6.0")

    assert set(defs) == {"ARMING_CHECK", "ARMING_ACCTHRESH"}

    check = defs["ARMING_CHECK"]
    assert check.description == "Bitmask of arming checks"
    assert check.bitmask == {0: "All", 1: "Barometer"}
    assert check.reboot_required is False
    assert check.vehicle_types == ["ArduCopter"]
    assert check.firmware_version == "4.6.0"

    thresh = defs["ARMING_ACCTHRESH"]
    assert thresh.unit == "m/s/s"
    assert thresh.increment == 0.01
    assert thresh.min_value == 0.25
    assert thresh.max_value == 3.0
    assert thresh.reboot_required is True


def test_skips_non_param_entries():
    raw = {"json": {"version": 0}, "EMPTY_GROUP": {}}
    defs = parse_param_definitions(raw, vehicle_types=["ArduPlane"], firmware_version="4.6.0")
    assert defs == {}


def test_values_and_no_range():
    raw = {
        "ALAND_": {
            "ALAND_ENABLE": {
                "Description": "enable Auto land script action",
                "Values": {"0": "Disabled", "1": "Enabled"},
            }
        }
    }
    defs = parse_param_definitions(raw, vehicle_types=["ArduCopter"], firmware_version="4.6.0")
    p = defs["ALAND_ENABLE"]
    assert p.values == {"0": "Disabled", "1": "Enabled"}
    assert p.min_value is None
    assert p.max_value is None
