import uuid
from collections.abc import Sequence
from datetime import date

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError
from radd.modules.auth import principals, service as auth
from radd.modules.auth.models import User
from radd.modules.auth.types import AuthEntity
from radd.modules.cycles import service as cycles_service
from radd.modules.itemtypes import service as itemtypes
from radd.modules.itemtypes.types import TypeEntity
from radd.modules.labels import service as labels_service
from radd.modules.projects.models import Project
from radd.modules.releases import service as releases_service
from radd.modules.releases.types import ReleaseEntity
from radd.modules.teams import service as teams
from radd.modules.teams.models import Team
from radd.modules.workflow import service as workflow
from radd.modules.workflow.models import State
from radd.modules.workflow.types import StateEntity

from ..enums import REQUIRED_PARENT_KIND, ItemEntity, ItemKind
from ..models import ItemLabel, WorkItem
from .queries import require_item


# --- relation validation ---


async def _resolve_state(
    session: AsyncSession, project: Project, state_id: uuid.UUID | None
) -> State:
    if state_id is None:
        return await workflow.default_state(session, project.id)
    state = await workflow.get_state(session, state_id)
    if state.project_id != project.id:
        raise ConflictError(StateEntity.STATE, reason=f"{state.name} belongs to another project")
    return state


async def _resolve_type(
    session: AsyncSession, project: Project, type_id: uuid.UUID | None
) -> uuid.UUID | None:
    """Validate a chosen issue type belongs to the project (spec 51). None = untyped."""
    if type_id is None:
        return None
    issue_type = await itemtypes.get_type(session, type_id)
    if issue_type.project_id != project.id:
        raise ConflictError(
            TypeEntity.ISSUE_TYPE, reason=f"{issue_type.name} belongs to another project"
        )
    return issue_type.id


async def _resolve_parent(
    session: AsyncSession, kind: ItemKind, parent_id: uuid.UUID | None
) -> None:
    """Enforce the hierarchy: epic ← issue ← subtask, max depth 3. Since spec 80
    the parent may live in ANOTHER PROJECT (spec 86: no boundary above that)."""
    required = REQUIRED_PARENT_KIND.get(kind)
    if parent_id is None:
        if kind == ItemKind.SUBTASK:
            raise ConflictError(ItemEntity.ITEM, reason=f"{kind} requires a parent {required}")
        return
    if required is None:
        raise ConflictError(ItemEntity.ITEM, reason=f"{kind} cannot have a parent")
    parent = await require_item(session, parent_id)
    if parent.kind != required:
        raise ConflictError(
            ItemEntity.ITEM, reason=f"{kind} parent must be of kind {required}, not {parent.kind}"
        )


async def _resolve_assignee(
    session: AsyncSession, user_id: uuid.UUID, *, allow_inactive: bool = False
) -> User:
    """Resolve an assignee/reporter, refusing a deactivated account.

    `allow_inactive` is the IMPORT escape hatch (project.manage-gated at the call
    site, like the `created_at` override). An import restates history: an issue
    really was assigned to, or reported by, someone who has since left, and
    refusing that would either lose the attribution or force their account to stay
    active — which is worse, because a departed person then shows up in every
    assignee picker. Deactivating a user never breaks EXISTING rows; it only stops
    new assignment, and a historical import is not new assignment.
    """
    user = await auth.get_user(session, user_id)
    if not user.active and not allow_inactive:
        raise ConflictError(AuthEntity.USER, reason=f"{user_id} is inactive")
    # Spec 121: Anyone / Signed-in users are grant subjects, never a person
    # an issue can belong to.
    principals.require_person(user, what="an assignee or reporter")
    return user


async def _resolve_team(session: AsyncSession, project: Project, team_id: uuid.UUID) -> Team:
    return await teams.get_team(session, team_id)


async def _resolve_cycle(session: AsyncSession, project: Project, cycle_id: uuid.UUID) -> None:
    await cycles_service.get_cycle(session, cycle_id)


async def _resolve_release(session: AsyncSession, project: Project, release_id: uuid.UUID) -> None:
    release = await releases_service.get_release(session, release_id)
    if release.project_id != project.id:
        raise ConflictError(ReleaseEntity.RELEASE, reason=f"{release_id} belongs to another project")


def _validate_dates(start: date | None, target: date | None) -> None:
    if start is not None and target is not None and target < start:
        raise ConflictError(ItemEntity.ITEM, reason="target_date must be on or after start_date")


async def _set_labels(
    session: AsyncSession,
    item: WorkItem,
    names: Sequence[str],
    actor_id: uuid.UUID,
) -> None:
    labels = await labels_service.resolve_labels(session, names, actor_id=actor_id)
    await session.execute(delete(ItemLabel).where(ItemLabel.item_id == item.id))
    session.add_all(ItemLabel(item_id=item.id, label_id=label.id) for label in labels)
    await session.flush()
