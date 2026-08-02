"""SLQ suggest (spec 12): lexer-driven detection of what the cursor position wants.

Runs the existing lexer over q[:cursor] and classifies the trailing complete
tokens with a small expectation machine ("what may the next token be" — the
parser's grammar tracked forward, never re-parsed). A trailing WORD that ends
exactly at the cursor is the token being completed: it becomes the filter
partial and `replace_from` points at its start; an unterminated string means
the cursor sits inside quotes (value position, open quote respected). Pure —
no DB, no registry: `suggest.py` turns the `Detection` into ranked suggestions.
"""

from dataclasses import dataclass, replace
from enum import Enum, StrEnum, auto

from .errors import SlqError
from .lexer import _ESCAPE, _QUOTES, Token, TokenKind, tokenize
from .parser import RESERVED_WORDS, Keyword


class SuggestContext(StrEnum):
    """The frozen `context` values of the suggest response contract."""

    FIELD = "field"
    OPERATOR = "operator"
    VALUE = "value"
    KEYWORD = "keyword"


class Offer(StrEnum):
    """What the assembly layer should enumerate for the detected position."""

    FIELDS = "fields"  # every queryable field in scope (+ Detection.keywords)
    SORTABLE_FIELDS = "sortable_fields"  # ORDER BY position: sortable fields only
    OPERATORS = "operators"  # the in-play field's operator surface (catalog)
    VALUES = "values"  # the in-play field's value source (live data)
    KEYWORDS = "keywords"  # exactly Detection.keywords
    NOTHING = "nothing"  # position understood, nothing sensible to offer


class KeywordSuggestion(StrEnum):
    """Canonical spellings of suggestible keywords (multi-word inserts verbatim)."""

    AND = "AND"
    OR = "OR"
    NOT = "NOT"
    ORDER_BY = "ORDER BY"
    BY = "BY"
    IN = "IN"
    NOT_IN = "NOT IN"
    IS_EMPTY = "IS EMPTY"
    IS_NOT_EMPTY = "IS NOT EMPTY"
    EMPTY = "EMPTY"
    NOT_EMPTY = "NOT EMPTY"
    ASC = "ASC"
    DESC = "DESC"


@dataclass(frozen=True)
class Detection:
    """Where the cursor sits: the response context plus what to enumerate.

    `insert` values splice over [replace_from, cursor); `partial` is the piece
    already typed (decoded when inside quotes) used as the match filter.
    """

    context: SuggestContext
    offer: Offer
    replace_from: int
    partial: str
    field: str | None = None  # the field in play (operator/value positions)
    keywords: tuple[KeywordSuggestion, ...] = ()
    quote: str | None = None  # open-quote char when the cursor is inside a string


class _S(Enum):
    """Expectation states — one per 'what may come next' position in the grammar."""

    TERM = auto()  # field | NOT | '('        (start, after AND/OR/NOT/'(')
    FIELD_DONE = auto()  # op | IN | NOT IN | IS
    FIELD_NOT = auto()  # IN
    OP_DONE = auto()  # value
    IN_KEYWORD = auto()  # '('
    IN_VALUE = auto()  # value                (after 'IN (' or a list comma)
    IN_NEXT = auto()  # ',' | ')'
    IS_KEYWORD = auto()  # NOT | EMPTY
    IS_NOT = auto()  # EMPTY
    DONE = auto()  # AND | OR | ')' | ORDER   (complete comparison / group)
    ORDER = auto()  # BY
    ORDER_FIELD = auto()  # sortable field    (after ORDER BY or an order comma)
    ORDER_DIR = auto()  # ASC | DESC | ','
    ORDER_NEXT = auto()  # ','
    INVALID = auto()


def detect(q: str, cursor: int) -> Detection:
    prefix = q[:cursor]
    try:
        tokens = tokenize(prefix)[:-1]  # drop EOF
    except SlqError as error:
        if prefix[error.position] in _QUOTES:  # unterminated string: inside quotes
            return _string_detection(prefix, error.position)
        # Unlexable tail (e.g. a lone '!'): treat it as the partial being typed.
        tokens = tokenize(prefix[: error.position])[:-1]
        return _classify(tokens, replace_from=error.position, partial=prefix[error.position :])
    partial = _trailing_word(tokens, cursor)
    if partial is not None:
        return _classify(tokens[:-1], replace_from=partial.position, partial=partial.text)
    return _classify(tokens, replace_from=cursor, partial="")


def _trailing_word(tokens: list[Token], cursor: int) -> Token | None:
    """The WORD being completed — iff it runs right up to the cursor."""
    if tokens and tokens[-1].kind is TokenKind.WORD:
        token = tokens[-1]
        if token.position + len(token.text) == cursor:
            return token
    return None


def _string_detection(prefix: str, start: int) -> Detection:
    """Cursor inside an open quote: always a value position, insert re-quotes."""
    quote = prefix[start]
    partial = _decode_string_body(prefix[start + 1 :])
    detection = _classify(tokenize(prefix[:start])[:-1], replace_from=start, partial=partial)
    if detection.offer is Offer.VALUES:  # a quote where a value belongs
        return replace(detection, quote=quote)
    return Detection(
        SuggestContext.VALUE, Offer.NOTHING, start, partial, field=detection.field, quote=quote
    )


def _decode_string_body(body: str) -> str:
    chars: list[str] = []
    i = 0
    while i < len(body):
        if body[i] == _ESCAPE and i + 1 < len(body):
            chars.append(body[i + 1])
            i += 2
        else:
            chars.append(body[i])
            i += 1
    return "".join(chars)


def _keyword_of(token: Token) -> Keyword | None:
    if token.kind is TokenKind.WORD and token.text.lower() in RESERVED_WORDS:
        return Keyword(token.text.lower())
    return None


def _is_value(token: Token, keyword: Keyword | None) -> bool:
    return token.kind is TokenKind.STRING or (
        token.kind is TokenKind.WORD and keyword is None
    )


def _classify(tokens: list[Token], *, replace_from: int, partial: str) -> Detection:
    state, field = _run_machine(tokens)
    return _detection(state, field, replace_from, partial)


def _run_machine(tokens: list[Token]) -> tuple["_MachineResult", str | None]:
    state = _S.TERM
    field: str | None = None
    depth = 0  # '(' groups (IN lists track their parens via IN_* states)
    at_start = True  # a bare ORDER BY may open the query
    just_not = False  # NOT was just consumed -> don't offer NOT again
    for token in tokens:
        keyword = _keyword_of(token)
        match state:
            case _S.TERM:
                just_not = False
                if token.kind is TokenKind.LPAREN:
                    depth += 1
                elif keyword is Keyword.NOT:
                    just_not = True
                elif keyword is Keyword.ORDER and at_start and depth == 0:
                    state = _S.ORDER
                elif token.kind is TokenKind.WORD and keyword is None:
                    field, state = token.text, _S.FIELD_DONE
                else:
                    state = _S.INVALID
            case _S.FIELD_DONE:
                if token.kind is TokenKind.OP:
                    state = _S.OP_DONE
                elif keyword is Keyword.IN:
                    state = _S.IN_KEYWORD
                elif keyword is Keyword.NOT:
                    state = _S.FIELD_NOT
                elif keyword is Keyword.IS:
                    state = _S.IS_KEYWORD
                else:
                    state = _S.INVALID
            case _S.FIELD_NOT:
                state = _S.IN_KEYWORD if keyword is Keyword.IN else _S.INVALID
            case _S.OP_DONE:
                state = _S.DONE if _is_value(token, keyword) else _S.INVALID
            case _S.IN_KEYWORD:
                state = _S.IN_VALUE if token.kind is TokenKind.LPAREN else _S.INVALID
            case _S.IN_VALUE:
                if _is_value(token, keyword):
                    state = _S.IN_NEXT
                elif token.kind is TokenKind.RPAREN:
                    state = _S.DONE
                else:
                    state = _S.INVALID
            case _S.IN_NEXT:
                if token.kind is TokenKind.COMMA:
                    state = _S.IN_VALUE
                elif token.kind is TokenKind.RPAREN:
                    state = _S.DONE
                else:
                    state = _S.INVALID
            case _S.IS_KEYWORD:
                if keyword is Keyword.NOT:
                    state = _S.IS_NOT
                elif keyword is Keyword.EMPTY:
                    state = _S.DONE
                else:
                    state = _S.INVALID
            case _S.IS_NOT:
                state = _S.DONE if keyword is Keyword.EMPTY else _S.INVALID
            case _S.DONE:
                if keyword is Keyword.AND or keyword is Keyword.OR:
                    field, state = None, _S.TERM
                elif token.kind is TokenKind.RPAREN and depth > 0:
                    depth -= 1
                elif keyword is Keyword.ORDER and depth == 0:
                    state = _S.ORDER
                else:
                    state = _S.INVALID
            case _S.ORDER:
                state = _S.ORDER_FIELD if keyword is Keyword.BY else _S.INVALID
            case _S.ORDER_FIELD:
                if token.kind is TokenKind.WORD and keyword is None:
                    state = _S.ORDER_DIR
                else:
                    state = _S.INVALID
            case _S.ORDER_DIR:
                if keyword is Keyword.ASC or keyword is Keyword.DESC:
                    state = _S.ORDER_NEXT
                elif token.kind is TokenKind.COMMA:
                    state = _S.ORDER_FIELD
                else:
                    state = _S.INVALID
            case _S.ORDER_NEXT:
                state = _S.ORDER_FIELD if token.kind is TokenKind.COMMA else _S.INVALID
            case _S.INVALID:
                break
        at_start = False
    return _MachineResult(state, depth, just_not), field


@dataclass(frozen=True)
class _MachineResult:
    state: _S
    depth: int
    just_not: bool


def _detection(
    result: _MachineResult, field: str | None, replace_from: int, partial: str
) -> Detection:
    def make(
        context: SuggestContext,
        offer: Offer,
        keywords: tuple[KeywordSuggestion, ...] = (),
        with_field: bool = False,
    ) -> Detection:
        return Detection(
            context,
            offer,
            replace_from,
            partial,
            field=field if with_field else None,
            keywords=keywords,
        )

    match result.state:
        case _S.TERM:
            keywords = () if result.just_not else (KeywordSuggestion.NOT,)
            return make(SuggestContext.FIELD, Offer.FIELDS, keywords)
        case _S.FIELD_DONE:
            return make(SuggestContext.OPERATOR, Offer.OPERATORS, with_field=True)
        case _S.FIELD_NOT:
            return make(
                SuggestContext.OPERATOR, Offer.KEYWORDS, (KeywordSuggestion.IN,), with_field=True
            )
        case _S.OP_DONE | _S.IN_VALUE:
            return make(SuggestContext.VALUE, Offer.VALUES, with_field=True)
        case _S.IN_KEYWORD:  # expecting '(' — nothing sensible to insert
            return make(SuggestContext.VALUE, Offer.NOTHING, with_field=True)
        case _S.IN_NEXT:  # expecting ',' or ')'
            return make(SuggestContext.KEYWORD, Offer.NOTHING)
        case _S.IS_KEYWORD:
            return make(
                SuggestContext.OPERATOR,
                Offer.KEYWORDS,
                (KeywordSuggestion.EMPTY, KeywordSuggestion.NOT_EMPTY),
                with_field=True,
            )
        case _S.IS_NOT:
            return make(
                SuggestContext.OPERATOR, Offer.KEYWORDS, (KeywordSuggestion.EMPTY,), with_field=True
            )
        case _S.DONE:
            keywords = (KeywordSuggestion.AND, KeywordSuggestion.OR)
            if result.depth == 0:
                keywords += (KeywordSuggestion.ORDER_BY,)
            return make(SuggestContext.KEYWORD, Offer.KEYWORDS, keywords)
        case _S.ORDER:
            return make(SuggestContext.KEYWORD, Offer.KEYWORDS, (KeywordSuggestion.BY,))
        case _S.ORDER_FIELD:
            return make(SuggestContext.FIELD, Offer.SORTABLE_FIELDS)
        case _S.ORDER_DIR:
            return make(
                SuggestContext.KEYWORD,
                Offer.KEYWORDS,
                (KeywordSuggestion.ASC, KeywordSuggestion.DESC),
            )
    # ORDER_NEXT (expecting ',') and INVALID: position understood, nothing to offer.
    return make(SuggestContext.KEYWORD, Offer.NOTHING)
