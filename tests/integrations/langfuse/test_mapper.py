from copy import deepcopy

import pytest
from pydantic import ValidationError

from api.integrations.langfuse.mapper import map_dataset_item, map_observation
from api.integrations.langfuse.models import LangfuseSourceRequest


def test_message_dataset_item_maps_system_to_metadata():
    preview = map_dataset_item(
        {
            "id": "item-1",
            "input": {
                "messages": [
                    {"role": "system", "content": "old system"},
                    {"role": "user", "content": "hello"},
                ]
            },
            "expectedOutput": "welcome",
        },
        prompt_variables=set(),
    )

    assert preview.case.chat_history == [{"role": "user", "content": "hello"}]
    assert preview.case.expected_output == {"content": "welcome"}
    assert preview.case.source_metadata["source_system_prompt"] == "old system"


def test_bare_message_list_becomes_chat_history():
    preview = map_dataset_item(
        {
            "id": "item-messages",
            "input": [
                {"role": "system", "content": "source prompt"},
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "second"},
            ],
        },
        prompt_variables=set(),
    )

    assert preview.case.chat_history == [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "second"},
    ]
    assert preview.case.variables == {}


def test_direct_helix_fields_map_without_flattening():
    tools = [{"type": "function", "function": {"name": "lookup"}}]
    preview = map_dataset_item(
        {
            "id": "item-fields",
            "input": {
                "variables": {"locale": "en"},
                "chat_history": [
                    {"role": "system", "content": "source prompt"},
                    {"role": "user", "content": "hello"},
                ],
                "tools": tools,
            },
        },
        prompt_variables={"locale"},
    )

    assert preview.case.variables == {"locale": "en"}
    assert preview.case.chat_history == [{"role": "user", "content": "hello"}]
    assert preview.case.tools == tools
    assert preview.case.source_metadata["source_system_prompt"] == "source prompt"


def test_arbitrary_dictionary_becomes_variables():
    preview = map_dataset_item(
        {"id": "item-dict", "input": {"question": "hello", "locale": "en"}},
        prompt_variables={"question", "locale"},
    )

    assert preview.case.variables == {"question": "hello", "locale": "en"}
    assert preview.case.chat_history == []


def test_scalar_input_warns_when_input_is_not_an_anchor_variable():
    preview = map_dataset_item(
        {"id": "item-scalar", "input": "hello"},
        prompt_variables={"question"},
    )

    assert preview.case.variables == {"input": "hello"}
    assert "Input variable is not declared by this prompt" in preview.warnings


def test_scalar_input_has_no_anchor_warning_when_declared():
    preview = map_dataset_item(
        {"id": "item-scalar", "input": 42},
        prompt_variables={"input"},
    )

    assert preview.case.variables == {"input": 42}
    assert "Input variable is not declared by this prompt" not in preview.warnings


@pytest.mark.parametrize(
    "expected_output",
    [
        {"behavior": ["Be concise"]},
        {
            "tool_calls": [{"name": "lookup", "arguments": {"id": 1}}],
            "match_args": "subset",
            "require_content": True,
        },
        {"content": "welcome"},
    ],
)
def test_helix_expected_output_dictionaries_pass_through(expected_output):
    preview = map_dataset_item(
        {"id": "item-output", "input": {}, "expectedOutput": expected_output},
        prompt_variables=set(),
    )

    assert preview.case.expected_output == expected_output


def test_arbitrary_expected_output_dictionary_becomes_content():
    preview = map_dataset_item(
        {
            "id": "item-structured-output",
            "input": {},
            "expectedOutput": {"answer": 42},
        },
        prompt_variables=set(),
    )

    assert preview.case.expected_output == {"content": {"answer": 42}}


def test_dataset_metadata_preserves_source_identity_and_timestamp():
    preview = map_dataset_item(
        {
            "id": "item-meta",
            "datasetName": "support/qa",
            "createdAt": "2026-07-10T12:00:00Z",
            "input": {},
        },
        prompt_variables=set(),
    )

    assert preview.case.source_metadata == {
        "type": "langfuse",
        "external_id": "item-meta",
        "source_kind": "dataset_item",
        "dataset_name": "support/qa",
        "source_timestamp": "2026-07-10T12:00:00Z",
        "observed_config": {},
    }


def test_dataset_mapping_is_deterministic_and_does_not_mutate_input():
    item = {
        "id": "stable-item",
        "input": {"messages": [{"role": "user", "content": "hello"}]},
        "expectedOutput": {"content": "world"},
    }
    original = deepcopy(item)

    first = map_dataset_item(item, prompt_variables=set())
    second = map_dataset_item(item, prompt_variables=set())

    assert first == second
    assert item == original


def test_observation_requires_reproducibility_fields():
    preview = map_observation(
        {"id": "obs-1", "input": [{"role": "user", "content": "hi"}], "output": "ok"},
        prompt_variables=set(),
    )

    assert preview.importable is False
    assert preview.missing_fields == ["model", "temperature", "max_tokens"]


def test_observation_requires_complete_input():
    preview = map_observation(
        {
            "id": "obs-missing-input",
            "model": "openai/gpt-4.1-mini",
            "modelParameters": {"temperature": 0, "max_tokens": 100},
            "output": "ok",
        },
        prompt_variables=set(),
    )

    assert preview.importable is False
    assert preview.missing_fields == ["input"]


def test_complete_observation_preserves_parity_without_changing_case_config():
    preview = map_observation(
        {
            "id": "obs-complete",
            "traceId": "trace-1",
            "startTime": "2026-07-10T12:00:00Z",
            "providedModelName": "openai/gpt-4.1-mini",
            "modelParameters": {"temperature": 0, "maxTokens": 512},
            "input": [
                {"role": "system", "content": "observed system"},
                {"role": "user", "content": "hi"},
            ],
            "output": "ok",
        },
        prompt_variables=set(),
    )

    assert preview.importable is True
    assert preview.missing_fields == []
    assert preview.case.chat_history == [{"role": "user", "content": "hi"}]
    assert preview.case.expected_output == {"content": "ok"}
    assert preview.case.source_metadata == {
        "type": "langfuse",
        "external_id": "obs-complete",
        "source_kind": "observation",
        "trace_id": "trace-1",
        "source_timestamp": "2026-07-10T12:00:00Z",
        "source_system_prompt": "observed system",
        "observed_config": {
            "model": "openai/gpt-4.1-mini",
            "temperature": 0,
            "max_tokens": 512,
        },
    }
    assert "model" not in preview.case.variables
    assert "temperature" not in preview.case.variables
    assert "max_tokens" not in preview.case.variables


def test_observation_prefers_model_and_snake_case_max_tokens():
    preview = map_observation(
        {
            "id": "obs-aliases",
            "model": "resolved-model",
            "providedModelName": "fallback-model",
            "modelParameters": {"temperature": 0.25, "max_tokens": 256, "maxTokens": 512},
            "input": {"topic": "billing"},
            "output": {"tool_calls": [{"name": "lookup", "arguments": {}}]},
        },
        prompt_variables={"topic"},
    )

    assert preview.importable is True
    assert preview.case.variables == {"topic": "billing"}
    assert preview.case.expected_output == {
        "tool_calls": [{"name": "lookup", "arguments": {}}]
    }
    assert preview.case.source_metadata["observed_config"] == {
        "model": "resolved-model",
        "temperature": 0.25,
        "max_tokens": 256,
    }


def test_source_request_requires_identifier_matching_source_kind():
    assert LangfuseSourceRequest(
        prompt_id="prompt", source_kind="dataset", dataset_name="support"
    ).dataset_name == "support"
    assert LangfuseSourceRequest(
        prompt_id="prompt", source_kind="observation", observation_id="obs-1"
    ).observation_id == "obs-1"

    with pytest.raises(ValidationError, match="exactly one identifier"):
        LangfuseSourceRequest(prompt_id="prompt", source_kind="dataset", observation_id="obs-1")

    with pytest.raises(ValidationError, match="exactly one identifier"):
        LangfuseSourceRequest(
            prompt_id="prompt",
            source_kind="observation",
            dataset_name="support",
            observation_id="obs-1",
        )
