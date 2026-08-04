"""SLQ suggest (spec 12): live value sources per field.

Scope = the project when given, else the actor's readable projects (RADD-839)
for row-level data — item keys+titles and project keys. State/label/release/
type NAMES stay instance-wide vocabulary (the open-visibility default,
docs/modules.md). Everything flows through the owning modules' public service
functions; item keys are the one direct query (WorkItem is ours, Project
follows the service-layer precedent set by items/service.py).
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import String, cast, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.auth import service as auth
from radd.modules.cycles import service as cycles_service
from radd.modules.fields.models import FieldDefinition
from radd.modules.fields.types import SELECT_TYPES, FieldType
from radd.modules.labels import service as labels_service
from radd.modules.releases import service as releases_service
from radd.modules.teams import service as teams_service
from radd.modules.workflow import service as workflow
from radd.modules.workflow.types import StateCategory
from radd.modules.projects import service as projects_service
from radd.modules.projects.models import Project

from ..enums import ItemKind, Priority
from ..filters import NONE_LITERAL
from ..models import WorkItem
from .catalog import ME_LITERAL, SlqField
from .custom import BOOLEAN_WORDS
from .helpers import LIKE_ESCAPE, TODAY_LITERAL, escape_like

MAX_SUGGESTIONS = 20  # frozen response cap (spec 12)

# Sentinels lead their field's list (spec: "me, none, then active users").
TIER_SENTINEL = 0
TIER_ENTITY = 1

DATE_TEMPLATE = "YYYY-MM-DD"
ITEM_KEY_SEPARATOR = "-"

# Builtin fields whose value suggestions require a DB round-trip. Pure detection tests
# call with session=None to check context/replace_from over a value-position query; those
# fields no-op rather than crash (session is always real in production).
_DB_BACKED_FIELDS = frozenset(
    {
        SlqField.STATE,
        SlqField.ASSIGNEE,
        SlqField.REPORTER,
        SlqField.TEAM,
        SlqField.LABEL,
        SlqField.PROJECT,
        SlqField.KEY,
        SlqField.PARENT,
        SlqField.CYCLE,
        SlqField.PAST_CYCLE,
        SlqField.RELEASE,
        SlqField.BLOCKS,
        SlqField.BLOCKED,
        # Ancestor fields (spec 83) that reuse item-key/state/user sources.
        SlqField.EPIC,
        SlqField.EPIC_STATE,
        SlqField.EPIC_ASSIGNEE,
        SlqField.PARENT_STATE,
        SlqField.PARENT_ASSIGNEE,
        SlqField.TYPE,
    }
)


class SuggestDetail(StrEnum):
    """Fixed `detail` strings (entity values carry their field/key name instead)."""

    FIELD = "field"
    KEYWORD = "keyword"
    OPERATOR = "operator"
    CURRENT_USER = "current user"
    NO_VALUE = "no value"
    DATE_HINT = "date format hint"
    RELATIVE_DATE = "relative date (also today+3d / today-2w)"


@dataclass(frozen=True)
class Candidate:
    """A pre-ranking suggestion; filtering/quoting/limiting happen in suggest.py."""

    value: str
    label: str | None = None  # display text; defaults to value
    detail: str = ""
    tier: int = TIER_ENTITY
    literal: bool = True  # False = sentinel/keyword — inserted bare, never quoted
    insertable: bool = True  # False = format hint: insert stays "", exempt from filtering


@dataclass(frozen=True)
class SuggestScope:
    """Where value suggestions come from: the project when given, else the
    actor's readable projects (RADD-839 — item keys/titles and project keys
    complete only from projects the actor may read; None = trusted context).
    State/label/release/type NAMES stay instance-wide vocabulary."""

    project: Project | None = None
    readable_project_ids: frozenset[uuid.UUID] | None = None


def _me() -> Candidate:
    return Candidate(
        ME_LITERAL, detail=SuggestDetail.CURRENT_USER, tier=TIER_SENTINEL, literal=False
    )


def _none() -> Candidate:
    return Candidate(
        NONE_LITERAL, detail=SuggestDetail.NO_VALUE, tier=TIER_SENTINEL, literal=False
    )


def _date_hint() -> Candidate:
    return Candidate(DATE_TEMPLATE, detail=SuggestDetail.DATE_HINT, insertable=False)


def _today() -> Candidate:
    """Spec 69: the relative-date literal, leading its field's list like me/none."""
    return Candidate(
        TODAY_LITERAL, detail=SuggestDetail.RELATIVE_DATE, tier=TIER_SENTINEL, literal=False
    )


def _entities(names: list[str], field: SlqField) -> list[Candidate]:
    return [Candidate(name, detail=field.value) for name in names]


def _enum_candidates(enum_cls: type[StrEnum], field: SlqField) -> list[Candidate]:
    return [Candidate(member.value, detail=field.value, literal=False) for member in enum_cls]


async def value_candidates(
    session: AsyncSession,
    scope: SuggestScope,
    field: str,
    partial: str,
    definitions_by_key: Mapping[str, FieldDefinition],
) -> list[Candidate]:
    """The value source for one field. Unknown fields (and free-form types) yield
    no candidates — the context is still reported to the caller."""
    try:
        builtin = SlqField(field)
    except ValueError:
        definition = definitions_by_key.get(field)
        return [] if definition is None else _cf_candidates(definition)
    if session is None and builtin in _DB_BACKED_FIELDS:
        return []
    match builtin:
        # Ancestor sub-fields (spec 83) reuse the item-level sources; the
        # candidate detail carries the matched field name (epic.state, …).
        case SlqField.STATE | SlqField.EPIC_STATE | SlqField.PARENT_STATE:
            return _entities(await _state_names(session, scope), builtin)
        case SlqField.CATEGORY | SlqField.EPIC_CATEGORY | SlqField.PARENT_CATEGORY:
            return _enum_candidates(StateCategory, builtin)
        case SlqField.KIND:
            return _enum_candidates(ItemKind, builtin)
        case SlqField.PRIORITY | SlqField.EPIC_PRIORITY | SlqField.PARENT_PRIORITY:
            return _enum_candidates(Priority, builtin)
        case (
            SlqField.ASSIGNEE
            | SlqField.REPORTER
            | SlqField.EPIC_ASSIGNEE
            | SlqField.PARENT_ASSIGNEE
        ):
            return [_me(), _none()] + await _user_candidates(session)
        case SlqField.TEAM:
            teams = await teams_service.list_teams(session)
            return [_none()] + _entities([team.name for team in teams], builtin)
        case SlqField.TYPE:
            # Was the one entity field with no value source (found by the
            # spec-103 NL repair work) — distinct issue-type names, instance-wide.
            from radd.modules.itemtypes.models import IssueType

            names = (
                (await session.execute(select(IssueType.name).distinct().order_by(IssueType.name)))
                .scalars()
                .all()
            )
            return _entities(list(names), builtin)
        case SlqField.LABEL:
            labels = await labels_service.list_labels(session)
            return _entities([label.name for label in labels], builtin)
        case SlqField.PROJECT:
            projects = await projects_service.list_projects(session)
            if scope.readable_project_ids is not None:
                projects = [p for p in projects if p.id in scope.readable_project_ids]
            return _entities([project.key for project in projects], builtin)
        case SlqField.KEY:
            return await _item_key_candidates(session, scope, partial)
        case SlqField.PARENT | SlqField.EPIC:
            return [_none()] + await _item_key_candidates(session, scope, partial)
        case SlqField.BLOCKS | SlqField.BLOCKED:
            return await _item_key_candidates(session, scope, partial)
        case SlqField.CYCLE | SlqField.PAST_CYCLE:
            return [_none()] + _entities(await _cycle_names(session, scope), builtin)
        case SlqField.RELEASE:
            return [_none()] + _entities(await _release_versions(session, scope), builtin)
        case SlqField.CREATED | SlqField.UPDATED | SlqField.START | SlqField.TARGET:
            return [_today(), _date_hint()]
        case SlqField.FLAGGED | SlqField.STARRED:
            return [Candidate(word, literal=False) for word in BOOLEAN_WORDS]
    return []  # title / number: free-form


def _cf_candidates(definition: FieldDefinition) -> list[Candidate]:
    field_type = FieldType(definition.type)
    if field_type in SELECT_TYPES:
        return [Candidate(option, detail=definition.key) for option in definition.options or ()]
    if field_type is FieldType.BOOLEAN:
        return [Candidate(word, detail=definition.key, literal=False) for word in BOOLEAN_WORDS]
    if field_type is FieldType.DATE:
        return [_today(), _date_hint()]
    return []  # text/url/number/duration/user: free-form (context still reported)


async def _state_names(session: AsyncSession, scope: SuggestScope) -> list[str]:
    """Distinct state names in scope — the project's own, else across all projects."""
    projects = (
        [scope.project]
        if scope.project is not None
        else await projects_service.list_projects(session)
    )
    names: dict[str, None] = {}
    for project in projects:
        for state in await workflow.list_states(session, project.id):
            names.setdefault(state.name, None)
    return list(names)


async def _cycle_names(session: AsyncSession, scope: SuggestScope) -> list[str]:
    """Cycle names (cycles span projects; project scope doesn't narrow them)."""
    cycles = await cycles_service.list_cycles(session)
    return [cycle.name for cycle in cycles]


async def _release_versions(session: AsyncSession, scope: SuggestScope) -> list[str]:
    """Release versions in scope: the project's own, else deduped across projects."""
    projects = (
        [scope.project]
        if scope.project is not None
        else await projects_service.list_projects(session)
    )
    versions: dict[str, None] = {}
    for project in projects:
        for release in await releases_service.list_releases(session, project.id):
            versions.setdefault(release.version, None)
    return list(versions)


async def _user_candidates(session: AsyncSession) -> list[Candidate]:
    """Active users: insert email, label display name, detail email (spec 86 —
    the member floor is every active user, so the directory IS the candidate set)."""
    users = await auth.list_users(session, active=True)
    return [Candidate(user.email, label=user.name, detail=user.email) for user in users]


async def _item_key_candidates(
    session: AsyncSession, scope: SuggestScope, partial: str
) -> list[Candidate]:
    """Item keys (TD-12) matching the typed prefix, capped at the response limit."""
    key_column = Project.key + ITEM_KEY_SEPARATOR + cast(WorkItem.number, String)
    query = (
        select(Project.key, WorkItem.number, WorkItem.title)
        .join(Project, Project.id == WorkItem.project_id)
        .where(key_column.ilike(escape_like(partial) + "%", escape=LIKE_ESCAPE))
    )
    if scope.project is not None:
        query = query.where(WorkItem.project_id == scope.project.id)
    elif scope.readable_project_ids is not None:
        # RADD-839: keys + TITLES complete only from readable projects.
        query = query.where(WorkItem.project_id.in_(scope.readable_project_ids))
    query = query.order_by(Project.key, WorkItem.number).limit(MAX_SUGGESTIONS)
    return [
        Candidate(f"{key}{ITEM_KEY_SEPARATOR}{number}", detail=title)
        for key, number, title in (await session.execute(query)).all()
    ]
