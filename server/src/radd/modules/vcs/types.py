from enum import StrEnum


class VcsRefType(StrEnum):
    BRANCH = "branch"
    COMMIT = "commit"
    MERGE_REQUEST = "merge_request"
    PULL_REQUEST = "pull_request"


class VcsProvider(StrEnum):
    MANUAL = "manual"
    GITLAB = "gitlab"
    GITHUB = "github"
    FORGEJO = "forgejo"


class VcsEvent(StrEnum):
    LINKED = "vcs.linked"
    UPDATED = "vcs.updated"
    UNLINKED = "vcs.unlinked"


class VcsEntity(StrEnum):
    VCS_LINK = "vcs_link"
    USER_LINK = "vcs_user_link"


class RefStatus(StrEnum):
    """Status recorded on a merge/pull-request link."""

    OPEN = "open"
    MERGED = "merged"
    CLOSED = "closed"


class VcsMatchedBy(StrEnum):
    """How a provider account was tied to a Radd user (RADD-1258)."""

    EMAIL = "email"
    MANUAL = "manual"


class VcsUserLinkEvent(StrEnum):
    """Spec 123: identity-map administration is audited; not a trigger."""

    CREATED = "vcs_user_link.created"
    DELETED = "vcs_user_link.deleted"


class VcsSocket(StrEnum):
    """The socket a code-host connector provides its `ConnectorSpec` on (RADD-1435).
    vcs reads it for what is loaded NOW, so a disabled connector's tab goes too."""

    CONNECTOR = "vcs_connector"


class DeliveryCredential(StrEnum):
    """How a host authenticates a webhook delivery — what a refusal names."""

    SIGNATURE = "signature"  # an HMAC of the raw body (Forgejo, GitHub)
    TOKEN = "token"  # the secret echoed back verbatim (GitLab)


class ConnectorSetting(StrEnum):
    """A connector's `config.Settings` keys, named `<provider>_<key>` (`ConnectorSpec.setting`)."""

    # Seed-only: the env seeds ONE connection (+ repository) once (the spec-101 rule).
    WEBHOOK_SECRET = "webhook_secret"
    BASE_URL = "base_url"
    API_TOKEN = "api_token"
    REPO = "repo"
    # Tunables.
    HTTP_TIMEOUT = "http_timeout_seconds"
    PAGE_SIZE = "api_page_size"
    MAX_COMMITS = "backfill_max_commits"


class CiOutcome(StrEnum):
    """The terminal CI states — the ones that fire `ci.completed`. A queued or
    running report updates the link's badge and fires nothing."""

    SUCCESS = "success"
    FAILURE = "failure"
    CANCELLED = "cancelled"


class CiState(StrEnum):
    """Every state a ref's CI badge shows (spec 111): the three outcomes plus the
    two that fire nothing. Each connector maps its host's vocabulary onto this one,
    and `ItemVcsLink.ci_state` stores a member ("" = never reported)."""

    SUCCESS = CiOutcome.SUCCESS.value
    FAILURE = CiOutcome.FAILURE.value
    CANCELLED = CiOutcome.CANCELLED.value
    RUNNING = "running"
    UNKNOWN = "unknown"


#: A report for the SAME run cannot leave one of these for a non-terminal state.
CI_TERMINAL: frozenset[str] = frozenset(CiOutcome)

#: How several reported streams summarise into one badge: the first of these that
#: any stream is in wins, so one red workflow outranks nine green ones.
CI_SUMMARY_ORDER: tuple[CiState, ...] = (
    CiState.FAILURE, CiState.RUNNING, CiState.CANCELLED, CiState.UNKNOWN, CiState.SUCCESS
)


class CiReportKind(StrEnum):
    """The stream a CI report is keyed under in `ItemVcsLink.ci_reports`. PIPELINE
    is the one-stream default (GitLab); GitHub and Forgejo compose `<event>:<workflow>`
    keys so each workflow is ordered on its own."""

    PIPELINE = "pipeline"
