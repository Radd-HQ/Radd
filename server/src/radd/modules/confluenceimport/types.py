"""Enums and pure value objects for the Confluence importer (spec 117).

Every string that names a behaviour, a state or a kind lives here as a `StrEnum`,
per rule 2 — including the ones that reach the wire, which is why renaming a
member is a data migration rather than a rename.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ConfluenceEntity(StrEnum):
    """Entity keys for `NotFoundError`/`ConflictError`."""

    CONFLUENCE = "confluence"
    CONNECTION = "confluence_connection"
    SNAPSHOT = "confluence_snapshot"
    PLAN = "confluence_plan"
    RUN = "confluence_run"


class ConfluenceAuthMode(StrEnum):
    PAT = "pat"  # Bearer — the Server/DC idiom
    BASIC = "basic"  # username + password, for instances with tokens disabled


class ConnectionSource(StrEnum):
    ENV = "env"  # seeded once from the environment
    USER = "user"


class ScopeKind(StrEnum):
    """What a snapshot selected.

    The three selections a migration actually asks for — "the whole space", "this
    section and everything under it", "these particular pages" — are ONE concept
    here rather than three code paths: `SUBTREE` and `PAGES` both resolve to a
    page-id set before the download starts, so the downloader has one input shape.
    """

    SPACE = "space"
    SUBTREE = "subtree"
    PAGES = "pages"


class SnapshotStage(StrEnum):
    """The download's progress. The snapshot ROW is the progress bar (spec 100)."""

    PENDING = "pending"
    SPACES = "spaces"
    TREE = "tree"
    BODIES = "bodies"
    VERSIONS = "versions"  # skipped unless the snapshot asked for history
    COMMENTS = "comments"
    RESTRICTIONS = "restrictions"
    ATTACHMENTS = "attachments"
    DONE = "done"
    FAILED = "failed"
    CANCELED = "canceled"


TERMINAL_SNAPSHOT_STAGES = frozenset(
    {SnapshotStage.DONE, SnapshotStage.FAILED, SnapshotStage.CANCELED}
)


class RunStage(StrEnum):
    """The import's progress.

    `BODIES` follows `PAGES` deliberately: a link can only be rewritten once its
    target's Radd id exists, so the tree is created first and converted second.
    `ATTACHMENTS` precedes `COMMENTS` for the same reason — a comment can embed an
    image.
    """

    PENDING = "pending"
    PROVISION = "provision"
    SPACES = "spaces"
    PAGES = "pages"
    BODIES = "bodies"
    ATTACHMENTS = "attachments"
    COMMENTS = "comments"
    RESTRICTIONS = "restrictions"
    VERSIONS = "versions"
    RELINK = "relink"
    DONE = "done"
    FAILED = "failed"
    CANCELED = "canceled"


TERMINAL_RUN_STAGES = frozenset({RunStage.DONE, RunStage.FAILED, RunStage.CANCELED})


class RunKind(StrEnum):
    IMPORT = "import"
    ROLLBACK = "rollback"


class ProblemKind(StrEnum):
    """Why one page did not import cleanly."""

    MACRO = "macro"  # a macro with no mapping
    USER = "user"  # an author who could not be resolved
    RESTRICTION = "restriction"  # a principal who could not be resolved
    PARENT = "parent"  # an ancestor outside the selection
    LINK = "link"  # a link target not imported (yet)
    ATTACHMENT = "attachment"
    PERMISSION = "permission"  # fidelity degraded — see _check_fidelity
    CONVERT = "convert"
    FAILED = "failed"


class MacroAction(StrEnum):
    """What the converter does with one macro name.

    The default for anything unmapped is `UNSUPPORTED`, never `STRIP`: a page whose
    content WAS the macro must not import as an empty page. An unsupported block
    keeps the macro's name and parameters, so building the renderer later upgrades
    every instance in place on the next conversion.
    """

    NATIVE = "native"  # plain markdown — a code fence, a task list
    EXTENSION = "extension"  # a radd:<name> fence
    UNSUPPORTED = "unsupported"  # a radd:unsupported-macro card
    STRIP = "strip"  # genuine chrome, dropped
    IGNORE = "ignore"  # not present in this corpus (count 0)


class MappingSection(StrEnum):
    """The plan's tables. A `Problem` carries one of these plus the key inside it,
    which is what lets a run report offer "Fix in Macros → drawio" instead of
    leaving someone to guess which control caused the failure."""

    SPACES = "spaces"
    MACROS = "macros"
    USERS = "users"
    GROUPS = "groups"
    LABELS = "labels"
    JIRA_LINKS = "jira_links"


class UnresolvedPrincipal(StrEnum):
    """What to do with a restriction principal that does not resolve.

    `FAIL` is the default and the only safe one: importing a restricted page open
    is a data leak, and it is the failure nobody notices, because the page looks
    perfectly fine.
    """

    FAIL = "fail"
    MAP_TO = "map_to"  # every unresolved principal → one named subject


@dataclass(frozen=True, slots=True)
class ConfluenceCreds:
    """One connection, as a thread-safe value.

    REST calls are synchronous and run in `asyncio.to_thread`, so they must never
    hold a SQLAlchemy row — the row belongs to a session on another thread.
    """

    base_url: str
    auth_mode: ConfluenceAuthMode
    credential: str
    username: str = ""
    verify_ssl: bool = True
    timeout_seconds: float = 30.0


@dataclass(frozen=True, slots=True)
class ConfluenceSpace:
    key: str
    name: str
    id: str = ""
    description: str = ""
    homepage_id: str = ""


@dataclass(frozen=True, slots=True)
class ConfluencePage:
    """One page's metadata, without its body — what the `tree` stage collects."""

    id: str
    title: str
    space_key: str
    parent_id: str | None = None
    position: int = 0
    version: int = 1
    created_at: str = ""
    updated_at: str = ""
    author: str = ""
    author_email: str = ""
    labels: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Problem:
    """One thing that went wrong, addressed back to the control that fixes it."""

    kind: ProblemKind
    message: str
    subject: str = ""
    detail: str = ""
    section: MappingSection | None = None
    mapping_key: str = ""

    def as_dict(self) -> dict:
        return {
            "kind": self.kind.value,
            "message": self.message,
            "subject": self.subject,
            "detail": self.detail,
            "section": self.section.value if self.section else None,
            "mapping_key": self.mapping_key,
        }


@dataclass(slots=True)
class Scope:
    """What to download. Resolved to `page_ids` before the download begins."""

    kind: ScopeKind
    space_key: str = ""
    root_page_id: str = ""
    page_ids: list[str] = field(default_factory=list)
    max_depth: int | None = None

    def as_dict(self) -> dict:
        return {
            "kind": self.kind.value,
            "space_key": self.space_key,
            "root_page_id": self.root_page_id,
            "page_ids": list(self.page_ids),
            "max_depth": self.max_depth,
        }

    @classmethod
    def from_dict(cls, raw: dict | None) -> "Scope":
        raw = raw or {}
        return cls(
            kind=ScopeKind(raw.get("kind", ScopeKind.SPACE.value)),
            space_key=raw.get("space_key", ""),
            root_page_id=raw.get("root_page_id", ""),
            page_ids=list(raw.get("page_ids") or []),
            max_depth=raw.get("max_depth"),
        )
