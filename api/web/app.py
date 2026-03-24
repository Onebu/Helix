"""FastAPI application factory for Helix API.

Provides create_app() factory with CORS, lifespan management,
exception handlers mapping domain errors to HTTP status codes,
and a /health endpoint.

Usage:
    uvicorn api.web.app:app --reload
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.exceptions import (
    GenePrompterError,
    PromptAlreadyExistsError,
    PromptNotFoundError,
)
from api.web.event_bus import EventBus
from api.web.run_manager import RunManager

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown hooks."""
    # Startup: create RunManager and EventBus for background evolution tasks
    app.state.run_manager = RunManager()
    app.state.event_bus = EventBus()

    # Auto-migrate database schema if configured
    from api.storage.database import Database
    from api.web.deps import get_config

    try:
        config = get_config()
        if config.database_url is not None:
            db = Database(config.database_url)
            await db.create_tables()
            await db.ensure_columns()
            logger.info("Database schema up to date")

            # Check if DB has any prompts
            from sqlalchemy import select
            from sqlalchemy.sql import func

            from api.storage.models import Prompt

            async with db.session_factory() as session:
                result = await session.execute(
                    select(func.count()).select_from(Prompt)
                )
                prompt_count = result.scalar() or 0

            if prompt_count == 0:
                # No prompts in DB -- check if filesystem prompts/ dir exists
                prompts_dir = getattr(config, "prompts_dir", "prompts")
                import os

                if os.path.isdir(prompts_dir):
                    # Migrate existing prompts from filesystem to DB
                    count = await db.import_prompts_from_filesystem(prompts_dir)
                    logger.info("Migrated %d prompts from filesystem to DB", count)
                else:
                    # No prompts/ dir -- seed demo data for new users
                    seeded = await db.seed_demo_prompt()
                    if seeded:
                        logger.info("Seeded demo pizza-ivr prompt for new users")
            else:
                # Prompts exist -- still import sidecars for any new ones
                prompts_dir = getattr(config, "prompts_dir", "prompts")
                await db.import_prompt_sidecars(prompts_dir)

            await db.close()
    except Exception:
        logger.warning("Database setup failed (history will return 503)", exc_info=True)

    yield
    # Shutdown: cancel running tasks and clean up
    await app.state.run_manager.shutdown()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        Configured FastAPI instance with CORS, exception handlers,
        and /health endpoint.
    """
    load_dotenv()

    application = FastAPI(
        title="Helix API",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS: configurable via CORS_ORIGINS env var (comma-separated)
    cors_origins_str = os.environ.get("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000")
    cors_origins = [origin.strip() for origin in cors_origins_str.split(",")]
    application.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Exception handlers mapping domain errors to HTTP codes ---

    @application.exception_handler(PromptNotFoundError)
    async def prompt_not_found_handler(request: Request, exc: PromptNotFoundError):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @application.exception_handler(PromptAlreadyExistsError)
    async def prompt_already_exists_handler(request: Request, exc: PromptAlreadyExistsError):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @application.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @application.exception_handler(GenePrompterError)
    async def helix_error_handler(request: Request, exc: GenePrompterError):
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    # --- Health check ---

    @application.get("/health")
    async def health():
        return {"status": "ok"}

    # --- Routers ---
    from api.web.routers import (
        datasets,
        evolution,
        format_guides,
        history,
        models,
        personas,
        playground,
        presets,
        prompts,
        settings,
        synthesis,
        wizard,
        ws,
    )

    application.include_router(prompts.router, prefix="/api/prompts", tags=["prompts"])
    application.include_router(datasets.router, prefix="/api/prompts", tags=["datasets"])
    application.include_router(evolution.router, prefix="/api/evolution", tags=["evolution"])
    application.include_router(history.router, prefix="/api/history", tags=["history"])
    application.include_router(models.router, prefix="/api/models", tags=["models"])
    application.include_router(wizard.router, prefix="/api/wizard", tags=["wizard"])
    application.include_router(synthesis.router, prefix="/api/prompts", tags=["synthesis"])
    application.include_router(personas.router, prefix="/api/prompts", tags=["personas"])
    application.include_router(settings.router, prefix="/api/settings", tags=["settings"])
    application.include_router(presets.router, prefix="/api/presets", tags=["presets"])
    application.include_router(ws.router, tags=["websocket"])
    application.include_router(playground.router, prefix="/api/prompts", tags=["playground"])
    application.include_router(format_guides.router, prefix="/api/prompts", tags=["format-guides"])

    return application


# Module-level app instance for: uvicorn api.web.app:app
app = create_app()
