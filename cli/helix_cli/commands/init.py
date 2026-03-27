"""helix init — scaffold a new prompt directory."""

from __future__ import annotations

import json
import re
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

from helix_cli.project.scaffold import (
    scaffold_config_yaml,
    scaffold_dataset_yaml,
    scaffold_prompt_yaml,
)

console = Console()
_SLUG_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")


def init_command(
    prompt_id: str = typer.Argument(help="Prompt identifier (lowercase slug)"),
    directory: Path = typer.Option(Path("."), "--dir", "-d", help="Workspace directory"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    """Scaffold a new prompt directory with template YAML files."""
    if not _SLUG_PATTERN.match(prompt_id) or len(prompt_id) > 100:
        console.print(
            f"[red]Invalid prompt ID '{prompt_id}'. "
            "Must be lowercase alphanumeric + hyphens, 1-100 chars.[/red]"
        )
        raise typer.Exit(1)

    prompt_dir = directory.resolve() / prompt_id
    if prompt_dir.exists():
        console.print(f"[red]Directory '{prompt_dir}' already exists.[/red]")
        raise typer.Exit(1)

    prompt_dir.mkdir(parents=True)
    (prompt_dir / "results").mkdir()

    files = []
    for name, content in [
        ("prompt.yaml", scaffold_prompt_yaml(prompt_id)),
        ("dataset.yaml", scaffold_dataset_yaml()),
        ("config.yaml", scaffold_config_yaml()),
    ]:
        path = prompt_dir / name
        path.write_text(content, encoding="utf-8")
        files.append(str(path))

    if json_output:
        typer.echo(json.dumps({"status": "created", "path": str(prompt_dir), "files": files}))
    else:
        console.print(Panel(
            f"[green]Created prompt directory:[/green] {prompt_dir}\n\n"
            f"  prompt.yaml    Prompt template & variables\n"
            f"  dataset.yaml   Test cases\n"
            f"  config.yaml    Model & evolution settings\n"
            f"  results/       Evolution results\n\n"
            f"[dim]Next: edit prompt.yaml, add test cases, then run[/dim]\n"
            f"  [bold]helix evolve {prompt_id}[/bold]",
            title="helix init",
            border_style="green",
        ))
