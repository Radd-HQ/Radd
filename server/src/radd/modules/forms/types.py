from enum import StrEnum

class FormEvent(StrEnum):
    CREATED = "form.created"
    UPDATED = "form.updated"
    DELETED = "form.deleted"
    #: RADD-1320 — someone submitted this form and an issue was created. The
    #: item, the form's project and the submitter are subjects; `item.created`
    #: alone could not say WHICH form produced the issue.
    SUBMITTED = "form.submitted"
    #: RADD-800 — a person's submission staging area was reclaimed. Emitted by
    #: the age sweep, and named `.deleted` because that is exactly what it is
    #: from the GC's point of view: the parent is gone, take its rows and bytes.
    #: Fitting the existing cascade beat inventing a second cleanup path.
    STAGING_DELETED = "form.staging.deleted"


class FormEntity(StrEnum):
    FORM = "form"


class FormShareSubject(StrEnum):
    USER = "user"
    TEAM = "team"
