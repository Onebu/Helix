"""Wizard endpoint for LLM-powered prompt template generation.

Accepts wizard form answers and returns a generated YAML prompt template
using the configured meta_model via the gateway factory.
"""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from api.config.models import GeneConfig
from api.gateway.factory import create_provider
from api.storage.models import User
from api.types import ModelRole
from api.web.auth import get_current_user
from api.web.deps import get_config
from api.web.schemas import WizardGenerateRequest, WizardGenerateResponse

logger = logging.getLogger(__name__)

router = APIRouter()

WIZARD_SYSTEM_PROMPT = """\
You are an expert prompt engineer. Given a description of a prompt's purpose, \
variables, and constraints, generate a complete Jinja2 prompt template in YAML format.

CRITICAL: The template content MUST be a SYSTEM PROMPT — instructions that define an AI \
assistant's role, capabilities, constraints, and behavior. It should read like directives \
to an AI (e.g. "You are a ... assistant. Your role is to ..."). \
Do NOT write a conversational first message, greeting, or user-facing reply. \
The template is injected as the system message in an LLM chat completion call.

Structure the system prompt with clear sections:
- Role definition ("You are...")
- Context/knowledge (use {{ variables }} for dynamic data)
- Behavioral rules and constraints
- Output format expectations
- Edge case handling

Return ONLY valid YAML with the following structure:
- id: (slug identifier)
- purpose: (one-line description)
- template: | (multi-line Jinja2 SYSTEM PROMPT using {{ variable_name }} syntax)
- variables: (list of variable definitions with name, type, description, required, is_anchor)

Do NOT wrap the output in markdown code fences. Return raw YAML only.\
"""


def _format_user_prompt(body: WizardGenerateRequest) -> str:
    """Format wizard answers into a structured user message for the LLM."""
    parts = [
        f"Prompt ID: {body.id}",
        f"Purpose: {body.purpose}",
    ]

    if body.description:
        parts.append(f"Description: {body.description}")

    if body.variables:
        var_lines = []
        for v in body.variables:
            desc = f" - {v.description}" if v.description else ""
            anchor = " (anchor)" if v.is_anchor else ""
            examples = ""
            if v.examples:
                examples = f" [examples: {', '.join(str(e) for e in v.examples)}]"
            var_lines.append(f"  - {v.name} ({v.var_type}){anchor}{desc}{examples}")
        parts.append("Variables:\n" + "\n".join(var_lines))

    if body.constraints:
        parts.append(f"Constraints: {body.constraints}")

    if body.behaviors:
        parts.append(f"Expected behaviors: {body.behaviors}")

    if body.include_tools and body.tool_descriptions:
        tool_lines = []
        for tool in body.tool_descriptions:
            name = tool.get("name", "unknown")
            desc = tool.get("description", "")
            tool_lines.append(f"  - {name}: {desc}")
        parts.append("Tool definitions:\n" + "\n".join(tool_lines))

    if body.language and body.language != "en":
        parts.append(
            f"Language: Generate the template content in {body.language}. "
            "The system prompt should instruct the AI to respond in this language."
        )
    if body.channel == "voice":
        parts.append(
            "Channel: This is for voice/phone interactions. "
            "Template should instruct short responses, conversational tone, "
            "no markdown or visual formatting."
        )

    return "\n\n".join(parts)


def _clean_yaml_response(text: str) -> str:
    """Strip markdown code fences and leading/trailing whitespace from LLM output."""
    # Remove opening code fence (e.g. ```yaml, ```yml, ```)
    cleaned = re.sub(r"^```\w*\n?", "", text)
    # Remove closing code fence
    cleaned = re.sub(r"\n?```\s*$", "", cleaned)
    return cleaned.strip()


@router.post("/generate", response_model=WizardGenerateResponse)
async def generate_template(
    body: WizardGenerateRequest,
    config: GeneConfig = Depends(get_config),
    user: User = Depends(get_current_user),
) -> WizardGenerateResponse:
    """Generate a prompt template from wizard answers using the meta model."""
    try:
        provider = create_provider(config.meta_provider, config)
        async with provider:
            response = await provider.chat_completion(
                messages=[
                    {"role": "system", "content": WIZARD_SYSTEM_PROMPT},
                    {"role": "user", "content": _format_user_prompt(body)},
                ],
                model=config.meta_model,
                role=ModelRole.META,
            )

        yaml_text = _clean_yaml_response(response.content or "")
        return WizardGenerateResponse(yaml_template=yaml_text)

    except Exception:
        logger.exception("Wizard generation failed")
        return JSONResponse(
            status_code=502,
            content={"detail": "Template generation failed. Please try again."},
        )
