"""The two automation nodes (RADD-1269): run a script, and decide with one.

Contributed through the kernel exactly as the milestone and page actions are —
nothing here imports `automations`. The executor supplies the savepoint, the
budget and the loop guard; this module supplies what a script sees and what
its answer means.

What a script sees is bounded by WHO the automation runs as: the token minted
for the run is the actor's own, unscoped, so a key can never exceed its
account (spec 113). The packet's items are read through that actor too.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from radd.config import settings
from radd.kernel.specs import OutputField
from radd.sdk import AutomationNodeSpec

from . import runner, service
from .types import NODE_DECIDE, NODE_RUN, PERM_MANAGE, UNAVAILABLE_PORT

logger = logging.getLogger(__name__)

#: Params the script sees as its own — everything but the node's wiring.
_WIRING_PARAMS = frozenset({"script", "timeout", "outputs", "ports", "arity", "act_as"})
#: Outputs one node may declare; a token picker with fifty entries is a wall.
MAX_OUTPUTS = 20
MAX_PORTS = 8

RUN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["script"],
    "properties": {
        "script": {"type": "string", "title": "Script", "minLength": 1, "maxLength": 100},
        "outputs": {
            "type": "array",
            "title": "Outputs the script returns (keys of the dict main returns)",
            "items": {"type": "string"},
            "default": [],
        },
        "timeout": {
            "type": "integer",
            "title": "Timeout (seconds)",
            "minimum": 1,
            "maximum": 600,
            "default": 60,
        },
    },
}

DECIDE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["script", "ports"],
    "properties": {
        "script": {"type": "string", "title": "Script", "minLength": 1, "maxLength": 100},
        "ports": {
            "type": "array",
            "title": "Ports the script may name (it returns one of these)",
            "items": {"type": "string"},
            "default": ["yes", "no"],
        },
        "timeout": {
            "type": "integer",
            "title": "Timeout (seconds)",
            "minimum": 1,
            "maximum": 600,
            "default": 60,
        },
    },
}


def _names(values: Any, cap: int) -> list[str]:
    seen: list[str] = []
    for raw in values or []:
        name = str(raw).strip()
        if name and name not in seen:
            seen.append(name)
    return seen[:cap]


def outputs_for(params: dict[str, Any]) -> tuple[OutputField, ...]:
    return tuple(
        OutputField(name=name, label=name, description=f"`{name}` from the dict the script returns.")
        for name in _names(params.get("outputs"), MAX_OUTPUTS)
        if _is_identifier(name)
    )


def ports_for(params: dict[str, Any]) -> tuple[str, ...]:
    ports = [p for p in _names(params.get("ports"), MAX_PORTS) if p != UNAVAILABLE_PORT]
    return (*ports, UNAVAILABLE_PORT)


def _is_identifier(name: str) -> bool:
    return name.isidentifier()


def check_run(params: dict[str, Any]) -> None:
    for name in _names(params.get("outputs"), MAX_OUTPUTS + 1):
        if not _is_identifier(name):
            raise ValueError(f"output {name!r} could never be a token — use letters, digits and underscores")
    if len(_names(params.get("outputs"), MAX_OUTPUTS + 1)) > MAX_OUTPUTS:
        raise ValueError(f"at most {MAX_OUTPUTS} outputs")


def check_decide(params: dict[str, Any]) -> None:
    ports = _names(params.get("ports"), MAX_PORTS + 1)
    if not ports:
        raise ValueError("a deciding script needs at least one port to name")
    if len(ports) > MAX_PORTS:
        raise ValueError(f"at most {MAX_PORTS} ports")
    for port in ports:
        if not _is_identifier(port):
            raise ValueError(f"port {port!r} — use letters, digits and underscores")


@dataclass
class _Plan:
    detail: str
    resolves: bool = True
    script_id: uuid.UUID | None = None
    body: str = ""
    timeout: float = 60.0
    outputs: list[str] = field(default_factory=list)


def _timeout(params: dict[str, Any]) -> float:
    try:
        wanted = float(params.get("timeout") or settings.scripts_default_timeout_seconds)
    except (TypeError, ValueError):
        wanted = float(settings.scripts_default_timeout_seconds)
    return max(1.0, min(wanted, float(settings.scripts_max_timeout_seconds)))


async def _resolve(ctx: Any) -> _Plan:
    name = str(ctx.node.params.get("script") or "").strip()
    if not name:
        return _Plan("script: no script chosen", False)
    script = await service.script_by_name(ctx.session, name)
    if script is None:
        return _Plan(f"script: no script named {name!r}", False)
    if not script.body.strip():
        return _Plan(f"script: {name!r} is empty", False)
    return _Plan(
        f"script {name!r}",
        script_id=script.id,
        body=script.body,
        timeout=_timeout(ctx.node.params),
        outputs=_names(ctx.node.params.get("outputs"), MAX_OUTPUTS),
    )


def _ids(ctx: Any) -> list[uuid.UUID]:
    """The items this invocation is about. An ACTION is handed its subject ids
    by the executor; a GATE is not (it routes the whole packet), so it reads
    the packet's items itself — the same reading `ai.classify` takes."""
    return list(ctx.subject_ids) or list(getattr(ctx.packet, "item_ids", ()))


async def _execute(ctx: Any, plan: _Plan) -> runner.Outcome:
    """Mint the run's key, hand the packet over, run, discard the key."""
    payload = await service.packet_payload(
        ctx.session,
        actor=ctx.actor,
        subject_ids=_ids(ctx),
        facts=ctx.packet.facts,
        variables={k: dict(v) for k, v in dict(ctx.packet.vars).items()},
        params={k: v for k, v in dict(ctx.node.params).items() if k not in _WIRING_PARAMS},
    )
    return await service.run_body(
        ctx.session, plan.body, payload, actor=ctx.actor, timeout=plan.timeout, label=f"node {ctx.node.id}"
    )


# --- script.run --------------------------------------------------------------


async def plan_run(ctx: Any) -> _Plan:
    plan = await _resolve(ctx)
    if plan.resolves:
        plan.detail = f"run {plan.detail} on {len(_ids(ctx))} item(s)"
    return plan


async def apply_run(ctx: Any, plan: _Plan) -> None:
    outcome = await _execute(ctx, plan)
    if not outcome.ok:
        # Raised so the executor's savepoint rolls back whatever the script
        # wrote through the API in the same transaction (nothing — it went
        # over HTTP), logs it, and the run report records the failure against
        # this node rather than calling it applied.
        raise RuntimeError(outcome.summary)
    if isinstance(outcome.result, dict):
        for name in plan.outputs:
            if name in outcome.result:
                ctx.set_output(name, outcome.result[name])
    if outcome.stderr.strip():
        logger.info("scripts: node %s said: %s", ctx.node.id, outcome.stderr.strip()[-500:])


# --- script.decide -----------------------------------------------------------


async def plan_decide(ctx: Any) -> str:
    """A gate's plan IS its evaluation (as `ai.classify`'s is): the port the
    script named, or `unavailable` when it could not answer."""
    plan = await _resolve(ctx)
    ports = ports_for(ctx.node.params)
    if not plan.resolves:
        logger.info("scripts: decide node %s: %s", ctx.node.id, plan.detail)
        return UNAVAILABLE_PORT
    outcome = await _execute(ctx, plan)
    if not outcome.ok:
        logger.info("scripts: decide node %s failed: %s", ctx.node.id, outcome.summary)
        return UNAVAILABLE_PORT
    answer = str(outcome.result if not isinstance(outcome.result, dict) else outcome.result.get("port", "")).strip()
    if answer in ports and answer != UNAVAILABLE_PORT:
        return answer
    logger.info("scripts: decide node %s named %r, not one of its ports", ctx.node.id, answer)
    return UNAVAILABLE_PORT


RUN_NODE = AutomationNodeSpec(
    key=NODE_RUN,
    kind="action",
    label="Run a script",
    description=(
        "Run one of your Python scripts in the managed interpreter, with the items, "
        "the event and a Radd API client acting as this automation. The dict it "
        "returns becomes tokens downstream."
    ),
    group="Scripts",
    params_schema=RUN_SCHEMA,
    outputs_for=outputs_for,
    subject="item",
    arity="set",
    arity_options=("set", "item"),
    needs_items=False,
    permission=PERM_MANAGE,
    plan=plan_run,
    apply=apply_run,
    check=check_run,
)

DECIDE_NODE = AutomationNodeSpec(
    key=NODE_DECIDE,
    kind="gate",
    label="Decide with a script",
    description=(
        "Route the packet by what a Python script returns — the name of one of the "
        "ports you declare. A script that fails or answers something else takes "
        "the unavailable port."
    ),
    group="Scripts",
    params_schema=DECIDE_SCHEMA,
    ports_for=ports_for,
    subject="item",
    arity="set",
    needs_items=False,
    permission=PERM_MANAGE,
    plan=plan_decide,
    check=check_decide,
)
