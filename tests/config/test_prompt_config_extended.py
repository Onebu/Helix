"""Tests for extended PromptConfigSchema and GeneConfig per-role fields.

Covers requirements: CFG-01, CFG-02, CFG-04, CFG-05
"""

import json
from pathlib import Path


from api.config.models import GeneConfig
from api.config.loader import load_prompt_config
from api.registry.schemas import PromptConfigSchema


# -- PromptConfigSchema: provider fields (CFG-01, CFG-05) --


class TestPromptConfigSchemaProviders:
    """PromptConfigSchema accepts per-role provider fields."""

    def test_accepts_meta_provider(self):
        schema = PromptConfigSchema(meta_provider="gemini")
        assert schema.meta_provider == "gemini"

    def test_accepts_target_provider(self):
        schema = PromptConfigSchema(target_provider="openai")
        assert schema.target_provider == "openai"

    def test_accepts_judge_provider(self):
        schema = PromptConfigSchema(judge_provider="openrouter")
        assert schema.judge_provider == "openrouter"

    def test_provider_fields_default_to_none(self):
        schema = PromptConfigSchema()
        assert schema.meta_provider is None
        assert schema.target_provider is None
        assert schema.judge_provider is None


# -- PromptConfigSchema: temperature fields (CFG-02) --


class TestPromptConfigSchemaTemperatures:
    """PromptConfigSchema accepts per-role temperature fields."""

    def test_accepts_meta_temperature(self):
        schema = PromptConfigSchema(meta_temperature=0.9)
        assert schema.meta_temperature == 0.9

    def test_accepts_target_temperature(self):
        schema = PromptConfigSchema(target_temperature=0.0)
        assert schema.target_temperature == 0.0

    def test_accepts_judge_temperature(self):
        schema = PromptConfigSchema(judge_temperature=0.3)
        assert schema.judge_temperature == 0.3

    def test_temperature_fields_default_to_none(self):
        schema = PromptConfigSchema()
        assert schema.meta_temperature is None
        assert schema.target_temperature is None
        assert schema.judge_temperature is None


# -- PromptConfigSchema: thinking budget fields (CFG-02) --


class TestPromptConfigSchemaThinkingBudget:
    """PromptConfigSchema accepts per-role thinking budget fields."""

    def test_accepts_meta_thinking_budget(self):
        schema = PromptConfigSchema(meta_thinking_budget=-1)
        assert schema.meta_thinking_budget == -1

    def test_accepts_target_thinking_budget(self):
        schema = PromptConfigSchema(target_thinking_budget=1024)
        assert schema.target_thinking_budget == 1024

    def test_accepts_judge_thinking_budget(self):
        schema = PromptConfigSchema(judge_thinking_budget=0)
        assert schema.judge_thinking_budget == 0

    def test_thinking_budget_fields_default_to_none(self):
        schema = PromptConfigSchema()
        assert schema.meta_thinking_budget is None
        assert schema.target_thinking_budget is None
        assert schema.judge_thinking_budget is None


# -- PromptConfigSchema: serialization --


class TestPromptConfigSerialization:
    """to_json() and from_json() handle new fields correctly."""

    def test_to_json_excludes_none_fields(self):
        """to_json() with exclude_none should omit unset fields for backward compat."""
        schema = PromptConfigSchema(meta_provider="gemini", meta_temperature=0.9)
        json_str = schema.to_json()
        data = json.loads(json_str)
        assert "meta_provider" in data
        assert "meta_temperature" in data
        # None fields should be excluded
        assert "target_provider" not in data
        assert "judge_thinking_budget" not in data
        assert "generation" not in data

    def test_from_json_with_legacy_fields_only(self):
        """from_json() with only legacy fields (target_model, generation) still works."""
        legacy_json = json.dumps(
            {
                "target_model": "gemini-3-flash-preview",
                "generation": {"temperature": 0, "max_tokens": 1024},
            }
        )
        schema = PromptConfigSchema.from_json(legacy_json)
        assert schema.target_model == "gemini-3-flash-preview"
        assert schema.generation is not None
        assert schema.generation.temperature == 0
        assert schema.generation.max_tokens == 1024
        # New fields should be None
        assert schema.meta_provider is None
        assert schema.meta_temperature is None

    def test_roundtrip_with_all_new_fields(self):
        """to_json() -> from_json() preserves all new fields."""
        original = PromptConfigSchema(
            meta_model="gemini-2.5-pro",
            meta_provider="gemini",
            meta_temperature=0.9,
            meta_thinking_budget=-1,
            target_model="gpt-4o-mini",
            target_provider="openai",
            target_temperature=0.0,
            target_thinking_budget=None,
            judge_model="claude-sonnet-4",
            judge_provider="openrouter",
            judge_temperature=0.3,
            judge_thinking_budget=2048,
        )
        json_str = original.to_json()
        restored = PromptConfigSchema.from_json(json_str)
        assert restored.meta_model == "gemini-2.5-pro"
        assert restored.meta_provider == "gemini"
        assert restored.meta_temperature == 0.9
        assert restored.meta_thinking_budget == -1
        assert restored.target_provider == "openai"
        assert restored.target_temperature == 0.0
        assert restored.judge_provider == "openrouter"
        assert restored.judge_temperature == 0.3
        assert restored.judge_thinking_budget == 2048


# -- PromptConfigSchema: independence of fields (CFG-05) --


class TestPromptConfigFieldIndependence:
    """Provider and model are independent optional fields (no cross-field validator)."""

    def test_provider_without_model_is_valid(self):
        """Setting a provider without a model doesn't raise validation error."""
        schema = PromptConfigSchema(meta_provider="gemini")
        assert schema.meta_provider == "gemini"
        assert schema.meta_model is None

    def test_model_without_provider_is_valid(self):
        """Setting a model without a provider doesn't raise validation error."""
        schema = PromptConfigSchema(meta_model="gemini-2.5-pro")
        assert schema.meta_model == "gemini-2.5-pro"
        assert schema.meta_provider is None

    def test_all_fields_independently_settable(self):
        """Each field can be set/unset independently of others."""
        schema = PromptConfigSchema(
            meta_temperature=0.9,
            target_thinking_budget=1024,
            judge_provider="openrouter",
        )
        assert schema.meta_temperature == 0.9
        assert schema.target_thinking_budget == 1024
        assert schema.judge_provider == "openrouter"
        # Everything else None
        assert schema.meta_model is None
        assert schema.meta_provider is None
        assert schema.target_model is None


# -- GeneConfig: per-role temperature fields (CFG-02) --


class TestGeneConfigTemperatureFields:
    """GeneConfig has per-role temperature fields."""

    def test_meta_temperature_defaults_to_none(self):
        config = GeneConfig()
        assert config.meta_temperature is None

    def test_target_temperature_defaults_to_none(self):
        config = GeneConfig()
        assert config.target_temperature is None

    def test_judge_temperature_defaults_to_none(self):
        config = GeneConfig()
        assert config.judge_temperature is None

    def test_meta_temperature_configurable(self):
        config = GeneConfig(meta_temperature=0.9)
        assert config.meta_temperature == 0.9

    def test_target_temperature_configurable(self):
        config = GeneConfig(target_temperature=0.0)
        assert config.target_temperature == 0.0

    def test_judge_temperature_configurable(self):
        config = GeneConfig(judge_temperature=0.3)
        assert config.judge_temperature == 0.3


# -- load_prompt_config: merges new fields (CFG-04) --


class TestLoadPromptConfigExtended:
    """load_prompt_config merges new per-role fields from config.json onto GeneConfig."""

    def _make_base_config(self):
        return GeneConfig(
            meta_provider="openrouter",
            target_provider="openrouter",
            judge_provider="openrouter",
            meta_model="anthropic/claude-sonnet-4",
            target_model="openai/gpt-4o-mini",
            judge_model="anthropic/claude-sonnet-4",
        )

    def test_merges_provider_fields(self, tmp_path: Path):
        """load_prompt_config merges provider overrides from config.json."""
        base = self._make_base_config()
        prompt_dir = tmp_path / "test-prompt"
        prompt_dir.mkdir()
        (prompt_dir / "config.json").write_text(
            json.dumps(
                {
                    "meta_provider": "gemini",
                    "target_provider": "openai",
                }
            )
        )

        merged = load_prompt_config(base, prompt_dir)
        assert merged.meta_provider == "gemini"
        assert merged.target_provider == "openai"
        assert merged.judge_provider == "openrouter"  # unchanged

    def test_merges_temperature_fields(self, tmp_path: Path):
        """load_prompt_config merges per-role temperature overrides."""
        base = self._make_base_config()
        prompt_dir = tmp_path / "test-prompt"
        prompt_dir.mkdir()
        (prompt_dir / "config.json").write_text(
            json.dumps(
                {
                    "meta_temperature": 0.9,
                    "target_temperature": 0.0,
                }
            )
        )

        merged = load_prompt_config(base, prompt_dir)
        assert merged.meta_temperature == 0.9
        assert merged.target_temperature == 0.0
        assert merged.judge_temperature is None  # unchanged

    def test_merges_thinking_budget_fields(self, tmp_path: Path):
        """load_prompt_config merges thinking budget overrides."""
        base = self._make_base_config()
        prompt_dir = tmp_path / "test-prompt"
        prompt_dir.mkdir()
        (prompt_dir / "config.json").write_text(
            json.dumps(
                {
                    "meta_thinking_budget": -1,
                    "judge_thinking_budget": 2048,
                }
            )
        )

        merged = load_prompt_config(base, prompt_dir)
        assert merged.meta_thinking_budget == -1
        assert merged.judge_thinking_budget == 2048
        assert merged.target_thinking_budget is None  # unchanged

    def test_missing_config_json_returns_base_unchanged(self, tmp_path: Path):
        """If config.json doesn't exist, return base config unchanged."""
        base = self._make_base_config()
        prompt_dir = tmp_path / "no-config"
        prompt_dir.mkdir()

        result = load_prompt_config(base, prompt_dir)
        assert result.meta_provider == "openrouter"
        assert result.meta_temperature is None
        assert result.meta_thinking_budget is None

    def test_merges_all_new_fields_together(self, tmp_path: Path):
        """All new fields (providers, temperatures, thinking budgets) merge in one config.json."""
        base = self._make_base_config()
        prompt_dir = tmp_path / "test-prompt"
        prompt_dir.mkdir()
        (prompt_dir / "config.json").write_text(
            json.dumps(
                {
                    "meta_provider": "gemini",
                    "meta_model": "gemini-2.5-pro",
                    "meta_temperature": 0.9,
                    "meta_thinking_budget": -1,
                    "target_provider": "openai",
                    "target_model": "gpt-4o-mini",
                    "target_temperature": 0.0,
                    "judge_temperature": 0.3,
                }
            )
        )

        merged = load_prompt_config(base, prompt_dir)
        assert merged.meta_provider == "gemini"
        assert merged.meta_model == "gemini-2.5-pro"
        assert merged.meta_temperature == 0.9
        assert merged.meta_thinking_budget == -1
        assert merged.target_provider == "openai"
        assert merged.target_model == "gpt-4o-mini"
        assert merged.target_temperature == 0.0
        assert merged.judge_temperature == 0.3
        # Unchanged
        assert merged.judge_provider == "openrouter"
        assert merged.judge_model == "anthropic/claude-sonnet-4"
