import uuid
from datetime import datetime
from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin


class Script(Base, TimestampMixin):
    """An admin-authored Python script (RADD-1269). Its body is what a
    `script.run` / `script.decide` automation node executes, in the managed
    interpreter, out of process."""

    __tablename__ = "scripts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    body: Mapped[str] = mapped_column(Text, default="")
    #: The current version's number — the automation graphs' shape (RADD-1268).
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class ScriptVersion(Base):
    """One immutable version of a script's body."""

    __tablename__ = "script_versions"
    __table_args__ = (UniqueConstraint("script_id", "version"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    script_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scripts.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    body: Mapped[str] = mapped_column(Text)
    note: Mapped[str] = mapped_column(Text, default="")
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime]


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
