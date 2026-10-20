import pytest

from app.orchestrator.nim_client import DEFAULT_NIM_BASE_URL, get_nim_chat_model


def test_overrides_win_over_env(monkeypatch):
    monkeypatch.setenv("NIM_API_KEY", "env-key")
    monkeypatch.setenv("NIM_BASE_URL", "https://integrate.api.nvidia.com/v1")
    monkeypatch.setenv("NIM_MODEL", "env-model")

    model = get_nim_chat_model(
        api_key="user-key", base_url="https://api.openai.com/v1", model="gpt-5",
    )

    assert model.openai_api_key.get_secret_value() == "user-key"
    assert str(model.openai_api_base) == "https://api.openai.com/v1"
    assert model.model_name == "gpt-5"


def test_partial_override_falls_back_to_env_for_the_rest(monkeypatch):
    monkeypatch.setenv("NIM_API_KEY", "env-key")
    monkeypatch.setenv("NIM_BASE_URL", "https://integrate.api.nvidia.com/v1")
    monkeypatch.setenv("NIM_MODEL", "env-model")

    model = get_nim_chat_model(model="a-different-model")

    assert model.openai_api_key.get_secret_value() == "env-key"
    assert model.model_name == "a-different-model"


def test_no_override_uses_env_exactly_as_before(monkeypatch):
    monkeypatch.setenv("NIM_API_KEY", "env-key")
    monkeypatch.delenv("NIM_BASE_URL", raising=False)
    monkeypatch.setenv("NIM_MODEL", "env-model")

    model = get_nim_chat_model()

    assert model.openai_api_key.get_secret_value() == "env-key"
    assert str(model.openai_api_base) == DEFAULT_NIM_BASE_URL
    assert model.model_name == "env-model"


def test_missing_api_key_raises_actionable_error(monkeypatch):
    monkeypatch.delenv("NIM_API_KEY", raising=False)
    monkeypatch.setenv("NIM_MODEL", "env-model")

    with pytest.raises(RuntimeError, match="No API key configured"):
        get_nim_chat_model()


def test_missing_model_raises_actionable_error(monkeypatch):
    monkeypatch.setenv("NIM_API_KEY", "env-key")
    monkeypatch.delenv("NIM_MODEL", raising=False)

    with pytest.raises(RuntimeError, match="No model configured"):
        get_nim_chat_model()
