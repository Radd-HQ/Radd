"""Glob matching: exact types, `item.*` prefixes, catch-all `*`."""

from radd_sdk.runner import Registry


def _cb(name: str):
    def callback(client, event) -> None:  # pragma: no cover - never dispatched here
        pass

    callback.__name__ = name
    return callback


def test_exact_prefix_and_catchall_globs() -> None:
    reg = Registry()
    reg.on("item.*", _cb("items"))
    reg.on("*", _cb("all"))
    reg.on("sla.breached", _cb("exact"))

    assert [cb.__name__ for cb in reg.matches("item.created")] == ["items", "all"]
    assert [cb.__name__ for cb in reg.matches("sla.breached")] == ["all", "exact"]
    assert [cb.__name__ for cb in reg.matches("comment.created")] == ["all"]


def test_no_match_returns_empty() -> None:
    reg = Registry()
    reg.on("item.*", _cb("items"))
    assert reg.matches("release.created") == []
    # `item.*` must not match the bare prefix without a dot segment
    assert reg.matches("items") == []
