"""Checkpoint save/load round-trip and corruption handling."""

from pathlib import Path

from radd_sdk.runner import load_checkpoint, save_checkpoint


def test_round_trip(tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    assert load_checkpoint(state) is None  # missing file
    save_checkpoint(state, 42)
    assert load_checkpoint(state) == 42
    save_checkpoint(state, 43)  # overwrite via atomic rename
    assert load_checkpoint(state) == 43
    assert not state.with_suffix(".json.tmp").exists()


def test_corrupt_file_ignored(tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    state.write_text("{not json")
    assert load_checkpoint(state) is None
    state.write_text("{}")  # valid JSON, no offset key
    assert load_checkpoint(state) is None
