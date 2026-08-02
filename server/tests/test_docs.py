"""Unit tests for the docs module's pure core (spec 43) — repo style: only the
invariants many flows depend on (tree cycle guard, version-snapshot decision,
tsquery builder, archived-subtree visibility). Everything else is verified by
in-process ASGI runs against the live app.
"""

import uuid

from radd.modules.docs.core import (
    build_tsquery,
    should_snapshot,
    slugify,
    visible_page_ids,
    would_create_cycle,
)

A, B, C, D = (uuid.uuid4() for _ in range(4))


# --- cycle guard ---


def test_move_to_root_or_sibling_is_not_a_cycle():
    parent_of = {A: None, B: A, C: B}
    assert not would_create_cycle(C, None, parent_of)  # to root
    assert not would_create_cycle(C, A, parent_of)  # up a level
    assert not would_create_cycle(B, None, parent_of)


def test_move_under_own_descendant_is_a_cycle():
    parent_of = {A: None, B: A, C: B}
    assert would_create_cycle(A, C, parent_of)  # grandchild
    assert would_create_cycle(A, B, parent_of)  # direct child
    assert would_create_cycle(B, C, parent_of)


def test_move_under_self_is_a_cycle():
    assert would_create_cycle(A, A, {A: None})


def test_preexisting_loop_in_data_reads_as_cycle_not_hang():
    # Corrupt chain (B <-> C): the guard must terminate and refuse the move.
    parent_of = {B: C, C: B}
    assert would_create_cycle(A, B, parent_of)


# --- version-snapshot decision ---


def test_snapshot_on_title_or_body_change():
    assert should_snapshot("t", "b", "new title", None)
    assert should_snapshot("t", "b", None, "new body")
    assert should_snapshot("t", "b", "new title", "new body")


def test_no_snapshot_when_content_unchanged():
    # Omitted fields and same-text saves must NOT burn a version — a pure
    # move (parent/position PATCH) keeps the version number stable.
    assert not should_snapshot("t", "b", None, None)
    assert not should_snapshot("t", "b", "t", "b")
    assert not should_snapshot("t", "b", "t", None)


# --- tsquery builder ---


def test_tsquery_ands_terms_and_prefixes_the_last():
    assert build_tsquery("render farm") == "'render' & 'farm':*"
    assert build_tsquery("deploy") == "'deploy':*"


def test_tsquery_drops_metacharacters_and_empty_input():
    assert build_tsquery("a & b | c!") == "'a' & 'b' & 'c':*"
    assert build_tsquery("&&& ((()))") == ""
    assert build_tsquery("   ") == ""


# --- archived-subtree visibility ---


def test_archived_page_hides_its_descendants():
    parent_of = {A: None, B: A, C: B, D: None}
    assert visible_page_ids(parent_of, {B}) == {A, D}
    assert visible_page_ids(parent_of, set()) == {A, B, C, D}
    assert visible_page_ids(parent_of, {A}) == {D}


# --- slugs (cosmetic) ---


def test_slugify_is_lowercase_dashed_and_bounded():
    assert slugify("Render Farm — Ops!") == "render-farm-ops"
    assert slugify("---") == "space"  # never empty
    assert len(slugify("x" * 500)) <= 100
