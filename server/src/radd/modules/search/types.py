"""Constants for the search module."""

import re

# This module's cursor name in the events stream.
CONSUMER_NAME = "search.indexer"

# Postgres text-search configuration used for both indexing and querying.
SEARCH_TS_CONFIG = "english"

# A full or partial item key: "TD", "TD-", "TD-12" — triggers key-prefix matching.
KEY_QUERY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,9}(-\d*)?$")

# A bare issue number: "123" — matches the numeric part of any key ("#123" habit
# from Jira/GitHub; the editor's `#` mention sends exactly this).
NUMBER_QUERY_RE = re.compile(r"^\d{1,10}$")

# Tokens kept when building a tsquery (everything else is a separator).
TSQUERY_TOKEN_RE = re.compile(r"[\w][\w.-]*", re.UNICODE)

# Cap on q length — longer input is truncated, not an error.
MAX_QUERY_CHARS = 200

# Per-section result cap for GET /search/deflect (spec 66).
DEFLECT_LIMIT = 5

# Hybrid semantic search (spec 103). The ai module is optional — its candidate
# seam loads via this deferred module path (the DOCS_MODULE precedent).
AI_EMBEDDINGS_MODULE = "radd.modules.ai"
# Below this many characters a query is type-ahead, not meaning — FTS only.
MIN_SEMANTIC_QUERY_CHARS = 8
# ANN over-fetch into the fuse (narrow-access users still fill the page).
SEMANTIC_CANDIDATES = 40
