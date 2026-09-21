import uuid
from datetime import datetime
from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base


class ScriptPackage(Base):
    """A package an admin asked for in the managed interpreter."""

    __tablename__ = "script_packages"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    #: The distribution name, normalised (`requests`, `google-api-python-client`).
    name: Mapped[str] = mapped_column(String(200), unique=True)
    #: What was asked for — `requests>=2.31`, `pandas==2.2.*`.
    spec: Mapped[str] = mapped_column(String(300))
    #: What resolved, from `uv pip show` after the install; "" until then.
    resolved_version: Mapped[str] = mapped_column(String(100), default="")
    #: A `PackageStatus` value.
    status: Mapped[str] = mapped_column(String(16), default="pending")
    #: The installer's output, tail-capped.
    log: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime]
    installed_at: Mapped[datetime | None] = mapped_column(nullable=True)


class ScriptInterpreter(Base):
    """THE managed interpreter — one row, fixed id. A table rather than a
    settings key because it carries state (built when, with what, how it
    went), not a tunable."""

    __tablename__ = "script_interpreter"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    python_version: Mapped[str] = mapped_column(String(20), default="3.12")
    #: An `InterpreterStatus` value.
    status: Mapped[str] = mapped_column(String(16), default="missing")
    #: The interpreter's own report of itself (`python -V`), "" until built.
    resolved: Mapped[str] = mapped_column(String(100), default="")
    log: Mapped[str] = mapped_column(Text, default="")
    built_at: Mapped[datetime | None] = mapped_column(nullable=True)
    #: Where packages resolve from (RADD-1277): a package index of the admin's
    #: own ("" = PyPI) — an air-gapped site runs a mirror — and `offline`, which
    #: resolves from the wheelhouses alone and fails fast instead of waiting on
    #: a dropped route. The URL may carry credentials; readers mask them.
    index_url: Mapped[str] = mapped_column(String(500), default="", server_default="")
    offline: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
