"""Internal-comment visibility gate (spec 50): teams narrow, never replace, the
comment.read_internal audience. Pure — the decision every comment surface reuses."""

import uuid

from radd.modules.comments.visibility import internal_comment_visible

T1, T2, T3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def gate(**overrides):
    base = dict(
        is_author=False,
        has_read_internal=True,
        has_manage=False,
        comment_teams=set(),
        actor_teams=set(),
    )
    base.update(overrides)
    return internal_comment_visible(**base)


def test_unrestricted_internal_visible_to_any_reader():
    assert gate(comment_teams=set()) is True


def test_non_reader_denied_unless_author_or_manager():
    assert gate(has_read_internal=False) is False
    assert gate(has_read_internal=False, is_author=True) is True
    assert gate(has_read_internal=False, has_manage=True) is True


def test_team_narrowing_requires_membership():
    assert gate(comment_teams={T1, T2}, actor_teams={T2}) is True
    assert gate(comment_teams={T1, T2}, actor_teams={T3}) is False
    # a reader with read_internal but no overlapping team is shut out
    assert gate(comment_teams={T1}, actor_teams=set()) is False


def test_author_and_manager_bypass_team_restriction():
    assert gate(comment_teams={T1}, actor_teams=set(), is_author=True) is True
    assert gate(comment_teams={T1}, actor_teams=set(), has_manage=True) is True
