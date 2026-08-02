from enum import StrEnum


class ProjectRole(StrEnum):
    """Legacy fixed role ladder. Since spec 06 project roles are DATA (auth `roles`
    table); this enum survives only as the fields module's `min_read_role`/
    `min_write_role` levels until spec 07 replaces those with per-role/team grants."""

    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class TeamEvent(StrEnum):
    CREATED = "team.created"
    UPDATED = "team.updated"  # also emitted for membership and project-attachment changes
    DELETED = "team.deleted"  # spec 87


class TeamEntity(StrEnum):
    TEAM = "team"
    MEMBER = "team_member"
    PROJECT_TEAM = "project_team"
    MANAGER = "team_manager"  # spec 87 — delegated per-team management


class TeamSource(StrEnum):
    """Who owns a team's MEMBERSHIP (spec 87).

    LOCAL — people are added and removed by hand here.
    DIRECTORY — the linked AD group is the sole source of truth and membership is
    read-only in Radd: add/remove answer 409. Mixed ownership (spec 84 allowed
    manual rows to sit alongside synced ones) is what made linked teams drift.

    Two things stay LOCAL even on a directory team, deliberately: the team NAME
    (AD CNs like `SG-RND-Pipeline-RW` make poor display names, and a rename is
    cosmetic), and the team's PROJECT GRANTS — deciding what an AD group may do
    here is the whole point of linking it.
    """

    LOCAL = "local"
    DIRECTORY = "directory"


class MemberSource(StrEnum):
    """How a team_members row got there (spec 84). Directory sync touches ONLY
    directory-source rows; hand-added members are never removed by a sync."""

    MANUAL = "manual"
    DIRECTORY = "directory"


class TeamChange(StrEnum):
    """`action` values in team.updated event payloads."""

    MEMBER_ADDED = "member_added"
    MEMBER_REMOVED = "member_removed"
    PROJECT_ATTACHED = "project_attached"
    PROJECT_ROLE_CHANGED = "project_role_changed"
    PROJECT_DETACHED = "project_detached"
    RENAMED = "renamed"
    # Spec 84: AD group link lifecycle + reconcile results.
    DIRECTORY_LINKED = "directory_linked"
    DIRECTORY_UNLINKED = "directory_unlinked"
    DIRECTORY_SYNCED = "directory_synced"  # payload carries added/removed counts
    # Spec 87: the linked group vanished from AD / came back.
    DIRECTORY_MISSING = "directory_missing"
    DIRECTORY_RESTORED = "directory_restored"
    # Spec 87: delegated management.
    MANAGERS_REPLACED = "managers_replaced"
    OWNER_TRANSFERRED = "owner_transferred"
