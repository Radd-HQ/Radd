"""Composable, depth-limited directory membership reads owned by groups."""
from sqlalchemy import Select, literal, select

from radd.config import settings
from .models import Group, GroupMember, GroupParent


def member_projection(root_ids: Select) -> Select:
    """Distinct (root_id, user_id), including descendants at the supported depth.

    UNION deduplicates each root/node/depth frontier, including diamonds and
    cycles. No path enumeration or Python-sized user-id set is needed. The
    depth bound matches group_user_ids, including the seed at depth zero.
    """
    reach = select(Group.id.label("root_id"), Group.id.label("group_id"),
                   literal(0).label("depth")).where(Group.id.in_(root_ids)).cte(
                       "group_member_reach", recursive=True)
    reach = reach.union(select(reach.c.root_id, GroupParent.child_id, reach.c.depth + 1)
                        .join(GroupParent, GroupParent.parent_id == reach.c.group_id)
                        .where(reach.c.depth < settings.group_nesting_max_depth))
    return select(reach.c.root_id, GroupMember.user_id).join(
        GroupMember, GroupMember.group_id == reach.c.group_id).distinct()
