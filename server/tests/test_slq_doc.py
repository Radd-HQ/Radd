"""RADD-1428: the SLQ description an agent reads is derived from the catalog.

The MCP `search_items` parameter used to carry a hand-written field list that
had lost `type`, `points`, `visibility`, `epic.*`, `parent.*`, `past_cycle`,
`cycle.status` and the relative dates. These tests read the generated text back
against `SlqField`/`BUILTIN_OPS`, so a field added to the catalog without
reaching the doc — or the other way round — fails the build.
"""

import re

from radd.modules.items.mcpschemas import _SLQ_DOC
from radd.modules.items.slq.catalog import BUILTIN_OPS, SlqField
from radd.modules.items.slq.doc import (
    EMPTY_TEXT,
    GROUP_SEPARATOR,
    LEAD_IN,
    MEMBERSHIP_TEXT,
    RELATIVE_DATE_EXAMPLES,
    SORT_ONLY_TEXT,
    SORTABLE_LEAD_IN,
    builtin_fields_doc,
)
from radd.modules.items.slq.lexer import CompareOp


def _groups(doc: str) -> dict[str, set[str]]:
    """operator-surface label -> the fields listed under it."""
    body = doc.split(SORTABLE_LEAD_IN)[0].split(LEAD_IN, 1)[1].strip(" .")
    groups: dict[str, set[str]] = {}
    for group in body.split(GROUP_SEPARATOR):
        label, _, names = group.rpartition(": ")
        groups[label] = {name.strip() for name in names.split(",")}
    return groups


def _sortable(doc: str) -> set[str]:
    tail = doc.split(SORTABLE_LEAD_IN, 1)[1].split(".", 1)[0]
    return {name.strip() for name in tail.split(",")}


def test_every_builtin_field_is_listed_exactly_once():
    doc = builtin_fields_doc()
    listed = [name for names in _groups(doc).values() for name in names]
    assert sorted(listed) == sorted(field.value for field in SlqField)


def test_each_field_sits_under_its_own_operator_surface():
    groups = _groups(builtin_fields_doc())
    for field in SlqField:
        ops = BUILTIN_OPS[field]
        label = next(label for label, names in groups.items() if field.value in names)
        for op in CompareOp:
            assert (op.value in label.split(", ")[0].split(" ")) is (op in ops.compare), (field, op)
        assert (MEMBERSHIP_TEXT in label) is ops.membership, field
        assert (EMPTY_TEXT in label) is ops.empty, field
        assert (label == SORT_ONLY_TEXT) is (not ops.compare and not ops.membership and not ops.empty)


def test_the_sortable_set_is_the_catalog_s():
    assert _sortable(builtin_fields_doc()) == {
        field.value for field in SlqField if BUILTIN_OPS[field].sortable
    }


def test_the_omissions_the_audit_named_are_present():
    doc = builtin_fields_doc()
    for name in ("type", "points", "visibility", "epic", "epic.category", "parent.state",
                 "past_cycle", "cycle.status"):
        assert re.search(rf"(?<![\w.]){re.escape(name)}(?![\w.])", doc), name
    for literal in RELATIVE_DATE_EXAMPLES:
        assert literal in doc


def test_the_mcp_parameter_carries_the_generated_text():
    assert builtin_fields_doc() in _SLQ_DOC
    assert "ORDER BY field [ASC|DESC]" in _SLQ_DOC  # the grammar sentence stays prose
