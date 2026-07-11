"""Per-prompt configuration override merging."""

from api.config.models import GeneConfig, GenerationConfig


def load_prompt_config(
    base_config: GeneConfig,
    overrides_dict: dict | None = None,
) -> GeneConfig:
    """Merge explicit per-prompt config overrides onto a base config.

    Returns new GeneConfig with per-prompt overrides applied.
    If no overrides found, returns the base config unchanged.
    """
    if not overrides_dict:
        return base_config

    # Handle nested generation config
    update_dict = {}
    for key, value in overrides_dict.items():
        if key == "generation" and isinstance(value, dict):
            # Merge generation overrides onto existing generation config
            current_gen = base_config.generation.model_dump()
            current_gen.update(value)
            update_dict["generation"] = GenerationConfig(**current_gen)
        else:
            update_dict[key] = value

    return base_config.model_copy(update=update_dict)
