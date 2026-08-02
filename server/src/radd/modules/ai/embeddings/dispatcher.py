"""In-process embedder loop, mirroring the other outbox consumers. The async
gates (pgvector present, embeddings role assigned, feature toggle) live inside
run_once — the sync `enabled` lambda only covers the worker split."""

from radd.config import settings
from radd.worker import PeriodicLoop

from . import embedder

_loop = PeriodicLoop(
    embedder.run_once,
    interval=lambda: settings.ai_embedder_poll_interval,
    name="ai-embedder",
    enabled=lambda: settings.run_workers,  # web-only process skips (spec 48 worker split)
    # A backfill (first enable, big import, model swap) drains batch-after-batch;
    # the poll interval only paces the idle loop.
    drain=True,
)

start = _loop.start
stop = _loop.stop
