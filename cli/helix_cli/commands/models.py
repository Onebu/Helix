"""helix models — list available models for a provider."""

from __future__ import annotations

import asyncio
import json

import typer
from rich.console import Console
from rich.table import Table

console = Console()

PROVIDERS = ["gemini", "openai", "openrouter"]


def models_command(
    provider: str = typer.Argument(
        None,
        help="Provider name (gemini, openai, openrouter). Omit to list all providers.",
    ),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    """List available models for a provider."""
    if not provider:
        if json_output:
            typer.echo(json.dumps({"providers": PROVIDERS}))
        else:
            console.print("[bold]Available providers:[/bold]")
            for p in PROVIDERS:
                console.print(f"  {p}")
            console.print("\n[dim]Run [bold]helix models <provider>[/bold] to list models.[/dim]")
        return

    if provider not in PROVIDERS:
        console.print(f"[red]Unknown provider '{provider}'. Choose from: {', '.join(PROVIDERS)}[/red]")
        raise typer.Exit(1)

    from dotenv import load_dotenv

    load_dotenv()

    try:
        model_list = asyncio.run(_fetch_models(provider))
    except Exception as e:
        console.print(f"[red]Failed to fetch models: {e}[/red]")
        console.print("[dim]Make sure your API key is set. Run [bold]helix setup[/bold] first.[/dim]")
        raise typer.Exit(1) from None

    if json_output:
        typer.echo(json.dumps([
            {"id": m.id, "name": getattr(m, "name", m.id)}
            for m in model_list
        ], indent=2))
        return

    if not model_list:
        console.print(f"[yellow]No models found for {provider}.[/yellow]")
        return

    table = Table(title=f"Models ({provider})")
    table.add_column("ID", style="bold")
    for m in model_list:
        table.add_row(m.id)

    console.print(table)


async def _fetch_models(provider: str):
    """Fetch model list from the provider API."""
    from api.config.models import GeneConfig
    from api.gateway.registry import get_provider_config

    config = GeneConfig()
    provider_config = get_provider_config(provider)
    api_key = getattr(config, provider_config.api_key_field, None)

    if not api_key:
        raise ValueError(
            f"No API key for {provider}. "
            f"Set {provider_config.api_key_field.upper()} in .env or run 'helix setup'."
        )

    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        base_url=provider_config.base_url,
        api_key=api_key,
    )
    try:
        response = await client.models.list()
        return sorted(response.data, key=lambda m: m.id)
    finally:
        await client.close()
