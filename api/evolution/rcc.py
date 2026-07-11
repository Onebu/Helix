"""RCC (Refinement through Critical Conversation) engine.

The critic receives evidence from every selected parent, and each author draft
is validated before it can leave the engine. Cost-controlled conversations
retain only the final draft; callback-driven conversations evaluate and retain
every round.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable

from jinja2 import TemplateSyntaxError

from api.evaluation.models import CaseResult
from api.evaluation.validator import TemplateValidator
from api.evolution.models import Candidate
from api.evolution.prompts import (
    AUTHOR_SYSTEM_PROMPT,
    AUTHOR_USER_PROMPT,
    CRITIC_SYSTEM_PROMPT,
    CRITIC_USER_PROMPT,
    DIVERSE_RESET_PROMPT,
    FRESH_GENERATION_PROMPT,
)
from api.gateway.cost import CostTracker
from api.gateway.protocol import LLMProvider
from api.types import ModelRole

logger = logging.getLogger(__name__)

_TEMPLATE_RE = re.compile(
    r"<revised_template>\s*(.*?)\s*</revised_template>",
    re.DOTALL,
)
_CANDIDATE_IDS_RE = re.compile(
    r"<candidate_ids>\s*(.*?)\s*</candidate_ids>",
    re.DOTALL,
)

DraftEvaluator = Callable[[Candidate], Awaitable[Candidate]]


def _format_parent_evidence(parents: list[Candidate]) -> str:
    """Format every actual parent and its evaluation for the critic."""
    blocks: list[str] = []
    for index, parent in enumerate(parents, start=1):
        results = parent.evaluation.case_results if parent.evaluation else []
        blocks.append(
            "\n".join(
                [
                    f"PARENT {index} [{parent.id}] score={parent.fitness_score}",
                    parent.template,
                    RCCEngine._format_failing_cases(results),
                    RCCEngine._format_passing_summary(results),
                ]
            )
        )
    return "\n\n".join(blocks)


class RCCEngine:
    """Run validated critic-author refinement with a configured meta-model."""

    def __init__(
        self,
        client: LLMProvider,
        cost_tracker: CostTracker,
        validator: TemplateValidator,
        meta_model: str,
        max_retries: int = 3,
        extra_kwargs: dict | None = None,
    ) -> None:
        if getattr(client, "owns_cost_accounting", False) is True and getattr(
            client, "cost_tracker", None
        ) is not cost_tracker:
            raise ValueError("Accounting provider and RCC must use the same CostTracker")
        self._client = client
        self._cost_tracker = cost_tracker
        self._validator = validator
        self._meta_model = meta_model
        self._max_retries = max_retries
        self._extra_kwargs = extra_kwargs

    async def run_conversation(
        self,
        parents: list[Candidate],
        original_template: str,
        anchor_variables: set[str],
        purpose: str,
        rcc_rounds: int,
        generation: int,
        evaluate_draft: DraftEvaluator | None = None,
    ) -> list[Candidate]:
        """Return validated drafts produced across the requested RCC rounds.

        Fresh generation consumes the first round. With ``evaluate_draft``,
        every valid round is evaluated, retained, and used as the next round's
        evidence. Without it, only the final valid draft is retained.
        """
        parent_ids = [parent.id for parent in parents]
        next_parent_ids = list(parent_ids)
        parent_evidence = (
            _format_parent_evidence(parents)
            if parents
            else "(Fresh generation has no selected parents.)"
        )
        drafts: list[Candidate] = []
        case_results: list[CaseResult] = []
        first_critic_round = 0

        if parents:
            current = max(parents, key=lambda candidate: candidate.fitness_score)
            current_template = current.template
            if current.evaluation is not None:
                case_results = current.evaluation.case_results
        else:
            if rcc_rounds < 1:
                return []
            current_template = await self._generate_fresh(
                original_template=original_template,
                anchor_variables=anchor_variables,
                purpose=purpose,
            )
            if current_template is None:
                return []

            candidate = Candidate(
                template=current_template,
                generation=generation,
                parent_ids=[],
            )
            if evaluate_draft is not None:
                candidate = await evaluate_draft(candidate)
                candidate.parent_ids = []
                candidate.generation = generation
                drafts.append(candidate)
                if candidate.evaluation is not None:
                    case_results = candidate.evaluation.case_results
                current_template = candidate.template
            else:
                drafts = [candidate]
            first_critic_round = 1

        required_variables_str = ", ".join(sorted(anchor_variables))

        for round_index in range(first_critic_round, rcc_rounds):
            logger.debug(
                "RCC round %d/%d for generation %d",
                round_index + 1,
                rcc_rounds,
                generation,
            )
            critic_messages = [
                {
                    "role": "system",
                    "content": CRITIC_SYSTEM_PROMPT.format(
                        purpose=purpose,
                        required_variables=required_variables_str,
                    ),
                },
                {
                    "role": "user",
                    "content": CRITIC_USER_PROMPT.format(
                        parent_evidence=parent_evidence,
                        current_template=current_template,
                        failing_cases_formatted=self._format_failing_cases(case_results),
                        passing_cases_summary=self._format_passing_summary(case_results),
                        required_variables=required_variables_str,
                    ),
                },
            ]
            critic_response = await self._client.chat_completion(
                messages=critic_messages,
                model=self._meta_model,
                role=ModelRole.META,
                **(self._extra_kwargs or {}),
            )
            if getattr(self._client, "owns_cost_accounting", False) is not True:
                self._cost_tracker.record(critic_response)
            revised = await self._author_with_retry(
                critic_analysis=critic_response.content or "",
                current_template=current_template,
                original_template=original_template,
                anchor_variables=anchor_variables,
            )
            if revised is None:
                logger.warning(
                    "All %d author attempts failed on round %d",
                    self._max_retries,
                    round_index + 1,
                )
                break

            candidate = Candidate(
                template=revised,
                generation=generation,
                parent_ids=list(next_parent_ids),
            )
            if evaluate_draft is not None:
                candidate = await evaluate_draft(candidate)
                candidate.parent_ids = list(next_parent_ids)
                candidate.generation = generation
                drafts.append(candidate)
                if candidate.evaluation is not None:
                    case_results = candidate.evaluation.case_results
                else:
                    case_results = []
                current_template = candidate.template
                next_parent_ids = [candidate.id]
            else:
                drafts = [candidate]
                current_template = revised

        return drafts

    async def _author_with_retry(
        self,
        critic_analysis: str,
        current_template: str,
        original_template: str,
        anchor_variables: set[str],
    ) -> str | None:
        """Return the first changed, non-empty, syntactically valid revision."""
        required_variables_str = ", ".join(sorted(anchor_variables))
        feedback: str | None = None

        for attempt in range(self._max_retries):
            user_prompt = AUTHOR_USER_PROMPT.format(
                critic_analysis=critic_analysis,
                template=current_template,
                required_variables=required_variables_str,
            )
            if feedback:
                user_prompt += f"\n\nIMPORTANT: {feedback}"

            author_response = await self._client.chat_completion(
                messages=[
                    {
                        "role": "system",
                        "content": AUTHOR_SYSTEM_PROMPT.format(
                            required_variables=required_variables_str,
                        ),
                    },
                    {"role": "user", "content": user_prompt},
                ],
                model=self._meta_model,
                role=ModelRole.META,
                **(self._extra_kwargs or {}),
            )
            if getattr(self._client, "owns_cost_accounting", False) is not True:
                self._cost_tracker.record(author_response)
            template = self._extract_template(author_response.content or "")
            feedback = self._template_feedback(
                original_template=original_template,
                candidate_template=template,
                anchor_variables=anchor_variables,
                current_template=current_template,
            )
            if feedback is None:
                return template

            logger.warning(
                "Author output invalid on attempt %d/%d: %s",
                attempt + 1,
                self._max_retries,
                feedback,
            )

        return None

    async def _generate_fresh(
        self,
        original_template: str,
        anchor_variables: set[str],
        purpose: str,
    ) -> str | None:
        """Generate and validate the first no-parent RCC round."""
        required_variables_str = ", ".join(sorted(anchor_variables))
        variable_descriptions = "\n".join(
            f"- {variable}: (used in template)" for variable in sorted(anchor_variables)
        )
        feedback: str | None = None

        for attempt in range(self._max_retries):
            prompt = FRESH_GENERATION_PROMPT.format(
                purpose=purpose,
                required_variables=required_variables_str,
                variable_descriptions=variable_descriptions,
            )
            if feedback:
                prompt += f"\n\nIMPORTANT: {feedback}"

            response = await self._client.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                model=self._meta_model,
                role=ModelRole.META,
                **(self._extra_kwargs or {}),
            )
            if getattr(self._client, "owns_cost_accounting", False) is not True:
                self._cost_tracker.record(response)
            template = self._extract_template(response.content or "")
            feedback = self._template_feedback(
                original_template=original_template,
                candidate_template=template,
                anchor_variables=anchor_variables,
                current_template=original_template,
            )
            if feedback is None:
                return template

            logger.warning(
                "Fresh output invalid on attempt %d/%d: %s",
                attempt + 1,
                self._max_retries,
                feedback,
            )

        return None

    def _template_feedback(
        self,
        original_template: str,
        candidate_template: str,
        anchor_variables: set[str],
        current_template: str | None = None,
    ) -> str | None:
        """Return retry feedback, or ``None`` when a draft is valid."""
        if not candidate_template.strip():
            return "You returned an empty template. Return a complete revised template."
        if current_template is not None and candidate_template.strip() == current_template.strip():
            return "You returned the unchanged template. Make a targeted revision."

        try:
            validation = self._validator.validate_preserved(
                original_template,
                candidate_template,
                anchor_variables,
            )
        except TemplateSyntaxError as exc:
            return f"The template has invalid Jinja2 syntax: {exc}."

        if validation.valid:
            return None

        feedback_parts: list[str] = []
        if validation.renamed_variables:
            rename_details = ", ".join(
                f"{old} -> {new}" for old, new in validation.renamed_variables.items()
            )
            feedback_parts.append(
                f"You RENAMED these variables: {rename_details}. "
                "Use the ORIGINAL variable names."
            )
        dropped = [
            variable
            for variable in validation.missing_variables
            if variable not in validation.renamed_variables
        ]
        if dropped:
            feedback_parts.append(
                f"You DROPPED these required variables: {', '.join(dropped)}."
            )
        feedback_parts.append(f"Required variables: {', '.join(sorted(anchor_variables))}")
        return " ".join(feedback_parts)

    async def select_diverse(
        self,
        candidates: list[Candidate],
        count: int,
    ) -> list[Candidate]:
        """Select validated meta-model IDs or use deterministic score fallback."""
        target = min(max(count, 0), len(candidates))
        if target == 0:
            return []

        listing = "\n\n".join(
            f"[{candidate.id}] score={candidate.fitness_score} rejected={candidate.rejected}\n"
            f"{candidate.template}"
            for candidate in candidates
        )
        response = await self._client.chat_completion(
            messages=[
                {
                    "role": "user",
                    "content": DIVERSE_RESET_PROMPT.format(
                        count=target,
                        candidates=listing,
                    ),
                }
            ],
            model=self._meta_model,
            role=ModelRole.META,
            **(self._extra_kwargs or {}),
        )
        if getattr(self._client, "owns_cost_accounting", False) is not True:
            self._cost_tracker.record(response)
        matches = _CANDIDATE_IDS_RE.findall(response.content or "")
        by_id = {candidate.id: candidate for candidate in candidates}
        if len(matches) == 1:
            candidate_ids = [item.strip() for item in matches[0].split(",")]
            if (
                len(candidate_ids) == target
                and len(set(candidate_ids)) == target
                and all(candidate_id in by_id for candidate_id in candidate_ids)
            ):
                return [by_id[candidate_id] for candidate_id in candidate_ids]

        return sorted(
            candidates,
            key=lambda candidate: (candidate.rejected, -candidate.fitness_score),
        )[:target]

    @staticmethod
    def _format_failing_cases(case_results: list[CaseResult]) -> str:
        """Format failed case IDs, tiers, scores, and reasons."""
        failing = [case_result for case_result in case_results if not case_result.passed]
        if not failing:
            return "(No failing cases)"
        return "\n".join(
            f"- Case {case.case_id} [tier={case.tier}, score={case.score:.2f}]: {case.reason}"
            for case in failing
        )

    @staticmethod
    def _format_passing_summary(case_results: list[CaseResult]) -> str:
        """Return a brief passing-case summary for critic context."""
        passing = [case_result for case_result in case_results if case_result.passed]
        if not passing:
            return "(No passing cases)"
        return f"{len(passing)} case(s) passed: {', '.join(case.case_id for case in passing)}"

    @staticmethod
    def _extract_template(response_content: str) -> str:
        """Extract a delimited template, falling back to stripped content."""
        match = _TEMPLATE_RE.search(response_content)
        if match:
            return match.group(1).strip()
        return response_content.strip()
