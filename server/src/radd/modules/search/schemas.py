import uuid

from pydantic import BaseModel


class SearchResult(BaseModel):
    item_id: uuid.UUID
    project_id: uuid.UUID
    key: str
    title: str
    # ts_headline fragment with <b>…</b> marks; None for key-prefix hits.
    snippet: str | None


class SearchResponse(BaseModel):
    results: list[SearchResult]


# --- GET /search/deflect (spec 66): KB deflection under the new-issue title ---


class DeflectDoc(BaseModel):
    id: uuid.UUID  # page id
    # space_id rides along beyond the spec shape — the doc-page route needs it.
    space_id: uuid.UUID
    title: str
    space_name: str


class DeflectItem(BaseModel):
    key: str
    title: str


class DeflectResponse(BaseModel):
    docs: list[DeflectDoc]  # "Maybe this answers it" wiki pages
    items: list[DeflectItem]  # "Previously resolved" items (done/canceled)


# --- GET /search/semantic (spec 103): the palette's Ask mode ---


class SemanticItem(BaseModel):
    item_id: uuid.UUID
    project_id: uuid.UUID
    key: str
    title: str
    score: float  # 1 - cosine distance, 0..1


class SemanticDoc(BaseModel):
    page_id: uuid.UUID
    space_id: uuid.UUID
    title: str
    score: float


class SemanticResponse(BaseModel):
    # False = semantic search is not configured here (extension/role/toggle) —
    # the UI hides Ask mode; empty lists with True = a real "nothing similar".
    enabled: bool
    items: list[SemanticItem]
    docs: list[SemanticDoc]
