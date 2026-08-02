"""SLQ parser: tokens -> AST dataclasses, plus canonical rendering (`render`).

Grammar (spec 10, frozen):

    query     := [expr] [ORDER BY order (',' order)*]
    expr      := and_expr (OR and_expr)*          # AND binds tighter than OR
    and_expr  := term (AND term)*
    term      := [NOT] (comparison | '(' expr ')')
    comparison:= field op value
               | field [NOT] IN '(' value (',' value)* ')'
               | field IS [NOT] EMPTY
    order     := field [ASC|DESC]

Keywords are case-insensitive. An entirely empty query (or a bare ORDER BY) is
accepted — saved views default to ''. Positions are `compare=False` so AST
equality (round-trip tests) ignores them.
"""

from dataclasses import dataclass, field as dc_field
from enum import StrEnum

from .errors import SlqError
from .lexer import CompareOp, Token, TokenKind, tokenize


class Keyword(StrEnum):
    AND = "and"
    OR = "or"
    NOT = "not"
    IN = "in"
    IS = "is"
    EMPTY = "empty"
    ORDER = "order"
    BY = "by"
    ASC = "asc"
    DESC = "desc"


RESERVED_WORDS = frozenset(Keyword)


class BoolOp(StrEnum):
    AND = "AND"
    OR = "OR"


@dataclass(frozen=True)
class Value:
    text: str
    quoted: bool = False  # quoted values are always literal (never me/none sentinels)
    position: int = dc_field(default=0, compare=False)


@dataclass(frozen=True)
class Comparison:
    field: str
    op: CompareOp
    value: Value
    field_position: int = dc_field(default=0, compare=False)
    op_position: int = dc_field(default=0, compare=False)


@dataclass(frozen=True)
class Membership:
    """field [NOT] IN (v, …)"""

    field: str
    values: tuple[Value, ...]
    negated: bool = False
    field_position: int = dc_field(default=0, compare=False)


@dataclass(frozen=True)
class EmptyCheck:
    """field IS [NOT] EMPTY"""

    field: str
    negated: bool = False
    field_position: int = dc_field(default=0, compare=False)


@dataclass(frozen=True)
class NotExpr:
    operand: "Expr"


@dataclass(frozen=True)
class BoolExpr:
    op: BoolOp
    operands: tuple["Expr", ...]


Expr = Comparison | Membership | EmptyCheck | NotExpr | BoolExpr
Condition = Comparison | Membership | EmptyCheck


@dataclass(frozen=True)
class OrderTerm:
    field: str
    descending: bool = False
    field_position: int = dc_field(default=0, compare=False)


@dataclass(frozen=True)
class Query:
    where: Expr | None = None
    order: tuple[OrderTerm, ...] = ()


def parse(text: str) -> Query:
    return _Parser(tokenize(text)).query()


class _Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.index = 0

    # --- token helpers ---

    def peek(self) -> Token:
        return self.tokens[self.index]

    def advance(self) -> Token:
        token = self.tokens[self.index]
        self.index += 1
        return token

    def match(self, kind: TokenKind) -> bool:
        if self.peek().kind is kind:
            self.index += 1
            return True
        return False

    def is_keyword(self, token: Token, keyword: Keyword) -> bool:
        return token.kind is TokenKind.WORD and token.text.lower() == keyword.value

    def match_keyword(self, keyword: Keyword) -> bool:
        if self.is_keyword(self.peek(), keyword):
            self.index += 1
            return True
        return False

    def expect_keyword(self, keyword: Keyword, message: str) -> None:
        if not self.match_keyword(keyword):
            token = self.peek()
            raise SlqError(f"{message}, got '{token.text}'", token.position)

    def at_order_by(self) -> bool:
        return self.is_keyword(self.peek(), Keyword.ORDER) and self.is_keyword(
            self.tokens[self.index + 1], Keyword.BY
        )

    # --- grammar ---

    def query(self) -> Query:
        where = None
        if self.peek().kind is not TokenKind.EOF and not self.at_order_by():
            where = self.expr()
        order = self.order_clause() if self.at_order_by() else ()
        token = self.peek()
        if token.kind is not TokenKind.EOF:
            raise SlqError(f"expected AND, OR or ORDER BY, got '{token.text}'", token.position)
        return Query(where=where, order=order)

    def expr(self) -> Expr:
        operands = [self.and_expr()]
        while self.match_keyword(Keyword.OR):
            operands.append(self.and_expr())
        return operands[0] if len(operands) == 1 else BoolExpr(BoolOp.OR, tuple(operands))

    def and_expr(self) -> Expr:
        operands = [self.term()]
        while self.match_keyword(Keyword.AND):
            operands.append(self.term())
        return operands[0] if len(operands) == 1 else BoolExpr(BoolOp.AND, tuple(operands))

    def term(self) -> Expr:
        if self.match_keyword(Keyword.NOT):
            return NotExpr(self._term_body())
        return self._term_body()

    def _term_body(self) -> Expr:
        if self.match(TokenKind.LPAREN):
            inner = self.expr()
            if not self.match(TokenKind.RPAREN):
                token = self.peek()
                raise SlqError(f"expected ')', got '{token.text}'", token.position)
            return inner
        return self.comparison()

    def comparison(self) -> Condition:
        token = self.peek()
        if token.kind is not TokenKind.WORD or token.text.lower() in RESERVED_WORDS:
            raise SlqError(f"expected a field name, got '{token.text}'", token.position)
        field_token = self.advance()
        nxt = self.peek()
        if nxt.kind is TokenKind.OP:
            self.advance()
            return Comparison(
                field=field_token.text,
                op=CompareOp(nxt.text),
                value=self.value(),
                field_position=field_token.position,
                op_position=nxt.position,
            )
        if self.match_keyword(Keyword.IN):
            return Membership(
                field=field_token.text,
                values=self.value_list(),
                field_position=field_token.position,
            )
        if self.match_keyword(Keyword.NOT):
            self.expect_keyword(Keyword.IN, "expected IN after NOT")
            return Membership(
                field=field_token.text,
                values=self.value_list(),
                negated=True,
                field_position=field_token.position,
            )
        if self.match_keyword(Keyword.IS):
            negated = self.match_keyword(Keyword.NOT)
            self.expect_keyword(Keyword.EMPTY, "expected EMPTY after IS")
            return EmptyCheck(
                field=field_token.text, negated=negated, field_position=field_token.position
            )
        raise SlqError(f"expected an operator after '{field_token.text}'", nxt.position)

    def value(self) -> Value:
        token = self.peek()
        if token.kind is TokenKind.STRING:
            self.advance()
            return Value(token.text, quoted=True, position=token.position)
        if token.kind is TokenKind.WORD:
            if token.text.lower() in RESERVED_WORDS:
                raise SlqError(
                    f"'{token.text}' is a reserved word — quote it to use as a value",
                    token.position,
                )
            self.advance()
            return Value(token.text, quoted=False, position=token.position)
        raise SlqError(f"expected a value, got '{token.text}'", token.position)

    def value_list(self) -> tuple[Value, ...]:
        token = self.peek()
        if not self.match(TokenKind.LPAREN):
            raise SlqError(f"expected '(' after IN, got '{token.text}'", token.position)
        values = [self.value()]
        while self.match(TokenKind.COMMA):
            values.append(self.value())
        token = self.peek()
        if not self.match(TokenKind.RPAREN):
            raise SlqError(f"expected ')' or ',', got '{token.text}'", token.position)
        return tuple(values)

    def order_clause(self) -> tuple[OrderTerm, ...]:
        self.advance()  # ORDER
        self.advance()  # BY
        terms = [self.order_term()]
        while self.match(TokenKind.COMMA):
            terms.append(self.order_term())
        return tuple(terms)

    def order_term(self) -> OrderTerm:
        token = self.peek()
        if token.kind is not TokenKind.WORD or token.text.lower() in RESERVED_WORDS:
            raise SlqError(f"expected a field name in ORDER BY, got '{token.text}'", token.position)
        self.advance()
        descending = False
        if self.match_keyword(Keyword.DESC):
            descending = True
        else:
            self.match_keyword(Keyword.ASC)
        return OrderTerm(field=token.text, descending=descending, field_position=token.position)


# --- canonical rendering (parse(render(q)) == q; used by tests and tooling) ---


def render(query: Query) -> str:
    parts: list[str] = []
    if query.where is not None:
        parts.append(_render_expr(query.where))
    if query.order:
        terms = ", ".join(f"{t.field} DESC" if t.descending else t.field for t in query.order)
        parts.append(f"ORDER BY {terms}")
    return " ".join(parts)


def _render_value(value: Value) -> str:
    if value.quoted:
        escaped = value.text.replace("\\", "\\\\").replace("'", "\\'")
        return f"'{escaped}'"
    return value.text


def _render_expr(expr: Expr) -> str:
    match expr:
        case Comparison():
            return f"{expr.field} {expr.op.value} {_render_value(expr.value)}"
        case Membership():
            values = ", ".join(_render_value(v) for v in expr.values)
            keyword = "NOT IN" if expr.negated else "IN"
            return f"{expr.field} {keyword} ({values})"
        case EmptyCheck():
            return f"{expr.field} IS {'NOT ' if expr.negated else ''}EMPTY"
        case NotExpr():
            if isinstance(expr.operand, BoolExpr):
                return f"NOT ({_render_expr(expr.operand)})"
            return f"NOT {_render_expr(expr.operand)}"
        case BoolExpr():
            rendered = [
                f"({_render_expr(op)})" if _needs_parens(op, expr.op) else _render_expr(op)
                for op in expr.operands
            ]
            return f" {expr.op.value} ".join(rendered)
    raise TypeError(f"unhandled node {expr!r}")  # pragma: no cover


def _needs_parens(child: Expr, parent_op: BoolOp) -> bool:
    """Parenthesize so precedence survives the round-trip: any bool child inside
    AND; an OR child inside OR (explicit grouping the flat parse would lose)."""
    if not isinstance(child, BoolExpr):
        return False
    return parent_op is BoolOp.AND or child.op is BoolOp.OR
