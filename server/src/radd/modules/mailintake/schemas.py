from pydantic import BaseModel, ConfigDict


class MailContactRead(BaseModel):
    """One external person on an item's mail thread; the rail marks `is_primary`."""

    model_config = ConfigDict(from_attributes=True)

    email: str
    name: str
    is_primary: bool = False
