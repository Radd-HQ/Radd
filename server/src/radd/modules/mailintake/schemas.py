from pydantic import BaseModel, ConfigDict


class MailContactRead(BaseModel):
    """One external person on an item's mail thread (spec 62) — the issue rail's
    "External requester" chip renders these.

    `is_primary` was added by RADD-980 when the table became n-ary. It is
    additive on the wire: the singular `GET /items/{id}/mail-contact` still
    answers one object with `email` and `name` where it always did, and the
    plural endpoint uses the same shape so the rail can mark which of several
    addresses is the one the ticket was raised from.
    """

    model_config = ConfigDict(from_attributes=True)

    email: str
    name: str
    is_primary: bool = False
