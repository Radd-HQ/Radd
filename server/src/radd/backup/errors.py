"""One base for every backup failure.

`BackupError` lives in its own module so the lower layers (`crypto`, `artifact`,
`postgres`) can subclass it without importing `service`, which imports them.
Everything a backup or restore can go wrong with is therefore catchable in one
clause — the CLI prints it, and the router turns it into a 409 with the reason.
Every message is written for an operator, not a stack trace reader.
"""


class BackupError(Exception):
    """A backup or restore could not proceed. The message is the explanation."""
