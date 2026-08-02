# Spec 114 — the MCP catalog is what the key can actually do

**.** An agent's context is finite and every tool definition spends some of it.
Radd knows precisely what a given key may do, in which projects — so the tool
list stops being a constant and becomes a function of the caller. A viewer's key
sees reads. An admin's key sees the admin family. Nobody's key sees a tool that
would 403.

## Why

Spec 45 shipped a fixed catalog: nine tools, identical for every caller. That
was right for one tool-user on an instance they administered, and wrong the
moment service accounts (spec 113) exist to be deliberately narrow. Two costs:

- **Context.** Tool definitions are sent on every conversation turn that lists
  them. A catalog that grows to ~25 tools spends real budget describing writes to
  a key that can only read.
- **Failure modes.** An agent offered `create_item` will eventually call it, get
  a 403, and spend turns reasoning about a rule it was never told. Hiding the
  tool is not security — the call still authorizes — it is honesty about the
  interface.

The permission engine already answers "may this actor do X in project P". Spec
113 makes a key's own ceiling machine-readable. Filtering is then a projection
of facts that exist, not a new policy.

## What

- **Tools declare their requirement.** An `McpToolSpec` carries
  `permission: Permission | None`, `scope: project | global`, and
  `project_param: str | None` alongside the existing name/description/schema.
  The nine current tools are annotated (`create_item` → `item.create`, project
  scope, `project_key`; `search_docs` → `doc.read`, global; `list_projects` →
  none).
- **`tools/list` is computed per caller.** For each spec: resolve the projects
  in which the actor holds the permission, intersected with the key's scopes
  (spec 113's seam, so this is one call, not a second policy). A project-scoped
  tool appears iff that set is non-empty; a global tool appears iff the key holds
  the atom.
- **The project parameter is an enum of the permitted projects.** `create_item`
  offered to a key that may write only RADD carries
  `"project_key": {"enum": ["RADD"]}` — the agent cannot name a project it may
  not write to, and the enum doubles as the answer to "where can I file this".
  Above `mcp_project_enum_max` (default 25) it degrades to a plain string with
  the count in the description, because a 300-entry enum costs more context than
  it saves.
- **New families**, each gated the same way:
  - **Workflow** — `get_allowed_transitions`, `transition_item`. Guard failures
    (spec 107) come back as the reason text, so an agent learns *why* a move is
    refused instead of retrying.
  - **Time** — `log_work`, `list_worklogs` (worklog SLQ dialect, spec 98),
    gated on `worklog.write` / `timesheet.view`.
  - **Releases** — `list_releases`, `create_release`, `set_item_release`,
    which is what lets an agent close out a version alongside spec 112.
  - **Admin** — users, roles, service accounts, settings, project creation.
    Gated on `user.manage` / `role.manage` / `global.manage`; this is the family
    that makes an admin key's catalog visibly larger than a member's.
- **Plugins contribute tools** through a kernel registry (`registries.mcp_tools`,
  the spec-93 pattern), and inherit the filtering with no extra code — a plugin
  cannot accidentally expose an unfiltered tool.
- **Per-call authorization is unchanged.** Every tool still calls
  `authz.require`. A tool hidden from the catalog and invoked anyway returns the
  same domain error it does today. Filtering is presentation; the enforcement is
  where it always was.

## Invariants tested

- A viewer key's catalog contains no mutating tool; an admin key's contains the
  admin family; a member's sits between them.
- A tool absent from the catalog still 403s when called directly — hiding is not
  the enforcement.
- The project enum lists exactly the projects where the permission holds, and a
  key scoped (spec 113) to one project sees only that project even when the
  account may write to five.
- Above the enum threshold the parameter degrades to a string and the tool still
  works.
- A plugin-contributed tool is filtered by the same rule as a builtin one, and
  disappears when the plugin is disabled (the spec-94 unmount path).
- An unscoped admin PAT sees the whole catalog — the spec-45 behaviour is
  preserved for existing callers.

## Known simplifications

- No `tools/list_changed` push. The catalog is computed per `tools/list` call,
  so a permission change is picked up on the next listing; long-lived sessions
  see it when they re-list.
- No per-tool rate limiting or quotas.
- Tool DESCRIPTIONS are static per tool; only the project enum varies per caller.
  Tailoring prose per role was considered and dropped — it makes the catalog
  untestable for marginal benefit.
- The admin family is deliberately small at first: reads plus the few writes an
  agent has a real reason to make. It is easier to add a tool than to explain one
  that turned out to be a mistake.

## Addendum — RADD-640/672/673: the registry, the gate, and the workflow (0.4.0)

Three follow-ups landed together, closing the promises this spec made:

**RADD-640 — plugins contribute MCP tools through the kernel.** The acceptance
line "a plugin-contributed tool is filtered by the same rule as a builtin one"
is now real: `McpToolSpec` (kernel spec: name, description, inputSchema,
handler, permission ATOM, project_param) rides the plugin manifest into
`registries.mcp_tools`. `live_catalog` appends registry tools (a builtin name
cannot be shadowed), `requirements.requirement_for` treats the spec as the
annotation, and the dispatcher requires the declared atom — scoped to the
`project_param` project when the call names one — BEFORE the handler runs, so a
plugin cannot ship an unfiltered tool even by omission. Unmount removes catalog
and dispatch together. The old show-unannotated-tools fallback is reversed: a
tool in neither `REQUIREMENTS` nor the registry is hidden and logged. North
star: `milestones/mcptool.py` contributes `list_milestones` with zero authz
code of its own.

**RADD-672 — the catalog/enforcement disagreement this spec forbade.**
`search_items`, `list_projects` and `list_worklogs` (and `GET /projects` +
cross-project `list_items`/`bulk` under them) demanded GLOBAL `item.read`,
which a spec-113 key scoped to one project never holds — while
`visible_catalog` listed those tools for exactly that key. New authz seam
`require_anywhere`: the atom held in ANY project admits the caller, the answer
narrows to where it holds, and item listing constrains its query up front
(also fixing LIMIT-before-visibility pagination). Found dogfooding the Radd
Agent key; admin keys masked it because they hold the global atom.

**RADD-673 — the tracking workflow, tool-complete.** Names in, ids resolved
server-side: `type`/`parent`/`estimate_points`/`cycle` on create/update,
`category` on `log_work`, `status` on `create_release`, and `sweep_release`
(the spec-112 pipeline step, `release.update`). Pinned by
`test_the_tracking_workflow_runs_entirely_over_mcp`: epic + typed child with
points, categorized worklog, released version, sweep — zero REST calls.
