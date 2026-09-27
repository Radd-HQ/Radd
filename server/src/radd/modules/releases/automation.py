"""The "Publish version and sweep" automation node (RADD-1310): what an
automation puts after a "<host>: release published" trigger. Calls
`pipeline.on_release_published`; `subject="project"` hands it the project the
event names (the repository's default project). The version is the event's
(tag minus a leading `v`) unless the node sets one — a literal or a template
(RADD-1324). Nothing here imports `automations`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from radd.kernel import OutputField
from radd.sdk import AutomationNodeKind, AutomationNodeSpec, NodeArity

PUBLISH_NODE_KEY = "release.publish"

PUBLISH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "project": {
            "type": "string",
            "title": "Project key — empty for the project the event names",
            "maxLength": 20,
        },
        "version": {
            "type": "string",
            "title": "Version — empty for the released version the event carries",
            "maxLength": 100,
        },
    },
}


@dataclass
class _PublishPlan:
    project_id: uuid.UUID | None
    version: str
    name: str
    notes: str
    detail: str
    resolves: bool = True


def _payload(ctx: Any) -> dict[str, Any]:
    facts = getattr(ctx.packet, "facts", None)
    payload = getattr(facts, "payload", None)
    return payload if isinstance(payload, dict) else {}


async def _project(ctx: Any):
    from radd.exceptions import NotFoundError
    from radd.modules.projects import service as projects

    key = str(ctx.node.params.get("project") or "").strip()
    if key:
        try:
            return await projects.get_by_key(ctx.session, key), key
        except NotFoundError:
            return None, key
    if not ctx.subject_ids:
        return None, ""
    return await projects.get_project(ctx.session, ctx.subject_ids[0]), ""


async def plan_publish(ctx: Any) -> _PublishPlan:
    from radd.modules.workflow import service as workflow

    from . import service as releases

    payload = _payload(ctx)
    # RADD-1324: the override is a template now — `{{payload.tag}}`, a node's
    # output — rendered like any action's text.
    override = (await ctx.render(str(ctx.node.params.get("version") or ""), line=True)).strip()
    # The event's name and notes describe the event's version; an override is a
    # different version, so it takes neither.
    version = override or str(payload.get("version") or "").strip()
    name = version if override else str(payload.get("name") or version)
    notes = "" if override else str(payload.get("notes") or "")
    project, key = await _project(ctx)
    if project is None:
        reason = f"no project {key!r}" if key else "the event names no project (map the repository to one, or set Project key)"
        return _PublishPlan(None, version, name, notes, f"release.publish: {reason}", False)
    if not version:
        return _PublishPlan(project.id, "", name, notes, "release.publish: no version — the event carries none and the node sets none", False)
    transitions = await workflow.release_transitions(ctx.session, project.id)
    if not transitions:
        # Recording the version is still worth doing; say what will not happen.
        moves = "nothing moves — the project has no transition that moves on release"
    else:
        from sqlalchemy import select
        from radd.modules.items.models import WorkItem
        candidates = list((await ctx.session.scalars(select(WorkItem.number).where(
            WorkItem.project_id == project.id,
            WorkItem.state_id.in_({transition.from_state_id for transition in transitions}),
        ).order_by(WorkItem.number))).all())
        keys = ", ".join(f"{project.key}-{number}" for number in candidates[:20])
        suffix = ", …" if len(candidates) > 20 else ""
        moves = f"{len(candidates)} candidate issue(s) across the project" + (f": {keys}{suffix}" if keys else "")
    existing = await releases.resolve_release(ctx.session, project.id, version)
    verb = "re-sweep" if existing is not None else "publish"
    return _PublishPlan(project.id, version, name, notes, f"release.publish: {verb} {project.key} {version}; {moves}")


async def apply_publish(ctx: Any, plan: _PublishPlan) -> None:
    from radd.modules.projects import service as projects

    from . import pipeline

    project = await projects.get_project(ctx.session, plan.project_id)
    # As the automation's actor (RADD-1315), not a hardcoded system user.
    release, moved = await pipeline.on_release_published(
        ctx.session, project, version=plan.version, name=plan.name, notes=plan.notes,
        actor_id=ctx.actor.id,
    )
    ctx.set_output("release_id", release.id)
    ctx.set_output("moved", moved)


PUBLISH_NODE = AutomationNodeSpec(
    key=PUBLISH_NODE_KEY,
    kind=AutomationNodeKind.ACTION.value,
    label="Publish version and sweep",
    description=(
        "Record the version as released in the project and move everything waiting for release "
        "into it, across the whole project, regardless of which commits the tag contains. Put it after a “release published” trigger; re-running it for the same version "
        "is harmless."
    ),
    group="Releases",
    params_schema=PUBLISH_SCHEMA,
    subject="project",
    arity=NodeArity.SET.value,
    needs_items=False,  # it needs a PROJECT, not an item — see `subject`
    permission="release.create",
    outputs=(
        OutputField("release_id", "Release id"),
        OutputField("moved", "Issues shipped"),
    ),
    plan=plan_publish,
    apply=apply_publish,
)
