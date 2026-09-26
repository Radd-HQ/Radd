from enum import StrEnum


class TeamEvent(StrEnum):
    CREATED = "team.created"
    UPDATED = "team.updated"  # also emitted for membership changes
    DELETED = "team.deleted"  # spec 87


class TeamEntity(StrEnum):
    TEAM = "team"
    MEMBER = "team_member"
    MANAGER = "team_manager"  # spec 87 — delegated per-team management


class TeamChange(StrEnum):
    """`action` values in team.updated event payloads."""

    MEMBER_ADDED = "member_added"
    MEMBER_REMOVED = "member_removed"
    # RADD-829: a GROUP joined/left the team's membership.
    GROUP_ADDED = "group_added"
    GROUP_REMOVED = "group_removed"
    RENAMED = "renamed"
    # Spec 87: delegated management.
    MANAGERS_REPLACED = "managers_replaced"
    OWNER_TRANSFERRED = "owner_transferred"
