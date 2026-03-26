"""Scoring strategies for evaluating LLM responses against expected outputs.

Provides two concrete scorer implementations:
- ExactMatchScorer: deterministic comparison of tool call names and arguments
- BehaviorJudgeScorer: per-criterion binary evaluation of behavioral expectations
  via an LLM judge model

Both scorers return CaseResult with penalty scores (<= 0). 0 = no penalty (pass),
negative values indicate violations of varying severity.
"""

import json
import logging
from typing import Any

from api.evaluation.models import CaseResult
from api.gateway.protocol import LLMProvider
from api.registry.tool_resolver import normalize_tool_call
from api.types import LLMResponse, ModelRole

logger = logging.getLogger(__name__)

# ISO 639-1 code -> English language name lookup for judge prompt context
_LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "es": "Spanish",
    "zh": "Chinese",
    "ar": "Arabic",
    "pt": "Portuguese",
    "fr": "French",
    "de": "German",
    "ja": "Japanese",
    "ko": "Korean",
    "hi": "Hindi",
    "it": "Italian",
    "ru": "Russian",
    "nl": "Dutch",
    "th": "Thai",
    "vi": "Vietnamese",
    "tr": "Turkish",
    "pl": "Polish",
    "sv": "Swedish",
    "id": "Indonesian",
    "uk": "Ukrainian",
}




class ExactMatchScorer:
    """Scores tool call responses by comparing function names and arguments.

    Penalty-based scoring (0 = perfect, negative = violation):
    - 0 (passed=True): Tool names AND arguments match exactly.
    - -1 (passed=False): Tool names match but arguments differ.
    - -2 (passed=False): Tool names mismatch, missing tool calls, count mismatch,
      or silent response (require_content failure).
    - 0 (passed=True): Neither side has tool calls (not applicable, no penalty).

    Arguments are normalized via JSON serialization (sorted keys) to handle
    formatting differences. By default, type coercion is applied (string "2"
    equals int 2) unless strict_types=True.
    """

    def __init__(self, strict_types: bool = False):
        self._strict_types = strict_types

    async def score(
        self,
        expected: dict[str, Any],
        actual_response: LLMResponse,
        context: dict[str, Any] | None = None,
    ) -> CaseResult:
        ctx = context or {}
        case_id = ctx.get("case_id", "")

        expected_tools = expected.get("tool_calls", [])
        actual_tools = actual_response.tool_calls or []

        # Edge case: neither side has tool calls (not applicable, no penalty)
        if not expected_tools and not actual_tools:
            return CaseResult(
                case_id=case_id,
                score=0,
                passed=True,
                reason="Exact match not applicable: neither expected nor actual has tool_calls",
                expected=expected,
                actual_content=actual_response.content,
                actual_tool_calls=actual_tools if actual_tools else None,
            )

        # Edge case: one side missing tool calls
        if not expected_tools or not actual_tools:
            side = "actual" if not actual_tools else "expected"
            return CaseResult(
                case_id=case_id,
                score=-2,
                passed=False,
                reason=f"Tool call mismatch: {side} has no tool_calls",
                expected=expected,
                actual_content=actual_response.content,
                actual_tool_calls=actual_tools if actual_tools else None,
            )

        # require_content: response MUST include spoken text alongside tool calls
        if expected.get("require_content") and not (
            actual_response.content and actual_response.content.strip()
        ):
            return CaseResult(
                case_id=case_id,
                score=-2,
                passed=False,
                reason="Silent response: tool call executed without spoken text content",
                expected=expected,
                actual_content=actual_response.content,
                actual_tool_calls=actual_tools,
            )

        # Different number of tool calls
        if len(expected_tools) != len(actual_tools):
            return CaseResult(
                case_id=case_id,
                score=-2,
                passed=False,
                reason=(
                    f"Tool call count mismatch: expected {len(expected_tools)}, "
                    f"got {len(actual_tools)}"
                ),
                expected=expected,
                actual_content=actual_response.content,
                actual_tool_calls=actual_tools,
            )

        # Normalize all tool calls to flat {name, arguments} format
        expected_tools = [normalize_tool_call(tc) for tc in expected_tools]
        actual_tools = [normalize_tool_call(tc) for tc in actual_tools]

        # Compare tool calls in order
        all_names_match = True
        all_args_match = True
        match_args_mode = expected.get("match_args", "exact")

        for exp_call, act_call in zip(expected_tools, actual_tools, strict=False):
            exp_name = exp_call["name"]
            act_name = act_call["name"]

            if exp_name != act_name:
                all_names_match = False
                break

            if match_args_mode == "subset":
                # Subset matching: expected keys must exist in actual with matching values
                if not _args_subset_match(
                    exp_call["arguments"],
                    act_call["arguments"],
                    strict_types=self._strict_types,
                ):
                    all_args_match = False
            else:
                exp_args_norm = _normalize_args(
                    exp_call["arguments"], strict_types=self._strict_types
                )
                act_args_norm = _normalize_args(
                    act_call["arguments"], strict_types=self._strict_types
                )

                if exp_args_norm != act_args_norm:
                    all_args_match = False

        if not all_names_match:
            expected_names = [c["name"] for c in expected_tools]
            actual_names = [c["name"] for c in actual_tools]
            return CaseResult(
                case_id=case_id,
                score=-2,
                passed=False,
                reason=f"Tool name mismatch: expected {expected_names}, got {actual_names}",
                expected=expected,
                actual_content=actual_response.content,
                actual_tool_calls=actual_response.tool_calls,
            )

        if all_args_match:
            return CaseResult(
                case_id=case_id,
                score=0,
                passed=True,
                reason="Full match: tool names and arguments match exactly",
                expected=expected,
                actual_content=actual_response.content,
                actual_tool_calls=actual_response.tool_calls,
            )

        # Names match but arguments differ -> small penalty
        return CaseResult(
            case_id=case_id,
            score=-1,
            passed=False,
            reason="Partial match: tool names match but arguments differ",
            expected=expected,
            actual_content=actual_response.content,
            actual_tool_calls=actual_response.tool_calls,
        )


def _normalize_args(args: Any, *, strict_types: bool = False) -> str:
    """Normalize tool call arguments for deterministic comparison.

    Handles JSON strings, dict objects, and applies optional type coercion.
    Returns a canonical JSON string (sorted keys) for comparison.

    Args:
        args: Arguments as a dict or JSON string.
        strict_types: If False (default), coerce numeric strings to numbers.

    Returns:
        Canonical JSON string for comparison.
    """
    # Parse JSON string into dict if needed
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except (json.JSONDecodeError, TypeError):
            return args  # Return raw string if not valid JSON

    if not isinstance(args, dict):
        return json.dumps(args, sort_keys=True)

    if not strict_types:
        args = _coerce_types(args)

    return json.dumps(args, sort_keys=True)


def _args_subset_match(expected_args: Any, actual_args: Any, *, strict_types: bool = False) -> bool:
    """Check if expected arguments are a subset of actual arguments.

    Only verifies that keys present in expected exist in actual with matching
    values. Extra keys in actual are ignored. Useful when the tool schema has
    required arguments (like ``summary``) that vary per invocation and shouldn't
    be compared.

    Args:
        expected_args: Expected argument dict (or JSON string).
        actual_args: Actual argument dict (or JSON string).
        strict_types: If False, coerce numeric strings before comparison.

    Returns:
        True if all expected keys match in actual.
    """
    # Parse JSON strings if needed
    if isinstance(expected_args, str):
        try:
            expected_args = json.loads(expected_args)
        except (json.JSONDecodeError, TypeError):
            return str(expected_args) == str(actual_args)
    if isinstance(actual_args, str):
        try:
            actual_args = json.loads(actual_args)
        except (json.JSONDecodeError, TypeError):
            return False

    if not isinstance(expected_args, dict) or not isinstance(actual_args, dict):
        return _normalize_args(expected_args, strict_types=strict_types) == _normalize_args(
            actual_args, strict_types=strict_types
        )

    if not strict_types:
        expected_args = _coerce_types(expected_args)
        actual_args = _coerce_types(actual_args)

    for key, exp_val in expected_args.items():
        if key not in actual_args:
            return False
        act_val = actual_args[key]
        if json.dumps(exp_val, sort_keys=True) != json.dumps(act_val, sort_keys=True):
            return False

    return True


def _coerce_types(obj: Any) -> Any:
    """Recursively coerce numeric strings to numbers for comparison.

    "2" -> 2, "3.14" -> 3.14, "true" stays "true" (only numeric coercion).
    """
    if isinstance(obj, dict):
        return {k: _coerce_types(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_coerce_types(item) for item in obj]
    if isinstance(obj, str):
        # Try int first, then float
        try:
            return int(obj)
        except ValueError:
            pass
        try:
            return float(obj)
        except ValueError:
            pass
    return obj


# ===========================================================================
# BehaviorJudgeScorer
# ===========================================================================

# JSON schema for structured behavior judge output
_BEHAVIOR_JUDGE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "behavior_evaluation",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "evaluations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "criterion": {
                                "type": "string",
                                "description": "The behavior criterion being evaluated.",
                            },
                            "passed": {
                                "type": "boolean",
                                "description": "Whether the criterion is satisfied.",
                            },
                            "reason": {
                                "type": "string",
                                "description": "Explanation of the evaluation.",
                            },
                        },
                        "required": ["criterion", "passed", "reason"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["evaluations"],
            "additionalProperties": False,
        },
    },
}


class BehaviorJudgeScorer:
    """Scores responses against natural language behavior criteria.

    Penalty-based scoring: each failed criterion adds -2 penalty.
    Passed criteria add 0 (no penalty). Total score = sum of per-criterion
    penalties. All criteria must pass for the case to pass.

    Judge provides a reason for every criterion evaluation (both pass and fail).
    """

    def __init__(self, client: LLMProvider, judge_model: str, extra_kwargs: dict | None = None):
        self._client = client
        self._judge_model = judge_model
        self._extra_kwargs = extra_kwargs

    async def score(
        self,
        expected: dict[str, Any],
        actual_response: LLMResponse,
        context: dict[str, Any] | None = None,
    ) -> CaseResult:
        ctx = context or {}
        case_id = ctx.get("case_id", "")
        criteria = expected.get("behavior", [])

        if not criteria:
            return CaseResult(
                case_id=case_id,
                score=0,
                passed=True,
                reason="No behavior criteria to evaluate",
                expected=expected,
                actual_content=actual_response.content,
            )

        # Build full conversation context for judge
        conversation = ctx.get("conversation", [])
        purpose = ctx.get("purpose", "")
        language = ctx.get("language", "en")
        messages = self._build_judge_prompt(
            criteria=criteria,
            conversation=conversation,
            actual_content=actual_response.content or "",
            actual_tool_calls=actual_response.tool_calls,
            purpose=purpose,
            language=language,
        )

        try:
            judge_response = await self._client.chat_completion(
                messages=messages,
                model=self._judge_model,
                role=ModelRole.JUDGE,
                temperature=0,
                response_format=_BEHAVIOR_JUDGE_SCHEMA,
                **(self._extra_kwargs or {}),
            )
            evaluations = self._parse_response(judge_response, criteria)
        except _JudgeParsingError as exc:
            return CaseResult(
                case_id=case_id,
                score=-2,
                passed=False,
                reason=f"Judge parsing failed: {exc}",
                expected=expected,
                actual_content=actual_response.content,
            )

        failed_count = sum(1 for e in evaluations if not e["passed"])
        score_val = -2 * failed_count  # -2 penalty per failed criterion
        passed = failed_count == 0  # All must pass

        reasons = []
        for e in evaluations:
            prefix = "PASS" if e["passed"] else "FAIL"
            reasons.append(f"[{prefix}] {e['criterion']}: {e['reason']}")

        return CaseResult(
            case_id=case_id,
            score=score_val,
            passed=passed,
            reason="; ".join(reasons),
            expected=expected,
            actual_content=actual_response.content,
            actual_tool_calls=actual_response.tool_calls,
            criteria_results=evaluations,
        )

    @staticmethod
    def _build_judge_prompt(
        criteria: list[str],
        conversation: list[dict[str, str]],
        actual_content: str,
        actual_tool_calls: list[dict[str, Any]] | None,
        purpose: str,
        language: str = "en",
    ) -> list[dict[str, str]]:
        """Build the behavior judge evaluation prompt messages.

        When language is not 'en', appends a context section instructing the
        judge to evaluate in the correct language context and not penalize
        non-English responses.
        """
        system_msg = (
            "You are an expert evaluator. Your task is to evaluate whether "
            "an AI assistant's response meets specific behavioral criteria.\n\n"
            "For EACH criterion listed below, determine if the response "
            "satisfies it (pass) or not (fail).\n\n"
            "Rules:\n"
            "- Evaluate ONLY the criteria provided, in the EXACT order given.\n"
            "- For each criterion, provide a clear, concise reason explaining "
            "your judgment.\n"
            "- A criterion passes if the response demonstrably exhibits the "
            "described behavior.\n"
            "- A criterion fails if the behavior is absent, incorrect, or "
            "insufficient.\n"
            "- Be strict but fair: the response doesn't need to use exact "
            "wording, but must clearly demonstrate the behavior.\n"
            "- Consider the FULL conversation context, not just the final "
            "response."
        )

        if language and language != "en":
            lang_name = _LANGUAGE_NAMES.get(language, language)
            system_msg += (
                f"\n\nIMPORTANT: The conversation is in {lang_name} ({language}). "
                f"Evaluate the response appropriateness in that language context. "
                f"Do not penalize for using {lang_name} instead of English."
            )

        # Format conversation as JSON for unambiguous context
        conversation_formatted = json.dumps(conversation, indent=2) if conversation else "[]"

        # Format tool calls section
        tool_calls_section = ""
        if actual_tool_calls:
            tool_calls_section = (
                f"\n\n## Tool Calls Made\n{json.dumps(actual_tool_calls, indent=2)}"
            )

        # Format criteria as numbered list
        criteria_formatted = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(criteria))

        user_parts = []
        if purpose:
            user_parts.append(f"## Purpose\n{purpose}")
        user_parts.append(f"## Conversation\n{conversation_formatted}")
        user_parts.append(f"## AI Response Being Evaluated\n{actual_content}{tool_calls_section}")
        user_parts.append(
            f"## Criteria to Evaluate\n{criteria_formatted}\n\n"
            f"Evaluate each criterion. Return your evaluation as JSON."
        )

        return [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": "\n\n".join(user_parts)},
        ]

    @staticmethod
    def _parse_response(
        response: LLMResponse,
        criteria: list[str],
    ) -> list[dict[str, Any]]:
        """Parse the judge's structured JSON response.

        If the judge returns a different number of evaluations than criteria,
        attempts to match by criterion text. Unmatched criteria are marked
        as failed with reason "Judge did not evaluate this criterion".

        Raises:
            _JudgeParsingError: If response content is null or invalid JSON.
        """
        if response.content is None:
            raise _JudgeParsingError("Judge returned null content")

        try:
            data = json.loads(response.content)
        except (json.JSONDecodeError, TypeError) as exc:
            raise _JudgeParsingError(f"Invalid JSON: {exc}") from exc

        raw_evaluations = data.get("evaluations", [])

        # If count matches, use positional mapping
        if len(raw_evaluations) == len(criteria):
            return [
                {
                    "criterion": criteria[i],
                    "passed": bool(raw_evaluations[i].get("passed", False)),
                    "reason": str(raw_evaluations[i].get("reason", "")),
                }
                for i in range(len(criteria))
            ]

        # Count mismatch: match by criterion text
        matched: dict[int, dict[str, Any]] = {}
        for raw_eval in raw_evaluations:
            raw_criterion = raw_eval.get("criterion", "")
            for idx, c in enumerate(criteria):
                if idx not in matched and raw_criterion.strip().lower() == c.strip().lower():
                    matched[idx] = {
                        "criterion": c,
                        "passed": bool(raw_eval.get("passed", False)),
                        "reason": str(raw_eval.get("reason", "")),
                    }
                    break

        # Build final list, marking unmatched criteria as failed
        result = []
        for idx, c in enumerate(criteria):
            if idx in matched:
                result.append(matched[idx])
            else:
                result.append(
                    {
                        "criterion": c,
                        "passed": False,
                        "reason": "Judge did not evaluate this criterion",
                    }
                )

        return result


class _JudgeParsingError(Exception):
    """Internal error for judge response parsing failures."""
