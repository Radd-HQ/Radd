"""Bounded, read-only diagnostics for permission SQL and oversized batches."""
import asyncio
import hashlib
import json
import time
import sys
from pathlib import Path
from sqlalchemy import select, text
import profile_reads as p
from radd.modules.items.service import items_by_ids


async def main():
    output = {}
    async with p.SessionLocal() as session:
        await p.prepare(session)
        project_id = (await session.execute(text('SELECT project_id FROM work_items GROUP BY project_id ORDER BY count(*) DESC LIMIT 1'))).scalar_one()
        candidates = (await session.execute(text("SELECT u.id FROM users u JOIN work_items w ON w.assignee_id=u.id WHERE u.instance_role='member' AND u.active AND u.source NOT IN ('principal','service','email') GROUP BY u.id ORDER BY count(*) DESC LIMIT 8"))).scalars().all()
        for uid in candidates:
            user = await session.get(p.User,uid)
            if project_id in await p.authz.readable_projects(session,user):
                break
        else:
            raise RuntimeError('No member fixture found')

    for jit in ['off','on']:
        async with p.SessionLocal() as session:
            await p.prepare(session)
            await session.execute(text('SET LOCAL jit = '+jit))
            user = await session.get(p.User,uid)
            p.queries.clear(); p.raw_queries.clear(); p.active=True
            started=time.perf_counter()
            try:
                result=await p.grouped_items(session,user,p.GroupPageRequest(axis='state',summary_only=True))
            finally:
                p.active=False
            ms=(time.perf_counter()-started)*1000
            # Inspect the summary itself even when a cold metadata lookup
            # happens to take longer after the optimization.
            _,sql,params=max((q for q in p.raw_queries if 'GROUP BY' in q[1] and 'work_items' in q[1]),key=lambda q:q[0])
            conn=await session.connection()
            plan=(await conn.exec_driver_sql('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) '+sql,params)).scalar_one()[0]
            output['summary_jit_'+jit]={'ms':round(ms,2),'queries':len(p.queries),'result_sha256':hashlib.sha256(json.dumps(result.model_dump(mode='json'),sort_keys=True).encode()).hexdigest(),'execution_ms':plan['Execution Time'],'planning_ms':plan['Planning Time'],'jit':plan.get('JIT')}
            print(json.dumps({jit:output['summary_jit_'+jit]}),flush=True)

    async with p.SessionLocal() as session:
        await p.prepare(session)
        ids=(await session.execute(text('SELECT id FROM work_items WHERE project_id=:p AND archived_at IS NULL'),{'p':project_id})).scalars().all()
        started=time.perf_counter()
        try:
            rows=await items_by_ids(session,ids)
            output['large_item_batch']={'ids':len(ids),'returned':len(rows),'ms':round((time.perf_counter()-started)*1000,2)}
        except Exception as exc:
            output['large_item_batch']={'ids':len(ids),'error':type(exc).__name__,'reason':str(getattr(exc,'orig',type(exc).__name__)).split('\n')[0][:250]}
        print(json.dumps(output['large_item_batch']),flush=True)
    destination = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name('scale-diagnostics.json')
    destination.write_text(json.dumps(output,indent=2))
    await p.engine.dispose()


asyncio.run(main())
