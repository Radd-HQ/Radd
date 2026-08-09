"""Confluence storage format → Radd markdown (spec 117).

Pure and self-contained: `parse` builds a tree over the XHTML dialect, `convert`
walks it, `macros` decides what each `<ac:structured-macro>` becomes. No DB, no
network — everything that needs the world arrives as a callable on
`ConvertContext`, which is what lets the converter re-run over a cached body every
time the plan's mappings change.
"""

from .convert import ConvertContext, ConvertResult, convert, translate_jql
from .macros import BUILTIN_MACROS, MacroSpec, spec_for
from .tree import Node, parse

__all__ = [
    "BUILTIN_MACROS",
    "ConvertContext",
    "ConvertResult",
    "MacroSpec",
    "Node",
    "convert",
    "parse",
    "spec_for",
    "translate_jql",
]
