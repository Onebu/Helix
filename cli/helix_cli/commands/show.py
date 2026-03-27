"""helix show — display prompt details."""

from __future__ import annotations

import json
from pathlib import Path

import typer
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from helix_cli.project.discovery import resolve_prompt_dir
from helix_cli.project.writer import read_latest_result

console = Console()


def show_command(
    prompt_id: str = typer.Argument(help="Prompt identifier"),
    directory: Path = typer.Option(Path("."), "--dir", "-d", help="Workspace directory"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    """Show details for a prompt."""
    try:
        prompt_dir = resolve_prompt_dir(directory.resolve(), prompt_id)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from None

    prompt_data = yaml.safe_load((prompt_dir / "prompt.yaml").read_text(encoding="utf-8")) or {}
    template = prompt_data.get("template", "")
    variables = prompt_data.get("variables", [])
    tools = prompt_data.get("tools", [])

    # Dataset summary
    dataset_file = prompt_dir / "dataset.yaml"
    cases = []
    if dataset_file.exists():
        ds = yaml.safe_load(dataset_file.read_text(encoding="utf-8")) or {}
        cases = ds.get("cases", [])

    tiers = {"critical": 0, "normal": 0, "low": 0}
    for c in cases:
        tier = c.get("tier", "normal")
        tiers[tier] = tiers.get(tier, 0) + 1

    latest = read_latest_result(prompt_dir)

    if json_output:
        typer.echo(json.dumps({
            "id": prompt_data.get("id", prompt_id),
            "purpose": prompt_data.get("purpose", ""),
            "template_lines": len(template.splitlines()),
            "variables": variables,
            "tools_count": len(tools),
            "test_cases": len(cases),
            "tiers": tiers,
            "latest_result": latest,
        }, indent=2, default=str))
        return

    # Rich display
    lines = template.splitlines()
    preview = "\n".join(lines[:8])
    if len(lines) > 8:
        preview += f"\n[dim]... ({len(lines)} lines total)[/dim]"

    console.print(Panel(
        f"[bold]{prompt_data.get('id', prompt_id)}[/bold]\n"
        f"[dim]{prompt_data.get('purpose', '')}[/dim]",
        border_style="cyan",
    ))

    console.print(f"\n[bold]Template[/bold] ({len(lines)} lines)")
    console.print(Panel(preview, border_style="dim"))

    if variables:
        var_table = Table(show_header=True, show_lines=False)
        var_table.add_column("Name", style="bold")
        var_table.add_column("Type")
        var_table.add_column("Anchor")
        var_table.add_column("Description", style="dim")
        for v in variables:
            var_table.add_row(
                v.get("name", ""),
                v.get("var_type", "string"),
                "[green]yes[/green]" if v.get("is_anchor") else "no",
                v.get("description", ""),
            )
        console.print(f"\n[bold]Variables[/bold] ({len(variables)})")
        console.print(var_table)

    console.print(
        f"\n[bold]Dataset[/bold]  {len(cases)} cases "
        f"({tiers['critical']} critical, {tiers['normal']} normal, {tiers['low']} low)"
    )

    if tools:
        console.print(f"[bold]Tools[/bold]    {len(tools)}")

    if latest:
        fitness = latest.get("fitness", {})
        cost = latest.get("cost", {})
        console.print(
            f"\n[bold]Latest Run[/bold]  {latest.get('run_id', '?')} "
            f"| fitness: {fitness.get('score', '?')} "
            f"| cost: ${cost.get('total_cost_usd', 0):.4f} "
            f"| {latest.get('termination_reason', '?')}"
        )
