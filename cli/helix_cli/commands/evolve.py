"""helix evolve — run prompt evolution."""

from __future__ import annotations

import asyncio
import json
import signal
from pathlib import Path

import typer
from rich.console import Console

from helix_cli.display.progress import EvolutionProgress
from helix_cli.project.discovery import resolve_prompt_dir
from helix_cli.project.loader import load_config, load_dataset, load_prompt
from helix_cli.project.writer import write_result

console = Console()


def evolve_command(
    prompt_id: str = typer.Argument(help="Prompt identifier"),
    directory: Path = typer.Option(Path("."), "--dir", "-d", help="Workspace directory"),
    generations: int | None = typer.Option(None, "--generations", "-g", help="Override generations"),
    islands: int | None = typer.Option(None, "--islands", "-i", help="Override island count"),
    budget: float | None = typer.Option(None, "--budget", "-b", help="Override budget cap (USD)"),
    json_output: bool = typer.Option(False, "--json", help="JSON output (no live display)"),
) -> None:
    """Run prompt evolution using local YAML files."""
    try:
        prompt_dir = resolve_prompt_dir(directory.resolve(), prompt_id)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from None

    # Load YAML files
    try:
        prompt_record = load_prompt(prompt_dir)
        cases = load_dataset(prompt_dir)
        if not cases:
            console.print("[red]No test cases found in dataset.yaml. Add at least one case.[/red]")
            raise typer.Exit(1)

        cli_overrides = {}
        if generations is not None:
            cli_overrides["generations"] = generations
        if islands is not None:
            cli_overrides["n_islands"] = islands
        if budget is not None:
            cli_overrides["budget_cap_usd"] = budget

        config, evo_config, run_kwargs = load_config(prompt_dir, cli_overrides=cli_overrides)
    except Exception as e:
        console.print(f"[red]Failed to load project files: {e}[/red]")
        raise typer.Exit(1) from None

    # Validate API key
    for role in ("meta", "target", "judge"):
        provider = getattr(config, f"{role}_provider")
        key_field = f"{provider}_api_key" if provider != "openai" else "openai_api_key"
        if not getattr(config, key_field, None):
            console.print(
                f"[red]Missing API key for {provider} ({role} role).[/red]\n"
                f"[dim]Run [bold]helix setup[/bold] to configure, "
                f"or set GENE_{key_field.upper()} in .env[/dim]"
            )
            raise typer.Exit(1)

    if not json_output:
        console.print(
            f"[bold]Starting evolution:[/bold] {prompt_id}\n"
            f"  {evo_config.generations} generations, "
            f"{evo_config.n_islands} islands, "
            f"{len(cases)} test cases"
        )

    result = asyncio.run(
        _run_evolution(config, prompt_record, cases, evo_config, run_kwargs, json_output)
    )

    if result is None:
        console.print("[yellow]Evolution cancelled.[/yellow]")
        raise typer.Exit(1)

    # Write result
    config_snapshot = {
        "evolution": {
            "generations": evo_config.generations,
            "islands": evo_config.n_islands,
            "conversations_per_island": evo_config.conversations_per_island,
        },
    }
    result_path = write_result(prompt_dir, result, config_snapshot)

    if json_output:
        typer.echo(json.dumps({
            "status": "complete",
            "run_id": result_path.stem,
            "result_file": str(result_path),
            "termination_reason": result.termination_reason,
            "best_fitness": result.best_candidate.fitness_score,
            "normalized_score": result.best_candidate.normalized_score,
            "total_cost_usd": result.total_cost.get("total_cost_usd", 0),
        }, indent=2))
    else:
        console.print(f"\n[green]Result saved:[/green] {result_path}")
        console.print(
            f"  Fitness: [bold]{result.best_candidate.fitness_score:.4f}[/bold]  "
            f"Cost: ${result.total_cost.get('total_cost_usd', 0):.4f}  "
            f"Reason: {result.termination_reason}"
        )
        console.print(f"\n[dim]Run [bold]helix results {prompt_id}[/bold] to view details, "
                       f"or [bold]helix accept {prompt_id}[/bold] to apply the evolved template.[/dim]")


async def _run_evolution(config, prompt_record, cases, evo_config, run_kwargs, json_mode):
    """Async wrapper that runs evolution with progress display."""
    from api.evolution.runner import run_evolution

    cancelled = False

    def handle_sigint(*_):
        nonlocal cancelled
        cancelled = True

    prev_handler = signal.signal(signal.SIGINT, handle_sigint)

    progress = EvolutionProgress(
        prompt_id=prompt_record.id,
        total_generations=evo_config.generations,
        budget_cap=evo_config.budget_cap_usd,
    )

    live = None if json_mode else progress.create_live()

    async def event_callback(event_type: str, data: dict) -> None:
        if cancelled:
            return
        if event_type == "seed_evaluated":
            score = data.get("fitness_score", 0)
            progress.set_seed_fitness(score)
        elif event_type == "generation_complete":
            gen = data.get("generation", 0)
            progress.update_generation(gen)
            progress.update_fitness(
                best=data.get("best_fitness", 0),
                avg=data.get("avg_fitness", 0),
                candidates=data.get("candidates_evaluated", 0),
                cost=data.get("total_cost_usd", 0),
            )
            if live:
                progress.refresh(live)

    try:
        if live:
            live.start()
        result = await run_evolution(
            config=config,
            prompt_record=prompt_record,
            cases=cases,
            evolution_config=evo_config,
            event_callback=event_callback,
            **run_kwargs,
        )
        progress.finish(result.termination_reason)
        if live:
            progress.refresh(live)
        return result
    except Exception as e:
        if live:
            live.stop()
        if cancelled:
            return None
        raise e
    finally:
        if live:
            live.stop()
        signal.signal(signal.SIGINT, prev_handler)
