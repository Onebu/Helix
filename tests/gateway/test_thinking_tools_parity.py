"""Parity tests for thinking budget, structured output, and tool calls across providers.

Verifies that LiteLLMProvider correctly forwards extra_body (thinking config),
response_format (structured output), and tools (function calling) kwargs to the
underlying OpenAI SDK for all registered providers (gemini, openrouter, openai).

Also tests _normalize_tool_call from scorers.py for consistent format handling.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.evaluation.scorers import _BEHAVIOR_JUDGE_SCHEMA
from api.registry.tool_resolver import normalize_tool_call as _normalize_tool_call
from api.gateway.litellm_provider import LiteLLMProvider
from api.types import ModelRole


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

PROVIDERS = ["gemini", "openrouter", "openai"]

SAMPLE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "parameters": {
                "type": "object",
                "properties": {"location": {"type": "string"}},
                "required": ["location"],
            },
        },
    }
]

SAMPLE_JSON_CONTENT = json.dumps(
    {
        "evaluations": [
            {
                "criterion": "Greets the user",
                "passed": True,
                "reason": "Response starts with a greeting",
            }
        ]
    }
)


def _mock_completion(
    content="Hello!",
    model="test-model",
    prompt_tokens=10,
    completion_tokens=5,
    response_id="gen-test",
    tool_calls=None,
    finish_reason="stop",
):
    """Create a mock OpenAI ChatCompletion response."""
    message = MagicMock()
    message.content = content
    message.tool_calls = tool_calls

    choice = MagicMock()
    choice.message = message
    choice.finish_reason = finish_reason

    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens

    response = MagicMock()
    response.choices = [choice]
    response.usage = usage
    response.model = model
    response.id = response_id

    return response


def _make_provider(provider_name: str) -> LiteLLMProvider:
    """Create a LiteLLMProvider with a mocked SDK client."""
    p = LiteLLMProvider(provider=provider_name, api_key="test-key")
    p._client.chat.completions.create = AsyncMock(return_value=_mock_completion())
    return p


# ===========================================================================
# TestThinkingBudgetParity (COMPAT-03)
# ===========================================================================


class TestThinkingBudgetParity:
    """Tests that thinking budget (extra_body) and structured output (response_format)
    are correctly forwarded through the unified LiteLLMProvider for all providers."""

    # ---- Thinking budget forwarding tests ----

    async def test_gemini_forwards_extra_body_thinking_config(self):
        """Gemini provider forwards extra_body with thinking_config to SDK create call."""
        provider = _make_provider("gemini")

        extra_body = {"google": {"thinking_config": {"thinking_budget": 2048}}}
        await provider.chat_completion(
            messages=[{"role": "user", "content": "Hi"}],
            model="gemini-2.5-pro",
            role=ModelRole.TARGET,
            extra_body=extra_body,
        )

        call_kwargs = provider._client.chat.completions.create.call_args.kwargs
        assert "extra_body" in call_kwargs
        assert call_kwargs["extra_body"]["google"]["thinking_config"]["thinking_budget"] == 2048

    async def test_openrouter_forwards_extra_body_without_error(self):
        """OpenRouter provider forwards extra_body without error."""
        provider = _make_provider("openrouter")

        extra_body = {"google": {"thinking_config": {"thinking_budget": 2048}}}
        await provider.chat_completion(
            messages=[{"role": "user", "content": "Hi"}],
            model="some-model",
            role=ModelRole.TARGET,
            extra_body=extra_body,
        )

        call_kwargs = provider._client.chat.completions.create.call_args.kwargs
        assert "extra_body" in call_kwargs
        assert call_kwargs["extra_body"] == extra_body

    async def test_openai_forwards_extra_body_without_error(self):
        """OpenAI provider forwards extra_body without error."""
        provider = _make_provider("openai")

        extra_body = {"google": {"thinking_config": {"thinking_budget": 2048}}}
        await provider.chat_completion(
            messages=[{"role": "user", "content": "Hi"}],
            model="gpt-4o",
            role=ModelRole.TARGET,
            extra_body=extra_body,
        )

        call_kwargs = provider._client.chat.completions.create.call_args.kwargs
        assert "extra_body" in call_kwargs
        assert call_kwargs["extra_body"] == extra_body

    # ---- Structured output (response_format) tests ----

    @pytest.mark.parametrize("provider_name", PROVIDERS)
    async def test_response_format_passed_to_sdk(self, provider_name: str):
        """response_format with json_schema is passed to SDK create call for all providers."""
        provider = _make_provider(provider_name)
        provider._client.chat.completions.create = AsyncMock(
            return_value=_mock_completion(content=SAMPLE_JSON_CONTENT)
        )

        response = await provider.chat_completion(
            messages=[{"role": "user", "content": "Evaluate"}],
            model="test-model",
            role=ModelRole.JUDGE,
            response_format=_BEHAVIOR_JUDGE_SCHEMA,
        )

        call_kwargs = provider._client.chat.completions.create.call_args.kwargs
        assert "response_format" in call_kwargs
        assert call_kwargs["response_format"] == _BEHAVIOR_JUDGE_SCHEMA
        # Verify content is returned as-is (JSON string in content field)
        assert response.content == SAMPLE_JSON_CONTENT
        parsed = json.loads(response.content)
        assert "evaluations" in parsed

    @pytest.mark.parametrize("provider_name", PROVIDERS)
    async def test_response_format_omitted_when_not_provided(self, provider_name: str):
        """response_format is NOT sent when not provided (no accidental default)."""
        provider = _make_provider(provider_name)

        await provider.chat_completion(
            messages=[{"role": "user", "content": "Hi"}],
            model="test-model",
            role=ModelRole.TARGET,
        )

        call_kwargs = provider._client.chat.completions.create.call_args.kwargs
        assert "response_format" not in call_kwargs

    # ---- _build_thinking_kwargs pattern test ----

    def test_build_thinking_kwargs_budget_zero_returns_empty(self):
        """Budget of 0 returns empty dict (Gemini 2.5 rejects budget=0 with 400)."""
        # Inline the _build_thinking_kwargs logic from evolve.py
        # (not importable -- it's a nested closure)
        thinking_config = {"target": {"thinking_budget": 0}}

        def _build_thinking_kwargs(role_name: str) -> dict:
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

        assert _build_thinking_kwargs("target") == {}

    def test_build_thinking_kwargs_budget_negative_returns_empty(self):
        """Budget of -1 returns empty dict (dynamic/provider default)."""
        thinking_config = {"meta": {"thinking_budget": -1}}

        def _build_thinking_kwargs(role_name: str) -> dict:
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

        assert _build_thinking_kwargs("meta") == {}

    def test_build_thinking_kwargs_budget_positive_returns_extra_body(self):
        """Positive budget returns correct extra_body structure."""
        thinking_config = {"judge": {"thinking_budget": 2048}}

        def _build_thinking_kwargs(role_name: str) -> dict:
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

        result = _build_thinking_kwargs("judge")
        assert result == {"extra_body": {"google": {"thinking_config": {"thinking_budget": 2048}}}}


# ===========================================================================
# TestToolCallParity (COMPAT-04)
# ===========================================================================


class TestToolCallParity:
    """Tests that tool definitions, tool call extraction, and normalization
    work identically across all providers."""

    # ---- Tool definition passthrough tests ----

    @pytest.mark.parametrize("provider_name", PROVIDERS)
    async def test_tools_kwarg_passed_to_sdk(self, provider_name: str):
        """tools kwarg with OpenAI function-calling schema is passed to SDK create call."""
        provider = _make_provider(provider_name)

        await provider.chat_completion(
            messages=[{"role": "user", "content": "What is the weather?"}],
            model="test-model",
            role=ModelRole.TARGET,
            tools=SAMPLE_TOOLS,
        )

        call_kwargs = provider._client.chat.completions.create.call_args.kwargs
        assert "tools" in call_kwargs
        assert call_kwargs["tools"] == SAMPLE_TOOLS

    # ---- Tool call extraction tests ----

    @pytest.mark.parametrize("provider_name", PROVIDERS)
    async def test_tool_calls_extracted_from_response(self, provider_name: str):
        """Response with tool_calls in nested format is extracted to list[dict]."""
        tc_mock = MagicMock()
        tc_mock.model_dump.return_value = {
            "id": "call_123",
            "type": "function",
            "function": {"name": "get_weather", "arguments": '{"location": "London"}'},
        }

        provider = _make_provider(provider_name)
        provider._client.chat.completions.create = AsyncMock(
            return_value=_mock_completion(tool_calls=[tc_mock])
        )

        response = await provider.chat_completion(
            messages=[{"role": "user", "content": "Weather?"}],
            model="test-model",
            role=ModelRole.TARGET,
            tools=SAMPLE_TOOLS,
        )

        assert response.tool_calls is not None
        assert len(response.tool_calls) == 1
        assert response.tool_calls[0]["function"]["name"] == "get_weather"

    @pytest.mark.parametrize("provider_name", PROVIDERS)
    async def test_no_tool_calls_returns_none(self, provider_name: str):
        """Response with no tool_calls returns tool_calls=None in LLMResponse."""
        provider = _make_provider(provider_name)
        provider._client.chat.completions.create = AsyncMock(
            return_value=_mock_completion(tool_calls=None)
        )

        response = await provider.chat_completion(
            messages=[{"role": "user", "content": "Hi"}],
            model="test-model",
            role=ModelRole.TARGET,
        )

        assert response.tool_calls is None

    @pytest.mark.parametrize("provider_name", PROVIDERS)
    async def test_multiple_tool_calls_extracted(self, provider_name: str):
        """Multiple tool calls in a single response are all extracted."""
        tc_mocks = []
        for i in range(3):
            tc = MagicMock()
            tc.model_dump.return_value = {
                "id": f"call_{i}",
                "type": "function",
                "function": {"name": f"func_{i}", "arguments": f'{{"arg": {i}}}'},
            }
            tc_mocks.append(tc)

        provider = _make_provider(provider_name)
        provider._client.chat.completions.create = AsyncMock(
            return_value=_mock_completion(tool_calls=tc_mocks)
        )

        response = await provider.chat_completion(
            messages=[{"role": "user", "content": "Do things"}],
            model="test-model",
            role=ModelRole.TARGET,
            tools=SAMPLE_TOOLS,
        )

        assert response.tool_calls is not None
        assert len(response.tool_calls) == 3
        names = [tc["function"]["name"] for tc in response.tool_calls]
        assert names == ["func_0", "func_1", "func_2"]

    # ---- _normalize_tool_call tests ----

    def test_normalize_nested_format(self):
        """_normalize_tool_call handles nested format (real API response) -> flat dict."""
        nested = {
            "id": "call_1",
            "type": "function",
            "function": {"name": "get_weather", "arguments": '{"city": "London"}'},
        }
        result = _normalize_tool_call(nested)
        assert result == {"name": "get_weather", "arguments": {"city": "London"}}

    def test_normalize_flat_format(self):
        """_normalize_tool_call handles flat format (test fixture style) -> same flat dict."""
        flat = {"name": "get_weather", "arguments": {"city": "London"}}
        result = _normalize_tool_call(flat)
        assert result == {"name": "get_weather", "arguments": {"city": "London"}}

    def test_normalize_json_string_arguments(self):
        """_normalize_tool_call handles JSON-string arguments -> parsed dict."""
        call = {"name": "fn", "arguments": '{"x": 1}'}
        result = _normalize_tool_call(call)
        assert result == {"name": "fn", "arguments": {"x": 1}}
