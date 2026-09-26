"""Internal-comment visibility as a pure predicate (spec 50). Teams NARROW the
`comment.read_internal` audience, never replace it. `reading.audience` is the SQL
form of the same rule; this one serves callers already holding rows (notify
fan-out, history). Keep the two in step.
"""

import uuid
from collections.abc import Set


def internal_comment_visible(
    *,
    is_author: bool,
    has_read_internal: bool,
    has_manage: bool,
    comment_teams: Set[uuid.UUID],
    actor_teams: Set[uuid.UUID],
) -> bool:
    """May the actor read this INTERNAL comment? (public comments never call this.)

    - the author and project managers always can (own note / oversight);
    - otherwise `comment.read_internal` is required (the staff gate), AND
    - if the comment names teams, the actor must belong to one of them.
    Empty `comment_teams` = every internal-reader.
    """
    if has_manage or is_author:
        return True
    if not has_read_internal:
        return False
    if not comment_teams:
        return True
    return bool(comment_teams & actor_teams)
