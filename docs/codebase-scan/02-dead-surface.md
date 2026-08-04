# Dead surface — built, served, unreachable

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

## 2. Plugin contribution settings — **dead, and contradicts the docs**

```
GET /plugins/contribution-settings          modules/pluginmgr/router.py:42
PUT /plugins/{plugin_id}/contribution-settings   modules/pluginmgr/router.py:49
```

CLAUDE.md describes spec 94's **two-scope, plugin-owned per-contribution
toggles**: global-admin in `InstalledPlugin.config` via this endpoint, per-user
in `users.preferences` via `/auth/me/preferences`. The per-user half is wired in
the SPA. **The admin half is not called from anywhere.**

So an admin cannot turn a plugin's individual contribution off instance-wide,
which is the documented behaviour. Either the UI was never built or it was lost;
`useDisabledNavPaths`/`useDisabledMatches` consume the *result*, so the reading
side exists and the writing side does not.

## 3. Local-embedding diagnostic

```
GET /ai/local-embed                         modules/ai/admin_router.py:147
```

The `radd[localembed]` CPU backend's probe. Plausibly deliberate — an operator
curls it — but Settings → AI is where it would belong, and Settings → Monitoring
(spec 105) already surfaces exactly this kind of health signal.

## 4. Jira import re-suggest

```
POST /jira/plans/{plan_id}/resuggest        modules/jiraimport/routers/pipeline.py:94
```

Spec 100's importer has an editable mapping plan; this re-runs the suggestion
pass. The wizard exposes mapping tables but not this. If a user hand-edits
mappings and wants to start over, they cannot.

## 5. Alertmanager receiver — **correctly absent, not dead**

```
POST /integrations/alertmanager             modules/alertmanager/router.py:20
```

Inbound webhook called by Alertmanager, not by the SPA. **Listed only so the
next person running this scan does not "fix" it.** No action.

---

## Also dead, not routes

## 6. `CrudAction.READ` — declared, never used

```python
# modules/auth/types.py:164
class CrudAction(StrEnum):
    """The four verbs of the resource × action matrix (spec 50)."""
    CREATE = "create"
    READ = "read"        # <- no CRUD_RESOURCES entry lists it
    UPDATE = "update"
    DELETE = "delete"
```

`CRUD_RESOURCES` (types.py:321) defaults `actions=(CREATE, UPDATE, DELETE)` and
no resource overrides it to include `READ`. The comment at :318 says reads
"stay open to members" by design — a defensible default, but the enum member
advertises a capability that cannot be granted. Covered by spec 115 finding F6.

## 7. Nine `*.manage` atoms with zero enforcement

`canned` `cardpreset` `cycle` `label` `release` `role` `sla` `team` `view` —
each checked by no `require()` anywhere. Granting one is exactly equivalent to
ticking its three CRUD boxes. Full measurement and recommendation in spec 115
finding F13 / RADD-824; repeated here because it is dead surface by any
reasonable definition.

`view.manage` is worse than dead — the client gates on it while the server
gates on `view.create`, so it hides a button the API would allow.
