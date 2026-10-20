import gzip
import io
import json
import lzma

import pytest

from app.knowledge import metadata_fetcher as mf
from app.knowledge.metadata_parser import parse_pdef_xml, pdef_xml_commit
from app.models.vehicle import VehicleVersionInfo

SHA = "fb773567896014da007bca58358704d4a0d8516f"
XML = f"""<?xml version="1.0" encoding="utf-8"?>
<!-- Generated from git tag Copter-4.7.2 ({SHA}) -->
<paramfile><vehicles><parameters name="ArduCopter">
  <param humanName="RTL" name="ArduCopter:RTL_SPEED" documentation="Speed &amp; more" user="Standard">
    <field name="Units">cm/s</field><field name="Range">0 2000</field><field name="Increment">50</field>
  </param>
</parameters></vehicles><libraries><parameters name="CAM">
  <param humanName="Camera feedback pin" name="CAM1_FEEDBAK_PIN" documentation="pin number" user="Standard">
    <values><value code="-1">Disabled</value><value code="50">AUX1</value></values>
    <field name="RebootRequired">True</field>
  </param>
  <param humanName="Opts" name="CAM1_OPTIONS" documentation="Camera options bitmask" user="Standard">
    <field name="Bitmask">0:Recording Starts at arming and stops at disarming,1:Other</field>
  </param>
</parameters></libraries></paramfile>"""


def test_parse_pdef_xml_matches_the_json_parsers_shape():
    defs = parse_pdef_xml(XML, vehicle_type="ArduCopter", firmware_version="4.7.2")
    assert set(defs) == {"RTL_SPEED", "CAM1_FEEDBAK_PIN", "CAM1_OPTIONS"}  # "ArduCopter:" prefix dropped
    rtl = defs["RTL_SPEED"]
    assert (rtl.unit, rtl.min_value, rtl.max_value, rtl.increment) == ("cm/s", 0.0, 2000.0, 50.0)
    assert rtl.description == "Speed & more" and rtl.vehicle_types == ["ArduCopter"]
    cam = defs["CAM1_FEEDBAK_PIN"]
    assert cam.values == {"-1": "Disabled", "50": "AUX1"} and cam.reboot_required is True
    assert defs["CAM1_OPTIONS"].bitmask == {0: "Recording Starts at arming and stops at disarming", 1: "Other"}
    assert pdef_xml_commit(XML) == SHA


def test_xml_with_dtd_or_entities_is_refused():
    with pytest.raises(ValueError, match="DTD"):
        parse_pdef_xml('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><paramfile/>', vehicle_type="ArduCopter", firmware_version="x")


def _manifest(*entries):
    return {"firmware": [dict(vehicletype="Copter", **e) for e in entries]}


def test_only_release_pinned_urls_for_this_exact_commit_are_used():
    pinned = "https://firmware.ardupilot.org/Copter/stable-4.7.2/__METADATA__/apm.pdef.xml.xz"
    moving = "https://firmware.ardupilot.org/Copter/stable/__METADATA__/apm.pdef.xml.xz"
    m = _manifest({"git-sha": SHA, "parameters": moving}, {"git-sha": SHA, "parameters": pinned},
                  {"git-sha": "aaaa" + SHA[4:], "parameters": "https://x/Copter/stable-4.7.1/__METADATA__/apm.pdef.xml.xz"})
    assert mf.find_official_pdef_url(m, "ArduCopter", "fb773567") == pinned  # moving "stable/" never used
    assert mf.find_official_pdef_url(_manifest({"git-sha": SHA, "parameters": moving}), "ArduCopter", "fb773567") is None
    assert mf.find_official_pdef_url(m, "ArduPlane", "fb773567") is None  # other vehicle
    assert mf.find_official_pdef_url(_manifest({"git-sha": SHA}), "ArduCopter", "fb773567") is None  # older stables: none published


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _serve(monkeypatch, xml_text, manifest):
    pinned = "https://firmware.ardupilot.org/Copter/stable-4.7.2/__METADATA__/apm.pdef.xml.xz"
    blobs = {mf.MANIFEST_URL: gzip.compress(json.dumps(manifest).encode()), pinned: lzma.compress(xml_text.encode())}
    monkeypatch.setattr(mf, "_manifest_cache", None)
    monkeypatch.setattr(mf.urllib.request, "urlopen", lambda url, timeout=0: _Resp(blobs[url]))
    return pinned


def _ver(h="fb773567"):
    return VehicleVersionInfo(vehicle_type="ArduCopter", mav_type=2, board_type=0, flight_sw_version="4.7.2", git_hash=h)


def test_fetch_uses_the_official_file_and_verifies_its_header_commit(monkeypatch):
    pinned = "https://firmware.ardupilot.org/Copter/stable-4.7.2/__METADATA__/apm.pdef.xml.xz"
    manifest = _manifest({"git-sha": SHA, "parameters": pinned})
    _serve(monkeypatch, XML, manifest)
    defs = mf.fetch_definitions_from_public_source("ArduCopter", _ver())
    assert set(defs) == {"RTL_SPEED", "CAM1_FEEDBAK_PIN", "CAM1_OPTIONS"}
    _serve(monkeypatch, XML.replace(SHA, "0" * 40), manifest)  # file claims a different commit
    assert mf.fetch_definitions_from_public_source("ArduCopter", _ver()) is None
    assert mf.fetch_definitions_from_public_source("ArduCopter", _ver(h=None)) is None  # no hash: never guess


def test_chain_prefers_official_metadata_over_the_slow_git_fetch(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(mf, "fetch_definitions_from_public_source", lambda vt, v, progress=None: calls.append("official") or {"X": object()})
    monkeypatch.setattr(mf, "fetch_definitions_from_git_source", lambda vt, v, progress=None: calls.append("git") or None)
    monkeypatch.setattr(mf.MetadataCache, "put", lambda self, *a: None)
    result = mf.get_param_definitions(_ver(), cache=mf.MetadataCache(tmp_path))
    assert set(result) == {"X"}
    assert calls == ["official"]  # the git fetch was never attempted
    calls.clear()
    assert mf.get_param_definitions(_ver(), cache=mf.MetadataCache(tmp_path), allow_git_fetch=False) is None
    assert calls == []  # offline mode: no network strategy at all
