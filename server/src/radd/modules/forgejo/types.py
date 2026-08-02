"""Wire constants for the Forgejo/Gitea webhook connector (spec 47)."""

from enum import StrEnum


class ForgejoEventKind(StrEnum):
    """Values of the X-Forgejo-Event / X-Gitea-Event header this connector handles."""

    PUSH = "push"
    PULL_REQUEST = "pull_request"


class PrStatus(StrEnum):
    """Status recorded on the merge_request-type vcs link (spec 47: open/merged/closed)."""

    OPEN = "open"
    MERGED = "merged"
    CLOSED = "closed"
