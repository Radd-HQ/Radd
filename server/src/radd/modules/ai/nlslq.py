"""NL -> SLQ: prompt, repair values, compile-validate server-side, retry once."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.auth import authz
from radd.modules.auth.models import User
from radd.modules.fields import service as fields_service
from radd.modules.fields.models import FieldDefinition
from radd.modules.items import slq

from . import client, features, nlrepair, prompts, provider
from .types import (
    NL_MAX_ATTEMPTS,
    AiFeature,
    AiInvalidQueryError,
    AiRole,
    NlOutcome,
    NlQueryResponse,
    SlqDialect,
)

_NO_QUERY_ERROR = "the reply contained no JSON object with a non-empty 'slq' string"


def decide(attempt: int, error: str | None) -> NlOutcome:
    """Validation-retry decision (pure): valid -> accept; first failure -> retry
    with the error in-prompt; failure on the last allowed attempt -> reject (422)."""
    if error is None:
        return NlOutcome.ACCEPT
    return NlOutcome.RETRY if attempt < NL_MAX_ATTEMPTS - 1 else NlOutcome.REJECT


async def _compile_error(
    session: AsyncSession,
    slq_text: str,
    *,
    definitions_by_key: dict[str, FieldDefinition],
    actor_id: uuid.UUID,
    dialect: SlqDialect = SlqDialect.ITEMS,
) -> str | None:
    """Parse + compile the generated query against the target DIALECT's
    compiler; the SlqError message when invalid, None when it compiles."""
    try:
        if dialect is SlqDialect.WORKLOG:
            from radd.modules.timelogging.slq import compiler as worklog_compiler

            await worklog_compiler.compile_worklog_query(
                session, slq.parse(slq_text), current_user_id=actor_id
            )
        else:
            await slq.compile_query(
                session,
                slq.parse(slq_text),
                definitions_by_key=definitions_by_key,
                current_user_id=actor_id,
            )
    except slq.SlqError as exc:
        return str(exc)
    return None


async def nl_to_slq(
    session: AsyncSession,
    *,
    question: str,
    actor: User,
    dialect: SlqDialect = SlqDialect.ITEMS,
) -> NlQueryResponse:
    """Natural language -> SLQ. The system prompt embeds the frozen grammar plus
    the field registry; the produced query is VALIDATED by compiling it
    server-side (invalid -> one retry with the error in-prompt, then 422).
    `dialect` targets the surface the caller filters (spec 98: the timesheet's
    rows are worklogs — item fields ride `issue.` there)."""
    await features.require_feature(session, AiFeature.NL_SLQ)
    await authz.require_member(session, actor)  # RADD-788
    definitions = await fields_service.list_fields(session)
    # Small live value sets ride in the prompt (types/categories are a handful;
    # users/labels are not — those resolve via the repair pass instead).
    from radd.modules.items.slq.suggest_values import SuggestScope, value_candidates

    issue_types = [
        c.value for c in await value_candidates(session, SuggestScope(), "type", "", {})
    ]
    states = [c.value for c in await value_candidates(session, SuggestScope(), "state", "", {})]
    work_categories = (
        [c.value for c in await nlrepair.category_candidates(session)]
        if dialect is SlqDialect.WORKLOG
        else []
    )
    system = prompts.nl_system_prompt(
        definitions,
        dialect=dialect.value,
        issue_types=issue_types,
        work_categories=work_categories,
        states=states,
    )
    definitions_by_key: dict[str, FieldDefinition] = {}
    for definition in definitions:
        definitions_by_key.setdefault(definition.key, definition)

    from datetime import date as _date

    user_prompt = prompts.nl_user_prompt(question, today=_date.today().isoformat())
    last_slq, last_error = "", _NO_QUERY_ERROR
    for attempt in range(NL_MAX_ATTEMPTS):
        reply = await client.complete(session, AiRole.CHAT, system, user_prompt)
        parsed = provider.first_json(reply, dict) or {}
        candidate = parsed.get("slq")
        explanation = parsed.get("explanation")
        repair_notes: list[str] = []
        if isinstance(candidate, str) and candidate.strip():
            candidate = candidate.strip()
            # Value repair (spec 103 addendum): resolve entity values against the
            # live records BEFORE validation — for most fields an unknown value
            # would otherwise compile into a silent zero-row query ("jimmy" vs
            # the account "Jimmy Lee Barlow").
            try:
                parsed_query = slq.parse(candidate)
            except slq.SlqError as exc:
                error = str(exc)
            else:
                repaired, repairs = await nlrepair.repair_query(
                    session,
                    parsed_query,
                    definitions_by_key=definitions_by_key,
                    dialect=dialect.value,
                )
                if repairs:
                    candidate = slq.render(repaired)
                    repair_notes = [repair.note() for repair in repairs]
                error = await _compile_error(
                    session,
                    candidate,
                    definitions_by_key=definitions_by_key,
                    actor_id=actor.id,
                    dialect=dialect,
                )
        else:
            candidate, error = "", _NO_QUERY_ERROR
        outcome = decide(attempt, error)
        if outcome is NlOutcome.ACCEPT:
            explanation_text = explanation if isinstance(explanation, str) else ""
            if repair_notes:
                joined = "; ".join(repair_notes)
                suffix = f"{joined[0].upper()}{joined[1:]}."
                explanation_text = f"{explanation_text} {suffix}".strip()
            return NlQueryResponse(slq=candidate, explanation=explanation_text)
        last_slq, last_error = candidate, error or _NO_QUERY_ERROR
        if outcome is NlOutcome.RETRY:
            user_prompt = prompts.nl_retry_prompt(question, last_slq, last_error)
    raise AiInvalidQueryError(last_slq, last_error)
