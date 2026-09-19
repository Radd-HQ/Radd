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
    PENDING_WORKLOG = "vcs_pending_worklog"


class VcsMatchedBy(StrEnum):
    """How a provider account was tied to a Radd user (RADD-1258)."""

    EMAIL = "email"
    MANUAL = "manual"


class VcsUserLinkEvent(StrEnum):
    """Spec 123: identity-map administration is audited; not a trigger."""

    CREATED = "vcs_user_link.created"
    DELETED = "vcs_user_link.deleted"
