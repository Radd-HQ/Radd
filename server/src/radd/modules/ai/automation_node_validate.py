"""`ai.validate`: check an intake draft against the admin's quality bar (spec 119).

Separate from `ai.classify`, which routes on enumerated answers and says nothing
in its own words; this model writes findings a person reads. It only ROUTES
(RADD-1329): pass, fail (any blocking finding), warn (minor only), or unavailable
(provider down, dormant, out of time), and publishes the findings
(`ctx.publish_findings`) for a downstream Block/Warn node to relay.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping

from radd.kernel import AutomationNodeKind, AutomationNodeSpec, NodeArity

from .automation_context import ask_structured, include_schema, preflight
from .types import AiFeature

logger = logging.getLogger(__name__)

NODE_KEY = "ai.validate"

#: The port a clean draft leaves by.
PASS_PORT = "pass"
#: The port a draft with at least one BLOCKING problem leaves by.
FAIL_PORT = "fail"
#: The port a draft with only MINOR problems leaves by (RADD-1329).
WARN_PORT = "warn"
#: The port an unreachable/dormant provider takes. LAST in `PORTS` because the
#: executor treats a contributed router's final port as its fallback — so a
#: failure the node does not catch itself still lands somewhere sensible.
FALLBACK_PORT = "unavailable"

#: Static ports, not `ports_for`: a client draws handles before it has params (RADD-1064).
PORTS: tuple[str, ...] = (PASS_PORT, FAIL_PORT, WARN_PORT, FALLBACK_PORT)

#: How the model grades a problem (RADD-1329).
SEVERITY_BLOCKING = "blocking"
SEVERITY_MINOR = "minor"

DEFAULT_MAX_FINDINGS = 5
#: A hard ceiling independent of the param. A model handed a vague bar can list
#: twenty things; twenty is a wall, not feedback.
MAX_FINDINGS_CEILING = 10

SYSTEM_PROMPT = (
    "You review newly submitted issue reports against a quality bar the "
    "administrator sets. Answer with findings: short, specific, actionable "
    "sentences addressed to the person who submitted it, in the second person. "
    "Each finding may name the field it is about, and says how serious it is: "
    "'blocking' when the submission cannot be worked on without it, 'minor' "
    "when it would merely be better with it. Report only real problems "
    "against the stated bar — if the submission meets it, return no findings at "
    "all. Never invent facts about the issue, never restate the bar back, and "
    "never ask for information the submission already contains."
)


PARAMS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["prompt"],
    "properties": {
        "prompt": {
            "type": "string",
            "title": "The quality bar",
            "description": (
                "What a good submission looks like, in your words. The model "
                "reports what falls short of it, addressed to the submitter. "
                "Be concrete: 'a bug report must name the version, the steps to "
                "reproduce, and what was expected' beats 'submissions should be "
                "high quality'."
            ),
            "maxLength": 2000,
        },
        "max_findings": {
            "type": "integer",
            "title": "Most findings to report",
            "description": (
                "A person fixing a submission can act on a handful. Extra "
                "findings are dropped, not summarised."
            ),
            "minimum": 1,
            "maximum": MAX_FINDINGS_CEILING,
            "default": DEFAULT_MAX_FINDINGS,
        },
        "include": include_schema(
            "Which parts of the draft are sent. Reads run as the "
            "automation's identity, which is usually wider than the "
            "submitter's — and the findings are shown to whoever submitted, "
            "including a portal visitor. Anything an upstream node puts in "
            "front of the model can end up quoted back in a finding, so "
            "treat what you include as readable by the person submitting."
        ),
    },
}

#: The answer shape. `passed` is asked for as well as `findings` so a model that
#: means "this is fine" has a way to say so that does not depend on returning an
#: empty array — but findings WIN when the two disagree, because a model that
#: listed three problems and then ticked "passed" has told us about the problems.
FINDINGS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["passed", "findings"],
    "additionalProperties": False,
    "properties": {
        "passed": {"type": "boolean"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["message", "severity"],
                "additionalProperties": False,
                "properties": {
                    "message": {"type": "string"},
                    "field": {"type": "string"},
                    "severity": {"type": "string", "enum": [SEVERITY_BLOCKING, SEVERITY_MINOR]},
                },
            },
        },
    },
}


def max_findings(params: Mapping[str, Any]) -> int:
    """Clamped into the schema's range; not `or DEFAULT` — a stored 0 is falsy."""
    raw = params.get("max_findings")
    if raw is None:
        return DEFAULT_MAX_FINDINGS
    try:
        wanted = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_MAX_FINDINGS
    return max(1, min(wanted, MAX_FINDINGS_CEILING))


async def plan(ctx: Any) -> str:
    """Check the draft, publish what it found, and name the port it leaves by.
    Never raises: every failure is the `unavailable` port."""
    params = dict(ctx.node.params)
    if not await preflight(ctx, AiFeature.VALIDATION, NODE_KEY):
        return FALLBACK_PORT

    try:
        answer = await _ask(ctx, params)
    except Exception:
        logger.exception("ai.validate: provider unavailable")
        return FALLBACK_PORT

    findings = _findings_of(answer, params)
    if not findings:
        return PASS_PORT
    vocabulary = await _field_vocabulary(ctx)
    publish = getattr(ctx, "publish_findings", None)
    if callable(publish):
        # An unknown field key degrades to a GENERAL finding rather than being
        # dropped: the advice is still worth reading, it just has no control to
        # attach itself to. Same rule a card layout's departed attribute follows.
        publish([
            {"message": message, "field": field if field in vocabulary else "", "blocking": blocking}
            for message, field, blocking in findings
        ])
    return FAIL_PORT if any(blocking for _m, _f, blocking in findings) else WARN_PORT


def _findings_of(answer: Mapping[str, Any], params: Mapping[str, Any]) -> list[tuple[str, str, bool]]:
    """(message, field, blocking), capped; an ungraded finding BLOCKS; findings
    beat `passed` (a model that listed problems has told us about them)."""
    raw = answer.get("findings")
    found: list[tuple[str, str, bool]] = []
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        message = str(entry.get("message") or "").strip()
        if not message:
            continue
        blocking = str(entry.get("severity") or SEVERITY_BLOCKING) != SEVERITY_MINOR
        found.append((message, str(entry.get("field") or "").strip(), blocking))
    return found[: max_findings(params)]


async def _field_vocabulary(ctx: Any) -> set[str]:
    """Builtin field names plus `cf.<key>` for the draft's project (live registry)."""
    from radd.modules.fields import service as fields_service
    from radd.modules.fields.types import BuiltinItemField
    from radd.modules.projects.models import Project
    from radd.modules.items.models import WorkItem

    vocabulary = {field.value for field in BuiltinItemField}
    item_ids = tuple(ctx.packet.item_ids)
    if not item_ids:
        return vocabulary
    project_id = await ctx.session.scalar(
        WorkItem.__table__.select()
        .with_only_columns(WorkItem.project_id)
        .where(WorkItem.id == item_ids[0])
    )
    if project_id is None:
        return vocabulary
    project = await ctx.session.get(Project, project_id)
    if project is None:
        return vocabulary
    for definition in await fields_service.definitions_for_project(ctx.session, project):
        vocabulary.add(f"{CUSTOM_FIELD_PREFIX}{definition.key}")
    return vocabulary


#: Mirrors `automations.service.CUSTOM_FIELD_PREFIX`. Duplicated rather than
#: imported: `ai` contributes this node through the KERNEL and imports nothing
#: from `automations` — which is what makes the seam a seam.
CUSTOM_FIELD_PREFIX = "cf."


async def _ask(ctx: Any, params: Mapping[str, Any]) -> Mapping[str, Any]:
    return await ask_structured(
        ctx,
        params,
        system=SYSTEM_PROMPT,
        user=lambda context: (
            f"The administrator's quality bar for this intake:\n{params.get('prompt', '')}\n\n"
            f"Report at most {max_findings(params)} findings.\n\n"
            f"The submission:\n{context}"
        ),
        schema=FINDINGS_SCHEMA,
    )


SPEC = AutomationNodeSpec(
    key=NODE_KEY,
    kind=AutomationNodeKind.GATE.value,  # routes the packet without changing the item set
    label="AI check",
    description=(
        "Check a submission against a quality bar you describe. It leaves by pass, "
        "fail (a blocking problem), warn (only minor ones) or can't check; wire a "
        "Block submission or Warn submitter node after it to tell the person — "
        "they relay the model's findings in its own words."
    ),
    group="Gates",
    params_schema=PARAMS_SCHEMA,
    ports=PORTS,
    produces_findings=True,
    #: A check about nothing has nothing to say — and an empty packet in a
    #: validation walk means an upstream filter excluded this draft.
    needs_items=True,
    # SET only: a validation walk carries one draft.
    arity=NodeArity.SET.value,
    plan=plan,
)
