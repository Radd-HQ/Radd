"""Effective membership must be deduplicated before roster/candidate windows."""
from test_team_directory import team_reader_account
import uuid

import httpx
import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.app import create_app
from radd.config import settings
from radd.db import get_session
from radd.modules.auth import service as auth
from radd.modules.auth.models import User
from radd.modules.auth.schemas import TokenCreate
from radd.modules.auth.types import UserSource
from radd.modules.groups import service as groups
from radd.modules.groups.models import Group, GroupMember, GroupParent
from radd.modules.teams import service as teams
from radd.modules.teams.models import Team, TeamManager, TeamMember


@pytest.mark.parametrize('depth', [0, 1, 2, 4])
async def test_group_projection_matches_depth_limited_cyclic_diamond_closure(monkeypatch, depth):
    monkeypatch.setattr(settings, 'group_nesting_max_depth', depth)
    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        prefix = uuid.uuid4().hex
        nodes = [Group(name=f'Group {i}', dn=f'{prefix}-{i}') for i in range(5)]
        users = [User(name=f'Person {i}', email=f'{prefix}-{i}@test.invalid') for i in range(5)]
        db.add_all([*nodes, *users]); await db.flush()
        db.add_all([GroupMember(group_id=g.id, user_id=u.id) for g, u in zip(nodes, users)])
        db.add_all([GroupParent(parent_id=nodes[a].id, child_id=nodes[b].id)
                    for a, b in [(0, 1), (0, 2), (1, 3), (2, 3), (3, 0), (3, 4)]])
        await db.flush()
        projection = groups.member_projection(select(Group.id).where(Group.id.in_([nodes[0].id, nodes[2].id])))
        rows = (await db.execute(projection)).all()
        for root in (nodes[0], nodes[2]):
            expected = await groups.group_user_ids(db, root.id)
            actual = [user_id for root_id, user_id in rows if root_id == root.id]
            assert set(actual) == expected
            assert len(actual) == len(expected)
        await db.rollback()
    await engine.dispose()


async def test_roster_http_windows_provenance_candidates_and_guards():
    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        prefix = uuid.uuid4().hex
        actor = User(name='Directory operator', email=prefix+'@test.invalid', instance_role='admin')
        people = [User(name=f'Roster {i:03}', email=f'{prefix}-member-{i}@test.invalid') for i in range(126)]
        candidates = [User(name=f'Candidate {i:03}', email=f'{prefix}-candidate-{i}@test.invalid') for i in range(126)]
        inactive = User(name='Candidate inactive', email=prefix+'-inactive@test.invalid', active=False)
        requester = User(name='Candidate requester', email=prefix+'-requester@test.invalid', source=UserSource.EMAIL)
        service = User(name='Candidate service', email=prefix+'-service@test.invalid', source=UserSource.SERVICE)
        roots = [Group(name=name, dn=prefix+name) for name in ('A carrier', 'Z carrier', 'Child')]
        team = Team(name=prefix+' team')
        db.add_all([actor, *people, *candidates, inactive, requester, service, *roots, team]); await db.flush()
        db.add_all([TeamMember(team_id=team.id, user_id=u.id) for u in people[:70]])
        db.add_all([TeamMember(team_id=team.id, group_id=g.id) for g in roots[:2]])
        db.add_all([GroupMember(group_id=roots[2].id, user_id=u.id) for u in people[40:]])
        db.add_all([GroupMember(group_id=roots[1].id, user_id=u.id) for u in people[100:]])
        db.add(GroupParent(parent_id=roots[0].id, child_id=roots[2].id)); await db.flush()
        await team_reader_account(db, actor)
        _, token = await auth.create_api_token(db, actor, TokenCreate(name='Roster', scopes={'global': ['team.read', 'team.update']}))
        async def override(): yield db
        app = create_app(); app.dependency_overrides[get_session] = override
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test',
                                     headers={'Authorization': f'Bearer {token}'}) as client:
            path = f'/api/v1/teams/{team.id}'
            seen = []
            for offset, count in [(0, 50), (50, 50), (100, 26)]:
                sql = []
                def record(conn, cursor, statement, parameters, context, executemany): sql.append(statement)
                event.listen(engine.sync_engine, 'before_cursor_execute', record)
                try: r = await client.get(path+'/members', params={'limit': 50, 'offset': offset})
                finally: event.remove(engine.sync_engine, 'before_cursor_execute', record)
                assert r.status_code == 200, r.text
                assert len(r.json()) == count and r.headers['X-Total-Count'] == '126'
                roster_sql = [stmt for stmt in sql if 'WITH RECURSIVE group_member_reach' in stmt]
                assert len(roster_sql) == 2  # count and lean window, independent of group count
                assert all('password' not in stmt for stmt in roster_sql)
                assert 'LIMIT' in roster_sql[-1]
                seen.extend(r.json())
            assert [row['user_id'] for row in seen] == [str(u.id) for u in people]
            assert all(row['via_group'] is None for row in seen[:70])
            assert all(row['via_group'] == 'A carrier' for row in seen[70:])
            assert (await client.get(path+'/members')).json() == seen  # existing callers retain full read
            r = await client.get(path+'/members', params={'q': '  ROSTER 125  ', 'limit': 50})
            assert r.headers['X-Total-Count'] == '1' and r.json()[0]['user_id'] == str(people[125].id)
            r = await client.get(path+'/members', params={'q': people[125].email, 'limit': 50})
            assert r.headers['X-Total-Count'] == '1'
            assert (await client.get(path+'/member-candidates')).status_code == 403
            # Intrinsic delegated manager with only team.read may choose/add people.
            db.add(TeamManager(team_id=team.id, user_id=actor.id)); await db.flush(); db.info.clear()
            for offset, count in [(0, 50), (50, 50), (100, 27)]:
                r = await client.get(path+'/member-candidates', params={'q': 'Candidate', 'limit': 50, 'offset': offset})
                assert r.status_code == 200, r.text
                assert len(r.json()) == count and r.headers['X-Total-Count'] == '127'
                assert all(set(row) == {'id', 'name'} for row in r.json())
            r = await client.get(path+'/member-candidates', params={'q': 'Roster'})
            assert r.json() == [] and r.headers['X-Total-Count'] == '0'
            r = await client.post(path+'/members', json={'user_id': str(candidates[125].id)})
            assert r.status_code == 201, r.text
            r = await client.get(path+'/member-candidates', params={'q': 'Candidate 125'})
            assert r.json() == [] and r.headers['X-Total-Count'] == '0'
            # Removing a direct membership must reveal, not remove, inherited membership.
            assert (await client.delete(path+'/members/'+str(people[50].id))).status_code == 204
            r = await client.get(path+'/members', params={'q': 'Roster 050', 'limit': 50})
            assert r.json()[0]['via_group'] == 'A carrier'
            for suffix in ('/members', '/member-candidates'):
                for params in ({'limit': 0}, {'limit': 201}, {'offset': -1}, {'q': 'x'*201}):
                    assert (await client.get(path+suffix, params=params)).status_code == 422
                r = await client.get(path+suffix, params={'q': '%_', 'limit': 50})
                assert r.json() == [] and r.headers['X-Total-Count'] == '0'
                assert (await client.get(f'/api/v1/teams/{uuid.uuid4()}'+suffix)).status_code == 404
        assert len(await teams.list_team_members(db, team.id)) == 127
        await db.rollback()
    await engine.dispose()
