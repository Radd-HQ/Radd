/** The fixture API the mocked board/planning proofs share: one DEV project, its cycles and saved
 *  view, an item factory, and the routes every page load asks. Proofs mutate `project`/`view` live. */

const CYCLES = [
  { id: "active", name: "Current sprint", status: "active", start_date: "2026-09-10", end_date: "2026-09-24" },
  { id: "draft", name: "Next sprint", status: "draft", start_date: null, end_date: null },
  { id: "closed", name: "Historical sprint", status: "completed" },
];
const STATES = [
  { id: "todo", name: "To do", category: "todo", position: 1 },
  { id: "progress", name: "In progress", category: "in_progress", position: 2 },
];
const NO_PLUGINS = { capabilities: [], nav: [], plugins: [], ui: [], view_types: [] };

/**
 * `view` patches the board view; `starred(n)` marks items; `capabilities` may be a function, read
 * per request. `route(p)` answers the shared routes (undefined for any other path); a proof answers
 * its own routes first and its `/settings` and `/stats` after.
 */
export function planningFixture({ permissions = ["item.read"], cycles = CYCLES, view: patch = {}, states = STATES,
  capabilities = NO_PLUGINS, starred = () => false } = {}) {
  const project = { id: "project", key: "DEV", name: "Development", permissions, created_at: "2026-01-01" };
  const summary = { total: 1, related_count: 1, permissions: [...permissions] };
  const view = { id: "planning", project_id: project.id, name: "Planning", view_type: "board", query: "",
    query_string: "project_id=project", group_by: "state", swimlane_by: null, quick_filters: [],
    columns: ["item", "priority", "state"], column_order: [], hidden_columns: [], cycle_filter: null,
    can_edit: false, can_manage: false, ...patch };
  const item = (n, cycle = null) => ({ id: `i-${n}`, key: `DEV-${n}`, number: n, project_id: project.id,
    title: `${cycle ? "Sprint" : "Backlog"} work ${n}`, description: "",
    state: { id: "todo", name: "To do", category: "todo", color: "#999" }, priority: "high", kind: "issue",
    type: null, assignee: null, reporter: null, team: null, cycle, labels: [], custom_fields: {},
    starred: starred(n), flagged: false, visibility: "public", created_at: "2026-09-01", updated_at: "2026-09-17",
    comment_count: 0, attachment_count: 0 });
  const route = (p) => {
    if (p === "/api/v1/auth/me") return { id: "person", name: "Tester", email: "tester@example.com",
      global_role: "member", instance_role: "member", permissions: [], timezone: "UTC" };
    if (p === "/api/v1/views/planning") return view;
    if (p === "/api/v1/views") return [view];
    if (p === "/api/v1/projects/summary") return summary;
    if (p === "/api/v1/page-spaces/summary") return { total: 0, permissions: [] };
    if (p === "/api/v1/projects") return [project];
    if (p.startsWith("/api/v1/projects/")) return project;
    if (p === "/api/v1/cycles") return cycles;
    if (p === "/api/v1/states") return states;
    if (p.includes("/capabilities")) return typeof capabilities === "function" ? capabilities() : capabilities;
    if (p.includes("/notifications")) return { items: [], notifications: [], unread_count: 0, total: 0 };
    if (p.includes("/preferences") || p.includes("/config")) return {};
    return undefined;
  };
  return { project, cycles, view, item, route };
}

/** Answer as the fixture API does: JSON with an X-Total-Count. */
export function sendFixture(res, data) {
  res.setHeader("content-type", "application/json");
  res.setHeader("X-Total-Count", String(Array.isArray(data) ? data.length : 0));
  res.end(JSON.stringify(data));
}
