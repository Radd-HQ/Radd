"""Registry + editor API shapes (specs 101/103). Spec-46 flow schemas stay in types.py."""

import uuid
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from .types import (
    EDITOR_DOCUMENT_MAX_CHARS,
    EDITOR_INSTRUCTION_MAX_CHARS,
    EDITOR_SELECTION_MAX_CHARS,
    RESERVED_REQUEST_PARAMS,
    AiRole,
    AiWireShape,
    EditorActionKind,
)


def _request_params(value: dict[str, Any]) -> dict[str, Any]:
    """Extra request parameters are an OBJECT of top-level payload keys. The
    structural keys stay Radd's: a `messages` or `stream` override would not
    tune the call, it would replace it."""
    reserved = RESERVED_REQUEST_PARAMS & set(value)
    if reserved:
        raise ValueError(
            "request_params may not set " + ", ".join(sorted(reserved))
        )
    return value


RequestParams = Annotated[dict[str, Any], AfterValidator(_request_params)]


class AiProviderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    wire_shape: AiWireShape
    base_url: str = Field(default="", max_length=500)  # "" = the shape's default
    api_key: str = ""
    default_model: str = Field(default="", max_length=200)
    # RADD-1273: off by default on every new connection; see AiProviderRow.
    reasoning: bool = False
    request_params: RequestParams = Field(default_factory=dict)


class AiProviderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    wire_shape: AiWireShape | None = None
    base_url: str | None = Field(default=None, max_length=500)
    # "" on update = keep the stored key (reads are redacted, forms round-trip "").
    api_key: str | None = None
    default_model: str | None = Field(default=None, max_length=200)
    reasoning: bool | None = None
    request_params: RequestParams | None = None


class AiProviderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    wire_shape: str
    base_url: str
    has_api_key: bool
    default_model: str
    source: str
    reasoning: bool
    request_params: dict[str, Any]


class AiRoleAssign(BaseModel):
    provider_id: uuid.UUID
    model: str = Field(default="", max_length=200)  # "" = the provider's default model


class AiRoleRead(BaseModel):
    role: AiRole
    provider_id: uuid.UUID
    provider_name: str
    model: str
    effective_model: str  # role model, falling back to the provider default


class AiPresetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=1)
    enabled: bool = True
    position: int = 0


class AiPresetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    prompt: str | None = Field(default=None, min_length=1)
    enabled: bool | None = None
    position: int | None = None


class AiPresetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    prompt: str
    enabled: bool
    position: int


# --- editor actions (spec 103) ------------------------------------------------


class EditorActionRead(BaseModel):
    """One menu entry. Prompts NEVER ship to the client — the id comes back."""

    id: str  # EditorAction value, or a preset uuid
    label: str
    kind: EditorActionKind


class EditorStreamRequest(BaseModel):
    action_id: str | None = None
    instruction: str | None = Field(default=None, max_length=EDITOR_INSTRUCTION_MAX_CHARS)
    document: str = Field(max_length=EDITOR_DOCUMENT_MAX_CHARS)
    selection: str = Field(default="", max_length=EDITOR_SELECTION_MAX_CHARS)

    @model_validator(mode="after")
    def _exactly_one_of(self) -> "EditorStreamRequest":
        if bool(self.action_id) == bool(self.instruction and self.instruction.strip()):
            raise ValueError("send exactly one of action_id or instruction")
        return self
