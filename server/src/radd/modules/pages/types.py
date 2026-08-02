"""Constants + enums for the docs (wiki) module — spec 43."""

import re
from enum import StrEnum

# Postgres text-search configuration. MUST match the expression GIN index the
# migration builds: to_tsvector('english', title || ' ' || body).
DOCS_TS_CONFIG = "english"

# Tokens kept when building a tsquery (same contract as the search module's).
TSQUERY_TOKEN_RE = re.compile(r"[\w][\w.-]*", re.UNICODE)

# Cap on q length — longer input is truncated, not an error.
MAX_QUERY_CHARS = 200

# The ai module's dotted name, for the deferred semantic-candidate seam
# (spec 106 public deflection fusion — same contract as search.types).
AI_EMBEDDINGS_MODULE = "radd.modules.ai"

# Space slugs are cosmetic (URLs use ids): lowercase, digits, dashes.
SLUG_MAX_CHARS = 100
SLUG_SEPARATOR_RE = re.compile(r"[^a-z0-9]+")


class PageEntity(StrEnum):
    SPACE = "page_space"
    PAGE = "page"


class PageEvent(StrEnum):
    SPACE_CREATED = "page_space.created"
    SPACE_UPDATED = "page_space.updated"
    SPACE_DELETED = "page_space.deleted"
    PAGE_CREATED = "page.created"
    PAGE_UPDATED = "page.updated"
    PAGE_DELETED = "page.deleted"
    PAGE_MOVED = "page.moved"
    PAGE_RESTORED = "page.restored"
    LINK_CREATED = "page_link.created"
    LINK_DELETED = "page_link.deleted"


class PageExtensionName(StrEnum):
    """The fence suffix of each first-party extension (RADD-709).

    A member here is the wire format — it appears in page bodies in the database
    — so renaming one is a data migration, not a rename.
    """

    TOC = "toc"
    CHILDREN = "children"
    CALLOUT = "callout"
    BACKLINKS = "backlinks"
    INCLUDE = "include"
    LABEL_LIST = "label-list"


class RestoreKind(StrEnum):
    """`action` values in page.restored event payloads."""

    VERSION = "version"  # an old version's content restored as a NEW version
    UNARCHIVE = "unarchive"  # archived_at cleared (page.manage)
