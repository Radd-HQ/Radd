"""Wire constants for the GitLab connector (RADD-1253, rebuilding spec 31)."""

from enum import StrEnum


class GitlabEventKind(StrEnum):
    """Values of `object_kind` (and the `X-Gitlab-Event` header, normalised) this
    connector reads. Anything else is a deliberate no-op — a project hook may be
    configured to send every event, and an unknown one is not an error."""

    PUSH = "push"
    TAG_PUSH = "tag_push"
    MERGE_REQUEST = "merge_request"
    # RADD-1255 will read these for CI state and deployment markers.
    PIPELINE = "pipeline"
    DEPLOYMENT = "deployment"
    # RADD-1256 will read these for the release trigger.
    RELEASE = "release"
    NOTE = "note"
    BUILD = "build"


class MrStatus(StrEnum):
    """Status recorded on the merge_request-type vcs link."""

    OPEN = "open"
    MERGED = "merged"
    CLOSED = "closed"


class GitlabEvent(StrEnum):
    """Spec 123: connection + repository administration, audited with a diff.
    Tokens and webhook secrets appear only as "changed". Not triggers."""

    CONNECTION_CREATED = "gitlab_connection.created"
    CONNECTION_UPDATED = "gitlab_connection.updated"
    CONNECTION_DELETED = "gitlab_connection.deleted"
    REPO_CREATED = "gitlab_repo.created"
    REPO_UPDATED = "gitlab_repo.updated"
    REPO_DELETED = "gitlab_repo.deleted"


class GitlabEntity(StrEnum):
    """Entity names for NotFound/Conflict errors."""

    CONNECTION = "gitlab_connection"
    REPO = "gitlab_repo"


#: gitlab.com's web host; a self-managed instance is any other base URL. Both
#: serve REST under `/api/v4` and GraphQL under `/api/graphql`.
GITLAB_COM = "https://gitlab.com"
