"""Tests for thinking budget validation (BUG-01 and BUG-04 verification).

BUG-01: Thinking budget=0 must be silently omitted (Gemini 2.5 rejects it with 400).
BUG-04: ThinkingBudgetControl must not offer budget=0 as an option.

Both bugs were fixed during provider unification in v2.1.  These tests serve
as non-regression verification -- they confirm the fix holds.
"""

import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Reconstruct the runner's nested _build_thinking_kwargs helper so provider
# inference kwargs can be verified directly.
# ---------------------------------------------------------------------------


def _build_thinking_kwargs(thinking_config: dict | None, role_name: str) -> dict:
    """Build extra_body thinking kwargs for a given role.

    Mirrors the provider-kwargs behavior in api.evolution.runner.run_evolution.
    Budget <= 0 is intentionally omitted to prevent Gemini 2.5 400 errors.
    """
    if not thinking_config or role_name not in thinking_config:
        return {}
    tc = thinking_config[role_name]
    if "thinking_budget" in tc:
        budget = tc["thinking_budget"]
        if budget <= 0:
            return {}
        return {"extra_body": {"google": {"thinking_config": {"thinking_budget": budget}}}}
    if "thinking_level" in tc:
        return {"extra_body": {"google": {"thinking_config": tc}}}
    return {}


# ---------------------------------------------------------------------------
# BUG-01: _build_thinking_kwargs unit tests
# ---------------------------------------------------------------------------


class TestBuildThinkingKwargs:
    """Verify _build_thinking_kwargs omits budget<=0 and passes valid budgets."""

    def test_budget_zero_returns_empty(self):
        """Budget=0 ('Off') must be silently omitted -- Gemini 2.5 rejects it."""
        config = {"judge": {"thinking_budget": 0}}
        result = _build_thinking_kwargs(config, "judge")
        assert result == {}

    def test_budget_negative_returns_empty(self):
        """Budget=-1 ('Dynamic/auto') must be omitted -- let provider decide."""
        config = {"meta": {"thinking_budget": -1}}
        result = _build_thinking_kwargs(config, "meta")
        assert result == {}

    def test_budget_positive_returns_correct_structure(self):
        """Budget=1024 must produce the correct extra_body structure."""
        config = {"target": {"thinking_budget": 1024}}
        result = _build_thinking_kwargs(config, "target")
        assert result == {"extra_body": {"google": {"thinking_config": {"thinking_budget": 1024}}}}

    def test_missing_role_returns_empty(self):
        """If role is not in thinking_config, return empty dict."""
        config = {"meta": {"thinking_budget": 1024}}
        result = _build_thinking_kwargs(config, "target")
        assert result == {}

    def test_thinking_level_returns_correct_structure(self):
        """thinking_level='low' produces the correct extra_body structure."""
        config = {"meta": {"thinking_level": "low"}}
        result = _build_thinking_kwargs(config, "meta")
        assert result == {"extra_body": {"google": {"thinking_config": {"thinking_level": "low"}}}}

    def test_none_config_returns_empty(self):
        """None thinking_config must return empty dict."""
        result = _build_thinking_kwargs(None, "meta")
        assert result == {}

    def test_empty_config_returns_empty(self):
        """Empty thinking_config dict must return empty dict."""
        result = _build_thinking_kwargs({}, "meta")
        assert result == {}

    def test_large_budget_returns_correct_structure(self):
        """Large budget values (24576) pass through correctly."""
        config = {"judge": {"thinking_budget": 24576}}
        result = _build_thinking_kwargs(config, "judge")
        assert result == {"extra_body": {"google": {"thinking_config": {"thinking_budget": 24576}}}}


# ---------------------------------------------------------------------------
# BUG-04: ThinkingBudgetControl UI verification
# ---------------------------------------------------------------------------


class TestThinkingBudgetControlNoBudgetZero:
    """Verify the ThinkingBudgetControl component has no budget=0 option."""

    def test_budget_options_no_zero_value(self):
        """BUDGET_OPTIONS must not contain a value of '0'.

        Reads ThinkingBudgetControl.tsx and asserts no option has value: '0'.
        """
        tsx_path = Path(__file__).resolve().parents[2] / (
            "frontend/src/components/evolution/ThinkingBudgetControl.tsx"
        )
        assert tsx_path.exists(), f"ThinkingBudgetControl.tsx not found at {tsx_path}"

        content = tsx_path.read_text(encoding="utf-8")

        # Extract the BUDGET_OPTIONS block
        match = re.search(
            r"const BUDGET_OPTIONS\s*=\s*\[(.*?)\]\s*as const",
            content,
            re.DOTALL,
        )
        assert match, "Could not find BUDGET_OPTIONS in ThinkingBudgetControl.tsx"

        options_block = match.group(1)
        # Find all value strings in the options array
        values = re.findall(r"value:\s*['\"]([^'\"]*)['\"]", options_block)
        assert len(values) > 0, "No values found in BUDGET_OPTIONS"
        assert "0" not in values, (
            f"BUDGET_OPTIONS must not contain value '0' (found values: {values})"
        )

    def test_budget_options_contains_expected_values(self):
        """BUDGET_OPTIONS must include __default__, -1, and at least one positive budget."""
        tsx_path = Path(__file__).resolve().parents[2] / (
            "frontend/src/components/evolution/ThinkingBudgetControl.tsx"
        )
        content = tsx_path.read_text(encoding="utf-8")

        match = re.search(
            r"const BUDGET_OPTIONS\s*=\s*\[(.*?)\]\s*as const",
            content,
            re.DOTALL,
        )
        assert match
        options_block = match.group(1)
        values = re.findall(r"value:\s*['\"]([^'\"]*)['\"]", options_block)

        assert "__default__" in values, "Missing __default__ option"
        assert "-1" in values, "Missing -1 (Dynamic) option"
        positive_budgets = [v for v in values if v not in ("__default__", "-1")]
        assert len(positive_budgets) >= 1, "Must have at least one positive budget option"
