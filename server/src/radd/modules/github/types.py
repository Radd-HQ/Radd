"""Wire constants for the GitHub connector (RADD-1129)."""

from enum import StrEnum


class GithubEventKind(StrEnum):
    """Values of the X-GitHub-Event header this connector handles.

    Anything else is a deliberate no-op: a repository may be configured to send
    every event, and an unknown one is not an error.
    """

    PING = "ping"
    PUSH = "push"
    PULL_REQUEST = "pull_request"
    # `published` fires the release-published trigger (RADD-1309).
    RELEASE = "release"
    # CI state for a ref, from any of the three shapes GitHub emits.
    CHECK_RUN = "check_run"
    CHECK_SUITE = "check_suite"
    WORKFLOW_RUN = "workflow_run"
    # Branch/tag lifecycle — accepted, not acted on (parity with forgejo).
    CREATE = "create"
    DELETE = "delete"
    # RADD-1261: the `/spend` convention rides PR comments and reviews.
    ISSUE_COMMENT = "issue_comment"
    PULL_REQUEST_REVIEW_COMMENT = "pull_request_review_comment"
    PULL_REQUEST_REVIEW = "pull_request_review"


class CommentAction(StrEnum):
    """`action` values of the comment webhooks this connector reads."""

    CREATED = "created"
    EDITED = "edited"
    DELETED = "deleted"
    # pull_request_review sends `submitted`/`edited`/`dismissed`.
    SUBMITTED = "submitted"


class PrStatus(StrEnum):
    """Status recorded on the pull_request-type vcs link (open/merged/closed)."""

    OPEN = "open"
    MERGED = "merged"
    CLOSED = "closed"


class CiState(StrEnum):
    """Latest run state for a ref. Not a check-run history — the panel answers
    "is this green", and a ref with two workflows shows the last to report."""

    SUCCESS = "success"
    FAILURE = "failure"
    RUNNING = "running"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class GithubTrigger(StrEnum):
    """RADD-1309: GitHub's OWN automation triggers. The connector links refs and
    does nothing else; what a merge or a published release should cause is an
    automation. Registered by this plugin, so disabling GitHub removes them."""

    PR_OPENED = "github.pull_request.opened"
    PR_MERGED = "github.pull_request.merged"
    PR_CLOSED = "github.pull_request.closed"
    PUSHED = "github.push"
    CI_COMPLETED = "github.ci.completed"
    RELEASE_PUBLISHED = "github.release.published"


class PrAction(StrEnum):
    """`action` values of a pull_request delivery that fire a trigger. A merge
    arrives as `closed` with `merged: true`; `edited`/`synchronize` fire nothing."""

    OPENED = "opened"
    REOPENED = "reopened"
    CLOSED = "closed"


class ReleaseAction(StrEnum):
    """Only `published` publishes — a draft, an edit or a deletion must not."""

    PUBLISHED = "published"


class GithubEvent(StrEnum):
    """Spec 123: connection + repository administration, audited with a diff.
    Tokens and webhook secrets appear only as "changed". Not triggers."""

    CONNECTION_CREATED = "github_connection.created"
    CONNECTION_UPDATED = "github_connection.updated"
    CONNECTION_DELETED = "github_connection.deleted"
    REPO_CREATED = "github_repo.created"
    REPO_UPDATED = "github_repo.updated"
    REPO_DELETED = "github_repo.deleted"


class GithubEntity(StrEnum):
    """Entity names for NotFound/Conflict errors."""

    CONNECTION = "github_connection"
    REPO = "github_repo"


#: github.com's web host; anything else is GitHub Enterprise Server, whose API
#: lives under `<host>/api/v3`.
GITHUB_COM = "https://github.com"
GITHUB_COM_API = "https://api.github.com"
