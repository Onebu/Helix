# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Helix (PyPI: `helix-engine`) — an evolutionary prompt optimization engine inspired by the Mind Evolution paper (Google DeepMind, 2025). Uses island-model evolution, RCC (Refinement through Critical Conversation), and Boltzmann selection to iteratively improve LLM prompts against test case datasets.

**Three interfaces share the same core engine:**
- **Web UI** (`api/web/`) — FastAPI + React dashboard
- **CLI** (`cli/helix_cli/`) — standalone terminal tool (`pip install helix-evolve`)
- **Python API** — import `api.evolution.runner.run_evolution()` directly

## Commands

### Backend (Python 3.13+, uv)

```bash
uv sync                          # Install all dependencies
uv run uvicorn api.web.app:create_app --factory --host 127.0.0.1 --port 8000 --reload

# Tests
pytest                           # All tests (skips e2e by default)
pytest tests/api/test_settings.py           # Single file
pytest tests/api/test_settings.py::test_get -x -v  # Single test
pytest -m e2e                    # E2E tests (needs real API keys)

# Lint
ruff check api/                  # Line length: 100, target: py313
ruff format api/
```

### Frontend (Node 22+, npm)

```bash
cd frontend
npm install
npm run dev                      # Vite dev server (port 5173, proxies /api + /ws to :8000)
npm run build                    # openapi-ts → tsc → vite build
npm run generate-client          # Regenerate TS client from OpenAPI spec
npm run lint                     # ESLint
npm run test                     # Vitest
```

### CLI (`cli/`, helix-evolve)

```bash
uv pip install -e cli/               # Install CLI (requires core engine)
helix init my-prompt                  # Scaffold prompt directory
helix list                            # List prompts in workspace
helix show my-prompt                  # Display prompt details
helix evolve my-prompt                # Run evolution (Rich live progress)
helix results my-prompt               # Show latest results
helix accept my-prompt                # Apply evolved template
# All commands support --json for agent/script integration
```

### Docker

```bash
docker compose up --build                        # Production (nginx :80)
docker compose -f docker-compose.dev.yml up      # Dev with hot reload
```

## Architecture

### Backend (`api/`)

**API layer** — FastAPI with factory pattern (`api/web/app.py`). Routes in `api/web/routers/`. Dependencies injected via `api/web/deps.py` (`get_config`, `get_registry`, `get_dataset_service`, `get_database`).

**Evolution engine** — `evolution/runner.py` wires up all service dependencies and executes the pipeline. `evolution/islands.py` manages N parallel islands. Each island runs `evolution/loop.py` which orchestrates: `BoltzmannSelector` → `RCCEngine` (multi-turn critic-author LLM dialogue) → `StructuralMutator` (section reordering). Fitness scored by `evaluation/evaluator.py` with pluggable strategies (`scorers.py`).

**LLM gateway** — Single `AsyncOpenAI` client for all providers. `gateway/registry.py` maps provider names to `ProviderConfig` (base_url + api_key_field). Adding a provider = one dict entry in `PROVIDER_REGISTRY`.

**Config cascade** — `config/models.py` `GeneConfig` uses pydantic-settings: constructor args > env vars (`GENE_*` prefix).

**Storage** — SQLAlchemy 2.0 async ORM (`storage/models.py`). SQLite default, PostgreSQL optional. Schema auto-migrated via `ensure_columns()` on startup (no Alembic at runtime).

**Real-time** — `EventBus` (`api/web/event_bus.py`) with ring buffer replay fans out evolution events to WebSocket subscribers. `RunManager` (`api/web/run_manager.py`) handles background task lifecycle.

### Frontend (`frontend/src/`)

**Stack**: React 19 + Vite + TypeScript + Tailwind v4 + shadcn/ui (Radix).

**API client**: Auto-generated from OpenAPI via `@hey-api/openapi-ts`. All API URLs use `VITE_API_URL` env var (empty in dev = Vite proxy).

**Key hooks**: `useEvolutionSocket` (WebSocket reducer for live evolution), `useChatStream` (SSE for playground chat).

**Visualization**: Recharts (fitness), custom SVG (lineage graph, island summary).

**Routing**: React Router v7. `AppShell` → `PromptLayout` (nested routes per prompt tab).

### CLI (`cli/helix_cli/`)

**Stack**: Typer + Rich. YAML project files (prompt.yaml, dataset.yaml, config.yaml).

**Loader**: `project/loader.py` bridges YAML files to domain models (`PromptRecord`, `TestCase`, `GeneConfig`, `EvolutionConfig`). Reuses `api.registry.service._extract_anchor_variables()` and Jinja2 meta for variable extraction.

**Evolve**: `commands/evolve.py` calls `api.evolution.runner.run_evolution()` directly via `asyncio.run()`. Provides Rich Live progress via `event_callback`.

**Writer**: `project/writer.py` serializes `EvolutionResult` to `results/run-NNN.yaml`.

**Config cascade**: CLI flags > config.yaml > `GENE_*` env vars > defaults.

### Communication

- REST: CRUD operations, evolution start/cancel, model listing
- WebSocket (`/ws`): Live evolution events (generation updates, migrations, resets)
- SSE: Chat playground streaming

## Key Patterns

- **Data-driven scoring**: Scoring behaviors controlled via test case JSON fields (`require_content`, `match_args`), not code changes
- **Tiered regression**: Test cases have priority tiers (critical = hard constraint, normal/low = weighted in fitness)
- **Section-aware mutation**: Prompts use H1/H2 + XML sections; mutations target sections, preserving template variables
- **Snapshot-copy parallelism**: CostTracker/LineageCollector use snapshot copies per island to avoid locks during parallel evolution
- **ensure_columns migration**: New DB columns added at startup by inspecting existing schema — no migration files needed

## Git Workflow

- **Every change starts with a GitHub issue.** Create an issue first, then a branch linked to it.
- **Branch naming**: `<type>/<short-description>` — e.g. `feat/modular-prompts`, `fix/lineage-null-crash`, `chore/bump-deps`.
- **Commit prefixes** (Conventional Commits):
  - `feat:` — new feature
  - `fix:` — bug fix
  - `chore:` — maintenance, deps, CI
  - `docs:` — documentation only
  - `refactor:` — code restructure without behavior change
  - `test:` — test additions or fixes
- **PR title** must use the same prefix format: `feat: add modular prompt composition`.
- **PR body** must reference the issue: `Closes #54` or `Resolves #54`.
- **Merge strategy**: squash merge, delete branch after merge.
- **After merge**: close the linked issue if not auto-closed.

## Conventions

- Python: `from __future__ import annotations` at top. Use `X | None` not `Optional[X]`. `list[T]` not `List[T]`.
- Ruff: line-length 100, target py313.
- Frontend: path aliases via `@/` (maps to `src/`). shadcn/ui components in `components/ui/`.
- Tests: `pytest-asyncio` with `asyncio_mode = "auto"`. API tests use `httpx.ASGITransport` with dependency overrides and `FakeGitStorage`.
- **When modifying or creating features/bug fixes, always review and update related test files.** Ensure tests pass before committing.
- **Cross-component sync (MANDATORY)**: Helix has three tightly coupled parts — backend (`api/`), frontend (`frontend/`), and CLI (`cli/`). **Before finalizing any change**, check all three for sync:
  - **Backend model/endpoint changes** → update frontend API client (`npm run generate-client`), update CLI if it calls the affected code
  - **API response shape changes** → verify frontend components consuming that data, verify CLI output formatting
  - **Core engine changes** (`api/evolution/`, `api/evaluation/`, `api/gateway/`, `api/config/`, `api/dataset/`, `api/registry/`) → these are shared by web API, CLI, and direct Python imports — verify all three consumers
  - **Frontend route/page changes** → check if CLI references those routes (e.g. `helix show` opening web URLs)
  - **Config/env var changes** → update all three: backend settings, frontend `.env.example`, CLI config loader
  - **Database schema changes** → check `ensure_columns()` migration, verify CLI still works against updated DB
  - **Never merge a change that breaks another part.** Run both `pytest` and `npm run test` before submitting.

## Packages (PyPI)

- `helix-engine` (root `pyproject.toml`) — core engine. Deps: pydantic, jinja2, openai, tenacity. No web/DB deps.
- `helix-engine[web]` — adds FastAPI, SQLAlchemy, aiosqlite, asyncpg for the web server.
- `helix-evolve` (`cli/pyproject.toml`) — standalone CLI. Depends on `helix-engine` + typer + rich.
- **Publishing**: Push `engine-v*` or `cli-v*` git tags to trigger PyPI publish via GitHub Actions (`.github/workflows/publish.yml`). Requires trusted publishing configured on PyPI.

## Environment

### Two modes

1. **Developer mode (default)** — single-user, no login required. Recommended for local development and solo use. API keys configured via `.env` or the Settings page.
2. **Multi-user mode** — JWT authentication, per-user API keys stored encrypted in DB, login page. Enable with `HELIX_AUTH_DISABLED=false`. Only needed for shared/team deployments.

### Required in `.env`
```
GENE_OPENROUTER_API_KEY=...      # Or GENE_GEMINI_API_KEY, GENE_OPENAI_API_KEY (at least one)
GENE_DATABASE_URL=sqlite+aiosqlite:///./helix.db  # Optional, defaults to None (must be set for DB features)
```

### Optional
```
CORS_ORIGINS=http://localhost:5173    # Comma-separated, default: localhost dev ports
RATE_LIMIT_PER_MINUTE=120            # Per-IP rate limit, 0 = disabled
HELIX_AUTH_DISABLED=true              # Set to false for multi-user mode
HELIX_SECRET_KEY=...                  # JWT signing key (auto-generated if missing)
```

`VITE_API_URL` — set in production frontend builds to point at the backend (e.g., `https://api.example.com`). Leave empty for local dev.
