from app.knowledge.metadata_fetcher import MetadataCache, reconcile
from app.models.params import LiveParam, ParamDefinition


def _def(name: str) -> ParamDefinition:
    return ParamDefinition(
        name=name, vehicle_types=["ArduCopter"], firmware_version="4.6.0", description="d"
    )


def test_cache_roundtrip(tmp_path):
    cache = MetadataCache(root=tmp_path)
    assert cache.get("ArduCopter", "abc123") is None

    defs = {"ARMING_CHECK": _def("ARMING_CHECK")}
    cache.put("ArduCopter", "abc123", defs)

    loaded = cache.get("ArduCopter", "abc123")
    assert loaded is not None
    assert loaded["ARMING_CHECK"].description == "d"


def test_cache_never_overwrites(tmp_path):
    cache = MetadataCache(root=tmp_path)
    cache.put("ArduCopter", "v1", {"A": _def("A")})
    # A second put for the same version, with different content, must not overwrite.
    cache.put("ArduCopter", "v1", {"A": _def("A"), "B": _def("B")})
    loaded = cache.get("ArduCopter", "v1")
    assert set(loaded) == {"A"}


def test_cache_distinct_by_vehicle_type_and_version(tmp_path):
    cache = MetadataCache(root=tmp_path)
    cache.put("ArduCopter", "v1", {"A": _def("A")})
    cache.put("ArduPlane", "v1", {"B": _def("B")})
    cache.put("ArduCopter", "v2", {"C": _def("C")})

    assert set(cache.get("ArduCopter", "v1")) == {"A"}
    assert set(cache.get("ArduPlane", "v1")) == {"B"}
    assert set(cache.get("ArduCopter", "v2")) == {"C"}


def test_reconcile_flags_undocumented_params():
    live_values = {"ARMING_CHECK": 1.0, "MYSTERY_PARAM": 42.0}
    definitions = {"ARMING_CHECK": _def("ARMING_CHECK")}

    result = reconcile(live_values, definitions)

    assert isinstance(result["ARMING_CHECK"], LiveParam)
    assert result["ARMING_CHECK"].is_documented is True
    assert result["MYSTERY_PARAM"].is_documented is False
    assert result["MYSTERY_PARAM"].definition is None


def test_reconcile_with_no_definitions_at_all():
    result = reconcile({"X": 1.0}, None)
    assert result["X"].is_documented is False
