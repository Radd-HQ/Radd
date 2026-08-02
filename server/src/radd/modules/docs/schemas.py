import uuid

from pydantic import BaseModel, ConfigDict, Field
from radd.apitypes import UtcDatetime

SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]{0,99}$"


# --- spaces ---


class DocSpaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    # Omitted -> derived from the name (slugs are cosmetic; URLs use ids).
    slug: str | None = Field(default=None, pattern=SLUG_PATTERN)
    description: str = ""
    position: float = 0


class DocSpaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    slug: str | None = Field(default=None, pattern=SLUG_PATTERN)
    description: str | None = None
    position: float | None = None
    # Spec 74: toggle no-login readability via /public/kb (doc.manage).
    public: bool | None = None


class DocSpaceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    description: str
    position: float
    public: bool
    page_count: int = 0  # live (non-archived) pages; hydrated by the service
    created_at: UtcDatetime
    updated_at: UtcDatetime


# --- pages ---


class DocPageCreate(BaseModel):
    space_id: uuid.UUID
    parent_id: uuid.UUID | None = None
    title: str = Field(min_length=1, max_length=500)
    body: str = ""
    position: float | None = None  # omitted -> appended after current siblings


class DocPageUpdate(BaseModel):
    """Omitted = unchanged; `parent_id: null` moves to root (model_fields_set
    tri-state). `expected_version` (when sent) must match the current version
    or the PATCH 409s instead of clobbering a concurrent edit."""

    title: str | None = Field(default=None, min_length=1, max_length=500)
    body: str | None = None
    parent_id: uuid.UUID | None = None
    position: float | None = None
    expected_version: int | None = Field(default=None, ge=1)


class DocPageSummary(BaseModel):
    """Flat tree row — the client assembles the hierarchy."""

    id: uuid.UUID
    parent_id: uuid.UUID | None
    title: str
    position: float
    has_children: bool
    updated_at: UtcDatetime


class DocBreadcrumb(BaseModel):
    id: uuid.UUID
    title: str


class DocPageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    space_id: uuid.UUID
    parent_id: uuid.UUID | None
    title: str
    body: str
    position: float
    version: int
    created_by: uuid.UUID
    updated_by: uuid.UUID
    archived_at: UtcDatetime | None
    created_at: UtcDatetime
    updated_at: UtcDatetime
    space: DocSpaceRead
    breadcrumb: list[DocBreadcrumb]  # ancestors, root first (excludes the page)


# --- versions ---


class DocVersionMeta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version: int
    title: str
    author_id: uuid.UUID
    created_at: UtcDatetime


class DocVersionRead(DocVersionMeta):
    body: str


class DocRestoreRequest(BaseModel):
    version: int = Field(ge=1)


# --- item links ---


class DocLinkCreate(BaseModel):
    item_key: str = Field(min_length=1, max_length=30)  # e.g. "TD-123"


class DocLinkedItem(BaseModel):
    """An issue linked to a page, hydrated for display (key chip + title + state)."""

    item_id: uuid.UUID
    key: str
    title: str
    state: str
    state_category: str


class ItemDocRef(BaseModel):
    """A page linked to an issue (the issue page's Docs row)."""

    page_id: uuid.UUID
    space_id: uuid.UUID
    title: str
    space_name: str


# --- search ---


class DocSearchResult(BaseModel):
    page_id: uuid.UUID
    space_id: uuid.UUID
    title: str
    snippet: str | None


class DocSearchResponse(BaseModel):
    results: list[DocSearchResult]


# --- public KB (spec 74) — the deliberately TRIMMED no-login shapes ---


class PublicKbSpace(BaseModel):
    """GET /public/kb/spaces — a public space's card, nothing internal."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    description: str


class PublicKbPageNode(BaseModel):
    """GET /public/kb/spaces/{id}/tree — one non-archived tree row."""

    id: uuid.UUID
    parent_id: uuid.UUID | None
    title: str
    position: float


class PublicKbPageRead(BaseModel):
    """GET /public/kb/pages/{id} — body + breadcrumb only (no versions/links/
    authors; markdown renders client-side)."""

    id: uuid.UUID
    space_id: uuid.UUID
    title: str
    body: str
    breadcrumb: list[DocBreadcrumb]  # ancestors, root first
    updated_at: UtcDatetime
