"""The item-key grammar every connector reads refs with, and the link a webhook
parser plans. Pure; the receiver resolves keys and writes."""

import re
from dataclasses import dataclass

from .types import VcsRefType

# An item key referenced in text: TD-123 (project keys are 1-10 alnum starting
# with a letter). Word-bounded so sha1-2abc doesn't match.
KEY_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9]{0,9}-\d+)\b")


@dataclass(frozen=True)
class PlannedLink:
    item_key: str  # upper-cased "TD-123"
    ref_type: VcsRefType
    external_id: str
    title: str
    url: str
    status: str = ""


def extract_keys(*texts: str | None) -> list[str]:
    """Upper-cased, deduped, order-preserving item keys found in the texts."""
    seen: list[str] = []
    for text in texts:
        for match in KEY_RE.finditer(text or ""):
            key = match.group(1).upper()
            if key not in seen:
                seen.append(key)
    return seen
