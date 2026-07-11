"""Pure mappings from Langfuse payloads to Helix test-case previews."""

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from api.dataset.models import TestCase
from api.integrations.langfuse.models import MappedCasePreview

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_INPUT_ANCHOR_WARNING = "Input variable is not declared by this prompt"
_DATASET_CONFIG_WARNING = "Dataset item does not include observed model configuration"
_EXPECTED_OUTPUT_KEYS = {"behavior", "tool_calls", "content", "require_content", "match_args"}


def map_dataset_item(
    item: dict[str, Any],
    prompt_variables: set[str],
    *,
    dataset_name: str | None = None,
) -> MappedCasePreview:
    """Map one Langfuse dataset item without mutating it or external state."""

    external_id = _external_id(item)
    chat_history, variables, tools, source_system_prompt, warnings = _map_input(
        item.get("input"), prompt_variables
    )
    warnings.append(_DATASET_CONFIG_WARNING)
    metadata = {
        "type": "langfuse",
        "external_id": external_id,
        "source_kind": "dataset_item",
        "dataset_name": dataset_name or item.get("datasetName") or item.get("dataset_name"),
        "source_timestamp": _first(item, "createdAt", "created_at", "timestamp"),
        "observed_config": {},
    }
    if source_system_prompt is not None:
        metadata["source_system_prompt"] = source_system_prompt

    case = TestCase(
        id=f"langfuse:dataset-item:{external_id}",
        created_at=_EPOCH,
        chat_history=chat_history,
        variables=variables,
        tools=tools,
        expected_output=_map_expected_output(item.get("expectedOutput")),
        source_metadata=metadata,
    )
    return MappedCasePreview(external_id=external_id, case=case, warnings=warnings)


def map_observation(
    observation: dict[str, Any], prompt_variables: set[str]
) -> MappedCasePreview:
    """Map one leaf observation and enforce its reproducibility parity gate."""

    external_id = _external_id(observation)
    input_present = "input" in observation and observation["input"] is not None
    chat_history, variables, tools, source_system_prompt, warnings = _map_input(
        observation.get("input"), prompt_variables
    )
    parameters = observation.get("modelParameters")
    parameters = parameters if isinstance(parameters, dict) else {}
    model = observation.get("model") or observation.get("providedModelName")
    temperature = parameters.get("temperature")
    max_tokens = (
        parameters.get("max_tokens")
        if "max_tokens" in parameters
        else parameters.get("maxTokens")
    )
    observed_config = {
        key: value
        for key, value in (
            ("model", model),
            ("temperature", temperature),
            ("max_tokens", max_tokens),
        )
        if value is not None
    }
    missing_fields = [
        key
        for key, value in (
            ("model", model),
            ("temperature", temperature),
            ("max_tokens", max_tokens),
        )
        if value is None or value == ""
    ]
    if not input_present:
        missing_fields.append("input")

    metadata = {
        "type": "langfuse",
        "external_id": external_id,
        "source_kind": "observation",
        "trace_id": observation.get("traceId") or observation.get("trace_id"),
        "source_timestamp": _first(
            observation, "startTime", "start_time", "createdAt", "created_at", "timestamp"
        ),
        "observed_config": observed_config,
    }
    if source_system_prompt is not None:
        metadata["source_system_prompt"] = source_system_prompt

    case = TestCase(
        id=f"langfuse:observation:{external_id}",
        created_at=_EPOCH,
        chat_history=chat_history,
        variables=variables,
        tools=tools,
        expected_output=_map_expected_output(observation.get("output")),
        source_metadata=metadata,
    )
    return MappedCasePreview(
        external_id=external_id,
        case=case,
        warnings=warnings,
        missing_fields=missing_fields,
        importable=not missing_fields,
    )


def _map_input(
    value: Any, prompt_variables: set[str]
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]] | None, str | None, list[str]]:
    warnings: list[str] = []
    if _is_message_list(value):
        chat_history, system_prompt = _without_system_messages(value)
        return chat_history, {}, None, system_prompt, warnings

    if isinstance(value, dict):
        recognized = any(
            key in value for key in ("messages", "chat_history", "variables", "tools")
        )
        if not recognized:
            return [], deepcopy(value), None, None, warnings

        messages = value.get("messages", value.get("chat_history", []))
        chat_history, system_prompt = (
            _without_system_messages(messages) if _is_message_list(messages) else ([], None)
        )
        variables = deepcopy(value.get("variables", {}))
        tools = deepcopy(value.get("tools"))
        return chat_history, variables, tools, system_prompt, warnings

    if "input" not in prompt_variables:
        warnings.append(_INPUT_ANCHOR_WARNING)
    return [], {"input": deepcopy(value)}, None, None, warnings


def _map_expected_output(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        if value.keys() & _EXPECTED_OUTPUT_KEYS:
            return deepcopy(value)
        return {"content": deepcopy(value)}
    return {"content": str(value)}


def _is_message_list(value: Any) -> bool:
    return isinstance(value, list) and all(
        isinstance(message, dict) and "role" in message for message in value
    )


def _without_system_messages(
    messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str | None]:
    system_parts = [
        str(message.get("content", "")) for message in messages if message.get("role") == "system"
    ]
    chat_history = [
        deepcopy(message) for message in messages if message.get("role") != "system"
    ]
    return chat_history, "\n\n".join(system_parts) if system_parts else None


def _external_id(source: dict[str, Any]) -> str:
    external_id = source.get("id")
    if external_id is None or str(external_id) == "":
        raise ValueError("Langfuse source is missing an id")
    return str(external_id)


def _first(source: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in source:
            return deepcopy(source[key])
    return None
