"""The node registry seam (spec 116): `graph.py` stays pure and takes resolvers;
everything that validates or walks a graph asks HERE for a node's ports, outputs
and arity, so the precedence exists once."""

from __future__ import annotations

from typing import Any

from radd.kernel.registry import registries
from radd.kernel.specs import OutputField, valid_output_name

from . import graph
from .types import ARITY_PARAM, ArityRule, NodeArity


def ports_of(node: graph.Node) -> tuple[str, ...]:
    """A node's outputs: its TYPE's spec's answer (RADD-1322: built-ins are
    registered too), else the kind's fixed set.

    The fallback is for a type nothing registers — a node from a plugin that has
    since been uninstalled — so the stored graph still loads and validates.
    """
    spec = registries.automation_nodes.get(node.type)
    if spec is not None:
        return spec.ports_at(node.params)
    return graph.default_ports(node)


def outputs_of(node: graph.Node) -> tuple[OutputField, ...]:
    """The named values a node produces (spec 120) — its spec's answer, else none."""
    spec = registries.automation_nodes.get(node.type)
    if spec is not None:
        return tuple(spec.outputs_at(node.params))
    return ()


def output_name(node: graph.Node) -> str:
    """The name this node can be addressed by, or "" — a stored illegal name makes
    the node unaddressable, never the automation unloadable."""
    return node.name if valid_output_name(node.name) else ""


def spec_for(node: graph.Node):
    """The registered spec for a node, or None for a type nothing registers (an
    uninstalled plugin's). Built-ins are registered since RADD-1322."""
    return registries.automation_nodes.get(node.type)


def arity_rule(node_type: str) -> ArityRule:
    """What arities a node TYPE allows, and which it defaults to.

    Unknown types answer "fixed at SET" rather than raising: an automation
    holding a node from a plugin that has since been uninstalled must still be
    loadable, and the executor already refuses to run what it cannot resolve.
    """
    spec = registries.automation_nodes.get(node_type)
    if spec is not None:
        default = _coerce(spec.arity, NodeArity.SET)
        options = tuple(dict.fromkeys(_coerce(value, default) for value in spec.arity_options))
        return ArityRule(default, options or (default,))
    return ArityRule(NodeArity.SET, (NodeArity.SET,))


def arity_of(node: graph.Node) -> NodeArity:
    """How this node reads its packet: the stored param only when the type allows
    it (a hand-edited `set_state` at set arity would hit whichever item came first)."""
    rule = arity_rule(node.type)
    if not rule.configurable:
        return rule.default
    chosen = _coerce(node.params.get(ARITY_PARAM), rule.default)
    return chosen if chosen in rule.options else rule.default


def needs_items(node: graph.Node) -> bool:
    """Whether an EMPTY packet should stop this node running — its spec says so
    directly. An unknown type answers yes: it has nothing to run anyway."""
    spec = registries.automation_nodes.get(node.type)
    if spec is not None:
        return spec.needs_items
    return True


def _coerce(value: Any, fallback: NodeArity) -> NodeArity:
    try:
        return NodeArity(str(value))
    except ValueError:
        return fallback
