import uuid

from pydantic import BaseModel, ConfigDict, Field
from radd.apitypes import UtcDatetime

SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]{0,99}$"


# --- spaces ---


class ExternalIdentity(BaseModel):
    """Where a row came from, for callers that import (spec 117).

    Honored only when the caller passes a permission set carrying
    `page.manage` — the same shape `CommentCreate` uses for its author/timestamp
    overrides, so an ordinary request cannot reach these by adding two fields to
    its JSON body.
    """

    #: The INSTANCE, not the product: `confluence:wiki.example.com`.
    external_source: str = Field(default="", max_length=200)
    external_id: str = Field(default="", max_length=200)


class PageSpaceCreate(ExternalIdentity):
    name: str = Field(min_length=1, max_length=200)
    # Omitted -> derived from the name (slugs are cosmetic; URLs use ids).
    slug: str | None = Field(default=None, pattern=SLUG_PATTERN)
    description: str = ""
    position: float = 0


class PageSpaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    slug: str | None = Field(default=None, pattern=SLUG_PATTERN)
    description: str | None = None
    position: float | None = None
    # Spec 74: toggle no-login readability via /public/pages (page.manage).
    public: bool | None = None


class PageSpaceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    description: str
    position: float
    public: bool
    page_count: int = 0  # live (non-archived) pages; hydrated by the service
    #: RADD-814: the caller's per-SPACE permission union — the space analogue of
    #: ProjectRead.permissions, and what lets the SPA's one `can()` seam resolve
    #: a space-scoped atom instead of asking a global question (the RADD-810
    #: class). Filled by the list endpoint; empty from other constructors.
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
    #: RADD-712: start from a template's shape. Ignored when `body` is given —
    #: an explicit body is a deliberate choice and must win.
    template: str | None = None
    #: Spec 117 import overrides, honored only for a caller holding page.manage.
    #: An import STATES the author; falling back to the actor credits whoever ran
    #: it with thousands of other people's pages (the spec-90 mistake).
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
    #: Do not snapshot the previous content into `page_versions`, and do not bump
    #: `version` (spec 117). An import CONSTRUCTS a page over several passes — the
    #: body is written once, then rewritten when its attachments exist — and those
    #: intermediate states are not edits anybody made. Without this the
    #: construction passes occupy the version numbers the page's REAL imported
    #: history needs, and writing that history then collides on (page, version).
    suppress_version: bool = False


class PageBacklink(BaseModel):
    """A page that links here (RADD-713). Carries the space slug because a
    backlink may come from ANOTHER space, and the URL needs both segments."""

    id: uuid.UUID
    title: str
    slug: str
    space_id: uuid.UUID
    space_slug: str
    updated_at: UtcDatetime


class PageLabelled(BaseModel):
    """A page carrying a label (RADD-718), for `radd:label-list`."""

    id: uuid.UUID
    title: str
    slug: str
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
    """One entry in the editor's insert menu (RADD-709).

    A projection of the kernel's `PageExtensionSpec`. No handler crosses the
    wire because there is none: rendering is client-side by design, and this
    endpoint exists so the menu is a function of what is INSTALLED rather than a
    list hardcoded in the SPA.
    """

    name: str
    label: str
    description: str
    params_schema: dict = Field(default_factory=dict)
    icon: str = ""
    #: The plugin that contributes it (RADD-748). The insert menu groups on this,
    #: so an installed plugin's extensions arrive under their own heading with no
    #: frontend change — and the SERVER is what says where each came from, rather
    #: than the client guessing from a name it may never have seen.
    source: str = ""


class PageSummary(BaseModel):
    """Flat tree row — the client assembles the hierarchy."""

    id: uuid.UUID
    parent_id: uuid.UUID | None
    title: str
    slug: str
    position: float
    has_children: bool
    updated_at: UtcDatetime
    labels: list[str] = Field(default_factory=list)  # RADD-718


class PageBreadcrumb(BaseModel):
    """An ancestor in the trail. Carries the slug so the client can build the
    ancestor's URL without a second fetch (RADD-702)."""

    id: uuid.UUID
    title: str
    slug: str


class PageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    space_id: uuid.UUID
    parent_id: uuid.UUID | None
    title: str
    slug: str
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
    #: The page's TEXT mentions it (RADD-943) — the link is reconciled on every
    #: save, so it is not the reader's to remove. False = someone typed the key.
    derived: bool = False


class ItemPageRef(BaseModel):
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


class PageSearchResponse(BaseModel):
    results: list[DocSearchResult]


# --- public KB (spec 74) — the deliberately TRIMMED no-login shapes ---


class PublicPageSpace(BaseModel):
    """GET /public/pages/spaces — a public space's card, nothing internal."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    description: str


class PublicPageNode(BaseModel):
    """GET /public/pages/spaces/{id}/tree — one non-archived tree row."""

    id: uuid.UUID
    parent_id: uuid.UUID | None
    title: str
    slug: str  # RADD-702: the public tree builds /public-pages/<space>/<page> too
    position: float


class PublicPageRead(BaseModel):
    """GET /public/pages/pages/{id} — body + breadcrumb only (no versions/links/
    authors; markdown renders client-side)."""

    id: uuid.UUID
    space_id: uuid.UUID
    title: str
    body: str
    breadcrumb: list[PageBreadcrumb]  # ancestors, root first
    updated_at: UtcDatetime
