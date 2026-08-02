"""The artifact container (spec 99 §2): plaintext header, sealed payload, footer.

    magic "RADDBK01" │ u32 len │ manifest JSON        ← plaintext
    AES-256-GCM chunks of a tar (database.dump, attachments/…)
    magic "RADDFT01" │ u32 len │ footer JSON          ← plaintext

**The manifest is plaintext on purpose.** Listing the backups page, showing
sizes and dates, and deciding whether an artifact can be restored here all have
to work without the key — and none of that is secret. The payload, which is
everything that matters, is not readable without it.

The manifest is fixed BEFORE the payload is written, because its sha256 is the
AAD binding every chunk (crypto.py). Facts only known afterwards — the plaintext
size and hash — therefore go in a footer. That footer is a plaintext integrity
aid, not the authenticity mechanism: with encryption on, the GCM tags already
prove the payload; with encryption off there is nothing to prove anyway.

Names are `radd-<UTC date>-<UTC time>-<8 hex>.radd`, validated by regex before a
name is ever joined to a path — a filename, never a path.
"""

import base64
import hashlib
import io
import json
import re
import secrets
import tarfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO, Iterator

from . import crypto
from .crypto import ArtifactCorrupt, BackupKey
from .errors import BackupError
from .types import BackupKind

MAGIC = b"RADDBK01"
FOOTER_MAGIC = b"RADDFT01"
_LENGTH_BYTES = 4
FORMAT_VERSION = 1
SUFFIX = ".radd"

#: Members inside the sealed tar.
DUMP_MEMBER = "database.dump"
ATTACHMENTS_MEMBER = "attachments"

ARTIFACT_NAME_RE = re.compile(r"^radd-\d{8}-\d{6}-[0-9a-f]{8}\.radd$")


class ArtifactInvalid(BackupError):
    """Not a Radd artifact, or a manifest that will not parse."""


def new_artifact_name(now: datetime | None = None) -> str:
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
    return f"radd-{stamp}-{secrets.token_hex(4)}{SUFFIX}"


def is_valid_name(name: str) -> bool:
    return bool(ARTIFACT_NAME_RE.match(name))


def resolve_in(directory: Path, name: str) -> Path:
    """`directory / name`, refusing anything that is not a bare artifact name.

    The regex already excludes separators and `..`, and the resolved-parent check
    is the belt to its braces (symlinked directories, exotic normalisation)."""
    if not is_valid_name(name):
        raise ArtifactInvalid(f"invalid backup name {name!r}")
    path = (directory / name).resolve()
    if path.parent != directory.resolve():
        raise ArtifactInvalid(f"backup name {name!r} escapes the backup directory")
    return path


@dataclass(frozen=True)
class Manifest:
    """What an artifact is, and what it can be restored into."""

    created_at: str
    kind: str
    radd_version: str
    schema_version: int
    alembic_revision: str | None
    pg_server_version: str
    encryption: str
    key_id: str | None
    base_nonce: str  # base64
    chunk_bytes: int
    includes_attachments: bool
    created_by: str | None = None
    schedule_id: str | None = None
    format_version: int = FORMAT_VERSION
    extra: dict[str, Any] = field(default_factory=dict)

    def to_bytes(self) -> bytes:
        # sort_keys: the digest is AAD, so serialisation must be reproducible.
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()

    @classmethod
    def from_bytes(cls, raw: bytes) -> "Manifest":
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ArtifactInvalid("manifest is not valid JSON") from exc
        if not isinstance(data, dict):
            raise ArtifactInvalid("manifest is not an object")
        known = {f for f in cls.__dataclass_fields__}
        missing = {"created_at", "kind", "schema_version", "encryption"} - data.keys()
        if missing:
            raise ArtifactInvalid(f"manifest is missing {', '.join(sorted(missing))}")
        return cls(**{k: v for k, v in data.items() if k in known})

    @property
    def encrypted(self) -> bool:
        return self.encryption != crypto.ENCRYPTION_NONE


@dataclass(frozen=True)
class Footer:
    payload_bytes: int
    payload_sha256: str

    def to_bytes(self) -> bytes:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()


def _write_block(target: BinaryIO, magic: bytes, payload: bytes) -> None:
    target.write(magic)
    target.write(len(payload).to_bytes(_LENGTH_BYTES, "big"))
    target.write(payload)


def _read_block(source: BinaryIO, magic: bytes, *, what: str) -> bytes:
    if source.read(len(magic)) != magic:
        raise ArtifactInvalid(f"not a Radd backup artifact ({what} magic mismatch)")
    length_bytes = source.read(_LENGTH_BYTES)
    if len(length_bytes) != _LENGTH_BYTES:
        raise ArtifactInvalid(f"truncated {what} length")
    payload = source.read(int.from_bytes(length_bytes, "big"))
    return payload


@contextmanager
def write_artifact(
    path: Path, manifest: Manifest, *, key: BackupKey | None
) -> Iterator[tarfile.TarFile]:
    """Open `path` for writing and yield a tar the caller adds members to.

    Streamed end to end (`tarfile` mode `w|` needs no seeking), so nothing is
    staged twice — a large instance does not need scratch space equal to itself.
    The footer is written on clean exit only: a crash mid-dump leaves a file with
    no footer, which `read_footer` reports as incomplete rather than restorable.
    """
    header = manifest.to_bytes()
    digest = hashlib.sha256(header).hexdigest()
    with path.open("wb") as target:
        _write_block(target, MAGIC, header)
        if manifest.encrypted:
            if key is None:
                raise ArtifactInvalid("an encrypted artifact needs a key")
            sealer: Any = crypto.ChunkSealer(
                target,
                key=key,
                base_nonce=base64.b64decode(manifest.base_nonce),
                header_digest=digest,
                chunk_bytes=manifest.chunk_bytes,
            )
        else:
            sealer = crypto.PlainSealer(target)
        with tarfile.open(fileobj=sealer, mode="w|") as tar:
            yield tar
        total, sha256 = sealer.finalize()
        _write_block(target, FOOTER_MAGIC, Footer(total, sha256).to_bytes())


def read_manifest(path: Path) -> Manifest:
    """The plaintext header — no key needed. This is what listing uses."""
    with path.open("rb") as source:
        return Manifest.from_bytes(_read_block(source, MAGIC, what="header"))


@contextmanager
def read_artifact(path: Path, manifest: Manifest, *, key: BackupKey | None) -> Iterator[tarfile.TarFile]:
    """Yield the sealed tar, then verify the footer against what was read.

    A mismatch raises `ArtifactCorrupt`: with encryption on the GCM tags have
    already failed by then for any real tampering, so this catches the
    encryption-off case and honest bit-rot.
    """
    with path.open("rb") as source:
        header = _read_block(source, MAGIC, what="header")
        digest = hashlib.sha256(header).hexdigest()
        if manifest.encrypted:
            if key is None:
                raise ArtifactCorrupt("artifact is encrypted and no key is available")
            opener: Any = crypto.ChunkOpener(
                source,
                key=key,
                base_nonce=base64.b64decode(manifest.base_nonce),
                header_digest=digest,
            )
            with tarfile.open(fileobj=opener, mode="r|") as tar:
                yield tar
            total, sha256 = opener.verify_complete()
        else:
            with tarfile.open(fileobj=source, mode="r|") as tar:
                yield tar
            total = sha256 = None  # type: ignore[assignment]
        footer = _read_footer(source)
        if footer is None:
            raise ArtifactCorrupt("artifact has no footer — the backup did not finish")
        if sha256 is not None and (footer.payload_bytes != total or footer.payload_sha256 != sha256):
            raise ArtifactCorrupt("payload does not match the footer checksum")


def _read_footer(source: BinaryIO) -> Footer | None:
    try:
        raw = _read_block(source, FOOTER_MAGIC, what="footer")
    except ArtifactInvalid:
        return None
    try:
        data = json.loads(raw)
        return Footer(int(data["payload_bytes"]), str(data["payload_sha256"]))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def read_footer(path: Path) -> Footer | None:
    """Seek to the end and read the footer without opening the payload.

    Used by `verify` to answer "did this backup finish?" cheaply. The footer is
    the last block, so we read a bounded tail rather than the whole file.
    """
    size = path.stat().st_size
    tail_bytes = min(size, 4096)
    with path.open("rb") as source:
        source.seek(size - tail_bytes)
        tail = source.read(tail_bytes)
    index = tail.rfind(FOOTER_MAGIC)
    if index < 0:
        return None
    return _read_footer(io.BytesIO(tail[index:]))


def build_manifest(
    *,
    kind: BackupKind,
    radd_version: str,
    schema_version: int,
    alembic_revision: str | None,
    pg_server_version: str,
    includes_attachments: bool,
    key: BackupKey | None,
    created_by: str | None = None,
    schedule_id: str | None = None,
) -> Manifest:
    encrypted = key is not None
    return Manifest(
        created_at=datetime.now(UTC).isoformat(),
        kind=kind.value,
        radd_version=radd_version,
        schema_version=schema_version,
        alembic_revision=alembic_revision,
        pg_server_version=pg_server_version,
        encryption=crypto.ENCRYPTION_ALGORITHM if encrypted else crypto.ENCRYPTION_NONE,
        key_id=key.key_id if key else None,
        base_nonce=base64.b64encode(crypto.new_base_nonce()).decode(),
        chunk_bytes=crypto.CHUNK_BYTES,
        includes_attachments=includes_attachments,
        created_by=created_by,
        schedule_id=schedule_id,
    )
