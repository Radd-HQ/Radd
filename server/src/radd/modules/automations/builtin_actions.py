"""The built-in ACTION nodes, registered as `AutomationNodeSpec`s (RADD-1322).

Until this, built-ins were a separate path from plugin nodes: an `ActionType`
enum the executor mapped node types back into, arity and ports in side tables,
and a catalog that served only `contributed_nodes` while the SPA carried the
built-ins by hand. Spec 116 said they had moved onto the registry; they had
not. Now every action — `set_state` as much as `page.comment` — is one spec the
executor runs through ONE path: `plan` records what it would do (so the dry run
is free), `apply` runs inside the savepoint, the budget and the loop guard.

Twenty-eight specs share one planner and one applier: the per-action logic
still lives in `planning._plan` / `engine._apply_plan`, which is the actions'
own implementation, not a dispatch the executor has to know about.
"""

from __future__ import annotations

import uuid
from typing import Any

from radd.config import settings
from radd.kernel.specs import AutomationNodeSpec, OutputField

from .types import (
    ACTION_ARITY_CONFIGURABLE,
    ACTION_ARITY_DEFAULT,
    ACTION_TYPE_PREFIX,
    ActionType,
    NodeArity,
    NodePort,
)

#: Palette labels — what the SPA used to hardcode in `meta.ts`.
LABELS: dict[ActionType, str] = {
    ActionType.SET_STATE: "Set state",
    ActionType.SET_PRIORITY: "Set priority",
    ActionType.SET_ASSIGNEE: "Set assignee",
    ActionType.ASSIGN_ROUND_ROBIN: "Assign next from team",
    ActionType.SET_TEAM: "Set team",
    ActionType.ADD_LABEL: "Add label",
    ActionType.REMOVE_LABEL: "Remove label",
    ActionType.SET_CYCLE: "Set cycle",
    ActionType.SET_RELEASE: "Set release",
    ActionType.SET_CUSTOM_FIELD: "Set custom field",
    ActionType.ADD_COMMENT: "Add comment",
    ActionType.SET_PARENT: "Set parent",
    ActionType.SET_TYPE: "Set issue type",
    ActionType.SET_REPORTER: "Set reporter",
    ActionType.SET_DATES: "Set dates",
    ActionType.SET_ESTIMATE: "Set estimate",
    ActionType.SET_FLAG: "Flag / unflag",
    ActionType.SET_VISIBILITY: "Set visibility",
    ActionType.LINK_ITEM: "Link to issue",
    ActionType.ARCHIVE_ITEM: "Archive / restore",
    ActionType.ADD_WATCHER: "Add watcher",
    ActionType.ADD_PARTICIPANT: "Add participant",
    ActionType.MOVE_TO_PROJECT: "Move to project",
    ActionType.CREATE_ITEM: "Create issue",
    ActionType.SEND_WEBHOOK: "Send webhook",
    ActionType.POST_CHAT: "Post to chat",
    ActionType.NOTIFY_USER: "Notify user",
    ActionType.SEND_EMAIL: "Send email",
}

#: Params a fresh node needs to be valid enough to save — the action union
#: validates these, so an empty object would 422 on the first save.
DEFAULT_PARAMS: dict[ActionType, dict[str, Any]] = {
    ActionType.SET_STATE: {"state": ""},
    ActionType.SET_PRIORITY: {"priority": "normal"},
    ActionType.SET_ASSIGNEE: {"assignee": ""},
    ActionType.ASSIGN_ROUND_ROBIN: {"team": ""},
    ActionType.SET_TEAM: {"team": ""},
    ActionType.ADD_LABEL: {"label": ""},
    ActionType.REMOVE_LABEL: {"label": ""},
    ActionType.SET_CYCLE: {"cycle": ""},
    ActionType.SET_RELEASE: {"release": ""},
    ActionType.SET_CUSTOM_FIELD: {"key": "", "value": ""},
    ActionType.ADD_COMMENT: {"body": "", "visibility": "public"},
    ActionType.SET_PARENT: {"parent": ""},
    ActionType.SET_TYPE: {"type": ""},
    ActionType.SET_REPORTER: {"reporter": ""},
    ActionType.SET_DATES: {"start": "", "target": ""},
    ActionType.SET_ESTIMATE: {"points": ""},
    ActionType.SET_FLAG: {"flagged": True},
    ActionType.SET_VISIBILITY: {"visibility": "public"},
    ActionType.LINK_ITEM: {"target": "", "link_type": "relates"},
    ActionType.ARCHIVE_ITEM: {"archived": True},
    ActionType.ADD_WATCHER: {"user": "assignee"},
    ActionType.ADD_PARTICIPANT: {"user": ""},
    ActionType.MOVE_TO_PROJECT: {"project": ""},
    ActionType.CREATE_ITEM: {"project": "", "title": ""},
    ActionType.SEND_WEBHOOK: {"url": "https://"},
    ActionType.POST_CHAT: {"webhook_url": "https://", "message": ""},
    ActionType.NOTIFY_USER: {"user": "", "message": ""},
    ActionType.SEND_EMAIL: {"to": "reporter", "subject": "", "body": ""},
}

#: `create_item` is the one built-in producer: the new issue's key is what makes
#: "file a follow-up, then say which one on the original" expressible (spec 120).
_CREATED_OUTPUTS = (
    OutputField(name="key", label="Key", description="The new issue's key, e.g. TD-42."),
    OutputField(name="id", label="Id", description="Its uuid."),
    OutputField(name="url", label="URL", description="A link to it."),
)


def action_of(node_type: str) -> ActionType:
    return ActionType(node_type.removeprefix(ACTION_TYPE_PREFIX))


# --- the one planner and the one applier every built-in action shares --------

#: Per-NODE memo on `ctx.cache`: the items of the whole packet and their
#: `{{item.*}}` facts, fetched once rather than once per item — a per-item run
#: over 200 issues is 200 renders, not 800 queries (RADD-1265).
_LOADED = "builtin.loaded"


async def _loaded(ctx: Any):
    from .executor import _load
    from .planning import load_item_facts

    cached = ctx.cache.get(_LOADED)
    if cached is None:
        loaded = await _load(ctx.session, ctx.packet.item_ids)
        cached = (loaded, await load_item_facts(ctx.session, loaded))
        ctx.cache[_LOADED] = cached
    return cached


async def plan_action(ctx: Any):
    """Resolve one invocation — read-only. At SET arity `ctx.subject_ids` is the
    whole packet (one item → it is the target, so `{{item.key}}` resolves on an
    event-triggered run; several → no single target, `{{items.*}}` speaks); at
    ITEM arity it is the one item this invocation is for."""
    from .planning import _plan, items_ctx

    loaded, facts = await _loaded(ctx)
    wanted = set(ctx.subject_ids)
    scope = [(item, project) for item, project in loaded if item.id in wanted]
    item, project = scope[0] if len(scope) == 1 else (None, None)
    plan = await _plan(
        ctx.session,
        {"type": action_of(ctx.node.type).value, "params": ctx.node.params},
        item,
        project,
        ctx.actor,
        facts=ctx.packet.facts,
        rule_name=ctx.automation_name,
        items=items_ctx(scope, facts),
        variables=ctx.packet.vars,
        item_facts=facts.get(item.id) if item is not None else None,
    )
    plan.target = item
    return plan


async def apply_action(ctx: Any, plan) -> None:
    from .engine import _apply_plan

    made = await _apply_plan(ctx.session, plan, plan.target, ctx.actor, rule_name=ctx.automation_name)
    made_id: uuid.UUID | None = getattr(made, "id", None)
    if made_id is None:
        return
    ctx.add_created("item", made_id)
    key = str(getattr(made, "key", "") or "")
    ctx.set_output("id", made_id)
    ctx.set_output("key", key)
    ctx.set_output("url", f"{settings.app_base_url.rstrip('/')}/issues/{key}" if key else "")


async def _plan_entry(ctx: Any):
    # Late-bound through the module so a test can stand in for the planner.
    return await plan_action(ctx)


async def _apply_entry(ctx: Any, plan) -> None:
    await apply_action(ctx, plan)


def _check(action: ActionType):
    """Write-time validation: the action union type-checks the params (a pydantic
    `ValidationError` propagates as the 422 it always was), and a ROLE recipient
    needs per-item arity — `send_email` to `reporter` at set arity resolves no
    recipient and skip-logs on every run (RADD-918)."""

    def check(params: dict[str, Any]) -> None:
        from .email_action import is_role
        from .schemas import ActionAdapter
        from .types import ARITY_PARAM

        ActionAdapter.validate_python({"type": action.value, "params": params})
        if action in (ActionType.SEND_EMAIL, ActionType.NOTIFY_USER):
            target = str(params.get("to") or params.get("user") or "")
            arity = str(params.get(ARITY_PARAM) or ACTION_ARITY_DEFAULT[action].value)
            if is_role(target) and arity != NodeArity.ITEM.value:
                raise ValueError(
                    f"{target!r} is a property of one issue, so this action must run once per "
                    f"item — it would resolve no recipient otherwise. Name an address instead, "
                    f"or switch it to per item."
                )

    return check


def _spec(action: ActionType) -> AutomationNodeSpec:
    default = ACTION_ARITY_DEFAULT[action]
    creates = action is ActionType.CREATE_ITEM
    return AutomationNodeSpec(
        key=f"{ACTION_TYPE_PREFIX}{action.value}",
        kind="action",
        label=LABELS[action],
        group="Actions",
        keywords=f"{action.value} do apply",
        default_params=dict(DEFAULT_PARAMS[action]),
        ports=(NodePort.OUT.value, NodePort.CREATED.value) if creates else (NodePort.OUT.value,),
        outputs=_CREATED_OUTPUTS if creates else (),
        arity=default.value,
        arity_options=(
            (NodeArity.SET.value, NodeArity.ITEM.value) if action in ACTION_ARITY_CONFIGURABLE else ()
        ),
        # A SET action still fires on an empty packet ("nothing matched — tell
        # me"); an ITEM action with no items has nothing to do, which the
        # executor already knows from arity.
        needs_items=False,
        plan=_plan_entry,
        apply=_apply_entry,
        check=_check(action),
    )


ACTION_NODES: tuple[AutomationNodeSpec, ...] = tuple(_spec(action) for action in ActionType)

