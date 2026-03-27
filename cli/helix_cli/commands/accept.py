"""helix accept — apply an evolved template back to prompt.yaml."""

from __future__ import annotations

import json
from pathlib import Path

import typer
import yaml
from rich.console import Console

from helix_cli.project.discovery import resolve_prompt_dir
from helix_cli.project.writer import read_latest_result, read_result

console = Console()


def accept_command(
    prompt_id: str = typer.Argument(help="Prompt identifier"),
    run: str | None = typer.Option(None, "--run", "-r", help="Specific run ID (e.g. run-001)"),
    directory: Path = typer.Option(Path("."), "--dir", "-d", help="Workspace directory"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    """Accept an evolved template and update prompt.yaml."""
    try:
        prompt_dir = resolve_prompt_dir(directory.resolve(), prompt_id)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from None

    result = read_result(prompt_dir, run) if run else read_latest_result(prompt_dir)

    if not result:
        console.print(f"[yellow]No results found for '{prompt_id}'.[/yellow]")
        raise typer.Exit(1)

    evolved_template = result.get("best_template")
    if not evolved_template:
        console.print("[red]Result has no best_template.[/red]")
        raise typer.Exit(1)

    # Update prompt.yaml
    prompt_path = prompt_dir / "prompt.yaml"
    prompt_data = yaml.safe_load(prompt_path.read_text(encoding="utf-8")) or {}
    old_template = prompt_data.get("template", "")
    prompt_data["template"] = evolved_template

    prompt_path.write_text(
        yaml.dump(prompt_data, default_flow_style=False, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    run_id = result.get("run_id", "?")
    fitness = result.get("fitness", {}).get("score", "?")

    if json_output:
        typer.echo(json.dumps({
            "status": "accepted",
            "run": run_id,
            "fitness": fitness,
            "prompt_file": str(prompt_path),
        }))
    else:
        old_lines = len(old_template.splitlines())
        new_lines = len(evolved_template.splitlines())
        console.print(
            f"[green]Accepted template from {run_id}[/green]\n"
            f"  Fitness: [bold]{fitness}[/bold]\n"
            f"  Template: {old_lines} -> {new_lines} lines\n"
            f"  Updated: {prompt_path}"
        )
