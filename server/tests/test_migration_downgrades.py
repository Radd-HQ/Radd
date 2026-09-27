"""Two migrations rewrite data the previous image cannot read back; their
`downgrade()` must refuse rather than report success (RADD-1453)."""

import importlib.util
from pathlib import Path

import pytest

VERSIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _load(prefix: str):
    (path,) = VERSIONS.glob(f"{prefix}*.py")
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("prefix", ["d1329verdict", "d1334review"])
def test_irreversible_migrations_refuse_to_downgrade(prefix: str) -> None:
    with pytest.raises(RuntimeError):
        _load(prefix).downgrade()


def test_d1318_no_longer_deletes_the_mail_settings_rows() -> None:
    (path,) = VERSIONS.glob("d1318mailorigin*.py")
    assert "DELETE FROM scoped_settings" not in path.read_text()
