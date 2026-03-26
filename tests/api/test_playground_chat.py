"""Tests for Playground Chat SSE endpoint.

Covers:
- POST /api/prompts/{id}/chat returns SSE stream with token + done events (mocked LLM)
- POST /api/prompts/nonexistent/chat returns 404
- POST /api/prompts/{id}/chat with turn limit exceeded returns limit_reached event
- POST /api/prompts/{id}/chat renders template variables into system message
- POST /api/prompts/{id}/chat agentic tool loop with mock resolution
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx


PROMPT_ID = "test-chat"


async def _register_prompt(
    client: httpx.AsyncClient,
    prompt_id: str = PROMPT_ID,
    template: str = "You are a helpful assistant.",
) -> httpx.Response:
    """POST a new prompt and return the response."""
    return await client.post(
        "/api/prompts/",
        json={
            "id": prompt_id,
            "purpose": "Test prompt for playground chat",
            "template": template,
        },
    )


def _make_response(
    content: str | None = "Hello!",
    tool_calls=None,
    finish_reason: str = "stop",
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
):
    """Build a mock non-streaming ChatCompletion response."""
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
    return response


def _make_tool_call(call_id: str, name: str, arguments: dict):
    """Build a mock tool call object."""
    tc = MagicMock()
    tc.model_dump.return_value = {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }
    tc.get = tc.model_dump.return_value.get
    return tc


def _build_mock_provider(responses):
    """Build a mock provider whose _client.chat.completions.create returns responses in sequence."""
    mock_provider = AsyncMock()
    if isinstance(responses, list):
        mock_provider._client.chat.completions.create = AsyncMock(side_effect=responses)
    else:
        mock_provider._client.chat.completions.create = AsyncMock(return_value=responses)
    mock_provider.close = AsyncMock()
    mock_provider._normalize_model = lambda model: model
    return mock_provider


def _parse_sse_events(text: str) -> list[dict]:
    """Parse SSE text into a list of {event, data} dicts."""
    events = []
    current_event = None
    current_data = None

    for line in text.split("\n"):
        if line.startswith("event: "):
            current_event = line[len("event: "):]
        elif line.startswith("data: "):
            current_data = line[len("data: "):]
        elif line == "" and current_event is not None:
            events.append({
                "event": current_event,
                "data": json.loads(current_data) if current_data else None,
            })
            current_event = None
            current_data = None

    return events


class TestChatStream:
    """POST /api/prompts/{prompt_id}/chat."""

    async def test_chat_returns_sse_stream(self, client: httpx.AsyncClient):
        """POST with mocked provider returns SSE token events followed by done event."""
        await _register_prompt(client)

        mock_response = _make_response(content="Hello world")
        mock_provider = _build_mock_provider(mock_response)

        with patch(
            "api.web.routers.playground.create_provider",
            return_value=mock_provider,
        ):
            resp = await client.post(
                f"/api/prompts/{PROMPT_ID}/chat",
                json={"messages": [{"role": "user", "content": "hi"}]},
            )

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

        events = _parse_sse_events(resp.text)
        event_names = [e["event"] for e in events]
        assert "token" in event_names
        assert "done" in event_names

        # Verify token content
        token_events = [e for e in events if e["event"] == "token"]
        combined = "".join(e["data"]["content"] for e in token_events)
        assert combined == "Hello world"

        # Verify done event has expected fields
        done_event = next(e for e in events if e["event"] == "done")
        assert "input_tokens" in done_event["data"]
        assert "output_tokens" in done_event["data"]
        assert "model" in done_event["data"]
        assert "finish_reason" in done_event["data"]
        assert "steps" in done_event["data"]

    async def test_chat_prompt_not_found(self, client: httpx.AsyncClient):
        """POST /api/prompts/nonexistent/chat returns 404."""
        resp = await client.post(
            "/api/prompts/nonexistent/chat",
            json={"messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 404

    async def test_chat_turn_limit_exceeded(self, client: httpx.AsyncClient):
        """POST with more user messages than DB turn_limit returns limit_reached event."""
        await _register_prompt(client)

        # Set turn_limit=2 via playground config
        await client.put(
            f"/api/prompts/{PROMPT_ID}/playground-config",
            json={"turn_limit": 2},
        )

        # Send 3 user messages (exceeds limit of 2)
        resp = await client.post(
            f"/api/prompts/{PROMPT_ID}/chat",
            json={
                "messages": [
                    {"role": "user", "content": "msg1"},
                    {"role": "assistant", "content": "reply1"},
                    {"role": "user", "content": "msg2"},
                    {"role": "assistant", "content": "reply2"},
                    {"role": "user", "content": "msg3"},
                ],
            },
        )

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

        events = _parse_sse_events(resp.text)
        assert len(events) >= 1
        assert events[0]["event"] == "limit_reached"
        assert events[0]["data"]["reason"] == "turn_limit"
        assert events[0]["data"]["turns_used"] == 3
        assert events[0]["data"]["turn_limit"] == 2

    async def test_chat_renders_template_variables(self, client: httpx.AsyncClient):
        """POST with variables renders them into the system message."""
        await _register_prompt(
            client,
            template="You are an assistant for {{ name }}. Help them with {{ topic }}.",
        )

        captured_messages = []

        mock_response = _make_response(content="Sure!")
        mock_provider = _build_mock_provider(mock_response)

        # Capture messages passed to the LLM
        original_create = mock_provider._client.chat.completions.create

        async def capturing_create(*args, **kwargs):
            captured_messages.extend(kwargs.get("messages", []))
            return mock_response

        mock_provider._client.chat.completions.create = AsyncMock(
            side_effect=capturing_create
        )

        with patch(
            "api.web.routers.playground.create_provider",
            return_value=mock_provider,
        ):
            resp = await client.post(
                f"/api/prompts/{PROMPT_ID}/chat",
                json={
                    "messages": [{"role": "user", "content": "hello"}],
                    "variables": {"name": "Alice", "topic": "cooking"},
                },
            )

        assert resp.status_code == 200

        # Verify the system message was rendered with variables
        assert len(captured_messages) >= 1
        system_msg = captured_messages[0]
        assert system_msg["role"] == "system"
        assert "Alice" in system_msg["content"]
        assert "cooking" in system_msg["content"]


class TestAgenticToolLoop:
    """POST /api/prompts/{prompt_id}/chat with tool calls."""

    async def test_tool_call_emits_events(self, client: httpx.AsyncClient):
        """When model returns tool_calls and mocks exist, emits tool_call + tool_result events."""
        # Register prompt with tools and mocks
        await client.post(
            "/api/prompts/",
            json={
                "id": "tool-prompt",
                "purpose": "Test tool calling",
                "template": "You are a helpful assistant.",
                "tools": [{"type": "function", "function": {"name": "get_weather", "parameters": {}}}],
                "mocks": [{
                    "tool_name": "get_weather",
                    "scenarios": [{"match_args": {}, "response": "Sunny, 22°C"}],
                }],
            },
        )

        tc = _make_tool_call("call_1", "get_weather", {"city": "SF"})

        # Step 1: model returns tool_call, Step 2: model returns text after tool result
        responses = [
            _make_response(content=None, tool_calls=[tc], finish_reason="tool_calls"),
            _make_response(content="The weather in SF is sunny!", finish_reason="stop"),
        ]
        mock_provider = _build_mock_provider(responses)

        with patch(
            "api.web.routers.playground.create_provider",
            return_value=mock_provider,
        ):
            resp = await client.post(
                "/api/prompts/tool-prompt/chat",
                json={"messages": [{"role": "user", "content": "What's the weather?"}]},
            )

        assert resp.status_code == 200
        events = _parse_sse_events(resp.text)
        event_names = [e["event"] for e in events]

        assert "tool_call" in event_names
        assert "tool_result" in event_names
        assert "token" in event_names
        assert "done" in event_names

        # Verify tool_call event content
        tc_event = next(e for e in events if e["event"] == "tool_call")
        assert tc_event["data"]["name"] == "get_weather"

        # Verify tool_result event content
        tr_event = next(e for e in events if e["event"] == "tool_result")
        assert "Sunny" in tr_event["data"]["content"]

        # Verify done has steps count
        done_event = next(e for e in events if e["event"] == "done")
        assert done_event["data"]["steps"] == 2

    async def test_no_tools_no_loop(self, client: httpx.AsyncClient):
        """Without tools/mocks, behaves like normal single-step chat."""
        await _register_prompt(client, prompt_id="no-tools")

        mock_response = _make_response(content="Just text")
        mock_provider = _build_mock_provider(mock_response)

        with patch(
            "api.web.routers.playground.create_provider",
            return_value=mock_provider,
        ):
            resp = await client.post(
                "/api/prompts/no-tools/chat",
                json={"messages": [{"role": "user", "content": "hi"}]},
            )

        events = _parse_sse_events(resp.text)
        event_names = [e["event"] for e in events]
        assert "tool_call" not in event_names
        assert "tool_result" not in event_names
        assert "token" in event_names
        assert "done" in event_names

        done = next(e for e in events if e["event"] == "done")
        assert done["data"]["steps"] == 1

    async def test_multi_step_chained_tool_calls(self, client: httpx.AsyncClient):
        """Model chains 3 tool calls across 3 steps before returning text."""
        await client.post(
            "/api/prompts/",
            json={
                "id": "chain-prompt",
                "purpose": "Test chained tool calls",
                "template": "You are an assistant.",
                "tools": [
                    {"type": "function", "function": {"name": "get_balance", "parameters": {}}},
                    {"type": "function", "function": {"name": "check_eligibility", "parameters": {}}},
                    {"type": "function", "function": {"name": "transfer_funds", "parameters": {}}},
                ],
                "mocks": [
                    {"tool_name": "get_balance", "scenarios": [{"match_args": {}, "response": '{"balance": 1000}'}]},
                    {"tool_name": "check_eligibility", "scenarios": [{"match_args": {}, "response": '{"eligible": true}'}]},
                    {"tool_name": "transfer_funds", "scenarios": [{"match_args": {}, "response": '{"status": "ok"}'}]},
                ],
            },
        )

        tc1 = _make_tool_call("call_1", "get_balance", {})
        tc2 = _make_tool_call("call_2", "check_eligibility", {"amount": 500})
        tc3 = _make_tool_call("call_3", "transfer_funds", {"amount": 500})

        responses = [
            _make_response(content="Let me check...", tool_calls=[tc1], finish_reason="tool_calls"),
            _make_response(content="Checking eligibility...", tool_calls=[tc2], finish_reason="tool_calls"),
            _make_response(content="Processing transfer...", tool_calls=[tc3], finish_reason="tool_calls"),
            _make_response(content="Transfer of $500 completed!", finish_reason="stop"),
        ]
        mock_provider = _build_mock_provider(responses)

        with patch(
            "api.web.routers.playground.create_provider",
            return_value=mock_provider,
        ):
            resp = await client.post(
                "/api/prompts/chain-prompt/chat",
                json={"messages": [{"role": "user", "content": "Transfer $500"}]},
            )

        events = _parse_sse_events(resp.text)

        tool_calls = [e for e in events if e["event"] == "tool_call"]
        tool_results = [e for e in events if e["event"] == "tool_result"]
        tokens = [e for e in events if e["event"] == "token"]
        done = next(e for e in events if e["event"] == "done")

        assert len(tool_calls) == 3
        assert len(tool_results) == 3
        assert tool_calls[0]["data"]["name"] == "get_balance"
        assert tool_calls[1]["data"]["name"] == "check_eligibility"
        assert tool_calls[2]["data"]["name"] == "transfer_funds"

        # Verify mock responses were used
        assert '{"balance": 1000}' in tool_results[0]["data"]["content"]
        assert '{"eligible": true}' in tool_results[1]["data"]["content"]
        assert '{"status": "ok"}' in tool_results[2]["data"]["content"]

        # Final token should be the completion text
        assert any("Transfer of $500 completed" in t["data"]["content"] for t in tokens)

        assert done["data"]["steps"] == 4
        assert done["data"]["finish_reason"] == "stop"

    async def test_max_steps_limit(self, client: httpx.AsyncClient):
        """Agentic loop stops at max_steps even if model keeps calling tools."""
        await client.post(
            "/api/prompts/",
            json={
                "id": "loop-prompt",
                "purpose": "Test max steps",
                "template": "You are an assistant.",
                "tools": [{"type": "function", "function": {"name": "search", "parameters": {}}}],
                "mocks": [{"tool_name": "search", "scenarios": [{"match_args": {}, "response": "no results"}]}],
            },
        )

        # Set max_tool_steps=2 via config
        await client.put(
            "/api/prompts/loop-prompt/config",
            json={"max_tool_steps": 2},
        )

        tc = _make_tool_call("call_x", "search", {"q": "test"})

        # Model always returns tool calls — never stops on its own
        infinite_tool_response = _make_response(content="Searching...", tool_calls=[tc], finish_reason="tool_calls")
        final_response = _make_response(content="Done searching.", finish_reason="stop")

        responses = [infinite_tool_response, infinite_tool_response, final_response]
        mock_provider = _build_mock_provider(responses)

        with patch(
            "api.web.routers.playground.create_provider",
            return_value=mock_provider,
        ):
            resp = await client.post(
                "/api/prompts/loop-prompt/chat",
                json={"messages": [{"role": "user", "content": "search everything"}]},
            )

        events = _parse_sse_events(resp.text)
        tool_calls = [e for e in events if e["event"] == "tool_call"]
        done = next(e for e in events if e["event"] == "done")

        # Should stop after 2 tool steps (max_tool_steps=2)
        assert len(tool_calls) == 2
        assert done["data"]["steps"] >= 2
