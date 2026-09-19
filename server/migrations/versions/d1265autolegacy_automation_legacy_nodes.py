"""RADD-1265: retire the automation condition tree and the schedule query

Two stored shapes stop being executable in this version and are rewritten in
place rather than shimmed:

* A schedule trigger's `query` param becomes a `search.slq` SOURCE node wired
  between the trigger and everything the trigger fed. Same query, same
  semantics, now visible on the canvas as the node it always was (RADD-919).
* A `gate.event` node holding a condition tree becomes the equivalent NAMED
  gates. An `all` group of leaf conditions is a chain (true → true); each
  leaf maps onto `gate.changed_by`, `gate.field_changed`,
  `gate.state_category` or the new `gate.payload`. A tree this cannot express
  (any/none groups, nesting) DISABLES the automation and renames it with a
  "[needs review]" suffix — an automation that silently fires more broadly
  than it was written to is worse than one that stops and says so.

Revision ID: d1265autolegacy
Revises: d1253gitlabconn
"""

import json
import logging

import sqlalchemy as sa
from alembic import op

revision = "d1265autolegacy"
down_revision = "d1253gitlabconn"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.runtime.migration")

_SUBJECT_TO_GATE = {"actor", "changed_field", "old_value", "new_value", "state_category", "payload"}


def _leaf_to_gate(leaf: dict, node_id: str) -> dict | None:
    subject = leaf.get("subject")
    operator = leaf.get("operator") or "eq"
    value = leaf.get("value")
    values = value if isinstance(value, list) else ([value] if value not in (None, "") else [])
    qualifier = str(leaf.get("qualifier") or "").strip()
    if subject == "actor" and operator in ("eq", "in", "neq", "not_in") and values:
        return {"id": node_id, "kind": "gate", "type": "gate.changed_by",
                "params": {"users": [str(v) for v in values], "negate": operator in ("neq", "not_in")}}
    if subject == "changed_field" and operator in ("eq", "contains", "in") and values:
        return {"id": node_id, "kind": "gate", "type": "gate.field_changed",
                "params": {"field": str(values[0]), "from_mode": "any", "from_values": [],
                           "to_mode": "any", "to_values": []}}
    if subject in ("old_value", "new_value") and qualifier:
        side = "from" if subject == "old_value" else "to"
        other = "to" if side == "from" else "from"
        if operator in ("eq", "in") and values:
            mode, chosen = "specific", [str(v) for v in values]
        elif operator == "not_set":
            mode, chosen = "empty", []
        elif operator == "is_set":
            return {"id": node_id, "kind": "gate", "type": "gate.payload",
                    "params": {"path": f"changes.{side}", "operator": "is_set", "value": "", "negate": False}}
        else:
            return None
        return {"id": node_id, "kind": "gate", "type": "gate.field_changed",
                "params": {"field": qualifier, f"{side}_mode": mode, f"{side}_values": chosen,
                           f"{other}_mode": "any", f"{other}_values": []}}
    if subject == "state_category" and operator in ("eq", "in") and values:
        return {"id": node_id, "kind": "gate", "type": "gate.state_category",
                "params": {"categories": [str(v) for v in values]}}
    if subject == "payload" and qualifier:
        return {"id": node_id, "kind": "gate", "type": "gate.payload",
                "params": {"path": qualifier, "operator": operator,
                           "value": value if isinstance(value, list) else ("" if value is None else str(value)),
                           "negate": False}}
    return None


def _convert_gate(node: dict, taken: set[str]) -> list[dict] | None:
    """The chain of named gates replacing one `gate.event`, or None."""
    tree = (node.get("params") or {}).get("conditions") or {}
    leaves = tree.get("conditions") if isinstance(tree, dict) else None
    if not leaves:
        return []  # an empty tree always matched: nothing to keep
    if str(tree.get("op", "all")) != "all":
        return None
    chain: list[dict] = []
    for index, leaf in enumerate(leaves):
        if not isinstance(leaf, dict) or "conditions" in leaf:
            return None
        new_id = node["id"] if index == 0 else f"{node['id']}_{index + 1}"
        while new_id in taken:
            new_id += "x"
        taken.add(new_id)
        gate = _leaf_to_gate(leaf, new_id)
        if gate is None:
            return None
        gate["x"], gate["y"] = node.get("x"), node.get("y")
        chain.append(gate)
    return chain


def _rewrite(nodes: list[dict], edges: list[dict]) -> tuple[list[dict], list[dict], bool]:
    """(nodes, edges, ok). ok=False means a tree could not be expressed."""
    taken = {str(n.get("id")) for n in nodes}
    out_nodes: list[dict] = []
    out_edges = list(edges)
    for node in nodes:
        params = dict(node.get("params") or {})
        if node.get("kind") == "trigger" and params.get("event") == "schedule" and "query" in params:
            query = str(params.pop("query") or "").strip()
            node = {**node, "params": params}
            if query:
                search_id = f"find_{node['id']}"
                while search_id in taken:
                    search_id += "x"
                taken.add(search_id)
                search = {"id": search_id, "kind": "source", "type": "search.slq",
                          "params": {"slq": query, "project": "", "mode": "replace"}}
                out_edges = [
                    ({**e, "source": search_id, "port": "out"} if e.get("source") == node["id"] else e)
                    for e in out_edges
                ]
                out_edges.append({"source": node["id"], "port": "out", "target": search_id})
                out_nodes.append(node)
                out_nodes.append(search)
                continue
        if node.get("type") == "gate.event":
            chain = _convert_gate(node, taken)
            if chain is None:
                return nodes, edges, False
            if not chain:
                # Always-true: splice it out, feeders go straight to the true targets.
                feeders = [e for e in out_edges if e.get("target") == node["id"]]
                true_targets = [e for e in out_edges if e.get("source") == node["id"] and e.get("port") == "true"]
                out_edges = [e for e in out_edges if e.get("source") != node["id"] and e.get("target") != node["id"]]
                for f in feeders:
                    for t in true_targets:
                        out_edges.append({"source": f["source"], "port": f.get("port", "out"), "target": t["target"]})
                continue
            first, last = chain[0]["id"], chain[-1]["id"]
            false_targets = [e["target"] for e in out_edges if e.get("source") == node["id"] and e.get("port") == "false"]
            out_edges = [
                ({**e, "source": last} if e.get("source") == node["id"] and e.get("port") == "true" else e)
                for e in out_edges
                if not (e.get("source") == node["id"] and e.get("port") == "false")
            ]
            out_edges = [({**e, "target": first} if e.get("target") == node["id"] else e) for e in out_edges]
            for a, b in zip(chain, chain[1:]):
                out_edges.append({"source": a["id"], "port": "true", "target": b["id"]})
            for gate in chain:
                for target in false_targets:
                    out_edges.append({"source": gate["id"], "port": "false", "target": target})
            out_nodes.extend(chain)
            continue
        out_nodes.append(node)
    return out_nodes, out_edges, True


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, name, nodes, edges, enabled FROM automations")).fetchall()
    for row in rows:
        nodes = row.nodes if isinstance(row.nodes, list) else json.loads(row.nodes or "[]")
        edges = row.edges if isinstance(row.edges, list) else json.loads(row.edges or "[]")
        touched = any(
            (n.get("type") == "gate.event")
            or (n.get("kind") == "trigger" and "query" in (n.get("params") or {}))
            for n in nodes
        )
        if not touched:
            continue
        new_nodes, new_edges, ok = _rewrite(nodes, edges)
        if ok:
            bind.execute(
                sa.text("UPDATE automations SET nodes = :nodes, edges = :edges WHERE id = :id"),
                {"id": row.id, "nodes": json.dumps(new_nodes), "edges": json.dumps(new_edges)},
            )
            log.info("RADD-1265: rewrote automation %s (%s)", row.id, row.name)
        else:
            bind.execute(
                sa.text(
                    "UPDATE automations SET enabled = false, name = :name WHERE id = :id"
                ),
                {"id": row.id, "name": (row.name + " [needs review]")[:200]},
            )
            log.warning(
                "RADD-1265: automation %s (%s) holds a condition tree the named gates cannot "
                "express; DISABLED for review",
                row.id, row.name,
            )


def downgrade() -> None:
    pass  # the old shapes are not executable any more; nothing to restore to
