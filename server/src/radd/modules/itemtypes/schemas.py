import uuid

from pydantic import BaseModel, ConfigDict, Field

# Issue templates (spec 76) are markdown snippets, not documents — cap the size.
TEMPLATE_MAX_LENGTH = 20_000


class TypeRef(BaseModel):
    """Embedded issue-type reference on an item read (spec 51)."""

    id: uuid.UUID
    name: str
    color: str
    icon: str | None = None


class IssueTypeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    color: str
    icon: str | None
    position: int
    is_default: bool
    # Issue template (spec 76): markdown the new-item modal prefills on select.
    description_template: str | None = None


class IssueTypeCreate(BaseModel):
    project_id: uuid.UUID
    name: str = Field(min_length=1, max_length=100)
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    icon: str | None = Field(default=None, max_length=40)
    position: int | None = None
    is_default: bool = False
    description_template: str | None = Field(default=None, max_length=TEMPLATE_MAX_LENGTH)


class IssueTypeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    icon: str | None = Field(default=None, max_length=40)
    position: int | None = None
    is_default: bool | None = None
    # Omitted = unchanged; explicit null/'' clears (model_fields_set idiom).
    description_template: str | None = Field(default=None, max_length=TEMPLATE_MAX_LENGTH)
