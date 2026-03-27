"""Helix CLI entry point."""

from __future__ import annotations

import typer

from helix_cli.commands import accept, evolve, init, list as list_cmd, models, results, setup, show

app = typer.Typer(
    name="helix",
    help="Evolutionary prompt optimization CLI.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

app.command(name="setup", help="Configure API key and provider.")(setup.setup_command)
app.command(name="models", help="List available models.")(models.models_command)
app.command(name="init", help="Scaffold a new prompt directory.")(init.init_command)
app.command(name="list", help="List prompts in the workspace.")(list_cmd.list_command)
app.command(name="show", help="Show prompt details.")(show.show_command)
app.command(name="evolve", help="Run prompt evolution.")(evolve.evolve_command)
app.command(name="results", help="Show evolution results.")(results.results_command)
app.command(name="accept", help="Accept an evolved template.")(accept.accept_command)

if __name__ == "__main__":
    app()
