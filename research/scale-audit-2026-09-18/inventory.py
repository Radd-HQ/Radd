"""Read-only fixture, index, and local machine inventory; never prints DSNs."""
import json
import os
import platform
from pathlib import Path
import psycopg
from radd.config import settings

tables=['work_items','comments','events','search_index','projects','users','teams','field_definitions']
with psycopg.connect(settings.database_url.replace('postgresql+psycopg:', 'postgresql:')) as conn:
    conn.execute('SET TRANSACTION READ ONLY')
    config=dict(conn.execute("SELECT name,setting FROM pg_settings WHERE name IN ('max_connections','shared_buffers','work_mem','effective_cache_size','max_parallel_workers_per_gather','statement_timeout','jit')").fetchall())
    conn.execute("SET LOCAL statement_timeout = '15s'")
    result={'tables':{t:conn.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in tables},
            'database_size':conn.execute('SELECT pg_size_pretty(pg_database_size(current_database()))').fetchone()[0],
            'database_settings_raw':config,
            'app_pool':{'retained':settings.db_pool_size,'overflow':settings.db_max_overflow,'workers_in_process':settings.run_workers},
            'indexes':conn.execute("SELECT tablename,indexdef FROM pg_indexes WHERE schemaname='public' AND tablename=ANY(%s) ORDER BY tablename,indexname",(['work_items','search_index','events','comments'],)).fetchall(),
            'enabled_sla_policies':conn.execute('SELECT count(*) FROM sla_policies WHERE enabled').fetchone()[0],
            'pg_stat_statements_installed':bool(conn.execute("SELECT count(*) FROM pg_extension WHERE extname='pg_stat_statements'").fetchone()[0])}
    conn.rollback()
result['host']={'system':platform.system(),'logical_cpus':os.cpu_count()}
if Path('/proc/cpuinfo').exists():
    result['host']['cpu']=next((line.split(':',1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')),None)
if Path('/proc/meminfo').exists():
    result['host']['memory_kib']={k:int(v.split()[0]) for k,v in (line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines()) if k in ('MemTotal','MemAvailable')}
Path(__file__).with_name('inventory.json').write_text(json.dumps(result,indent=2))
print(json.dumps({k:v for k,v in result.items() if k!='indexes'},indent=2))
