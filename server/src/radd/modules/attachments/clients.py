"""Per-host storage clients (spec 102) — the request-path implementation of the
kernel's STORAGE_BACKEND socket.

One client instance per host row, cached on `(host.id, host.updated_at)` so an
admin edit invalidates it. Both types deal in `storage_name` (uuid hex) and a
rewindable buffered stream; delivery honors the host's mode (proxy bytes
through the API, or 307 to a short presigned URL minted with the host's own
credentials — network reachability then decides who can actually fetch).
"""

import asyncio
import logging
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import BinaryIO, Protocol, runtime_checkable

from fastapi import UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response

from radd.config import settings

from .models import Attachment, StorageHost
from .types import AttachmentTooLarge, DeliveryMode, serves_inline

logger = logging.getLogger(__name__)

_CHUNK_BYTES = 1 << 20  # 1 MiB
_SPOOL_BYTES = 8 << 20  # spill buffered uploads to disk past 8 MiB


@dataclass(frozen=True)
class BlobStat:
    size_bytes: int
    etag: str | None


@dataclass(frozen=True)
class HostHealth:
    ok: bool
    detail: str = ""


@runtime_checkable
class StorageClient(Protocol):
    """What every host type implements; registered on the STORAGE_BACKEND socket
    as a class taking the StorageHost row."""

    async def save(self, storage_name: str, source: BinaryIO, *, size: int, content_type: str) -> None: ...
    async def remove(self, storage_name: str) -> None: ...
    async def read(self, storage_name: str) -> bytes: ...
    async def stat(self, storage_name: str) -> BlobStat: ...
    async def response(self, attachment: Attachment) -> Response: ...
    async def ensure_ready(self) -> None: ...
    async def health(self) -> HostHealth: ...


async def buffer_upload(upload: UploadFile) -> tuple[BinaryIO, int]:
    """Read an incoming upload ONCE into a rewindable spooled buffer, enforcing
    the size cap. The buffer feeds routing (LLM rules read bytes) and the host
    write without re-reading the wire."""
    limit = settings.attachment_max_bytes
    buffer = tempfile.SpooledTemporaryFile(max_size=_SPOOL_BYTES)
    size = 0
    while chunk := await upload.read(_CHUNK_BYTES):
        size += len(chunk)
        if size > limit:
            buffer.close()
            raise AttachmentTooLarge(limit)
        buffer.write(chunk)
    buffer.seek(0)
    return buffer, size


class FilesystemClient:
    def __init__(self, host: StorageHost):
        self._root = Path(host.root_dir or settings.attachments_dir)

    def _path(self, storage_name: str) -> Path:
        return self._root / storage_name

    async def save(self, storage_name: str, source: BinaryIO, *, size: int, content_type: str) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        path = self._path(storage_name)
        try:
            await asyncio.to_thread(self._write, path, source)
        except BaseException:
            path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _write(path: Path, source: BinaryIO) -> None:
        with path.open("wb") as target:
            shutil.copyfileobj(source, target, _CHUNK_BYTES)

    async def remove(self, storage_name: str) -> None:
        self._path(storage_name).unlink(missing_ok=True)

    async def read(self, storage_name: str) -> bytes:
        return await asyncio.to_thread(self._path(storage_name).read_bytes)

    async def stat(self, storage_name: str) -> BlobStat:
        stat = await asyncio.to_thread(self._path(storage_name).stat)
        return BlobStat(size_bytes=stat.st_size, etag=None)

    async def response(self, attachment: Attachment) -> Response:
        inline = serves_inline(attachment.content_type)
        return FileResponse(
            self._path(attachment.storage_name),
            media_type=attachment.content_type,
            filename=None if inline else attachment.filename,
            content_disposition_type="inline" if inline else "attachment",
            headers={"X-Content-Type-Options": "nosniff"},
        )

    async def ensure_ready(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)

    async def health(self) -> HostHealth:
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            probe = self._root / f".radd-health-{uuid.uuid4().hex[:8]}"
            probe.write_bytes(b"ok")
            probe.unlink()
        except OSError as exc:
            return HostHealth(ok=False, detail=str(exc))
        return HostHealth(ok=True)


class S3Client:
    """MinIO SDK (sync, wrapped in to_thread) against any S3-compatible endpoint —
    Garage is the blessed server (docs/deploy.md), the code is server-agnostic."""

    def __init__(self, host: StorageHost):
        from minio import Minio

        self._bucket = host.bucket
        self._delivery = DeliveryMode(host.delivery_mode)
        self._expiry = host.presign_expiry_seconds or settings.s3_presign_expiry_seconds
        self._client = Minio(
            host.endpoint,
            access_key=host.access_key,
            secret_key=host.secret_key,
            secure=host.secure,
            region=host.region or None,
        )

    async def save(self, storage_name: str, source: BinaryIO, *, size: int, content_type: str) -> None:
        await asyncio.to_thread(
            self._client.put_object,
            self._bucket,
            storage_name,
            source,
            length=size,
            content_type=content_type,
        )

    async def remove(self, storage_name: str) -> None:
        await asyncio.to_thread(self._client.remove_object, self._bucket, storage_name)

    async def read(self, storage_name: str) -> bytes:
        def _read() -> bytes:
            response = self._client.get_object(self._bucket, storage_name)
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()

        return await asyncio.to_thread(_read)

    async def stat(self, storage_name: str) -> BlobStat:
        stat = await asyncio.to_thread(self._client.stat_object, self._bucket, storage_name)
        return BlobStat(size_bytes=stat.size or 0, etag=stat.etag)

    async def response(self, attachment: Attachment) -> Response:
        inline = serves_inline(attachment.content_type)
        if self._delivery is DeliveryMode.PRESIGNED:
            disposition = (
                "inline"
                if inline
                else f'attachment; filename="{attachment.filename.replace(chr(34), "")}"'
            )
            url = await asyncio.to_thread(
                self._client.presigned_get_object,
                self._bucket,
                attachment.storage_name,
                expires=timedelta(seconds=self._expiry),
                response_headers={
                    "response-content-disposition": disposition,
                    "response-content-type": attachment.content_type,
                },
            )
            return RedirectResponse(url, status_code=307)
        # Proxy: bounded by the upload cap, so a full read is fine — and it keeps
        # the S3 endpoint invisible to browsers (headers match the fs path).
        data = await self.read(attachment.storage_name)
        disposition = "inline" if inline else "attachment"
        filename = "" if inline else f'; filename="{attachment.filename.replace(chr(34), "")}"'
        return Response(
            content=data,
            media_type=attachment.content_type,
            headers={
                "X-Content-Type-Options": "nosniff",
                "Content-Disposition": f"{disposition}{filename}",
            },
        )

    async def ensure_ready(self) -> None:
        def _ensure() -> None:
            if not self._client.bucket_exists(self._bucket):
                self._client.make_bucket(self._bucket)
                logger.info("attachments: created bucket %s", self._bucket)

        await asyncio.to_thread(_ensure)

    async def health(self) -> HostHealth:
        try:
            exists = await asyncio.to_thread(self._client.bucket_exists, self._bucket)
        except Exception as exc:  # noqa: BLE001 — any SDK/network failure is the answer
            detail = str(exc)
            # SigV4 scope mismatch reads as gibberish; name the actual knob.
            if "AuthorizationHeaderMalformed" in detail or "unexpected scope" in detail:
                detail += (
                    " — the host's Region must match the server's configured "
                    "region (Garage's default is 'garage')"
                )
            return HostHealth(ok=False, detail=detail)
        if not exists:
            return HostHealth(ok=False, detail=f"bucket {self._bucket!r} does not exist")
        return HostHealth(ok=True)


# --- per-host resolution (socket-backed) --------------------------------------

_cache: dict[uuid.UUID, tuple[object, StorageClient]] = {}


def client_for(host: StorageHost) -> StorageClient:
    """The cached client for a host row; edited hosts (updated_at moved) rebuild."""
    cached = _cache.get(host.id)
    if cached is not None and cached[0] == host.updated_at:
        return cached[1]
    from radd.kernel import sockets

    factory = sockets.provider(sockets.Socket.STORAGE_BACKEND, host.host_type)
    if factory is None:  # a plugin host type whose plugin is gone
        raise RuntimeError(f"no storage backend registered for {host.host_type!r}")
    client = factory(host)
    _cache[host.id] = (host.updated_at, client)
    return client


async def ensure_all_ready() -> None:
    """Startup: ensure every host's bucket/dir, logging failures instead of
    failing boot — an unreachable zoned host must not stop the server."""
    from radd.db import SessionLocal

    from . import hosts as hosts_service

    async with SessionLocal() as session:
        all_hosts = await hosts_service.list_hosts(session)
    for host in all_hosts:
        try:
            await client_for(host).ensure_ready()
        except Exception:  # noqa: BLE001
            logger.warning("attachments: storage host %r is not ready", host.name, exc_info=True)
