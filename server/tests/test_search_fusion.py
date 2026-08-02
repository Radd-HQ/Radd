"""Hybrid search fusion (spec 103): the RRF math (pure) and the graceful-off
property — /search with the ai module unavailable/unconfigured is byte-for-byte
the pre-103 FTS behavior (pinned by the whole existing test_search suite still
passing; here we pin the seams' failure modes)."""

import pytest

from radd.modules.search import fusion


def test_rrf_scores_and_ordering():
    fused = fusion.rrf_fuse([["a", "b", "c"], ["b", "d"]])
    keys = [key for key, _ in fused]
    # b appears high in both lists -> wins over a (top of one only).
    assert keys[0] == "b"
    assert set(keys) == {"a", "b", "c", "d"}
    scores = dict(fused)
    assert scores["b"] == pytest.approx(1 / 61 + 1 / 62)
    assert scores["a"] == pytest.approx(1 / 61)
    # Monotone: every later entry scores <= the one before it.
    values = [score for _, score in fused]
    assert values == sorted(values, reverse=True)


def test_rrf_single_ranking_is_identity_order():
    fused = fusion.rrf_fuse([["x", "y", "z"]])
    assert [key for key, _ in fused] == ["x", "y", "z"]


def test_rrf_tie_breaks_by_first_appearance():
    fused = fusion.rrf_fuse([["a"], ["b"]])  # identical scores
    assert [key for key, _ in fused] == ["a", "b"]


def test_rrf_empty_inputs():
    assert fusion.rrf_fuse([]) == []
    assert fusion.rrf_fuse([[], []]) == []


