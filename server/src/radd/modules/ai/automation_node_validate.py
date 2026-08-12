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

**On a validation walk** the findings join the collection through
`ctx.add_finding` — the seam `automations` exposes for exactly this, so this
module never imports its vocabulary. **On an ordinary event walk** nothing is
collecting, `add_finding` is a no-op, and the node is a pure router on
`pass`/`fail` — the same node, useful in both graphs, with no mode switch.

**An AI outage must not silently block intake.** The provider being down is not
evidence that a submission is bad. Failures take the `unavailable` port, which a
graph can wire; whether they ALSO record a blocking finding is `on_unavailable`,
default `pass`. A required-mode admin who would rather refuse than let anything
through unchecked sets it to `fail`, deliberately and visibly.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping

from radd.kernel import AutomationNodeSpec

logger = logging.getLogger(__name__)

NODE_KEY = "ai.validate"

#: The port a clean draft leaves by.
PASS_PORT = "pass"
#: The port a draft with findings leaves by.
FAIL_PORT = "fail"
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
PORTS: tuple[str, ...] = (PASS_PORT, FAIL_PORT, FALLBACK_PORT)

#: What `on_unavailable` may say. Not booleans on the wire: "pass" and "fail"
#: read as what happens to the submission, which is the question being answered.
ON_UNAVAILABLE_PASS = "pass"
ON_UNAVAILABLE_FAIL = "fail"

DEFAULT_MAX_FINDINGS = 5
#: A hard ceiling independent of the param. A model handed a vague bar can list
#: twenty things; twenty is a wall, not feedback.
MAX_FINDINGS_CEILING = 10

#: What the person is told when the check could not run and the admin chose to
#: refuse anyway. It names the cause, because "this was rejected" with no reason
#: is the worst refusal there is — and here the reason is not their fault.
UNAVAILABLE_MESSAGE = (
    "This submission could not be checked automatically right now, and this "
    "intake requires the check to run. Please try again shortly."
)

SYSTEM_PROMPT = (
    "You review newly submitted issue reports against a quality bar the "
    "administrator sets. Answer with findings: short, specific, actionable "
    "sentences addressed to the person who submitted it, in the second person. "
    "Each finding may name the field it is about. Report only real problems "
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
        "on_unavailable": {
            "type": "string",
            "title": "If the check cannot run",
            "description": (
                "The provider being unreachable is not evidence that a "
                "submission is bad, so the default lets it through. Choose "
                "'fail' only if you would rather refuse than accept anything "
                "unchecked — it turns every provider outage into a refused "
                "intake."
            ),
            "enum": [ON_UNAVAILABLE_PASS, ON_UNAVAILABLE_FAIL],
            "default": ON_UNAVAILABLE_PASS,
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
                "required": ["message"],
                "additionalProperties": False,
                "properties": {
                    "message": {"type": "string"},
                    "field": {"type": "string"},
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


def on_unavailable(params: Mapping[str, Any]) -> str:
    value = str(params.get("on_unavailable") or ON_UNAVAILABLE_PASS)
    return value if value in (ON_UNAVAILABLE_PASS, ON_UNAVAILABLE_FAIL) else ON_UNAVAILABLE_PASS


async def plan(ctx: Any) -> str:
    """Check the draft, record what it found, and name the port it leaves by.

    Never raises. A contributed router that throws takes its fallback port
    anyway, but catching here is what lets the node decide whether an outage
    should ALSO refuse the submission — a decision the executor cannot make on
    its behalf.
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
        # feature gate, because being out of time is a reason not to do any of
        # the remaining work — and a model round trip is the only work here that
        # can be measured in seconds. It resolves as an outage rather than as a
        # pass, so an admin who set `on_unavailable: fail` still gets what they
        # asked for: the check did not run.
        logger.info("ai.validate: node %s ran out of time; taking %s", ctx.node.id, FALLBACK_PORT)
        return _unavailable(ctx, params)

    try:
        live = await feature_enabled(ctx.session, AiFeature.VALIDATION)
    except Exception:
        logger.exception("ai.validate: could not resolve the feature gate")
        live = False
    if not live:
        return _unavailable(ctx, params)

    try:
        answer = await _ask(ctx, params)
    except Exception:
        logger.exception("ai.validate: provider unavailable")
        return _unavailable(ctx, params)

    findings = _findings_of(answer, params)
    if not findings:
        return PASS_PORT
    vocabulary = await _field_vocabulary(ctx)
    for message, field in findings:
        # An unknown field key degrades to a GENERAL finding rather than being
        # dropped: the advice is still worth reading, it just has no control to
        # attach itself to. Same rule a card layout's departed attribute follows.
        ctx.add_finding(message, field if field in vocabulary else "")
    return FAIL_PORT


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


def _unavailable(ctx: Any, params: Mapping[str, Any]) -> str:
    if on_unavailable(params) == ON_UNAVAILABLE_FAIL:
        ctx.add_finding(UNAVAILABLE_MESSAGE)
    return FALLBACK_PORT


def _findings_of(answer: Mapping[str, Any], params: Mapping[str, Any]) -> list[tuple[str, str]]:
    """`(message, field)` pairs from the model's answer, trimmed and capped.

    `passed` is consulted only when there is nothing to report — a model that
    listed problems and then said it passed has told us about the problems, and
    honouring the flag would throw away the part with information in it.
    """
    raw = answer.get("findings")
    found: list[tuple[str, str]] = []
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        message = str(entry.get("message") or "").strip()
        if not message:
            continue
        found.append((message, str(entry.get("field") or "").strip()))
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
        "Check a submission against a quality bar you describe, and report what "
        "falls short in the model's own words. In a validation graph the "
        "findings are shown to the person submitting; anywhere else it is a "
        "pass/fail router."
    ),
    group="Gates",
    params_schema=PARAMS_SCHEMA,
    ports=PORTS,
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
