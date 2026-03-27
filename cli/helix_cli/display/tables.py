"""Shared Rich formatting utilities."""

from __future__ import annotations

from rich.panel import Panel
from rich.table import Table


def result_summary_panel(result: dict) -> Panel:
    """Create a Rich panel summarizing an evolution result."""
    fitness = result.get("fitness", {})
    cost = result.get("cost", {})
    models = result.get("effective_models", {})

    stats = Table.grid(padding=(0, 2))
    stats.add_column(justify="right", style="dim")
    stats.add_column()

    stats.add_row("Run", result.get("run_id", "?"))
    stats.add_row("Fitness", f"{fitness.get('score', '?')}")
    stats.add_row("Normalized", f"{fitness.get('normalized_score', '?')}")

    seed = result.get("seed_fitness")
    if seed is not None:
        delta = fitness.get("score", 0) - seed
        stats.add_row("Seed", f"{seed} ({'+' if delta >= 0 else ''}{delta:.4f})")

    stats.add_row("Cost", f"${cost.get('total_cost_usd', 0):.4f}")
    stats.add_row("Reason", result.get("termination_reason", "?"))

    if models:
        meta = models.get("meta_model", "?")
        target = models.get("target_model", "?")
        stats.add_row("Meta", meta)
        stats.add_row("Target", target)

    gens = result.get("generation_records", [])
    if gens:
        stats.add_row("Generations", str(len(gens)))

    return Panel(stats, title="[bold]Evolution Result[/bold]", border_style="green")


def variables_table(variables: list[dict]) -> Table:
    """Create a Rich table of variable definitions."""
    table = Table(show_header=True, show_lines=False)
    table.add_column("Name", style="bold")
    table.add_column("Type")
    table.add_column("Anchor")
    table.add_column("Description", style="dim")
    for v in variables:
        table.add_row(
            v.get("name", ""),
            v.get("var_type", "string"),
            "[green]yes[/green]" if v.get("is_anchor") else "no",
            v.get("description", ""),
        )
    return table
