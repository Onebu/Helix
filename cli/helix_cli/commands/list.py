"""helix list — list prompts in the workspace."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from helix_cli.project.discovery import find_prompts

console = Console()


def list_command(
    directory: Path = typer.Option(Path("."), "--dir", "-d", help="Workspace directory"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    """List all prompt directories in the workspace."""
    prompts = find_prompts(directory.resolve())

    if json_output:
        typer.echo(json.dumps(prompts, indent=2))
        return

    if not prompts:
        console.print("[dim]No prompts found. Run [bold]helix init <id>[/bold] to create one.[/dim]")
        return

    table = Table(title="Prompts", show_lines=False)
    table.add_column("ID", style="bold")
    table.add_column("Purpose", style="dim")
    table.add_column("Cases", justify="right")
    table.add_column("Runs", justify="right")

    for p in prompts:
        table.add_row(
            p["id"],
            p["purpose"][:60] + ("..." if len(p["purpose"]) > 60 else ""),
            str(p["test_cases"]),
            str(p["results_count"]),
        )

    console.print(table)
