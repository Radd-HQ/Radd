<!--
The hand-written half of docs/modules.md. server/scripts/modules_map.py merges it with what the
plugin manifests declare. Edit this file (never docs/modules.md), then regenerate:

    uv --directory server run python scripts/modules_map.py

What server/tests/test_modules_map.py holds this file to:
  * "Modules" has one entry per plugin package, and each is ONE paragraph of at most 750
    characters: what the module owns, the seam other modules use, and one "Trap:" sentence.
    Leave out what the generator prints beside it from the manifest (the description, events,
    atoms, settings, nav, contributions, dependencies).
  * "Preamble" entries print above the module list, "Sections" below it; each is at most
    2,500 characters.
  * No issue keys, and nothing but the present tense: the history is in the tracker,
    docs/specs/ and `git log`.
-->

# Module notes

## Preamble

### Reading this map

Each package under `server/src/radd/modules/` is a plugin: it exposes `plugin: RaddPlugin` (`kernel/plugin.py`), a manifest of everything it contributes, and the kernel (`radd/kernel/`) is only mechanism: the registries, the loader, the specs and the sockets. An entry below opens with the module's kind — **core** cannot be disabled; **optional** (`core=False`) is switched at runtime through `pluginmgr` — then where its UI lives: **bundled** (a core plugin's `ui/` package the host imports at build time, listed in `web/src/plugins/static.generated.ts`), **remote** (an optional plugin's own bundle, built by its `ui/vite.config.mjs` and loaded while the plugin is enabled), **host** (a core module whose screens are in `web/src`) or **none**; `+ contracts` marks a package that only exports types to other packages. Then the manifest's description, one hand-written paragraph, and the declared contributions. The platform's design and every contract: [plugin-platform.md](plugin-platform.md); the frontend half: [plugin-ui.md](plugin-ui.md); writing a plugin: [plugin-development.md](plugin-development.md).

### Assembly

`radd.app:create_app()` resolves the boot set (`pluginmgr/boot.py`: core plugins always, optional ones unless disabled, installable ones once enabled), imports each package's models so the app and Alembic see the same tables (`import_models`), and `load_plugins` checks `api_version` and `depends_on`, then registers every contribution in `registries`. The runtime mounts each plugin's routers under `/api/v1` and starts the plugins in the lifespan; periodic ticks wait until every plugin has started. The manifest refuses a bare value where a tuple is declared (`on_startup=start` must be `(start,)`), and the registry records which plugin contributed what (`ContributionSource`), so disabling a plugin withdraws exactly what it added. Outside the module system: `radd/middleware.py` (`CommitBeforeSendMiddleware` holds a response until the request's session has committed; `text/event-stream` passes through), SPA serving (`_mount_spa` in `app.py`) and the unprefixed `/health`.

## Modules

### events

Owns `events`, the append-only outbox and audit log (never pruned), and `consumer_offsets`. The seam is `events.service.emit`, in the writer's transaction: `subjects={"item": id}` writes the owner's canonical ref; a `has_changes` type needs `changes=` or `emit` raises `ChangesRequired`. Consumers read with `read_after` and `get_offset`/`set_offset`; `runner.run_head_seeded` never replays the backlog. `events.quiet()` marks a bulk import silent. `EventSource` splits the ledger: people, automations (`automated`), system (actor-less or a `MACHINE_SOURCES` account; connectors write as Automation). Trap: skip silent rows in the loop but advance the cursor — filtering in SQL makes an all-silent batch an empty stream and wedges the consumer.

### projects

Owns `projects`: a global container with a unique, immutable `key` (item keys derive from it) and the counter behind `allocate_item_number`. Others call `projects.service` (`get_project`, `get_by_key`) and subscribe to its in-transaction hooks: `project.created` (per-project defaults are seeded there) and the `ProjectHook` pair — `project.inspecting` reports counts and blockers, `project.deleting` removes what the database cannot cascade. Trap: rows hung off a project without an FK cascade need a `project.deleting` subscriber — a field or link type scoped only to the deleted project would otherwise turn global, because no scope rows means every project.

### auth

Owns `users`, `sessions`, `api_tokens`, `roles` and `global_role_grants` (subject × role × scope). The seam is `authz.require(session, user, Permission.X, project=…|space_id=…)`: 403 or the effective set (direct, team and group grants plus the Baseline floor; a key's `scopes` intersect inside it). Routes take `CurrentUser` or, anonymously, `Actor`; logins mint through `create_session`. `principals.BUILTIN_ROWS` (converged at boot) seeds the two principals and the Automation SERVICE account (`SYSTEM_ACTOR_ID`) integrations write as; `require_not_builtin` guards them; `MACHINE_SOURCES` = no person behind the credential. Trap: a new user-id column must be handled by `merge_users` (`_MERGE_REPOINT`), or `tests/test_merge_coverage.py` fails.

### capabilities

Serves `GET /capabilities`, the backend-assembled manifest the SPA renders from: each loaded plugin's evaluated `CapabilitySpec` (with its owning `plugin`), the contributed nav items, the loaded plugin names, the federated remotes with their `ui_api_version`, and the contributed view and widget types. It owns only the `workers` capability and the default `localloop` task backend. Trap: this response is how the SPA learns a plugin is gone — disabling a plugin drops its capabilities, nav, remote and types here, so UI that must disappear with a plugin is keyed on its contribution in this manifest, never hardcoded in the host.

### pluginmgr

Owns `installed_plugins` (each non-core plugin's desired state) and `plugin_processes` (each replica's leased acknowledgement); core plugins have no row. `discovery.py` finds plugins, and each process's `live.py` reconciler applies desired state through `kernel.runtime.PluginRuntime`, so a toggle needs no restart. Enabling moves the plugin's `ConsumerResume.HEAD` consumers to the stream head in the same transaction; disabling refuses while a loaded plugin depends on it; uninstall runs `sweep_plugin_atoms`, stripping its declared atoms from roles and token scopes. Trap: uninstall refuses until every live process has acknowledged the disabled state — a plugin still mounted in one replica is still running.

### settings

Owns the scalar cascade: `scoped_settings` rows (scope `instance` or `project`) over a default from `config.Settings`. It declares no keys; each is a `SettingSpec` on the manifest of the module that reads it (type, allowed `scopes`, optional `choices`). The seam is `settings.service.resolve(session, key, project_id=…)`: the project override, else the instance override, else the default, looking only at the spec's scopes. Writes go through `set_value`/`clear_value` (a scope or value the spec refuses is a 409) and emit `setting.changed`. Trap: `SettingKey` in `settings/types.py` must name exactly the registered keys — `tests/test_setting_ownership.py` fails when the enum and the registry disagree.

### groups

Owns the read-only mirror of directory groups: `groups`, `group_parents` (the nesting graph) and `group_members`, written only by the `ldap` sync. A group is never local; a team is never mirrored. Two closures: `user_group_ids` (a user's groups plus every ancestor, memoised) and `group_user_ids` (everyone a grant on the group reaches); the SLQ fields and the membership gate take a name, a DN or an id. Both walks guard against cycles and stop at `group_nesting_max_depth`, failing closed; groups are subjects on both grant tables, so every permission path inherits nesting. Trap: a group whose DN stops resolving is flagged missing and keeps its members and grants — a directory outage must never become a permission outage.

### teams

Owns `teams` (unique names, an `owner_id`), `team_managers` and `team_members`, where a member is a user or a directory group; a team's access to a project is a role grant in `global_role_grants`, not a column here. The seam is `user_team_ids` (the teams a person is on, directly or through any group transitively) and `users_for_teams` (groups expanded); every membership query goes through `_membership_filter`, and the SLQ fields `reporter_team`/`assignee_team` through `reading.member_projection`. The owner or a manager may run a team (`is_team_steward`). Trap: `user_team_ids` is memoised on `session.info`, so a write to `team_members` must call `forget_user_teams`, or the request keeps the membership it read before the write.

### access

Owns `access_grants`: a resource (`resource_type`, a string `resource_id`), a subject (user, team, role or group), an access, a scope (`project_id`, NULL = global) and an allow or deny `effect`. A module makes a resource protectable by declaring a `ResourceSpec` (`access/registry.py`) in its manifest's `access_resources`; the generic `/grants` API and `AccessGrantsEditor` then serve it unchanged. Every decision goes through the pure `access/resolution.py` (`has_access`, `effective_level`): specificity first, deny on ties. Trap: resolution has no admin bypass — an operator who sees through grants is a named short-circuit at the caller, never a branch in the algebra.

### workflow

Owns per-project `states` and the optional `workflow_transitions` graph; each state is filed under a `state_categories` row whose `behaves_as` is copied onto `states.category`, so category consumers read one column. The seam is `workflow.service`: `check_transition` (items calls it after a patch applies, on a real state change, for every actor, automations included), `state_moved` (tells `TRANSITION_CHECK` providers) and `release_transitions` (the `on_release` rows the releases sweep performs). The first row whose `applies_when` the item satisfies governs alone. Trap: a stored rule whose check no loaded plugin provides fails closed (`guards.unprovided_failure`), so disabling a plugin blocks those moves instead of opening them.

### labels

Owns the instance-wide `labels` catalog (names unique across the instance); issues hold theirs in `item_labels`, which cascades when a label is deleted. The seam is `labels.service.resolve_labels`, which maps names to labels and creates unknown ones, so items, pages and automations can write labels freely; `labels_by_ids` and `label_by_name` serve readers. Trap: deleting a label detaches it from every issue without counting them first, because counting would mean reading another module's tables; whoever needs that detail subscribes to the emitted event.

### fields

Owns `field_definitions` (typed custom fields with options and `default_value`) and their scope in `field_definition_projects`: no rows means global. Values live inline on the issue in `work_items.custom_fields`. The seam is `fields.service.definitions_for_project`, the one place any consumer resolves which fields apply to a project; `readable_keys`, `writable_check` and `readonly_field_keys` resolve grants through the `access` module. Trap: `update_field` never touches `options`, because a renamed option leaves every stored value, saved view and automation naming the old string matching nothing; add with `extend_options`, remove with `remove_option`, which rewrites stored values through the items service.

### cycles

Owns `cycles` (one cycle holds issues from any project; its optional home `project_id` is not a scope), `cycle_teams` (no rows = visible to everyone), `cycle_series` and `item_cycle_records` (one row per stint). Status is derived by the pure `types.cycle_status`, never stored. The seam is `cycles.service`: `record_cycle_change` (items calls it on every cycle assignment change), `cycle_visible_to`, and `complete_cycle`, which moves open issues through `items.move_open_cycle_items` as the caller so authz and events apply. Trap: cycle stats span every project unless the caller passes `project_id`; a project-scoped surface that omits it shows other projects' time and points.

### releases

Owns `releases`, project-scoped versions, planned or released. Shipping is a workflow fact: transitions marked `on_release` name where finished work waits (a done-category state) and where it ships. The seam is `releases.pipeline`: every write path (REST, MCP, the publish node, `vcs/policies.py` through `on_release_published`) goes through `create_release`/`update_release`, and a version that becomes released sweeps every waiting issue into the shipped state with `release_id` set in the same patch, so a guard requiring a release passes. Trap: re-saving an already-released version does not sweep again; work that reached the waiting state later needs `POST /releases/{id}/sweep`.

### itemtypes

Owns `issue_types`, the per-project classification axis (Bug, Task, Story…), orthogonal to the `ItemKind` hierarchy. Each project has one `is_default` type, seeded from `DEFAULT_TYPES` on `project.created`, and a type may carry a `description_template` the issue-creation form prefills. The seam is `itemtypes.service`: `default_type` (items, forms and bulk move resolve an omitted type through it) and `ids_by_names` behind SLQ's `type` field. Trap: "bugs" means `type = Bug`, never `kind`, which is the hierarchy level and has a fixed vocabulary.

### screens

Owns `screens` and `screen_fields`: per project, optionally per issue type, whether each optional builtin and each custom field (`cf:<key>`) shows as primary, secondary (collapsed) or hidden. Presentation only: never validation, storage or permissions. The seam is `screens.service.resolve_effective`: the issue type's screen, else the project's default screen, else built-in defaults (builtins primary, custom fields secondary). Trap: a field the stored config omits keeps its default placement, so a custom field created after the screen's last save still appears, collapsed, rather than vanishing.

### linktypes

Owns the link-type catalog `item_link_types` (outward and inward names, directed or symmetric, `system`, `auto_managed`) and its project scope in `item_link_type_projects` (no rows = global); `ensure_builtins` seeds blocks, relates, duplicates and mentions at startup. The seam is `linktypes.service`: `catalog` and `is_symmetric` (items validates every `ItemLink.link_type` key against them) and `types_for_project` for the manual picker. Trap: `mentions` is auto-managed, derived by items from issue-key references in the title and description, so a manual link of that type is refused, and no type can be deleted while links use it.

### items

Owns `work_items` (keys, the `kind` ladder, `rank`), `item_links`, `item_labels`, `item_key_aliases` and the SLQ compiler in `items/slq/`. The seam is the `items.service` barrel: `require_readable_item` gates every child surface (a hidden issue 404s), `relation_read_clause` filters lists, and `update_item` is the shared write path, then `workflow.check_transition`. An issue's epic may sit in any project; a subtask lives in its parent's. A typed full key names ITS project; a bare number means the source item's own. `create_item` dispatches `ItemHook.CREATING` before `item.created`, so a handler may refuse. Trap: `items/history.py:RELATED_EVENT_TYPES` names other modules' events by wire string; list History events there.

### comments

Owns `comments` on any parent registered in `comments/parents.py` (issues built in, pages by pages; a comment is never more visible than its parent), one-level replies, `comment_visibility_teams` and `thread_resolution_rules`. The seams: `reading.audience` is the one visibility clause for roots, replies and counts; `visibility.internal_comment_visible` is the pure gate notify and issue History apply; `comment_counts` feeds item hydration; `has_unresolved_threads` answers workflow's resolved-threads check. Trap: every comment event carries a body excerpt, internal comments included; only the webhook egress withholds it, so any other consumer leaving the instance must filter `visibility` itself.

### weblinks

Owns `item_web_links`: URLs related to an issue (documents, designs, specs), each with a `WebLinkCategory`. Every write, REST or MCP, gates through the items seam (`require_readable_item`, then `item.update` on that issue), and every event carries `item_id`, which is how the issue's History feed and the realtime hub (a web link is a record-local entity) pick links up without items importing this module. Trap: History lists `weblink.*` by wire string in `items/history.py:RELATED_EVENT_TYPES`, so renaming an event type here silently drops links from History.

### webhooks

Owns `webhook_endpoints` (secret encrypted at rest) and the `webhook_deliveries` log. The dispatcher is an offset consumer: `service.fanout_events` turns each non-silent event into a pending delivery per matching endpoint, and `service.attempt_due` posts Standard-Webhooks-signed bodies on the `webhook_retry_schedule` back-off until a delivery is dead. Outbound payloads redact read-restricted fields (`fields.service.outbound_restricted_keys`) and withhold internal-comment excerpts, because an endpoint belongs to no team. Trap: deliveries have no cascade from their endpoint, so `service.delete_endpoint` clears the log explicitly; anything else that removes endpoints must do the same.

### views

Owns `views` (a saved definition: SLQ `query`, axes and the shared shape such as `columns` and `card_layout`), `view_members` (items pinned by hand, read through the `roadmap` SLQ field) and `card_layout_presets`. Every work surface is a view; the epic board (`/e/KEY/board`) is a synthetic one, no row. Visibility is owner, access grants on resource `view`, or `global_access`; anyone else gets a 404, admins included. `ViewRead.query_string` is the ready-made `GET /items?` composition, and other modules check a reference with `service.visible_view`. Trap: shared-shape fields keep unknown keys on purpose so a departed state or field degrades, while column widths and page size are per-browser — never put a personal preference on the view row.

### reporting

Owns no tables: every report is recomputed per request from the event log, with `reporting/timeline.py` rebuilding each item's state and cycle history from its `item.*` payloads. A plugin's own report folds the same way through the public `service.bucket_starts`, `service.matching_ids` (the reader's item universe, the optional SLQ `q` intersected on top) and `service.report_scope`; the slas report uses these. The bundled UI package exports the chart kit and `REPORT_SECTION_SLOT` for plugin report sections. Trap: SLQ evaluates an item's CURRENT state, and `matching_ids` must run even when `q` is absent, or a cross-project figure folds projects the reader cannot see.

### forms

Owns `forms` (fields over the project's registry, `defaults` resolved by NAME at submit) and `form_shares` (portal grants). `service.submit_form` is the one path to an item, through `automations.intake.create_or_refuse`, so intake validation governs every form. The portal (`forms/portal.py`) admits by `allow_public` or a share and submits as the SYSTEM actor with the visitor as reporter; `forms/requests.py` admits a requester by relationship (`visible_condition`), never `item.read`, and answers 404 rather than 403. Trap: a requester's rows are trimmed in the QUERY — even the comment count sees public comments only, because a count over everything leaks that internal discussion exists.

### automations

Owns `automations` (a graph in `nodes`/`edges`), the `automation_triggers` index rebuilt on every write, `automation_versions` (every version, the current one included), `automation_runs` and the validation and scheduling state. `graph.py` is pure structure and validation; `executor.py` gives nodes meaning, each action in its own savepoint; every run goes through `engine.run_graph`. Every node, trigger kind and template, the built-ins included, is a kernel contribution. Trap: every applied mutation runs inside `events.automated()`, and an automated event reaches only triggers that opted into chaining, never its own automation, never past `automation_max_chain_depth` — emitting outside that context defeats the loop guard.

### timelogging

Owns `worklogs` (booked to a `worked_on` date; itemless ones need a category), `item_estimates` (remaining is derived, never stored), `work_categories` and `project_timelogging` (no row means logging is off). Durations parse and format only in `duration.py`, with one instance-wide hours-per-day factor. Others read through `logged_seconds_by_items`/`estimate_seconds_by_items`, the worklog SLQ dialect in `timelogging/slq/`, and `external.reconcile_external_worklogs`, which the VCS time mirror uses. Trap: `service.authorize_mutation` refuses to edit or delete a mirrored row (non-empty `external_source`), admins included — it is corrected where it was logged, and the refusal lives in the service so MCP agrees.

### vcs

Owns `item_vcs_links` (one row per ref per item per connection), the author identity map `vcs_user_links` and time entries parked for want of an author (`vcs_pending_worklogs`). Every code-host connector shares its shape: a receiver that authenticates, calls `receiving.claim_delivery`, then `receiving.link_planned` and fires one trigger per linked issue (`fire_ref_action`/`fire_push`/`fire_ci`), and a backfill inside `events.quiet()`. Seams: `service.upsert_vcs_link` (the only link write) and `timemirror.reconcile` (time entries become worklogs through `timelogging.external`). Trap: an external id not spelled by `vcs/ids.py` creates a twin row the unique index cannot catch, and CI stamps land on neither.

### audit

Owns no tables: a read-only projection of the event log through `events.query_events`, labelled from the registries (`GET /audit/catalog` is the SPA's vocabulary). `service.require_audit_scope` is the one gate for the ledger, `GET /audit/access` and the MCP tool: an instance admin reads the instance; anyone else names a project they hold `project.manage` on, item diffs redacted through `items.history.redaction_for`. `audited=False` event types stay hidden unless asked for. `AuditActor.machine` marks a service account or principal: a system row, no avatar. Trap: an entry links to its entity only through the OWNER's `EntityLinkSpec` (`kernel/entity_links.py` refuses a foreign one): a link for another module's entity goes on that manifest.

### backup

The engine lives in `radd/backup/` (with the `python -m radd.backup` CLI) and imports no FastAPI, plugin registry or ORM model, because a recovery restores onto an empty database where none can load. This module owns only `backup_schedules`, `backup_runs`, an instance-admin-only API and a nightly schedule seeded on first boot. An artifact is a plaintext manifest header, so listing needs no key, then an AES-256-GCM chunked payload. A restore takes a safety backup, engages maintenance mode, runs `alembic upgrade head` and rolls back on failure. Trap: artifacts are deliberately NOT a table — a restore rewrites the database and would roll its own inventory back; the backup directory is the inventory.

### notify

Owns `item_watchers`, the per-person `notifications` rows (`inbox`/`email` stamped at write, `delivery` settled by the mail loops) and `notification_rules`, sparse per-scope `{kind: channel}` maps. The consumer (`notify/consumer.py`) plans each event purely, picks the channel with the pure `rules.resolve` (the most specific scope with an opinion wins), then checks each recipient may read that row, so following never widens access. `service.create_notification` is the one write seam for every producer; `service.add_watchers` makes someone follow an issue. Pages, participant teams and mail reach notify only through sockets. Trap: mark-read touches inbox rows only, because the mailer skips read rows and an email-only row can never be opened.

### realtime

Owns no tables. `GET /api/v1/ws` authenticates by session cookie. `broadcaster.py` tails the outbox from the stream head with an in-memory cursor — not an offset consumer, so a reconnecting client refetches instead of replaying — and pushes payload-free `{entity, event_type}` frames. Notification frames go only to their recipient (`hub.should_deliver`); every other frame reaches every signed-in connection, safe because frames carry no data and every refetched endpoint is RBAC'd. The SPA's `lib/realtime.ts` maps entity types to cache tags and calls `invalidateEntities`. Trap: a query without `meta.entities` is never subscribed, so nothing refreshes it — check the query's meta before the hub.

### search

Owns `search_index` (one row per item: key, title, description, PUBLIC comment text, `tsv`, plus relation and `visibility` mirrors), written only by the `search.indexer` consumer; replaying the stream is the index build. `service.search` fuses ranked full-text by RRF with candidates from the `SEMANTIC_CANDIDATES` socket inside a time budget, full-text only on failure; documents arrive through `SEARCH_DOCUMENTS`, so search imports neither pages nor ai. Reads pass the same relations and row guard as `GET /items`. Trap: where a read-restricting grant covers `description` in a project, the indexer blanks that project's descriptions for everyone, since index text is one per row.

### attachments

Owns polymorphic `attachments` (an `(entity_type, entity_id)` parent), `storage_hosts` and `storage_rules`, an ordered routing chain whose first answering rule wins and whose end is the default host. A module makes its rows attachable with `parents.register_parent`; cleanup of rows, grants and bytes derives from those bindings (`gc.py`). Every download goes through `service.download_response` after `acl.attachment_readable`; only non-SVG images render inline. Importers use the blob API (`service.save_blob`/`read_blob`/`remove_blob`). Trap: the parent type is a wire value the SPA mirrors in `web/src/lib/types/attachments.ts`; a mismatch compiles on both sides and 422s every upload.

### avatars

Owns only the bytes of a profile picture: uploads are normalised to a 256px square WebP and stored through the attachments blob API (`save_blob`, `read_blob`, `remove_blob`). `auth` owns the columns and the one rule, `User.avatar_url` (uploaded picture, else the identity provider's, else none), which every user shape carries; `sso` records the provider's picture through `auth.service.set_idp_picture`. `GET /users/{id}/avatar` serves anyone who can read a name, cached as immutable because the URL carries a version. Trap: an avatar is deliberately not an attachment (no listing, no per-file grants, no storage-host prompt), so never route it through the attachment parent bindings.

### canned

Owns `canned_responses`: one instance-wide list. A body may carry the fixed `CannedToken` variables, resolved against an item the caller can read by `GET /canned-responses/{id}/render` through the pure `render.render_canned`, the same `{{token}}` idiom as automation templating; the comment composer inserts through it. The list needs the revocable `canned.read` atom and answers an empty list without it. Trap: an unknown token, or one with no value (an unassigned item's assignee name), renders verbatim by design so it stays visible in the composer — never turn a missing value into an empty string or an error.

### slas

Owns `sla_policies` (per project, ordered by `position`) and `sla_item_states`, which make each breach and due-soon event fire once. One policy governs an item: the pure `service.first_match` takes the first enabled policy whose filters all match, and the engine, chips and queue all resolve through `service.matched_policies`. Timer math is pure (`timers.py`); non-working dates come from the non-working-days socket (`calendar.non_working_dates`). The engine (`engine.py`) is a clock, not an outbox consumer: a breach happens when nothing changes. Trap: a reply counts by comment origin, not author (`metrules.NOT_A_RESPONSE`): inbound mail and automation comments never meet a reply target.

### gitlab

GitLab does not sign bodies: the hook echoes its secret as `X-Gitlab-Token`, compared constant-time by `service.verify_token`. A merge request's trigger follows the delivery's `action`, never its `state`, which every later edit of a merged request repeats (`parsing.mr_action`). Time has no webhook: a delivery whose `total_time_spent` changed makes `timelogs.reconcile_merge_request` read the GraphQL timelogs, and only an admin's token reveals authors' emails. Trap: GitLab removes time by appending a NEGATIVE timelog, so `timelogs.net_entries` folds removals in creation (gid) order; sorting by `spentAt` lets a reset eat entries logged after it.

### sso

Owns `sso_providers`, `user_identities` (provider + immutable subject to user) and the provisioning rules. A kind (Google, GitHub, generic OIDC) supplies only endpoints and a profile strategy (`types.KIND_DEFAULTS`); all run one state + PKCE engine with one callback, so `service.provision` is kind-blind. The first login links an existing account by verified email and pins the subject; later logins match the subject alone. The signup allowlist gates creation only (empty = no signups). Trap: role sync runs only when `admin_groups` is set; a provider without a group opinion must not touch `instance_role`, or a Google login demotes the directory admin it just linked.

### ldap

Sign-in is a direct bind with the person's own password, so no stored account is needed to log in; the optional bind account enables directory search, imports and the periodic syncs (`directory_sync_state`). The connection is five instance settings defaulting to `RADD_LDAP_*`, resolved by `service.refresh_conn` at every session-bearing boundary, so an edit needs no restart. `groupsync.reconcile_group` replaces a mirrored group's members with AD's transitive answer. Trap: `groups.get_group` answers None only for a genuinely missing DN and raises `DirectoryUnreachable` otherwise; reading an outage or a renamed group as empty would revoke every grant that group carries.

### pages

Owns `page_spaces`, the `pages` tree (keyed by id, permalinked by `number`, addressed by a derived `<space>/<slug>/…` path that `pages/paths.py` resolves, `page_path_history` catching old addresses) and `page_versions`. A space is a grant scope; a page restriction only narrows it, and every restriction on the ancestor path must pass. The seam: `page_access.guard_page` is the one per-page gate for REST, MCP and the comment and attachment bindings; `pages/hooks.py` (`PageHook`) lets `collab` refuse or vouch for a body write. Trap: a list surface (tree, FTS, label index) filters through `page_access.readable_page_ids` and constrains to readable spaces BEFORE its limit, because a hit's title and snippet are the content.

### collab

Holds one pycrdt document per page in this process (so one app replica, `docs/deploy.md`), persisted to `page_collab_docs` and resumed only when its version tag matches the page: the markdown is the truth. `POST /collab/pages/{id}/join` gates through `page_access.guard_page`; `collab/channel.py` drops an observer's document frames. The seam is `pages/hooks.py`: `collab/guard.py` refuses a body write while an editor is connected unless it carries that editor's `collab_session` (which vouches it past `expected_version`), and resets the room when anything else wrote the body. Trap: a hook subscription cannot unregister, so every handler asks `guard.is_enabled()`, or a hot-disabled plugin keeps guarding.

### ai

Owns the provider registry (`ai_providers`, `ai_model_roles`, `ai_preset_prompts`) and a pgvector store outside `Base.metadata` (`embeddings/service.py`, one partial HNSW index per active model, fed by `ai.embedder`). Callers use `ai/client.py` (`complete`, `complete_structured`, `complete_choice`, `embed`, `stream`) behind `features.feature_enabled`, which is False once the plugin is disabled. Model-bound text passes through `prose.prose`, and `provider.finish_payload` merges an admin's `request_params` last. Trap: `features.FEATURE_ROLE` and `FEATURE_SETTING` are total over `AiFeature`; a feature missing either entry, its `SettingKey`, config default or `SettingSpec` breaks `GET /ai/status`, which gates every AI affordance.

### mcp

No tables. `POST /mcp` is a hand-rolled JSON-RPC 2.0 server authenticated by the ordinary token or session, so every tool runs through its owner's service and authz seams. Tools are `McpToolSpec`s their owner modules contribute; `requirements.visible_catalog` hides what the caller cannot run and rewrites the project parameter to an enum of permitted keys, and `tools.call_tool` validates arguments against the schema tools/list advertises. Domain errors answer `isError: true` after a rollback; anything else is -32603, never HTTP 500. Trap: hiding is presentation, not enforcement; a builtin declared `kernel_enforced=False` must still call `authz.require` in its own seam.

### forgejo

Also serves Gitea. Deliveries carry a hex HMAC-SHA256 of the raw body in `X-Forgejo-Signature` or `X-Gitea-Signature` (`service.verify_signature`). Forgejo tracks time on a pull request but has no time webhook and no total on the payload, so with a token and `mirror_time` on, every `pull_request` delivery re-reads the pull request's tracked times through `timelogs.py` and reconciles. Trap: a tracked-time entry has only a `created` timestamp, so a mirrored worklog is dated the UTC day the time was recorded, not the day the work was done.

### github

Deliveries are verified from `X-Hub-Signature-256` (`service.verify_signature`); CI events stamp state, and only a `published` release fires the release trigger. GitHub has no time tracking, so time rides pull-request comments: `spend.py` parses `/spend` lines and `timelogs.py` keys each entry by comment id and line, so editing a comment updates its entries and deleting it removes them. Trap: GitHub pairs an email with a login only in push commit authors (`timelogs.record_commit_authors` fills the identity map from them), so `/spend` time from someone who has not pushed parks as unmatched until an admin maps the login.

### alertmanager

Owns `alertmanager_receivers` (a token, a project, and behaviours off by default) and `alert_items`, which deduplicates by receiver and fingerprint, never across receivers. A delivery's receiver is found by token (`service.receiver_for_token`, constant-time over every active row); `service.process` locks that row, plans with the pure `planner.plan_alerts`, creates issues as the system actor and fires the firing, repeated or resolved trigger per alert. Trap: issue creation runs inside `automations.intake.suppressed()`; a required validation check refusing machine intake answers Alertmanager with a 5xx it retries forever.

### mailintake

Owns `mail_sources` (each with an ordered `mail_rules` routing chain), `mail_senders`, `mail_messages` (every Message-ID in and out, for dedup and threading) and `mail_contacts` (a ticket's external addresses, one primary). `intake.accept` is the path every inbound transport calls. Everything that mails a person goes through `service.send_item_mail`/`send_plain_mail`, which picks the sender bound to the item's origin mailbox, records the Message-ID the relay reports and emits `mail.sent`/`mail.failed`; notify reaches it only through the mail-transport socket. Trap: the relay (`outbound.should_reply`) decides by comment origin, not author: only `inbound_mail` is never echoed back.

### csat

Owns `csat_surveys`: one survey per item for its lifetime, keyed by a token that is the requester's only credential on the unauthenticated `/public/csat/{token}` routes. The sender (`sender.py`) runs head-seeded and commits the survey row before mailing (at most once), surveys an item entering done when `csat_enabled` holds for its project, and sends through mailintake's `send_item_mail`. `service.announces_resolution` tells mailintake to skip its own resolution notice; `report.responded_rows` feeds the SLA report. Trap: the emailed `?rating=N` links only preselect a star; the page must POST, so a mail scanner prefetching them never records a vote.

### approvals

Owns `approval_requests` (approver entries snapshotted; one live request per item and target state) and `approval_votes`. `gate.py::ApprovalGate` is the `require_approval` check on workflow's transition-check socket: it passes on `service.approved_target_state_ids`, and `service.consume` (reached through `workflow.service.state_moved`) spends the approval, so one approval unlocks one move. The deciding vote applies the move as the final approver; if another guard refuses, the unlock stays banked. Trap: a team entry counts the team's CURRENT members, so a team shrunk below `required`, or deleted, leaves the entry unsatisfiable; with the plugin disabled workflow fails approval rules closed.

### participants

Owns `item_participants` (a user or a whole team per row, never both) and registers `participant` as a relation on the item resource, so the Baseline's `item.read@participant` lets someone shared into one issue open it, discuss it and be notified, nothing wider. A direct user participant is auto-watched (`notify.service.add_watchers`); a team row stays live, its CURRENT members joining the audience at fan-out time (`audience.py`). Sharing is gated by `participant.manage`. Trap: leaving is an identity operation: `service.remove_participant` lets a person remove themselves without the readability gate, so self-leave must not go through `require_readable_item`.

### scripts

Owns `script_packages` (name and version specifiers only) and the one-row `script_interpreter`; `interpreter.py` builds one uv venv per instance under `RADD_SCRIPTS_DIR`. A script's body lives on its automation node (`params.body`, defining `main(ctx)`), so the automation's versions are its history. `service.run_body` runs one body out of process through `runner.run`, with a minimal environment and a timeout, and `ctx.client` calls back with a short-lived key `auth.service_tokens.mint_ephemeral_token` mints for the automation's actor. Trap: that key is minted and discarded in its own session, never the caller's transaction — the child's API calls arrive on another connection and must see it committed.

### dashboards

Owns `dashboards` and `dashboard_widgets` and nothing about the data they show: every widget fetches through the ordinary read APIs at render time, so RBAC is inherited, never reimplemented. On write, `widgets.py` checks each config's references against the WRITER. Sharing is the access framework (resource `dashboard`) plus `global_access`; an invisible dashboard is a 404, admins included. My Work stores the same widget definitions per person (`dashboards/personal.py`): its own kinds plus every personal `WidgetTypeSpec` a registered plugin contributes. Trap: a saved My Work widget whose plugin is off keeps its place and only a NEW widget of an unregistered type is refused — never fail the whole save.

### jiraimport

Owns connections, a snapshot (a JQL result downloaded once into `jira_snapshots`/`jira_snapshot_issues`; every later step reads the cache), `jira_plans` (nine editable mapping tables), `jira_runs`, and the ledger `jira_import_records` that `rollback.py` replays in reverse, sparing anything edited since. Fields are identified by Jira's `schema.custom` key (`schemakeys.find_by_schema_key`), never a `customfield_*` id. `runs.py` is one pipeline with a `commit` flag, so a dry run and an import cannot disagree. Trap: a run is `events.quiet` by default and creates items inside `automations.intake.suppressed()`; an import is history, not intake, and anything a run writes must honour both.

### confluenceimport

Server and Data Center only (storage-format XHTML bodies). It keeps the jiraimport shape: a snapshot downloaded once, a plan, dry run and import sharing one `commit` flag inside `events.quiet`, and a `confluence_import_records` ledger for rollback. `storage/` is a pure converter re-run over the cache whenever a mapping changes; an unmapped macro becomes a `radd:unsupported-macro` block, never stripped. Revisions go through `pages.service.write_version`. Trap: `restrictions.py` maps a restriction to the same mirrored AD group, and a principal that resolves to nothing with no fallback fails its page instead of importing it open.

### monitoring

Owns no tables. `GET /monitoring/overview` (instance admins) answers database health, APPROXIMATE entity counts from `pg_stat_user_tables`, and every background consumer's lag through the public `events.service.consumer_status`, plus `workers_in_process` so idle workers on a web-only replica read correctly. The settings page renders a `settings.section` slot matched on `monitoring`, where mailintake and ai add their health cards, so monitoring depends on neither. Trap: a new count must stay a catalog estimate — querying another module's table breaks the module boundary and costs seconds on a large instance.

### leave

Owns `leave_periods`: one subject per row (`user_id` or `team_id`) — a person's leave, or a team HOLIDAY expanded to its CURRENT members at read time. Days are the subject's own dates; `start_time`/`end_time` narrow a boundary day in the row's `timezone`, and `service.current(now)` judges each row in its zone. Everyone records their own leave, a steward covers members (`/leave/teams/{id}`, the profile's Team leave section), only admins manage holidays, always whole days. Other modules reach leave only through its two date-granular sockets. Trap: `NON_WORKING_DAYS` answers from holidays only, instance-wide; `PERSON_AVAILABILITY` answers per person — never answer one with the other's data.

### milestones

The plugin platform's worked example, off on a fresh instance: one `EntitySpec` in `milestones/spec.py`, from which the kernel builds the table, a permission-guarded CRUD router, the `milestone.*` events and atoms, a `#`-mention search and the audit link. It imports only `radd.sdk`, which makes it the reference for an external plugin: `milestones/mcptool.py` for an MCP tool, `milestones/automation.py` for an action node, `milestones/ui` for a remote page. Trap: the generated read gate admits a row only through `item.read` held with `@any` or through a relation the entity registers — a reader narrowed to `item.read@own` sees no milestones.

## Sections

### Connection rules

- A module reaches another only through its public service functions (`service.py`, or the barrel `__init__` of a `service/` package, which re-exports only the public surface; `items/service/` is the reference), the events it emits, and declared extension points. The spine exception and the declared-import rule are CLAUDE.md rule 1, enforced by `tests/test_module_contracts.py`.
- A core module never reaches an optional plugin: it reads a socket (above), dispatches a hook, or iterates a contributed spec. A runtime check is `"<plugin id>" in registries.plugins`, never `except ImportError` or `settings.modules`, neither of which sees a runtime disable.
- Every domain mutation calls `events.service.emit` in the same transaction (the outbox guarantee), with a type declared as an `EventTypeSpec`. A consumer that delivers outside the instance (mail, a survey) runs on `events.runner.run_head_seeded` and declares `ConsumerResume.HEAD`: it never replays the backlog, and it commits its cursor before delivering, so a message is dropped rather than duplicated.
- In-transaction hooks (`radd/hooks.py`: `@hooks.on(...)`, `hooks.dispatch`) are for reactions that must commit or fail with their trigger — workflow seeds a project's states on `project.created`, collab vouches for page body writes. Everything else is an outbox consumer, which runs after commit.
- Permission checks go through `auth.authz.require` and are never re-implemented. A module declares the atoms it enforces (`PermissionSpec`/`CrudResourceSpec`) and the scalar settings it reads (`SettingSpec`) on its own manifest, plus the typed alias (`auth.types.Permission`, `settings.types.SettingKey`); `tests/test_permission_ownership.py` and `tests/test_setting_ownership.py` fail when the two disagree.
- Custom fields serialize inline on the entity in every representation, never through a side-channel endpoint; the `fields` registry is the one source of dynamic schema.
- An import that would cycle at module scope moves into the function body with a `# deferred:` comment, and its target is declared in `weak_depends`.

### Socket policies

Every kernel socket declares a `SocketPolicy` in `kernel/sockets.py::SOCKET_POLICIES`, and the Sockets table above prints it. **Fails closed** means the reader refuses what it holds for the socket when no provider is live: a stored transition rule blocks the move, a storage host whose type has no backend cannot be opened, no periodic loop runs without a task backend, a notification subject nobody vouches for notifies nobody and its queued rows stop mailing, and queued email is recorded undeliverable. **Fails open** means the reader proceeds with the empty answer: no date is non-working, nobody is away, a stored routing rule of a withdrawn type falls through, search shows issues alone, and an item's audience is its watchers. A **single-provider** socket (`single=True`; the mail transport) admits one plugin: `registries.register_plugin` raises `ContributionConflict` naming both plugins, which the plugin manager shows on the row of the plugin being enabled, and `sockets.single_provider` raises `AmbiguousProvider` rather than taking the first of two. The same conflict is raised for two plugins on one `(socket, name)` key of any socket; the registry never overwrites a provider. A socket a plugin defines for itself (the vcs connector tabs) has no row and reads as fail-open, multi-provider.

### Relations and row guards

An atom may carry a relation qualifier, `resource.action@relation`; an unqualified atom means `@any`, and relations close downward along any ⊃ team ⊃ own (`assigned` and `participant` sit off the chain). A plugin declares what a relation means for its rows with a `RelationSpec` on its manifest, supplying both `where` (the SQL form that keeps lists, counts and search honest) and `holds` (the check on a loaded row); a pair that disagrees is a silent leak. A `RowGuardSpec` is a per-row admission every reader passes whatever relation they hold: items admit restricted issues only to `own`, `assigned` and `participant`, so `@any` does not mean every row. `authz.relation_filter` is the filtering form (it fails closed with `false()` when nothing is held) and `authz.relation_holds_row` the gating form; `RelationActor.unrestricted` (the instance admin) is the one bypass. Membership tests use `authz.holds_base`, because a raw `atom in perms` misses relation-qualified holders. The normative table: [relations semantics](specs/115-relations-semantics.md).

### Event diffs and subjects

`kernel/changes.py` is the one diff shape — `{field, from, to}`, `{field, added, removed}` through `collection_change`, and `{field}` through `hidden_change` for secrets and bodies — resolved to display names when written, so the record outlives renames. A type declaring `has_changes=True` must be emitted with `changes=` (`[]` when nothing visible changed), or `emit` raises `ChangesRequired`; `tests/test_event_changes.py` holds every registered `*.updated` type to it. `EventTypeSpec.subjects` names what an event is about, and the loader refuses a plugin whose event or action node names a subject no loaded plugin describes with an `EntityRefSpec`.

### Configuration is rows; the environment only seeds

Connection and provider configuration lives in rows edited in Settings: `sso_providers`, the code-host connections, Alertmanager receivers, and the Jira and Confluence connections. The matching `RADD_*` environment variables only seed one row at startup: the code-host connectors and Alertmanager record the seed in a marker table (`vcs_seeds`, `alertmanager_seed`) so it happens once ever, while `sso`, `jiraimport` and `confluenceimport` seed whenever their table is empty. Credentials are write-only: reads carry `has_*` flags, and an empty value on update keeps the stored one. Every replayed credential — importer credentials, the SSO client secret, secret settings such as the LDAP bind password, AI provider keys, storage host keys, code-host tokens and webhook secrets, mail passwords and ingest secrets, Alertmanager tokens, webhook signing secrets and TOTP seeds — is `radd.secretbox` ciphertext at rest under a key derived from the backup key: sealed on write, decrypted at its one point of use, adopted from legacy plaintext by the owner's startup sweep (which logs and skips without a usable key), and recorded in the audit ledger only as "changed" (each owner's `SECRET_FIELDS`). `ldap` differs: `RADD_LDAP_*` is the default of instance settings the Directory page overrides. Two active code-host connections may not share a webhook secret (`vcs/setup.py::require_distinct_secret`, compared on the decrypted values).

### Page links

A page is keyed by id and addressed by path. The SPA assembles a page URL in exactly one place, `pages/ui/src/links.ts` (`pageLink`, `pagePermalink`, `pageHref`, `pagePrintHref`), which the host, the palette and the issue surfaces import through `@radd-plugin-ui/pages/links`; a plugin that may not import it links by the permalink `/pages?pageId=<number>`. Server-built links (mail, notification payloads) use the permalink too, through `mailrender.page_url`, so a rename or a move never breaks a link someone already holds.

### What reaches a model

Only prose reaches a language model: every prompt and every embedded text read a markdown body through `ai/prose.py::prose`, which drops images (keeping the alt text), data URIs, HTML tags, bare URLs and `radd:*` fences and keeps code. An editor transform masks every `radd:*` fence, image and attachment link behind a `⟦keep-N⟧` placeholder before the run and restores it after (`ai/ui/src/editor/protect.ts`; the server's `editor.PROTECTED_PLACEHOLDER_RULE` states the token), so a reply can move a block but never delete it.

### Field grants

Field visibility rides the `access` framework: grants are `access_grants` rows on resource type `field` (the definition's id) or `builtin_field` (the field name), to a user, team, role or directory group, global or per project, with the accesses `read` and `write`; write implies read, and a deny beats an allow at equal scope. `fields/service.py` resolves them through `access/resolution.py` against the actor's `FieldAccessContext`. With no grant for an access it is open: read to anyone holding `item.read`, write to anyone holding `item.update`. Once read grants exist, only a holder of a read or write grant sees the value; once write grants exist, only a write holder may change it, so a field with read grants alone stays writable by `item.update`. `has_manage` on the context means instance admin, who bypasses both; managing the grants needs `field.manage` on the field's scope. A grant only narrows action RBAC: without `item.read` on the project it is moot.

### Query language (SLQ)

The dialect rules (rooted at what a query returns, bare field names, reach across by delegating) are CLAUDE.md's "Query language (SLQ)". The item dialect is `items/slq/`: `lexer.py` → `parser.py` → `compiler.py`, operator tables in `catalog.py`, builtin fields in `builtins.py`, custom fields by bare registry key in `custom.py`, `epic.*`/`parent.*` in `ancestors.py`, sorting in `ordering.py`, and `items.slq` exports the lexer, parser and helpers as generic query machinery. The worklog dialect is `timelogging/slq/`, which hands each `issue.<field>` condition to `items.slq.compile_query`. Plugins add item fields with `SlqFieldSpec` (listed per module above). `GET /items?q=` and saved views (`views.query`) take the item dialect; an invalid query answers 422 `{detail, position}`. The grammar is frozen, and the SPA renders its cheat sheet from it:

```
query     := [expr] [ORDER BY order (, order)*]
expr      := term ((AND|OR) term)*        # AND binds tighter than OR
term      := [NOT] (comparison | '(' expr ')')
comparison:= field op value | field [NOT] IN '(' value (',' value)* ')' | field IS [NOT] EMPTY
op        := = | != | ~ | > | < | >= | <=
value     := bareword | 'single' | "double" quoted | number | YYYY-MM-DD | today[±Nd|Nw] | me | none
order     := field [ASC|DESC]
```

`!=` and `NOT IN` over a nullable to-one relation are the complement of the positive form (`helpers.polarity`), so `= x` and `!= x` partition the rows. Keywords are case-insensitive, field names case-sensitive, and a quoted value is always literal.

### Frontend cache invalidation

One domain object is cached under many TanStack Query keys (an item lives in `["items"]`, `["viewItems"]`, `["item"]`, `["itemByKey"]` and more), so the SPA invalidates by ENTITY, never by key (`@radd/plugin-sdk`, `packages/plugin-sdk/src/cache.ts`). A read declares what it caches — `meta: entityMeta(Entity.item)`, one tag per entity in its data — and a mutation calls `invalidateEntities(queryClient, Entity.item, …)`, listing every entity it can change (a comment also changes its item's `comment_count`). Any query tagged with that entity refreshes, including ones other modules add later. Optimistic writes may still `setQueryData` for an instant feel; the invalidation on settle keeps every surface live. A new shared entity gets a member in the SDK's `Entity` — the host and every plugin UI import that one vocabulary; a plugin's OWN entity is tagged with its server entity type verbatim, which is what the realtime hub subscribes to.

### Outside the server modules

- **`web/`** — React 19 + Vite with TanStack Router and Query, built into `web/dist` and served by the API. The shell is `components/shell/`; every work surface is a saved view rendered by `routes/view.tsx`, and the issue page is `routes/item-page.tsx`. `lib/api.ts` is the typed client; routes, query keys and API paths live in `lib/constants/`, queries in `lib/queries/`. Core plugins' UI is bundled and registered at boot, optional plugins load as remotes, and both import only `@radd/plugin-sdk`, which `web/scripts/plugin-boundaries.test.mjs` enforces; [plugin-ui.md](plugin-ui.md) is the contract. Plugins add list columns and card cells through the `item.attribute` slot.
- **`sdk/`** — the Apache-2.0 extensions SDK (`radd-sdk`): `RaddClient` and the `radd-runner` event runner over `GET /events`, for connectors that live outside the server.
- **`examples/acme-notes/`** — an external plugin in its own package, the acceptance test for the plugin platform.
- **Packaging** — `Containerfile`, `compose.yaml`, the Helm chart `deploy/helm/radd/` and [deploy.md](deploy.md). `RADD_RUN_WORKERS` gates the background loops, so a worker replica can run them apart from the web one.

### Known simplifications

- OpenAPI is rebuilt per request; the field-schema cache refreshes inside the mutating transaction, so a rolled-back field change leaves it one step ahead until the next mutation.
- A project's default states are seeded in the `project.created` hook, which carries no actor, so those `state.created` events are actor-less.
- Expired sessions are never pruned (lookups ignore them); a PAT's `last_used_at` is throttled (`RADD_TOKEN_LAST_USED_THROTTLE_SECONDS`), so it is approximate.
- A state's `is_default` cannot be moved; item labels replace wholesale on PATCH.
- A custom-field key shadowed by a builtin name or an SLQ keyword is unreachable in queries.
- LDAP is Active Directory-flavoured only (UPN bind, `sAMAccountName`, the in-chain group rule).
- The extensions SDK polls (2 s by default), one offset per runner process.
- One app replica, on purpose ([deploy.md](deploy.md)): realtime fan-out and co-editing rooms live in one process, and a second replica would double-fire timers.
- Internal-comment bodies are not search-indexed; search has no typo tolerance.
- Reports recompute from the event log on every request (no read model).

### Records

Why things are the way they are: the specs in [specs/](specs/), the tracker (the RADD project), and `git log`. The plugin-ownership wave: `research/plugin-isolation/README.md`; the September 2026 audit remediation: `research/audit-2026-09-09/REMEDIATION.md`; the large-view performance work: `research/large-views-2026-09/`.
