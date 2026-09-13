# Spec 121 — Public projects, issue visibility, and Sign in with GitHub

User ask (2026-09-13): Radd is on GitHub and its README links to
project.radd-hq.com, where every link lands on a login page. Make a project
**public** so anyone can read its issues and public comments without signing
in; public saved views show only what the world may see; add **Sign in with
GitHub**; and let people who sign in through GitHub or Google comment and file
issues. While answering "can I hide one issue in an HR project from everyone
but the people on it?", the ask grew a per-issue **visibility** level.

Spec 115's D9 ("no anonymous reporting") stands: nothing here lets an
unauthenticated caller WRITE. Reading is the new thing, and it is built so
that the anonymous visitor is one more principal in the one authorisation
model rather than a second model beside it.

## 1. The world is a principal, not a flag

Two seeded `users` rows with fixed ids and `UserSource.PRINCIPAL`:

| Row | Id suffix | Held by |
|---|---|---|
| **Anyone** | `…000000a4104e` | every request, signed in or not |
| **Signed-in users** | `…0000005160ed` | every request carrying a session or key |

They are grant SUBJECTS. `auth.grants._subject_condition` (the one place a
grant's subject is matched against an actor) adds `user_id = Anyone` for every
actor and `user_id = Signed-in users` for every real one; the access-grant
framework's `SubjectContext` carries the same `principal_ids`. Nothing else in
the resolver changes: `granted_role_ids`, `effective_permissions`,
`readable_projects`, `relation_read_clause`, the spec-114 MCP catalog — all of
it inherits, because "what the world holds here" is now an ordinary
project-scoped `global_role_grants` row.

**A public project** is therefore one row: the seeded **Public** role granted
to Anyone on the project. Settings → Project → Access shows it as a toggle
("Public project"), and the permission inspector explains a visitor's access
the way it explains anyone else's. **Contributions from outsiders** are a
second row: the seeded **Contributor** role granted to Signed-in users on the
project. A public project defaults to contributions ON (the ask is "let people
comment and file issues"); a private project cannot have them (the toggle
needs the project public — a Contributor grant on a private project would be
unreachable by construction, since `item.create` needs a project the actor can
see).

Seeded roles (`BuiltinRoleKey.PUBLIC`, `BuiltinRoleKey.CONTRIBUTOR`):

- **Public**: `item.read@public` plus the catalog reads a rendered issue needs
  (`label.read`, `cycle.read`, `release.read`, `role.read`, `team.read`,
  `card_preset.read`). No `comment.read_internal`, no `page.read` (a public
  wiki space is its own grant, §5).
- **Contributor**: `item.create`, `item.update@own`, `comment.write`,
  `attachment.create`. Reading comes from Public via Anyone.

Rejected: a `projects.public` boolean consulted inside the resolvers. That is
a second delivery mechanism beside grants — the thing RADD-929 just removed —
and it can only say yes/no where a grant can say WHAT. Rejected: a parallel
`/public/projects` router with trimmed schemas (the spec-74 pattern). It is a
second authorisation model, which D9 refused, and it needs its own copies of
listing, comments, attachments, search and views; the public KB already shows
the drift (images broken since the day it shipped — §5 retires it).

## 2. The anonymous actor at the seam

`auth.deps.actor` resolves like `optional_user` and returns the Anyone row
when there is no credential. `Actor = Annotated[User, Depends(actor)]`.
`CurrentUser` keeps its meaning (a real account, 401 otherwise), so the 600+
existing sites are untouched; only the endpoints a public project needs to
render switch to `Actor`. The dependency is **structurally read-only**: a
non-read method resolving to Anyone is refused at the seam, the RADD-836
view-as rule, so no write can ever be attributed to the principal even if a
route declared `Actor` by mistake.

The endpoints that accept `Actor` are a frozen inventory
(`tests/test_anonymous_surface.py`): every route declaring it must be listed,
and every listed route must declare it. A new route cannot join the anonymous
surface by accident, and removing one from the list is a review decision.
The inventory: projects (list, get, by-key, summary), items (list, ids, count,
get, by-key, children, links, history, web-links, pages, rollup, allowed
transitions), comments (list, feed), attachments (list, download), views
(list, get, counts), states, labels, issue types, fields (list, writable),
screens, cycles (list, summary), releases (list), scoped-settings resolve,
search (all three), pages + page-spaces reads (§5), `/auth/me`,
`/capabilities`, `/instance/*` reads.

`GET /auth/me` answers 200 for the anonymous actor with
`{anonymous: true, id: <Anyone>, permissions: [], …}` instead of 401. The SPA
keys everything personal on `anonymous` (§7).

**Realtime** stays cookie-only; the anonymous shell never opens the socket.
**MCP** stays key-only. **Notifications** never target a principal.

## 3. Issue visibility: public / internal / restricted

`work_items.visibility` (`ItemVisibility`), default from the project setting
`item_default_visibility` (scoped setting, instance → project, default
`public`):

| Level | Readable by |
|---|---|
| `public` | Anyone holding `item.read` on the project — the world, when the project is public |
| `internal` | Members only: unqualified `item.read` holders. Hidden from the world even in a public project |
| `restricted` | The people on it — reporter, assignee, participants — provided they hold `item.read` in any form. Project managers do not bypass (D1); instance admins do |

The vocabulary is the one comments already use (`CommentVisibility`), so a
public issue with an internal note reads consistently.

Enforcement is one kernel primitive, composed under every relation set:

- A **row guard** (`RowGuardSpec`, registered by `items` on the manifest like
  its relations): `open_where` = `visibility != restricted`, `admits` =
  `("own", "assigned", "participant")`, resolved through the relation registry
  at query time. `authz.relation_filter` ANDs it under every answer and
  answers it alone for `@any` — so `@any` stops meaning "every row" the moment
  a guard is registered; `relation_holds_row(_async)` and
  `relation_row_ids_holding` apply it the same way. `RelationActor.unrestricted`
  (the instance admin) is the one bypass (D1). The two item seams
  (`relation_read_clause`, `ensure_item_relation`) simply stop short-circuiting
  `@any` before calling the primitives; notify's delivery gate does the same.
- `@public` is a new item relation (`where: visibility = public`) flagged
  `row_property=True`, which is what makes holding it ENTITLE the actor to the
  project in `visible_projects`.
- `search_index.visibility` mirrors the column (the d841 rule: search never
  joins `work_items`); `public` joins the mirrored relations and the guard is
  compiled over the mirror (`_guard_index_clause`).

`item.read@public` is a new item relation (`where: visibility = public`,
`holds: row.visibility == public`), off the any⊃team⊃own chain like
`@assigned`. Because it is a property of the ROW, not of the actor, a project
where it is held counts as **entitled** in `visible_projects` — public
projects appear in the rail for everyone.

Changing visibility needs `item.update` on the row and refuses a change that
would hide the issue from the actor making it (admins excepted). The issue
rail shows a visibility control; in a private project the `public` and
`internal` levels are equivalent (the world holds nothing), so the control
offers Normal / Restricted there and Public / Members only / Restricted in a
public project.

## 4. Public views

A view is visible to the world only by an explicit **"Anyone on the web:
viewer"** share — an `access_grants` row whose subject is the Anyone
principal, written from the existing sharing dialog. `global_access` keeps
meaning every signed-in user. Rows are scoped by the actor as they always
were, so a view shared with the world shows exactly the public issues of
public projects and nothing else; the sharing dialog offers the row only when
the view's project is public or the view spans all projects.

## 5. The public wiki joins the model

Spec 74's `page_spaces.public` + `/public/pages/*` + `/public-pages` SPA
routes are deleted. A public space is `page.read` (the Viewer role) granted to
Anyone on the space, through the space-scoped grants RADD-791 built. Public
pages render inside the ordinary wiki with the ordinary shell, attachments
inside them download through the ordinary chokepoint (§6), and the semantic
index's copied public flag goes with the column. The migration converts every
public space into the grant.

## 6. Attachments

`GET /attachments/{id}/download` accepts `Actor`. The spec-102 ACL is
default-open and gates on the parent binding, so a public issue's files
download for the world and a restricted issue's do not, with no new rule.

## 7. The SPA

The same shell renders for an anonymous visitor: a **Sign in** button in the
avatar slot, no inbox bell, no pins, no realtime socket, no leave lookup, no
plugin preference sync, and `useNavFacts` hides Timesheet / Portal / My Work /
New item. The auth gate lets `anonymous` through; personal routes (inbox,
my-work, settings, profile, portal) redirect to `/login?next=<path>`, and so
does any 401 or a 404 met while anonymous (the issue you cannot see may be
one you could see signed in). `next` rides the SSO flow cookie, so a GitHub
sign-in returns to the issue that prompted it. `/` for an anonymous visitor
is the projects index.

## 8. Sign in with GitHub

`SsoKind.GITHUB` in the spec-110 registry. GitHub is plain OAuth2 — no
discovery, no `id_token` — so the spec-110 claim "a kind only supplies
discovery defaults" is restated as: **a kind supplies its endpoints and its
profile strategy; the state + PKCE + one-callback + identity-pinning +
signup-allowlist engine is shared.** `KIND_DEFAULTS[github]` pins the
authorize/token endpoints; `service.metadata` returns them without a fetch;
`exchange_code` splits into the token exchange and a per-kind `profile()`:
OIDC/Google verify the `id_token` as today, GitHub calls `GET /user` (subject
= the numeric `id`, never `login`, which is renameable) and `GET /user/emails`
(the `primary` + `verified` address, emitted as `email_verified: true`, so
`require_verified_email` and the email-once linking rule work untouched).
Scopes `read:user user:email`; token requests send `Accept: application/json`.
Settings → Sign-in hides the issuer field for GitHub as it does for Google;
the login page shows a GitHub mark.

Provisioned accounts hold the Baseline plus whatever Signed-in users are
granted — nothing per provider is needed for public contributions, which is
why they are a project fact (§1) and not a provisioning rule.

## 9. Abuse control

Sign-up becomes open on the public instance, so writes get a bounded
admission: `auth.throttle` generalises into a per-account sliding window
consulted by `POST /items` and comment creation (`RADD_WRITE_WINDOW_SECONDS`,
`RADD_ITEM_CREATES_PER_WINDOW`, `RADD_COMMENTS_PER_WINDOW`; 429 with
`Retry-After`; instance admins exempt). Anonymous reads stay the deployment
proxy's job, as spec 74 documented.

## 10. Migration (one revision, `d121public`)

- `users`: the two principal rows; `work_items.visibility` (backfilled
  `public`); `search_index.visibility`.
- Roles: Public + Contributor seeded via `ensure_builtin_roles`.
- `page_spaces.public` → a Viewer grant to Anyone per public space, then the
  column is dropped.
- No project is public after the migration. The live instance makes RADD
  public by hand, through the toggle.

## 11. Tests and proofs

- `test_anonymous_surface.py` — the frozen `Actor` inventory + the read-only
  seam.
- `test_principals.py` — Anyone/Signed-in grants reach every actor; a
  Contributor grant on a private project is unreachable; the principal rows
  cannot log in, be assigned, or appear in directories.
- `test_item_visibility.py` — the three levels against an unqualified
  reader, a `@public` reader, a `@own` reader, the reporter of a restricted
  item, a project manager, an admin; list, count, search and get agree
  (`test_relation_semantics` extended with `@public`).
- `test_sso_providers.py` — the GitHub kind's endpoints, and `profile()` over
  mocked `/user` + `/user/emails` (`httpx.MockTransport`).
- `web/scripts/public-project-proof.mjs` — a headless anonymous visitor opens
  a public project, sees public and not internal/restricted issues, sees
  public and not internal comments, downloads an attachment, and is bounced
  to `/login?next=` on a private issue; the same walk signed in as a fresh
  GitHub-provisioned account can comment and file.
