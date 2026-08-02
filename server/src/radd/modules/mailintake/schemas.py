from pydantic import BaseModel, ConfigDict


class MailContactRead(BaseModel):
    """The external requester behind an item (spec 62) — the issue rail's
    "External requester" chip renders this."""

    model_config = ConfigDict(from_attributes=True)

    email: str
    name: str
