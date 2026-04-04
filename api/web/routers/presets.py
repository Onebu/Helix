"""Presets CRUD API endpoints for managing config and evolution presets.

Provides full CRUD operations for presets stored in the database.

Endpoints:
- GET /: List all presets (optional type filter)
- POST /: Create a new preset (201)
- GET /{preset_id}: Get a single preset
- PUT /{preset_id}: Update a preset
- DELETE /{preset_id}: Delete a preset (204)
- PUT /{preset_id}/default: Mark as default (clears others of same type)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.storage.models import Preset, User
from api.web.auth import get_current_user
from api.web.deps import get_db_session
from api.web.schemas import (
    CreatePresetRequest,
    PresetResponse,
    UpdatePresetRequest,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _preset_to_response(preset: Preset) -> PresetResponse:
    """Convert a Preset ORM instance to a PresetResponse."""
    return PresetResponse(
        id=preset.id,
        name=preset.name,
        type=preset.type,
        data=preset.data,
        is_default=preset.is_default,
        created_at=preset.created_at.isoformat() if preset.created_at else "",
    )


@router.get("", response_model=list[PresetResponse])
async def list_presets(
    type: str | None = None,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> list[PresetResponse]:
    """List all presets, optionally filtered by type."""
    stmt = select(Preset)
    if type is not None:
        stmt = stmt.where(Preset.type == type)
    result = await session.execute(stmt)
    presets = result.scalars().all()
    return [_preset_to_response(p) for p in presets]


@router.post("", response_model=PresetResponse, status_code=201)
async def create_preset(
    body: CreatePresetRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> PresetResponse:
    """Create a new preset."""
    preset = Preset(
        name=body.name,
        type=body.type,
        data=body.data,
        is_default=body.is_default,
    )
    session.add(preset)
    await session.commit()
    await session.refresh(preset)
    return _preset_to_response(preset)


@router.get("/{preset_id}", response_model=PresetResponse)
async def get_preset(
    preset_id: int,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> PresetResponse:
    """Get a single preset by ID."""
    preset = await session.get(Preset, preset_id)
    if preset is None:
        raise HTTPException(status_code=404, detail=f"Preset {preset_id} not found")
    return _preset_to_response(preset)


@router.put("/{preset_id}", response_model=PresetResponse)
async def update_preset(
    preset_id: int,
    body: UpdatePresetRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> PresetResponse:
    """Update an existing preset (partial update)."""
    preset = await session.get(Preset, preset_id)
    if preset is None:
        raise HTTPException(status_code=404, detail=f"Preset {preset_id} not found")

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(preset, field, value)

    await session.commit()
    await session.refresh(preset)
    return _preset_to_response(preset)


@router.delete("/{preset_id}", status_code=204)
async def delete_preset(
    preset_id: int,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> Response:
    """Delete a preset."""
    preset = await session.get(Preset, preset_id)
    if preset is None:
        raise HTTPException(status_code=404, detail=f"Preset {preset_id} not found")

    await session.delete(preset)
    await session.commit()
    return Response(status_code=204)


@router.put("/{preset_id}/default", response_model=PresetResponse)
async def set_default(
    preset_id: int,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> PresetResponse:
    """Mark a preset as default, clearing other defaults of the same type."""
    preset = await session.get(Preset, preset_id)
    if preset is None:
        raise HTTPException(status_code=404, detail=f"Preset {preset_id} not found")

    # Clear other defaults of the same type
    stmt = select(Preset).where(Preset.type == preset.type, Preset.is_default.is_(True))
    result = await session.execute(stmt)
    for other in result.scalars().all():
        other.is_default = False

    preset.is_default = True
    await session.commit()
    await session.refresh(preset)
    return _preset_to_response(preset)
