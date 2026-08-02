"""Reciprocal rank fusion (spec 103) — pure, unit-tested.

RRF combines rankings WITHOUT comparable scores: each list contributes
1/(k + rank) per member, so an item near the top of either list surfaces, and
one near the top of BOTH dominates. k=60 is the literature default — it damps
the difference between rank 1 and rank 5 enough that neither ranker bullies
the other (research/architecture.md: hybrid ≈ 62%→84% precision over either
alone).
"""

from collections.abc import Hashable, Sequence

RRF_K = 60


def rrf_fuse[K: Hashable](
    rankings: Sequence[Sequence[K]], *, k: int = RRF_K
) -> list[tuple[K, float]]:
    """Fuse ordered rankings -> [(key, score)] best-first. Ties break by first
    appearance so the output is deterministic."""
    scores: dict[K, float] = {}
    first_seen: dict[K, int] = {}
    order = 0
    for ranking in rankings:
        for rank, key in enumerate(ranking):
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
            if key not in first_seen:
                first_seen[key] = order
                order += 1
    return sorted(scores.items(), key=lambda pair: (-pair[1], first_seen[pair[0]]))
