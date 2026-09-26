"""Confluence storage format → Radd markdown (spec 117).

Pure and self-contained: `parse` builds a tree over the XHTML dialect, `convert`
walks it, `macros` decides what each `<ac:structured-macro>` becomes. No DB, no
network — everything that needs the world arrives as a callable on
`ConvertContext`, which is what lets the converter re-run over a cached body every
time the plan's mappings change.
"""

from .convert import ConvertContext, convert, translate_jql

__all__ = ["ConvertContext", "convert", "translate_jql"]
