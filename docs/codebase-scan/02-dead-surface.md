# Dead surface — built, served, unreachable

> **Correction (2026-08-15).** Three of this scan's findings did not survive
> re-verification: §2 was a measurement error (the caller lives in a non-UTF8
> file that plain grep skips — use `grep -a`), §4's route was deleted by the
> RADD-893 dead-code sweep, and §6/§7 were resolved by RADD-816/824. Each
> section carries its own correction; §1 (webhook deliveries) re-verified
> TRUE today and remains the highest-value entry.

432 server routes extracted from their decorators and prefixes; every
distinctive literal path segment checked against **all** of `web/src` and
`web/packages`. Six routes have a segment that appears in neither.

This is the failure spec 87 recorded: *"all 47 global atoms were ungrantable for
a year because nothing could deliver them."* A capability with no delivery is
indistinguishable from a missing one.

---

## 1. Webhook delivery log — **dead, and it matters**

```
GET /webhooks/{endpoint_id}/deliveries      modules/webhooks/router.py:56
```

`deliveries` appears nowhere in the frontend. The delivery history is recorded,
queryable and served — and there is no screen. A webhook that stops working is
therefore silent: the answer exists and nobody can look at it.

Highest-value entry in this file. The endpoint is done; this is a table.

## 2. Plugin contribution settings — **CORRECTED: measurement error, not dead**

```
GET /plugins/contribution-settings          modules/pluginmgr/router.py:42
PUT /plugins/{plugin_id}/contribution-settings   modules/pluginmgr/router.py:49
```

The scan claimed "the admin half is not called from anywhere". It is —
`web/packages/plugin-sdk/src/slots.tsx` PUTs `/plugins/{id}/contribution-settings`
at `:244` and GETs `/plugins/contribution-settings` at `:270`, exactly the
global-admin scope of spec 94's two-scope toggles. The file is non-UTF8, so
`file(1)` reports it as "data" and a plain grep skips it as binary; only
`grep -a` sees the calls. The original finding is preserved as a caution:
**this scan's methodology (grep for path segments) silently misses non-UTF8
frontend files — always re-check a "dead" route with `grep -a`.**

## 3. Local-embedding diagnostic

```
GET /ai/local-embed                         modules/ai/admin_router.py:147
```

The `radd[localembed]` CPU backend's probe. Plausibly deliberate — an operator
curls it — but Settings → AI is where it would belong, and Settings → Monitoring
(spec 105) already surfaces exactly this kind of health signal.

## 4. Jira import re-suggest — **CORRECTED (RADD-893): the route was deleted**

```
POST /jira/plans/{plan_id}/resuggest        (removed — was jiraimport/routers/pipeline.py)
```

Spec 100's importer has an editable mapping plan; this re-ran the suggestion
pass, and the wizard never exposed it. The RADD-893 backend dead-code sweep
resolved it the other way: the endpoint is gone (`grep -rn resuggest
server/src web/src` → 0), so there is no dead surface left — a user who
hand-edits mappings and wants to start over still cannot, but that is now an
ordinary feature request, not an unreachable capability.

## 5. Alertmanager receiver — **correctly absent, not dead**

```
POST /integrations/alertmanager             modules/alertmanager/router.py:20
```

Inbound webhook called by Alertmanager, not by the SPA. **Listed only so the
next person running this scan does not "fix" it.** No action.

---

## Also dead, not routes

## 6. `CrudAction.READ` — **CORRECTED (RADD-816 F6): now deliverable**

At scan time no `CRUD_RESOURCES` entry listed `READ` (the default was
`actions=(CREATE, UPDATE, DELETE)`), so the enum member advertised a
capability that could not be granted. Spec 115 finding F6 resolved it:
`read` became a deliverable action for the config catalogs —
`LABEL_READ`/`CYCLE_READ`/`CANNED_READ`/`TEAM_READ`/`ROLE_READ`/
`CARD_PRESET_READ` are real atoms in `auth/types.py`, resources such as
cycles/teams/labels/canned/views declare `actions=("create", "read",
"update", "delete")` in their `__init__.py`, and the atoms are
Baseline-seeded so day-one behaviour matches the old member floor while
being revocable for the first time (see `auth/permissions.py`, the `role`
resource).

## 7. Nine `*.manage` atoms with zero enforcement — **CORRECTED (RADD-816/824): the atoms were deleted**

At scan time `canned` `cardpreset` `cycle` `label` `release` `role` `sla`
`team` `view` `.manage` were each checked by no `require()` anywhere —
granting one was exactly equivalent to ticking its three CRUD boxes (the
measurement lives in spec 115 finding F13). RADD-816 removed all nine from
`auth/types.py` (the deletion note sits at types.py:81-86); the only
`*.manage` atoms left are the enforced ones (global/project/form/user/
automation/state/field/webhook/page). The `view.manage` client/server split
was fixed by RADD-824: `ViewModal.tsx` now gates on `view.create`, mirroring
the server.
