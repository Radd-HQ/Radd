from enum import StrEnum

# Spec 74: how many public-KB pages the tokened form deflection returns
# (mirrors the authed deflection's DEFLECT_LIMIT in search/types.py).
PUBLIC_DEFLECT_LIMIT = 5


class FormEvent(StrEnum):
    CREATED = "form.created"
    UPDATED = "form.updated"
    DELETED = "form.deleted"
    #: RADD-800 — a person's submission staging area was reclaimed. Emitted by
    #: the age sweep, and named `.deleted` because that is exactly what it is
    #: from the GC's point of view: the parent is gone, take its rows and bytes.
    #: Fitting the existing cascade beat inventing a second cleanup path.
    STAGING_DELETED = "form.staging.deleted"


class FormEntity(StrEnum):
    FORM = "form"
