"""SLQ lexer: query text -> position-carrying tokens.

Keywords (AND, OR, IN, …) are plain WORD tokens here — the parser gives them
meaning, so a *quoted* value can never collide with a keyword or sentinel.
"""

from dataclasses import dataclass
from enum import StrEnum

from .errors import SlqError


class TokenKind(StrEnum):
    WORD = "word"  # bareword: fields, keywords, enum values, numbers, dates, emails, keys
    STRING = "string"  # quoted value ('…' or "…"), backslash-escaped
    OP = "op"  # a CompareOp symbol
    LPAREN = "("
    RPAREN = ")"
    COMMA = ","
    EOF = "end of query"


class CompareOp(StrEnum):
    EQ = "="
    NE = "!="
    CONTAINS = "~"  # case-insensitive substring (title/text fields)
    GT = ">"
    LT = "<"
    GE = ">="
    LE = "<="


# Longest first so ">=" never lexes as ">" then "=".
_OPERATORS = (CompareOp.GE, CompareOp.LE, CompareOp.NE, CompareOp.EQ,
              CompareOp.CONTAINS, CompareOp.GT, CompareOp.LT)
_PUNCTUATION = {"(": TokenKind.LPAREN, ")": TokenKind.RPAREN, ",": TokenKind.COMMA}
_QUOTES = ("'", '"')
_ESCAPE = "\\"
# With alphanumerics these cover emails, item keys (TD-12), dates, decimals, cf keys.
_WORD_EXTRA = "_.@+-/"


@dataclass(frozen=True)
class Token:
    kind: TokenKind
    text: str  # decoded content for STRING; the symbol for OP; raw for WORD
    position: int  # character offset in the query text


def _is_word_char(char: str) -> bool:
    return char.isalnum() or char in _WORD_EXTRA


def tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    i, length = 0, len(text)
    while i < length:
        char = text[i]
        if char.isspace():
            i += 1
        elif char in _PUNCTUATION:
            tokens.append(Token(_PUNCTUATION[char], char, i))
            i += 1
        elif operator := next((op for op in _OPERATORS if text.startswith(op.value, i)), None):
            tokens.append(Token(TokenKind.OP, operator.value, i))
            i += len(operator.value)
        elif char in _QUOTES:
            token, i = _read_string(text, i)
            tokens.append(token)
        elif _is_word_char(char):
            start = i
            while i < length and _is_word_char(text[i]):
                i += 1
            tokens.append(Token(TokenKind.WORD, text[start:i], start))
        else:
            raise SlqError(f"unexpected character {char!r}", i)
    tokens.append(Token(TokenKind.EOF, TokenKind.EOF.value, length))
    return tokens


def _read_string(text: str, start: int) -> tuple[Token, int]:
    quote = text[start]
    chars: list[str] = []
    i = start + 1
    while i < len(text):
        if text[i] == _ESCAPE and i + 1 < len(text):
            chars.append(text[i + 1])
            i += 2
        elif text[i] == quote:
            return Token(TokenKind.STRING, "".join(chars), start), i + 1
        else:
            chars.append(text[i])
            i += 1
    raise SlqError("unterminated string", start)
