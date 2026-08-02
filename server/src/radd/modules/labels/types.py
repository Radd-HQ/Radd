from enum import StrEnum


class LabelEvent(StrEnum):
    CREATED = "label.created"
    UPDATED = "label.updated"  # spec 87 — rename/recolor
    DELETED = "label.deleted"  # spec 87 — detaches from every item (item_labels CASCADE)


class LabelEntity(StrEnum):
    LABEL = "label"
