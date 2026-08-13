"""The node registry seam (spec 116 phase 2, extended by RADD-918).

`graph.py` stays pure — it takes a resolver rather than importing the kernel — so
this is where the two meet. Everything that validates or walks a graph asks here
what a node's outputs are and how it reads its input, and gets the same answer
whether the node type is built into `automations` or contributed by a plugin.

That "same answer" is the whole point of the module. Ports and arity are each
resolvable from three places (a registered spec, a built-in table, the kind's
default), and a second copy of the precedence anywhere would eventually disagree
with this one — which the graph validator cannot survive, because it rejects
edges against a port set it has to believe.
"""

from __future__ import annotations

from typing import Any

from radd.kernel.registry import registries
from radd.kernel.specs import OutputField, valid_output_name

from . import graph
from .types import (
    ARITY_PARAM,
    BUILTIN_ARITY,
    BUILTIN_OUTPUTS,
    BUILTIN_PORTS,
    ArityRule,
    NodeArity,
)


def ports_of(node: graph.Node) -> tuple[str, ...]:
    """A node's outputs: its TYPE's answer when one is registered or tabled,
    else the kind's fixed set.

    The fallback matters — most core types predate the registry and are still
    resolved by kind, so a graph mixing contributed and built-in nodes validates
    the same way.
    """
    spec = registries.automation_nodes.get(node.type)
    if spec is not None:
        return spec.ports_at(node.params)
    builtin = BUILTIN_PORTS.get(node.type)
    if builtin is not None:
        return tuple(port.value for port in builtin)
    return graph.default_ports(node)


def outputs_of(node: graph.Node) -> tuple[OutputField, ...]:
    """The named values a node produces (spec 120) — its TYPE's answer when one
    is registered or tabled, else nothing.

    Ranked exactly like `ports_of`, and for the same reason: the write path
    refuses a token naming an output its producer cannot emit, so it has to ask
    one place. "Nothing" is the honest default — most node types produce no
    values at all, and a fallback that invented some would put tokens in the
    editor's picker that never resolve.
    """
    spec = registries.automation_nodes.get(node.type)
    if spec is not None:
        return tuple(spec.outputs_at(node.params))
    return BUILTIN_OUTPUTS.get(node.type, ())


def output_name(node: graph.Node) -> str:
    """The name this node can be ADDRESSED by, or "" when it cannot.

    Lenient by design: a stored name that is not a legal identifier makes the
    node unaddressable rather than making the automation unloadable. The write
    path is where someone is told; a row edited around the API degrades to a
    producer nobody can reference, which is visible in the dry run rather than
    fatal at 3am.
    """
    return node.name if valid_output_name(node.name) else ""


def spec_for(node: graph.Node):
    """The registered spec for a node, or None for a built-in type."""
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
    return BUILTIN_ARITY.get(node_type) or ArityRule(NodeArity.SET, (NodeArity.SET,))


def arity_of(node: graph.Node) -> NodeArity:
    """How this node reads its packet.

    The stored param wins ONLY when the type allows it. A node whose type is
    fixed at ITEM cannot be talked into running once by hand-editing its params
    — a `set_state` that fired a single time for a set would apply to whichever
    item happened to be first, which is not a behaviour anyone asked for.
    """
    rule = arity_rule(node.type)
    if not rule.configurable:
        return rule.default
    chosen = _coerce(node.params.get(ARITY_PARAM), rule.default)
    return chosen if chosen in rule.options else rule.default


def needs_items(node: graph.Node) -> bool:
    """Whether an EMPTY packet should stop this node running.

    A contributed spec says so directly. Built-ins answer from arity, which is
    the same question asked once: an ITEM node has nothing to do with no items,
    a SET node ("post to chat every Monday", "nothing matched — tell me") has.
    """
    spec = registries.automation_nodes.get(node.type)
    if spec is not None:
        return spec.needs_items
    return arity_of(node) is NodeArity.ITEM


def _coerce(value: Any, fallback: NodeArity) -> NodeArity:
    try:
        return NodeArity(str(value))
    except ValueError:
        return fallback
