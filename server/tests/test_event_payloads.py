"""One shape for item-scoped event payloads (RADD-922).

The stream had fourteen. The issue key was `key` on item and CSAT events,
`item_key` on SLA and page-link events, and absent from the other nine.
`project_id` was on two families out of fourteen. `item_id` was on everything
EXCEPT the item events, which carried `id`.

Nothing enforced a shape, so every new emitter invented one, and every consumer
grew a branch per spelling — `notify/consumer.py` resolved the key four ways,
`googlechat/formatter.py` branched on it, `search/indexer.py` opened with a
silent `if "project_id" not in payload: return`.

These tests are the enforcement. The first is a SOURCE SCAN: it parses every
`emit()` call in the codebase and fails when an item-scoped one does not build
`payload["item"]`. That is deliberately structural rather than behavioural —
a behavioural test can only cover the events a fixture happens to fire, and the
whole failure mode here is the emitter nobody thought about.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from radd.modules.items.service.refs import REQUIRED_KEYS

ROOT = pathlib.Path(__file__).resolve().parents[1] / "src" / "radd"

#: Event types that name an item but are NOT item-scoped triggers, so they carry
#: their own shape. `notification.created` is an internal realtime signal fired
#: once per recipient in a fan-out loop — resolving a ref per notification would
#: be N queries to describe something no automation can subscribe to.
NOT_ITEM_SCOPED = {"notification.created"}


def _emit_calls():
    """(file, line, entity_type expr, payload SOURCE) for every emit() call.

    Payloads built as a local variable (`payload = {...}` a few lines above, or a
    `_sla_payload(...)` helper) are resolved to every expression assigned to that
    name in the file. Without that, half the emitters read as an opaque `payload`
    and the check would pass by not looking — the vacuous-test failure mode this
    file exists to prevent.
    """
    for path in sorted(ROOT.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # pragma: no cover
            continue
        assigned: dict[str, list[str]] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        assigned.setdefault(target.id, []).append(ast.unparse(node.value))
            # `payload: dict = {...}` — an AnnAssign, which three emitters use.
            # Missing it made the check pass by not looking.
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.value is not None:
                    assigned.setdefault(node.target.id, []).append(ast.unparse(node.value))
        # `payload["x"] = ...` mutations, so a key added after the literal counts.
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Subscript)
                and isinstance(node.targets[0].value, ast.Name)
            ):
                assigned.setdefault(node.targets[0].value.id, []).append(
                    ast.unparse(node.targets[0])
                )
        # A returned dict literal is how the helper-built payloads are declared.
        returns = [
            ast.unparse(node.value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Return) and node.value is not None
        ]

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name != "emit":
                continue
            kw = {k.arg: k.value for k in node.keywords if k.arg}
            if "event_type" not in kw:
                continue
            payload = kw.get("payload")
            source = "" if payload is None else ast.unparse(payload)
            if isinstance(payload, ast.Name):
                source += " " + " ".join(assigned.get(payload.id, []))
            if isinstance(payload, ast.Call) or "**" in source:
                source += " " + " ".join(returns)
            # RADD-923: an emitter may hand the kernel `subjects={"item": id}`
            # and let it write the ref — which is the PREFERRED form, so the
            # check has to count it as satisfying the contract.
            if "subjects" in kw:
                source += " " + ast.unparse(kw["subjects"])
            yield path, node.lineno, kw.get("entity_type"), source


def _source(node) -> str:
    return "" if node is None else ast.unparse(node)


def test_every_item_scoped_emitter_builds_the_canonical_ref():
    """An emitter whose entity is an ITEM must put the ref in its payload.

    `entity_type=ItemEntity.ITEM` is the marker: those events are the ones the
    trigger registry marks item-scoped, and the ones a consumer will reach into
    for an item."""
    offenders = []
    for path, line, entity, source in _emit_calls():
        if "ItemEntity.ITEM" not in _source(entity):
            continue
        if '"item"' not in source and "'item'" not in source:
            offenders.append(f"{path.relative_to(ROOT)}:{line}")
    assert not offenders, (
        "these item-scoped emitters do not build payload['item'] — a consumer "
        "reaching for the item will find nothing: " + ", ".join(offenders)
    )


def test_no_emitter_reintroduces_a_second_spelling_of_the_key():
    """`item_key` and a bare `item_id` are the two shapes this replaced. Neither
    should come back: the cost was not the extra key, it was every consumer
    growing a branch for it."""
    banned = {'"item_key"': "item_key", '"item_id"': "item_id"}
    offenders = []
    for path, line, _entity, source in _emit_calls():
        for literal, name in banned.items():
            if literal in source:
                offenders.append(f"{path.relative_to(ROOT)}:{line} ({name})")
    assert not offenders, (
        "use payload['item'] (items.service.item_ref) instead: " + ", ".join(offenders)
    )


@pytest.mark.parametrize("key", REQUIRED_KEYS)
def test_the_ref_builder_produces_every_required_key(key):
    """The floor the consumers are written against."""
    from radd.modules.items.service import refs

    class _Item:
        id = "11111111-1111-1111-1111-111111111111"
        number = 42
        title = "a title"
        kind = "issue"
        priority = "normal"

    class _Project:
        id = "22222222-2222-2222-2222-222222222222"
        key = "TD"
        name = "Tracker"

    class _State:
        id = "33333333-3333-3333-3333-333333333333"
        name = "Todo"
        category = "todo"

    ref = refs.ref_from(_Item(), _Project(), _State())
    assert key in ref, f"{key} is required but the builder omits it"


def test_the_ref_names_relations_rather_than_pointing_at_them():
    """`{id, name}`, not a bare uuid. A payload exists to be READ — by a webhook
    receiver, a chat message, an automation template — and `assignee_id` alone
    renders a uuid at someone and calls it a notification."""
    from radd.modules.items.service import refs

    class _Named:
        id = "44444444-4444-4444-4444-444444444444"
        name = "Platform"

    class _Item:
        id = "11111111-1111-1111-1111-111111111111"
        number = 1
        title = "t"
        kind = "issue"
        priority = "normal"

    class _Project:
        id = "22222222-2222-2222-2222-222222222222"
        key = "TD"
        name = "Tracker"

    ref = refs.ref_from(_Item(), _Project(), None, team=_Named(), assignee=_Named())
    assert ref["team"] == {"id": _Named.id, "name": "Platform"}
    assert ref["assignee"] == {"id": _Named.id, "name": "Platform"}
    assert ref["project"]["key"] == "TD"
    # An unset relation is None, not an empty dict — `if ref["team"]` has to work.
    assert refs.ref_from(_Item(), _Project(), None)["team"] is None


def test_the_key_is_the_display_key_not_the_number():
    from radd.modules.items.service import refs

    class _Item:
        id = "11111111-1111-1111-1111-111111111111"
        number = 1234
        title = "t"
        kind = "issue"
        priority = "normal"

    class _Project:
        id = "22222222-2222-2222-2222-222222222222"
        key = "TD"
        name = "Tracker"

    assert refs.ref_from(_Item(), _Project(), None)["key"] == "TD-1234"
