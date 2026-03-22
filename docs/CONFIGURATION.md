# Configuration Guide

Helix is configured through environment variables (`.env` file) and the **Settings UI** in the web interface.

- **`.env` file** — API keys, database URL, default models (set once at startup)
- **Settings UI** — API keys, model/provider per role, temperature, concurrency (editable at runtime)
- **Config tab** — per-prompt model and inference overrides
- **Evolution tab** — per-run parameter overrides

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
| `POSTGRES_PASSWORD` | PostgreSQL password (only with `--profile postgres`) | `helix_dev` |

## Thinking Budget (Gemini models)

When using Gemini models, you can configure thinking/reasoning budget per role in the web UI:

- **Gemini 2.5 series**: "Thinking Budget" — token count (Off / Dynamic / Low 1K / Medium 8K / High 24K)
- **Gemini 3.x series**: "Thinking Level" — categorical (Low / Medium / High)

These are per-run overrides configured in the RunConfigForm. No environment variable — controlled exclusively through the UI.
