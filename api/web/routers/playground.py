"""Playground API endpoint for interactive chat with streaming SSE responses,
playground variable persistence, and playground config persistence endpoints.

Provides:
- POST /{prompt_id}/chat for sending messages and receiving
  LLM responses token-by-token via Server-Sent Events (SSE).
- GET /{prompt_id}/variables for loading saved variable values from DB.
- PUT /{prompt_id}/variables for saving variable values to DB (upsert).
- GET /{prompt_id}/playground-config for loading playground turn_limit/budget from DB.
- PUT /{prompt_id}/playground-config for saving playground turn_limit/budget to DB.

The chat endpoint renders the prompt template as a system message, builds
the conversation context, and streams the target model's response.
Config cascade (global -> prompt-level) is respected for model/provider selection.

Supports agentic tool calling: when the model returns tool_calls instead of stop,
tool calls are resolved via MockMatcher and the model is called again, repeating
until finish_reason=stop or max_steps is reached.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from api.config.models import GeneConfig
from api.evaluation.renderer import TemplateRenderer
from api.gateway.cost import estimate_cost_from_tokens
from api.gateway.factory import create_provider
from api.registry.llm_mocker import LLMMocker
from api.registry.schemas import MockDefinition
from api.registry.service import PromptRegistry
from api.registry.tool_resolver import normalize_tool_call, resolve_tool_call
from api.storage.models import PlaygroundVariable, PromptConfig, ToolFormatGuide
from api.web.deps import get_config, get_db_session, get_registry
from api.web.schemas import (
    ChatRequest,
    PlaygroundConfigResponse,
    PlaygroundConfigUpdateRequest,
    PlaygroundVariablesResponse,
    PlaygroundVariablesUpdateRequest,
)

router = APIRouter()

logger = logging.getLogger(__name__)

DEFAULT_MAX_STEPS = 10


@router.get("/{prompt_id}/variables", response_model=PlaygroundVariablesResponse)
async def get_variables(
    prompt_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> PlaygroundVariablesResponse:
    """Return all saved variable values for a prompt from DB."""
    stmt = select(PlaygroundVariable).where(PlaygroundVariable.prompt_id == prompt_id)
    result = await session.execute(stmt)
    rows = result.scalars().all()
    variables = {row.variable_name: row.value for row in rows}
    return PlaygroundVariablesResponse(prompt_id=prompt_id, variables=variables)


@router.put("/{prompt_id}/variables", response_model=PlaygroundVariablesResponse)
async def save_variables(
    prompt_id: str,
    body: PlaygroundVariablesUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
) -> PlaygroundVariablesResponse:
    """Save variable values to DB (upsert per variable_name).

    For each variable in the request, check if (prompt_id, variable_name)
    exists; if yes update value, if no insert new row.
    """
    for var_name, var_value in body.variables.items():
        stmt = select(PlaygroundVariable).where(
            PlaygroundVariable.prompt_id == prompt_id,
            PlaygroundVariable.variable_name == var_name,
        )
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing is not None:
            existing.value = var_value
        else:
            session.add(
                PlaygroundVariable(
                    prompt_id=prompt_id,
                    variable_name=var_name,
                    value=var_value,
                )
            )

    await session.commit()

    # Return the full set of variables for this prompt
    stmt = select(PlaygroundVariable).where(PlaygroundVariable.prompt_id == prompt_id)
    result = await session.execute(stmt)
    rows = result.scalars().all()
    variables = {row.variable_name: row.value for row in rows}
    return PlaygroundVariablesResponse(prompt_id=prompt_id, variables=variables)


@router.get("/{prompt_id}/playground-config", response_model=PlaygroundConfigResponse)
async def get_playground_config(
    prompt_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> PlaygroundConfigResponse:
    """Return playground config (turn_limit, budget) for a prompt."""
    result = await session.execute(
        select(PromptConfig).where(PromptConfig.prompt_id == prompt_id)
    )
    row = result.scalar_one_or_none()
    return PlaygroundConfigResponse(
        turn_limit=row.playground_turn_limit if row else None,
        budget=row.playground_budget if row else None,
    )


@router.put("/{prompt_id}/playground-config", response_model=PlaygroundConfigResponse)
async def update_playground_config(
    prompt_id: str,
    body: PlaygroundConfigUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
) -> PlaygroundConfigResponse:
    """Update playground config (turn_limit, budget) for a prompt."""
    result = await session.execute(
        select(PromptConfig).where(PromptConfig.prompt_id == prompt_id)
    )
    row = result.scalar_one_or_none()
    if row:
        if body.turn_limit is not None:
            row.playground_turn_limit = body.turn_limit
        if body.budget is not None:
            row.playground_budget = body.budget
    else:
        row = PromptConfig(
            prompt_id=prompt_id,
            playground_turn_limit=body.turn_limit,
            playground_budget=body.budget,
        )
        session.add(row)
    await session.commit()
    return PlaygroundConfigResponse(
        turn_limit=row.playground_turn_limit,
        budget=row.playground_budget,
    )


def _sse_event(event: str, data: dict) -> str:
    """Format a single SSE event string."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/{prompt_id}/chat")
async def chat(
    prompt_id: str,
    body: ChatRequest,
    config: GeneConfig = Depends(get_config),
    registry: PromptRegistry = Depends(get_registry),
    session: AsyncSession = Depends(get_db_session),
):
    """Stream an LLM chat response via Server-Sent Events.

    Loads the prompt template from DB, renders it with provided variables as the
    system message, appends the conversation history, and streams the
    target model's response token-by-token.

    Supports agentic tool calling: when tools and mocks are configured on the
    prompt, tool calls are resolved via MockMatcher and the model is called again
    until finish_reason=stop or max_steps is reached.

    SSE events emitted:
    - token: {"content": "..."} -- each streamed token
    - tool_call: {"id": "...", "name": "...", "arguments": {...}} -- model called a tool
    - tool_result: {"tool_call_id": "...", "name": "...", "content": "..."} -- mock response
    - done: {"input_tokens": N, "output_tokens": N, "cost_usd": F, "model": "...",
             "finish_reason": "...", "steps": N} -- stream complete
    - error: {"message": "..."} -- on failure
    - limit_reached: {"reason": "turn_limit", "turns_used": N, "turn_limit": N}
    """
    # Load prompt from DB via registry
    record = await registry.load_prompt(prompt_id, config)

    # Get merged config from the record (includes per-prompt overrides)
    merged_config = record.config if record.config else config

    # Determine turn limit: DB config > request body
    db_turn_limit = None
    result = await session.execute(
        select(PromptConfig).where(PromptConfig.prompt_id == prompt_id)
    )
    config_row = result.scalar_one_or_none()
    if config_row and config_row.playground_turn_limit is not None:
        db_turn_limit = config_row.playground_turn_limit

    effective_turn_limit = db_turn_limit if db_turn_limit is not None else body.turn_limit

    # Check turn limit: count user messages
    user_turn_count = sum(1 for m in body.messages if m.get("role") == "user")
    if user_turn_count > effective_turn_limit:
        return StreamingResponse(
            _limit_reached_generator(user_turn_count, effective_turn_limit),
            media_type="text/event-stream",
        )

    # Get template from DB-loaded record
    template_source = record.template
    if not template_source:
        raise HTTPException(
            status_code=404,
            detail=f"Prompt template not found for '{prompt_id}'",
        )

    renderer = TemplateRenderer()

    try:
        system_prompt = renderer.render(template_source, body.variables)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Template rendering failed: {e}",
        ) from e

    # Build full message list: system + conversation history
    messages = [{"role": "system", "content": system_prompt}, *body.messages]

    # Collect tools and mocks from the prompt record
    tools = record.tools if record.tools else None
    mocks = record.mocks if record.mocks else None
    max_steps = body.max_steps if body.max_steps is not None else DEFAULT_MAX_STEPS

    # Load LLM mocker config and format guides from DB
    llm_mocker = None
    format_guides: dict[str, list[str]] = {}

    if config_row and config_row.extra:
        tool_mocker_mode = config_row.extra.get("tool_mocker_mode", "static") or "static"
        tool_mocker_provider = config_row.extra.get("tool_mocker_provider")
        tool_mocker_model = config_row.extra.get("tool_mocker_model")

        if tool_mocker_mode == "llm" and tool_mocker_provider and tool_mocker_model:
            # Load format guides
            fg_result = await session.execute(
                select(ToolFormatGuide).where(ToolFormatGuide.prompt_id == prompt_id)
            )
            for row in fg_result.scalars().all():
                format_guides[row.tool_name] = row.examples

            if format_guides:
                try:
                    mocker_provider = create_provider(tool_mocker_provider, merged_config)
                    llm_mocker = LLMMocker(mocker_provider, tool_mocker_model)
                except Exception as exc:
                    logger.warning("Failed to create LLM mocker: %s", exc)

    return StreamingResponse(
        _sse_generator(
            merged_config, messages,
            tools=tools, mocks=mocks, max_steps=max_steps,
            llm_mocker=llm_mocker, format_guides=format_guides,
        ),
        media_type="text/event-stream",
    )


async def _limit_reached_generator(turns_used: int, turn_limit: int):
    """Yield a single limit_reached SSE event and close."""
    yield _sse_event(
        "limit_reached",
        {
            "reason": "turn_limit",
            "turns_used": turns_used,
            "turn_limit": turn_limit,
        },
    )


async def _sse_generator(
    config: GeneConfig,
    messages: list[dict],
    *,
    tools: list[dict] | None = None,
    mocks: list[MockDefinition] | None = None,
    max_steps: int = DEFAULT_MAX_STEPS,
    llm_mocker: LLMMocker | None = None,
    format_guides: dict[str, list[str]] | None = None,
):
    """Stream LLM response tokens as SSE events with agentic tool loop.

    When the model returns tool_calls, resolves them via MockMatcher and calls
    the model again with tool results. Repeats until finish_reason=stop or
    max_steps is reached. Each step streams tokens + emits tool_call/tool_result
    events.
    """
    provider = create_provider(config.target_provider, config)

    target_model = provider._normalize_model(config.target_model)
    temperature = config.target_temperature or config.generation.temperature

    # Build base kwargs
    base_kwargs: dict = {
        "temperature": temperature,
    }

    # Add thinking budget if configured
    if config.target_thinking_budget is not None and config.target_thinking_budget != 0:
        base_kwargs["extra_body"] = {
            "thinking": {
                "type": "enabled",
                "budget_tokens": config.target_thinking_budget,
            }
        }

    # Add tools if available
    if tools:
        base_kwargs["tools"] = tools

    total_input_tokens = 0
    total_output_tokens = 0
    finish_reason = "stop"
    step = 0

    try:
        while step < max_steps:
            step += 1

            # Use non-streaming call to capture full response including tool_calls
            response = await provider._client.chat.completions.create(
                model=target_model,
                messages=messages,
                **base_kwargs,
            )

            # Extract usage
            if response.usage:
                total_input_tokens += response.usage.prompt_tokens or 0
                total_output_tokens += response.usage.completion_tokens or 0

            choice = response.choices[0]
            finish_reason = choice.finish_reason or "stop"
            message = choice.message

            # Stream text content as tokens
            if message.content:
                yield _sse_event("token", {"content": message.content, "step": step})

            # Check for tool calls — only enter loop if model actually called tools
            if not message.tool_calls:
                break

            # Emit tool_call events and resolve via MockMatcher
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": [tc.model_dump() for tc in message.tool_calls],
            }
            messages.append(assistant_msg)

            for tc in message.tool_calls:
                tc_dict = tc.model_dump()
                normalized = normalize_tool_call(tc_dict)
                tool_call_id = tc_dict.get("id", "")

                yield _sse_event("tool_call", {
                    "id": tool_call_id,
                    "name": normalized["name"],
                    "arguments": normalized["arguments"],
                    "step": step,
                })

                result_content = await resolve_tool_call(
                    normalized["name"],
                    normalized["arguments"],
                    mocks=mocks,
                    llm_mocker=llm_mocker,
                    format_guides=format_guides,
                )

                yield _sse_event("tool_result", {
                    "tool_call_id": tool_call_id,
                    "name": normalized["name"],
                    "content": result_content,
                    "step": step,
                })

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": result_content,
                })

            # Loop continues — next iteration calls LLM with tool results

        # Compute cost
        cost_usd = estimate_cost_from_tokens(target_model, total_input_tokens, total_output_tokens)

        yield _sse_event(
            "done",
            {
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "cost_usd": cost_usd if cost_usd is not None else 0.0,
                "model": target_model,
                "finish_reason": finish_reason,
                "steps": step,
            },
        )

    except Exception as e:
        logger.exception("SSE streaming error for model %s", target_model)
        yield _sse_event("error", {"message": str(e)})

    finally:
        await provider.close()
