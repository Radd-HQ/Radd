"""Artifact container + encryption (spec 99 §§1-2).

Pure — no database, no Postgres binaries. These are the invariants the whole
feature rests on: an artifact must round-trip exactly, and every way of
tampering with one must fail CLOSED rather than yielding partial plaintext.
"""

import base64
import io
import tarfile

import pytest

from radd.backup import artifact as art, crypto
from radd.backup.crypto import ArtifactCorrupt, BackupKey, BackupKeyError
from radd.backup.types import BackupKind

PAYLOAD = b"radd-backup-payload-" * 5000  # ~100 KB, several chunks at 8 KiB


def _key(seed: bytes = b"\x01") -> BackupKey:
    return BackupKey.from_material(seed * 32)


def _manifest(key: BackupKey | None, *, chunk_bytes: int = 8192) -> art.Manifest:
    manifest = art.build_manifest(
        kind=BackupKind.MANUAL,
        radd_version="0.1.0",
        schema_version=1,
        alembic_revision="abc123",
        pg_server_version="16.4",
        includes_attachments=False,
        key=key,
    )
    # Small chunks so the multi-chunk paths are exercised by a small payload.
    return art.Manifest(**{**manifest.__dict__, "chunk_bytes": chunk_bytes})


def _write(path, key: BackupKey | None, payload: bytes = PAYLOAD, **kwargs) -> art.Manifest:
    manifest = _manifest(key, **kwargs)
    with art.write_artifact(path, manifest, key=key) as tar:
        info = tarfile.TarInfo(art.DUMP_MEMBER)
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    return manifest


def _read(path, manifest: art.Manifest, key: BackupKey | None) -> bytes:
    with art.read_artifact(path, manifest, key=key) as tar:
        member = tar.next()
        assert member is not None
        return tar.extractfile(member).read()


# --- round trip ---


def test_round_trip_encrypted(tmp_path):
    path = tmp_path / art.new_artifact_name()
    key = _key()
    manifest = _write(path, key)

    assert manifest.encrypted
    assert _read(path, manifest, key) == PAYLOAD


def test_round_trip_unencrypted(tmp_path):
    path = tmp_path / art.new_artifact_name()
    manifest = _write(path, None)

    assert not manifest.encrypted
    assert _read(path, manifest, None) == PAYLOAD


@pytest.mark.parametrize("size", [0, 1, 8192, 8193, 40000])
def test_round_trip_at_chunk_boundaries(tmp_path, size):
    """Empty, sub-chunk, exactly one chunk, one byte over, and several."""
    path = tmp_path / art.new_artifact_name()
    key = _key()
    payload = b"x" * size
    manifest = _write(path, key, payload)

    assert _read(path, manifest, key) == payload


def test_manifest_is_readable_without_the_key(tmp_path):
    """Listing the backups page must work with no key present."""
    path = tmp_path / art.new_artifact_name()
    _write(path, _key())

    manifest = art.read_manifest(path)
    assert manifest.kind == BackupKind.MANUAL
    assert manifest.encrypted and manifest.key_id == _key().key_id
    # ...but the payload is not recoverable from the file alone.
    assert PAYLOAD[:64] not in path.read_bytes()


def test_footer_records_the_plaintext_size_and_hash(tmp_path):
    path = tmp_path / art.new_artifact_name()
    _write(path, _key())

    footer = art.read_footer(path)
    assert footer is not None
    assert footer.payload_bytes >= len(PAYLOAD)  # tar framing rounds up
    assert len(footer.payload_sha256) == 64


# --- every tamper must fail closed ---


def test_wrong_key_is_rejected(tmp_path):
    path = tmp_path / art.new_artifact_name()
    manifest = _write(path, _key(b"\x01"))

    with pytest.raises(ArtifactCorrupt):
        _read(path, manifest, _key(b"\x02"))


def test_flipped_byte_in_the_payload_is_rejected(tmp_path):
    path = tmp_path / art.new_artifact_name()
    key = _key()
    manifest = _write(path, key)

    raw = bytearray(path.read_bytes())
    raw[-200] ^= 0xFF  # inside the sealed payload, before the footer
    path.write_bytes(raw)

    with pytest.raises(ArtifactCorrupt):
        _read(path, manifest, key)


def test_truncated_payload_is_rejected(tmp_path):
    """The last chunk is the only one sealed as final, so a stream that stops
    early can never authenticate — no partial plaintext escapes."""
    path = tmp_path / art.new_artifact_name()
    key = _key()
    manifest = _write(path, key)

    raw = path.read_bytes()
    path.write_bytes(raw[: len(raw) // 2])

    with pytest.raises(ArtifactCorrupt):
        _read(path, manifest, key)


def test_tampering_with_the_manifest_breaks_the_payload(tmp_path):
    """The manifest's digest is the AAD for every chunk, so editing the header
    invalidates the payload rather than silently changing what it claims."""
    path = tmp_path / art.new_artifact_name()
    key = _key()
    manifest = _write(path, key)

    raw = path.read_bytes()
    edited = raw.replace(b'"radd_version":"0.1.0"', b'"radd_version":"9.9.9"')
    assert edited != raw
    path.write_bytes(edited)

    with pytest.raises(ArtifactCorrupt):
        _read(path, art.read_manifest(path), key)


def test_chunk_spliced_from_another_artifact_is_rejected(tmp_path):
    """Same key, same nonce position, different artifact: the manifest digest in
    the AAD is what stops the graft."""
    key = _key()
    first = tmp_path / art.new_artifact_name()
    second = tmp_path / "radd-20260101-000000-deadbeef.radd"
    manifest_one = _write(first, key, b"a" * 40000)
    _write(second, key, b"b" * 40000)

    raw_one = bytearray(first.read_bytes())
    raw_two = second.read_bytes()
    # Graft a mid-payload slice across; both headers are the same length, so the
    # offsets line up and only the AAD binding can catch it.
    start = len(raw_one) // 2
    raw_one[start : start + 4096] = raw_two[start : start + 4096]
    first.write_bytes(bytes(raw_one))

    with pytest.raises(ArtifactCorrupt):
        _read(first, manifest_one, key)


def test_missing_footer_reports_an_unfinished_backup(tmp_path):
    """A crash mid-dump leaves a footerless file; it must not look restorable."""
    path = tmp_path / art.new_artifact_name()
    key = _key()
    manifest = _write(path, key)

    raw = path.read_bytes()
    path.write_bytes(raw[: raw.rfind(art.FOOTER_MAGIC)])

    assert art.read_footer(path) is None
    with pytest.raises(ArtifactCorrupt):
        _read(path, manifest, key)


def test_not_an_artifact_at_all(tmp_path):
    path = tmp_path / art.new_artifact_name()
    path.write_bytes(b"this is a text file, not a backup")

    with pytest.raises(art.ArtifactInvalid):
        art.read_manifest(path)


# --- names are filenames, never paths ---


@pytest.mark.parametrize(
    "name",
    [
        "../../etc/passwd",
        "/etc/passwd",
        "radd-20260101-000000-deadbeef.radd/../escape",
        "radd-2026-01-01-000000-deadbeef.radd",
        "radd-20260101-000000-DEADBEEF.radd",
        "radd-20260101-000000-deadbeef.tar",
        "",
    ],
)
def test_invalid_artifact_names_are_refused(tmp_path, name):
    assert not art.is_valid_name(name)
    with pytest.raises(art.ArtifactInvalid):
        art.resolve_in(tmp_path, name)


def test_generated_names_are_valid_and_unique():
    names = {art.new_artifact_name() for _ in range(50)}
    assert len(names) == 50
    assert all(art.is_valid_name(name) for name in names)


# --- the key file ---


def test_key_is_created_once_with_0600(tmp_path):
    path = tmp_path / "nested" / "backup.key"

    first = crypto.load_key(str(path))
    assert path.stat().st_mode & 0o777 == 0o600
    assert crypto.load_key(str(path)).material == first.material  # stable across loads


def test_key_permissions_are_reasserted_on_load(tmp_path):
    path = tmp_path / "backup.key"
    crypto.load_key(str(path))
    path.chmod(0o644)

    crypto.load_key(str(path))
    assert path.stat().st_mode & 0o777 == 0o600


def test_missing_key_can_be_required_rather_than_created(tmp_path):
    with pytest.raises(BackupKeyError):
        crypto.load_key(str(tmp_path / "absent.key"), create=False)


def test_malformed_key_is_an_error_not_a_silent_regeneration(tmp_path):
    path = tmp_path / "backup.key"
    path.write_bytes(b"not base64 !!!")

    with pytest.raises(BackupKeyError):
        crypto.load_key(str(path))


def test_key_id_identifies_the_key_without_revealing_it(tmp_path):
    key = _key()
    assert len(key.key_id) == 8
    assert base64.b64encode(key.material).decode() not in key.key_id
    assert _key(b"\x02").key_id != key.key_id
