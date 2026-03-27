# Helix CLI

Standalone command-line tool for evolutionary prompt optimization. Evolve your LLM prompts against test cases without running a web server.

## Overview

The Helix CLI runs the same evolution engine as the web UI, but operates on local YAML files. Define your prompt, test cases, and configuration as files in a directory, then run evolution from the terminal.

Key features:

- **Standalone** -- no web server or database needed
- **YAML-based** -- human-readable prompt and test case definitions
- **Agent-friendly** -- every command supports `--json` for machine-readable output
- **Same engine** -- uses the identical evolution pipeline as the web UI

## Installation

### Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- An API key for at least one LLM provider (Gemini, OpenAI, or OpenRouter)

### Install from source

```bash
git clone https://github.com/Onebu/helix.git
cd helix

# Install the core engine and CLI
uv pip install -e .          # core engine (api package)
uv pip install -e cli/       # CLI tool

# Verify installation
helix --help
```

If `helix` isn't on your PATH, use the full path to the venv binary:

```bash
.venv/bin/helix --help
```

### Configure API key

Create a `.env` file in your working directory (or set environment variables):

```bash
# Choose at least one provider
GENE_GEMINI_API_KEY=your-gemini-key
# GENE_OPENAI_API_KEY=your-openai-key
# GENE_OPENROUTER_API_KEY=your-openrouter-key
```

## Quick Start

```bash
# 1. Create a new prompt project
helix init customer-support

# 2. Edit the YAML files (see File Format below)
#    - customer-support/prompt.yaml
#    - customer-support/dataset.yaml
#    - customer-support/config.yaml

# 3. Run evolution
helix evolve customer-support

# 4. Review the results
helix results customer-support

# 5. Accept the evolved template
helix accept customer-support
```

## Commands

### `helix init <prompt-id>`

Scaffold a new prompt directory with template YAML files.

```bash
helix init my-prompt
helix init my-prompt --dir /path/to/workspace
helix init my-prompt --json    # machine-readable output
```

Creates:
```
my-prompt/
  prompt.yaml      # prompt template and variable definitions
  dataset.yaml     # test cases for fitness evaluation
  config.yaml      # model, provider, and evolution settings
  results/         # evolution results (populated by helix evolve)
```

### `helix list`

List all prompt directories in the current workspace.

```bash
helix list
helix list --dir /path/to/workspace
helix list --json
```

Output:
```
                     Prompts
┏━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━┓
┃ ID               ┃ Purpose               ┃ Cases ┃ Runs ┃
┡━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━┩
│ customer-support │ Handle support tickets │     8 │    3 │
│ summarizer       │ Summarize documents    │     5 │    1 │
└──────────────────┴───────────────────────┴───────┴──────┘
```

### `helix show <prompt-id>`

Display detailed information about a prompt: template preview, variables, dataset summary, and latest evolution result.

```bash
helix show customer-support
helix show customer-support --json
```

### `helix evolve <prompt-id>`

Run the evolution engine against your prompt and test cases. Shows a live Rich progress display with generation-by-generation fitness updates.

```bash
# Basic usage
helix evolve customer-support

# Override evolution parameters
helix evolve customer-support --generations 5 --islands 2 --budget 1.00

# JSON output (no live display, suitable for scripts/agents)
helix evolve customer-support --json
```

Options:
| Flag | Description |
|------|-------------|
| `--generations, -g` | Override number of generations |
| `--islands, -i` | Override number of islands |
| `--budget, -b` | Override budget cap in USD |
| `--json` | JSON output, no live display |

The live progress display shows:
```
╭──────────────── helix evolve customer-support ─────────────────╮
│  Generation  7/10  [████████████████████░░░░]  70%             │
│                                                                │
│  Best Fitness  -0.50  (seed: -6.00, +5.50)                     │
│  Avg Fitness   -2.10                                           │
│  Candidates    140                                             │
│  Cost          $0.23 / $2.00                                   │
│  Elapsed       1m 42s                                          │
╰────────────────────────────────────────────────────────────────╯
```

Results are automatically saved to `results/run-NNN.yaml`.

### `helix results <prompt-id>`

Display evolution results. Shows fitness, cost, model info, and the best evolved template.

```bash
# Latest result
helix results customer-support

# Specific run
helix results customer-support --run run-001

# JSON output
helix results customer-support --json

# Print only the evolved template (useful for piping)
helix results customer-support --template
```

### `helix accept <prompt-id>`

Accept an evolved template by copying it back into `prompt.yaml`, replacing the current template.

```bash
helix accept customer-support
helix accept customer-support --run run-001    # accept a specific run
helix accept customer-support --json
```

### Global Options

Every command supports:
| Flag | Description |
|------|-------------|
| `--dir, -d` | Workspace directory (default: current directory) |
| `--json` | Machine-readable JSON output |

## File Format Reference

### `prompt.yaml`

Defines the prompt template, variables, and optional tool definitions.

```yaml
# Required fields
id: customer-support                    # lowercase slug (a-z, 0-9, hyphens)
purpose: "Handle customer support tickets"

# The Jinja2 template. Variables use {{ variable_name }} syntax.
template: |
  You are a customer support agent for {{ company_name }}.

  Customer: {{ customer_name }}
  Issue: {{ issue_description }}

  Resolve the issue professionally and empathetically.
  Always offer a concrete next step.

# Variable definitions (optional).
# If omitted, variables are auto-extracted from the template.
# Define explicitly to set types, descriptions, and anchor status.
variables:
  - name: company_name
    description: "Company brand name"
    var_type: string                    # string | number | boolean | object | array
    is_anchor: true                    # anchored = preserved during evolution

  - name: customer_name
    description: "Customer's display name"
    var_type: string
    is_anchor: true

  - name: issue_description
    description: "Description of the customer's issue"
    var_type: string
    is_anchor: false

# Tool definitions (optional, OpenAI function-calling format)
tools:
  - type: function
    function:
      name: lookup_order
      description: "Look up a customer's order by ID"
      parameters:
        type: object
        properties:
          order_id:
            type: string
        required: [order_id]

  - type: function
    function:
      name: create_ticket
      description: "Create a support ticket"
      parameters:
        type: object
        properties:
          subject:
            type: string
          priority:
            type: string
            enum: [low, normal, high, urgent]
        required: [subject, priority]
```

**Anchor variables** are preserved during evolution. The evolution engine will never remove `{{ company_name }}` from the template if it's marked as an anchor. Use anchors for variables that must always be present (brand names, user identifiers, etc.).

### `dataset.yaml`

Defines test cases that the evolution engine scores prompts against. Each case specifies inputs, conversation context, and expected behavior.

```yaml
cases:
  # --- Simple behavior test ---
  - name: "Greeting"
    tier: normal                        # critical | normal | low
    tags: [greeting, basic]
    variables:
      company_name: "Acme Corp"
      customer_name: "Alice"
      issue_description: ""
    chat_history:
      - role: user
        content: "Hi, I need help with my order"
    expected_output:
      require_content: true             # must produce text (not just tool calls)
      behavior:                         # LLM-judged criteria
        - "Greets the customer by name"
        - "Asks for order details or offers to look it up"

  # --- Tool call test ---
  - name: "Order lookup"
    tier: critical                      # critical cases have 5x weight
    tags: [tool-call, order]
    variables:
      company_name: "Acme Corp"
      customer_name: "Bob"
      issue_description: "Where is my order #12345?"
    chat_history:
      - role: user
        content: "Where is my order #12345?"
    expected_output:
      match_args:                       # expect a specific tool call
        tool_name: lookup_order
        tool_args:
          order_id: "12345"

  # --- Multi-turn conversation ---
  - name: "Escalation flow"
    tier: normal
    tags: [escalation, multi-turn]
    variables:
      company_name: "Acme Corp"
      customer_name: "Carol"
      issue_description: "Product is defective"
    chat_history:
      - role: user
        content: "My product broke after one day!"
      - role: assistant
        content: "I'm sorry to hear that. Can you describe the issue?"
      - role: user
        content: "The screen cracked on its own. I want a full refund NOW."
    expected_output:
      require_content: true
      behavior:
        - "Shows empathy for the customer's frustration"
        - "Offers a concrete resolution (refund, replacement, or escalation)"
        - "Does not make promises outside company policy"

  # --- Edge case ---
  - name: "Off-topic request"
    tier: low                           # low priority = 0.25x weight
    tags: [edge-case]
    variables:
      company_name: "Acme Corp"
      customer_name: "Dave"
      issue_description: ""
    chat_history:
      - role: user
        content: "What's the meaning of life?"
    expected_output:
      require_content: true
      behavior:
        - "Politely redirects to support topics"
        - "Does not engage with the off-topic question"
```

**Test case tiers** control how much each case affects the fitness score:
| Tier | Weight | Use for |
|------|--------|---------|
| `critical` | 5x | Must-pass cases, core functionality |
| `normal` | 1x | Standard behavior expectations |
| `low` | 0.25x | Nice-to-have, edge cases |

**Expected output fields:**
| Field | Type | Description |
|-------|------|-------------|
| `require_content` | bool | Response must include text content |
| `behavior` | list[str] | Natural language criteria judged by LLM |
| `match_args` | dict | Expected tool call (`tool_name` + `tool_args`) |
| `tool_calls` | list[dict] | Multiple expected tool calls |
| `must_contain` | str | Response must contain this substring |

A fitness score of **0.0** means all cases pass. Negative scores indicate failures (more negative = worse).

### `config.yaml`

Configures models, providers, and evolution hyperparameters. All fields are optional and override environment variables.

```yaml
# Model configuration per role
models:
  meta:                                 # generates critique & refinement
    provider: gemini                    # gemini | openrouter | openai
    model: gemini-2.5-pro
    thinking_budget: -1                 # Gemini-specific (-1 = dynamic)
  target:                               # evaluates prompts against test cases
    provider: gemini
    model: gemini-2.5-flash
  judge:                                # scores evaluation results
    provider: gemini
    model: gemini-2.5-flash

# Evolution hyperparameters
evolution:
  generations: 10                       # number of evolution generations
  islands: 4                            # parallel island populations
  conversations_per_island: 5           # RCC conversations per island per gen
  budget_cap_usd: 2.00                  # stop when cost exceeds this
  # n_seq: 3                            # critic-author turns per conversation
  # temperature: 1.0                    # Boltzmann selection temperature
  # structural_mutation_probability: 0.2
  # population_cap: 10                  # max candidates per island
  # n_emigrate: 5                       # migration count between islands
  # reset_interval: 3                   # gens between island resets
  # adaptive_sampling: false            # enable adaptive case sampling

# Inference parameters (passed to LLM API calls)
generation:
  temperature: 0.7
  max_tokens: 4096
  # top_p: null
  # top_k: null
  # frequency_penalty: null
  # presence_penalty: null
```

### `results/run-NNN.yaml`

Written automatically by `helix evolve`. Contains the full evolution result.

```yaml
run_id: run-001
timestamp: "2026-03-27T22:35:28+00:00"
termination_reason: perfect_fitness     # or generations_complete, budget_exhausted

best_template: |
  You are a customer support agent for {{ company_name }}...
  (the full evolved template)

fitness:
  score: 0.0                           # 0.0 = all cases pass
  normalized_score: 0.0

seed_fitness: -6.0                      # original template's score

cost:
  total_calls: 342
  total_input_tokens: 1250000
  total_output_tokens: 85000
  total_cost_usd: 0.47

effective_models:
  meta_model: gemini-2.5-pro
  meta_provider: gemini
  target_model: gemini-2.5-flash
  target_provider: gemini
  judge_model: gemini-2.5-flash
  judge_provider: gemini

generation_records:
  - generation: 1
    best_fitness: -2.0
    avg_fitness: -4.5
    candidates_evaluated: 20
  - generation: 2
    best_fitness: -0.5
    avg_fitness: -1.8
    candidates_evaluated: 20

config_snapshot:
  evolution:
    generations: 10
    islands: 4
    conversations_per_island: 5
```

## Configuration Cascade

Settings are resolved in priority order (highest wins):

1. **CLI flags** (`--generations 5`, `--budget 1.00`)
2. **config.yaml** values
3. **Environment variables** (`GENE_GEMINI_API_KEY`, `GENE_META_MODEL`, etc.)
4. **Defaults** (built into the engine)

This means you can set defaults in `config.yaml`, override per-run with CLI flags, and keep secrets in `.env` or environment variables.

## Agent Integration

Every command supports `--json` for structured output, making the CLI usable by AI coding agents like Claude Code.

Example CLAUDE.md configuration for a project using Helix:

```markdown
## Prompt Optimization

Run `helix evolve <prompt-id> --json` to optimize prompts.
Run `helix results <prompt-id> --json` to check evolution results.
Run `helix accept <prompt-id>` to apply the best evolved template.
Run `helix show <prompt-id> --json` to inspect prompt configuration.
```

Example agent workflow:

```bash
# Agent creates a prompt
helix init my-agent-prompt --json

# Agent checks current state
helix show my-agent-prompt --json

# Agent runs evolution and parses result
helix evolve my-agent-prompt --generations 5 --json

# Agent reads the evolved template
helix results my-agent-prompt --template

# Agent accepts if fitness improved
helix accept my-agent-prompt --json
```

## Typical Workflow

```
  helix init <id>           Create prompt directory
        |
        v
  Edit YAML files           Define template, test cases, config
        |
        v
  helix evolve <id>         Run evolution (live progress)
        |
        v
  helix results <id>        Review fitness, cost, evolved template
        |
       / \
      /   \
     v     v
  Accept   Iterate          Apply template or adjust test cases
```

1. **Initialize**: `helix init` creates a starter directory
2. **Define**: Write your prompt template in `prompt.yaml`, add test cases to `dataset.yaml`
3. **Configure**: Set models and budget in `config.yaml` (or use defaults)
4. **Evolve**: `helix evolve` runs the engine and saves results
5. **Review**: `helix results` shows what improved and by how much
6. **Accept or iterate**: `helix accept` applies the evolved template, or adjust test cases and re-run

## Troubleshooting

**"Missing API key for gemini"**
Set your API key in a `.env` file or environment:
```bash
export GENE_GEMINI_API_KEY=your-key-here
```

**"No test cases found"**
Add at least one test case to `dataset.yaml`. See the file format reference above.

**"Prompt not found"**
Make sure you're in the right directory. Use `helix list` to see available prompts, or `--dir` to specify the workspace.

**Evolution finishes instantly with perfect fitness**
Your test cases may be too easy. Add more specific `behavior` criteria or `critical`-tier cases to challenge the prompt.
