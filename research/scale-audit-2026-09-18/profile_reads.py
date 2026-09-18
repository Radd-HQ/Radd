"""Read-only local service profiles. Run from server/ with its virtualenv.

No application lifespan, workers, login, or mutations are executed. Every
transaction is READ ONLY, statements have a timeout, and sessions roll back.
Results contain timings/query shapes, not issue contents or account names.
This measures services, excluding HTTP, authentication, and browser rendering.
"""
import asyncio
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

from sqlalchemy import event, select, text
from radd.config import settings
from radd.kernel import import_models, load_plugins

import_models(settings.modules)
load_plugins(settings.modules)

from radd.db import SessionLocal, engine
from radd.modules.auth import authz
from radd.modules.auth.models import User
from radd.modules.items.filters import ItemListFilters
from radd.modules.items.service import get_item_by_key, list_items
from radd.modules.items.grouped import grouped_items
from radd.modules.items.grouped_schemas import GroupPageRequest
from radd.modules.items.bulk import count_items, visible_matching_ids
from radd.modules.search.service import search

queries = []
active = False
raw_queries = []


@event.listens_for(engine.sync_engine, "before_cursor_execute")
def before(conn, cursor, statement, parameters, context, executemany):
    context.audit_start = time.perf_counter()


@event.listens_for(engine.sync_engine, "after_cursor_execute")
def after(conn, cursor, statement, parameters, context, executemany):
    if active:
        elapsed = (time.perf_counter()-context.audit_start)*1000
        raw_queries.append((elapsed, statement, parameters))
        queries.append({"ms": round(elapsed, 2),
                        "sql": re.sub(r"\s+", " ", statement)[:1600],
                        "parameter_count": len(parameters) if parameters else 0})


async def prepare(session):
    await session.execute(text("SET TRANSACTION READ ONLY"))
    await session.execute(text("SET LOCAL statement_timeout = '15s'"))


async def main():
    global active
    results = []
    async with SessionLocal() as session:
        await prepare(session)
        admin = await session.scalar(select(User).where(User.instance_role == "admin", User.active.is_(True)))
        if admin is None:
            raise RuntimeError("No existing administrator to profile read permissions")
        admin_id = admin.id
        project_id, project_count = (await session.execute(text(
            "SELECT project_id,count(*) FROM work_items GROUP BY project_id ORDER BY count(*) DESC LIMIT 1"
        ))).one()
        issue_key = (await session.execute(text(
            "SELECT p.key || '-' || w.number FROM work_items w JOIN projects p ON p.id=w.project_id "
            "WHERE w.project_id=:pid ORDER BY w.rank LIMIT 1"
        ), {"pid": project_id})).scalar_one()
        state_id = (await session.execute(text(
            "SELECT state_id FROM work_items WHERE project_id=:pid GROUP BY state_id ORDER BY count(*) DESC LIMIT 1"
        ), {"pid": project_id})).scalar_one()
        candidates = (await session.execute(text(
            "SELECT u.id FROM users u JOIN work_items w ON w.assignee_id=u.id "
            "WHERE u.instance_role='member' AND u.active AND u.source NOT IN ('principal','service','email') "
            "GROUP BY u.id ORDER BY count(*) DESC LIMIT 8"
        ))).scalars().all()
        member_id = None
        for uid in candidates:
            user = await session.get(User, uid)
            if project_id in await authz.readable_projects(session, user):
                member_id = uid
                break
        inventory = {"largest_project_items": project_count, "member_available": bool(member_id),
                     "pool_size": settings.db_pool_size, "pool_overflow": settings.db_max_overflow}

    operations = [
        ("issue_detail", lambda s,u: get_item_by_key(s, role_issue_key, u)),
        ("project_list_25", lambda s,u: list_items(s, actor=u, filters=ItemListFilters(project_id=project_id), limit=25, offset=0)),
        ("cross_project_list_25", lambda s,u: list_items(s, actor=u, filters=ItemListFilters(), limit=25, offset=0)),
        ("project_list_offset_20000", lambda s,u: list_items(s, actor=u, filters=ItemListFilters(project_id=project_id), limit=25, offset=20000)),
        ("project_state_summary", lambda s,u: grouped_items(s,u,GroupPageRequest(project_id=project_id, axis="state",summary_only=True))),
        ("cross_project_state_summary", lambda s,u: grouped_items(s,u,GroupPageRequest(axis="state",summary_only=True))),
        ("cross_project_assignee_summary", lambda s,u: grouped_items(s,u,GroupPageRequest(axis="assignee",summary_only=True))),
        ("project_state_cell_25", lambda s,u: grouped_items(s,u,GroupPageRequest(project_id=project_id,axis="state",column_key=str(state_id),rows_only=True,cursor_mode=True))),
        ("all_visible_count", lambda s,u: count_items(s,actor=u,filters=ItemListFilters())),
        ("search_issue_key", lambda s,u: search(s,u,role_issue_key,limit=20)),
        ("search_word_render", lambda s,u: search(s,u,"render",limit=20)),
        ("report_visible_id_universe", lambda s,u: visible_matching_ids(s,actor=u,q="")),
    ]
    for role, uid in [("admin", admin_id), ("member", member_id)]:
        if uid is None:
            continue
        role_issue_key = issue_key
        if role == "member":
            async with SessionLocal() as session:
                await prepare(session)
                user = await session.get(User, uid)
                readable_items = await list_items(session, actor=user, filters=ItemListFilters(project_id=project_id),limit=1,offset=0)
                role_issue_key = readable_items[0].key
        for name, operation in operations:
            async with SessionLocal() as session:
                await prepare(session)
                user = await session.get(User, uid)
                queries.clear()
                raw_queries.clear()
                started = time.perf_counter()
                active = True
                error = None
                value = None
                try:
                    value = await asyncio.wait_for(operation(session, user), timeout=30)
                except Exception as exc:
                    error = type(exc).__name__
                finally:
                    active = False
                elapsed = (time.perf_counter()-started)*1000
                result = {"role": role,"operation":name,"ms":round(elapsed,2),
                          "queries":len(queries),"sql_ms":round(sum(q["ms"] for q in queries),2),
                          "max_parameters":max((q["parameter_count"] for q in queries),default=0),
                          "rows":len(value) if isinstance(value,(list,set,dict)) else None,
                          "error":error,"slowest":sorted(queries,key=lambda q:q["ms"],reverse=True)[:4],
                          "repeated_shapes":[{"count":c,"sql":sql[:300]} for sql,c in Counter(q["sql"] for q in queries).most_common(5)]}
                results.append(result)
                print(json.dumps({k:v for k,v in result.items() if k not in ('slowest','repeated_shapes')}),flush=True)
                if not error and name in ('cross_project_state_summary','search_word_render','search_issue_key'):
                    _, sql, parameters = max(raw_queries,key=lambda row:row[0])
                    try:
                        conn = await session.connection()
                        plan = (await conn.exec_driver_sql('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) '+sql,parameters)).scalar_one()[0]
                        def brief(node):
                            keys = ('Node Type','Relation Name','Index Name','Actual Rows','Actual Loops',
                                    'Actual Total Time','Rows Removed by Filter','Rows Removed by Join Filter',
                                    'Shared Hit Blocks','Shared Read Blocks','Temp Read Blocks','Temp Written Blocks',
                                    'Sort Method','Sort Space Used','Sort Space Type')
                            return {**{k:node[k] for k in keys if k in node},'Plans':[brief(p) for p in node.get('Plans',[])]}
                        result['explain'] = {'execution_ms':plan['Execution Time'],'planning_ms':plan['Planning Time'],'jit':plan.get('JIT'),'plan':brief(plan['Plan'])}
                    except Exception as exc:
                        result['explain_error'] = type(exc).__name__
    output = Path(sys.argv[1]) if len(sys.argv)>1 else Path('/tmp/radd-scale-read-profile.json')
    output.write_text(json.dumps({"inventory":inventory,"results":results},indent=2))
    await engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
