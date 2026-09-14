"""Wire constants for the Forgejo/Gitea connector (specs 47, 111)."""

from enum import StrEnum


class ForgejoEventKind(StrEnum):
    """Values of the X-Forgejo-Event / X-Gitea-Event header this connector handles.

    Anything else is a deliberate no-op: a host may be configured to send every
    event, and an unknown one is not an error.
    """

    PUSH = "push"
    PULL_REQUEST = "pull_request"
    # Spec 111 — consumed by the release pipeline (spec 112).
    RELEASE = "release"
    # Branch/tag lifecycle: a deleted branch's link is marked stale rather than
    # left pointing at a ref that no longer exists.
    CREATE = "create"
    DELETE = "delete"
    # Forgejo Actions, where the host emits them.
    WORKFLOW_RUN = "workflow_run"
    WORKFLOW_JOB = "workflow_job"


class PrStatus(StrEnum):
    """Status recorded on the merge_request-type vcs link (spec 47: open/merged/closed)."""

    OPEN = "open"
    MERGED = "merged"
    CLOSED = "closed"


class CiState(StrEnum):
    """Latest run state for a ref (spec 111). Not a check-run history — the panel
    answers "is this green", and a branch with two workflows shows the last to report."""

    SUCCESS = "success"
    FAILURE = "failure"
    RUNNING = "running"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class ForgejoEvent(StrEnum):
    """Spec 123: connection + repository administration, audited with a diff.
    Tokens and webhook secrets appear only as "changed". Not triggers."""

    CONNECTION_CREATED = "forgejo_connection.created"
    CONNECTION_UPDATED = "forgejo_connection.updated"
    CONNECTION_DELETED = "forgejo_connection.deleted"
    REPO_CREATED = "forgejo_repo.created"
    REPO_UPDATED = "forgejo_repo.updated"
    REPO_DELETED = "forgejo_repo.deleted"


class ForgejoEntity(StrEnum):
    """Entity names for NotFound/Conflict errors and events."""

    CONNECTION = "forgejo_connection"
    REPO = "forgejo_repo"
