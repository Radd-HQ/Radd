# Spec 117 — the Confluence importer

The wiki half of the migration. Spec 100 rebuilt the Jira importer cache-first,
explicit and reversible; this is the same machine pointed at Confluence, writing
into `pages` instead of `items`.

It is the last named gap in `docs/modules.md` §"Remaining cross-cutting gaps".

## What it must do

Bring across, from a Confluence **Server/DC** instance:

- a **whole space**, a **page and its descendants**, or an **explicit set of pages**;
- page **bodies**, converted from Confluence storage format to Radd markdown;
- page **comments** — footer and inline;
- page **attachments**, including the images the bodies embed;
- page **restrictions** and space permissions;
- **macros**, mapped onto `radd:*` page extensions — the set grows as the corpus
  demands, which is why the plan *counts* them before anyone maps them;
- optionally, **version history**.

## The target is Server/DC

`confluence.example.com` serves `/pages/viewpage.action?pageId=…`, which
is Server/DC, not Cloud. That decides three things:

- auth is PAT or basic, matching `JiraConnection.auth_mode` exactly;
- the REST base is `/rest/api`, not `/wiki/api/v2` — space permissions come from
  the space object, not Cloud's `/spaces/{id}/permissions`;
- bodies arrive as **storage format** (`body.storage`), the XHTML dialect with
  `ac:`/`ri:` elements, not Cloud's ADF JSON.

A Cloud adapter is a second `client.py` behind the same `service.py`. Not built;
not designed around either, because guessing at a wire format nobody here runs is
how the old importer's hardcoded `customfield_*` blocklist happened.

## Shape: four phases, the spec-100 machine

Module `server/src/radd/modules/confluenceimport/`, `core=False`.

### 1 · Connections — `confluence_connections`

The `JiraConnection` shape verbatim: `name` unique, `base_url`, `auth_mode`
(`pat`|`basic`), `username`, `credential` (never returned; `has_credential`),
`verify_ssl`, `is_default` with the exactly-one invariant, `source` (`env`|`user`).
Env seeds one, **once** — the spec-101 rule.

### 2 · Snapshot — download once, read forever

`confluence_snapshots` + `confluence_snapshot_pages` + `confluence_snapshot_blobs`,
mirroring `jira_snapshots`/`_issues`/`_blobs`. Every later step reads the cache;
nothing after this phase touches the network.

**Selection is a scope on the snapshot**, which is how "whole spaces or specific
sections with children or specific pages" becomes one concept rather than three
code paths:

```python
class ScopeKind(StrEnum):
    SPACE   = "space"    # every page in space_key
    SUBTREE = "subtree"  # root_page_id and its descendants, depth-capped or not
    PAGES   = "pages"    # exactly these page ids
```

`SUBTREE` and `PAGES` both resolve to a page-id set before download begins, so the
downloader has one input shape. A `PAGES` scope still records each page's
`parent_id`; the run reparents to the nearest **imported** ancestor and reports the
gap, rather than silently flattening.

Stages — the row is the progress bar, as in spec 100:

```
pending → spaces → tree → bodies → versions → comments → restrictions → attachments → done
```

`versions` is skipped unless the snapshot asked for history (below). Cancellation
is cooperative, `mark_interrupted` runs on startup, `COMMIT_EVERY` bounds the
transaction — all inherited idioms, not new ones.

### 3 · Plan — the mapping tables, and the census

`confluence_plans.mappings` JSONB, read and written whole. **Six** tables, not
Jira's nine, because a wiki has less schema:

| Table | Rows are | Default |
|---|---|---|
| `spaces` | Confluence space → create a Radd space, or map to an existing one | create |
| `macros` | every macro name found, **with its count** | see below |
| `users` | Confluence username → Radd user | matched by email, then username |
| `groups` | Confluence group → Radd group | **identity** (see Restrictions) |
| `labels` | Confluence label → Radd label | identity, create if absent |
| `jira_links` | Jira project key seen in a `jira` macro → imported Radd project | resolve |

Every table carries `count` and the spec-100 `unused` treatment: rows at count 0
collapse into the hidden section and default to `IGNORE`. `PlanProblem` and
`Problem` carry `section` + `mapping_key` so the run report offers **"Fix in
Macros → drawio"** instead of leaving you to guess.

#### The macro census

The plan's profiling pass streams the cached bodies, counts every
`<ac:structured-macro ac:name="…">`, and merges a count-0 tail for macros Radd
already renders. That is the whole point: Jira's 337 fields became 14 decisions
because the profile said which 14 mattered, and a Confluence corpus is the same
problem — hundreds of macro names in the wild, a dozen that actually carry your
content.

A macro row's action is one of:

- `NATIVE` — the converter emits plain markdown (`code` → a fence, `toc` →
  `radd:toc`). Pre-filled for every macro in the built-in table below.
- `EXTENSION` — emit `radd:<name>` with mapped parameters.
- `UNSUPPORTED` — emit `radd:unsupported-macro` carrying the original name and
  parameters. **Visible, honest, and upgradable in place**: build the renderer
  later and re-run the converter over the same snapshot, or leave it — nothing was
  lost.
- `STRIP` — drop it. For genuine chrome.

The default for an unmapped macro is `UNSUPPORTED`, never `STRIP`. A page whose
content *was* the macro must not import as an empty page.

### 4 · Run — provision, write, record, reverse

```
pending → provision → spaces → pages → bodies → attachments → comments
        → restrictions → versions → relink → done
```

- **Dry run shares the write path** via one `commit: bool`, exactly as
  `jiraimport.apply.apply_item` does. Counts are truthful with writes off.
- **Silent**: the pipeline runs inside `events.quiet(options.quiet and not dry_run)`,
  so notify/webhooks/automations skip the import while search and history do not.
- **Reversible**: `confluence_import_records` — the `JiraImportRecord` shape,
  `BigInteger Identity()` so undo is the exact inverse of write order, `before`
  images narrowed to the columns the import touched.
- **Relink**: `confluence_pending_refs` for links whose target page has not been
  imported yet — the cross-space case, and the `PAGES`-scope case where a link
  points outside the selection.

Bodies are written in a stage **after** pages, because a link can only be rewritten
once its target's Radd id exists. Attachments come before comments for the same
reason: a comment can embed an image.

## The converter — storage format → markdown

`confluenceimport/storage/`, pure and unit-tested, no DB and no network.

**Parser: stdlib `html.parser`.** No new dependency. Confluence storage format is
machine-generated XHTML, and a *lenient HTML* parser handles the pasted junk in a
decade-old corpus better than a strict XML one would — `lxml` buys speed we do not
need and a C extension in the image. A ~60-line tree builder over `HTMLParser`,
then a visitor per node.

### Block macros → `radd:*` fences

Five of the seven first-party extensions already exist, which is most of the
common vocabulary:

| Confluence | Becomes | Note |
|---|---|---|
| `toc` | `radd:toc` | `maxLevel` → `depth` |
| `children`, `pagetree` | `radd:children` | `depth`; `pagetree` roots elsewhere → report |
| `info`, `note`, `tip`, `warning` | `radd:callout` | `kind` = info/info/success/warning |
| `panel` | `radd:callout` | `kind: info`; `title` from `ac:parameter[title]` |
| `include`, `excerpt-include` | `radd:include` | target resolved through the page map |
| `contentbylabel` | `radd:label-list` | `label` from the `cql`/`labels` parameter |
| `code` | a fenced code block | `language` parameter → the fence info string |
| `ac:task-list` | `- [ ]` / `- [x]` | native markdown, not an extension |
| `expand` | `radd:expand` | **new** — trivial renderer, common macro |
| `jiraissues`, `jira` with `jqlQuery` | `radd:items` | **new** — see below |
| anything else | `radd:unsupported-macro` | **new** — the honest fallback |

### `radd:items` — the JQL table, translated

A `jiraissues` macro is a live query rendered as a table. Its Radd equivalent is
an SLQ query rendered as a table — the language already exists, and the item
dialect is exactly the right root. So the extension takes `{query, columns}` and
the converter makes a **best-effort JQL→SLQ translation**, recording the original
JQL in the block either way.

A translation that fails is not a failure of the import: the block imports with
the original JQL in a `note` parameter and an `unsupported` flag, so the page shows
what the query *was* and a person fixes it. Guessing silently is the failure mode
worth avoiding.

### Inline macros — the honest gap

`radd:*` fences are **block-level**. Three common Confluence constructs are inline:

- **`<ri:user>` mentions** → `@[Name](uuid)` when the user resolves. Native; the
  markdown renderer already handles this token.
- **single-key `jira` macro** → `#[KEY](KEY)` when the key resolves to an item
  imported by spec 100, otherwise a markdown link to the Jira browse URL. This is
  what joins the two halves of the migration: the wiki stops pointing at the system
  being replaced. `item_page_links` picks these up for free, because
  `pages/mentions.py` reconciles derived links from body text.
- **`status` lozenge** → inline code (`` `IN PROGRESS` ``). Lossy — the colour is
  gone.

There is no inline extension seam in the kernel, and inventing one for a coloured
lozenge is not proportionate. Filed as a follow-up; the degrade is deliberate and
recorded here so nobody reads it as an oversight.

### Everything else

Tables (including `colgroup` widths, dropped), headings, lists, `<ac:image>` →
`![alt](attachment-url)` rewritten to the imported attachment, `<ac:link>` +
`<ri:page>` → a Radd page link resolved through the page map (or a pending ref),
`<time datetime>` → its text, `<ac:placeholder>` → dropped (it is editor chrome,
never content).

## Restrictions — AD groups map to themselves

Confluence page restrictions name AD users and groups. Radd already mirrors AD:
`groups` holds `dn` (unique) with real nesting via `group_parents`, and
`GrantSubject.GROUP` is a first-class access-grant subject that `pages`'
`_PAGE_SPEC` already accepts, matched **through nesting** (RADD-832).

So the mapping is **identity, by DN** — the same directory behind both systems is
the assumption, and it is a checkable one. A Confluence restriction becomes an
`access_grants` row: `subject_type=group`, `subject_id=<groups.id matched by dn>`,
`resource_type=page`, `access=read`|`write`. No translation layer, no new concept.

The `groups` mapping table is the **fallback**, for principals that do not resolve
— a group that predates the current directory, a deleted user, an instance whose
AD was never connected. It carries per-row targets plus two bulk controls the user
asked for:

- **map all to X** — every unresolved principal resolves to one named group/team;
- **map all unknown to Y** — per-row overrides stand, the tail goes to Y.

An unresolved principal with no fallback set **fails its page** rather than
importing it open. A wiki import that silently opens a restricted page is a data
leak, and it is the failure nobody notices.

Confluence's view/edit split maps onto `Access.READ`/`Access.WRITE`, which
`_PAGE_SPEC` already declares with `implied_by={read: (write,)}`. Space
permissions become **space-scoped role grants** (`global_role_grants.space_id`,
RADD-791) rather than per-page grants — the levels are coarser, and that is the
right layer for them.

Two Confluence semantics to preserve deliberately:

- Confluence restrictions **inherit down the tree**, and so do Radd's since
  RADD-948 (every ancestor on the path must pass). These agree; no translation.
- Confluence's "edit restricted, view open" is expressible, because `write` does
  not imply exclusive `read`.

## Version history — optional, off by default

Full history is supported and **defaults to off**. A live page in the corpus sits
at version 206; pulling every revision of every page means one body fetch and one
row per revision, and most migrations do not want it.

- `ConfluenceSnapshotOptions.include_history: bool = False` — when off, the
  `versions` stage is skipped in both the download and the run, and the snapshot
  stays small.
- When on, `history_limit: int | None = None` bounds it to the most recent N
  revisions per page. `None` means all.
- Revisions become `page_versions` rows written **directly**, not by replaying
  `update_page` once per revision. Replaying would fire N `page.updated` events, N
  watcher fan-outs and 2N reindex passes per page to reconstruct history that is,
  by definition, already final.

`PageVersion` stores the *previous* content — version N's row is written when N+1
becomes current — so the importer writes revisions 1..N-1 as rows and revision N as
the live `pages.body`, with `page.version = N`.

## External identity — the durable back-reference

**A page must remember where it came from, on the page.**

The Jira importer never needed this and the reason is instructive: it maps
`DEV-123` onto Radd `DEV-123`, so `items_service.find_item_by_key()` *is* the
external identity, and `apply.apply_item` upserts on it. There is no `external_id`
column on `work_items` because the key already is one.

**Pages have no such handle.** A page carries a UUID and a per-space `slug` that is
cosmetic and frozen after create; neither is derived from Confluence. Without a
column, the Confluence-id → page mapping lives only in `confluence_import_records`
— which is scoped to one run, deleted by rollback, and gone if the plugin is
uninstalled. That breaks three things the migration actually needs:

1. **Re-import is an upsert, not a duplicate.** Running the same space again after
   fixing a macro mapping must update the pages it made, not make a second copy.
2. **Links resolve across runs.** Importing space `PIP` in March and space `TRX` in
   June: a `TRX` body linking to a `PIP` page must resolve, and the run that
   created the target is long finished. Today `confluence_pending_refs` can only
   resolve within the importer's own bookkeeping.
3. **Provenance survives.** "Which Confluence page was this?" stays answerable
   during the years both systems run side by side.

So `pages` and `page_spaces` each gain a **generic, source-qualified** external
identity — not a `confluence_page_id`, because `pages` must not learn the word
Confluence, and because the next importer should not have to invent its own map
table:

```python
external_source: Mapped[str] = mapped_column(String(200), default="")
external_id:     Mapped[str] = mapped_column(String(200), default="")
```

- `external_source` is the *instance*, not the product — `confluence:confluence.example.com`
  — because two Confluence servers both have a page `12345`. The importer owns the
  string; `pages` only stores it.
- `external_id` is the Confluence page id as text.
- Empty on every natively-created page. Unique together under a **partial** index
  (`WHERE external_id <> ''`), so native pages do not collide on the empty pair.
- Written only through the new `PageCreate` seam, never by an `UPDATE` from the
  importer.

`pages.service` grows one lookup — `find_by_external(session, source, external_id)`
— which is what makes the converter's link rewriting a plain question with an
answer, in any run, forever.

`page_spaces` gets the same pair for the same reason: re-importing a space must
land in the space it made, not create "Space PIP (2)".

**Not extended to attachments or comments** in this spec. Their identity within a
re-import is `(page, filename)` and `(page, author, created_at)`, both available
from the snapshot, and adding columns nothing yet reads is speculative. Called out
here so the omission is a decision rather than an oversight.

## Seams this needs from `pages`

Four gaps. Three are the same gap `comments` already closed with
`CommentCreate.author_id` + `created_at` gated on `PROJECT_MANAGE`. They belong in
`pages`, added as public seams — **not** worked around by writing `pages` rows from
the importer, which rule 1 forbids and which would fork the slug, position,
backlink and mention logic.

1. **`PageCreate.author_id`** — historical authorship. `create_page` currently sets
   `created_by` and `updated_by` to the actor.
2. **`PageCreate.created_at` / `PageUpdate.updated_at`** — backdating. Both models
   use `TimestampMixin` server defaults today.
3. **`pages.service.write_version(...)`** — the direct `PageVersion` seam the
   history import needs.
4. **`PageCreate.external_source` / `.external_id`** plus
   `pages.service.find_by_external(...)` and the matching pair on
   `PageSpaceCreate` — the external identity above. Migration `d117extid`.

All four gate on `page.manage` in the target space (pages have no project, so
`PROJECT_MANAGE` is not the right atom) and are recorded on the run as a
`ProblemKind.PERMISSION` warning when absent, matching `jiraimport._check_fidelity`
— missing the permission degrades fidelity, it does not stop the run.

## Authorization

Both routers gate on `InstanceRole.ADMIN`, hand-rolled, as `jiraimport` does. No
new permission atoms: an importer is an admin tool, and inventing
`confluenceimport.*` atoms nobody grants was exactly the dead-atom problem spec 87
audited.

## Frontend

`/settings/confluence-import`, one scrolling page, not a step wizard —
`ConnectionsPanel` → `SnapshotsPanel` (with the scope picker) → `PlansPanel` →
`PlanEditor` (six tabs) → `RunsPanel`. The spec-100 components are the model; the
`MappingSection`/`splitByUse` used/unused split and the `ProblemList` "Fix in …"
jump are reused wholesale.

The nav entry carries `plugin: "confluenceimport"` so disabling the plugin removes
it, per spec 94.

## Done when

- A space, a subtree and an explicit page set each import, with tree shape and
  sibling order preserved.
- Bodies render with tables, code, callouts, task lists, images and page links
  intact; every macro is either rendered, natively converted, or visibly carded.
- Comments arrive with original author and timestamp, inline ones anchored.
- Attachments download and their in-body images resolve to them.
- A restricted page is restricted in Radd, to the same AD groups, and an
  unresolvable principal fails that page rather than opening it.
- A `jira` macro whose key was imported by spec 100 renders as a live issue chip.
- History imports when asked for and is absent when not.
- A dry run reports what a real run would do; a real run is rollback-able.
- Running the same scope twice **updates** the pages it made rather than
  duplicating them, and a link from a space imported later resolves to a page
  imported earlier.

## Deliberately not built

- **Confluence Cloud.** A second client behind the same service seam.
- **Blogs, whiteboards, databases.** Pages only.
- **An inline extension seam** for the `status` lozenge.
- **Page templates and blueprints.** Radd has `page_templates`; mapping
  Confluence's blueprint machinery onto it is its own spec.
- **Two-way sync.** The external identity makes re-import an upsert, which is in
  scope. Watching Confluence for changes, or writing back to it, is not: that is a
  connector, not an importer, and it has a different failure model.
