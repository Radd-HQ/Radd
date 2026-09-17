"""Values shared by mail composition and delivery adapters."""
from dataclasses import dataclass


@dataclass(frozen=True)
class MailAttachment:
    filename: str
    content_type: str
    data: bytes
