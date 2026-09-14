from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING
import uuid

if TYPE_CHECKING:
    from .models import Project


class ProjectEvent(StrEnum):
    PROJECT_CREATED = "project.created"
    #: RADD-1009: name/description edited (`changes` in the payload; the key
    #: never changes, so it is never in there).
    PROJECT_UPDATED = "project.updated"
    #: RADD-1174: the row is gone. Emitted BEFORE the delete so the subject ref
    #: resolves; the payload carries the key, the name and what went with it.
    PROJECT_DELETED = "project.deleted"


class ProjectEntity(StrEnum):
    PROJECT = "project"


class ProjectHook(StrEnum):
    """In-transaction hook points this module dispatches (RADD-1174), named for
    the MOMENT like `ItemHook`. `project.created` seeds through the same
    registry; these are its mirror image for teardown.

    `projects` cannot know which modules hang rows off a project — comments and
    attachments key to a polymorphic parent, settings and notification rules
    carry a bare `scope_id`, and a plugin may have declared anything — so it
    DISPATCHES and every owner subscribes. The `ProjectPurgeSpec` registry
    covers the tables a plain `DELETE … WHERE project_id` can reach; these hooks
    cover everything it cannot.
    """

    #: Before anything is destroyed: report what of yours dies (`counts`) and
    #: what must stop the deletion outright (`blockers`). Read-only by contract.
    INSPECTING = "project.inspecting"
    #: The project is going. Remove what the database cannot cascade. A handler
    #: that raises aborts the whole deletion — nothing is half-deleted.
    DELETING = "project.deleting"


@dataclass(frozen=True)
class Blocker:
    """Something that makes the deletion unsafe, named so the person can go and
    fix it: `kind` is the owner's vocabulary (`mail_source`), `label` is what
    the UI prints, `hint` says where to go."""

    kind: str
    id: str
    label: str
    hint: str = ""


@dataclass
class ProjectInspection:
    """The subject of `ProjectHook.INSPECTING` — a mutable ledger the handlers
    fill in. `counts` keys are the owner's nouns (`items`, `comments`,
    `worklog_seconds`); the SPA renders what it recognises and ignores the rest,
    so a plugin's count degrades to nothing rather than to an error."""

    project: "Project"
    counts: dict[str, int] = field(default_factory=dict)
    blockers: list[Blocker] = field(default_factory=list)

    def add(self, key: str, count: int | None) -> None:
        if count:
            self.counts[key] = self.counts.get(key, 0) + int(count)


@dataclass(frozen=True)
class ProjectDeleting:
    """The subject of `ProjectHook.DELETING`. The actor rides along for the
    handlers that emit or that must clear per-person state."""

    project: "Project"
    actor_id: uuid.UUID | None = None
