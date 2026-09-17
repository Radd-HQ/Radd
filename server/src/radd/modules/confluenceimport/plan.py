"""The plan: profiling, the macro census, and the six mapping tables (spec 117).

This is the step that turns "Confluence has hundreds of macros" into a handful of
decisions somebody can actually make. Jira's 337 fields became 14 decisions
because the profile said which 14 mattered; a decade of Confluence is the same
problem, and the answer is the same — COUNT first, then decide.

Profiling reads only the snapshot cache. It is therefore free to re-run, which is
what makes "fix a mapping and try again" a loop rather than a download.
"""

from __future__ import annotations

import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import NotFoundError

from .models import ConfluencePlan, ConfluenceSnapshotComment, ConfluenceSnapshotPage
from .schemas import (
    GroupMapping,
    JiraLinkMapping,
    LabelMapping,
    MacroMapping,
    PlanCreate,
    PlanMappings,
    PlanOptions,
    PlanProblem,
    PlanUpdate,
    SpaceMapping,
    UserMapping,
)
from .restrictions import principals_of
from .snapshot import service as snapshot_service
from .storage.macros import BUILTIN_MACROS
from .types import (
    ConfluenceEntity,
    GroupAction,
    UserAction,
    MacroAction,
    MappingSection,
    SpaceAction,
    UnresolvedPrincipal,
)

#: `<ac:structured-macro … ac:name="foo">` — the census's whole parser. A regex
#: rather than a tree walk because this runs over every cached body and only ever
#: needs the name; building a tree per page to read one attribute would make
#: profiling a large space noticeably slower for no extra information.
_MACRO_RE = re.compile(r'<ac:structured-macro[^>]*\bac:name="([^"]+)"')
#: Matches BOTH mention forms; the key is resolved to a name via the
#: snapshot's people catalog, so the mapping row is readable either way.
_USER_RE = re.compile(r'<ri:user\s+ri:(?:username|userkey)="([^"]+)"')
_JIRA_KEY_RE = re.compile(r'<ac:parameter\s+ac:name="key">([A-Z][A-Z0-9_]+)-\d+</ac:parameter>')


async def get_plan(session: AsyncSession, plan_id: uuid.UUID) -> ConfluencePlan:
    plan = await session.get(ConfluencePlan, plan_id)
    if plan is None:
        raise NotFoundError(ConfluenceEntity.PLAN, plan_id)
    return plan


def mappings_of(plan: ConfluencePlan) -> PlanMappings:
    return PlanMappings.model_validate(plan.mappings or {})


def options_of(plan: ConfluencePlan) -> PlanOptions:
    return PlanOptions.model_validate(plan.options or {})


# --- profiling ----------------------------------------------------------------


async def profile(session: AsyncSession, snapshot_id: uuid.UUID) -> PlanMappings:
    """Stream the cache and count everything a decision could hang on."""
    snapshot = await snapshot_service.get_snapshot(session, snapshot_id)
    # Resolved at download time — see `_people_catalog`. Without it the People
    # table listed opaque 32-char user keys, which nobody can map by hand.
    directory: dict[str, dict] = (snapshot.catalogs or {}).get("users") or {}
    rows = list(
        (
            await session.execute(
                select(ConfluenceSnapshotPage).where(
                    ConfluenceSnapshotPage.snapshot_id == snapshot_id
                )
            )
        ).scalars()
    )
    comments = list(
        (
            await session.execute(
                select(ConfluenceSnapshotComment).where(
                    ConfluenceSnapshotComment.snapshot_id == snapshot_id
                )
            )
        ).scalars()
    )

    macros: dict[str, int] = {}
    macro_sample: dict[str, str] = {}
    spaces: dict[str, int] = {}
    users: dict[str, int] = {}
    labels: dict[str, int] = {}
    jira_projects: dict[str, int] = {}
    principals: dict[str, int] = {}

    for row in rows:
        spaces[row.space_key] = spaces.get(row.space_key, 0) + 1
        for label in row.labels or []:
            labels[label] = labels.get(label, 0) + 1
        for name in _MACRO_RE.findall(row.body or ""):
            macros[name] = macros.get(name, 0) + 1
            macro_sample.setdefault(name, row.title)
        for username in _USER_RE.findall(row.body or ""):
            users[username] = users.get(username, 0) + 1
        for project_key in _JIRA_KEY_RE.findall(row.body or ""):
            jira_projects[project_key] = jira_projects.get(project_key, 0) + 1
        for principal in principals_of(row.restrictions or {}):
            principals[principal] = principals.get(principal, 0) + 1

    for comment in comments:
        if comment.author:
            users[comment.author] = users.get(comment.author, 0) + 1

    return PlanMappings(
        spaces=[
            SpaceMapping(key=key, name=key, count=count, action=SpaceAction.CREATE)
            for key, count in sorted(spaces.items(), key=lambda kv: -kv[1])
        ],
        macros=_macro_rows(macros, macro_sample),
        users=[
            UserMapping(
                username=name,
                display_name=(directory.get(name) or {}).get("display_name", ""),
                email=(directory.get(name) or {}).get("email", ""),
                count=count,
            )
            for name, count in sorted(users.items(), key=lambda kv: -kv[1])
        ],
        groups=[
            GroupMapping(name=name, count=count, action=GroupAction.IDENTITY)
            for name, count in sorted(principals.items(), key=lambda kv: -kv[1])
        ],
        labels=[
            LabelMapping(name=name, count=count)
            for name, count in sorted(labels.items(), key=lambda kv: -kv[1])
        ],
        jira_links=[
            JiraLinkMapping(project_key=key, count=count)
            for key, count in sorted(jira_projects.items(), key=lambda kv: -kv[1])
        ],
    )


def _macro_rows(counts: dict[str, int], sample: dict[str, str]) -> list[MacroMapping]:
    """The census. Every macro FOUND, ranked by use, plus a count-0 tail for the
    ones Radd can already render — so the table doubles as the list of what is
    supported, and an admin can see a mapping exists before needing it."""
    rows: list[MacroMapping] = []
    for name, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        spec = BUILTIN_MACROS.get(name)
        rows.append(
            MacroMapping(
                name=name,
                count=count,
                action=spec.action if spec else MacroAction.UNSUPPORTED,
                extension=spec.extension if spec else "",
                sample_page=sample.get(name, ""),
                reason=(spec.note if spec else "no mapping — imported as a card"),
            )
        )
    for name, spec in sorted(BUILTIN_MACROS.items()):
        if name in counts:
            continue
        # Count 0: collapsed and ignored by default, the spec-100 treatment.
        rows.append(
            MacroMapping(
                name=name, count=0, action=MacroAction.IGNORE,
                extension=spec.extension, reason=spec.note or "not used in this snapshot",
            )
        )
    return rows


# --- CRUD ---------------------------------------------------------------------


async def create_plan(
    session: AsyncSession, data: PlanCreate
) -> ConfluencePlan:
    await snapshot_service.require_complete(session, data.snapshot_id)
    mappings = await profile(session, data.snapshot_id)
    plan = ConfluencePlan(
        name=data.name,
        snapshot_id=data.snapshot_id,
        mappings=mappings.model_dump(mode="json"),
        options=PlanOptions().model_dump(mode="json"),
    )
    session.add(plan)
    await session.flush()
    return plan


async def update_plan(
    session: AsyncSession, plan_id: uuid.UUID, data: PlanUpdate
) -> ConfluencePlan:
    plan = await get_plan(session, plan_id)
    if data.name is not None:
        plan.name = data.name
    if data.mappings is not None:
        plan.mappings = data.mappings.model_dump(mode="json")
    if data.options is not None:
        plan.options = data.options.model_dump(mode="json")
    await session.flush()
    return plan


async def validate_plan(session: AsyncSession, plan_id: uuid.UUID) -> list[PlanProblem]:
    """Everything that would make a run misbehave, addressed to its own control."""
    plan = await get_plan(session, plan_id)
    mappings = mappings_of(plan)
    options = options_of(plan)
    problems: list[PlanProblem] = []

    if not [s for s in mappings.spaces if s.action is not SpaceAction.IGNORE]:
        problems.append(PlanProblem(
            section=MappingSection.SPACES, subject="",
            message="every space is ignored — this run would import nothing",
        ))
    for space in mappings.spaces:
        if space.action is SpaceAction.MAP and space.space_id is None:
            problems.append(PlanProblem(
                section=MappingSection.SPACES, subject=space.key,
                message="mapped to an existing space, but no space is chosen",
            ))
    for group in mappings.groups:
        if group.action is GroupAction.MAP and bool(group.group_id) == bool(group.team_id):
            problems.append(PlanProblem(section=MappingSection.GROUPS, subject=group.name,
                message="choose exactly one destination group or team"))
    from radd.modules.pages import spaces
    from radd.modules.groups import service as groups
    from radd.modules.teams import service as teams
    from radd.modules.auth.models import User
    from radd.kernel.registry import registries
    for space in mappings.spaces:
        if space.action is SpaceAction.MAP and space.space_id:
            try:
                await spaces.get_space(session, space.space_id)
            except NotFoundError:
                problems.append(PlanProblem(section=MappingSection.SPACES, subject=space.key, message="chosen space no longer exists"))
    for user in mappings.users:
        if user.action is not UserAction.IGNORE and user.user_id and await session.get(User, user.user_id) is None:
            problems.append(PlanProblem(section=MappingSection.USERS, subject=user.username, message="chosen account no longer exists"))
    destinations = [(g.name, g.group_id, g.team_id) for g in mappings.groups if g.action is GroupAction.MAP]
    if options.unresolved_principal is UnresolvedPrincipal.MAP_TO:
        destinations.append(("Unresolved principals", options.unresolved_group_id, options.unresolved_team_id))
    for subject, group_id, team_id in destinations:
        try:
            if group_id:
                await groups.get_group(session, group_id)
            if team_id:
                await teams.get_team(session, team_id)
        except NotFoundError:
            problems.append(PlanProblem(section=MappingSection.GROUPS, subject=subject, message="chosen permission destination no longer exists"))
    for macro in mappings.macros:
        if macro.action is MacroAction.EXTENSION and macro.extension and macro.extension not in registries.page_extensions:
            problems.append(PlanProblem(section=MappingSection.MACROS, subject=macro.name, message="chosen page renderer is not installed"))
        if macro.action is MacroAction.EXTENSION and not macro.extension:
            problems.append(PlanProblem(
                section=MappingSection.MACROS, subject=macro.name,
                message="set to render as an extension, but no extension is named",
            ))
    # The one that is a data leak rather than a nuisance.
    if options.import_restrictions and options.unresolved_principal is UnresolvedPrincipal.MAP_TO:
        if options.unresolved_group_id is None and options.unresolved_team_id is None:
            problems.append(PlanProblem(
                section=MappingSection.GROUPS, subject="",
                message="unresolved principals are set to map to a subject, "
                        "but no group or team is chosen",
            ))
    return problems


async def list_plans(session: AsyncSession) -> list[ConfluencePlan]:
    result = await session.execute(select(ConfluencePlan).order_by(ConfluencePlan.name))
    return list(result.scalars())


async def delete_plan(session: AsyncSession, plan_id: uuid.UUID) -> None:
    plan = await get_plan(session, plan_id)
    await session.delete(plan)
    await session.flush()
