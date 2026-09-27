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
