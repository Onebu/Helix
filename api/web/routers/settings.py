"""Settings router -- read, update, and test configuration.

Provides:
- GET /api/settings: current config with masked API keys (reads DB + env cascade)
- PUT /api/settings: update config in DB Setting table, invalidate cache
- GET /api/settings/defaults: default GeneConfig values
- POST /api/settings/test-connection: validate provider API key
"""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.config.models import GeneConfig, GenerationConfig
from api.gateway.registry import PROVIDER_REGISTRY, SUPPORTED_PROVIDERS
from api.storage.encryption import get_encryptor
from api.storage.models import Setting, User
from api.web.auth import get_current_user
from api.web.deps import get_config, get_db_session
from api.web.schemas import (
    RoleConfig,
    SettingsResponse,
    SettingsUpdateRequest,
    TestConnectionRequest,
    TestConnectionResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# API key field names that get encrypted and stored in the "api_keys" Setting category
_API_KEY_FIELDS = {"openrouter_api_key", "gemini_api_key", "openai_api_key"}


def _mask_key(key: str | None) -> tuple[bool, str]:
    """Return (has_key, key_hint) for an API key value.

    Keys are never exposed in full -- only a masked hint showing the last 4 characters.
    """
    if not key:
        return False, ""
    return True, "\u2022\u2022\u2022\u2022" + key[-4:]


def _get_key_for_provider(provider: str, config: GeneConfig) -> str | None:
    """Look up the API key for a provider from config via the registry."""
    provider_config = PROVIDER_REGISTRY.get(provider)
    if provider_config is None:
        return None
    return getattr(config, provider_config.api_key_field, None)


def _build_settings_response(
    config: GeneConfig, *, has_db_keys: bool = False
) -> SettingsResponse:
    """Build a SettingsResponse from a GeneConfig instance."""
    roles = {}
    for role in ("meta", "target", "judge"):
        provider = getattr(config, f"{role}_provider")
        model = getattr(config, f"{role}_model")
        thinking_budget = getattr(config, f"{role}_thinking_budget", None)
        api_key = _get_key_for_provider(provider, config)
        has_key, key_hint = _mask_key(api_key)

        roles[role] = RoleConfig(
            provider=provider,
            model=model,
            has_key=has_key,
            key_hint=key_hint,
            thinking_budget=thinking_budget,
        )

    return SettingsResponse(
        meta=roles["meta"],
        target=roles["target"],
        judge=roles["judge"],
        concurrency_limit=config.concurrency_limit,
        generation=config.generation.model_dump(),
        providers=SUPPORTED_PROVIDERS,
        has_db_keys=has_db_keys,
    )


def _setting_filter(category: str, user_id: str | None):
    """Build a SQLAlchemy filter for a setting by category + user scope.

    Matches the user's own rows, or legacy rows with NULL user_id.
    """
    from sqlalchemy import or_

    base = Setting.category == category
    if user_id and user_id != "local":
        return base, or_(Setting.user_id == user_id, Setting.user_id.is_(None))
    return base, Setting.user_id.is_(None)


async def _get_setting(session: AsyncSession, category: str, user_id: str | None) -> Setting | None:
    """Fetch a setting row scoped to a user. Prefers user-owned over legacy NULL rows."""
    cat_filter, user_filter = _setting_filter(category, user_id)
    result = await session.execute(
        select(Setting).where(cat_filter, user_filter).order_by(Setting.user_id.desc())
    )
    return result.scalars().first()


async def _load_db_settings(session: AsyncSession, user_id: str | None = None) -> dict:
    """Load global_config, generation_defaults, and api_keys from DB into a flat dict.

    Settings are scoped per-user when auth is enabled. Falls back to legacy
    NULL user_id rows for backwards compatibility.
    API keys stored in the "api_keys" category are decrypted before merging.
    Returns a dict suitable for merging onto GeneConfig defaults.
    """
    merged: dict = {}

    global_row = await _get_setting(session, "global_config", user_id)
    if global_row is not None:
        merged.update(global_row.data)

    gen_row = await _get_setting(session, "generation_defaults", user_id)
    if gen_row is not None:
        merged["generation"] = gen_row.data

    # Load and decrypt API keys stored in DB
    keys_row = await _get_setting(session, "api_keys", user_id)
    if keys_row is not None:
        encryptor = get_encryptor()
        for field, encrypted_value in keys_row.data.items():
            if encrypted_value:
                decrypted = encryptor.decrypt(encrypted_value)
                if decrypted:
                    merged[field] = decrypted

    return merged


def _merge_db_onto_config(config: GeneConfig, db_data: dict) -> GeneConfig:
    """Merge DB setting values onto a GeneConfig, returning a new instance.

    DB values override GeneConfig defaults, but env vars still win
    (they're already baked into the config instance).
    For API key fields, DB values are only applied when the env var is not set
    (i.e. the config field is None), so env var > DB encrypted key > nothing.
    """
    if not db_data:
        return config

    update = {}
    for key, value in db_data.items():
        if key == "generation" and isinstance(value, dict):
            current_gen = config.generation.model_dump()
            current_gen.update(value)
            update["generation"] = GenerationConfig(**current_gen)
        elif key in _API_KEY_FIELDS:
            # Only apply DB key if env var key is not set
            if getattr(config, key, None) is None:
                update[key] = value
        else:
            update[key] = value

    return config.model_copy(update=update)


@router.get("/", response_model=SettingsResponse)
async def get_settings(
    config: GeneConfig = Depends(get_config),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> SettingsResponse:
    """Return current configuration with masked API keys.

    Reads DB Setting rows (including encrypted API keys) and merges onto
    GeneConfig defaults. Env var keys take priority over DB-stored keys.
    """
    db_data = await _load_db_settings(session, user.username)
    # Check if any API keys are stored in DB (before merge overrides them)
    has_db_keys = any(k in db_data for k in _API_KEY_FIELDS)
    merged = _merge_db_onto_config(config, db_data)
    return _build_settings_response(merged, has_db_keys=has_db_keys)


@router.get("/defaults", response_model=SettingsResponse)
async def get_defaults(user: User = Depends(get_current_user)) -> SettingsResponse:
    """Return GeneConfig default values (for 'Reset to Defaults' feature)."""
    defaults = GeneConfig()
    return _build_settings_response(defaults)


@router.put("/", response_model=SettingsResponse)
async def update_settings(
    body: SettingsUpdateRequest,
    config: GeneConfig = Depends(get_config),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> SettingsResponse:
    """Update configuration in database and return new settings.

    Only provided (non-None) fields are updated; others are preserved.
    API key fields are encrypted and stored in the "api_keys" Setting category.
    Non-key fields go to "global_config" as before.
    The config cache is cleared so the next request picks up new values.
    """
    update_data = body.model_dump(exclude_none=True)

    # Extract API key fields -- they get encrypted and stored separately
    key_updates = {k: update_data.pop(k) for k in list(update_data) if k in _API_KEY_FIELDS}

    # Split generation dict from other settings
    generation_update = update_data.pop("generation", None)

    # --- Upsert api_keys (encrypted) ---
    if key_updates:
        encryptor = get_encryptor()
        encrypted_keys = {}
        for field, value in key_updates.items():
            if value and not encryptor.is_encrypted(value):
                encrypted_keys[field] = encryptor.encrypt(value)
            elif value:
                encrypted_keys[field] = value  # Already encrypted, keep as-is

        keys_row = await _get_setting(session, "api_keys", user.username)

        if keys_row is not None:
            merged_keys = {**keys_row.data, **encrypted_keys}
            keys_row.data = merged_keys
        else:
            keys_row = Setting(category="api_keys", data=encrypted_keys, user_id=user.username)
            session.add(keys_row)

    # --- Upsert global_config ---
    if update_data:
        global_row = await _get_setting(session, "global_config", user.username)

        if global_row is not None:
            merged_data = {**global_row.data, **update_data}
            global_row.data = merged_data
        else:
            global_row = Setting(category="global_config", data=update_data, user_id=user.username)
            session.add(global_row)

    # --- Upsert generation_defaults ---
    if generation_update is not None:
        gen_row = await _get_setting(session, "generation_defaults", user.username)

        if gen_row is not None:
            merged_gen = {**gen_row.data, **generation_update}
            gen_row.data = merged_gen
        else:
            gen_row = Setting(category="generation_defaults", data=generation_update, user_id=user.username)
            session.add(gen_row)

    await session.commit()

    # Invalidate cached config so next request picks up fresh values
    get_config.cache_clear()

    # Re-read from DB and merge onto fresh config for response
    db_data = await _load_db_settings(session, user.username)
    has_db_keys = any(k in db_data for k in _API_KEY_FIELDS)
    fresh_config = GeneConfig()
    merged = _merge_db_onto_config(fresh_config, db_data)
    # Re-apply env var keys from original config (env vars take priority)
    for field_name in _API_KEY_FIELDS:
        env_val = getattr(config, field_name, None)
        if env_val:
            merged = merged.model_copy(update={field_name: env_val})

    return _build_settings_response(merged, has_db_keys=has_db_keys)


@router.post("/test-connection", response_model=TestConnectionResponse)
async def test_connection(body: TestConnectionRequest, user: User = Depends(get_current_user)) -> TestConnectionResponse:
    """Validate an API key by making a lightweight request to the provider.

    Attempts to list models from the provider. Returns success/failure.
    """
    if body.provider not in PROVIDER_REGISTRY:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider: {body.provider}. Supported: {', '.join(SUPPORTED_PROVIDERS)}",
        )

    provider_config = PROVIDER_REGISTRY[body.provider]

    # Build the models listing URL
    if body.provider == "gemini":
        url = "https://generativelanguage.googleapis.com/v1beta/models"
        params = {"key": body.api_key}
        headers = {}
    else:
        url = f"{provider_config.base_url}/models"
        params = None
        headers = {"Authorization": f"Bearer {body.api_key}"}
        if provider_config.default_headers:
            headers.update(provider_config.default_headers)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
        return TestConnectionResponse(success=True)
    except httpx.HTTPStatusError as exc:
        return TestConnectionResponse(
            success=False,
            error=f"HTTP {exc.response.status_code}: {exc.response.reason_phrase or 'Error'}",
        )
    except Exception as exc:
        return TestConnectionResponse(success=False, error=str(exc))
