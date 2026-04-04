# Configuration Guide

Helix is configured through environment variables (`.env` file) and the **Settings UI** in the web interface.

- **`.env` file** — API keys, database URL, default models (set once at startup)
- **Settings UI** — API keys, model/provider per role, temperature, concurrency (editable at runtime)
- **Config tab** — per-prompt model and inference overrides
- **Evolution tab** — per-run parameter overrides

## Two Modes

Helix runs in one of two modes:

### Developer Mode (default)

Single-user, no login required. Ideal for local development and solo use.

- No authentication — all endpoints are open
- API keys configured via `.env` or the Settings page (stored globally)
- This is the recommended mode for most users

### Multi-User Mode

JWT authentication with per-user data isolation. For shared or team deployments.

- Login/register page with username + password
- API keys stored encrypted (Fernet) per user in the database
- Each user sees only their own settings and API keys
- Enable with: `HELIX_AUTH_DISABLED=false`

## Quick Start

```bash
cp .env.example .env
# Edit .env and add your API key(s)
```

## Environment Variables

All environment variables use the `GENE_` prefix.

### Required

| Variable | Description |
|----------|-------------|
| `GENE_GEMINI_API_KEY` | Google Gemini API key. Required for Gemini models. Get one at [aistudio.google.com](https://aistudio.google.com/apikey) |

### Optional — API Keys

| Variable | Description | Default |
|----------|-------------|---------|
| `GENE_OPENROUTER_API_KEY` | OpenRouter API key. Required only if using OpenRouter models. | `None` |
| `GENE_DATABASE_URL` | Database connection string for evolution history persistence. | `None` (no DB, history endpoint returns 503) |

### Model Configuration

Each evolution run uses three model roles:

| Role | What it does |
|------|-------------|
| **Meta** | The "critic" and "author" — evaluates candidates and writes improved prompts (RCC engine) |
| **Target** | The model being optimized for — test cases are evaluated against this model's responses |
| **Judge** | Evaluates behavior criteria (BehaviorJudgeScorer) for test cases that use LLM-as-judge scoring |

Default models and providers:

| Variable | Description | Default |
|----------|-------------|---------|
| `GENE_META_MODEL` | Meta role model ID | `anthropic/claude-sonnet-4` |
| `GENE_META_PROVIDER` | Meta role provider | `openrouter` |
| `GENE_TARGET_MODEL` | Target role model ID | `openai/gpt-4o-mini` |
| `GENE_TARGET_PROVIDER` | Target role provider | `openrouter` |
| `GENE_JUDGE_MODEL` | Judge role model ID | `anthropic/claude-sonnet-4` |
| `GENE_JUDGE_PROVIDER` | Judge role provider | `openrouter` |

**Providers:** `gemini` (Google Gemini direct) or `openrouter` (OpenRouter proxy).

**Model IDs:**
- For `gemini` provider: use Gemini model names like `gemini-2.5-flash`, `gemini-2.5-pro`, `gemini-3-flash-preview`
- For `openrouter` provider: use OpenRouter model IDs like `anthropic/claude-sonnet-4`, `openai/gpt-4o-mini`

**Per-run overrides:** The web UI allows overriding model/provider per role for individual evolution runs without changing server defaults.

### All-Gemini Configuration Example

```bash
# .env — all three roles using Gemini directly (cheapest setup)
GENE_GEMINI_API_KEY=your-key-here
GENE_META_MODEL=gemini-2.5-flash
GENE_META_PROVIDER=gemini
GENE_TARGET_MODEL=gemini-3-flash-preview
GENE_TARGET_PROVIDER=gemini
GENE_JUDGE_MODEL=gemini-2.5-flash
GENE_JUDGE_PROVIDER=gemini
```

### Inference Parameters

These control the LLM generation behavior for the target model:

| Variable | Description | Default |
|----------|-------------|---------|
| `GENE_GENERATION__TEMPERATURE` | Sampling temperature (0 = deterministic) | `0.7` |
| `GENE_GENERATION__MAX_TOKENS` | Maximum output tokens | `4096` |
| `GENE_GENERATION__TOP_P` | Nucleus sampling threshold | `None` |
| `GENE_GENERATION__TOP_K` | Top-K sampling | `None` |
| `GENE_GENERATION__FREQUENCY_PENALTY` | Frequency penalty | `None` |
| `GENE_GENERATION__PRESENCE_PENALTY` | Presence penalty | `None` |

Note the double underscore `__` for nested config (e.g., `GENE_GENERATION__TEMPERATURE=0.5`).

Per-run overrides are available in the web UI under "Inference Parameters".

### Database

| Variable | Description | Default |
|----------|-------------|---------|
| `GENE_DATABASE_URL` | Async database URL | `None` |

Supported databases:
- **SQLite** (recommended for local dev): `sqlite+aiosqlite:///helix.db`
- **PostgreSQL**: `postgresql+asyncpg://user:pass@host:5432/dbname`

Without a database configured:
- Evolution runs still work (results stream via WebSocket)
- History and run detail pages return 503
- No persistent storage of run results

The app automatically creates tables and migrates schema on startup.

### Web Server

| Variable | Description | Default |
|----------|-------------|---------|
| `CORS_ORIGINS` | Allowed CORS origins (comma-separated) | `http://localhost:5173,http://localhost:3000` |
| `RATE_LIMIT_PER_MINUTE` | Per-IP request limit for API endpoints (0 = disabled) | `120` |
| `RATE_LIMIT_EVOLUTION` | Per-IP limit for evolution start (expensive LLM calls) | `10` |

### Authentication (Multi-User Mode)

| Variable | Description | Default |
|----------|-------------|---------|
| `HELIX_AUTH_DISABLED` | `true` = developer mode (no login), `false` = multi-user mode | `true` |
| `HELIX_SECRET_KEY` | JWT signing key. Auto-generated and saved to `.env` if missing | (auto-generated) |
| `HELIX_JWT_EXPIRY_HOURS` | JWT token lifetime in hours | `24` |

When multi-user mode is enabled (`HELIX_AUTH_DISABLED=false`):
- All API endpoints require a Bearer JWT token
- WebSocket connections require a `?token=` query parameter
- Users register/login at `/api/auth/register` and `/api/auth/login`
- The frontend shows a login page and stores the JWT in localStorage
- API keys saved via Settings are scoped per user and encrypted with Fernet

### Langfuse Integration

Optional — for cold-start trace import only.

| Variable | Description | Default |
|----------|-------------|---------|
| `GENE_LANGFUSE_PUBLIC_KEY` | Langfuse public key | `None` |
| `GENE_LANGFUSE_SECRET_KEY` | Langfuse secret key | `None` |
| `GENE_LANGFUSE_HOST` | Langfuse host URL | `https://cloud.langfuse.com` |

### Runtime

| Variable | Description | Default |
|----------|-------------|---------|
| `GENE_CONCURRENCY_LIMIT` | Max concurrent LLM calls | `10` |
| `GENE_PROMPTS_DIR` | Directory for prompt files | `./prompts` |

## Docker Configuration

### Production (docker-compose.yml)

```bash
# Basic (SQLite, no PostgreSQL)
docker compose up

# With PostgreSQL
docker compose --profile postgres up
```

Set environment variables in `.env` — Docker Compose reads it automatically.

### Development (docker-compose.dev.yml)

```bash
docker compose -f docker-compose.dev.yml up
```

Uses volume mounts for hot reload on both backend and frontend.

### Docker Environment Variables

Same `GENE_*` variables apply. Additional Docker-specific:

| Variable | Description | Default |
|----------|-------------|---------|
| `POSTGRES_PASSWORD` | PostgreSQL password (only with `--profile postgres`). **Required** in production compose — no default. Dev compose defaults to `helix_dev`. | — |

## Thinking Budget (Gemini models)

When using Gemini models, you can configure thinking/reasoning budget per role in the web UI:

- **Gemini 2.5 series**: "Thinking Budget" — token count (Off / Dynamic / Low 1K / Medium 8K / High 24K)
- **Gemini 3.x series**: "Thinking Level" — categorical (Low / Medium / High)

These are per-run overrides configured in the RunConfigForm. No environment variable — controlled exclusively through the UI.
