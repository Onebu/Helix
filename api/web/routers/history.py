"""Evolution history query endpoints.

Routes:
    GET /{prompt_id}                     List evolution runs for a prompt
    GET /run/by-uuid/{run_uuid}/results  Get run results by RunManager UUID
    GET /run/{run_id:int}                Get single evolution run details
    GET /run/{run_id:int}/results        Get run results by DB integer ID
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from api.storage.database import Database
from api.storage.models import EvolutionRun, User
from api.storage.queries import get_evolution_history
from api.web.auth import get_current_user
from api.web.deps import get_database
from api.web.schemas import EvolutionRunHistory, RunResultsResponse

router = APIRouter()


def _run_to_history(run: EvolutionRun) -> EvolutionRunHistory:
    """Map an EvolutionRun ORM model to an EvolutionRunHistory response."""
    return EvolutionRunHistory(
        id=run.id,
        prompt_id=run.prompt_id,
        status=run.status,
        best_fitness_score=run.best_fitness_score,
        total_cost_usd=run.total_cost_usd,
        generations_completed=run.generations_completed,
        created_at=run.created_at.isoformat(),
        meta_model=run.meta_model,
        target_model=run.target_model,
    )


def _build_run_results_response(run: EvolutionRun) -> RunResultsResponse:
    """Build RunResultsResponse from an EvolutionRun ORM model."""
    meta = run.extra_metadata or {}
    lineage_events = meta.get("lineage_events", [])
    case_results = meta.get("case_results", [])
    seed_case_results = meta.get("seed_case_results", [])
    generation_records = meta.get("generation_records", [])
    best_candidate_id = meta.get("best_candidate_id")

    best_template = None
    if best_candidate_id and lineage_events:
        for event in lineage_events:
            if event.get("candidate_id") == best_candidate_id:
                best_template = event.get("template")
                break

    return RunResultsResponse(
        prompt_id=run.prompt_id,
        lineage_events=lineage_events,
        case_results=case_results,
        seed_case_results=seed_case_results,
        generation_records=generation_records,
        best_candidate_id=best_candidate_id,
        best_template=best_template,
        total_cost_usd=run.total_cost_usd or 0.0,
        best_fitness_score=run.best_fitness_score,
        best_normalized_score=meta.get("best_normalized_score"),
        generations_completed=run.generations_completed or 0,
        termination_reason=meta.get("termination_reason"),
        meta_model=run.meta_model,
        target_model=run.target_model,
        judge_model=getattr(run, "judge_model", None),
        meta_provider=getattr(run, "meta_provider", None),
        target_provider=getattr(run, "target_provider", None),
        judge_provider=getattr(run, "judge_provider", None),
        hyperparameters=run.hyperparameters,
    )


@router.get("/{prompt_id}", response_model=list[EvolutionRunHistory])
async def get_history(
    prompt_id: str,
    db: Database = Depends(get_database),
    user: User = Depends(get_current_user),
) -> list[EvolutionRunHistory]:
    """List evolution runs for a prompt, ordered by most recent first."""
    session = await db.get_session()
    try:
        runs = await get_evolution_history(session, prompt_id)
        return [_run_to_history(run) for run in runs]
    finally:
        await session.close()


@router.get("/run/by-uuid/{run_uuid}/results", response_model=RunResultsResponse)
async def get_run_results_by_uuid(
    run_uuid: str,
    db: Database = Depends(get_database),
    user: User = Depends(get_current_user),
) -> RunResultsResponse:
    """Get full results for a completed evolution run by its UUID.

    Used by the dashboard for live-to-completed transitions where
    the frontend only has the RunManager UUID, not the DB integer ID.
    """
    session = await db.get_session()
    try:
        stmt = select(EvolutionRun).where(EvolutionRun.run_uuid == run_uuid)
        result = await session.execute(stmt)
        run = result.scalar_one_or_none()
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return _build_run_results_response(run)
    finally:
        await session.close()


@router.get("/run/{run_id:int}", response_model=EvolutionRunHistory)
async def get_run_detail(
    run_id: int,
    db: Database = Depends(get_database),
    user: User = Depends(get_current_user),
) -> EvolutionRunHistory:
    """Get a single evolution run by its database ID."""
    session = await db.get_session()
    try:
        stmt = select(EvolutionRun).where(EvolutionRun.id == run_id)
        result = await session.execute(stmt)
        run = result.scalar_one_or_none()
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return _run_to_history(run)
    finally:
        await session.close()


@router.get("/run/{run_id:int}/results", response_model=RunResultsResponse)
async def get_run_results(
    run_id: int,
    db: Database = Depends(get_database),
    user: User = Depends(get_current_user),
) -> RunResultsResponse:
    """Get full results for a completed evolution run.

    Returns lineage events, case results, seed case results,
    best candidate ID, and best template for visualization.
    """
    session = await db.get_session()
    try:
        stmt = select(EvolutionRun).where(EvolutionRun.id == run_id)
        result = await session.execute(stmt)
        run = result.scalar_one_or_none()
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return _build_run_results_response(run)
    finally:
        await session.close()
