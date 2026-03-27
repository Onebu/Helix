# helix-cli

CLI for Helix evolutionary prompt optimization.

## Install

```bash
# From the Helix repo root:
uv pip install -e .        # core engine
uv pip install -e cli/     # CLI
```

## Quick Start

```bash
helix init my-prompt       # scaffold prompt directory
# edit my-prompt/prompt.yaml, dataset.yaml, config.yaml
helix evolve my-prompt     # run evolution
helix results my-prompt    # view results
helix accept my-prompt     # apply evolved template
```

## Commands

| Command | Description |
|---------|-------------|
| `helix init <id>` | Scaffold a new prompt directory |
| `helix list` | List prompts in workspace |
| `helix show <id>` | Display prompt details |
| `helix evolve <id>` | Run prompt evolution |
| `helix results <id>` | Show evolution results |
| `helix accept <id>` | Apply evolved template to prompt.yaml |

All commands support `--json` for machine-readable output.
