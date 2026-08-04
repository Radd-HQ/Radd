from enum import StrEnum


class GroupEntity(StrEnum):
    GROUP = "group"


class GroupEvent(StrEnum):
    SYNCED = "group.synced"  # payload carries member/edge counts
    MISSING = "group.missing"  # the DN stopped resolving in AD (grants kept)
    RESTORED = "group.restored"
