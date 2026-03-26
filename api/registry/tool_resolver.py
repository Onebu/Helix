"""Shared tool call resolution with LLM mocker cascade.

Provides resolve_tool_call() which tries:
1. LLMMocker (if mode=llm, format guides exist for the tool)
2. Static MockMatcher (pattern-based scenario matching)
3. Default JSON response (when no mock matches)

Used by playground, synthesis engine, and evaluation pipeline.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from api.registry.llm_mocker import LLMMocker
from api.registry.mock_matcher import MockMatcher
from api.registry.schemas import MockDefinition

logger = logging.getLogger(__name__)

DEFAULT_MAX_TOOL_STEPS = 10


def normalize_tool_call(tc: dict[str, Any]) -> dict[str, Any]:
    """Extract name and arguments from a tool call dict (various formats)."""
    if "function" in tc:
        fn = tc["function"]
        name = fn.get("name", "")
        args_raw = fn.get("arguments", "{}")
    else:
        name = tc.get("name", "")
        args_raw = tc.get("arguments", "{}")

    if isinstance(args_raw, str):
        try:
            args = json.loads(args_raw)
        except (json.JSONDecodeError, TypeError):
            args = {}
    else:
        args = args_raw if isinstance(args_raw, dict) else {}

    return {"name": name, "arguments": args}


async def resolve_tool_call(
    tool_name: str,
    call_args: dict[str, Any],
    *,
    mocks: list[MockDefinition] | None = None,
    llm_mocker: LLMMocker | None = None,
    format_guides: dict[str, list[str]] | None = None,
    scenario_type: str = "success",
) -> str:
    """Resolve a tool call to a mock response using the cascade.

    Resolution order:
    1. LLMMocker (if available and format guide exists for this tool)
    2. Static MockMatcher (if mocks are configured)
    3. Default JSON response

    Args:
        tool_name: Name of the tool being called.
        call_args: Arguments passed to the tool.
        mocks: Static mock definitions for pattern matching.
        llm_mocker: Optional LLM-based mocker instance.
        format_guides: Dict mapping tool names to example response lists.
        scenario_type: Scenario type for LLM mocker ("success", "failure", "edge_case").

    Returns:
        Mock response string (always returns something, never None).
    """
    mock_response: str | None = None

    # Step 1: Try LLM mocker if available and format guide exists
    if llm_mocker is not None and format_guides and tool_name in format_guides:
        try:
            mock_response = await llm_mocker.generate_mock_response(
                tool_name=tool_name,
                call_args=call_args,
                format_guide_examples=format_guides[tool_name],
                scenario_type=scenario_type,
            )
        except Exception:
            logger.warning("LLM mocker failed for %s, falling back to static", tool_name)

    # Step 2: Fall back to static MockMatcher
    if mock_response is None and mocks:
        mock_response = MockMatcher.match(tool_name, call_args, mocks)

    # Step 3: Default response
    if mock_response is None:
        return json.dumps({"status": "ok", "message": f"No mock configured for {tool_name}"})

    return mock_response
