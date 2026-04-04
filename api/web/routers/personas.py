"""Persona CRUD API endpoints for managing personas per prompt.

Provides full CRUD operations plus import/export for persona profiles
stored in the database (replaces personas.yaml sidecar files).

Endpoints:
- GET /{prompt_id}/personas: List personas (or return defaults)
- POST /{prompt_id}/personas: Create a new persona
- PUT /{prompt_id}/personas/{persona_id}: Update an existing persona
- DELETE /{prompt_id}/personas/{persona_id}: Remove a persona
- GET /{prompt_id}/personas/export: Export all personas as JSON array
- POST /{prompt_id}/personas/import: Import personas, skip duplicates
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.storage.models import Persona, User
from api.web.auth import get_current_user
from api.web.deps import get_db_session
from api.web.schemas import (
    CreatePersonaRequest,
    ImportPersonasResponse,
    PersonaProfileResponse,
    UpdatePersonaRequest,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# Default personas returned when no DB rows exist for a prompt
_DEFAULT_PERSONAS: list[dict] = [
    {
        "persona_id": "confused-user",
        "role": "Confused user who misunderstands instructions",
        "traits": ["easily confused", "asks vague questions", "gives incomplete info"],
        "communication_style": "Rambling, unclear, mixes topics",
        "goal": "Get help despite providing unclear or contradictory information",
        "edge_cases": ["gives wrong input types", "changes topic mid-conversation"],
        "behavior_criteria": [],
        "language": "en",
        "channel": "text",
    },
    {
        "persona_id": "adversarial-user",
        "role": "Adversarial user who tries to break the system",
        "traits": ["persistent", "creative", "boundary-testing"],
        "communication_style": "Direct, probing, tries unexpected inputs",
        "goal": "Find edge cases where the system fails or gives wrong answers",
        "edge_cases": ["requests outside scope", "provides malformed data"],
        "behavior_criteria": [],
        "language": "en",
        "channel": "text",
    },
    {
        "persona_id": "impatient-user",
        "role": "Impatient user who wants quick answers",
        "traits": ["rushed", "skips details", "easily frustrated"],
        "communication_style": "Short messages, abbreviations, demands speed",
        "goal": "Complete the task as fast as possible with minimal interaction",
        "edge_cases": ["interrupts flow", "skips required steps"],
        "behavior_criteria": [],
        "language": "en",
        "channel": "text",
    },
]


def _persona_to_response(persona: Persona) -> PersonaProfileResponse:
    """Convert a Persona ORM instance to a PersonaProfileResponse."""
    return PersonaProfileResponse(
        id=persona.persona_id,
        role=persona.role,
        traits=persona.traits,
        communication_style=persona.communication_style,
        goal=persona.goal,
        edge_cases=persona.edge_cases or [],
        behavior_criteria=persona.behavior_criteria or [],
        language=persona.language or "en",
        channel=persona.channel or "text",
    )


async def _load_personas_from_db(
    session: AsyncSession, prompt_id: str
) -> list[PersonaProfileResponse]:
    """Query Persona rows for prompt_id. Return defaults if none found."""
    stmt = select(Persona).where(Persona.prompt_id == prompt_id)
    result = await session.execute(stmt)
    rows = result.scalars().all()

    if not rows:
        # Return default personas without persisting them
        return [
            PersonaProfileResponse(
                id=d["persona_id"],
                role=d["role"],
                traits=d["traits"],
                communication_style=d["communication_style"],
                goal=d["goal"],
                edge_cases=d["edge_cases"],
                behavior_criteria=d["behavior_criteria"],
                language=d["language"],
                channel=d["channel"],
            )
            for d in _DEFAULT_PERSONAS
        ]

    return [_persona_to_response(p) for p in rows]


async def _materialize_defaults_to_db(session: AsyncSession, prompt_id: str) -> list[Persona]:
    """Ensure Persona rows exist for prompt_id. Insert defaults if empty.

    Used by write operations (POST/PUT/DELETE/import) to ensure the
    default personas are preserved when first edit occurs.

    Returns all Persona rows for the prompt_id.
    """
    stmt = select(Persona).where(Persona.prompt_id == prompt_id)
    result = await session.execute(stmt)
    rows = list(result.scalars().all())

    if not rows:
        # Insert defaults
        for d in _DEFAULT_PERSONAS:
            persona = Persona(
                prompt_id=prompt_id,
                persona_id=d["persona_id"],
                role=d["role"],
                traits=d["traits"],
                communication_style=d["communication_style"],
                goal=d["goal"],
                edge_cases=d["edge_cases"],
                behavior_criteria=d["behavior_criteria"],
                language=d["language"],
                channel=d["channel"],
            )
            session.add(persona)
        await session.flush()

        # Re-query to get all rows with IDs
        result = await session.execute(stmt)
        rows = list(result.scalars().all())

    return rows


@router.get("/{prompt_id}/personas", response_model=list[PersonaProfileResponse])
async def list_personas(
    prompt_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> list[PersonaProfileResponse]:
    """List all personas for a prompt. Returns defaults if no DB rows exist."""
    return await _load_personas_from_db(session, prompt_id)


@router.post(
    "/{prompt_id}/personas",
    response_model=PersonaProfileResponse,
    status_code=201,
)
async def create_persona(
    prompt_id: str,
    body: CreatePersonaRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> PersonaProfileResponse:
    """Create a new persona for a prompt."""
    # Materialize defaults first (if needed)
    existing_rows = await _materialize_defaults_to_db(session, prompt_id)

    # Check for duplicate persona_id
    existing_ids = {p.persona_id for p in existing_rows}
    if body.id in existing_ids:
        raise HTTPException(status_code=409, detail=f"Persona '{body.id}' already exists")

    new_persona = Persona(
        prompt_id=prompt_id,
        persona_id=body.id,
        role=body.role,
        traits=body.traits,
        communication_style=body.communication_style,
        goal=body.goal,
        edge_cases=body.edge_cases or [],
        behavior_criteria=body.behavior_criteria or [],
        language=body.language,
        channel=body.channel,
    )
    session.add(new_persona)
    await session.commit()
    await session.refresh(new_persona)

    return _persona_to_response(new_persona)


@router.put(
    "/{prompt_id}/personas/{persona_id}",
    response_model=PersonaProfileResponse,
)
async def update_persona(
    prompt_id: str,
    persona_id: str,
    body: UpdatePersonaRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> PersonaProfileResponse:
    """Update an existing persona's fields (partial update)."""
    stmt = select(Persona).where(
        Persona.prompt_id == prompt_id,
        Persona.persona_id == persona_id,
    )
    result = await session.execute(stmt)
    target = result.scalar_one_or_none()

    if target is None:
        raise HTTPException(status_code=404, detail=f"Persona '{persona_id}' not found")

    # Apply partial update
    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(target, field, value)

    await session.commit()
    await session.refresh(target)
    return _persona_to_response(target)


@router.delete("/{prompt_id}/personas/{persona_id}", status_code=204)
async def delete_persona(
    prompt_id: str,
    persona_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> Response:
    """Delete a persona by ID."""
    stmt = select(Persona).where(
        Persona.prompt_id == prompt_id,
        Persona.persona_id == persona_id,
    )
    result = await session.execute(stmt)
    target = result.scalar_one_or_none()

    if target is None:
        raise HTTPException(status_code=404, detail=f"Persona '{persona_id}' not found")

    await session.delete(target)
    await session.commit()
    return Response(status_code=204)


@router.get(
    "/{prompt_id}/personas/export",
    response_model=list[PersonaProfileResponse],
)
async def export_personas(
    prompt_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> list[PersonaProfileResponse]:
    """Export all personas as a JSON array."""
    return await _load_personas_from_db(session, prompt_id)


@router.post(
    "/{prompt_id}/personas/import",
    response_model=ImportPersonasResponse,
)
async def import_personas(
    prompt_id: str,
    body: list[CreatePersonaRequest],
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> ImportPersonasResponse:
    """Import personas from a JSON array, skipping existing IDs."""
    # Materialize defaults first
    existing_rows = await _materialize_defaults_to_db(session, prompt_id)
    existing_ids = {p.persona_id for p in existing_rows}

    added = 0
    skipped = 0
    for item in body:
        if item.id in existing_ids:
            skipped += 1
            continue
        new_persona = Persona(
            prompt_id=prompt_id,
            persona_id=item.id,
            role=item.role,
            traits=item.traits,
            communication_style=item.communication_style,
            goal=item.goal,
            edge_cases=item.edge_cases or [],
            behavior_criteria=item.behavior_criteria or [],
            language=item.language,
            channel=item.channel,
        )
        session.add(new_persona)
        existing_ids.add(item.id)
        added += 1

    await session.commit()

    # Count total
    stmt = select(Persona).where(Persona.prompt_id == prompt_id)
    result = await session.execute(stmt)
    total = len(result.scalars().all())

    return ImportPersonasResponse(
        added_count=added,
        skipped_count=skipped,
        total=total,
    )
