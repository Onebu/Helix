"""Server-side settings for optional Langfuse imports."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LangfuseSettings(BaseSettings):
    """Configuration loaded only from the ``HELIX_LANGFUSE_`` namespace."""

    model_config = SettingsConfigDict(env_prefix="HELIX_LANGFUSE_")

    base_url: str | None = None
    public_key: str | None = None
    secret_key: str | None = None
    connect_timeout_seconds: float = Field(default=5.0, gt=0)
    request_timeout_seconds: float = Field(default=30.0, gt=0)
    max_response_bytes: int = Field(default=10 * 1024 * 1024, gt=0)
    max_items: int = Field(default=1_000, gt=0)

    @property
    def enabled(self) -> bool:
        """Return whether all credentials required by the remote API are present."""

        return bool(self.base_url and self.public_key and self.secret_key)
