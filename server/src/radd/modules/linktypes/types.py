"""Vocabulary for user-definable issue link types. The four built-ins keep
stable KEYS that existing links and SLQ reference."""

from enum import StrEnum


class ItemLinkType(StrEnum):
    """The built-in link-type KEYS, referenced by code. Symmetry, directional
    names and whether a type is manual come from the catalog; MENTIONS is
    auto-derived from item text (spec 52)."""

    BLOCKS = "blocks"
    RELATES = "relates"
    DUPLICATES = "duplicates"
    MENTIONS = "mentions"


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
        "key": ItemLinkType.BLOCKS.value, "name": "Blocks",
        "outward_name": "blocks", "inward_name": "is blocked by",
        "direction": LinkDirection.DIRECTED, "system": True, "auto_managed": False,
    },
    {
        "key": ItemLinkType.RELATES.value, "name": "Relates",
        "outward_name": "relates to", "inward_name": "relates to",
        "direction": LinkDirection.SYMMETRIC, "system": True, "auto_managed": False,
    },
    {
        "key": ItemLinkType.DUPLICATES.value, "name": "Duplicates",
        "outward_name": "duplicates", "inward_name": "is duplicated by",
        "direction": LinkDirection.DIRECTED, "system": True, "auto_managed": False,
    },
    {
        "key": ItemLinkType.MENTIONS.value, "name": "Mentions",
        "outward_name": "mentions", "inward_name": "mentioned by",
        "direction": LinkDirection.DIRECTED, "system": True, "auto_managed": True,
    },
)
