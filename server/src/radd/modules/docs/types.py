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


class DocEntity(StrEnum):
    SPACE = "doc_space"
    PAGE = "doc_page"


class DocEvent(StrEnum):
    SPACE_CREATED = "doc_space.created"
    SPACE_UPDATED = "doc_space.updated"
    SPACE_DELETED = "doc_space.deleted"
    PAGE_CREATED = "doc_page.created"
    PAGE_UPDATED = "doc_page.updated"
    PAGE_DELETED = "doc_page.deleted"
    PAGE_MOVED = "doc_page.moved"
    PAGE_RESTORED = "doc_page.restored"
    LINK_CREATED = "doc_link.created"
    LINK_DELETED = "doc_link.deleted"


class RestoreKind(StrEnum):
    """`action` values in doc_page.restored event payloads."""

    VERSION = "version"  # an old version's content restored as a NEW version
    UNARCHIVE = "unarchive"  # archived_at cleared (doc.manage)
