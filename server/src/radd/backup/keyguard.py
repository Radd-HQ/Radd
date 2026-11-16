"""The encryption key is checked against the database at startup (RADD-1525).

One key file encrypts every backup artifact and, through `radd.secretbox`,
every credential stored in the database. `crypto.load_key` creates the file
when it is missing, which is right exactly once: on a fresh instance. On any
later boot a missing file means the volume holding it was lost or never
mounted, and minting a replacement would leave an instance that starts
cleanly, logs one warning, and can decrypt nothing it holds.

So the database remembers WHICH key it was encrypted with. The first boot
records the key's short id; every later boot compares:

- no file, id recorded   → refuse to start, naming the key that is missing;
- file with another id   → refuse to start, naming both;
- file with the same id  → proceed.

`RADD_BACKUP_KEY_ADOPT=true` is the operator's explicit "that key is gone":
the present (or newly generated) key is recorded in its place. Everything
encrypted with the old one stays unreadable; this only lets the instance start.

Raw SQL, no ORM model: like the rest of `radd.backup` this must work where the
plugin registry has not loaded.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from . import crypto

logger = logging.getLogger(__name__)

#: One row, id 1 — see migration `d1525keyrecord`.
_SELECT = text("SELECT key_id FROM encryption_key_record WHERE id = 1")
_RECORD = text(
    "INSERT INTO encryption_key_record (id, key_id) VALUES (1, :key_id) "
    "ON CONFLICT (id) DO UPDATE SET key_id = EXCLUDED.key_id, recorded_at = now()"
)


class EncryptionKeyMismatch(RuntimeError):
    """The key on disk is not the one this database was encrypted with."""


async def preflight() -> None:
    """Startup gate: record the key on first boot, refuse a different one after."""
    from radd.config import settings
    from radd.db import engine

    key_path = Path(settings.backup_key_file)
    async with engine.begin() as connection:
        try:
            recorded = (await connection.execute(_SELECT)).scalar_one_or_none()
        except ProgrammingError:
            # No table: a database older than the migration, or an empty one about
            # to be restored into. Nothing is recorded, so there is nothing to guard.
            logger.info("encryption key not checked: encryption_key_record does not exist yet")
            return

        if recorded is None or settings.backup_key_adopt:
            key = crypto.load_key()  # creates it on a genuinely fresh instance
            if recorded is not None and recorded != key.key_id:
                logger.warning(
                    "RADD_BACKUP_KEY_ADOPT is set: replacing recorded encryption key %s with %s. "
                    "Backups and stored credentials encrypted with %s can no longer be read.",
                    recorded, key.key_id, recorded,
                )
            await connection.execute(_RECORD, {"key_id": key.key_id})
            return

        if not key_path.exists():
            raise EncryptionKeyMismatch(
                f"Radd cannot start: this database was encrypted with key {recorded}, and there "
                f"is no key file at {key_path}. A new key would start cleanly and decrypt nothing: "
                f"every backup and every stored credential (webhooks, SSO, mail, AI, connectors) "
                f"needs the original. Restore the key file, or check that the volume or Secret "
                f"holding it is mounted. If that key is truly gone, set RADD_BACKUP_KEY_ADOPT=true "
                f"to start with a new one and re-enter the credentials."
            )
        key = crypto.load_key(create=False)
        if key.key_id != recorded:
            raise EncryptionKeyMismatch(
                f"Radd cannot start: this database was encrypted with key {recorded}, but the key "
                f"at {key_path} is {key.key_id}. Put the original key file back. If that key is "
                f"truly gone, set RADD_BACKUP_KEY_ADOPT=true to adopt this one and re-enter the "
                f"stored credentials."
            )
