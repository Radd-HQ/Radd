"""An AI quality check for intake drafts (spec 119).

Sibling to `automation_node.py`, and the split is the point. `ai.classify`
ROUTES: it is constrained to an enumerated set of answers precisely so it cannot
invent a branch, and it says nothing in its own words. This one WRITES: the admin
gives a quality bar in prose, and the model answers with findings — sentences a
person reads and acts on, each optionally aimed at the field it is about.

Keeping them apart rather than adding a "free text" mode to the classifier is
what stops each being worse at its job. A router that can also produce prose has
to decide, per call, which it is doing; a checker constrained to enumerated
answers can only ever say "no" without saying why, which is precisely the
canned-message version this rejected.

**It only ROUTES (RADD-1329).** It used to be drawn as a gate and ALSO write
the findings, so what refused a submission was the node plus a graph-wide mode
applied after the walk — nothing on the canvas said so. Now the model grades
each problem `blocking` or `minor`, the node leaves by:

* `pass` — nothing wrong;
* `fail` — at least one blocking problem;
* `warn` — only minor ones;
* `unavailable` ("can't check") — the provider is down, dormant, or out of time;

and it PUBLISHES what it found (`ctx.publish_findings`) for a "Block submission"
or "Warn submitter" node downstream to relay. What happens to the submission is
whichever of those someone wired — including what an outage does, which used to
be the hidden `on_unavailable` param.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping

from radd.kernel import AutomationNodeSpec

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

#: FIXED, unlike `ai.classify`'s. The answers here are prose, not branches — what
#: varies is what the model SAYS, not how many ways the packet can go. Declared
#: as the spec's static `ports` rather than computed by a `ports_for` that
#: ignores its argument (RADD-1064): a client drawing this node's handles has to
#: know the set before it has any params to ask about, and one that could only
#: guess drew a gate's TRUE/FALSE instead.
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
        "include": {
            "type": "object",
            "title": "What the model sees",
            "description": (
                "Which parts of the draft are sent. Reads run as the "
                "automation's identity, which is usually wider than the "
                "submitter's — and the findings are shown to whoever submitted, "
                "including a portal visitor. Anything an upstream node puts in "
                "front of the model can end up quoted back in a finding, so "
                "treat what you include as readable by the person submitting."
            ),
            "properties": {
                "fields": {
                    "type": "boolean",
                    "default": True,
                    "title": "Fields (type, state, priority, assignee, labels, custom fields)",
                },
                "description": {"type": "boolean", "default": True, "title": "Description (in full)"},
                "comments": {"type": "boolean", "default": False, "title": "Comments (all)"},
                "worklogs": {"type": "boolean", "default": False, "title": "Logged time"},
            },
        },
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
    """The cap, clamped into the schema's own range.

    `or DEFAULT` would be wrong here: a stored `0` is falsy, and treating an
    explicit "report none" as "report five" is the opposite of what it says.
    Absent means the default; present-but-out-of-range is clamped.
    """
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

    Never raises: every failure is the `unavailable` port, which the graph
    decides the meaning of by what is wired to it.
    """
    from .features import feature_enabled
    from .types import AiFeature

    params = dict(ctx.node.params)
    if not str(params.get("prompt") or "").strip():
        # A check with no bar has nothing to measure against. Quiet rather than
        # blocking: an unfinished node must not refuse every submission.
        logger.info("ai.validate: node %s has no prompt; routing to %s", ctx.node.id, FALLBACK_PORT)
        return FALLBACK_PORT

    if _out_of_time(ctx):
        # The walk's wall-clock budget is spent (spec 119). Asked BEFORE the
        # feature gate: being out of time is a reason not to do any of the
        # remaining work. It is "can't check", which the graph decides the
        # meaning of by what it wired to that port (RADD-1329).
        logger.info("ai.validate: node %s ran out of time; taking %s", ctx.node.id, FALLBACK_PORT)
        return FALLBACK_PORT

    try:
        live = await feature_enabled(ctx.session, AiFeature.VALIDATION)
    except Exception:
        logger.exception("ai.validate: could not resolve the feature gate")
        live = False
    if not live:
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


def _out_of_time(ctx: Any) -> bool:
    """Whether the walk says to stop spending time.

    Read through `getattr` because this module is written against the executor's
    node context as a DUCK TYPE — `ai` contributes this node through the kernel
    and imports nothing from `automations`, so a context that predates the
    budget (or a plugin host that never had one) simply has all the time in the
    world rather than crashing.
    """
    ask = getattr(ctx, "out_of_time", None)
    return bool(ask()) if callable(ask) else False


def _findings_of(answer: Mapping[str, Any], params: Mapping[str, Any]) -> list[tuple[str, str, bool]]:
    """`(message, field, blocking)` from the model's answer, trimmed and capped.
    A finding with no grade (or a grade the schema does not know) BLOCKS — the
    cautious reading of a model that forgot to say.

    `passed` is consulted only when there is nothing to report — a model that
    listed problems and then said it passed has told us about the problems, and
    honouring the flag would throw away the part with information in it.
    """
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
    """Field keys a finding may legitimately name: the builtin names plus
    `cf.<key>` for every custom field in the draft's project.

    Resolved against the LIVE registry rather than a static list, so a project's
    own fields are addressable and a model naming something that does not exist
    is caught rather than passed to a client that will look for a control by
    that name and find none.
    """
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
    from . import client as ai_client
    from .automation_context import ContextOptions, build_context
    from .types import AiRole

    context = await build_context(
        ctx.session, tuple(ctx.packet.item_ids), ctx.actor, ContextOptions.from_params(dict(params))
    )
    user = (
        f"The administrator's quality bar for this intake:\n{params.get('prompt', '')}\n\n"
        f"Report at most {max_findings(params)} findings.\n\n"
        f"The submission:\n{context}"
    )
    return await ai_client.complete_structured(
        ctx.session, AiRole.CHAT, system=SYSTEM_PROMPT, user=user, json_schema=FINDINGS_SCHEMA
    )


SPEC = AutomationNodeSpec(
    key=NODE_KEY,
    kind="gate",  # routes the packet without changing the item set
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
    # Fixed SET: a validation walk carries exactly one draft, and the item
    # reading would be the same call with a loop around it. Offering the choice
    # would invite dropping it into a scheduled run over a broad query, which is
    # one model round trip per item with nobody reading the results.
    arity="set",
    plan=plan,
)
