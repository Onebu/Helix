"""helix results — show evolution results."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

from helix_cli.display.tables import result_summary_panel
from helix_cli.project.discovery import resolve_prompt_dir
from helix_cli.project.writer import read_latest_result, read_result

console = Console()


def results_command(
    prompt_id: str = typer.Argument(help="Prompt identifier"),
    run: str | None = typer.Option(None, "--run", "-r", help="Specific run ID (e.g. run-001)"),
    directory: Path = typer.Option(Path("."), "--dir", "-d", help="Workspace directory"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    template: bool = typer.Option(False, "--template", "-t", help="Print only the best template"),
) -> None:
    """Show evolution results for a prompt."""
    try:
        prompt_dir = resolve_prompt_dir(directory.resolve(), prompt_id)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from None

    result = read_result(prompt_dir, run) if run else read_latest_result(prompt_dir)

    if not result:
        console.print(f"[yellow]No results found for '{prompt_id}'.[/yellow]")
        raise typer.Exit(1)

    if template:
        typer.echo(result.get("best_template", ""))
        return

    if json_output:
        typer.echo(json.dumps(result, indent=2, default=str))
        return

    # Rich display
    console.print(result_summary_panel(result))

    best = result.get("best_template", "")
    if best:
        console.print("\n[bold]Best Template[/bold]")
        console.print(Panel(
            Syntax(best, "markdown", theme="monokai", word_wrap=True),
            border_style="dim",
        ))
