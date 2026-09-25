"""Wire constants for the GitLab connector (RADD-1253, rebuilding spec 31)."""

from enum import StrEnum


class GitlabEventKind(StrEnum):
    """Values of `object_kind` (and the `X-Gitlab-Event` header, normalised) this
    connector reads. Anything else is a deliberate no-op — a project hook may be
    configured to send every event, and an unknown one is not an error."""

    PUSH = "push"
    TAG_PUSH = "tag_push"
    MERGE_REQUEST = "merge_request"
    # RADD-1255: CI state + the CI trigger, and the deployment trigger.
    PIPELINE = "pipeline"
    DEPLOYMENT = "deployment"
    # RADD-1309: `create` fires the release-published trigger.
    RELEASE = "release"
    NOTE = "note"
    BUILD = "build"


class MrStatus(StrEnum):
    """Status recorded on the merge_request-type vcs link."""

    OPEN = "open"
    MERGED = "merged"
    CLOSED = "closed"


class GitlabTrigger(StrEnum):
    """RADD-1309: GitLab's OWN automation triggers. The connector links refs and
    does nothing else; what a merge or a release should cause is an automation.
    Registered by this plugin, so disabling GitLab removes them from the palette."""

    MR_OPENED = "gitlab.merge_request.opened"
    MR_MERGED = "gitlab.merge_request.merged"
    MR_CLOSED = "gitlab.merge_request.closed"
    MR_UPDATED = "gitlab.merge_request.updated"  # RADD-1330
    # RADD-1255: a pipeline finished for a ref an issue is linked to, and a
    # deployment of such a ref finished (success, failed or canceled).
    CI_COMPLETED = "gitlab.ci.completed"
    DEPLOYMENT_FINISHED = "gitlab.deployment.finished"
    PUSHED = "gitlab.push"
    RELEASE_PUBLISHED = "gitlab.release.published"


class MrAction(StrEnum):
    """`object_attributes.action` values of a merge_request delivery that fire a
    trigger. `update` fires "updated" (RADD-1330); `approved` and the rest fire nothing."""

    OPEN = "open"
    REOPEN = "reopen"
    MERGE = "merge"
    CLOSE = "close"
    UPDATE = "update"


class ReleaseAction(StrEnum):
    """`action` of a release delivery; only `create` publishes."""

    CREATE = "create"


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


#: RADD-1255: GitLab pipeline `status` → the ref's CI state (the vocabulary the
#: GitHub/Forgejo badges use). `manual`/`scheduled` wait on a person or a clock.
PIPELINE_STATES: dict[str, str] = {
    "success": "success",
    "failed": "failure",
    "canceled": "cancelled",
    "skipped": "cancelled",
    "running": "running",
    "pending": "running",
    "created": "running",
    "preparing": "running",
    "waiting_for_resource": "running",
    "manual": "unknown",
    "scheduled": "unknown",
}

#: A deployment `status` that is an OUTCOME — the ones that fire the trigger.
DEPLOYMENT_OUTCOMES: frozenset[str] = frozenset({"success", "failed", "canceled"})

