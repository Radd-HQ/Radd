"""Artifact encryption (spec 99 §1) — AES-256-GCM over a chunked stream.

A backup holds password hashes, TOTP seeds, API tokens and every comment, so the
security property that matters is that the FILE is useless without the key.
Encryption therefore wraps the whole payload rather than individual columns.

The stream is chunked (1 MiB) and exposed as FILE-LIKE OBJECTS, so `tarfile` can
write straight through the sealer and read straight out of the opener. Nothing
is ever staged twice: a 40 GB instance does not need 40 GB of scratch space.

Independent chunks would normally let an attacker reorder, drop or splice them,
so every chunk's AAD binds three things:

    <manifest sha256> : <chunk index> : <is this the last chunk>

Reordering breaks the index; truncation breaks the final flag (the last chunk is
the only one sealed with `1`, and the reader demands one); a chunk lifted from
another artifact breaks the manifest hash. Nonces are `base_nonce(8) || counter(4)`
— unique per chunk within an artifact, and per artifact by the random base.

Sealing holds ONE chunk back: chunk *i* is only emitted once we know something
follows it, which is how the writer learns which chunk is last without seeking.

The key is 32 raw bytes, stored base64 in `settings.backup_key_file`, created on
first use with mode 0600. `key_id` is the first 8 hex of its sha256 — enough to
tell two keys apart in a manifest, not enough to attack the key.
"""

import base64
import hashlib
import io
import logging
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .errors import BackupError

logger = logging.getLogger(__name__)

CHUNK_BYTES = 1 << 20
KEY_BYTES = 32
BASE_NONCE_BYTES = 8
_COUNTER_BYTES = 4
_TAG_BYTES = 16
_LENGTH_BYTES = 4
ENCRYPTION_ALGORITHM = "aes-256-gcm"
ENCRYPTION_NONE = "none"


class BackupKeyError(BackupError):
    """The key file is missing, malformed, or is not the artifact's key."""


class ArtifactCorrupt(BackupError):
    """Authentication failed: wrong key, tampered bytes, or reordered chunks."""


@dataclass(frozen=True)
class BackupKey:
    """32 raw bytes plus the short id that names them in a manifest."""

    material: bytes
    key_id: str

    @classmethod
    def from_material(cls, material: bytes) -> "BackupKey":
        if len(material) != KEY_BYTES:
            raise BackupKeyError(f"backup key must be {KEY_BYTES} bytes, got {len(material)}")
        return cls(material, hashlib.sha256(material).hexdigest()[:8])


def generate_key() -> bytes:
    return secrets.token_bytes(KEY_BYTES)


def new_base_nonce() -> bytes:
    return secrets.token_bytes(BASE_NONCE_BYTES)


def load_key(path: str | None = None, *, create: bool = True) -> BackupKey:
    """The instance's backup key, created on first use.

    Written 0600, and 0600 is re-asserted on every load: a key file that has
    turned world-readable is a finding, not a shrug. Creation is logged loudly —
    an operator who never learns the key exists cannot back it up, and without
    it every artifact is unrecoverable.
    """
    from radd.config import settings

    key_path = Path(path or settings.backup_key_file)
    if key_path.exists():
        try:
            material = base64.b64decode(key_path.read_bytes().strip(), validate=True)
        except Exception as exc:  # noqa: BLE001 — every decode failure is one error
            raise BackupKeyError(f"backup key at {key_path} is not valid base64") from exc
        key_path.chmod(0o600)
        return BackupKey.from_material(material)

    if not create:
        raise BackupKeyError(f"no backup key at {key_path}")
    key_path.parent.mkdir(parents=True, exist_ok=True)
    material = generate_key()
    # O_EXCL + 0600 at creation: never even briefly world-readable.
    descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(base64.b64encode(material))
    logger.warning(
        "generated a new backup encryption key at %s — BACK THIS FILE UP, and keep "
        "it somewhere other than %s; without it every backup is unrecoverable",
        key_path,
        settings.backup_dir,
    )
    return BackupKey.from_material(material)


def _nonce(base_nonce: bytes, index: int) -> bytes:
    return base_nonce + index.to_bytes(_COUNTER_BYTES, "big")


def _aad(header_digest: str, index: int, final: bool) -> bytes:
    return f"{header_digest}:{index}:{int(final)}".encode()


class ChunkSealer(io.RawIOBase):
    """Write-through file object that seals whole chunks into `target`.

    Holds one chunk back so the final one can be sealed with the end marker.
    `finalize()` flushes it and returns (plaintext bytes, plaintext sha256) —
    the caller records both in the manifest.
    """

    def __init__(
        self,
        target: BinaryIO,
        *,
        key: BackupKey,
        base_nonce: bytes,
        header_digest: str,
        chunk_bytes: int = CHUNK_BYTES,
    ) -> None:
        self._target = target
        self._aesgcm = AESGCM(key.material)
        self._base_nonce = base_nonce
        self._header_digest = header_digest
        self._chunk_bytes = chunk_bytes
        self._buffer = bytearray()
        self._held: bytes | None = None
        self._index = 0
        self._digest = hashlib.sha256()
        self._total = 0
        self._finalized = False

    def writable(self) -> bool:
        return True

    def write(self, data) -> int:  # noqa: ANN001 — RawIOBase signature
        payload = bytes(data)
        self._buffer.extend(payload)
        while len(self._buffer) >= self._chunk_bytes:
            self._offer(bytes(self._buffer[: self._chunk_bytes]))
            del self._buffer[: self._chunk_bytes]
        return len(payload)

    def _offer(self, chunk: bytes) -> None:
        """Queue a chunk, emitting the previously held one as non-final."""
        if self._held is not None:
            self._emit(self._held, final=False)
        self._held = chunk

    def _emit(self, chunk: bytes, *, final: bool) -> None:
        self._digest.update(chunk)
        self._total += len(chunk)
        sealed = self._aesgcm.encrypt(
            _nonce(self._base_nonce, self._index), chunk, _aad(self._header_digest, self._index, final)
        )
        self._target.write(len(sealed).to_bytes(_LENGTH_BYTES, "big"))
        self._target.write(sealed)
        self._index += 1

    def finalize(self) -> tuple[int, str]:
        if self._finalized:
            raise RuntimeError("sealer already finalized")
        self._finalized = True
        if self._buffer:
            self._offer(bytes(self._buffer))
            self._buffer.clear()
        # An empty payload still gets one (empty) final chunk, so the reader's
        # "must end on a final chunk" rule holds for every artifact.
        self._emit(self._held if self._held is not None else b"", final=True)
        self._held = None
        return self._total, self._digest.hexdigest()


class ChunkOpener(io.RawIOBase):
    """Read-through file object that opens a sealed stream from `source`.

    Every failure mode surfaces as `ArtifactCorrupt`: wrong key, flipped byte,
    reordered or duplicated chunk, a chunk spliced in from another artifact, and
    truncation — the stream must end on a chunk sealed as final.
    """

    def __init__(self, source: BinaryIO, *, key: BackupKey, base_nonce: bytes, header_digest: str) -> None:
        self._source = source
        self._aesgcm = AESGCM(key.material)
        self._base_nonce = base_nonce
        self._header_digest = header_digest
        self._buffer = bytearray()
        self._index = 0
        self._digest = hashlib.sha256()
        self._total = 0
        self._done = False

    def readable(self) -> bool:
        return True

    def _fill(self) -> bool:
        """Open one more chunk into the buffer. False once the final one is in."""
        if self._done:
            return False
        length_bytes = self._source.read(_LENGTH_BYTES)
        if len(length_bytes) != _LENGTH_BYTES:
            raise ArtifactCorrupt("artifact ends without a final chunk (truncated)")
        sealed = self._source.read(int.from_bytes(length_bytes, "big"))
        if len(sealed) < _TAG_BYTES:
            raise ArtifactCorrupt("truncated chunk body")
        nonce = _nonce(self._base_nonce, self._index)
        # Try the non-final AAD first: a truncated stream then fails outright
        # rather than quietly decoding a valid-looking prefix.
        for final in (False, True):
            try:
                plain = self._aesgcm.decrypt(nonce, sealed, _aad(self._header_digest, self._index, final))
            except InvalidTag:
                continue
            break
        else:
            raise ArtifactCorrupt(
                f"chunk {self._index} failed authentication — wrong key, tampered, or reordered"
            )
        self._buffer.extend(plain)
        self._digest.update(plain)
        self._total += len(plain)
        self._index += 1
        self._done = final
        return True

    def read(self, size: int = -1) -> bytes:  # noqa: D102 — RawIOBase
        while (size < 0 or len(self._buffer) < size) and self._fill():
            pass
        if size < 0 or size >= len(self._buffer):
            out = bytes(self._buffer)
            self._buffer.clear()
            return out
        out = bytes(self._buffer[:size])
        del self._buffer[:size]
        return out

    def readinto(self, target) -> int:  # noqa: ANN001 — RawIOBase signature
        data = self.read(len(target))
        target[: len(data)] = data
        return len(data)

    def verify_complete(self) -> tuple[int, str]:
        """Drain and return (plaintext bytes, sha256). Raises if not terminated."""
        while self._fill():
            pass
        return self._total, self._digest.hexdigest()


class PlainSealer(io.RawIOBase):
    """`backup_encryption=false`: same interface, no sealing."""

    def __init__(self, target: BinaryIO) -> None:
        self._target = target
        self._digest = hashlib.sha256()
        self._total = 0

    def writable(self) -> bool:
        return True

    def write(self, data) -> int:  # noqa: ANN001
        payload = bytes(data)
        self._digest.update(payload)
        self._total += len(payload)
        self._target.write(payload)
        return len(payload)

    def finalize(self) -> tuple[int, str]:
        return self._total, self._digest.hexdigest()
