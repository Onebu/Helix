import pytest

from api.integrations.langfuse.config import LangfuseSettings


@pytest.fixture(autouse=True)
def clear_langfuse_environment(monkeypatch):
    for name in (
        "HELIX_LANGFUSE_BASE_URL",
        "HELIX_LANGFUSE_PUBLIC_KEY",
        "HELIX_LANGFUSE_SECRET_KEY",
        "HELIX_LANGFUSE_CONNECT_TIMEOUT_SECONDS",
        "HELIX_LANGFUSE_REQUEST_TIMEOUT_SECONDS",
        "HELIX_LANGFUSE_MAX_RESPONSE_BYTES",
        "HELIX_LANGFUSE_MAX_ITEMS",
    ):
        monkeypatch.delenv(name, raising=False)


def test_settings_use_helix_langfuse_prefix(monkeypatch):
    monkeypatch.setenv("HELIX_LANGFUSE_BASE_URL", "https://cloud.langfuse.com")
    monkeypatch.setenv("HELIX_LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("HELIX_LANGFUSE_SECRET_KEY", "sk-test")

    settings = LangfuseSettings()

    assert settings.enabled is True
    assert settings.base_url == "https://cloud.langfuse.com"
    assert settings.public_key == "pk-test"
    assert settings.secret_key == "sk-test"


def test_settings_remain_disabled_when_credentials_are_incomplete(monkeypatch):
    monkeypatch.setenv("HELIX_LANGFUSE_BASE_URL", "https://cloud.langfuse.com")
    monkeypatch.setenv("HELIX_LANGFUSE_PUBLIC_KEY", "pk-test")

    assert LangfuseSettings().enabled is False


def test_settings_do_not_read_legacy_vendor_prefix(monkeypatch):
    monkeypatch.setenv("GENE_LANGFUSE_HOST", "https://legacy.example.com")
    monkeypatch.setenv("GENE_LANGFUSE_PUBLIC_KEY", "legacy-public")
    monkeypatch.setenv("GENE_LANGFUSE_SECRET_KEY", "legacy-secret")

    settings = LangfuseSettings()

    assert settings.enabled is False
    assert settings.base_url is None


def test_settings_have_bounded_defaults():
    settings = LangfuseSettings()

    assert settings.connect_timeout_seconds == 5.0
    assert settings.request_timeout_seconds == 30.0
    assert settings.max_response_bytes == 10 * 1024 * 1024
    assert settings.max_items == 1_000
