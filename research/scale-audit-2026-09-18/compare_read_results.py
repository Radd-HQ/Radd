"""Read-only response parity against the audited revision; no payloads saved.

Run from server/. Old query builders share the current schema/service seams;
this checks output compatibility, not a clean old-build latency benchmark.
"""
import asyncio
import dataclasses
import hashlib
import importlib
import json
from pathlib import Path
import subprocess

from sqlalchemy import text, select, func
import profile_reads as p
from radd.modules.search.models import SearchIndexRow
from radd.modules.search.service import build_tsquery
from radd.modules.search.types import SEARCH_TS_CONFIG


def old_function(module_name, name):
    module = importlib.import_module(module_name)
    relative = Path(module.__file__).resolve().relative_to(Path.cwd().parent)
    source = subprocess.check_output(["git", "show", f"1ce62ae:{relative}"], text=True)
    namespace = {"__name__": module_name, "__package__": module.__package__}
    exec(compile(source, str(relative), "exec"), namespace)
    return namespace[name]


def canonical(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if dataclasses.is_dataclass(value):
        return dataclasses.asdict(value)
    if isinstance(value, list):
        return [canonical(row) for row in value]
    return value


async def main():
    old_list = old_function("radd.modules.items.service.listing", "list_items")
    old_search = old_function("radd.modules.search.service", "search")
    results = []
    async with p.SessionLocal() as session:
        await p.prepare(session)
        pid = await session.scalar(text("SELECT project_id FROM work_items GROUP BY project_id ORDER BY count(*) DESC LIMIT 1"))
        admin = await session.scalar(text("SELECT id FROM users WHERE instance_role='admin' AND active LIMIT 1"))
        candidates = (await session.scalars(text("SELECT u.id FROM users u JOIN work_items w ON w.assignee_id=u.id WHERE u.instance_role='member' AND u.active AND u.source NOT IN ('principal','service','email') GROUP BY u.id ORDER BY count(*) DESC LIMIT 8"))).all()
        for uid in candidates:
            actor = await session.get(p.User, uid)
            if pid in await p.authz.readable_projects(session, actor):
                member = uid
                break
        else:
            raise RuntimeError("No representative member")
    for role, uid in [("admin", admin), ("member", member)]:
        async with p.SessionLocal() as session:
            await p.prepare(session)
            actor = await session.get(p.User, uid)
            key = (await p.list_items(session, actor=actor, filters=p.ItemListFilters(project_id=pid), limit=1, offset=0))[0].key
        cases = [
            ("cross_project_list", old_list, p.list_items,
             {"filters": p.ItemListFilters(), "limit": 25, "offset": 0}),
            *[(label, old_search, p.search, {"q": q, "limit": 20}) for label, q in
              [("key", key), ("lowercase_key", key.lower()), ("numeric_prefix", key.rsplit("-", 1)[1]), ("common_word", "render")]],
        ]
        for label, old, new, args in cases:
            hashes = []
            values = []
            for fn in [old, new]:
                async with p.SessionLocal() as session:
                    await p.prepare(session)
                    actor = await session.get(p.User, uid)
                    value = (await fn(session, actor=actor, **args) if label == "cross_project_list"
                             else await fn(session, actor, **args))
                    encoded = json.dumps(canonical(value), sort_keys=True, default=str).encode()
                    values.append(canonical(value))
                    hashes.append(hashlib.sha256(encoded).hexdigest())
            row = {"role": role, "case": label, "equal": hashes[0] == hashes[1],
                   "before_sha256": hashes[0], "after_sha256": hashes[1]}
            if not row["equal"]:
                row["same_rows_unordered"] = sorted(json.dumps(v, sort_keys=True, default=str) for v in values[0]) == sorted(json.dumps(v, sort_keys=True, default=str) for v in values[1])
                row["same_item_set"] = {str(v["item_id"]) for v in values[0]} == {str(v["item_id"]) for v in values[1]}
                if label == "common_word":
                    ids = {v["item_id"] for value in values for v in value}
                    async with p.SessionLocal() as session:
                        await p.prepare(session)
                        rank = func.ts_rank_cd(SearchIndexRow.tsv, func.to_tsquery(SEARCH_TS_CONFIG, build_tsquery(args["q"])))
                        ranked = await session.execute(select(SearchIndexRow.item_id, rank, SearchIndexRow.updated_at).where(SearchIndexRow.item_id.in_(ids)))
                        order = {identifier: (float(score), str(updated)) for identifier, score, updated in ranked}
                    row["same_rank_and_updated_order"] = [order[v["item_id"]] for v in values[0]] == [order[v["item_id"]] for v in values[1]]
                    before = {v["item_id"]: v for v in values[0]}
                    after = {v["item_id"]: v for v in values[1]}
                    row["shared_hits_identical"] = all(before[key] == after[key] for key in before.keys() & after.keys())
            row["compatible"] = row["equal"] or (row.get("same_rank_and_updated_order", False) and row.get("shared_hits_identical", False))
            results.append(row)
            print(json.dumps(row), flush=True)
    Path(__file__).with_name("read-result-parity.json").write_text(json.dumps(results, indent=2))
    await p.engine.dispose()
    assert all(row["compatible"] for row in results), "Read response parity failed"


asyncio.run(main())
