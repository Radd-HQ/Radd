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
