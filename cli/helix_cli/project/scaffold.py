"""Generate scaffold YAML files for new prompts."""

from __future__ import annotations


def scaffold_prompt_yaml(prompt_id: str) -> str:
    return f"""\
# Helix Prompt Definition
id: {prompt_id}
purpose: "Describe what this prompt does"

template: |
  You are a helpful assistant.

  User request: {{{{ request }}}}

  Respond helpfully and concisely.

# Variables are auto-extracted from the template if omitted.
# Uncomment to explicitly define types, descriptions, and anchors:
# variables:
#   - name: request
#     description: "The user's request"
#     var_type: string
#     is_anchor: false

# Tool definitions (OpenAI function-calling format), optional:
# tools:
#   - type: function
#     function:
#       name: search
#       description: "Search for information"
#       parameters:
#         type: object
#         properties:
#           query:
#             type: string
#         required: [query]
"""


def scaffold_dataset_yaml() -> str:
    return """\
# Helix Test Cases
# Each case defines inputs and expected behavior for scoring.
cases:
  - name: "Basic request"
    tier: normal                    # critical | normal | low
    tags: [demo]
    variables:
      request: "What is the weather today?"
    chat_history:
      - role: user
        content: "What is the weather today?"
    expected_output:
      require_content: true         # response must include text
      # behavior:                   # LLM-judged criteria (one per line)
      #   - "Responds helpfully"
      #   - "Stays on topic"
      # match_args:                 # expected tool call
      #   tool_name: search
      #   tool_args:
      #     query: weather
"""


def scaffold_config_yaml() -> str:
    return """\
# Helix Evolution Configuration
# Values here override GENE_* environment variables.

# Model/provider settings
models:
  meta:
    provider: gemini               # gemini | openrouter | openai
    model: gemini-2.5-flash
  target:
    provider: gemini
    model: gemini-2.5-flash
  judge:
    provider: gemini
    model: gemini-2.5-flash

# Evolution hyperparameters
evolution:
  generations: 10
  islands: 4
  conversations_per_island: 5
  budget_cap_usd: 2.00

# Inference parameters (passed to LLM calls)
# generation:
#   temperature: 0.7
#   max_tokens: 4096
"""
