"""Prompt CRUD endpoints: list, get, create, update template, config.

Routes:
    GET  /              List all registered prompts (PromptSummary[])
    GET  /{prompt_id}   Get prompt detail with template text (PromptDetail)
    POST /              Register a new prompt (201 -> PromptSummary)
    PUT  /{prompt_id}/template   Update prompt template (PromptSummary)
    GET  /{prompt_id}/config     Get effective prompt config from DB
    PUT  /{prompt_id}/config     Update per-prompt config in DB PromptConfig table
"""

from __future__ import annotations

import logging

import jinja2
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.config.models import GeneConfig, GenerationConfig
from api.registry.models import PromptRegistration, VariableDefinition
from api.registry.schemas import PromptConfigSchema
from api.registry.service import PromptRegistry, _extract_anchor_variables
from api.storage.models import Prompt as PromptModel
from api.storage.models import PromptConfig
from api.web.deps import get_config, get_db_session, get_registry
from api.web.schemas import (
    AcceptVersionRequest,
    CreatePromptRequest,
    ExtractVariablesRequest,
    ExtractVariablesResponse,
    PromptConfigResponse,
    PromptDetail,
    PromptSummary,
    PromptVersionResponse,
    RoleConfigResponse,
    ToolMockerConfigResponse,
    UpdateMocksRequest,
    UpdateTemplateRequest,
    UpdateToolsRequest,
    UpdateVariablesRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _record_to_summary(record) -> PromptSummary:
    """Map a PromptRecord to a PromptSummary response."""
    return PromptSummary(
        id=record.id,
        purpose=record.purpose,
        template_variables=sorted(record.template_variables),
        anchor_variables=sorted(record.anchor_variables),
    )


@router.get("/", response_model=list[PromptSummary])
async def list_prompts(
    registry: PromptRegistry = Depends(get_registry),
) -> list[PromptSummary]:
    """List all registered prompts."""
    prompt_ids = await registry.list_prompts()
    summaries = []
    for pid in prompt_ids:
        try:
            record = await registry.load_prompt(pid)
            summaries.append(_record_to_summary(record))
        except Exception:
            logger.warning("Skipping broken prompt '%s'", pid)
    return summaries


def _build_config_response(merged: GeneConfig, overrides_dict: dict) -> PromptConfigResponse:
    """Build a PromptConfigResponse from merged config and raw overrides.

    For temperature: use per-role temperature if set, fallback to generation.temperature.
    """

    def _role_config(role: str) -> RoleConfigResponse:
        provider = getattr(merged, f"{role}_provider")
        model = getattr(merged, f"{role}_model")
        per_role_temp = getattr(merged, f"{role}_temperature", None)
        temperature = per_role_temp if per_role_temp is not None else merged.generation.temperature
        thinking_budget = getattr(merged, f"{role}_thinking_budget", None)
        return RoleConfigResponse(
            provider=provider,
            model=model,
            temperature=temperature,
            thinking_budget=thinking_budget,
        )

    # Build tool_mocker config from overrides (not a standard GeneConfig role)
    tool_mocker = ToolMockerConfigResponse(
        mode=overrides_dict.get("tool_mocker_mode", "static") or "static",
        provider=overrides_dict.get("tool_mocker_provider"),
        model=overrides_dict.get("tool_mocker_model"),
    )

    return PromptConfigResponse(
        meta=_role_config("meta"),
        target=_role_config("target"),
        judge=_role_config("judge"),
        tool_mocker=tool_mocker,
        overrides=overrides_dict,
    )


def _db_row_to_overrides_dict(row: PromptConfig) -> dict:
    """Extract a flat overrides dict from a PromptConfig DB row.

    Combines typed columns and extra JSON into a single dict,
    including only non-null values.
    """
    overrides: dict = {}

    # Start with extra JSON (holds all role-prefixed fields)
    if row.extra:
        overrides.update(row.extra)

    # Typed columns (target defaults if no role prefix in extra)
    if row.provider is not None and "meta_provider" not in overrides:
        overrides.setdefault("provider", row.provider)
    if row.model is not None and "meta_model" not in overrides:
        overrides.setdefault("model", row.model)
    if row.temperature is not None and "meta_temperature" not in overrides:
        overrides.setdefault("temperature", row.temperature)
    if row.thinking_budget is not None and "meta_thinking_budget" not in overrides:
        overrides.setdefault("thinking_budget", row.thinking_budget)

    return overrides


def _merge_overrides_onto_config(config: GeneConfig, overrides_dict: dict) -> GeneConfig:
    """Merge a flat overrides dict onto a GeneConfig, returning a new instance."""
    if not overrides_dict:
        return config

    update = {}
    for key, value in overrides_dict.items():
        if key == "generation" and isinstance(value, dict):
            current_gen = config.generation.model_dump()
            current_gen.update(value)
            update["generation"] = GenerationConfig(**current_gen)
        elif hasattr(config, key):
            update[key] = value

    return config.model_copy(update=update)


@router.post("/extract-variables", response_model=ExtractVariablesResponse)
async def extract_variables(
    body: ExtractVariablesRequest,
    registry: PromptRegistry = Depends(get_registry),
) -> ExtractVariablesResponse:
    """Extract Jinja2 template variables from a template string.

    Used by the import flow to auto-detect variables before registration.
    """
    errors: list[str] = []
    try:
        variables = sorted(registry.extract_variables(body.template))
    except jinja2.TemplateSyntaxError as exc:
        variables = []
        errors.append(f"Template syntax error: {exc}")
    return ExtractVariablesResponse(variables=variables, errors=errors)


@router.get("/{prompt_id}/config", response_model=PromptConfigResponse)
async def get_prompt_config(
    prompt_id: str,
    config: GeneConfig = Depends(get_config),
    session: AsyncSession = Depends(get_db_session),
    registry: PromptRegistry = Depends(get_registry),
) -> PromptConfigResponse:
    """Return prompt config with provenance info.

    Reads PromptConfig from DB. Returns both the effective (merged) config
    per role and the raw overrides dict, so the UI can show Global/Override badges.
    """
    # Check DB for prompt existence
    prompt_ids = await registry.list_prompts()
    if prompt_id not in prompt_ids:
        raise HTTPException(status_code=404, detail="Prompt not found")

    # Query PromptConfig from DB
    result = await session.execute(select(PromptConfig).where(PromptConfig.prompt_id == prompt_id))
    db_row = result.scalar_one_or_none()

    if db_row is not None:
        overrides_dict = _db_row_to_overrides_dict(db_row)
    else:
        overrides_dict = {}

    # Build effective (merged) values
    merged = _merge_overrides_onto_config(config, overrides_dict)

    return _build_config_response(merged, overrides_dict)


@router.put("/{prompt_id}/config", response_model=PromptConfigResponse)
async def update_prompt_config(
    prompt_id: str,
    body: PromptConfigSchema,
    config: GeneConfig = Depends(get_config),
    session: AsyncSession = Depends(get_db_session),
    registry: PromptRegistry = Depends(get_registry),
) -> PromptConfigResponse:
    """Update per-prompt config in DB PromptConfig table.

    Upserts the PromptConfig row. Stores role-prefixed fields in the extra
    JSON column. Does NOT write config.json.
    """
    # Check DB for prompt existence
    prompt_ids = await registry.list_prompts()
    if prompt_id not in prompt_ids:
        raise HTTPException(status_code=404, detail="Prompt not found")

    overrides_dict = body.model_dump(exclude_none=True)

    # Map common fields to typed columns, everything to extra
    provider = overrides_dict.get("meta_provider")
    model = overrides_dict.get("meta_model")
    temperature = overrides_dict.get("meta_temperature")
    thinking_budget = overrides_dict.get("meta_thinking_budget")

    # Extra holds the full override dict for all roles
    extra = overrides_dict if overrides_dict else None

    # Upsert: check if row exists
    result = await session.execute(select(PromptConfig).where(PromptConfig.prompt_id == prompt_id))
    db_row = result.scalar_one_or_none()

    if db_row is not None:
        # Update existing row
        db_row.provider = provider
        db_row.model = model
        db_row.temperature = temperature
        db_row.thinking_budget = thinking_budget
        db_row.extra = extra
    else:
        # Insert new row
        db_row = PromptConfig(
            prompt_id=prompt_id,
            provider=provider,
            model=model,
            temperature=temperature,
            thinking_budget=thinking_budget,
            extra=extra,
        )
        session.add(db_row)

    await session.commit()

    # Build effective merged config for response
    merged = _merge_overrides_onto_config(config, overrides_dict)

    return _build_config_response(merged, overrides_dict)


@router.get("/{prompt_id}", response_model=PromptDetail)
async def get_prompt(
    prompt_id: str,
    registry: PromptRegistry = Depends(get_registry),
    session: AsyncSession = Depends(get_db_session),
) -> PromptDetail:
    """Get a prompt's full detail including template text from DB."""
    record = await registry.load_prompt(prompt_id)

    # Template comes directly from PromptRecord (loaded from DB)
    template_text = record.template or ""

    # Convert typed Pydantic models to dicts for JSON serialization
    tool_schemas_dicts = (
        [ts.model_dump(exclude_none=True) for ts in record.tool_schemas]
        if record.tool_schemas
        else None
    )
    mocks_dicts = [m.model_dump(exclude_none=True) for m in record.mocks] if record.mocks else None

    # Load variable definitions from DB Prompt row


    result = await session.execute(
        select(PromptModel).where(PromptModel.id == prompt_id)
    )
    prompt_row = result.scalar_one_or_none()
    variable_defs_dicts = None
    if prompt_row and prompt_row.variables:
        variable_defs_dicts = [
            {k: v for k, v in var.items() if v is not None}
            for var in prompt_row.variables
        ]

    return PromptDetail(
        id=record.id,
        purpose=record.purpose,
        template_variables=sorted(record.template_variables),
        anchor_variables=sorted(record.anchor_variables),
        template=template_text,
        tools=record.tools,
        tool_schemas=tool_schemas_dicts,
        mocks=mocks_dicts,
        variable_definitions=variable_defs_dicts,
    )


@router.post("/", response_model=PromptSummary, status_code=201)
async def create_prompt(
    body: CreatePromptRequest,
    registry: PromptRegistry = Depends(get_registry),
) -> PromptSummary:
    """Register a new prompt."""
    # Convert body.variables (list[dict] | None) to list[VariableDefinition] | None
    variable_defs = None
    if body.variables is not None:
        variable_defs = [VariableDefinition(**d) for d in body.variables]

    registration = PromptRegistration(
        id=body.id,
        purpose=body.purpose,
        template=body.template,
        variables=variable_defs,
        tools=body.tools,
        tool_schemas=body.tool_schemas,
        mocks=body.mocks,
    )
    record = await registry.register(registration)
    return _record_to_summary(record)


@router.delete("/{prompt_id}", status_code=204)
async def delete_prompt(
    prompt_id: str,
    registry: PromptRegistry = Depends(get_registry),
) -> None:
    """Delete a prompt and all associated data."""
    await registry.delete_prompt(prompt_id)


@router.patch("/{prompt_id}", response_model=PromptSummary)
async def update_prompt(
    prompt_id: str,
    body: dict,
    registry: PromptRegistry = Depends(get_registry),
    session: AsyncSession = Depends(get_db_session),
) -> PromptSummary:
    """Partially update a prompt's metadata (e.g. purpose)."""
    result = await session.execute(
        select(PromptModel).where(PromptModel.id == prompt_id)
    )
    prompt_row = result.scalar_one_or_none()
    if not prompt_row:
        raise HTTPException(status_code=404, detail="Prompt not found")

    if "purpose" in body:
        prompt_row.purpose = body["purpose"]

    await session.commit()

    record = await registry.load_prompt(prompt_id)
    return _record_to_summary(record)


@router.put("/{prompt_id}/template", response_model=PromptSummary)
async def update_template(
    prompt_id: str,
    body: UpdateTemplateRequest,
    registry: PromptRegistry = Depends(get_registry),
) -> PromptSummary:
    """Update a prompt's template text."""
    record = await registry.update_template(prompt_id, body.template, "Update via API")
    return _record_to_summary(record)


@router.put("/{prompt_id}/variable-definitions", response_model=PromptSummary)
async def update_variable_definitions(
    prompt_id: str,
    body: UpdateVariablesRequest,
    registry: PromptRegistry = Depends(get_registry),
    session: AsyncSession = Depends(get_db_session),
) -> PromptSummary:
    """Update variable definitions for a prompt.

    Replaces the stored variable definitions and re-derives anchor_variables.
    """
    result = await session.execute(
        select(PromptModel).where(PromptModel.id == prompt_id)
    )
    prompt_row = result.scalar_one_or_none()
    if not prompt_row:
        raise HTTPException(status_code=404, detail="Prompt not found")

    # Validate each dict as a VariableDefinition
    variable_defs = [VariableDefinition(**d) for d in body.variables]

    # Serialize back to JSON-safe dicts
    prompt_row.variables = [v.model_dump() for v in variable_defs]
    await session.commit()

    # Re-derive template_variables and anchor_variables for the response
    template_variables = registry.extract_variables(prompt_row.template)
    anchor_variables = _extract_anchor_variables(variable_defs)

    return PromptSummary(
        id=prompt_row.id,
        purpose=prompt_row.purpose,
        template_variables=sorted(template_variables),
        anchor_variables=sorted(anchor_variables),
    )


@router.put("/{prompt_id}/mocks")
async def update_mocks(
    prompt_id: str,
    body: UpdateMocksRequest,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Update mock definitions for a prompt.

    Each mock has tool_name + scenarios with match_args and response.
    """
    result = await session.execute(
        select(PromptModel).where(PromptModel.id == prompt_id)
    )
    prompt_row = result.scalar_one_or_none()
    if not prompt_row:
        raise HTTPException(status_code=404, detail="Prompt not found")

    prompt_row.mocks = body.mocks
    await session.commit()
    return {"status": "ok", "mock_count": len(body.mocks)}


@router.put("/{prompt_id}/tools")
async def update_tools(
    prompt_id: str,
    body: UpdateToolsRequest,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Update tool definitions for a prompt."""
    result = await session.execute(
        select(PromptModel).where(PromptModel.id == prompt_id)
    )
    prompt_row = result.scalar_one_or_none()
    if not prompt_row:
        raise HTTPException(status_code=404, detail="Prompt not found")

    prompt_row.tools = body.tools if body.tools else None
    await session.commit()
    return {"status": "ok", "tool_count": len(body.tools)}


@router.get("/{prompt_id}/mocks")
async def get_mocks(
    prompt_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Get mock definitions for a prompt."""
    result = await session.execute(
        select(PromptModel).where(PromptModel.id == prompt_id)
    )
    prompt_row = result.scalar_one_or_none()
    if not prompt_row:
        raise HTTPException(status_code=404, detail="Prompt not found")

    return {"mocks": prompt_row.mocks or []}


# --- Version endpoints (Phase 63) ---


@router.get("/{prompt_id}/versions", response_model=list[PromptVersionResponse])
async def list_versions(
    prompt_id: str,
    registry: PromptRegistry = Depends(get_registry),
    session: AsyncSession = Depends(get_db_session),
) -> list[PromptVersionResponse]:
    """List all versions for a prompt, ordered by version number."""


    # Get the prompt to determine active_version
    result = await session.execute(
        select(PromptModel).where(PromptModel.id == prompt_id)
    )
    prompt_row = result.scalar_one_or_none()
    if prompt_row is None:
        raise HTTPException(status_code=404, detail="Prompt not found")

    active_version = prompt_row.active_version or 1

    versions = await registry.list_versions(prompt_id)
    return [
        PromptVersionResponse(
            version=v["version"],
            template=v["template"],
            created_at=v["created_at"],
            is_active=(v["version"] == active_version),
        )
        for v in versions
    ]


@router.get(
    "/{prompt_id}/versions/{version}",
    response_model=PromptVersionResponse,
)
async def get_version(
    prompt_id: str,
    version: int,
    registry: PromptRegistry = Depends(get_registry),
    session: AsyncSession = Depends(get_db_session),
) -> PromptVersionResponse:
    """Get a specific version of a prompt."""


    # Get version template (raises PromptNotFoundError -> 404 via exception handler)
    template = await registry.get_version_template(prompt_id, version)

    # Get active_version for is_active flag
    result = await session.execute(
        select(PromptModel).where(PromptModel.id == prompt_id)
    )
    prompt_row = result.scalar_one_or_none()
    active_version = prompt_row.active_version if prompt_row else 1

    # Get created_at from the version row
    from api.storage.models import PromptVersion

    ver_result = await session.execute(
        select(PromptVersion).where(
            PromptVersion.prompt_id == prompt_id,
            PromptVersion.version == version,
        )
    )
    version_row = ver_result.scalar_one()

    return PromptVersionResponse(
        version=version,
        template=template,
        created_at=version_row.created_at.isoformat() if version_row.created_at else "",
        is_active=(version == active_version),
    )


@router.put(
    "/{prompt_id}/versions/{version}/activate",
    response_model=PromptVersionResponse,
)
async def activate_version(
    prompt_id: str,
    version: int,
    registry: PromptRegistry = Depends(get_registry),
) -> PromptVersionResponse:
    """Activate a specific version for a prompt."""
    # activate_version raises PromptNotFoundError -> 404 via exception handler
    result = await registry.activate_version(prompt_id, version)
    return PromptVersionResponse(
        version=result["version"],
        template=result["template"],
        created_at="",  # Not returned by activate_version
        is_active=True,
    )


@router.post(
    "/{prompt_id}/versions/accept",
    response_model=PromptVersionResponse,
    status_code=201,
)
async def accept_version(
    prompt_id: str,
    body: AcceptVersionRequest,
    registry: PromptRegistry = Depends(get_registry),
) -> PromptVersionResponse:
    """Accept an evolved template as a new version.

    Creates a new version from the provided template and sets it as active.
    Idempotent: returns the existing version if the template already matches.
    Used after evolution runs to accept the best evolved template.
    """
    result = await registry.create_version(prompt_id, body.template)
    return PromptVersionResponse(
        version=result["version"],
        template=result["template"],
        created_at=result["created_at"],
        is_active=True,
        already_existed=result.get("already_existed", False),
    )
