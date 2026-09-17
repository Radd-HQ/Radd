"""Opt-in keyset continuation using the compiler's exact PostgreSQL ordering.

Tokens contain encrypted boundary values, never authorization. Scope and actor
are bound to the token; every request still rebuilds current visibility rules.
"""

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, false, or_
from sqlalchemy.sql import operators

from radd import secretbox
from .filters import FilterParseError


def scope_key(actor, scope):
    return hashlib.sha256(
        json.dumps([str(actor.id), scope], default=str, sort_keys=True).encode()
    ).hexdigest()


def terms(order):
    # The SLQ compiler emits ASC/DESC, without explicit null placement. Match
    # PostgreSQL: ASC NULLS LAST, DESC NULLS FIRST. Reject unknown modifiers.
    result = []
    for expression in order:
        if expression.modifier not in (operators.asc_op, operators.desc_op):
            raise FilterParseError("This order does not support cursor continuation")
        result.append((expression.element, expression.modifier is operators.desc_op))
    return result


def _pack(value):
    for kind, typ in [("datetime", datetime), ("date", date), ("decimal", Decimal), ("uuid", UUID)]:
        if isinstance(value, typ):
            return [kind, str(value)]
    return ["value", value]


def encode(scope, values, position):
    data = {
        "kind": "item-cursor-v1",
        "scope": scope,
        "position": position,
        "values": [_pack(v) for v in values],
    }
    token = secretbox.encrypt(json.dumps(data))
    # Huge custom text sorts must not create URLs rejected by reverse proxies.
    # Preserve navigation using the existing offset behavior for that boundary.
    if len(token) > 4096:
        data["values"] = None
        token = secretbox.encrypt(json.dumps(data))
    return token


def decode(token, scope, length):
    try:
        if len(token) > 16384 or not secretbox.is_encrypted(token):
            raise ValueError()
        data = json.loads(secretbox.decrypt(token))
        if (
            data["kind"] != "item-cursor-v1"
            or data["scope"] != scope
            or not isinstance(data["position"], int)
            or data["position"] < 0
        ):
            raise ValueError()
        if data["values"] is None:
            return None, data["position"]
        if len(data["values"]) != length:
            raise ValueError()
        parsers = {
            "datetime": datetime.fromisoformat,
            "date": date.fromisoformat,
            "decimal": Decimal,
            "uuid": UUID,
            "value": lambda x: x,
        }
        return [parsers[k](v) for k, v in data["values"]], data["position"]
    except (ValueError, TypeError, KeyError, secretbox.SecretBoxError) as exc:
        raise FilterParseError(
            "This continuation is invalid for the current view. Refresh to start again."
        ) from exc


def after_clause(order, values):
    equals, choices = [], []
    for (column, descending), value in zip(terms(order), values, strict=True):
        if value is None:
            later = column.is_not(None) if descending else false()
            equal = column.is_(None)
        else:
            # Boolean expressions have no Python SQLAlchemy < / > operator;
            # SQL's ordered comparison still supports bool bind values.
            later = column.op("<" if descending else ">")(value)
            if not descending:
                later = or_(later, column.is_(None))
            equal = column == value
        choices.append(and_(*equals, later))
        equals.append(equal)
    return or_(*choices)
