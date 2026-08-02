from enum import StrEnum

# Spec 74: how many public-KB pages the tokened form deflection returns
# (mirrors the authed deflection's DEFLECT_LIMIT in search/types.py).
PUBLIC_DEFLECT_LIMIT = 5


class FormEvent(StrEnum):
    CREATED = "form.created"
    UPDATED = "form.updated"
    DELETED = "form.deleted"


class FormEntity(StrEnum):
    FORM = "form"
