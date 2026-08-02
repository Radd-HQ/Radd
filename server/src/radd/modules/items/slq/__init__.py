"""SLQ — the Radd Query language (spec 10).

A JQL-like text query over work items: `lexer` -> `parser` (AST) -> `compiler`
(SQLAlchemy over WorkItem). `GET /items` takes it as `q`; saved views store it
as their `query` column. Any invalid input raises `SlqError` carrying the
character offset -> 422 `{detail, position}` via the items exception handler.
"""

from ..filters import NONE_LITERAL
from .catalog import ME_LITERAL, FieldOps
from .compiler import CompiledQuery, compile_query
from .errors import SlqError
from .helpers import (
    check_ops,
    compare,
    date_value,
    escape_like,
    is_sentinel,
    negated,
    number_value,
    plain,
    polarity,
    values_of,
)
from .parser import (
    BoolExpr,
    BoolOp,
    Comparison,
    Condition,
    EmptyCheck,
    Expr,
    Membership,
    NotExpr,
    Query,
    Value,
    parse,
    render,
)

# The lexer, parser and the coercion/negation helpers are GENERIC query
# machinery — nothing in them knows about work items. They are exported so a
# second dialect (timelogging's worklog SLQ, spec 98) can be a compiler and a
# field catalog rather than a second copy of the language. Longer term they
# belong in the kernel; keeping them here avoids a large move for one consumer.
__all__ = [
    "BoolExpr",
    "BoolOp",
    "CompiledQuery",
    "Comparison",
    "Condition",
    "EmptyCheck",
    "Expr",
    "FieldOps",
    "ME_LITERAL",
    "Membership",
    "NONE_LITERAL",
    "NotExpr",
    "Query",
    "SlqError",
    "Value",
    "check_ops",
    "compare",
    "compile_query",
    "date_value",
    "escape_like",
    "is_sentinel",
    "negated",
    "number_value",
    "parse",
    "plain",
    "polarity",
    "render",
    "values_of",
]
