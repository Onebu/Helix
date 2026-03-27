"""Rich Live progress display for evolution runs."""

from __future__ import annotations

import time

from rich.console import Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TextColumn
from rich.table import Table
from rich.text import Text


class EvolutionProgress:
    """Manages the Rich Live display during an evolution run."""

    def __init__(self, prompt_id: str, total_generations: int, budget_cap: float | None = None):
        self.prompt_id = prompt_id
        self.total_generations = total_generations
        self.budget_cap = budget_cap
        self.current_generation = 0
        self.candidates_evaluated = 0
        self.best_fitness = None
        self.avg_fitness = None
        self.seed_fitness = None
        self.total_cost = 0.0
        self.start_time = time.monotonic()
        self.termination_reason = None

        self._progress = Progress(
            TextColumn("[bold]{task.description}"),
            BarColumn(bar_width=30),
            TextColumn("{task.percentage:>3.0f}%"),
        )
        self._task = self._progress.add_task(
            "Generation", total=total_generations
        )

    def _build_display(self) -> Panel:
        elapsed = time.monotonic() - self.start_time
        mins, secs = divmod(int(elapsed), 60)

        stats = Table.grid(padding=(0, 2))
        stats.add_column(justify="right", style="dim")
        stats.add_column()

        if self.best_fitness is not None:
            fitness_text = f"{self.best_fitness:.4f}"
            if self.seed_fitness is not None:
                delta = self.best_fitness - self.seed_fitness
                fitness_text += f"  (seed: {self.seed_fitness:.4f}, "
                if delta >= 0:
                    fitness_text += f"[green]+{delta:.4f}[/green])"
                else:
                    fitness_text += f"[red]{delta:.4f}[/red])"
            stats.add_row("Best Fitness", fitness_text)

        if self.avg_fitness is not None:
            stats.add_row("Avg Fitness", f"{self.avg_fitness:.4f}")

        stats.add_row("Candidates", str(self.candidates_evaluated))

        cost_text = f"${self.total_cost:.4f}"
        if self.budget_cap:
            cost_text += f" / ${self.budget_cap:.2f}"
        stats.add_row("Cost", cost_text)
        stats.add_row("Elapsed", f"{mins}m {secs:02d}s")

        return Panel(
            Group(self._progress, Text(""), stats),
            title=f"[bold]helix evolve {self.prompt_id}[/bold]",
            border_style="green" if self.termination_reason else "cyan",
        )

    def update_generation(self, generation: int) -> None:
        self.current_generation = generation
        self._progress.update(self._task, completed=generation)

    def update_fitness(
        self,
        best: float,
        avg: float,
        candidates: int,
        cost: float,
    ) -> None:
        self.best_fitness = best
        self.avg_fitness = avg
        self.candidates_evaluated += candidates
        self.total_cost = cost

    def set_seed_fitness(self, score: float) -> None:
        self.seed_fitness = score

    def finish(self, reason: str) -> None:
        self.termination_reason = reason
        self._progress.update(self._task, completed=self.total_generations)

    def create_live(self) -> Live:
        return Live(self._build_display(), refresh_per_second=4)

    def refresh(self, live: Live) -> None:
        live.update(self._build_display())
