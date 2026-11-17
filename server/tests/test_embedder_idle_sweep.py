"""The embedder's reconcile sweep backs off when it finds nothing (RADD-1550).

It ran a 1.5 s anti-join every poll on a fully embedded 500k-item instance.
"""

from radd.config import settings
from radd.modules.ai.embeddings import embedder


def test_empty_sweeps_wait_longer_each_time_up_to_the_ceiling(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(embedder.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(settings, "ai_embedder_poll_interval", 3.0)
    monkeypatch.setattr(settings, "ai_embed_idle_sweep_max_seconds", 20.0)
    idle = embedder._IdleSweep()
    assert idle.due()  # a fresh process sweeps at once

    waits = []
    for _ in range(6):
        idle.swept(found=False)
        waits.append(idle.not_before - clock[0])
        assert not idle.due()
        clock[0] = idle.not_before
        assert idle.due()
    assert waits == [3.0, 6.0, 12.0, 20.0, 20.0, 20.0]


def test_work_resets_the_wait(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(embedder.time, "monotonic", lambda: clock[0])
    idle = embedder._IdleSweep()
    for _ in range(5):
        idle.swept(found=False)
    assert not idle.due()
    idle.reset()  # an event was consumed
    assert idle.due() and idle.wait == 0.0
    for _ in range(5):
        idle.swept(found=False)
    idle.swept(found=True)  # a sweep that found rows: keep draining
    assert idle.due()
