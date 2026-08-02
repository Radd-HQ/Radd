"""Performance seed: recreate a production-Jira-scale dataset in Radd.

Targets (mirrors the reference Jira Server instance we benchmark against):

    projects          82      issues        503,056     comments   1,796,620
    attachments   94,585      teams           2,293     components     2,016  (-> labels)
    custom fields    319      issue types        61     statuses         107  (name pools)
    screens          375      priorities          7     (-> Radd's 4-level enum)
    security levels    4      (no Radd equivalent; skipped)

Text sizes are calibrated from the real instance (via the cached jiraimport
snapshot): descriptions median 296 / avg 549 chars, comments median 176 /
avg 341 chars, attachment sizes median 226 KB / avg 374 KB. Comment volume
averages 3.57 per issue, matching the real 1.79M/503k ratio.

What it writes, and why (bulk INSERT/COPY, bypassing the service layer):

  - projects + states + issue_types + views + screens/screen_fields, mirroring
    what `create_project` seeds (states drawn from a 107-name status pool,
    types from a 61-name pool).
  - work_items via COPY: kinds epic/issue/subtask with valid parents, custom
    field values in the JSONB column, per-project sequential numbers.
  - comments / attachments / item_labels via COPY. Attachment rows point at the
    filesystem host with NO bytes on disk: listings work, downloads 404.
  - events: one silent `item.created` per item plus silent `item.updated` rows
    for state transitions, payload shaped like ItemRead. This is REQUIRED:
    reports, item history, and the audit log all enumerate items from the
    events table, not from work_items.
  - search_index: populated directly with the indexer's exact weighted-tsv
    recipe (A=key+title, B=description, C=public comments), then the GIN index
    is rebuilt and every consumer offset is advanced past the synthetic events
    so no worker replays them.
  - post: projects.next_number advanced past max(number), VACUUM ANALYZE.

Reuses the existing user accounts as reporters/assignees/authors. Idempotence:
none — this is a one-shot fixture load. Refuses to run on a DB that already
looks seeded (> 20 projects) without --force.

Usage (from server/): uv run python scripts/perfseed.py [--db URL] [--yes]
Stop the app server first: its pollers otherwise contend with the bulk load.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
import uuid
from datetime import datetime, timedelta

import numpy as np
import psycopg

# ---------------------------------------------------------------- targets ---

TARGET_PROJECTS = 82
TARGET_ITEMS = 503_056
TARGET_COMMENTS = 1_796_620
TARGET_ATTACHMENTS = 94_585
TARGET_TEAMS = 2_293  # total incl. existing
TARGET_COMPONENTS = 2_016  # -> labels
TARGET_FIELDS = 319  # total incl. existing
TARGET_TYPE_NAMES = 61
TARGET_STATUS_NAMES = 107
TARGET_SCREENS = 375

SEED = 20260731

# ------------------------------------------------------------- name pools ---

SHOWS = ["GRX", "CHRM", "BNX", "DLT", "ECH", "FXT", "GLF", "HTL", "IND", "JLT",
         "KLO", "LMA", "MKE", "NVB", "OSC", "PPA", "QBC", "RMO", "SRA", "TNG"]
DEPTS = ["PIPE", "RND", "COMP", "FX", "ANIM", "LGT", "RIG", "MOD", "TEX",
         "EDIT", "IO", "TOOLS", "FARM", "INFRA", "SUP", "PREV", "LAY", "CFX",
         "MATTE", "ROTO", "TRACK", "CROWD", "ENV", "CHAR", "ASSET", "SHOT",
         "DATA", "QC", "OPS", "SEC", "NET", "LIC", "WEB", "DOCS", "HR", "FAC",
         "PROD", "COORD", "DAIL", "REVW", "ING", "PUB", "CACH", "SIM", "GRM",
         "HAIR", "CLO", "SCAN", "PHOTO", "STAGE", "MOCAP", "AUDIO", "COLR",
         "DI", "VEND", "OUTS", "ARCH", "LEG", "TRAIN", "ONB", "OFF", "STK"]
CITIES = ["Lisbon", "Zagreb", "Prague", "Tallinn", "Oslo", "Valletta"]
DEPT_WORDS = ["Pipeline", "Compositing", "FX", "Animation", "Lighting",
              "Rigging", "Modeling", "Texturing", "Editorial", "Layout",
              "Production", "Rendering", "Assets", "Crowd", "Environment",
              "Matchmove", "Roto", "Paint", "Previs", "Techviz", "Data Ops",
              "Systems", "Support", "Tools", "Core", "Infrastructure",
              "Review", "Ingest", "Publishing", "Farm", "Groom", "Cloth",
              "Character", "Creature", "Matte Painting", "Color", "Audio"]
AREAS = ["pipeline", "comp", "fx", "anim", "layout", "lighting", "rigging",
         "modeling", "texture", "render", "farm", "io", "review", "editorial",
         "core", "tools", "maya", "nuke", "houdini", "gaffer", "katana",
         "shotgrid", "ftrack", "usd", "ocio", "deadline"]
PARTS = ["core", "ui", "api", "export", "import", "cache", "publish",
         "ingest", "submit", "queue", "db", "auth", "config", "plugins",
         "hooks", "shelf", "menu", "nodes", "ops", "utils", "docs", "tests",
         "ci", "build", "deploy", "sync"]

WORDS = ("render farm node crashes frame sequence playblast cache publish "
         "asset shot version pipeline plugin export import scene file path "
         "texture shader rig deform skin cluster constraint bake simulation "
         "cloth hair groom particle volume vdb alembic usd layer stage prim "
         "camera lens distortion plate comp merge roto paint key matte grade "
         "colorspace ocio aces srgb linear gamma exr dpx proxy resolution "
         "artifact flicker ghosting banding clipping crop reformat retime "
         "tracker solve point cloud geometry mesh topology normals uv seam "
         "overlap projection displacement bump roughness specular albedo "
         "lookdev turntable lighting hdri dome gobo shadow occlusion bounce "
         "denoise sample noise bucket tile hang timeout memory leak spike "
         "cpu gpu vram disk quota permission mount nfs latency throughput "
         "queue priority farm submit chunk task job batch wedge variant "
         "context toolkit config override template schema validation error "
         "traceback exception null crash freeze deadlock race condition "
         "regression workaround hotfix patch release deploy rollback branch "
         "merge conflict rebase tag build wheel package dependency upgrade "
         "python maya nuke houdini gaffer katana blender deadline tractor "
         "ffmpeg review dailies annotation burnin slate timecode metadata "
         "manifest checksum archive restore backup wrangler coordinator "
         "supervisor artist producer client vendor delivery deadline notes "
         "feedback approval kickoff turnover ingest conform edl otio cut "
         "handles offset framerate drop duplicate missing broken stale "
         "orphan cleanup migrate legacy deprecate refactor optimize profile "
         "benchmark instrument log verbose silent flag toggle setting env "
         "wrapper launcher bootstrap session login token certificate expiry "
         "database index query transaction lock vacuum replica failover "
         "webhook callback event trigger automation rule filter widget "
         "dashboard report chart export csv excel email notification inbox "
         "windows linux macos workstation license server dongle floating").split()

TITLE_PREFIXES = ["", "", "", "", "", "Fix", "Crash:", "[Support]", "RFE:",
                  "Investigate", "Cleanup:", "Error:", "Cannot", "Slow"]

STATUS_POOL: list[tuple[str, str]] = [
    # (name, category) — triage | backlog | todo | in_progress | done | canceled
    ("Triage", "triage"), ("Incoming", "triage"), ("New", "triage"),
    ("Needs Discussion", "triage"), ("Awaiting Triage", "triage"),
    ("Screening", "triage"),
    ("Backlog", "backlog"), ("Icebox", "backlog"), ("Deferred", "backlog"),
    ("Parked", "backlog"), ("On Hold", "backlog"), ("Suspended", "backlog"),
    ("Wishlist", "backlog"), ("Future", "backlog"),
    ("Todo", "todo"), ("Open", "todo"), ("Ready", "todo"),
    ("Ready for Dev", "todo"), ("Selected", "todo"), ("Approved", "todo"),
    ("Planned", "todo"), ("Scheduled", "todo"), ("Queued", "todo"),
    ("Reopened", "todo"), ("Ready for QA", "todo"), ("To Estimate", "todo"),
    ("In Progress", "in_progress"), ("In Development", "in_progress"),
    ("In Review", "in_progress"), ("Code Review", "in_progress"),
    ("QA", "in_progress"), ("Testing", "in_progress"),
    ("Verifying", "in_progress"), ("Blocked", "in_progress"),
    ("Waiting for Client", "in_progress"), ("Waiting for Info", "in_progress"),
    ("In Render", "in_progress"), ("On Farm", "in_progress"),
    ("Client Review", "in_progress"), ("Internal Review", "in_progress"),
    ("Addressing Notes", "in_progress"), ("Kickback", "in_progress"),
    ("Done", "done"), ("Closed", "done"), ("Resolved", "done"),
    ("Released", "done"), ("Shipped", "done"), ("Delivered", "done"),
    ("Verified", "done"), ("Complete", "done"), ("Final", "done"),
    ("Approved Final", "done"), ("Archived Done", "done"),
    ("Canceled", "canceled"), ("Won't Do", "canceled"),
    ("Rejected", "canceled"), ("Duplicate", "canceled"),
    ("Obsolete", "canceled"), ("Abandoned", "canceled"),
    ("Invalid", "canceled"), ("Omitted", "canceled"),
]

TYPE_POOL = ["Task", "Bug", "Story", "Epic", "Sub-task", "New Feature",
             "Improvement", "Support Request", "Incident", "Change Request",
             "Asset Request", "Shot Task", "Sequence Task", "RFE", "Question",
             "Documentation", "Maintenance", "Deployment", "Access Request",
             "Hardware Request", "License Request", "Render Issue",
             "Pipeline Bug", "Data Fix", "Ingest", "Delivery", "Turnover",
             "Review Note", "Client Note", "Tech Debt", "Spike", "Research",
             "Onboarding", "Offboarding", "Security", "Outage", "Alert",
             "Milestone", "Idea", "Test Case", "Automation", "Migration",
             "Upgrade", "Cleanup", "Audit", "Backup", "Restore", "Config",
             "Build Failure", "Farm Issue", "Storage Request", "QC Report",
             "Editorial Task", "Color Note", "Audio Note", "Version Up",
             "Publish Issue", "Cache Issue", "Scene Issue", "Plate Issue",
             "Workstation"]
TYPE_COLORS = ["#64748b", "#ef4444", "#22c55e", "#a855f7", "#3b82f6",
               "#f59e0b", "#06b6d4", "#ec4899", "#84cc16", "#f97316"]
TYPE_ICONS = ["square-check-big", "bug", "bookmark", "gem", "sparkles",
              "wrench", "flame", "life-buoy", "rocket", "file-text", None]

CONTENT_TYPES = [  # (ext, mime, weight)
    ("png", "image/png", 28), ("jpg", "image/jpeg", 16),
    ("exr", "image/x-exr", 6), ("pdf", "application/pdf", 10),
    ("mp4", "video/mp4", 8), ("mov", "video/quicktime", 6),
    ("zip", "application/zip", 6), ("txt", "text/plain", 5),
    ("log", "text/plain", 5), ("json", "application/json", 4),
    ("docx", "application/vnd.openxmlformats-officedocument"
             ".wordprocessingml.document", 3),
    ("xlsx", "application/vnd.openxmlformats-officedocument"
             ".spreadsheetml.sheet", 3),
]

PRIORITIES = ["low", "normal", "high", "blocker"]
PRIORITY_W = [0.13, 0.57, 0.22, 0.08]

FIELD_TYPES = ["text", "select", "multi_select", "number", "date", "user",
               "boolean", "url", "duration"]
FIELD_TYPE_W = [0.30, 0.22, 0.12, 0.12, 0.10, 0.06, 0.04, 0.02, 0.02]

NOW = datetime(2026, 7, 31, 12, 0, 0)


# ---------------------------------------------------------------- text gen ---

class TextGen:
    """Cheap corpus generator: a pregenerated sentence pool sampled into
    documents whose char sizes follow the calibrated lognormals."""

    def __init__(self, rng: random.Random, pool_size: int = 24_000):
        self.rng = rng
        self.pool: list[str] = []
        for _ in range(pool_size):
            n = rng.randint(4, 12)
            ws = rng.choices(WORDS, k=n)
            s = " ".join(ws)
            r = rng.random()
            if r < 0.04:
                s += f" v{rng.randint(1, 9)}.{rng.randint(0, 9)}.{rng.randint(0, 9)}"
            elif r < 0.07:
                s += f" in `/prod/{rng.choice(AREAS)}/{rng.choice(PARTS)}`"
            elif r < 0.09:
                s += f" on {rng.choice(SHOWS)}"
            self.pool.append(s[0].upper() + s[1:] + ".")

    def doc(self, budget: int, markdown: bool = False) -> str:
        if budget <= 0:
            return ""
        rng = self.rng
        parts: list[str] = []
        size = 0
        para = 0
        while size < budget:
            s = self.pool[rng.randrange(len(self.pool))]
            para += 1
            if markdown and para % 4 == 0 and rng.random() < 0.3:
                s = "\n\n" + rng.choice(["## ", "- ", "**Note:** ", "> "]) + s
            elif para % 3 == 0:
                s = "\n\n" + s
            parts.append(s)
            size += len(s) + 1
        text = " ".join(parts).replace("\n\n ", "\n\n")
        if markdown and rng.random() < 0.08:
            text += "\n\n```\nTraceback (most recent call last):\n  " + \
                self.pool[rng.randrange(len(self.pool))] + "\n```"
        return text[: budget + 200]

    def title(self) -> str:
        rng = self.rng
        n = rng.randint(3, 9)
        t = " ".join(rng.choices(WORDS, k=n))
        pfx = rng.choice(TITLE_PREFIXES)
        if pfx:
            t = f"{pfx} {t}"
        else:
            t = t[0].upper() + t[1:]
        if rng.random() < 0.08:
            t = f"[{rng.choice(SHOWS)}] {t}"
        return t[:300]


def lognormal_sizes(nprng: np.random.Generator, n: int, median: float,
                    mean: float, cap: int) -> np.ndarray:
    mu = math.log(median)
    sigma = math.sqrt(2 * math.log(mean / median))
    return np.minimum(nprng.lognormal(mu, sigma, n), cap).astype(np.int64)


def exact_counts(nprng: np.random.Generator, n_items: int, total: int,
                 nb_n: float) -> np.ndarray:
    """Negative-binomial per-item counts adjusted to sum EXACTLY to total."""
    mean = total / n_items
    p = nb_n / (nb_n + mean)
    counts = nprng.negative_binomial(nb_n, p, n_items).astype(np.int64)
    counts = np.minimum(counts, 400)
    diff = int(total - counts.sum())
    while diff != 0:
        idx = nprng.integers(0, n_items, min(abs(diff), n_items))
        if diff > 0:
            np.add.at(counts, idx, 1)
        else:
            nonzero = counts[idx] > 0
            np.subtract.at(counts, idx[nonzero], 1)
            np.maximum(counts, 0, out=counts)
        diff = int(total - counts.sum())
    return counts


# ------------------------------------------------------------------- main ---

def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default="postgresql://radd:radd@localhost:5455/radd")
    ap.add_argument("--yes", action="store_true", help="skip confirmation")
    ap.add_argument("--force", action="store_true",
                    help="run even if the DB already looks seeded")
    ap.add_argument("--scale", type=float, default=1.0,
                    help="scale the item/comment/attachment volumes "
                         "(smoke-test with e.g. 0.01)")
    args = ap.parse_args()

    global TARGET_ITEMS, TARGET_COMMENTS, TARGET_ATTACHMENTS
    if args.scale != 1.0:
        TARGET_ITEMS = max(TARGET_PROJECTS * 3, int(TARGET_ITEMS * args.scale))
        TARGET_COMMENTS = int(TARGET_COMMENTS * args.scale)
        TARGET_ATTACHMENTS = int(TARGET_ATTACHMENTS * args.scale)

    rng = random.Random(SEED)
    nprng = np.random.default_rng(SEED)
    tg = TextGen(rng)
    t0 = time.time()

    conn = psycopg.connect(args.db, autocommit=False)
    cur = conn.cursor()
    cur.execute("SET synchronous_commit = off")
    cur.execute("SET work_mem = '256MB'")
    cur.execute("SET maintenance_work_mem = '512MB'")

    # -------------------------------------------------- existing state ------
    cur.execute("SELECT count(*) FROM projects")
    n_projects = cur.fetchone()[0]
    if n_projects > 20 and not args.force:
        sys.exit(f"DB already has {n_projects} projects — looks seeded. "
                 "Use --force to run anyway.")

    cur.execute("SELECT id, name, active FROM users ORDER BY created_at")
    users = cur.fetchall()
    user_ids = [u[0] for u in users]
    active_ids = [u[0] for u in users if u[2]]
    if len(active_ids) < 10:
        sys.exit("Too few active users — seed users first.")
    # Zipf author weights: a few heavy contributors, a long tail.
    uw = 1.0 / np.arange(1, len(user_ids) + 1) ** 0.8
    nprng.shuffle(uw)
    uw /= uw.sum()
    aw = 1.0 / np.arange(1, len(active_ids) + 1) ** 0.8
    nprng.shuffle(aw)
    aw /= aw.sum()

    cur.execute("SELECT id FROM roles WHERE key = 'member' AND is_builtin")
    member_role_id = cur.fetchone()[0]
    cur.execute("SELECT id FROM storage_hosts WHERE host_type = 'filesystem' "
                "ORDER BY created_at LIMIT 1")
    row = cur.fetchone()
    if row is None:
        sys.exit("No filesystem storage host found.")
    fs_host_id = row[0]
    cur.execute("SELECT key FROM projects")
    existing_keys = {r[0] for r in cur.fetchall()}
    cur.execute("SELECT name FROM labels")
    existing_labels = {r[0] for r in cur.fetchall()}
    cur.execute("SELECT name FROM teams")
    existing_teams = {r[0] for r in cur.fetchall()}
    cur.execute("SELECT key FROM field_definitions")
    existing_fields = {r[0] for r in cur.fetchall()}
    cur.execute("SELECT count(*) FROM teams")
    teams_to_make = max(0, TARGET_TEAMS - cur.fetchone()[0])
    fields_to_make = max(0, TARGET_FIELDS - len(existing_fields))

    log(f"seeding into {args.db}: {TARGET_PROJECTS} projects, "
        f"{TARGET_ITEMS:,} items, {TARGET_COMMENTS:,} comments, "
        f"{TARGET_ATTACHMENTS:,} attachments, {teams_to_make} teams, "
        f"{fields_to_make} custom fields; reusing {len(user_ids)} users")
    if not args.yes:
        if input("Proceed? [y/N] ").strip().lower() != "y":
            sys.exit("aborted")

    # -------------------------------------------------- project scaffold ----
    # Keys: shows + depts + generated consonant-vowel codes, minus collisions.
    key_pool = [k for k in SHOWS + DEPTS if k not in existing_keys]
    while len(key_pool) < TARGET_PROJECTS:
        k = "".join(rng.choice("BCDFGHKLMNPRSTVZ" if i % 2 == 0 else "AEIOU")
                    for i in range(rng.randint(3, 5)))
        if k not in existing_keys and k not in key_pool:
            key_pool.append(k)
    proj_keys = key_pool[:TARGET_PROJECTS]

    # Zipf sizes summing exactly to TARGET_ITEMS (largest ~ a fifth).
    w = 1.0 / np.arange(1, TARGET_PROJECTS + 1) ** 1.0
    sizes = (w / w.sum() * TARGET_ITEMS).astype(np.int64)
    sizes[0] += TARGET_ITEMS - int(sizes.sum())

    projects = []  # (id, key, name, size, start_ts)
    for i, key in enumerate(proj_keys):
        name = (f"{rng.choice(DEPT_WORDS)} {rng.choice(CITIES)}" if i % 3
                else f"Show {key.title()}")
        # Big projects are old (up to ~8.5y), small ones may be recent.
        age_years = 1.0 + 7.5 * (sizes[i] / sizes[0]) ** 0.35 * rng.uniform(0.6, 1.0)
        start = NOW - timedelta(days=age_years * 365)
        projects.append((uuid.uuid4(), key, name, int(sizes[i]), start.timestamp()))

    cur.executemany(
        "INSERT INTO projects (id, key, name, next_number, created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        [(p[0], p[1], p[2], p[3] + 1, datetime.fromtimestamp(p[4]), NOW)
         for p in projects])

    # States: 6-9 per project drawn from the 107-name pool.
    status_pool = list(STATUS_POOL)
    seen_status = {s for s, _ in status_pool}
    di = 0
    while len(status_pool) < TARGET_STATUS_NAMES:
        base = ["Review", "QC", "Check", "Pass", "Prep"][di % 5]
        name = f"{DEPT_WORDS[di % len(DEPT_WORDS)]} {base}"
        di += 1
        if name in seen_status:
            continue
        seen_status.add(name)
        status_pool.append((name, rng.choice(["in_progress", "todo", "done"])))
    by_cat: dict[str, list[str]] = {}
    for name, cat in status_pool:
        by_cat.setdefault(cat, []).append(name)

    state_rows, proj_states = [], {}  # pid -> {"default","mid","by_cat"}
    for pid, key, _, _, pstart in projects:
        picks: list[tuple[str, str]] = []
        picks.append((rng.choice(by_cat["triage"] + by_cat["backlog"]
                                 + by_cat["todo"]), None))  # default, cat fixed below
        dname = picks[0][0]
        dcat = next(c for n, c in status_pool if n == dname)
        picks[0] = (dname, dcat)
        for cat, lo, hi in [("todo", 1, 2), ("in_progress", 1, 3),
                            ("done", 1, 2), ("canceled", 0, 1)]:
            for name in rng.sample(by_cat[cat], rng.randint(lo, hi)):
                if all(name != n for n, _ in picks):
                    picks.append((name, cat))
        info = {"by_cat": {}, "default": None, "mid": None}
        for pos, (name, cat) in enumerate(picks, start=1):
            sid = uuid.uuid4()
            state_rows.append((sid, pid, name, cat, pos, pos == 1,
                              datetime.fromtimestamp(pstart), NOW))
            info["by_cat"].setdefault(cat, []).append(sid)
            if pos == 1:
                info["default"] = sid
        info["mid"] = info["by_cat"]["in_progress"][0]
        proj_states[pid] = info
    cur.executemany(
        "INSERT INTO states (id, project_id, name, category, position, "
        "is_default, created_at, updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        state_rows)
    log(f"projects + {len(state_rows)} states")

    # Issue types: 5-12 per project from the 61-name pool.
    type_rows, proj_types = [], {}
    for pid, *_ , pstart in [(p[0], p[1], p[2], p[3], p[4]) for p in projects]:
        names = ["Task", "Bug"] + rng.sample(
            [t for t in TYPE_POOL if t not in ("Task", "Bug")],
            rng.randint(3, 10))
        tids = []
        for pos, name in enumerate(names, start=1):
            tid = uuid.uuid4()
            type_rows.append((tid, pid, name, rng.choice(TYPE_COLORS),
                              rng.choice(TYPE_ICONS), pos, pos == 1,
                              datetime.fromtimestamp(pstart), NOW))
            tids.append(tid)
        proj_types[pid] = tids
    cur.executemany(
        "INSERT INTO issue_types (id, project_id, name, color, icon, position, "
        "is_default, created_at, updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        type_rows)

    # Default views, mirroring views/defaults.py.
    view_rows = []
    for pid, *_ in projects:
        for name, vtype, group_by in [("Board", "board", "state"),
                                      ("List", "list", None),
                                      ("Planning", "planning", None),
                                      ("Roadmap", "roadmap", None)]:
            view_rows.append((uuid.uuid4(), pid, name, vtype, "", group_by,
                              json.dumps([]), "viewer", 0, NOW, NOW))
    cur.executemany(
        "INSERT INTO views (id, project_id, name, view_type, query, group_by, "
        "quick_filters, global_access, position, created_at, updated_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", view_rows)
    log(f"{len(type_rows)} issue types + {len(view_rows)} views")

    # Custom fields: fill to 319 total; ~25 global, the rest project-scoped.
    field_rows, scope_rows = [], []
    fkeys: list[tuple[str, str, list[str] | None]] = []  # (key, type, options)
    fi = 0
    while len(field_rows) < fields_to_make:
        base = f"{rng.choice(WORDS)}_{rng.choice(WORDS)}"
        key = base if fi % 7 else f"{base}_{fi}"
        fi += 1
        if key in existing_fields or any(k == key for k, _, _ in fkeys):
            continue
        ftype = rng.choices(FIELD_TYPES, weights=FIELD_TYPE_W)[0]
        options = None
        if ftype in ("select", "multi_select"):
            options = rng.sample(
                CITIES + SHOWS + DEPT_WORDS + WORDS[:60], rng.randint(3, 15))
        fid = uuid.uuid4()
        name = key.replace("_", " ").title()[:180]
        field_rows.append((fid, key, name, ftype, False,
                           json.dumps(options) if options else None,
                           False, True, "user",
                           "chips" if ftype == "multi_select" and rng.random() < 0.4
                           else None, NOW, NOW))
        fkeys.append((key, ftype, options))
        if len(field_rows) > 25:  # the first 25 stay global
            for pid, *_ in rng.sample(projects, rng.randint(1, 8)):
                scope_rows.append((fid, pid))
    cur.executemany(
        "INSERT INTO field_definitions (id, key, name, type, required, options, "
        "indexed, ai_visible, source, display, created_at, updated_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", field_rows)
    cur.executemany(
        "INSERT INTO field_definition_projects (field_id, project_id) "
        "VALUES (%s,%s)", scope_rows)

    # Per-project applicable fields (globals + scoped) with a fill probability.
    global_fields = fkeys[:25]
    scoped_by_project: dict[uuid.UUID, list[tuple[str, str, list | None]]] = {}
    fid_to_spec = {field_rows[i][0]: fkeys[i] for i in range(len(fkeys))}
    for fid, pid in scope_rows:
        scoped_by_project.setdefault(pid, []).append(fid_to_spec[fid])
    proj_fields = {}
    for pid, *_ in projects:
        appl = global_fields + scoped_by_project.get(pid, [])
        probs = [rng.uniform(0.05, 0.75) for _ in appl]
        proj_fields[pid] = (appl, probs)
    log(f"{len(field_rows)} custom fields ({len(scope_rows)} scope rows)")

    # Components -> labels, sliced per project.
    label_rows, proj_labels = [], {}
    per_proj = math.ceil(TARGET_COMPONENTS / TARGET_PROJECTS)
    made = 0
    for pid, key, *_ in projects:
        ids = []
        for _ in range(min(per_proj, TARGET_COMPONENTS - made)):
            name = f"{key.lower()}-{rng.choice(AREAS)}-{rng.choice(PARTS)}"
            if name in existing_labels:
                name = f"{name}-{made}"
            existing_labels.add(name)
            lid = uuid.uuid4()
            label_rows.append((lid, name[:100],
                               rng.choice(TYPE_COLORS) if rng.random() < 0.5
                               else None, NOW, NOW))
            ids.append(lid)
            made += 1
        proj_labels[pid] = ids
    cur.executemany(
        "INSERT INTO labels (id, name, color, created_at, updated_at) "
        "VALUES (%s,%s,%s,%s,%s)", label_rows)

    # Teams.
    team_rows, member_rows, manager_rows = [], [], []
    ti = 0
    while len(team_rows) < teams_to_make:
        name = rng.choice([
            f"{rng.choice(SHOWS)} {rng.choice(DEPT_WORDS)}",
            f"{rng.choice(CITIES)} {rng.choice(DEPT_WORDS)}",
            f"{rng.choice(DEPT_WORDS)} {rng.choice(['Crew', 'Squad', 'Unit', 'Group', 'Team'])}",
        ])
        if name in existing_teams:
            name = f"{name} {ti}"
        ti += 1
        existing_teams.add(name)
        tid = uuid.uuid4()
        owner = rng.choice(active_ids) if rng.random() < 0.3 else None
        team_rows.append((tid, name[:200], "local", owner, NOW, NOW))
        n_members = min(int(nprng.negative_binomial(1.2, 0.25)), 40)
        for u in rng.sample(active_ids, min(n_members, len(active_ids))):
            member_rows.append((tid, u, "manual"))
        if owner and rng.random() < 0.5:
            manager_rows.append((tid, owner))
    cur.executemany(
        "INSERT INTO teams (id, name, source, owner_id, created_at, updated_at) "
        "VALUES (%s,%s,%s,%s,%s,%s)", team_rows)
    cur.executemany(
        "INSERT INTO team_members (team_id, user_id, source) VALUES (%s,%s,%s)",
        member_rows)
    cur.executemany(
        "INSERT INTO team_managers (team_id, user_id) VALUES (%s,%s)",
        manager_rows)
    team_ids = [t[0] for t in team_rows]
    log(f"{len(team_rows)} teams ({len(member_rows)} memberships)")

    # Project members (RBAC realism).
    pm_rows = []
    for pid, *_ in projects:
        for u in rng.sample(active_ids, min(rng.randint(5, 40), len(active_ids))):
            pm_rows.append((pid, u, member_role_id))
    cur.executemany(
        "INSERT INTO project_members (project_id, user_id, role_id) "
        "VALUES (%s,%s,%s)", pm_rows)

    # Screens: 375 total = 4 per project + 1 extra for the first 47.
    screen_rows, sfield_rows = [], []
    builtin_fields = ["assignee", "reporter", "team", "cycle", "release",
                      "start_date", "target_date", "labels", "points"]
    for i, (pid, *_ ) in enumerate(projects):
        n_screens = 4 + (1 if i < TARGET_SCREENS - 4 * TARGET_PROJECTS else 0)
        typed = rng.sample(proj_types[pid], min(n_screens - 1, len(proj_types[pid])))
        for tsel in [None] + typed:
            sid = uuid.uuid4()
            screen_rows.append((sid, pid, tsel, NOW, NOW))
            pos = 0
            for f in rng.sample(builtin_fields, rng.randint(4, len(builtin_fields))):
                pos += 1
                sfield_rows.append((uuid.uuid4(), sid, f,
                                    rng.choice(["primary", "primary",
                                                "secondary", "hidden"]), pos))
            appl, _ = proj_fields[pid]
            for fkey, _, _ in rng.sample(appl, min(rng.randint(1, 5), len(appl))):
                pos += 1
                sfield_rows.append((uuid.uuid4(), sid, f"cf:{fkey}"[:60],
                                    rng.choice(["secondary", "hidden"]), pos))
    cur.executemany(
        "INSERT INTO screens (id, project_id, issue_type_id, created_at, "
        "updated_at) VALUES (%s,%s,%s,%s,%s)", screen_rows)
    cur.executemany(
        "INSERT INTO screen_fields (id, screen_id, field, placement, position) "
        "VALUES (%s,%s,%s,%s,%s)", sfield_rows)
    log(f"{len(screen_rows)} screens ({len(sfield_rows)} screen fields)")

    # ------------------------------------------------------- work items -----
    ccounts = exact_counts(nprng, TARGET_ITEMS, TARGET_COMMENTS, 0.5)
    acounts = exact_counts(nprng, TARGET_ITEMS, TARGET_ATTACHMENTS, 0.25)
    desc_sizes = lognormal_sizes(nprng, TARGET_ITEMS, 296, 549, 20_000)
    desc_sizes[nprng.random(TARGET_ITEMS) < 0.12] = 0

    cat_names = ["done", "canceled", "in_progress", "todo", "backlog", "triage"]
    cat_w = np.array([0.78, 0.06, 0.05, 0.05, 0.04, 0.02])
    cat_w_recent = np.array([0.18, 0.02, 0.30, 0.30, 0.15, 0.05])

    item_meta = []  # (item_id, created_ts, updated_ts, ci) per project chunk list
    label_buf: list[tuple[uuid.UUID, uuid.UUID]] = []
    ci = 0  # global item cursor
    items_copied = 0
    t_items = time.time()

    with cur.copy(
        "COPY work_items (id, project_id, number, kind, type_id, parent_id, "
        "title, description, state_id, priority, assignee_id, reporter_id, "
        "team_id, flagged, rank, estimate_points, cycle_id, release_id, "
        "start_date, target_date, archived_at, custom_fields, created_at, "
        "updated_at) FROM STDIN"
    ) as copy:
        for pid, pkey, _, size, pstart in projects:
            info = proj_states[pid]
            tids = proj_types[pid]
            type_w = [4.0 if i < 2 else 1.0 for i in range(len(tids))]
            appl, probs = proj_fields[pid]
            plabels = proj_labels[pid]
            span = NOW.timestamp() - pstart - 86_400
            created = pstart + (nprng.random(size) ** 0.85) * span
            created.sort()
            dur = nprng.lognormal(math.log(12 * 86_400), 1.4, size)
            updated = np.minimum(created + dur, NOW.timestamp() - 60)
            fill = nprng.random((size, len(appl))) if appl else None
            epics: list[uuid.UUID] = []
            issues: list[uuid.UUID] = []
            metas = []

            for j in range(size):
                iid = uuid.uuid4()
                r = rng.random()
                if r < 0.015:
                    kind, parent = "epic", None
                    epics.append(iid)
                elif r < 0.115 and issues:
                    kind, parent = "subtask", rng.choice(issues[-500:])
                else:
                    kind = "issue"
                    parent = (rng.choice(epics) if epics and rng.random() < 0.4
                              else None)
                    issues.append(iid)

                recent = NOW.timestamp() - created[j] < 45 * 86_400
                cw = cat_w_recent if recent else cat_w
                cat = cat_names[int(nprng.choice(6, p=cw))]
                sids = info["by_cat"].get(cat) or info["by_cat"]["done"]
                state_id = rng.choice(sids)

                cf = {}
                if appl:
                    for k in np.nonzero(fill[j] < probs)[0][:12]:
                        fkey, ftype, opts = appl[k]
                        if ftype == "select":
                            cf[fkey] = rng.choice(opts)
                        elif ftype == "multi_select":
                            cf[fkey] = rng.sample(opts, min(rng.randint(1, 3),
                                                            len(opts)))
                        elif ftype == "number":
                            cf[fkey] = rng.randint(0, 10_000)
                        elif ftype == "date":
                            d = datetime.fromtimestamp(created[j])
                            cf[fkey] = (d + timedelta(days=rng.randint(0, 400))
                                        ).date().isoformat()
                        elif ftype == "user":
                            cf[fkey] = str(rng.choice(user_ids))
                        elif ftype == "boolean":
                            cf[fkey] = rng.random() < 0.5
                        elif ftype == "url":
                            cf[fkey] = (f"https://wiki.example.com/"
                                        f"{rng.choice(WORDS)}/{rng.choice(WORDS)}")
                        elif ftype == "duration":
                            cf[fkey] = rng.randint(5, 4_800)
                        else:
                            cf[fkey] = " ".join(rng.choices(WORDS,
                                                            k=rng.randint(1, 6)))

                cdt = datetime.fromtimestamp(created[j])
                udt = datetime.fromtimestamp(updated[j])
                start_d = target_d = None
                if rng.random() < 0.08:
                    start_d = cdt.date()
                    target_d = (cdt + timedelta(days=rng.randint(7, 180))).date()
                copy.write_row((
                    iid, pid, j + 1, kind,
                    rng.choices(tids, weights=type_w)[0], parent,
                    tg.title(), tg.doc(int(desc_sizes[ci]), markdown=True),
                    state_id, rng.choices(PRIORITIES, weights=PRIORITY_W)[0],
                    rng.choices(active_ids, weights=aw)[0]
                    if rng.random() < 0.65 else None,
                    rng.choices(user_ids, weights=uw)[0]
                    if rng.random() < 0.97 else None,
                    rng.choice(team_ids) if team_ids and rng.random() < 0.20
                    else None,
                    rng.random() < 0.01, rng.uniform(0, 1e7),
                    rng.choice([0.5, 1, 2, 3, 5, 8, 13])
                    if rng.random() < 0.15 else None,
                    None, None, start_d, target_d, None,
                    json.dumps(cf), cdt, udt))

                for lid in rng.sample(plabels, min(
                        int(nprng.poisson(0.9)), len(plabels))):
                    label_buf.append((iid, lid))
                metas.append((iid, created[j], updated[j], ci))
                ci += 1

            item_meta.append((pid, metas))
            items_copied += size
            if items_copied % 50_000 < size:
                log(f"  items: {items_copied:,}/{TARGET_ITEMS:,}")

    log(f"work_items copied in {time.time() - t_items:.0f}s "
        f"({items_copied:,} rows)")

    with cur.copy("COPY item_labels (item_id, label_id) FROM STDIN") as copy:
        for row in label_buf:
            copy.write_row(row)
    log(f"{len(label_buf):,} item_labels")

    # --------------------------------------------------------- comments -----
    t_c = time.time()
    csizes = lognormal_sizes(nprng, TARGET_COMMENTS, 176, 341, 18_000)
    written = 0
    with cur.copy(
        "COPY comments (id, item_id, author_id, body, visibility, created_at, "
        "updated_at) FROM STDIN"
    ) as copy:
        for pid, metas in item_meta:
            for iid, cts, uts, idx in metas:
                n = int(ccounts[idx])
                if n == 0:
                    continue
                ts = cts + (np.sort(nprng.random(n)) ** 0.7) * max(uts - cts, 3_600)
                authors = nprng.choice(len(user_ids), n, p=uw)
                for k in range(n):
                    dt = datetime.fromtimestamp(float(ts[k]))
                    copy.write_row((
                        uuid.uuid4(), iid, user_ids[int(authors[k])],
                        tg.doc(int(csizes[written])),
                        "internal" if rng.random() < 0.02 else "public",
                        dt, dt))
                    written += 1
                if written % 200_000 < n:
                    log(f"  comments: {written:,}/{TARGET_COMMENTS:,}")
    log(f"comments copied in {time.time() - t_c:.0f}s ({written:,} rows)")

    # ------------------------------------------------------- attachments ----
    t_a = time.time()
    exts, mimes, ws = zip(*CONTENT_TYPES)
    wsum = sum(ws)
    asizes = lognormal_sizes(nprng, TARGET_ATTACHMENTS, 226_000, 374_000,
                             500_000_000)
    written_a = 0
    with cur.copy(
        "COPY attachments (id, entity_type, entity_id, filename, content_type, "
        "size_bytes, storage_name, storage_host_id, state, created_by, "
        "created_at) FROM STDIN"
    ) as copy:
        for pid, metas in item_meta:
            for iid, cts, uts, idx in metas:
                for _ in range(int(acounts[idx])):
                    k = rng.choices(range(len(exts)), weights=ws)[0]
                    fname = (f"{rng.choice(WORDS)}_{rng.choice(WORDS)}"
                             f"_{rng.randint(1, 999):03d}.{exts[k]}")
                    copy.write_row((
                        uuid.uuid4(), "item", iid, fname, mimes[k],
                        int(asizes[written_a]), uuid.uuid4().hex, fs_host_id,
                        "stored", rng.choice(user_ids),
                        datetime.fromtimestamp(
                            rng.uniform(cts, max(uts, cts + 60)))))
                    written_a += 1
    log(f"attachments copied in {time.time() - t_a:.0f}s ({written_a:,} rows)")

    # ------------------------------------------------------------ events ----
    # Reports/history/audit enumerate items from `events`. Emit silent rows:
    #   1. item.created  (state = the project default) for every item
    #   2. item.updated -> an in_progress state, for items that ended done/canceled
    #   3. item.updated -> the final state, for every item not in the default state
    t_e = time.time()
    pids = [p[0] for p in projects]
    cur.execute("CREATE TEMP TABLE seed_mid_state (project_id uuid PRIMARY KEY, "
                "state_id uuid NOT NULL) ON COMMIT DROP")
    cur.executemany("INSERT INTO seed_mid_state VALUES (%s,%s)",
                    [(pid, proj_states[pid]["mid"]) for pid in pids])

    payload = """jsonb_build_object(
        'id', wi.id::text, 'project_id', wi.project_id::text,
        'key', p.key || '-' || wi.number, 'number', wi.number,
        'kind', wi.kind, 'title', wi.title, 'description', wi.description,
        'priority', wi.priority,
        'state', jsonb_build_object('id', st.id::text, 'name', st.name,
                                    'category', st.category),
        'type', CASE WHEN it.id IS NULL THEN NULL ELSE jsonb_build_object(
            'id', it.id::text, 'name', it.name, 'color', it.color,
            'icon', it.icon) END,
        'assignee', CASE WHEN au.id IS NULL THEN NULL ELSE jsonb_build_object(
            'id', au.id::text, 'name', au.name) END,
        'reporter', CASE WHEN ru.id IS NULL THEN NULL ELSE jsonb_build_object(
            'id', ru.id::text, 'name', ru.name) END,
        'team', NULL, 'cycle', NULL, 'release', NULL,
        'parent_id', wi.parent_id::text, 'labels', '[]'::jsonb,
        'custom_fields', wi.custom_fields, 'flagged', wi.flagged,
        'created_at', to_jsonb(wi.created_at), 'updated_at', to_jsonb(%s))"""
    base_joins = """FROM work_items wi
        JOIN projects p ON p.id = wi.project_id
        LEFT JOIN issue_types it ON it.id = wi.type_id
        LEFT JOIN users au ON au.id = wi.assignee_id
        LEFT JOIN users ru ON ru.id = wi.reporter_id"""

    cur.execute(
        f"""INSERT INTO events (event_type, entity_type, entity_id, payload,
                                created_at, actor_id, silent)
        SELECT 'item.created', 'item', wi.id::text, {payload % "wi.created_at"},
               wi.created_at, wi.reporter_id, true
        {base_joins}
        JOIN states st ON st.project_id = wi.project_id AND st.is_default
        WHERE wi.project_id = ANY(%s)""", (pids,))
    n1 = cur.rowcount
    cur.execute(
        f"""INSERT INTO events (event_type, entity_type, entity_id, payload,
                                created_at, actor_id, silent)
        SELECT 'item.updated', 'item', wi.id::text,
               {payload % ("wi.created_at + (wi.updated_at - wi.created_at) * 0.35")},
               wi.created_at + (wi.updated_at - wi.created_at) * 0.35,
               coalesce(wi.assignee_id, wi.reporter_id), true
        {base_joins}
        JOIN states fs ON fs.id = wi.state_id
        JOIN seed_mid_state ms ON ms.project_id = wi.project_id
        JOIN states st ON st.id = ms.state_id
        WHERE wi.project_id = ANY(%s)
          AND fs.category IN ('done', 'canceled')""", (pids,))
    n2 = cur.rowcount
    cur.execute(
        f"""INSERT INTO events (event_type, entity_type, entity_id, payload,
                                created_at, actor_id, silent)
        SELECT 'item.updated', 'item', wi.id::text, {payload % "wi.updated_at"},
               wi.updated_at, coalesce(wi.assignee_id, wi.reporter_id), true
        {base_joins}
        JOIN states st ON st.id = wi.state_id
        JOIN states ds ON ds.project_id = wi.project_id AND ds.is_default
        WHERE wi.project_id = ANY(%s) AND wi.state_id <> ds.id""", (pids,))
    n3 = cur.rowcount
    log(f"events in {time.time() - t_e:.0f}s "
        f"({n1:,} created + {n2:,} mid + {n3:,} final)")

    # ------------------------------------------------------ search index ----
    # Same recipe as search/indexer.py (_TSV_UPDATE), applied set-wide.
    t_s = time.time()
    cur.execute("DROP INDEX IF EXISTS ix_search_index_tsv")
    cur.execute(
        """INSERT INTO search_index (item_id, project_id, key, title,
                                     description, comments_text, tsv, updated_at)
        SELECT wi.id, wi.project_id, p.key || '-' || wi.number, wi.title,
               wi.description, coalesce(cagg.txt, ''), NULL, now()
        FROM work_items wi
        JOIN projects p ON p.id = wi.project_id
        LEFT JOIN LATERAL (
            SELECT string_agg(c.body, E'\n' ORDER BY c.created_at) AS txt
            FROM comments c
            WHERE c.item_id = wi.id AND c.visibility = 'public') cagg ON true
        WHERE wi.project_id = ANY(%s)""", (pids,))
    log(f"  search_index rows: {cur.rowcount:,} ({time.time() - t_s:.0f}s)")
    for i, pid in enumerate(pids, 1):
        cur.execute(
            """UPDATE search_index SET tsv =
                setweight(to_tsvector('english',
                    key || ' ' || replace(key, '-', ' ') || ' ' || title), 'A') ||
                setweight(to_tsvector('english', description), 'B') ||
                setweight(to_tsvector('english', comments_text), 'C')
            WHERE project_id = %s AND tsv IS NULL""", (pid,))
        if i % 20 == 0:
            log(f"  tsv: {i}/{len(pids)} projects")
    cur.execute("CREATE INDEX ix_search_index_tsv ON search_index USING gin (tsv)")
    log(f"search_index done in {time.time() - t_s:.0f}s")

    # ------------------------------------------------------------ post ------
    cur.execute(
        """UPDATE projects p SET next_number = mx.m + 1
        FROM (SELECT project_id, max(number) AS m FROM work_items
              GROUP BY project_id) mx
        WHERE mx.project_id = p.id AND p.id = ANY(%s)""", (pids,))
    # No worker may replay the synthetic backlog: jump every consumer to head.
    cur.execute("UPDATE consumer_offsets SET last_event_id = "
                "(SELECT max(id) FROM events), updated_at = now()")
    conn.commit()
    log("committed")

    conn.autocommit = True
    for t in ["work_items", "comments", "events", "search_index", "attachments",
              "item_labels", "projects", "states", "issue_types", "labels",
              "teams", "team_members", "field_definitions", "screens",
              "screen_fields", "views", "project_members"]:
        cur.execute(f"VACUUM ANALYZE {t}")
    log(f"done in {(time.time() - t0) / 60:.1f} min")

    cur.execute("SELECT pg_size_pretty(pg_database_size(current_database()))")
    log(f"database size: {cur.fetchone()[0]}")
    conn.close()


if __name__ == "__main__":
    main()
