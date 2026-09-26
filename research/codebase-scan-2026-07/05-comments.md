# Comments — oversized, stale, or non-factual

Two different problems, and only the second is urgent. A long comment that is
*true* costs reading time; a short comment that is *false* costs a wrong change.

---

## Non-factual — comments describing things that no longer exist

These were the ones worth fixing — each named a concept the codebase removed,
and all three were deleted by the RADD-1097 rename-residue sweep (2026-08-15).

### 1. `config.py` — workspace scope, removed by spec 86 — **FIXED (RADD-1097)**

```python
# (off | guards | strict), overridable per workspace/project via the   # <- was config.py:289
```

There is no workspace: spec 86 stage 3 removed the entity and migrated
`workspace.manage` → `global.manage`, and this comment said otherwise. The
RADD-1097 rename-residue sweep (2026-08-15) deleted it —
`grep -in workspace server/src/radd/config.py` → 0 today.

### 2. `items/service/links.py` — workspace as a live scope — **FIXED (RADD-1097)**

```python
anchor project's WORKSPACE (spec 80 — restricted to projects the actor can   # <- was links.py:45
```

Read as though link scoping were workspace-bounded (it is
project/permission-bounded). Also deleted by the RADD-1097 sweep —
`grep -in workspace …/items/service/links.py` → 0 today.

### 3. `config.py` — MinIO named as the S3 example — **FIXED (RADD-1097)**

```python
# (default; attachments_dir) or "s3" (any S3-compatible store — MinIO, AWS).   # <- was config.py:65
```

Was mildly stale rather than false: MinIO CE is archived and **Garage is the
blessed S3 server** (spec 102), so the example pointed a new operator at the
wrong thing. Deleted by the RADD-1097 sweep — the only MinIO mentions left in
`server/src` are the attachments module's legitimate SDK references.

**Correctly historical, do not "fix":** the ~13 other `workspace` mentions
(`seed.py:2`, `auth/subscribers.py:8`, `auth/schemas.py:167`, `auth/router.py:114`,
`workflow/router.py:35`, `auth/types.py:37`, …) all say the workspace is *gone*
and explain what replaced it. Those are the good kind — they answer "why does
this look like this".

Same for `MEMBER_FLOOR` (`authz.py:58`, `:466`), which is referenced only to
explain what was removed and why the current shape exists.

---

## Oversized — measured

Contiguous `#` blocks ≥12 lines, and docstrings ≥28 lines. Only 11 in the whole
tree, which is a good result for a codebase this size.

| Lines | Kind | Location |
|---|---|---|
| 50 | docstring | `modules/ai/prompts.py:19` |
| 37 | docstring | `modules/auth/authz.py:457` (`readable_projects`) |
| 34 | docstring | `modules/forms/requests.py:1` |
| 31 | docstring | `modules/auth/authz.py:408` (`require_anywhere`) |
| 30 | docstring | `modules/forms/staging.py:1` |
| 28 | docstring | `modules/events/cascade.py:1` |
| 28 | docstring | `modules/auth/authz.py:1` |
| 21 | comment block | `modules/auth/authz.py:56` |
| 13 | comment block | `modules/auth/service.py:781` |
| 13 | comment block | `modules/auth/service.py:644` |
| 12 | comment block | `modules/auth/service.py:475` |

### The judgement

**`authz.py` accounts for four of the eleven** (a 28-line module docstring, a
21-line block, and two 30-line function docstrings). That is not accidental
verbosity — it is the file where three specs' worth of decisions collided
(spec 86's workspace removal, RADD-773's baseline, RADD-672/788's cross-project
gates), and each block explains a bug that the obvious reading would reintroduce.
`readable_projects`' docstring in particular exists because ~28 endpoints once
gated on a check that could not fail.

**Recommendation: leave them.** They are load-bearing, and spec 115's RADD-814
will delete or rewrite `require_anywhere` and `readable_projects` outright —
trimming their docstrings first is work that gets thrown away.

**The one to look at is `ai/prompts.py:19` (50 lines).** Prompt files tend to
accumulate rationale that belongs in a spec; worth checking whether that
docstring is explaining a decision or narrating the prompt.

---

## A pattern worth keeping

The house style — a comment that names the **bug it prevents**, not the code it
sits on — is why this file is short. Examples that should be preserved verbatim
through any refactor:

```python
# modules/auth/authz.py:72
# What survives here is the MECHANISM — every active user holds a baseline.
```

```python
# modules/auth/types.py:82  (RADD-790)
# Attaching a file is its OWN authority. It used to be `item.update`, which
# conflated "may edit this issue's fields" with "may add a file to it"…
```

These are the opposite of noise: each one is a day someone else does not have to
spend. The scan found no case of a comment that merely restates its code.
