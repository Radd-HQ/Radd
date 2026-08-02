# Spec 73 — Requester portal (intake-form directory + sharing)

Target-features wave, part 6. A portal page that shows a signed-in user every
intake form AVAILABLE TO THEM — public forms plus forms shared with them or
their teams — and lets them submit even without project item.create. Sharing
reuses the spec-57 grant-row idiom (presence-only, no levels).

## 1. Form sharing (forms module)

- New `form_shares` table: id, form_id FK CASCADE ix, exactly-one-of user_id /
  team_id (CHECK + FK CASCADE), created_at; unique per (form, subject).
  Presence = the subject can SEE the form on the portal and SUBMIT it. No
  levels (editing stays `form.manage`).
- `PUT /forms/{id}/sharing {shares: [{user_id|team_id}]}` — full-replace,
  `form.manage` on the form's project; subjects validated against the
  workspace (409). `FormRead.shares` for the builder UI.
- `form.updated` emitted on sharing changes (payload `share_count`).

## 2. Portal API

- `GET /portal/forms` (any authenticated user, no other gate) → enabled forms
  across all workspaces where `allow_public` OR a share row matches the actor
  or their teams; grouped payload `[{project: {id,key,name}, forms:
  [{id, name, description}]}]`. Trimmed — no tokens, no field config.
- `GET /portal/forms/{id}` — render payload for an ELIGIBLE actor (same
  public-or-shared check; 404 otherwise): reuses the spec-62 public-render
  trimming (`render_public_form`) since a portal visitor may not read the
  field registry.
- `POST /portal/forms/{id}/submit {title, values, description?}` — eligible
  actors; runs `submit_form` AS the SYSTEM actor with `reporter_id=actor.id`
  (the sharee may hold no item.create anywhere; the share is the grant —
  exactly the public-form trust model, but the reporter is a known user, so
  no mail-contact path). Response `{key, title}`.

## 3. Frontend

- New route `/portal` (authed): sidebar entry "Portal" (visible to everyone).
  Page = form cards grouped by project (name, description, project chip);
  click → portal submit page (`/portal/forms/$formId`) with the same
  title/description/fields layout as the public form page + the KB
  deflection panel (authenticated deflect endpoint works here).
- Form builder (project settings → Forms): a "Sharing" block next to the
  public-link toggle — user/team picker chips writing `PUT /sharing`.
- After submit: success screen with the created key; members with item.read
  get a link to the issue.

## 4. Tests

- portal listing: public form visible to any member; shared-with-team form
  visible to a member of that team and invisible to others; disabled forms
  excluded.
- portal submit: sharee WITHOUT item.create creates the item, reporter =
  sharee; non-eligible actor 404.

## Known simplifications

- Portal lists by ELIGIBILITY, not by workspace membership — a form shared to
  you in another workspace still shows (that's the feature).
- No anonymous portal: logged-out users use direct public-form links (public
  tokens stay unlisted by design).
- Requesters see their submitted request only if they hold item.read; the
  richer "my requests" surface can layer on later without schema changes.

## As-built notes

Shipped as specced, all inside the **forms module** (no new module). Backend:

- `form_shares` (models.py): id, form_id FK CASCADE ix, exactly-one-of
  user_id/team_id via the item_participants DB CHECK
  (`ck_form_shares_one_subject`), both subject FKs CASCADE, unique
  (form,user)+(form,team), TimestampMixin. Migration `48979a48f5b6` (from
  `4e66edf3f951`; the spurious `ix_doc_pages_fts` drop/create autogen noise
  deleted from both directions). User-merge: `("form_shares", "form_id",
  "user_id")` added to auth `_MERGE_DEDUPE`.
- `PUT /forms/{id}/sharing` (router.py → `service.update_sharing`):
  `form.manage`, delete-then-insert full replace (views idiom). Subject
  validation is the participants-module precedent, all 409: payload dupes;
  users must exist + be active + belong to the form's workspace (instance
  admins pass without a membership row); teams must belong to that workspace.
  `FormRead.shares` (list of `{id, user_id, team_id, created_at}`) is populated
  on the manage surfaces (list/update/sharing) and left empty on the plain
  submit render — subject names hydrate client-side. `form.updated` emitted
  with `share_count` in the payload (`_emit` grew an `extra` dict).
- Portal (`portal.py` + `portal_router.py`, mounted via the module contract;
  forms gained the `teams` dep — teams loads earlier in RADD_MODULES):
  eligibility = enabled AND (allow_public OR share row matching the actor or
  `teams.all_user_team_ids` — a NEW cross-workspace variant of
  `user_team_ids`, since portal eligibility spans workspaces). `GET
  /portal/forms` gates on nothing but a session; `GET /portal/forms/{id}`
  reuses the spec-62 trimming — `render_public_form` was split into
  `public.trimmed_read(form)` + the token wrapper — and returns
  `PortalFormRead` = `PublicFormRead` + `id` + `project {id,key,name}` (the
  authed page needs the project ref for the header chip AND the KB-deflection
  panel's project scope; a deliberate small extension over the spec text).
  `POST /portal/forms/{id}/submit` takes the plain `FormSubmit` shape and runs
  `submit_form` as the SYSTEM actor (deferred `SYSTEM_ACTOR_ID` import, the
  public.py idiom) with `reporter_id=actor.id`; response `PublicSubmitResult`.
  Ineligible/unknown/disabled → one 404.
- Frontend: `RoutePath.portal` (`/portal`, routes/portal.tsx — cards grouped
  by project, key chip + description) and `RoutePath.portalForm`
  (`/portal/forms/$formId`, routes/portal-form.tsx) under the authed app
  layout; sidebar "Portal" entry (ConciergeBell, under My Work, ungated). The
  portal submit page reuses the public page's rendering, which was extracted
  to `components/forms/PublicFormFields.tsx` (`toFieldDef`, `collectValues`,
  `PublicFormFieldList`, `FormDescriptionArea`; public-form.tsx now consumes
  the same pieces) and mounts the authed `DeflectionPanel` under the title.
  Success screen links the created key to `/issues/KEY` (portal-only users who
  click it hit the issue page's error state — accepted). Builder: a "Portal
  sharing" block (`components/forms/FormSharing.tsx`) beside the public-link
  toggle — user/team selects + removable chips, every change PUTs the full
  list; names hydrate from the existing users/teams queries.
- Tests: `tests/test_portal.py` (3) — listing eligibility (public visible to
  any member, team share only inside the team, disabled/unshared excluded,
  project grouping payload), portal submit as a floor-only sharee (no
  item.create; reporter = sharee; ineligible actor 404 on render and submit;
  render carries the project ref), and sharing-PUT validation + full-replace.
  Suite: 755 green.
