"""A downloaded snapshot's files, on disk (spec 117).

Attachments used to go through the spec-102 blob API and out to the object
store. That is the right home for a page's attachments and the wrong one for a
DOWNLOAD: one real section pushed **49 GB** through Garage's S3 API to cache
bytes that might never be imported, and the download crawled.

A snapshot is a working file, not durable content. So it is a plain directory:

    <confluence_snapshot_dir>/<snapshot_id>/
        manifest.json                 what this package is
        attachments/<id>/<filename>   the bytes, under their real names

Which buys three things the object store could not. Deleting a snapshot is one
`rmtree` rather than N delete calls that can half-fail. An operator can look at
what was downloaded, copy a package between machines, or hand it to someone
else. And the bytes only reach the object store when a RUN imports them — the
point at which they stop being a cache and become attachments someone will read.
"""

from __future__ import annotations

import json
import logging
import shutil
import uuid
from pathlib import Path
from typing import BinaryIO

from radd.config import settings

logger = logging.getLogger(__name__)

MANIFEST_NAME = "manifest.json"
ATTACHMENTS_DIR = "attachments"


def root() -> Path:
    return Path(settings.confluence_snapshot_dir)


def package_dir(snapshot_id: uuid.UUID) -> Path:
    return root() / str(snapshot_id)


def attachment_path(snapshot_id: uuid.UUID, attachment_id: str, filename: str) -> Path:
    """Where one attachment's bytes live.

    Nested under the attachment id so two pages attaching different files with
    the SAME name cannot collide — which they do constantly ("image.png",
    "Screenshot.png"). The real filename is kept as the leaf, so the directory
    stays readable to a person.
    """
    return package_dir(snapshot_id) / ATTACHMENTS_DIR / attachment_id / _safe(filename)


def _safe(filename: str) -> str:
    """A filename that cannot escape the package.

    Confluence filenames are arbitrary user input, and one containing `../`
    would otherwise write outside the directory entirely.
    """
    leaf = Path(filename.replace("\\", "/")).name.strip() or "attachment"
    return leaf[:200]


def open_for_write(snapshot_id: uuid.UUID, attachment_id: str, filename: str) -> tuple[Path, BinaryIO]:
    path = attachment_path(snapshot_id, attachment_id, filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path, path.open("wb")


def relative(path: Path, snapshot_id: uuid.UUID) -> str:
    """Stored on the row as a RELATIVE path, so moving the package — or the whole
    snapshot directory — does not invalidate every row in it."""
    try:
        return str(path.relative_to(package_dir(snapshot_id)))
    except ValueError:
        return str(path)


def resolve(snapshot_id: uuid.UUID, file_path: str) -> Path:
    return package_dir(snapshot_id) / file_path


def write_manifest(snapshot_id: uuid.UUID, manifest: dict) -> None:
    directory = package_dir(snapshot_id)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2, default=str))


def read_manifest(snapshot_id: uuid.UUID) -> dict:
    path = package_dir(snapshot_id) / MANIFEST_NAME
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except ValueError:
        return {}


def size_bytes(snapshot_id: uuid.UUID) -> int:
    directory = package_dir(snapshot_id)
    if not directory.exists():
        return 0
    return sum(f.stat().st_size for f in directory.rglob("*") if f.is_file())


def remove(snapshot_id: uuid.UUID) -> None:
    """Delete the whole package. One call, and it cannot half-succeed the way N
    object-store deletes can."""
    directory = package_dir(snapshot_id)
    if not directory.exists():
        return
    try:
        shutil.rmtree(directory)
    except OSError:  # a locked file must not block deleting the snapshot row
        logger.warning("could not remove snapshot package %s", directory, exc_info=True)
