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
    """The inspector's Test box (RADD-1272): a body, an optional item to seed
    `ctx.items` with, and what upstream values to pretend exist. A dry run of
    the automation never applies an action, so this is how a script is tried
    before the automation is enabled. Runs as the caller, against the real API."""

    body: str = Field(min_length=1, max_length=200_000)
    item_key: str = Field(default="", max_length=64)
    vars: dict[str, dict[str, str]] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)
    timeout: int = Field(default=30, ge=1, le=600)


class RunOutcomeRead(BaseModel):
    ok: bool
    result: Any = None
    stdout: str = ""
    stderr: str = ""
    error: str = ""
    duration_ms: int = 0
