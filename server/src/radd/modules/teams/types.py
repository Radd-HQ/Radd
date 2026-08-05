from enum import StrEnum


class TeamEvent(StrEnum):
    CREATED = "team.created"
    UPDATED = "team.updated"  # also emitted for membership and project-attachment changes
    DELETED = "team.deleted"  # spec 87


class TeamEntity(StrEnum):
    TEAM = "team"
    MEMBER = "team_member"
    PROJECT_TEAM = "project_team"
    MANAGER = "team_manager"  # spec 87 — delegated per-team management


# RADD-829: `TeamSource` and `MemberSource` retired with the Groups split — a
# team is never directory-mirrored, so the flags had nothing left to say. The
# six directory `TeamChange` values retired with them, WITHOUT reader-side
# aliases (no-backcompat rule: old audit rows render their raw action string).


class TeamChange(StrEnum):
    """`action` values in team.updated event payloads."""

    MEMBER_ADDED = "member_added"
    MEMBER_REMOVED = "member_removed"
    # RADD-829: a GROUP joined/left the team's membership.
    GROUP_ADDED = "group_added"
    GROUP_REMOVED = "group_removed"
    PROJECT_ATTACHED = "project_attached"
    PROJECT_ROLE_CHANGED = "project_role_changed"
    PROJECT_DETACHED = "project_detached"
    RENAMED = "renamed"
    # Spec 87: delegated management.
    MANAGERS_REPLACED = "managers_replaced"
    OWNER_TRANSFERRED = "owner_transferred"
