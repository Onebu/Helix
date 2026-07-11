> 🌐 [English](README.md) | [中文](README.zh-CN.md)

<p align="center">
  <img src="docs/logo.png" alt="Helix Logo" width="300" />
</p>

<h1 align="center">Helix</h1>

A tool for iteratively improving LLM prompts using automated testing. Helix evolves your prompt text against a dataset of test cases until it passes every case -- without breaking what already works.

## What is Helix?

You provide a prompt template and a dataset of test cases (input/output pairs), and Helix runs a genetic algorithm to discover prompt text that maximizes test case pass rates. The core loop is: evaluate candidates, select parents, refine via multi-turn LLM dialogue, mutate, and repeat.

Multiple isolated populations ("islands") evolve in parallel with periodic migration of top candidates between them. Within each island, the RCC (Refinement through Critical Conversation) mechanism uses a meta-model to diagnose failures in the current prompt and rewrite it with targeted edits. Boltzmann selection balances exploitation of strong candidates with exploration of novel ones.

A core design principle is **non-regression**: new improvements must never break existing passing behavior. Test cases have priority tiers (critical, normal, low), and the fitness function penalizes regressions on critical cases heavily.

Helix includes a web dashboard for configuration, real-time monitoring during evolution runs, and post-run analysis (phylogenetic trees, prompt diffs, mutation effectiveness statistics).

Helix provides a FastAPI service, a React dashboard, and an importable Python evolution engine.

## Key Features

- Island-model parallel evolution with cyclic migration and stagnation resets
- RCC: multi-turn critic-author dialogue for targeted prompt refinement
- Section-aware structural mutation preserving template variables
- Tiered regression testing (critical / normal / low priority)
- Multi-provider LLM support (Gemini, OpenAI, OpenRouter) via single AsyncOpenAI client
- Real-time evolution monitoring via WebSocket
- Interactive playground for prompt testing with chat streaming
- LLM-powered tool response mocking with format guides
- Interactive lineage graph with click-to-diff
- Multi-language UI (English, Chinese, Spanish)
- Docker Compose for single-command deployment

## Screenshots

| Template & Tools | Evolution Results | Lineage Tree |
|:---:|:---:|:---:|
| ![Template](docs/screenshots/template-tab.png) | ![Run Detail](docs/screenshots/run-detail.png) | ![Lineage](docs/screenshots/lineage.png) |
| Template preview with formatted tool cards | Fitness progression & island summary | Evolution lineage with click-to-diff |

## Quickstart

### Prerequisites

- Python 3.13+
- Node.js 22+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- npm
- An API key for at least one LLM provider (Gemini, OpenAI, or OpenRouter)

### 1. Clone the repository

```bash
git clone https://github.com/Onebu/helix.git
cd helix
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set your API key (at least one provider required):

```
GENE_OPENROUTER_API_KEY=your-key-here
# or GENE_GEMINI_API_KEY=your-key-here
# or GENE_OPENAI_API_KEY=your-key-here
```

Helix runs in **developer mode** by default — single-user, no login required. See [Configuration Guide](docs/CONFIGURATION.md) for all options including multi-user mode, rate limiting, and model setup.

### 3. Start the backend

```bash
uv sync
uv run uvicorn api.web.app:create_app --factory --host 127.0.0.1 --port 8000 --reload
```

### 4. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

### 5. Open the dashboard

Navigate to [http://localhost:5173](http://localhost:5173) in your browser.

### Alternative: Docker

For a single-command start with Docker:

```bash
docker compose up --build
```

This launches the backend, frontend (via nginx on port 80), and a SQLite database. Open [http://localhost](http://localhost) to access the dashboard.

### Alternative: Direct Python

The evolution engine can also be called directly. This example uses the default OpenRouter
provider for all three roles and requires `GENE_OPENROUTER_API_KEY` in `.env`.

```python
import asyncio
from datetime import UTC, datetime

from dotenv import load_dotenv

from api.config.models import GeneConfig
from api.dataset.models import TestCase
from api.evolution.models import EvolutionConfig
from api.evolution.runner import run_evolution
from api.registry.models import PromptRecord

load_dotenv()

prompt = PromptRecord(
    id="support-agent",
    purpose="Answer support questions clearly",
    template="You are a concise support agent.",
    template_variables=set(),
    anchor_variables=set(),
    created_at=datetime.now(UTC),
)
cases = [
    TestCase(
        chat_history=[{"role": "user", "content": "How do I reset my password?"}],
        expected_output={"behavior": ["Gives clear password-reset instructions"]},
    )
]

result = asyncio.run(
    run_evolution(
        config=GeneConfig(),
        prompt_record=prompt,
        cases=cases,
        evolution_config=EvolutionConfig(
            generations=1,
            n_islands=1,
            conversations_per_island=1,
            rcc_rounds=1,
            n_parents=1,
        ),
    )
)
print(result.best_candidate.template)
```

## Architecture Overview

```
api/
  web/            FastAPI REST + WebSocket endpoints
  config/         Pydantic settings + explicit prompt overrides
  dataset/        Test case management
  evaluation/     Fitness scoring, sampling, aggregation
  evolution/      Core loop, islands, RCC, mutation, selection
  gateway/        LLM provider registry, retry, cost tracking
  lineage/        Candidate ancestry tracking
  registry/       Prompt registration and section management
  storage/        SQLAlchemy ORM (SQLite/PostgreSQL)

frontend/src/
  components/     React UI (shadcn/ui, Radix primitives)
  hooks/          useEvolutionSocket (WebSocket), useChatStream (SSE)
  client/         Auto-generated TypeScript API client from OpenAPI
  pages/          Route-level page components
  i18n/           Translation files (en, zh, es)
```

**Backend**: FastAPI with factory pattern, SQLAlchemy 2.0 async ORM, pydantic-settings config cascade, async evolution engine with island-model parallelism.

**Frontend**: React 19 + Vite + TypeScript + Tailwind CSS v4 + shadcn/ui. Recharts for fitness charts, custom SVG for lineage and island views.

**Communication**: REST for CRUD, WebSocket for live evolution events, SSE for chat playground streaming.

For detailed architecture documentation, see [CLAUDE.md](CLAUDE.md).

## Algorithm Details

<details>
<summary>Evolution Pipeline</summary>

```
                    +-----------------------------+
                    |     Evaluate Seed Prompt     |
                    |  (all cases, target model)   |
                    +--------------+--------------+
                                   |
                    +--------------v--------------+
                    |   Clone Seed into N Islands  |
                    +--------------+--------------+
                                   |
              +--------------------v--------------------+
              |          For each generation:           |
              |  +----------------------------------+   |
              |  |  For each island:                |   |
              |  |    For each conversation:         |   |
              |  |      1. Boltzmann parent select   |   |
              |  |      2. RCC critic-author loop    |   |
              |  |      3. Structural mutation (20%) |   |
              |  |      4. Evaluate candidate        |   |
              |  |      5. Update population         |   |
              |  +--------------+-------------------+   |
              |                 |                        |
              |  +--------------v-------------------+   |
              |  |   Cyclic Migration               |   |
              |  |   Island i -> Island (i+1) % N   |   |
              |  +--------------+-------------------+   |
              |                 |                        |
              |  +--------------v-------------------+   |
              |  |   Island Reset (every K gens)    |   |
              |  |   Worst islands <- top globals   |   |
              |  +---------------------------------+   |
              +--------------------+--------------------+
                                   |
                    +--------------v--------------+
                    |    Return Best Candidate     |
                    +-----------------------------+
```

**Boltzmann Selection** -- Softmax-weighted parent sampling: `P(i) = exp((fitness_i - max) / T) / Z`. Temperature controls exploration vs. exploitation.

**RCC (Refinement through Critical Conversation)** -- Multi-turn critic-author dialogue where a meta-model diagnoses failures then rewrites the prompt with minimal, targeted edits.

**Structural Mutation** -- Section-level reorganization (reorder, split, merge) with syntax validation. Applied with configurable probability (default 20%).

**Multi-Island Model** -- Parallel sub-populations with cyclic migration and periodic resets of stagnant islands.

</details>

### Fitness Evaluation

| Expected Output | Scorer | Logic |
|-----------------|--------|-------|
| `tool_calls` only | ExactMatchScorer | Name + argument matching |
| `behavior` only | BehaviorJudgeScorer | LLM judge per criterion |
| Both | Combined | ExactMatch first, then BehaviorJudge |

Scores are aggregated with tier multipliers: Critical (5x), Normal (1x), Low (0.25x). A fitness of 0.0 means all cases pass.

### Configuration Reference

| Parameter | Default | Description |
|-----------|---------|-------------|
| `generations` | 10 | Number of evolution generations |
| `n_islands` | 4 | Parallel island populations |
| `conversations_per_island` | 5 | RCC conversations per island per generation |
| `evolution_profile` | `cost_controlled` | Cost-controlled defaults; use `paper_reference` for four evaluated RCC children and paper-scale initialization |
| `rcc_rounds` | 3 | RCC revisions per conversation; paper-reference default is 4 evaluated and retained children |
| `temperature` | 1.0 | Boltzmann selection temperature |
| `pr_no_parents` | 1/6 | Probability of generating from scratch |
| `structural_mutation_probability` | 0.2 | Chance of structural mutation per conversation |
| `population_cap` | 10 | Max candidates per island; paper-reference default is no cap |
| `budget_cap_usd` | None | LLM-call scheduling cap in USD |

With the defaults, `cost_controlled` produces roughly 200 final RCC candidates at the
10-generation upper-scale concept (`10 * 4 * 5`). `paper_reference` uses four evaluated and
retained RCC children for an upper scale of 800 (`10 * 4 * 5 * 4`), five author attempts, an
accumulating population, paper-scale initialization, and diverse reset selection. Both profiles
provide the critic with evidence from every selected parent. Helix evolves prompt templates rather
than the paper's task solutions, so `paper_reference` is an explicit adaptation, not a claim of
runtime parity. Partial sampling results are scouting data only and never compete with full-suite
evaluations. See [Evolution Algorithm](docs/EVOLUTION_ALGORITHM.md) for the exact comparison.

## Documentation

- [Setup Guide](docs/SETUP.md) -- detailed installation, Docker, and deployment instructions
- [Configuration](docs/CONFIGURATION.md) -- developer vs multi-user mode, environment variables, model roles, auth, and Settings UI
- [Evolution Algorithm](docs/EVOLUTION_ALGORITHM.md) -- profile behavior, paper comparison, candidate scale, and full-evaluation rules
- [Import & Export Formats](docs/IMPORT_EXPORT.md) -- JSON/YAML schemas for test cases and personas
- [Contributing](CONTRIBUTING.md) -- how to contribute to Helix
- [Architecture](CLAUDE.md) -- detailed codebase documentation and conventions

## Tech Stack

- **Backend**: Python 3.13, FastAPI, Pydantic, SQLAlchemy (async), Jinja2
- **Frontend**: React 19, TypeScript, Vite, Tailwind CSS v4, shadcn/ui, Recharts
- **LLM Providers**: Google Gemini, OpenAI, OpenRouter (via AsyncOpenAI)
- **Database**: SQLite (default) or PostgreSQL
- **Deployment**: Docker Compose, Vercel (frontend), Railway/Fly.io (backend)

## References

Inspired by [Mind Evolution / Evolving Deeper LLM Thinking](https://arxiv.org/abs/2501.09891)
(Google DeepMind, 2025). Helix adapts its evolutionary ideas to prompt-template optimization and
does not claim runtime parity with the paper's solution-evolution experiments.

## License

MIT -- see [LICENSE](LICENSE).
