"""API router for tool format guide CRUD and sample generation.

Provides endpoints for managing per-prompt, per-tool format guide examples
used by the LLM tool mocker, plus a sample generation endpoint for previewing
mock responses before running synthesis.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.config.models import GeneConfig
from api.gateway.factory import create_provider
from api.registry.llm_mocker import LLMMocker
from api.storage.models import PromptConfig, ToolFormatGuide, User
from api.web.auth import get_current_user
from api.web.deps import get_config, get_db_session
from api.web.schemas import (
    FormatGuideResponse,
    GenerateSampleRequest,
    GenerateSampleResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _row_to_response(row: ToolFormatGuide) -> FormatGuideResponse:
    """Convert a ToolFormatGuide ORM row to an API response model."""
    return FormatGuideResponse(
        id=row.id,
        prompt_id=row.prompt_id,
        tool_name=row.tool_name,
        examples=row.examples,
    )


@router.get(
    "/{prompt_id}/format-guides",
    response_model=list[FormatGuideResponse],
)
async def list_format_guides(
    prompt_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> list[FormatGuideResponse]:
    """List all format guides for a prompt."""
    stmt = select(ToolFormatGuide).where(ToolFormatGuide.prompt_id == prompt_id)
    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [_row_to_response(row) for row in rows]


@router.put(
    "/{prompt_id}/format-guides/{tool_name}",
    response_model=FormatGuideResponse,
)
async def upsert_format_guide(
    prompt_id: str,
    tool_name: str,
    examples: list[str],
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> FormatGuideResponse:
    """Create or update a format guide for a specific tool.

    Validates that at least 1 example is provided and each example
    is valid JSON. Upserts: updates if exists, creates if not.
    """
    # Validate non-empty
    if not examples:
        raise HTTPException(status_code=400, detail="At least 1 example required")

    # Validate each example is valid JSON
    for i, example in enumerate(examples):
        try:
            json.loads(example)
        except (json.JSONDecodeError, TypeError) as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Example {i + 1} is not valid JSON",
            ) from exc

    # Upsert: find existing or create
    stmt = select(ToolFormatGuide).where(
        ToolFormatGuide.prompt_id == prompt_id,
        ToolFormatGuide.tool_name == tool_name,
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()

    if row is not None:
        row.examples = examples
    else:
        row = ToolFormatGuide(
            prompt_id=prompt_id,
            tool_name=tool_name,
            examples=examples,
        )
        session.add(row)

    await session.commit()
    await session.refresh(row)
    return _row_to_response(row)


@router.delete("/{prompt_id}/format-guides/{tool_name}")
async def delete_format_guide(
    prompt_id: str,
    tool_name: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> dict:
    """Delete a format guide for a specific tool."""
    stmt = select(ToolFormatGuide).where(
        ToolFormatGuide.prompt_id == prompt_id,
        ToolFormatGuide.tool_name == tool_name,
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()

    if row is None:
        raise HTTPException(status_code=404, detail="Format guide not found")

    await session.delete(row)
    await session.commit()
    return {"deleted": True}


@router.post(
    "/{prompt_id}/format-guides/generate-sample",
    response_model=GenerateSampleResponse,
)
async def generate_sample(
    prompt_id: str,
    body: GenerateSampleRequest,
    config: GeneConfig = Depends(get_config),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> GenerateSampleResponse:
    """Generate a sample mock response using the LLM tool mocker.

    Loads the format guide for the specified tool from the database,
    creates an LLMMocker with the configured provider/model, and
    generates a preview response.
    """
    # Load prompt config to get tool_mocker settings
    stmt = select(PromptConfig).where(PromptConfig.prompt_id == prompt_id)
    result = await session.execute(stmt)
    prompt_cfg = result.scalar_one_or_none()

    overrides: dict = {}
    if prompt_cfg and prompt_cfg.extra:
        overrides = prompt_cfg.extra

    mode = overrides.get("tool_mocker_mode", "static") or "static"
    provider_name = overrides.get("tool_mocker_provider")
    model_name = overrides.get("tool_mocker_model")

    if mode != "llm" or not provider_name or not model_name:
        raise HTTPException(
            status_code=400,
            detail=(
                "Tool Mocker must be in 'llm' mode with provider and model configured. "
                "Set tool_mocker_mode='llm', tool_mocker_provider, and tool_mocker_model "
                "in the prompt config."
            ),
        )

    # Load format guide
    guide_stmt = select(ToolFormatGuide).where(
        ToolFormatGuide.prompt_id == prompt_id,
        ToolFormatGuide.tool_name == body.tool_name,
    )
    guide_result = await session.execute(guide_stmt)
    guide = guide_result.scalar_one_or_none()

    if guide is None:
        raise HTTPException(
            status_code=404,
            detail=f"No format guide found for tool '{body.tool_name}'",
        )

    # Create provider and LLMMocker
    try:
        provider = create_provider(provider_name, config)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to create provider '{provider_name}': {exc}",
        ) from exc

    mocker = LLMMocker(provider=provider, model=model_name)
    sample = await mocker.generate_sample(
        tool_name=body.tool_name,
        format_guide_examples=guide.examples,
        scenario_type=body.scenario_type,
    )

    if sample is None:
        raise HTTPException(
            status_code=500,
            detail="Failed to generate sample. The LLM may have returned invalid JSON.",
        )

    return GenerateSampleResponse(
        sample=sample,
        scenario_type=body.scenario_type,
    )
