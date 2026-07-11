# Evolution Algorithm

Helix applies ideas from [Mind Evolution](https://arxiv.org/abs/2501.09891) to prompt-template
optimization. It does not reproduce the paper's solution-evolution runtime: the paper evolves
task solutions, while Helix evolves Jinja prompt templates and evaluates them against a configured
test suite. Template validation, structural mutation, tiered regression scoring, and provider
behavior are Helix-specific adaptations.

## Profiles

`evolution_profile` makes the cost and fidelity trade-off explicit.

| Behavior | `cost_controlled` (default) | `paper_reference` | Mind Evolution comparison |
| --- | --- | --- | --- |
| Evolution domain | Prompt templates | Prompt templates | Task solutions; neither Helix profile claims runtime parity |
| RCC rounds | 3 internal revisions | 4 sequential children | Four sequential candidates |
| Evaluation and retention | Evaluate and retain the final validated child only | Evaluate and retain every validated child; each report informs the next round | Each sequential child is evaluated before refinement continues |
| Default generation scale | Roughly `10 generations * 4 islands * 5 conversations = 200` final RCC candidates | Up to `10 * 4 * 5 * 4 = 800` evaluated RCC children | Paper-scale candidate count is opt-in |
| Initialization | Evaluated seed plus up to 3 one-round seed variants distributed across islands | Evaluated seed plus `5 * 4 = 20` sequential, evaluated seed children shared across islands | Uses the larger sequential initialization pattern |
| Parent evidence | Every selected parent template, candidate ID, and evaluation summary | Same | Real multi-parent evidence is supplied rather than recording unused parents |
| Author attempts | 3 (`max_retries`) | 5 (`max_retries`) | Paper-reference uses five |
| Population lifetime | Best 10 per island (`population_cap=10`) | Accumulates (`population_cap=null`) | Paper populations accumulate until reset |
| Reset selection | Direct score-based, feasible-first elites | Meta-model-assisted diverse, feasible-first elites, with deterministic fallback | Paper-reference uses the diverse selection method |

The scale figures describe candidate upper-scale concepts for the default 10-generation,
4-island, 5-conversation settings. They are not LLM-call or cost guarantees. Deduplication,
early perfect fitness, failed validation, sampling, structural mutation, retries, initialization,
and a budget cap can change actual work.

Profile values are defaults, not locked presets. Explicit non-null profile controls override them.
For `population_cap`, an explicit `null` disables the cap. In public requests and serialized
configuration the RCC field is `rcc_rounds`.

Reset pools are feasible-first. Rejected, fully evaluated candidates fill remaining reset slots
only when too few feasible, fully evaluated candidates exist.

## Data flow

1. Evaluate the seed prompt on the complete test suite.
2. Build the profile-specific initial populations.
3. Select zero or more parents with Boltzmann sampling. Zero parents takes the fresh-generation
   path; otherwise every selected parent's template and evaluation evidence is sent to the critic.
4. The critic compares parent strengths and failures. The author writes a validated child, and
   later RCC rounds revise that child instead of restarting from one parent.
5. Optionally apply a structure-only mutation, preserving required Jinja variables and syntax.
6. Deduplicate canonical templates before admission.
7. Fully evaluate eligible children, update each island, migrate candidates cyclically, and reset
   stagnant islands at the configured completed-generation interval.
8. Return the best feasible, fully evaluated candidate. A perfect result requires every case to be
   present and passing, with no critical rejection.

## Full evaluation and scouting

Population fitness, selection, migration, reset, global-best comparison, and perfect-fitness checks
use only evaluations that cover the complete configured case set exactly. A failed critical case
marks a candidate rejected; feasible candidates rank ahead of rejected candidates.

When `sample_size` or `sample_ratio` is enabled, Helix may first score drafts on a shared subset for
that island generation. Those partial reports are ephemeral scouting data. Only the top distinct
scouts, limited by `promotions_per_island`, receive a complete evaluation. A scout cannot enter a
population, migrate, become global best, or satisfy perfect fitness, so partial and full scores are
never treated as comparable.

## Cost controls

`budget_cap_usd` is a scheduling cap. Helix reserves estimated cost before starting a provider call
and stops scheduling when the next reservation would exceed the cap. Already-started concurrent
calls cannot be recalled, so actual exposure can include work that was in flight at the boundary.
Budget-capped runs reject models whose price cannot be estimated.

See [Configuration](CONFIGURATION.md#evolution-profiles) for the public controls and defaults.
