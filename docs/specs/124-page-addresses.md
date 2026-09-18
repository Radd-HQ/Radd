# Spec 124 — Page addresses: keyed by id, addressed by path (RADD-1233)

**Status:** built 2026-09-18. **Module:** `pages` (+ `notify`, `mailrender`, the SPA router).

## The problem

A page's slug was its identity. It was unique per space across live *and*
archived rows, frozen after creation so links would survive, and every rule
around it defended that invariant: `-2` suffixes for a second page with the
same title anywhere in the space, an archived "Onboarding" holding `onboarding`
forever so the next "Onboarding" was `onboarding-2` (found building RADD-1228),
a restore that would have to rename a page. A label promoted to an identifier.
Issues never had this problem: `RADD-1233` is the key and the title is free.

## The model

- **`pages.id`** is the key. **`pages.number`** is the same identity as a small
  instance-wide integer (one sequence), the thing a permalink carries.
- **`slug`** is the segment a page contributes to its *path*, unique among
  **live siblings** only (partial expression index over space, coalesced
  parent, slug where `archived_at IS NULL`). That is the tree's natural
  invariant: a path is unambiguous exactly when siblings differ.
- **`path`** = `parent-slug/…/slug`, space-relative, *derived* from rows the
  tree already loads whole and never stored. Renames and moves rewrite nothing.

## Two addresses

| Address | Form | For |
|---|---|---|
| Readable | `/pages/<space>/<slug>/<slug>/…` | what people see, share and read |
| Permalink | `/pages?pageId=<number>` | everything the server emits (mail, notifications, audit refs, search hits) — survives every rename and move |

The SPA resolves a permalink and *replaces* it with the readable address.
`lib/page-links.ts` is the one place a page URL is assembled.

## Resolution — one query, then exactness

1. **Walk**: select every page in the space whose slug is in the path's segment
   set; walk from the root in memory matching `parent_id` level by level (live
   rows first, archived rows as a second pass). Same-named pages at other
   depths are in the set and never match their level's parent.
2. **History**: `page_path_history` holds every address the page — and each
   descendant whose address changed with it — ever had, written on rename,
   move and restore. A stale path is looked up *exactly*, so it lands on the
   page it named and never on a namesake that holds the address now.
3. **Legacy**: a single segment is tried as a bare slug anywhere in the space,
   only when it names exactly one page (pre-1233 `/pages/<space>/<slug>` links
   to nested pages). Several matches are a 404, not a guess.

Rejected: a bare-UUID URL (unreadable, no architectural gain over id-keyed +
path); a `/archived/…` prefix (cosmetic, does not free the name); a
materialised path column or `ltree` (a single index probe on read, but subtree
rewrites on every move and rename, for trees of hundreds of rows); last-segment
heuristics for stale links (a moved page and its namesake became a coin toss).

## Consequences accepted

- A move beside a live sibling with the same slug gets `-2`; the old address
  is remembered. A restore beside one does the same, and the event says so.
- A path can end in anything, so nothing may hang a literal after the page
  segment: the print view moved to `/print/pages/<space>/<path>`.
- `radd:include` takes `page` as a path (or a number); `space:path` reaches
  another space — a slash is a separator now.
- The API still accepts writes to an archived page (the Confluence importer
  re-applies through `update_page`).

## Proof

`server/tests/test_page_paths.py` (mint, walk, permalink, history on rename,
move and ancestor rename, archived namesakes) and
`web/scripts/page-paths-proof.mjs` — 15 checks in a real browser: tree and
breadcrumb links by path, the permalink redirect, stale addresses after a
rename and a move, the namesake left alone, a legacy single-segment link, an
archived namesake no longer blocking a name, and the print view.
