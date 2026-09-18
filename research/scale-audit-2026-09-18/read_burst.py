"""Local READ ONLY service burst, not a 100-user HTTP/browser capacity test.

Uses one existing restricted member with fresh sessions per operation. The mix
is 50% issue reads, 30% project lists, 10% search, 10% cross-project summaries.
Pool: application configuration. Guardrails: 15s SQL / 45s operation timeout.
No writes, external deliveries, application lifespan, or workers are started.
Run from server/: .venv/bin/python ../research/scale-audit-2026-09-18/read_burst.py 10
"""
import asyncio
import json
import math
import resource
import sys
import time
from collections import Counter
from pathlib import Path
from sqlalchemy import select, text
import profile_reads as p


def distribution(values):
    if not values:
        return {}
    values=sorted(values)
    return {'p50_ms':round(values[math.ceil(len(values)*.5)-1],2),
            'p95_ms':round(values[math.ceil(len(values)*.95)-1],2),
            'max_ms':round(values[-1],2)}


async def main():
    size=int(sys.argv[1]) if len(sys.argv)>1 else 10
    jit = sys.argv[2] if len(sys.argv)>2 else 'default'
    if jit not in ('default','on','off'):
        raise ValueError('JIT must be default, on, or off')
    if not 1<=size<=100:
        raise ValueError('Burst must be between 1 and 100')
    async with p.SessionLocal() as session:
        await p.prepare(session)
        pid=(await session.execute(text('SELECT project_id FROM work_items GROUP BY project_id ORDER BY count(*) DESC LIMIT 1'))).scalar_one()
        candidates=(await session.execute(text("SELECT u.id FROM users u JOIN work_items w ON w.assignee_id=u.id WHERE u.instance_role='member' AND u.active AND u.source NOT IN ('principal','service','email') GROUP BY u.id ORDER BY count(*) DESC LIMIT 8"))).scalars().all()
        for uid in candidates:
            user=await session.get(p.User,uid)
            if pid in await p.authz.readable_projects(session,user):
                items=await p.list_items(session,actor=user,filters=p.ItemListFilters(project_id=pid),limit=1,offset=0)
                if items:
                    key=items[0].key
                    break
        else:
            raise RuntimeError('No member fixture')

    lag=[]
    async def monitor():
        expected=time.perf_counter()+.05
        while True:
            await asyncio.sleep(.05)
            now=time.perf_counter()
            lag.append(max(0,(now-expected)*1000))
            expected=now+.05

    async def one(index):
        kind='detail' if index%10<5 else 'list' if index%10<8 else 'search' if index%10==8 else 'summary'
        began=time.perf_counter()
        acquisition_ms=None
        error=None
        error_reason=None
        try:
            async with asyncio.timeout(45):
                async with p.SessionLocal() as session:
                    await session.connection()
                    acquisition_ms=(time.perf_counter()-began)*1000
                    await p.prepare(session)
                    if jit != 'default':
                        await session.execute(text('SET LOCAL jit = '+jit))
                    user=await session.get(p.User,uid)
                    if kind=='detail':
                        await p.get_item_by_key(session,key,user)
                    elif kind=='list':
                        await p.list_items(session,actor=user,filters=p.ItemListFilters(project_id=pid),limit=25,offset=0)
                    elif kind=='search':
                        await p.search(session,user,'render',limit=20)
                    else:
                        await p.grouped_items(session,user,p.GroupPageRequest(axis='state',summary_only=True))
        except Exception as exc:
            error=type(exc).__name__
            error_reason=str(getattr(exc,'orig','')).split('\n')[0][:200]
        return {'kind':kind,'ms':round((time.perf_counter()-began)*1000,2),
                'connection_acquisition_ms':round(acquisition_ms,2) if acquisition_ms is not None else None,'error':error,'error_reason':error_reason}

    task=asyncio.create_task(monitor())
    began=time.perf_counter()
    rows=await asyncio.gather(*(one(i) for i in range(size)))
    wall=time.perf_counter()-began
    task.cancel()
    await asyncio.gather(task,return_exceptions=True)
    result={'concurrent_operations':size,'actor':'one existing restricted member',
            'transaction_local_jit':jit,
            'pool_size':p.settings.db_pool_size,'pool_overflow':p.settings.db_max_overflow,
            'wall_seconds':round(wall,2),'completed_per_second':round(sum(r['error'] is None for r in rows)/wall,2),
            'successful':sum(r['error'] is None for r in rows),'errors':dict(Counter(r['error'] for r in rows if r['error'])),
            'all_completion':distribution([r['ms'] for r in rows]),
            'connection_acquisition':distribution([r['connection_acquisition_ms'] for r in rows if r['connection_acquisition_ms'] is not None]),
            'event_loop_lag':distribution(lag),'process_max_rss_kib_linux':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            'by_operation':{kind:{'success':sum(r['error'] is None for r in rows if r['kind']==kind),
                                  **distribution([r['ms'] for r in rows if r['kind']==kind and r['error'] is None])}
                            for kind in ['detail','list','search','summary']},'operations':rows}
    suffix='' if jit=='default' else '-jit-'+jit
    output = Path(sys.argv[3]) if len(sys.argv) > 3 else Path(__file__).with_name(f'read-burst-{size}{suffix}.json')
    output.write_text(json.dumps(result,indent=2))
    print(json.dumps({k:v for k,v in result.items() if k!='operations'},indent=2),flush=True)
    await p.engine.dispose()


asyncio.run(main())
