"""Runner behavior: plugin load/hot-reload, dispatch isolation, offsets."""

import os
from pathlib import Path

from conftest import StubClient, make_event

from radd_sdk.runner import Runner, load_checkpoint

RECORDER = """\
from pathlib import Path

def register(reg):
    reg.on("*", handle)

def handle(client, event):
    with (Path(__file__).parent / "hits.log").open("a") as f:
        f.write(f"{TAG}:{event.id}\\n")

TAG = "v1"
"""

BOOM = """\
def register(reg):
    reg.on("*", handle)

def handle(client, event):
    raise RuntimeError("plugin blew up")
"""


def _hits(plugins_dir: Path) -> list[str]:
    log = plugins_dir / "hits.log"
    return log.read_text().splitlines() if log.exists() else []


def _runner(client: StubClient, tmp_path: Path, **kwargs) -> Runner:
    plugins = tmp_path / "plugins"
    plugins.mkdir(exist_ok=True)
    kwargs.setdefault("from_start", True)
    return Runner(client, plugins_dir=plugins, state_path=tmp_path / "state.json", **kwargs)


def test_load_dispatch_and_checkpoint(tmp_path: Path) -> None:
    client = StubClient([[make_event(1), make_event(2)]])
    runner = _runner(client, tmp_path)
    (runner.plugins_dir / "recorder.py").write_text(RECORDER)

    assert runner.poll_once() == 2
    assert _hits(runner.plugins_dir) == ["v1:1", "v1:2"]
    assert runner.offset == 2
    assert load_checkpoint(runner.state_path) == 2
    # next poll asks for events after the checkpointed offset
    assert runner.poll_once() == 0
    assert client.polled_after == [0, 2]


def test_hot_reload_on_mtime_change(tmp_path: Path) -> None:
    client = StubClient([[make_event(1)], [make_event(2)]])
    runner = _runner(client, tmp_path)
    plugin = runner.plugins_dir / "recorder.py"
    plugin.write_text(RECORDER)
    runner.poll_once()

    plugin.write_text(RECORDER.replace('TAG = "v1"', 'TAG = "v2"'))
    stat = plugin.stat()
    os.utime(plugin, (stat.st_atime, stat.st_mtime + 10))  # force an mtime change
    runner.poll_once()

    assert _hits(runner.plugins_dir) == ["v1:1", "v2:2"]


def test_raising_plugin_does_not_stop_others_or_loop(tmp_path: Path) -> None:
    client = StubClient([[make_event(1), make_event(2)]])
    runner = _runner(client, tmp_path)
    (runner.plugins_dir / "a_boom.py").write_text(BOOM)  # sorts (and fails) first
    (runner.plugins_dir / "b_recorder.py").write_text(RECORDER)

    assert runner.poll_once() == 2  # no exception escapes
    assert _hits(runner.plugins_dir) == ["v1:1", "v1:2"]  # recorder saw every event
    assert load_checkpoint(runner.state_path) == 2  # batch still checkpointed


def test_broken_plugin_file_is_skipped(tmp_path: Path) -> None:
    client = StubClient([[make_event(1)]])
    runner = _runner(client, tmp_path)
    (runner.plugins_dir / "bad.py").write_text("this is ( not python")
    (runner.plugins_dir / "no_register.py").write_text("x = 1\n")
    (runner.plugins_dir / "recorder.py").write_text(RECORDER)

    assert runner.poll_once() == 1
    assert [p.name for p in runner.plugins] == ["recorder"]
    assert _hits(runner.plugins_dir) == ["v1:1"]


def test_deleted_plugin_is_dropped(tmp_path: Path) -> None:
    client = StubClient([[make_event(1)], [make_event(2)]])
    runner = _runner(client, tmp_path)
    plugin = runner.plugins_dir / "recorder.py"
    plugin.write_text(RECORDER)
    runner.poll_once()
    plugin.unlink()
    runner.poll_once()
    assert _hits(runner.plugins_dir) == ["v1:1"]  # event 2 had no plugin to hit
    assert runner.plugins == []


def test_resume_from_saved_checkpoint(tmp_path: Path) -> None:
    from radd_sdk.runner import save_checkpoint

    state = tmp_path / "state.json"
    save_checkpoint(state, 7)
    client = StubClient()
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    runner = Runner(client, plugins_dir=plugins, state_path=state)
    assert runner.offset == 7
    runner.poll_once()
    assert client.polled_after == [7]


def test_no_checkpoint_starts_at_head_without_dispatch(tmp_path: Path) -> None:
    # head discovery pages the stream (two pages here) but never dispatches
    client = StubClient([[make_event(1), make_event(2)], [make_event(3)], []])
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    (plugins / "recorder.py").write_text(RECORDER)
    runner = Runner(client, plugins_dir=plugins, state_path=tmp_path / "state.json")
    assert runner.offset == 3
    assert _hits(plugins) == []


def test_from_start_begins_at_zero(tmp_path: Path) -> None:
    client = StubClient()
    runner = _runner(client, tmp_path, from_start=True)
    assert runner.offset == 0
    assert client.polled_after == []  # no head probe when starting from 0
