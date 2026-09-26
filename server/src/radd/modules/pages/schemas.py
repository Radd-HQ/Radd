import uuid

from pydantic import BaseModel, ConfigDict, Field
from radd.apitypes import UtcDatetime

SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]{0,99}$"


# --- spaces ---


class ExternalIdentity(BaseModel):
    """Where a row came from (spec 117). Honored only with a permission set
    carrying `page.manage` (the `CommentCreate` shape), so a request cannot reach
    it by adding two fields."""

    #: The INSTANCE, not the product: `confluence:wiki.example.com`.
    external_source: str = Field(default="", max_length=200)
    external_id: str = Field(default="", max_length=200)


class PageSpaceCreate(ExternalIdentity):
    name: str = Field(min_length=1, max_length=200)
    # Omitted -> derived from the name.
    slug: str | None = Field(default=None, pattern=SLUG_PATTERN)
    description: str = ""
    position: float = 0


class PageSpaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    slug: str | None = Field(default=None, pattern=SLUG_PATTERN)
    description: str | None = None
    position: float | None = None


class PageSpaceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    description: str
    position: float
    #: Spec 121 (RADD-1147): DERIVED — the Public role is granted to Anyone on
    #: this space. Written through PUT /page-spaces/{id}/public-access.
    public: bool = False
    page_count: int = 0  # live (non-archived) pages; hydrated by the service
    #: RADD-814: the caller's per-SPACE permission union (the space analogue of
    #: ProjectRead.permissions); filled by the list endpoint only.
    permissions: list[str] = []
    created_at: UtcDatetime
    updated_at: UtcDatetime


class PageSpaceSummaryRead(BaseModel):
    total: int
    permissions: list[str]


# --- pages ---


class PageCreate(ExternalIdentity):
    space_id: uuid.UUID
    parent_id: uuid.UUID | None = None
    title: str = Field(min_length=1, max_length=500)
    # Omitted -> derived from the title (RADD-702). Supplying one is for
    # importers that must preserve an existing URL.
    slug: str | None = Field(default=None, max_length=120)
    body: str = ""
    position: float | None = None  # omitted -> appended after current siblings
    #: RADD-712: start from a template; ignored when `body` is given.
    template: str | None = None
    #: Spec 117 import overrides (page.manage only): an import STATES the author.
    author_id: uuid.UUID | None = None
    created_at: UtcDatetime | None = None
    updated_at: UtcDatetime | None = None


class PageUpdate(BaseModel):
    """Omitted = unchanged; `parent_id: null` moves to root (model_fields_set
    tri-state). `expected_version` (when sent) must match the current version
    or the PATCH 409s instead of clobbering a concurrent edit."""

    title: str | None = Field(default=None, min_length=1, max_length=500)
    # The URL segment. Editing the TITLE never touches it (RADD-702) — changing
    # a page's URL is an explicit act, because it breaks every existing link.
    slug: str | None = Field(default=None, min_length=1, max_length=120)
    body: str | None = None
    parent_id: uuid.UUID | None = None
    position: float | None = None
    expected_version: int | None = Field(default=None, ge=1)
    #: Spec 117 import overrides (page.manage only). `author_id` credits the
    #: revision's real editor; `updated_at` backdates it.
    author_id: uuid.UUID | None = None
    updated_at: UtcDatetime | None = None
    #: Spec 117: an import's construction passes must not consume version numbers.
    suppress_version: bool = False
    #: Spec 122: the live session this save came from; a connected editor's
    #: session skips `expected_version` and the history window applies.
    collab_session: uuid.UUID | None = None
    #: Spec 122: the session's last save — always writes history.
    final: bool = False


class PageBacklink(BaseModel):
    """A page that links here (RADD-713). Carries the space slug because a
    backlink may come from ANOTHER space, and the URL needs both segments."""

    id: uuid.UUID
    number: int
    title: str
    slug: str
    path: str
    space_id: uuid.UUID
    space_slug: str
    updated_at: UtcDatetime


class PageLabelled(BaseModel):
    """A page carrying a label (RADD-718), for `radd:label-list`."""

    id: uuid.UUID
    number: int
    title: str
    slug: str
    path: str
    space_slug: str
    updated_at: UtcDatetime


class PageLabelsUpdate(BaseModel):
    """Full replacement — a set has no sensible partial update."""

    labels: list[str] = Field(default_factory=list)


class PageTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = ""
    icon: str = Field(default="", max_length=40)
    body: str = ""
    #: None = available in every space.
    space_id: uuid.UUID | None = None


class PageTemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    icon: str | None = Field(default=None, max_length=40)
    body: str | None = None
    space_id: uuid.UUID | None = None


class PageTemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str
    icon: str
    body: str
    space_id: uuid.UUID | None


class PageTemplateSummaryRead(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    icon: str
    space_id: uuid.UUID | None
    space_name: str | None


class PageExtensionRead(BaseModel):
    """One insert-menu entry (RADD-709); `source` is the contributing plugin (RADD-748)."""

    name: str
    label: str
    description: str
    params_schema: dict = Field(default_factory=dict)
    icon: str = ""
    source: str = ""


class PageSummary(BaseModel):
    """Flat tree row — the client assembles the hierarchy."""

    id: uuid.UUID
    number: int
    parent_id: uuid.UUID | None
    title: str
    slug: str
    #: RADD-1233: the space-relative address, `parent-slug/…/slug`.
    path: str
    position: float
    has_children: bool
    updated_at: UtcDatetime
    labels: list[str] = Field(default_factory=list)  # RADD-718
    # RADD-1228: set only in the `include_archived` listing, where the client
    # has to tell an archived page from a live descendant hidden with it.
    archived_at: UtcDatetime | None = None


class PageBreadcrumb(BaseModel):
    """An ancestor in the trail, with its path for the URL (RADD-1233)."""

    id: uuid.UUID
    number: int
    title: str
    slug: str
    path: str


class PageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    number: int
    space_id: uuid.UUID
    parent_id: uuid.UUID | None
    title: str
    slug: str
    #: RADD-1233: the canonical address; a client that came by another redirects.
    path: str
    body: str
    position: float
    version: int
    created_by: uuid.UUID
    updated_by: uuid.UUID
    archived_at: UtcDatetime | None
    created_at: UtcDatetime
    updated_at: UtcDatetime
    space: PageSpaceRead
    breadcrumb: list[PageBreadcrumb]  # ancestors, root first (excludes the page)
    labels: list[str] = Field(default_factory=list)  # RADD-718


# --- versions ---


class PageVersionMeta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version: int
    title: str
    author_id: uuid.UUID
    created_at: UtcDatetime


class PageVersionRead(PageVersionMeta):
    body: str


class DocRestoreRequest(BaseModel):
    version: int = Field(ge=1)


# --- item links ---


class DocLinkCreate(BaseModel):
    item_key: str = Field(min_length=1, max_length=30)  # e.g. "TD-123"


class PageLinkedItem(BaseModel):
    """An issue linked to a page, hydrated for display (key chip + title + state)."""

    item_id: uuid.UUID
    key: str
    title: str
    state: str
    state_category: str
    #: From the page TEXT (RADD-943), so not the reader's to remove.
    derived: bool = False


class ItemPageRef(BaseModel):
    """A page linked to an issue."""

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


class PageSearchResponse(BaseModel):
    results: list[DocSearchResult]


class SpacePublicAccessUpdate(BaseModel):
    """PUT /page-spaces/{id}/public-access (spec 121 §5)."""

    public: bool


class PageBulkRequest(BaseModel):
    """RADD-1249: the archive browser's selection — restore or delete many."""

    page_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


class PageBulkSkip(BaseModel):
    id: uuid.UUID
    reason: str


class PageBulkResult(BaseModel):
    """Per page, because a selection is many decisions: what went through and
    what did not, with the reason the single-page path would have answered."""

    done: list[uuid.UUID]
    skipped: list[PageBulkSkip]
