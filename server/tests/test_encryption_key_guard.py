"""Startup refuses an encryption key the database was not written with (RADD-1525).

`crypto.load_key` creates a missing key file. That is right on a fresh instance
and catastrophic on any other: the Helm chart in S3 mode mounted no volume for
the key, so a pod restart minted a new one, the server started, and every
backup and stored credential was unreadable behind one warning line.

The record row is committed state, so each test clears it before and after.
"""

import pytest
from sqlalchemy import text

from radd import secretbox
from radd.backup import crypto, keyguard
from radd.config import settings
from radd.db import engine


async def _recorded() -> str | None:
    async with engine.connect() as connection:
        return (
            await connection.execute(text("SELECT key_id FROM encryption_key_record WHERE id = 1"))
        ).scalar_one_or_none()


async def _forget() -> None:
    async with engine.begin() as connection:
        await connection.execute(text("DELETE FROM encryption_key_record"))


@pytest.fixture
async def key_file(tmp_path, monkeypatch):
    path = tmp_path / "data" / "radd-backup.key"
    monkeypatch.setattr(settings, "backup_key_file", str(path))
    monkeypatch.setattr(settings, "backup_key_adopt", False)
    secretbox.reset_key_cache()
    await _forget()
    yield path
    await _forget()
    secretbox.reset_key_cache()


async def test_a_fresh_instance_creates_its_key_and_records_it(key_file):
    assert not key_file.exists()
    await keyguard.preflight()
    assert key_file.exists()
    assert await _recorded() == crypto.load_key(create=False).key_id


async def test_the_same_key_starts_every_time(key_file):
    await keyguard.preflight()
    first = await _recorded()
    await keyguard.preflight()
    assert await _recorded() == first


async def test_a_missing_key_file_refuses_to_start_instead_of_minting_one(key_file):
    await keyguard.preflight()
    recorded = await _recorded()
    key_file.unlink()  # the pod restarted on a volume that was never mounted

    with pytest.raises(keyguard.EncryptionKeyMismatch) as refused:
        await keyguard.preflight()

    assert recorded in str(refused.value) and str(key_file) in str(refused.value)
    assert not key_file.exists(), "a replacement key was generated on the way to refusing"
    assert await _recorded() == recorded


async def test_a_different_key_file_refuses_to_start_and_names_both(key_file):
    await keyguard.preflight()
    recorded = await _recorded()
    key_file.unlink()
    other = crypto.load_key().key_id  # somebody restored the wrong file
    assert other != recorded

    with pytest.raises(keyguard.EncryptionKeyMismatch) as refused:
        await keyguard.preflight()

    assert recorded in str(refused.value) and other in str(refused.value)
    assert await _recorded() == recorded


async def test_adopt_is_the_explicit_way_past_a_lost_key(key_file, monkeypatch):
    await keyguard.preflight()
    recorded = await _recorded()
    key_file.unlink()
    monkeypatch.setattr(settings, "backup_key_adopt", True)

    await keyguard.preflight()

    adopted = await _recorded()
    assert adopted != recorded and adopted == crypto.load_key(create=False).key_id
