import re
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from radd.apitypes import UtcDatetime

#: A PEP 508-ish requirement without URLs, paths or options: a name, optional
#: extras, optional version specifiers. Anything cleverer is a way to install
#: from somewhere the admin did not name.
REQUIREMENT_RE = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?"
    r"(?:\[[A-Za-z0-9._,-]+\])?"
    r"(?:\s*(?:[<>=!~]=?|===)\s*[A-Za-z0-9._*+!-]+(?:\s*,\s*(?:[<>=!~]=?|===)\s*[A-Za-z0-9._*+!-]+)*)?$"
)
PYTHON_VERSION_RE = re.compile(r"^3\.(1[0-9]|[89])(?:\.\d+)?$")
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_ .-]{0,99}$")


class ScriptCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)
    body: str = Field(default="", max_length=200_000)
    note: str = Field(default="", max_length=2000)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = value.strip()
        if not NAME_RE.match(value):
            raise ValueError("a script name is letters, digits, spaces, dots, dashes or underscores")
        return value


class ScriptUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    body: str | None = Field(default=None, max_length=200_000)
    note: str = Field(default="", max_length=2000)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not NAME_RE.match(value):
            raise ValueError("a script name is letters, digits, spaces, dots, dashes or underscores")
        return value


class ScriptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str
    body: str
    version: int
    updated_by_id: uuid.UUID | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime


class ScriptSummary(BaseModel):
    """The list row — no body."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str
    version: int
    updated_at: UtcDatetime


class ScriptVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version: int
    body: str
    note: str
    created_by_id: uuid.UUID | None = None
    created_at: UtcDatetime


class PackageCreate(BaseModel):
    spec: str = Field(min_length=1, max_length=300)

    @field_validator("spec")
    @classmethod
    def _spec(cls, value: str) -> str:
        value = value.strip()
        if not REQUIREMENT_RE.match(value):
            raise ValueError(
                "a package is a name with optional extras and version specifiers, "
                "e.g. requests>=2.31 — not a URL, a path or an option"
            )
        return value


class PackageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    spec: str
    resolved_version: str
    status: str
    log: str
    created_at: UtcDatetime
    installed_at: UtcDatetime | None = None


class InterpreterRead(BaseModel):
    python_version: str
    status: str
    resolved: str
    log: str
    built_at: UtcDatetime | None = None
    #: Where the venv lives, so an operator can find it.
    path: str
    #: Versions uv can provide here, for the picker; empty when uv cannot say.
    available: list[str] = Field(default_factory=list)
    #: The pinned SDK's origin — a path or a package name.
    sdk_source: str = ""


class InterpreterRebuild(BaseModel):
    python_version: str = Field(min_length=3, max_length=20)

    @field_validator("python_version")
    @classmethod
    def _version(cls, value: str) -> str:
        value = value.strip()
        if not PYTHON_VERSION_RE.match(value):
            raise ValueError("a Python version like 3.12 or 3.12.6")
        return value


class RunRequest(BaseModel):
    """A pasted packet for the Run now box: the same shape a node hands the
    script, minus the client (which is real)."""

    items: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    vars: dict[str, dict[str, str]] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)
    event: dict[str, Any] | None = None
    timeout: int = Field(default=30, ge=1, le=600)


class RunOutcomeRead(BaseModel):
    ok: bool
    result: Any = None
    stdout: str = ""
    stderr: str = ""
    error: str = ""
    duration_ms: int = 0
