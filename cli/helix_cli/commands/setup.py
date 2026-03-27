"""helix setup — interactive first-run configuration."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

console = Console()

PROVIDERS = {
    "gemini": {
        "label": "Gemini (Google)",
        "env_key": "GENE_GEMINI_API_KEY",
        "default_model": "gemini-2.5-flash",
    },
    "openai": {
        "label": "OpenAI",
        "env_key": "GENE_OPENAI_API_KEY",
        "default_model": "gpt-4o-mini",
    },
    "openrouter": {
        "label": "OpenRouter (multi-provider)",
        "env_key": "GENE_OPENROUTER_API_KEY",
        "default_model": "openai/gpt-4o-mini",
    },
}


def setup_command(
    directory: Path = typer.Option(Path("."), "--dir", "-d", help="Directory to save .env"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    """Interactive setup for API key and default provider."""
    if json_output:
        typer.echo(json.dumps({"providers": list(PROVIDERS.keys())}))
        return

    console.print(Panel(
        "[bold]Helix Setup[/bold]\n\n"
        "Configure your LLM provider and API key.\n"
        "This saves to a .env file in your working directory.",
        border_style="cyan",
    ))

    # Provider selection
    console.print("\n[bold]Available providers:[/bold]")
    for i, (key, info) in enumerate(PROVIDERS.items(), 1):
        console.print(f"  {i}. {info['label']} [dim]({key})[/dim]")

    choice = Prompt.ask(
        "\nSelect provider",
        choices=["1", "2", "3", "gemini", "openai", "openrouter"],
        default="1",
    )

    # Map numeric choice to provider key
    provider_map = {"1": "gemini", "2": "openai", "3": "openrouter"}
    provider = provider_map.get(choice, choice)
    provider_info = PROVIDERS[provider]

    # API key
    api_key = Prompt.ask(f"\n{provider_info['label']} API key")
    if not api_key.strip():
        console.print("[red]API key cannot be empty.[/red]")
        raise typer.Exit(1)

    # Model
    default_model = provider_info["default_model"]
    model = Prompt.ask("Default model", default=default_model)

    # Write .env
    env_path = directory.resolve() / ".env"
    env_lines: list[str] = []
    if env_path.exists():
        env_lines = env_path.read_text(encoding="utf-8").splitlines()

    # Update or append the key
    env_key = provider_info["env_key"]
    key_found = False
    for i, line in enumerate(env_lines):
        if line.startswith(f"{env_key}="):
            env_lines[i] = f"{env_key}={api_key.strip()}"
            key_found = True
            break
    if not key_found:
        env_lines.append(f"{env_key}={api_key.strip()}")

    env_path.write_text("\n".join(env_lines) + "\n", encoding="utf-8")

    console.print(Panel(
        f"[green]Setup complete![/green]\n\n"
        f"  Provider: [bold]{provider}[/bold]\n"
        f"  Model:    [bold]{model}[/bold]\n"
        f"  Key:      [bold]{env_key}[/bold] saved to {env_path}\n\n"
        f"[dim]Tip: Run [bold]helix init my-prompt[/bold] to create your first prompt.[/dim]",
        border_style="green",
    ))
