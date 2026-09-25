"""RADD-1329: validation verdicts become visible nodes.

Every stored graph AND every saved version is rewritten so it reproduces the
verdict it gave before:

* A validate trigger loses its `mode`. What blocks is now a node:
  - each `ai.validate` a validate trigger reaches gains a verdict node on `fail`
    that RELAYS its findings — "Block submission" if a REQUIRED trigger reached
    it, "Warn submitter" otherwise — and a "Warn submitter" relay on its new
    `warn` port;
  - `on_unavailable: fail` becomes a verdict node on the `unavailable` port
    with the old message (the param is gone: the wiring says it now);
  - each `validation.fail` ("Report a problem") becomes a Block / Warn node with
    the same message and field. Verdict nodes are terminal, so its outgoing
    edges are re-sourced from whatever fed it (the old node passed its packet
    through unchanged). A `validation.fail` no validate trigger reaches was a
    no-op pass-through and is removed the same way.
* `automation_validations.mode` is re-derived: REQUIRED exactly when the
  trigger can reach a Block node — what the service computes on every save.

Revision ID: d1329verdict
Revises: d1315chain
"""

import json
import logging
import copy
from collections import deque

import sqlalchemy as sa
from alembic import op

revision = "d1329verdict"
down_revision = "d1315chain"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.runtime.migration")

BLOCK = "verdict.block"
WARN = "verdict.warn"
UNAVAILABLE_MESSAGE = (
    "This submission could not be checked automatically right now, and this "
    "intake requires the check to run. Please try again shortly."
)


def _reach(start: str, edges: list[dict]) -> set[str]:
    seen = {start}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        for edge in edges:
            if edge.get("source") == node and edge.get("target") not in seen:
                seen.add(edge["target"])
                queue.append(edge["target"])
    return seen


def _fresh_id(wanted: str, taken: set[str], limit: int | None = None) -> str:
    candidate, n = wanted[:limit], 2
    while candidate in taken:
        suffix = str(n)
        candidate, n = f"{wanted[:limit - len(suffix)] if limit else wanted}{suffix}", n + 1
    taken.add(candidate)
    return candidate


def _bypass(node_id: str, nodes: list[dict], edges: list[dict]) -> list[dict]:
    """Remove a node's OUTGOING edges, re-sourcing each from whatever fed it —
    the old pass-through, expressed as wires."""
    incoming = [e for e in edges if e.get("target") == node_id]
    outgoing = [e for e in edges if e.get("source") == node_id]
    kept = [e for e in edges if e.get("source") != node_id]
    present = {(e["source"], e.get("port"), e["target"]) for e in kept}
    for out in outgoing:
        for into in incoming:
            key = (into["source"], into.get("port"), out["target"])
            if key not in present:
                kept.append({"source": into["source"], "port": into.get("port"), "target": out["target"]})
                present.add(key)
    return kept


def rewrite(nodes: list[dict], edges: list[dict]) -> tuple[list[dict], list[dict], dict[str, bool]]:
    """(nodes, edges, {validate trigger id: can block}) — pure, so it is tested."""
    nodes = [dict(n, params=dict(n.get("params") or {})) for n in nodes]
    edges = [dict(e) for e in edges]
    # A shared legacy check inherits its ENTRY POINT's policy. Separate the
    # advisory path before replacing checks with terminal verdict nodes.
    triggers = [n for n in nodes if n.get("kind") == "trigger" and n["params"].get("event") == "validate"]
    required_nodes = set().union(*(_reach(n["id"], edges) for n in triggers if n["params"].get("mode") == "required"))
    taken_ids = {n["id"] for n in nodes}
    taken_names = {n["name"] for n in nodes if n.get("name")}
    for trigger in triggers:
        if trigger["params"].get("mode", "advisory") == "required":
            continue
        reached = _reach(trigger["id"], edges) - {trigger["id"]}
        if not reached & required_nodes:
            continue
        id_map = {node_id: _fresh_id(f"{node_id}_advisory", taken_ids) for node_id in sorted(reached)}
        originals = [n for n in nodes if n["id"] in reached]
        names = {n["name"]: _fresh_id(f"{n['name'][:20]}_advisory", taken_names, 30) for n in originals if n.get("name")}
        import re
        def rewrite_params(value):
            if isinstance(value, str):
                return re.sub(r"(\{\{\s*)([A-Za-z0-9_]+)(\.)", lambda m: m[1] + names.get(m[2], m[2]) + m[3], value)
            if isinstance(value, list):
                return [rewrite_params(v) for v in value]
            if isinstance(value, dict):
                return {k: rewrite_params(v) for k, v in value.items()}
            return value
        for original in originals:
            clone = copy.deepcopy(original)
            clone["id"] = id_map[original["id"]]
            if clone.get("name"):
                clone["name"] = names[clone["name"]]
            clone["params"] = rewrite_params(clone["params"])
            nodes.append(clone)
        cloned_edges = [{**edge, "source": id_map[edge["source"]], "target": id_map[edge["target"]]}
                        for edge in edges if edge["source"] in reached and edge["target"] in reached]
        edges = [{**edge, "target": id_map.get(edge["target"], edge["target"])}
                 if edge["source"] == trigger["id"] else edge for edge in edges]
        edges.extend(cloned_edges)
    by_id = {n["id"]: n for n in nodes}
    taken = set(by_id)

    required_reach: set[str] = set()
    any_reach: set[str] = set()
    validate_triggers: list[str] = []
    for node in nodes:
        if node.get("kind") == "trigger" and (node["params"].get("event") == "validate"):
            validate_triggers.append(node["id"])
            required = node["params"].pop("mode", "advisory") == "required"
            reached = _reach(node["id"], edges)
            any_reach |= reached
            if required:
                required_reach |= reached

    added: list[dict] = []
    for node in list(nodes):
        if node.get("type") != "ai.validate":
            continue
        on_unavailable = node["params"].pop("on_unavailable", "pass")
        if node["id"] not in any_reach:
            continue
        blocks = node["id"] in required_reach
        x, y = float(node.get("x") or 0), float(node.get("y") or 0)
        fail = _fresh_id(f"{node['id']}_fail", taken)
        added.append({"id": fail, "kind": "action", "type": BLOCK if blocks else WARN,
                      "params": {"relay": node["id"]}, "x": x - 220, "y": y + 160})
        edges.append({"source": node["id"], "port": "fail", "target": fail})
        warn = _fresh_id(f"{node['id']}_warn", taken)
        added.append({"id": warn, "kind": "action", "type": WARN,
                      "params": {"relay": node["id"]}, "x": x, "y": y + 160})
        edges.append({"source": node["id"], "port": "warn", "target": warn})
        if on_unavailable == "fail":
            unavailable = _fresh_id(f"{node['id']}_unavailable", taken)
            added.append({"id": unavailable, "kind": "action", "type": BLOCK if blocks else WARN,
                          "params": {"message": UNAVAILABLE_MESSAGE}, "x": x + 220, "y": y + 160})
            edges.append({"source": node["id"], "port": "unavailable", "target": unavailable})
    nodes.extend(added)

    for node in list(nodes):
        if node.get("type") != "validation.fail":
            continue
        edges = _bypass(node["id"], nodes, edges)
        if node["id"] in any_reach:
            node["type"] = BLOCK if node["id"] in required_reach else WARN
            node["params"] = {
                "message": str(node["params"].get("message") or ""),
                "field": str(node["params"].get("field") or ""),
            }
        else:
            nodes.remove(node)
            edges = [e for e in edges if e.get("target") != node["id"]]

    can_block = {}
    types = {n["id"]: n.get("type") for n in nodes}
    for trigger_id in validate_triggers:
        can_block[trigger_id] = any(types.get(n) == BLOCK for n in _reach(trigger_id, edges))
    return nodes, edges, can_block


def _touches(nodes: list[dict]) -> bool:
    return any(
        n.get("type") in ("ai.validate", "validation.fail")
        or (n.get("kind") == "trigger" and (n.get("params") or {}).get("event") == "validate")
        for n in nodes
    )


def _load(value) -> list:
    return value if isinstance(value, list) else json.loads(value or "[]")


def upgrade() -> None:
    bind = op.get_bind()
    for row in bind.execute(sa.text("SELECT id, name, nodes, edges FROM automations")).fetchall():
        nodes, edges = _load(row.nodes), _load(row.edges)
        if not _touches(nodes):
            continue
        new_nodes, new_edges, can_block = rewrite(nodes, edges)
        bind.execute(
            sa.text("UPDATE automations SET nodes = :nodes, edges = :edges WHERE id = :id"),
            {"id": row.id, "nodes": json.dumps(new_nodes), "edges": json.dumps(new_edges)},
        )
        for trigger_id, blocks in can_block.items():
            bind.execute(
                sa.text(
                    "UPDATE automation_validations SET mode = :mode "
                    "WHERE automation_id = :id AND node_id = :node"
                ),
                {"id": row.id, "node": trigger_id, "mode": "required" if blocks else "advisory"},
            )
        log.info("RADD-1329: rewrote automation %s (%s)", row.id, row.name)
    for row in bind.execute(sa.text("SELECT id, nodes, edges FROM automation_versions")).fetchall():
        nodes, edges = _load(row.nodes), _load(row.edges)
        if not _touches(nodes):
            continue
        new_nodes, new_edges, _ = rewrite(nodes, edges)
        bind.execute(
            sa.text("UPDATE automation_versions SET nodes = :nodes, edges = :edges WHERE id = :id"),
            {"id": row.id, "nodes": json.dumps(new_nodes), "edges": json.dumps(new_edges)},
        )


def downgrade() -> None:
    pass  # the old shapes are not executable any more; nothing to restore to
