"""Tests for evaluation scorers: ExactMatchScorer and BehaviorJudgeScorer.

Penalty-based scoring: 0 = no penalty (pass), negative = violation.
"""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.evaluation.models import CaseResult
from api.types import LLMResponse, ModelRole


# ---------------------------------------------------------------------------
# Helpers -- mock LLMResponse objects
# ---------------------------------------------------------------------------


def _make_response(
    content: str | None = None,
    tool_calls: list[dict] | None = None,
) -> LLMResponse:
    """Create a minimal LLMResponse for testing."""
    return LLMResponse(
        content=content,
        tool_calls=tool_calls,
        model_used="test-model",
        role=ModelRole.TARGET,
        input_tokens=10,
        output_tokens=10,
        cost_usd=0.001,
        timestamp=datetime.now(timezone.utc),
    )


# ===========================================================================
# ExactMatchScorer
# ===========================================================================


class TestExactMatchScorer:
    """Test ExactMatchScorer tool call comparison logic."""

    @pytest.fixture
    def scorer(self):
        from api.evaluation.scorers import ExactMatchScorer

        return ExactMatchScorer()

    @pytest.fixture
    def strict_scorer(self):
        from api.evaluation.scorers import ExactMatchScorer

        return ExactMatchScorer(strict_types=True)

    # -- Full match (score=0, no penalty) --

    @pytest.mark.asyncio
    async def test_full_match_single_tool_call(self, scorer):
        """Full match when tool name and arguments are identical."""
        expected = {
            "tool_calls": [
                {"name": "get_weather", "arguments": {"city": "London", "unit": "celsius"}}
            ]
        }
        actual = _make_response(
            tool_calls=[{"name": "get_weather", "arguments": {"city": "London", "unit": "celsius"}}]
        )
        result = await scorer.score(expected, actual)
        assert result.score == 0
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_full_match_json_string_arguments(self, scorer):
        """Full match when arguments come as JSON strings (normalized)."""
        expected = {
            "tool_calls": [{"name": "search", "arguments": '{"query": "python", "limit": 10}'}]
        }
        actual = _make_response(
            tool_calls=[{"name": "search", "arguments": '{"limit": 10, "query": "python"}'}]
        )
        result = await scorer.score(expected, actual)
        assert result.score == 0
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_full_match_multiple_tool_calls(self, scorer):
        """Full match when multiple tool calls match in order."""
        expected = {
            "tool_calls": [
                {"name": "fn_a", "arguments": {"x": 1}},
                {"name": "fn_b", "arguments": {"y": 2}},
            ]
        }
        actual = _make_response(
            tool_calls=[
                {"name": "fn_a", "arguments": {"x": 1}},
                {"name": "fn_b", "arguments": {"y": 2}},
            ]
        )
        result = await scorer.score(expected, actual)
        assert result.score == 0
        assert result.passed is True

    # -- Type coercion (string "2" vs int 2) --

    @pytest.mark.asyncio
    async def test_type_coercion_string_vs_int(self, scorer):
        """With strict_types=False (default), string '2' equals int 2."""
        expected = {"tool_calls": [{"name": "set_count", "arguments": {"count": 2}}]}
        actual = _make_response(tool_calls=[{"name": "set_count", "arguments": {"count": "2"}}])
        result = await scorer.score(expected, actual)
        assert result.score == 0
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_strict_types_string_vs_int(self, strict_scorer):
        """With strict_types=True, string '2' does NOT equal int 2 -> args differ penalty."""
        expected = {"tool_calls": [{"name": "set_count", "arguments": {"count": 2}}]}
        actual = _make_response(tool_calls=[{"name": "set_count", "arguments": {"count": "2"}}])
        result = await strict_scorer.score(expected, actual)
        assert result.score == -1
        assert result.passed is False

    # -- Args differ (score=-1) -- name match, argument mismatch --

    @pytest.mark.asyncio
    async def test_partial_match_name_match_args_differ(self, scorer):
        """Penalty when tool name matches but arguments differ."""
        expected = {"tool_calls": [{"name": "get_weather", "arguments": {"city": "London"}}]}
        actual = _make_response(
            tool_calls=[{"name": "get_weather", "arguments": {"city": "Paris"}}]
        )
        result = await scorer.score(expected, actual)
        assert result.score == -1
        assert result.passed is False

    # -- Name mismatch (score=-2) --

    @pytest.mark.asyncio
    async def test_name_mismatch(self, scorer):
        """Score -2 when tool names do not match."""
        expected = {"tool_calls": [{"name": "get_weather", "arguments": {"city": "London"}}]}
        actual = _make_response(
            tool_calls=[{"name": "get_stock_price", "arguments": {"symbol": "AAPL"}}]
        )
        result = await scorer.score(expected, actual)
        assert result.score == -2
        assert result.passed is False

    # -- Edge: expected has tool_calls, actual has none (score=-2) --

    @pytest.mark.asyncio
    async def test_expected_tools_actual_none(self, scorer):
        """Score -2 when expected has tool_calls but actual has none."""
        expected = {"tool_calls": [{"name": "get_weather", "arguments": {"city": "London"}}]}
        actual = _make_response(content="The weather is sunny.")
        result = await scorer.score(expected, actual)
        assert result.score == -2
        assert result.passed is False

    # -- Edge: actual has tool_calls, expected has none (score=-2) --

    @pytest.mark.asyncio
    async def test_actual_tools_expected_none(self, scorer):
        """Score -2 when actual has tool_calls but expected has none."""
        expected = {"content": "Just a text response"}
        actual = _make_response(tool_calls=[{"name": "some_fn", "arguments": {}}])
        result = await scorer.score(expected, actual)
        assert result.score == -2
        assert result.passed is False

    # -- Edge: neither has tool_calls (score=0, no penalty) --

    @pytest.mark.asyncio
    async def test_neither_has_tool_calls(self, scorer):
        """Score 0 with 'not applicable' reason when neither side has tool_calls."""
        expected = {"content": "Hello"}
        actual = _make_response(content="Hello there")
        result = await scorer.score(expected, actual)
        assert result.score == 0
        assert result.passed is True
        assert "not applicable" in result.reason.lower()

    # -- CaseResult fields populated correctly --

    @pytest.mark.asyncio
    async def test_case_result_fields_populated(self, scorer):
        """CaseResult includes case_id, expected, actual fields."""
        expected = {"tool_calls": [{"name": "fn", "arguments": {"a": 1}}]}
        actual = _make_response(
            tool_calls=[{"name": "fn", "arguments": {"a": 1}}],
            content="some content",
        )
        result = await scorer.score(expected, actual, context={"case_id": "case-42"})
        assert result.case_id == "case-42"
        assert result.expected == expected
        assert result.actual_tool_calls is not None

    # -- Multiple tool calls: order matters --

    @pytest.mark.asyncio
    async def test_multiple_tool_calls_order_matters(self, scorer):
        """Multiple tool calls compared in order; swapped order is a name mismatch."""
        expected = {
            "tool_calls": [
                {"name": "fn_a", "arguments": {}},
                {"name": "fn_b", "arguments": {}},
            ]
        }
        actual = _make_response(
            tool_calls=[
                {"name": "fn_b", "arguments": {}},
                {"name": "fn_a", "arguments": {}},
            ]
        )
        result = await scorer.score(expected, actual)
        assert result.score == -2
        assert result.passed is False

    # -- Different number of tool calls (score=-2) --

    @pytest.mark.asyncio
    async def test_different_number_of_tool_calls(self, scorer):
        """Score -2 when different number of tool calls."""
        expected = {
            "tool_calls": [
                {"name": "fn_a", "arguments": {}},
                {"name": "fn_b", "arguments": {}},
            ]
        }
        actual = _make_response(tool_calls=[{"name": "fn_a", "arguments": {}}])
        result = await scorer.score(expected, actual)
        assert result.score == -2
        assert result.passed is False


# ===========================================================================
# ExactMatchScorer -- Nested OpenAI Format
# ===========================================================================


class TestExactMatchScorerNestedFormat:
    """Test ExactMatchScorer with nested OpenAI-compatible tool call format."""

    @pytest.fixture
    def scorer(self):
        from api.evaluation.scorers import ExactMatchScorer

        return ExactMatchScorer()

    @pytest.mark.asyncio
    async def test_nested_actual_flat_expected_full_match(self, scorer):
        """Nested actual + flat expected with matching data scores 0 (no penalty)."""
        expected = {"tool_calls": [{"name": "get_weather", "arguments": {"city": "London"}}]}
        actual = _make_response(
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "arguments": '{"city": "London"}',
                    },
                }
            ]
        )
        result = await scorer.score(expected, actual)
        assert result.score == 0
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_nested_expected_flat_actual_full_match(self, scorer):
        """Nested expected + flat actual with matching data scores 0."""
        expected = {
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "arguments": '{"city": "London"}',
                    },
                }
            ]
        }
        actual = _make_response(
            tool_calls=[{"name": "get_weather", "arguments": {"city": "London"}}]
        )
        result = await scorer.score(expected, actual)
        assert result.score == 0
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_both_nested_full_match(self, scorer):
        """Both sides nested format with JSON string arguments scores 0."""
        expected = {
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "search",
                        "arguments": '{"query": "python", "limit": 10}',
                    },
                }
            ]
        }
        actual = _make_response(
            tool_calls=[
                {
                    "id": "call_2",
                    "type": "function",
                    "function": {
                        "name": "search",
                        "arguments": '{"limit": 10, "query": "python"}',
                    },
                }
            ]
        )
        result = await scorer.score(expected, actual)
        assert result.score == 0
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_nested_arguments_as_dict(self, scorer):
        """Nested format with arguments already a dict (not JSON string) scores 0."""
        expected = {"tool_calls": [{"name": "fn", "arguments": {"a": 1}}]}
        actual = _make_response(
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "fn",
                        "arguments": {"a": 1},
                    },
                }
            ]
        )
        result = await scorer.score(expected, actual)
        assert result.score == 0
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_nested_partial_match_args_differ(self, scorer):
        """Nested format, names match but args differ -> score=-1."""
        expected = {"tool_calls": [{"name": "get_weather", "arguments": {"city": "London"}}]}
        actual = _make_response(
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "arguments": '{"city": "Paris"}',
                    },
                }
            ]
        )
        result = await scorer.score(expected, actual)
        assert result.score == -1
        assert result.passed is False

    @pytest.mark.asyncio
    async def test_nested_name_mismatch_shows_correct_names(self, scorer):
        """Nested format, names differ -> -2. Error shows actual function names."""
        expected = {"tool_calls": [{"name": "get_weather", "arguments": {"city": "London"}}]}
        actual = _make_response(
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "get_stock_price",
                        "arguments": '{"symbol": "AAPL"}',
                    },
                }
            ]
        )
        result = await scorer.score(expected, actual)
        assert result.score == -2
        assert result.passed is False
        assert "get_weather" in result.reason
        assert "get_stock_price" in result.reason

    @pytest.mark.asyncio
    async def test_nested_multiple_tool_calls(self, scorer):
        """Multiple nested tool calls all matching scores 0."""
        expected = {
            "tool_calls": [
                {"name": "fn_a", "arguments": {"x": 1}},
                {"name": "fn_b", "arguments": {"y": 2}},
            ]
        }
        actual = _make_response(
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "fn_a", "arguments": '{"x": 1}'},
                },
                {
                    "id": "call_2",
                    "type": "function",
                    "function": {"name": "fn_b", "arguments": '{"y": 2}'},
                },
            ]
        )
        result = await scorer.score(expected, actual)
        assert result.score == 0
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_nested_with_type_coercion(self, scorer):
        """Nested format with type coercion: JSON string '2' matches int 2."""
        expected = {"tool_calls": [{"name": "set_count", "arguments": {"count": 2}}]}
        actual = _make_response(
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "set_count",
                        "arguments": '{"count": "2"}',
                    },
                }
            ]
        )
        result = await scorer.score(expected, actual)
        assert result.score == 0
        assert result.passed is True


# ===========================================================================
# _normalize_tool_call unit tests
# ===========================================================================


class TestNormalizeToolCall:
    """Direct unit tests for the _normalize_tool_call helper function."""

    def setup_method(self):
        from api.registry.tool_resolver import normalize_tool_call

        self.normalize = normalize_tool_call

    def test_flat_format_passthrough(self):
        """Flat format passes through unchanged."""
        result = self.normalize({"name": "fn", "arguments": {"a": 1}})
        assert result == {"name": "fn", "arguments": {"a": 1}}

    def test_nested_format_extracts_function(self):
        """Nested format extracts name and arguments from 'function' key."""
        result = self.normalize(
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "fn", "arguments": {"a": 1}},
            }
        )
        assert result == {"name": "fn", "arguments": {"a": 1}}

    def test_json_string_arguments_parsed(self):
        """JSON string arguments in flat format are parsed to dict."""
        result = self.normalize({"name": "fn", "arguments": '{"a": 1}'})
        assert result == {"name": "fn", "arguments": {"a": 1}}

    def test_nested_json_string_arguments_parsed(self):
        """JSON string arguments in nested format are parsed to dict."""
        result = self.normalize({"function": {"name": "fn", "arguments": '{"a": 1}'}})
        assert result == {"name": "fn", "arguments": {"a": 1}}

    def test_invalid_json_string_returns_empty_dict(self):
        """Invalid JSON string arguments are normalized to empty dict."""
        result = self.normalize({"name": "fn", "arguments": "not-json"})
        assert result == {"name": "fn", "arguments": {}}

    def test_empty_arguments_dict(self):
        """Empty arguments dict passes through."""
        result = self.normalize({"name": "fn", "arguments": {}})
        assert result == {"name": "fn", "arguments": {}}

    def test_missing_arguments_defaults_to_empty_dict(self):
        """Missing arguments key defaults to empty dict."""
        result = self.normalize({"name": "fn"})
        assert result == {"name": "fn", "arguments": {}}


# ===========================================================================
# BehaviorJudgeScorer
# ===========================================================================


def _make_behavior_judge_response(evaluations: list[dict]) -> LLMResponse:
    """Create an LLMResponse as if returned by the behavior judge model."""
    return LLMResponse(
        content=json.dumps({"evaluations": evaluations}),
        tool_calls=None,
        model_used="judge-model",
        role=ModelRole.JUDGE,
        input_tokens=100,
        output_tokens=50,
        cost_usd=0.002,
        timestamp=datetime.now(timezone.utc),
    )


class TestBehaviorJudgeScorer:
    """Test BehaviorJudgeScorer per-criterion binary evaluation via LLM judge."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock LLMProvider."""
        client = MagicMock()
        client.chat_completion = AsyncMock()
        return client

    @pytest.fixture
    def scorer(self, mock_client):
        from api.evaluation.scorers import BehaviorJudgeScorer

        return BehaviorJudgeScorer(client=mock_client, judge_model="test/judge-model")

    # -- All criteria pass (score=0) --

    @pytest.mark.asyncio
    async def test_all_criteria_pass(self, scorer, mock_client):
        """3 criteria all pass -> score=0, passed=True, 3 criteria_results all passed."""
        mock_client.chat_completion.return_value = _make_behavior_judge_response(
            [
                {"criterion": "greets warmly", "passed": True, "reason": "Warm greeting found"},
                {
                    "criterion": "confirms department",
                    "passed": True,
                    "reason": "Department confirmed",
                },
                {"criterion": "transfers correctly", "passed": True, "reason": "Correct transfer"},
            ]
        )
        expected = {"behavior": ["greets warmly", "confirms department", "transfers correctly"]}
        actual = _make_response(content="Hello! Let me transfer you to sales.")

        result = await scorer.score(expected, actual, context={"case_id": "c1"})
        assert result.score == 0
        assert result.passed is True
        assert result.criteria_results is not None
        assert len(result.criteria_results) == 3
        assert all(cr["passed"] for cr in result.criteria_results)

    # -- Partial criteria pass --

    @pytest.mark.asyncio
    async def test_partial_criteria_pass(self, scorer, mock_client):
        """3 criteria, 2 pass, 1 fails -> score=-2, passed=False."""
        mock_client.chat_completion.return_value = _make_behavior_judge_response(
            [
                {"criterion": "greets warmly", "passed": True, "reason": "Warm greeting found"},
                {
                    "criterion": "confirms department",
                    "passed": True,
                    "reason": "Department confirmed",
                },
                {"criterion": "transfers correctly", "passed": False, "reason": "Wrong department"},
            ]
        )
        expected = {"behavior": ["greets warmly", "confirms department", "transfers correctly"]}
        actual = _make_response(content="Hello! Transferring now.")

        result = await scorer.score(expected, actual, context={"case_id": "c2"})
        assert result.score == -2  # 1 failed criterion * -2
        assert result.passed is False
        assert result.criteria_results[2]["passed"] is False

    # -- Empty criteria --

    @pytest.mark.asyncio
    async def test_empty_criteria(self, scorer, mock_client):
        """Empty criteria list -> score=0, passed=True (vacuous truth)."""
        expected = {"behavior": []}
        actual = _make_response(content="Some response")

        result = await scorer.score(expected, actual)
        assert result.score == 0
        assert result.passed is True
        mock_client.chat_completion.assert_not_called()

    # -- Client call arguments --

    @pytest.mark.asyncio
    async def test_calls_client_with_judge_role_and_schema(self, scorer, mock_client):
        """BehaviorJudgeScorer calls client with ModelRole.JUDGE, temperature=0, correct schema."""
        mock_client.chat_completion.return_value = _make_behavior_judge_response(
            [
                {"criterion": "is polite", "passed": True, "reason": "Polite tone"},
            ]
        )
        expected = {"behavior": ["is polite"]}
        actual = _make_response(content="Hello!")

        await scorer.score(expected, actual)

        call_kwargs = mock_client.chat_completion.call_args
        assert call_kwargs.kwargs["model"] == "test/judge-model"
        assert call_kwargs.kwargs["role"] == ModelRole.JUDGE
        assert call_kwargs.kwargs["temperature"] == 0
        response_format = call_kwargs.kwargs.get("response_format")
        assert response_format is not None
        assert response_format["type"] == "json_schema"
        schema = response_format["json_schema"]["schema"]
        assert "evaluations" in schema["properties"]

    # -- Error handling: invalid JSON (score=-2) --

    @pytest.mark.asyncio
    async def test_invalid_json_response(self, scorer, mock_client):
        """Returns score=-2, passed=False when judge returns invalid JSON."""
        bad_response = LLMResponse(
            content="This is not JSON at all",
            tool_calls=None,
            model_used="judge-model",
            role=ModelRole.JUDGE,
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.002,
            timestamp=datetime.now(timezone.utc),
        )
        mock_client.chat_completion.return_value = bad_response
        expected = {"behavior": ["be polite"]}
        actual = _make_response(content="Hello")

        result = await scorer.score(expected, actual)
        assert result.score == -2
        assert result.passed is False
        assert "parsing failed" in result.reason.lower()

    # -- Error handling: null content (score=-2) --

    @pytest.mark.asyncio
    async def test_null_content_response(self, scorer, mock_client):
        """Returns score=-2, passed=False when judge returns null content."""
        null_response = LLMResponse(
            content=None,
            tool_calls=None,
            model_used="judge-model",
            role=ModelRole.JUDGE,
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.002,
            timestamp=datetime.now(timezone.utc),
        )
        mock_client.chat_completion.return_value = null_response
        expected = {"behavior": ["be polite"]}
        actual = _make_response(content="Hello")

        result = await scorer.score(expected, actual)
        assert result.score == -2
        assert result.passed is False

    # -- Conversation context and purpose --

    @pytest.mark.asyncio
    async def test_includes_conversation_and_purpose(self, scorer, mock_client):
        """BehaviorJudgeScorer includes conversation context and purpose in judge prompt."""
        mock_client.chat_completion.return_value = _make_behavior_judge_response(
            [
                {"criterion": "is helpful", "passed": True, "reason": "Helpful"},
            ]
        )
        expected = {"behavior": ["is helpful"]}
        actual = _make_response(content="Here is help")

        conversation = [
            {"role": "system", "content": "You are an assistant"},
            {"role": "user", "content": "Help me"},
        ]
        await scorer.score(
            expected,
            actual,
            context={"case_id": "c1", "purpose": "Customer support", "conversation": conversation},
        )

        call_kwargs = mock_client.chat_completion.call_args
        messages = call_kwargs.kwargs["messages"]
        messages_text = json.dumps(messages)
        assert "Customer support" in messages_text
        assert "Help me" in messages_text

    # -- Criteria count mismatch --

    @pytest.mark.asyncio
    async def test_criteria_count_mismatch_matches_by_text(self, scorer, mock_client):
        """When judge returns different count, matches by criterion text."""
        mock_client.chat_completion.return_value = _make_behavior_judge_response(
            [
                {"criterion": "greets warmly", "passed": True, "reason": "Warm greeting"},
            ]
        )
        expected = {"behavior": ["greets warmly", "transfers correctly"]}
        actual = _make_response(content="Hello!")

        result = await scorer.score(expected, actual, context={"case_id": "c1"})
        assert result.criteria_results is not None
        assert len(result.criteria_results) == 2
        assert result.criteria_results[0]["passed"] is True
        assert result.criteria_results[1]["passed"] is False
        assert "did not evaluate" in result.criteria_results[1]["reason"].lower()

    # -- CaseResult model compatibility --

    @pytest.mark.asyncio
    async def test_case_result_with_criteria_results(self, scorer, mock_client):
        """CaseResult.criteria_results is populated with list of dicts."""
        mock_client.chat_completion.return_value = _make_behavior_judge_response(
            [
                {"criterion": "is polite", "passed": True, "reason": "Polite tone"},
            ]
        )
        expected = {"behavior": ["is polite"]}
        actual = _make_response(content="Hello!")

        result = await scorer.score(expected, actual, context={"case_id": "cr-test"})
        assert result.criteria_results is not None
        assert result.criteria_results[0]["criterion"] == "is polite"
        assert result.criteria_results[0]["passed"] is True
        assert result.criteria_results[0]["reason"] == "Polite tone"

    @pytest.mark.asyncio
    async def test_case_result_without_criteria_results_backward_compat(self):
        """CaseResult works without criteria_results (defaults to None)."""
        result = CaseResult(case_id="bc-test", score=-1, passed=False, reason="test")
        assert result.criteria_results is None


# ===========================================================================
# ENG-02: require_content scorer flag
# ===========================================================================


class TestRequireContent:
    """Test require_content flag on ExactMatchScorer.

    When require_content=true in expected output, the response MUST include
    spoken text alongside tool calls. Responses with only tool calls
    (silent transfers) should score -2.
    """

    @pytest.fixture
    def scorer(self):
        from api.evaluation.scorers import ExactMatchScorer

        return ExactMatchScorer()

    @pytest.mark.asyncio
    async def test_require_content_with_content_and_tools_passes(self, scorer):
        """require_content=true + response has content + tool calls -> score=0."""
        expected = {
            "tool_calls": [{"name": "transfer_call", "arguments": {"department": "sales"}}],
            "require_content": True,
        }
        actual = _make_response(
            content="Let me transfer you to sales.",
            tool_calls=[{"name": "transfer_call", "arguments": {"department": "sales"}}],
        )
        result = await scorer.score(expected, actual)
        assert result.score == 0
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_require_content_no_content_fails_silent(self, scorer):
        """require_content=true + NO content + tool calls -> score=-2."""
        expected = {
            "tool_calls": [{"name": "transfer_call", "arguments": {"department": "sales"}}],
            "require_content": True,
        }
        actual = _make_response(
            content=None,
            tool_calls=[{"name": "transfer_call", "arguments": {"department": "sales"}}],
        )
        result = await scorer.score(expected, actual)
        assert result.score == -2
        assert result.passed is False
        assert "Silent" in result.reason or "silent" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_require_content_whitespace_only_fails(self, scorer):
        """require_content=true + whitespace-only content -> score=-2."""
        expected = {
            "tool_calls": [{"name": "transfer_call", "arguments": {"department": "billing"}}],
            "require_content": True,
        }
        actual = _make_response(
            content="   \n\t  ",
            tool_calls=[{"name": "transfer_call", "arguments": {"department": "billing"}}],
        )
        result = await scorer.score(expected, actual)
        assert result.score == -2
        assert result.passed is False

    @pytest.mark.asyncio
    async def test_no_require_content_flag_allows_silent(self, scorer):
        """require_content not set + no content + tool calls -> scored normally (score=0)."""
        expected = {
            "tool_calls": [{"name": "transfer_call", "arguments": {"department": "support"}}],
        }
        actual = _make_response(
            content=None,
            tool_calls=[{"name": "transfer_call", "arguments": {"department": "support"}}],
        )
        result = await scorer.score(expected, actual)
        assert result.score == 0
        assert result.passed is True


# ===========================================================================
# ENG-03: match_args subset mode
# ===========================================================================


class TestMatchArgsSubset:
    """Test match_args='subset' flag on ExactMatchScorer."""

    @pytest.fixture
    def scorer(self):
        from api.evaluation.scorers import ExactMatchScorer

        return ExactMatchScorer()

    @pytest.mark.asyncio
    async def test_subset_mode_extra_keys_passes(self, scorer):
        """match_args='subset' + expected keys present (extra in actual) -> score=0."""
        expected = {
            "tool_calls": [{"name": "transfer_call", "arguments": {"department": "sales"}}],
            "match_args": "subset",
        }
        actual = _make_response(
            tool_calls=[
                {
                    "name": "transfer_call",
                    "arguments": {
                        "department": "sales",
                        "summary": "Customer wants to buy a car",
                    },
                }
            ],
        )
        result = await scorer.score(expected, actual)
        assert result.score == 0
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_subset_mode_missing_key_fails(self, scorer):
        """match_args='subset' + expected key MISSING from actual -> score=-1."""
        expected = {
            "tool_calls": [{"name": "transfer_call", "arguments": {"department": "sales"}}],
            "match_args": "subset",
        }
        actual = _make_response(
            tool_calls=[
                {
                    "name": "transfer_call",
                    "arguments": {"summary": "Customer wants to buy a car"},
                }
            ],
        )
        result = await scorer.score(expected, actual)
        assert result.score == -1
        assert result.passed is False

    @pytest.mark.asyncio
    async def test_exact_mode_extra_keys_fails(self, scorer):
        """match_args default (exact) + extra keys in actual -> score=-1."""
        expected = {
            "tool_calls": [{"name": "transfer_call", "arguments": {"department": "sales"}}],
        }
        actual = _make_response(
            tool_calls=[
                {
                    "name": "transfer_call",
                    "arguments": {
                        "department": "sales",
                        "summary": "Extra key not in expected",
                    },
                }
            ],
        )
        result = await scorer.score(expected, actual)
        assert result.score == -1
        assert result.passed is False

    @pytest.mark.asyncio
    async def test_subset_mode_json_string_args(self, scorer):
        """match_args='subset' + JSON string args -> parsed and subset-matched."""
        expected = {
            "tool_calls": [{"name": "transfer_call", "arguments": {"department": "sales"}}],
            "match_args": "subset",
        }
        actual = _make_response(
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "transfer_call",
                        "arguments": '{"department": "sales", "summary": "extra"}',
                    },
                }
            ],
        )
        result = await scorer.score(expected, actual)
        assert result.score == 0
        assert result.passed is True


# ===========================================================================
# _args_subset_match unit tests
# ===========================================================================


class TestArgsSubsetMatch:
    """Direct unit tests for the _args_subset_match helper function."""

    def setup_method(self):
        from api.evaluation.scorers import _args_subset_match

        self.match = _args_subset_match

    def test_exact_match_returns_true(self):
        """Exact match (same keys and values) returns True."""
        assert (
            self.match(
                {"department": "sales"},
                {"department": "sales"},
            )
            is True
        )

    def test_subset_match_extra_keys_returns_true(self):
        """Subset match (extra keys in actual) returns True."""
        assert (
            self.match(
                {"department": "sales"},
                {"department": "sales", "summary": "extra"},
            )
            is True
        )

    def test_missing_key_returns_false(self):
        """Missing expected key in actual returns False."""
        assert (
            self.match(
                {"department": "sales"},
                {"summary": "no department key"},
            )
            is False
        )

    def test_nested_dict_subset_matching(self):
        """Nested dict subset matching works correctly."""
        assert (
            self.match(
                {"config": {"mode": "auto"}},
                {"config": {"mode": "auto"}, "extra": "ignored"},
            )
            is True
        )


# ===========================================================================
# BehaviorJudgeScorer -- Language Context (LANG-05)
# ===========================================================================


class TestBehaviorJudgeScorerLanguageContext:
    """Test that _build_judge_prompt includes language context for non-English conversations."""

    def test_spanish_includes_language_context(self) -> None:
        """_build_judge_prompt with language='es' includes 'conversation is in Spanish'."""
        from api.evaluation.scorers import BehaviorJudgeScorer

        messages = BehaviorJudgeScorer._build_judge_prompt(
            criteria=["responds appropriately"],
            conversation=[],
            actual_content="Hola, como puedo ayudarle?",
            actual_tool_calls=None,
            purpose="Customer support in Spanish",
            language="es",
        )
        system_msg = messages[0]["content"]
        assert "conversation is in Spanish" in system_msg

    def test_english_no_language_context(self) -> None:
        """_build_judge_prompt with language='en' does NOT include language context section."""
        from api.evaluation.scorers import BehaviorJudgeScorer

        messages = BehaviorJudgeScorer._build_judge_prompt(
            criteria=["responds appropriately"],
            conversation=[],
            actual_content="Hello, how can I help?",
            actual_tool_calls=None,
            purpose="Customer support",
            language="en",
        )
        system_msg = messages[0]["content"]
        assert "conversation is in" not in system_msg

    def test_none_language_no_language_context(self) -> None:
        """_build_judge_prompt with no language parameter does NOT include language context."""
        from api.evaluation.scorers import BehaviorJudgeScorer

        messages = BehaviorJudgeScorer._build_judge_prompt(
            criteria=["responds appropriately"],
            conversation=[],
            actual_content="Hello!",
            actual_tool_calls=None,
            purpose="Test",
        )
        system_msg = messages[0]["content"]
        assert "conversation is in" not in system_msg

    def test_chinese_includes_do_not_penalize(self) -> None:
        """_build_judge_prompt with language='zh' includes 'Do not penalize' phrasing."""
        from api.evaluation.scorers import BehaviorJudgeScorer

        messages = BehaviorJudgeScorer._build_judge_prompt(
            criteria=["responds appropriately"],
            conversation=[],
            actual_content="response in Chinese",
            actual_tool_calls=None,
            purpose="Test",
            language="zh",
        )
        system_msg = messages[0]["content"]
        assert "Do not penalize" in system_msg
        assert "Chinese" in system_msg
