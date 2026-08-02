"""Perf-seed depth pass: worklogs + rich event history for chosen projects.

Complements perfseed.py (which seeds breadth: 503k items / 1.8M comments) by
giving a subset of projects the per-item DEPTH a long-lived Jira project has:

  - time logging enabled (`project_timelogging`) + 1-10 worklogs per item with
    realistic durations/dates/authors (item-attached, so project_id stays NULL,
    matching `timelogging.create_worklog`), and matching silent
    `worklog.created` events so the History feed and timesheet agree.
  - silent `comment.created` events for the items' existing comments (the
    breadth pass skipped them), so comments appear in the History feed.
  - a coherent `item.updated` field-change walk per item (~20-30 total feed
    entries incl. related events): state transitions plus assignee/priority/
    title/description/custom-field edits, each carrying the `changes` diff
    shape from `items/changes.py` that the History tab renders verbatim.

Coherence rules (reports fold item.created/item.updated in id order):
  - the breadth pass's synthetic `item.updated` rows for these projects are
    DELETED and replaced by the walk, so per-item event id order == time order;
  - the walk starts from the project default state (what the existing
    item.created payload claims) and ENDS at the item's actual current state,
    so reports, boards and the item page agree;
  - all rows are silent; consumer offsets are advanced past the batch.

Usage (from server/): uv run python scripts/perfseed_depth.py \
    [--projects BNX,DLT] [--db URL] [--yes]
Stop the app server first (the search indexer would otherwise chew the batch).
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
import uuid
from datetime import date, datetime, timedelta

import numpy as np
import psycopg

SEED = 20260801
NOW = datetime(2026, 7, 31, 12, 0, 0)

WORDS = ("render farm node frame cache publish asset shot version pipeline "
         "plugin export scene texture shader rig simulation volume camera "
         "plate comp roto grade colorspace proxy tracker geometry uv seam "
         "lookdev lighting denoise sample memory disk queue farm task batch "
         "config schema validation traceback crash freeze regression hotfix "
         "patch release branch merge build package review dailies annotation "
         "metadata checksum archive wrangler artist notes feedback approval "
         "ingest conform cut handles missing broken stale cleanup migrate "
         "optimize profile benchmark log setting session database index "
         "query lock replica webhook event trigger rule widget report").split()

WORKLOG_SECONDS = [900, 1800, 2700, 3600, 5400, 7200, 10800, 14400,
                   21600, 28800]
WORKLOG_SECONDS_W = [8, 12, 6, 18, 8, 16, 10, 12, 6, 4]

PRIORITIES = ["low", "normal", "high", "blocker"]

# op-type weights for the field-change walk
OPS = ["state", "assignee", "priority", "description", "title",
       "custom", "misc"]
OPS_W = [0.22, 0.20, 0.12, 0.10, 0.05, 0.18, 0.13]


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def short(rng: random.Random, lo: int = 3, hi: int = 8) -> str:
    s = " ".join(rng.choices(WORDS, k=rng.randint(lo, hi)))
    return s[0].upper() + s[1:]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default="postgresql://radd:radd@localhost:5455/radd")
    ap.add_argument("--projects", default="BNX,DLT",
                    help="comma-separated project keys")
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()
    keys = [k.strip().upper() for k in args.projects.split(",") if k.strip()]

    rng = random.Random(SEED)
    nprng = np.random.default_rng(SEED)
    t0 = time.time()

    conn = psycopg.connect(args.db, autocommit=False)
    cur = conn.cursor()
    cur.execute("SET synchronous_commit = off")
    cur.execute("SET work_mem = '256MB'")

    # ------------------------------------------------------------ lookups ---
    cur.execute("SELECT id, key FROM projects WHERE key = ANY(%s)", (keys,))
    projects = cur.fetchall()
    if len(projects) != len(keys):
        sys.exit(f"projects not found: wanted {keys}, got "
                 f"{[k for _, k in projects]}")
    pids = [p[0] for p in projects]
    pkey = dict(projects)

    cur.execute("SELECT count(*) FROM work_items WHERE project_id = ANY(%s)",
                (pids,))
    n_items = cur.fetchone()[0]
    cur.execute(
        "SELECT count(*) FROM worklogs w JOIN work_items wi ON wi.id = w.item_id "
        "WHERE wi.project_id = ANY(%s)", (pids,))
    if cur.fetchone()[0]:
        sys.exit("These projects already have worklogs — depth pass looks "
                 "applied. Pick other projects.")

    cur.execute("SELECT id, name, active FROM users ORDER BY created_at")
    users = cur.fetchall()
    uname = {u[0]: u[1] for u in users}
    active_ids = [u[0] for u in users if u[2]]
    uw = 1.0 / np.arange(1, len(active_ids) + 1) ** 0.8
    nprng.shuffle(uw)
    uw_cum = list(np.cumsum(uw))

    def pick_user() -> uuid.UUID:
        return rng.choices(active_ids, cum_weights=uw_cum)[0]

    cur.execute("SELECT id FROM work_categories WHERE NOT archived "
                "ORDER BY position")
    category_ids = [r[0] for r in cur.fetchall()]
    cur.execute("SELECT key, name FROM field_definitions")
    field_names = dict(cur.fetchall())
    cur.execute(
        "SELECT project_id, id, name, category, is_default FROM states "
        "WHERE project_id = ANY(%s) ORDER BY position", (pids,))
    states: dict[uuid.UUID, dict] = {p: {"all": [], "default": None} for p in pids}
    sname: dict[uuid.UUID, tuple[str, str]] = {}
    for spid, sid, name, cat, is_default in cur.fetchall():
        states[spid]["all"].append(sid)
        sname[sid] = (name, cat)
        if is_default:
            states[spid]["default"] = sid
    cur.execute("SELECT id, name, color, icon FROM issue_types "
                "WHERE project_id = ANY(%s)", (pids,))
    tinfo = {r[0]: (r[1], r[2], r[3]) for r in cur.fetchall()}
    cur.execute(
        "SELECT item_id, count(*) FROM comments c JOIN work_items wi "
        "ON wi.id = c.item_id WHERE wi.project_id = ANY(%s) GROUP BY item_id",
        (pids,))
    comment_counts = dict(cur.fetchall())

    log(f"depth pass on {'+'.join(keys)}: {n_items:,} items — "
        f"worklogs 1-10/item + ~20-30 history events/item")
    if not args.yes and input("Proceed? [y/N] ").strip().lower() != "y":
        sys.exit("aborted")

    # ------------------------------------------------- timelogging on -------
    cur.executemany(
        "INSERT INTO project_timelogging (project_id, enabled) VALUES (%s, true) "
        "ON CONFLICT (project_id) DO UPDATE SET enabled = true, "
        "updated_at = now()", [(p,) for p in pids])

    # ------------------------------------------------------- worklogs -------
    t_w = time.time()
    cur.execute(
        "SELECT id, project_id, assignee_id, created_at, updated_at "
        "FROM work_items WHERE project_id = ANY(%s)", (pids,))
    item_times = cur.fetchall()
    wl_count: dict[uuid.UUID, int] = {}
    n_wl = 0
    with cur.copy(
        "COPY worklogs (id, item_id, author_id, category_id, worked_on, "
        "time_spent_seconds, note, created_at, updated_at) FROM STDIN"
    ) as copy:
        for iid, _pid, assignee, cts, uts, in item_times:
            n = rng.randint(1, 10)
            wl_count[iid] = n
            span = max((uts - cts).total_seconds(), 86_400)
            for _ in range(n):
                worked = cts + timedelta(seconds=rng.random() * span)
                author = (assignee if assignee and rng.random() < 0.45
                          else pick_user())
                logged = worked.replace(hour=rng.randint(16, 19),
                                        minute=rng.randint(0, 59))
                copy.write_row((
                    uuid.uuid4(), iid, author,
                    rng.choice(category_ids)
                    if category_ids and rng.random() < 0.75 else None,
                    worked.date(),
                    rng.choices(WORKLOG_SECONDS, weights=WORKLOG_SECONDS_W)[0],
                    short(rng) if rng.random() < 0.45 else "",
                    logged, logged))
                n_wl += 1
    log(f"worklogs: {n_wl:,} in {time.time() - t_w:.0f}s")

    # worklog.created events straight from the rows just written.
    cur.execute(
        """INSERT INTO events (event_type, entity_type, entity_id, payload,
                               created_at, actor_id, silent)
        SELECT 'worklog.created', 'worklog', w.id::text,
               jsonb_build_object(
                   'item_id', w.item_id::text, 'project_id', NULL,
                   'category_id', w.category_id::text,
                   'author_id', w.author_id::text,
                   'worked_on', to_char(w.worked_on, 'YYYY-MM-DD'),
                   'time_spent_seconds', w.time_spent_seconds),
               w.created_at, w.author_id, true
        FROM worklogs w JOIN work_items wi ON wi.id = w.item_id
        WHERE wi.project_id = ANY(%s)""", (pids,))
    log(f"worklog.created events: {cur.rowcount:,}")

    # comment.created events for the breadth pass's comments.
    cur.execute(
        """INSERT INTO events (event_type, entity_type, entity_id, payload,
                               created_at, actor_id, silent)
        SELECT 'comment.created', 'comment', c.id::text,
               jsonb_build_object(
                   'item_id', c.item_id::text, 'author_id', c.author_id::text,
                   'visibility', c.visibility, 'excerpt', left(c.body, 200),
                   'visible_to_teams', '[]'::jsonb),
               c.created_at, c.author_id, true
        FROM comments c JOIN work_items wi ON wi.id = c.item_id
        WHERE wi.project_id = ANY(%s)""", (pids,))
    log(f"comment.created events: {cur.rowcount:,}")

    # --------------------------------------- item.updated field-change walk --
    # Replace the breadth pass's mid/final updated events so per-item id order
    # stays chronological once the walk lands.
    t_e = time.time()
    cur.execute(
        """DELETE FROM events e USING work_items wi
        WHERE wi.project_id = ANY(%s) AND e.entity_type = 'item'
          AND e.event_type = 'item.updated' AND e.silent
          AND e.entity_id = wi.id::text""", (pids,))
    log(f"removed {cur.rowcount:,} breadth-pass item.updated events")

    n_ev = 0
    for pid in pids:
        cur.execute(
            "SELECT id, number, kind, title, description, priority, state_id, "
            "assignee_id, reporter_id, type_id, parent_id, custom_fields, "
            "flagged, estimate_points, created_at, updated_at "
            "FROM work_items WHERE project_id = %s", (pid,))
        rows = cur.fetchall()
        proj_states = states[pid]["all"]
        default_state = states[pid]["default"]
        key_prefix = pkey[pid]

        with cur.copy(
            "COPY events (event_type, entity_type, entity_id, payload, "
            "created_at, actor_id, silent) FROM STDIN"
        ) as copy:
            for (iid, number, kind, title, desc, priority, state_id,
                 assignee_id, reporter_id, type_id, parent_id, cf, flagged,
                 points, cts, uts) in rows:
                n_related = 1 + wl_count.get(iid, 0) + comment_counts.get(iid, 0)
                n_upd = min(max(rng.randint(20, 30) - n_related, 6), 24)

                # Backward walk: invent op chains that END at current values.
                ops = rng.choices(OPS, weights=OPS_W, k=n_upd)
                if state_id != default_state and "state" not in ops:
                    ops[rng.randrange(n_upd)] = "state"
                # state chain: default -> ...random... -> current
                n_state = sum(1 for o in ops if o == "state")
                chain = [default_state] + [rng.choice(proj_states)
                                           for _ in range(max(n_state - 1, 0))]
                if n_state:
                    chain.append(state_id)
                # assignee chain: current at both ends (matches item.created)
                n_asg = sum(1 for o in ops if o == "assignee")
                asg_chain = [assignee_id] + [
                    (pick_user() if rng.random() < 0.85 else None)
                    for _ in range(max(n_asg - 1, 0))]
                if n_asg:
                    asg_chain.append(assignee_id)
                pri_pool = [p for p in PRIORITIES if p != priority]

                span = max((uts - cts).total_seconds() - 3_600, 3_600)
                offsets = sorted(rng.random() for _ in range(n_upd))
                cur_state, cur_asg, cur_pri = chain[0], asg_chain[0], priority
                cur_title, si, ai = title, 0, 0
                for k, op in enumerate(ops):
                    changes: list[dict] = []
                    if op == "state":
                        frm, cur_state = chain[si], chain[si + 1]
                        si += 1
                        changes.append({"field": "state",
                                        "from": sname[frm][0],
                                        "to": sname[cur_state][0]})
                    elif op == "assignee":
                        frm, cur_asg = asg_chain[ai], asg_chain[ai + 1]
                        ai += 1
                        changes.append({
                            "field": "assignee",
                            "from": uname.get(frm) if frm else None,
                            "to": uname.get(cur_asg) if cur_asg else None})
                    elif op == "priority":
                        frm = rng.choice(pri_pool)
                        changes.append({"field": "priority", "from": frm,
                                        "to": cur_pri})
                    elif op == "description":
                        changes.append({"field": "description"})
                    elif op == "title":
                        changes.append({"field": "title",
                                        "from": short(rng, 4, 9),
                                        "to": cur_title})
                    elif op == "custom" and cf:
                        fkey = rng.choice(list(cf))
                        changes.append({
                            "field": "custom_field", "key": fkey,
                            "name": field_names.get(fkey, fkey),
                            "from": None, "to": cf[fkey]})
                    else:
                        changes.append({
                            "field": rng.choice(["target_date", "points",
                                                 "flagged"]),
                            "from": None,
                            "to": rng.choice([True, 3,
                                              (cts + timedelta(days=30))
                                              .date().isoformat()])})

                    at = cts + timedelta(seconds=3_600 + offsets[k] * span)
                    stn, stc = sname[cur_state]
                    tn = tinfo.get(type_id)
                    payload = {
                        "id": str(iid), "project_id": str(pid),
                        "key": f"{key_prefix}-{number}", "number": number,
                        "kind": kind, "title": cur_title, "description": desc,
                        "priority": cur_pri,
                        "state": {"id": str(cur_state), "name": stn,
                                  "category": stc},
                        "type": ({"id": str(type_id), "name": tn[0],
                                  "color": tn[1], "icon": tn[2]}
                                 if tn else None),
                        "assignee": ({"id": str(cur_asg),
                                      "name": uname.get(cur_asg, "")}
                                     if cur_asg else None),
                        "reporter": ({"id": str(reporter_id),
                                      "name": uname.get(reporter_id, "")}
                                     if reporter_id else None),
                        "team": None, "cycle": None, "release": None,
                        "parent_id": str(parent_id) if parent_id else None,
                        "labels": [], "custom_fields": cf, "flagged": flagged,
                        "created_at": cts.isoformat(),
                        "updated_at": at.isoformat(),
                        "changes": changes,
                    }
                    actor = (cur_asg if op == "assignee" and cur_asg
                             and rng.random() < 0.5 else pick_user())
                    copy.write_row(("item.updated", "item", str(iid),
                                    json.dumps(payload), at, actor, True))
                    n_ev += 1
        log(f"  {key_prefix}: item.updated walk done ({n_ev:,} total)")
    log(f"item.updated events: {n_ev:,} in {time.time() - t_e:.0f}s")

    cur.execute("UPDATE consumer_offsets SET last_event_id = "
                "(SELECT max(id) FROM events), updated_at = now()")
    conn.commit()
    log("committed")

    conn.autocommit = True
    for t in ["events", "worklogs", "project_timelogging"]:
        cur.execute(f"VACUUM ANALYZE {t}")
    cur.execute("SELECT pg_size_pretty(pg_database_size(current_database()))")
    log(f"done in {(time.time() - t0) / 60:.1f} min — DB {cur.fetchone()[0]}")
    conn.close()


if __name__ == "__main__":
    main()
