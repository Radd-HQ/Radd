"""Vocabulary for user-definable issue link types (spec 91).

Link types were a hardcoded enum (blocks/relates/duplicates + the auto-managed
mentions). They are now first-class, scopeable data: an admin can add new ones
with their own directional names, and scope any type global or to projects. The
four built-ins keep their stable KEYS so existing links and SLQ keep working.
"""

from enum import StrEnum


class LinkDirection(StrEnum):
    """How a link reads in each direction."""

    DIRECTED = "directed"  # outward ≠ inward ("blocks" / "is blocked by")
    SYMMETRIC = "symmetric"  # one name both ways ("relates to")


class LinkTypeEntity(StrEnum):
    LINK_TYPE = "link_type"


class LinkTypeEvent(StrEnum):
    CREATED = "link_type.created"
    UPDATED = "link_type.updated"
    DELETED = "link_type.deleted"


# The seeded built-ins. `system` types can't be deleted and keep their key +
# direction (code references these keys). `auto_managed` types (mentions) are
# derived from item text and never added/removed through the link API.
BUILTIN_LINK_TYPES: tuple[dict, ...] = (
    {
        "key": "blocks", "name": "Blocks",
        "outward_name": "blocks", "inward_name": "is blocked by",
        "direction": LinkDirection.DIRECTED, "system": True, "auto_managed": False,
    },
    {
        "key": "relates", "name": "Relates",
        "outward_name": "relates to", "inward_name": "relates to",
        "direction": LinkDirection.SYMMETRIC, "system": True, "auto_managed": False,
    },
    {
        "key": "duplicates", "name": "Duplicates",
        "outward_name": "duplicates", "inward_name": "is duplicated by",
        "direction": LinkDirection.DIRECTED, "system": True, "auto_managed": False,
    },
    {
        "key": "mentions", "name": "Mentions",
        "outward_name": "mentions", "inward_name": "mentioned by",
        "direction": LinkDirection.DIRECTED, "system": True, "auto_managed": True,
    },
)
