import pytest

from app.orchestrator.tracing import configure_tracing, trace_metadata


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("LANGCHAIN_TRACING_V2", raising=False)
    assert configure_tracing() is False


def test_enabled_without_api_key_raises_loudly(monkeypatch):
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="LANGCHAIN_API_KEY"):
        configure_tracing()


def test_enabled_with_api_key_sets_project(monkeypatch):
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setenv("LANGCHAIN_API_KEY", "fake-key")
    monkeypatch.delenv("LANGCHAIN_PROJECT", raising=False)
    assert configure_tracing("my-project") is True
    import os
    assert os.environ["LANGCHAIN_PROJECT"] == "my-project"


def test_trace_metadata_shape():
    meta = trace_metadata("ArduCopter", "4.6.0")
    assert meta == {"vehicle_type": "ArduCopter", "firmware_version": "4.6.0"}
