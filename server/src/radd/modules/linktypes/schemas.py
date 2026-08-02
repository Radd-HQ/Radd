import uuid

from pydantic import BaseModel, ConfigDict, Field, model_validator

from radd.apitypes import UtcDatetime

from .types import LinkDirection


class LinkTypeCreate(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,29}$", description="Stable snake_case key")
    name: str = Field(min_length=1, max_length=60)
    outward_name: str = Field(min_length=1, max_length=60)
    # For a symmetric type the inward name mirrors the outward one (filled if blank).
    inward_name: str = Field(default="", max_length=60)
    direction: LinkDirection = LinkDirection.DIRECTED
    # Empty = global; otherwise scope the type to these projects.
    project_ids: list[uuid.UUID] = Field(default_factory=list)

    @model_validator(mode="after")
    def _fill_inward(self) -> "LinkTypeCreate":
        if self.direction is LinkDirection.SYMMETRIC or not self.inward_name.strip():
            self.inward_name = self.outward_name
        self.project_ids = list(dict.fromkeys(self.project_ids))
        return self


class LinkTypeUpdate(BaseModel):
    """PATCH — omitted keys unchanged. Key + (for system types) direction are locked."""

    name: str | None = Field(default=None, min_length=1, max_length=60)
    outward_name: str | None = Field(default=None, min_length=1, max_length=60)
    inward_name: str | None = Field(default=None, min_length=1, max_length=60)
    direction: LinkDirection | None = None
    # Omitted = unchanged; [] = promote to global; non-empty = re-scope (model_fields_set).
    project_ids: list[uuid.UUID] | None = None


class LinkTypeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: str
    name: str
    outward_name: str
    inward_name: str
    direction: LinkDirection
    system: bool
    auto_managed: bool
    project_ids: list[uuid.UUID] = Field(default_factory=list)
    usages: int = 0  # how many links currently use this type
    created_at: UtcDatetime
