import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { stripTypeScriptTypes } from "node:module";
import { QueryClient, QueryObserver } from "../node_modules/@tanstack/react-query/build/modern/index.js";

const source = path => readFileSync(new URL(`../src/lib/${path}`, import.meta.url), "utf8");
function evaluate(code, imports, exports) {
  const js = stripTypeScriptTypes(code).replace(/^import[\s\S]*?from ["'][^"']+["'];\n/gm, "").replaceAll("export ", "");
  return Function(...Object.keys(imports), `${js}; return {${exports.join(",")}}`)(...Object.values(imports));
}
let factories = source("queries/shared.ts");
for (const [file, names] of [
  ["items", ["commentsQuery"]], ["activity", ["linkSearchQuery"]],
  ["ai-search", ["searchQuery", "similarToTextQuery"]], ["pages", ["pageSearchQuery"]],
]) {
  const code = source(`queries/${file}.ts`);
  for (const name of names) {
    const start = code.indexOf(`export const ${name} =`);
    factories += "\n" + code.slice(start, code.indexOf("\n  });", start) + 7);
  }
}
const { Entity, entityMeta, invalidateEntities } = evaluate(source("cache.ts"), {}, ["Entity", "entityMeta", "invalidateEntities"]);
const names = ["commentsQuery", "linkSearchQuery", "searchQuery", "similarToTextQuery", "pageSearchQuery"];
const queries = evaluate(factories, { queryOptions: x => x, api: {}, ApiPath: {}, Entity, entityMeta, keepPreviousData: undefined }, names);
for (const [name, a, b] of [
  ["linkSearchQuery", ["p", "q", "a", 20], ["p", "q", "b", 20]],
  ["searchQuery", ["q", 5], ["q", 20]],
  ["pageSearchQuery", ["q", 5], ["q", 20]],
  ["similarToTextQuery", ["comment", "old", "a"], ["comment", "new", "a"]],
  ["similarToTextQuery", ["comment", "same", "a"], ["comment", "same", "b"]],
]) assert.notDeepEqual(queries[name](...a).queryKey, queries[name](...b).queryKey, name);

const client = new QueryClient();
const comments = queries.commentsQuery("issue");
await client.fetchQuery({ ...comments, queryFn: async () => ["old comment"] });
await invalidateEntities(client, Entity.comment);
assert(client.getQueryState(comments.queryKey).isInvalidated, "another reader's comment event invalidates this thread");
client.clear();

const controller = new AbortController();
for (const count of [51, 201, 400]) {
  const rows = Array.from({length: count}, (_, id) => ({id}));
  const api = { getPaged: async (_path, {query}) => ({ rows: rows.slice(Number(query.offset), Number(query.offset) + Number(query.limit)), total: count }) };
  const { allRelationRows } = evaluate(source("pagination.ts"), { api }, ["allRelationRows"]);
  assert.deepEqual(await allRelationRows("/items", {}, controller.signal), rows);
}

const storage = new Map();
globalThis.localStorage = {getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key)};
const account = evaluate(source("account-storage.ts"), {}, ["setStorageAccount", "accountStorageKey"]);
const recent = evaluate(source("recent.ts"), account, ["recordRecentItem", "listRecentItems"]);
account.setStorageAccount("A");
recent.recordRecentItem("PRIVATE-1", "Account A private issue");
account.setStorageAccount("B");
assert.deepEqual(recent.listRecentItems(), []);
account.setStorageAccount("A");
assert.equal(recent.listRecentItems()[0].key, "PRIVATE-1");
delete globalThis.localStorage;
globalThis.window = {location: {origin: "http://test", pathname: "/projects"}};
const oldFetch = globalThis.fetch;
globalThis.fetch = (_url, options) => new Promise((_resolve, reject) => {
  options.signal.addEventListener("abort", () => reject(options.signal.reason), {once: true});
});
const requestModule = evaluate(source("api.ts"), {
  API_BASE: "/api", On401: {redirect: "redirect"}, RoutePath: {login: "/login"}, pushToast() {}, FORBIDDEN_FALLBACK_MESSAGE: "Denied",
}, ["api", "abortAccountRequests"]);
let stopped = false;
const session = evaluate(source("account-session.ts"), {
  abortAccountRequests: requestModule.abortAccountRequests,
  stopAllRealtime: () => { stopped = true; },
  setStorageAccount() {},
}, ["resetAccountSession"]);
client.setQueryData(["private"], {title: "Account A"});
const inflight = client.fetchQuery({ queryKey: ["slow-private"], retry: false, queryFn: () => requestModule.api.get("/slow") });
const rejection = assert.rejects(inflight);
await session.resetAccountSession(client);
await rejection;
assert(stopped);
assert.equal(client.getQueryCache().getAll().length, 0);
globalThis.fetch = oldFetch;
let socket;
const previousWebSocket = globalThis.WebSocket;
globalThis.WebSocket = class {
  static OPEN = 1;
  readyState = 1;
  sent = [];
  constructor() { socket = this; }
  send(data) { this.sent.push(JSON.parse(data)); }
  close() {}
};
const realtime = evaluate(source("realtime.ts"), {
  useEffect() {}, useQueryClient() {}, Entity, invalidateEntities,
  REALTIME_COALESCE_MS: 1, REALTIME_RECONNECT_BASE_MS: 1, REALTIME_RECONNECT_MAX_MS: 20, REALTIME_WS_PATH: "/ws",
}, ["startRealtime"]);
const calls = {A: 0, B: 0};
const observers = ["A", "B"].map(projectId => new QueryObserver(client, {
  queryKey: ["view", projectId], meta: {entities: [Entity.item], projectId},
  queryFn: async () => { calls[projectId]++; return []; },
}));
const unobserve = observers.map(observer => observer.subscribe(() => {}));
await Promise.all(observers.map(observer => observer.refetch()));
const stop = realtime.startRealtime(client);
socket.onopen();
const subscriptions = socket.sent.at(-1).queries;
assert.deepEqual(subscriptions.map(sub => sub.project_id).sort(), ["A", "B"]);
socket.onmessage({data: JSON.stringify({entity: "item", queries: [subscriptions.find(sub => sub.project_id === "A").id]})});
await new Promise(resolve => setTimeout(resolve, 20));
assert.deepEqual(calls, {A: 2, B: 1}, "project A's event must not refetch project B");
stop();
unobserve.forEach(fn => fn());
client.clear();
const cycleFactories = evaluate(source("queries/shared.ts") + "\n" + source("queries/cycles.ts"), {
  queryOptions: x => x, api: {}, ApiPath: {}, Entity, entityMeta, keepPreviousData: undefined,
}, ["cycleSeriesPageQuery"]);
let seriesReads = 0;
const seriesObserver = new QueryObserver(client, {
  ...cycleFactories.cycleSeriesPageQuery("later", 2),
  queryFn: async () => { seriesReads++; return { rows: [], total: 0 }; },
});
const unobserveSeries = seriesObserver.subscribe(() => {});
await seriesObserver.refetch();
const stopSeries = realtime.startRealtime(client);
socket.onopen();
assert(socket.sent.at(-1).queries.some(sub => sub.entities.includes("cycle_series")), "series queries subscribe to their server entity");
socket.onmessage({ data: JSON.stringify({ entity: "cycle_series" }) });
await new Promise(resolve => setTimeout(resolve, 20));
assert.equal(seriesReads, 2, "another reader's series change refetches the directory");
stopSeries();
unobserveSeries();
client.clear();
const wikiFactories = evaluate(source("queries/shared.ts") + "\n" + source("queries/pages.ts"), {
  queryOptions: x => x, api: {}, ApiPath: {}, Entity, entityMeta, keepPreviousData: undefined,
}, ["pageSpaceSummaryQuery", "pageSpacesPageQuery", "pageSpaceByIdentityQuery"]);
const wikiCalls = [0, 0, 0];
const wikiObservers = [wikiFactories.pageSpaceSummaryQuery(), wikiFactories.pageSpacesPageQuery("later", 2), wikiFactories.pageSpaceByIdentityQuery("later-space")]
  .map((options, index) => new QueryObserver(client, {
    ...options, queryFn: async () => { wikiCalls[index]++; return { total: 126 }; },
  }));
const stopWikiObservers = wikiObservers.map(observer => observer.subscribe(() => {}));
await Promise.all(wikiObservers.map(observer => observer.refetch()));
const stopWiki = realtime.startRealtime(client);
socket.onopen();
assert.equal(new Set(socket.sent.at(-1).queries.map(sub => sub.id)).size, 3, "summary, window and direct identity have distinct cache identities");
assert(socket.sent.at(-1).queries.every(sub => sub.entities.includes("role") && sub.entities.includes("page_space")));
socket.onmessage({ data: JSON.stringify({ entity: "role" }) });
await new Promise(resolve => setTimeout(resolve, 20));
assert.deepEqual(wikiCalls, [2, 2, 2], "role grant changes refresh all wiki authority readers");
socket.onmessage({ data: JSON.stringify({ entity: "page_space" }) });
await new Promise(resolve => setTimeout(resolve, 20));
assert.deepEqual(wikiCalls, [3, 3, 3], "space changes refresh summary, directory and direct names");
stopWiki();
stopWikiObservers.forEach(stop => stop());
client.clear();
const accessFactories = evaluate(source("queries/shared.ts") + "\n" + source("queries/roles.ts"), {
  queryOptions: x => x, api: {}, ApiPath: {}, Entity, entityMeta,
}, ["spaceGrantsPageQuery", "projectGrantsPageQuery"]);
const accessCalls = [0, 0, 0, 0, 0];
const accessObservers = [accessFactories.spaceGrantsPageQuery("space-a", "", 0), accessFactories.spaceGrantsPageQuery("space-a", "later", 0), accessFactories.spaceGrantsPageQuery("space-a", "later", 1), accessFactories.spaceGrantsPageQuery("space-b", "later", 1), accessFactories.projectGrantsPageQuery("space-a", "later", 1)]
  .map((options, index) => new QueryObserver(client, { ...options, queryFn: async () => { accessCalls[index]++; return { rows: [], total: 126 }; } }));
const stopAccessObservers = accessObservers.map(observer => observer.subscribe(() => {}));
await Promise.all(accessObservers.map(observer => observer.refetch()));
const stopAccess = realtime.startRealtime(client);
socket.onopen();
assert.equal(new Set(socket.sent.at(-1).queries.map(sub => sub.id)).size, 5, "project/wiki kind, scope, search and window are distinct access identities");
assert(socket.sent.at(-1).queries.every(sub => ["role", "user", "team", "group", "page_space"].every(entity => sub.entities.includes(entity))));
for (const entity of ["role", "user", "team", "group"]) {
  socket.onmessage({ data: JSON.stringify({ entity }) });
  await new Promise(resolve => setTimeout(resolve, 20));
}
assert.deepEqual(accessCalls, [5, 5, 5, 5, 5], "grants and permitted name changes refresh space access windows");
stopAccess();
stopAccessObservers.forEach(stop => stop());
client.clear();
const inspectorCode = source("queries/users.ts");
const inspectorStart = inspectorCode.indexOf("export const userPermissionsQuery =");
const inspectorEnd = inspectorCode.indexOf("\n};", inspectorStart) + 3;
const selectorQueries = evaluate(source("queries/shared.ts") + "\n" + source("queries/notifications.ts") + "\n" + inspectorCode.slice(inspectorStart, inspectorEnd), {
  queryOptions: x => x, api: {}, ApiPath: {}, Entity, entityMeta, keepPreviousData: undefined, NOTIFICATIONS_POLL_MS: 1000,
}, ["subscriptionOptionsQuery", "notificationPrefsQuery", "userPermissionsQuery"]);
const selectorCalls = [0, 0, 0, 0, 0, 0];
const selectorSpecs = [selectorQueries.subscriptionOptionsQuery("project", "", 0), selectorQueries.subscriptionOptionsQuery("space", "later", 0), selectorQueries.subscriptionOptionsQuery("team", "later", 1), selectorQueries.userPermissionsQuery("person", { projectId: "p" }), selectorQueries.userPermissionsQuery("person", { spaceId: "s" }), selectorQueries.notificationPrefsQuery()];
const selectorObservers = selectorSpecs.map((options, index) => new QueryObserver(client, { ...options, queryFn: async () => { selectorCalls[index]++; return []; } }));
const stopSelectorObservers = selectorObservers.map(observer => observer.subscribe(() => {}));
await Promise.all(selectorObservers.map(observer => observer.refetch()));
const stopSelectors = realtime.startRealtime(client);
socket.onopen();
assert.equal(new Set(socket.sent.at(-1).queries.map(sub => sub.id)).size, 6);
for (const entity of ["role", "team", "project", "page_space", "group", "user"]) {
  socket.onmessage({ data: JSON.stringify({ entity }) });
  await new Promise(resolve => setTimeout(resolve, 20));
}
assert.deepEqual(selectorCalls, [7, 7, 7, 7, 7, 7], "scope authority and name frames refresh inspectors, candidates and saved subscription labels");
stopSelectors();stopSelectorObservers.forEach(stop => stop());client.clear();
const { provisioningReferencesQuery } = evaluate(source("queries/provisioning.ts"), {
  queryOptions: x => x, api: {}, Entity, entityMeta,
}, ["provisioningReferencesQuery"]);
assert.deepEqual(provisioningReferencesQuery(["b", "a", "a"], [], []).queryKey,
  provisioningReferencesQuery(["a", "b"], [], []).queryKey, "reference order and duplicate IDs do not fragment cache identity");
const referenceCalls = [0, 0];
const referenceObservers = [provisioningReferencesQuery(["r1"], ["p1"], ["t1"]), provisioningReferencesQuery(["r2"], ["p2"], ["t2"])]
  .map((options, index) => new QueryObserver(client, { ...options, queryFn: async () => { referenceCalls[index]++; return {}; } }));
const stopReferenceObservers = referenceObservers.map(observer => observer.subscribe(() => {}));
await Promise.all(referenceObservers.map(observer => observer.refetch()));
const stopReferences = realtime.startRealtime(client);
socket.onopen();
assert.equal(new Set(socket.sent.at(-1).queries.map(sub => sub.id)).size, 2);
for (const entity of ["role", "project", "team"]) {
  socket.onmessage({ data: JSON.stringify({ entity }) });
  await new Promise(resolve => setTimeout(resolve, 20));
}
assert.deepEqual(referenceCalls, [4, 4], "name changes refresh both visible provisioning reference windows");
stopReferences(); stopReferenceObservers.forEach(stop => stop()); client.clear();
const { resourceGrantsPageQuery } = evaluate(source("queries/shared.ts") + "\n" + source("queries/fields.ts"), {
  queryOptions: x => x, api: {}, ApiPath: {}, Entity, entityMeta,
}, ["resourceGrantsPageQuery"]);
const builtinScopeKeys = [undefined, null, "project-a", "project-b"].map(scope => resourceGrantsPageQuery("builtin_field", "assignee", "", 0, scope));
assert.equal(new Set(builtinScopeKeys.map(options => JSON.stringify(options.queryKey))).size, 4,
  "all, global and project grant contexts must never share cached policies");
assert.equal(builtinScopeKeys[3].placeholderData({ rows: ["old-project"], total: 1 }, { queryKey: builtinScopeKeys[2].queryKey }), undefined,
  "changing project context cannot display the previous project's grants");
const resourceCalls = [0, 0, 0];
const resourceObservers = [resourceGrantsPageQuery("field", "a", "", 0), resourceGrantsPageQuery("field", "a", "later", 1), resourceGrantsPageQuery("page", "a", "", 0)]
  .map((options, index) => new QueryObserver(client, { ...options, queryFn: async () => { resourceCalls[index]++; return { rows: [], total: 126 }; } }));
const stopResourceObservers = resourceObservers.map(observer => observer.subscribe(() => {}));
await Promise.all(resourceObservers.map(observer => observer.refetch()));
const stopResources = realtime.startRealtime(client); socket.onopen();
assert.equal(new Set(socket.sent.at(-1).queries.map(sub => sub.id)).size, 3);
assert(socket.sent.at(-1).queries.every(sub => sub.entities.includes("access_grant")));
for (const entity of ["access_grant", "role", "user", "team", "group", "project"]) {
  socket.onmessage({ data: JSON.stringify({ entity }) });
  await new Promise(resolve => setTimeout(resolve, 20));
}
assert.deepEqual(resourceCalls, [7, 7, 7], "resource grants and permitted names refresh each distinct active window");
stopResources(); stopResourceObservers.forEach(stop => stop()); client.clear();
const fieldSettings = evaluate(source("queries/shared.ts") + "\n" + source("queries/field-settings.ts"), {
  queryOptions: x => x, api: {}, Entity, entityMeta,
}, ["fieldDirectoryQuery", "managedFieldQuery", "fieldProjectChoicesQuery", "fieldProjectReferencesQuery", "fieldSettingsSummaryQuery", "fieldOptionsQuery"]);
assert.deepEqual(fieldSettings.fieldProjectReferencesQuery(["b", "a", "a"]).queryKey,
  fieldSettings.fieldProjectReferencesQuery(["a", "b"]).queryKey);
const serviceAccounts = evaluate(source("queries/shared.ts") + "\n" + source("queries/integrations.ts"), {
  queryOptions: x => x, api: {}, Entity, entityMeta,
}, ["serviceAccountDirectoryQuery", "serviceAccountQuery", "serviceKeyDirectoryQuery"]);
const accountOptions = [serviceAccounts.serviceAccountDirectoryQuery("", 0), serviceAccounts.serviceAccountDirectoryQuery("later", 1),
  serviceAccounts.serviceAccountQuery("one"), serviceAccounts.serviceAccountQuery("two"),
  serviceAccounts.serviceKeyDirectoryQuery("one", "", 0), serviceAccounts.serviceKeyDirectoryQuery("two", "", 0),
  serviceAccounts.serviceKeyDirectoryQuery("one", "later", 0), serviceAccounts.serviceKeyDirectoryQuery("one", "", 1)];
assert.equal(new Set(accountOptions.map(o => JSON.stringify(o.queryKey))).size, accountOptions.length);
const accountCalls = accountOptions.map(() => 0);
const accountObservers = accountOptions.map((options, index) => new QueryObserver(client, { ...options,
  queryFn: async () => { accountCalls[index]++; return {}; } }));
const stopAccounts = accountObservers.map(observer => observer.subscribe(() => {}));
await Promise.all(accountObservers.map(observer => observer.refetch()));
const stopAccountLive = realtime.startRealtime(client); socket.onopen();
for (const entity of ["user", "role", "team", "group"]) {
  socket.onmessage({ data: JSON.stringify({ entity }) });
  await new Promise(resolve => setTimeout(resolve, 20));
}
assert.deepEqual(accountCalls, accountOptions.map(() => 5), "account and key directories refresh on identity/authority frames");
stopAccountLive(); stopAccounts.forEach(stop => stop()); client.clear();
const teamRefs = evaluate(source("queries/shared.ts") + "\n" + source("queries/users.ts"), {
  queryOptions: x => x, api: {}, Entity, entityMeta, keepPreviousData: undefined,
}, ["teamReferencesQuery"]);
assert.deepEqual(teamRefs.teamReferencesQuery(["b", "a", "a"]).queryKey, teamRefs.teamReferencesQuery(["a", "b"]).queryKey);
assert.notDeepEqual(teamRefs.teamReferencesQuery(["a"]).queryKey, teamRefs.teamReferencesQuery(["a"], true).queryKey);
const audienceReferenceOptions = [teamRefs.teamReferencesQuery(["a"]), teamRefs.teamReferencesQuery(["a"], true)];
const audienceReferenceCalls = audienceReferenceOptions.map(() => 0);
const audienceReferenceObservers = audienceReferenceOptions.map((options, index) => new QueryObserver(client, { ...options,
  queryFn: async () => { audienceReferenceCalls[index]++; return []; }, staleTime: Infinity,
}));
const audienceReferenceStops = audienceReferenceObservers.map(observer => observer.subscribe(() => {}));
await Promise.all(audienceReferenceObservers.map(observer => observer.refetch()));
const stopAudienceLive = realtime.startRealtime(client); socket.onopen();
for (const entity of ["team", "user", "group", "role"]) {
  socket.onmessage({data: JSON.stringify({entity})}); await new Promise(resolve => setTimeout(resolve, 30));
}
assert.deepEqual(audienceReferenceCalls, [5, 5], "audience names/counts refresh on membership and authority changes");
stopAudienceLive(); audienceReferenceStops.forEach(stop => stop()); client.clear();

const portalSharing = evaluate(source("queries/shared.ts") + "\n" + source("queries/forms.ts"), {
  queryOptions: x => x, api: {}, Entity, entityMeta, apiFormPath: id => "/forms/"+id,
}, ["formSharingQuery", "formShareCandidatesQuery"]);
const portalOptions = [portalSharing.formSharingQuery("one"), portalSharing.formSharingQuery("two"),
  portalSharing.formSharingQuery("one", "later", 1), portalSharing.formShareCandidatesQuery("one", "user"),
  portalSharing.formShareCandidatesQuery("one", "team"), portalSharing.formShareCandidatesQuery("one", "user", "later", 1)];
assert.equal(new Set(portalOptions.map(o => JSON.stringify(o.queryKey))).size, portalOptions.length);
const portalCalls = portalOptions.map(() => 0);
const portalObservers = portalOptions.map((options, index) => new QueryObserver(client, { ...options,
  queryFn: async () => { portalCalls[index]++; return {}; },
}));
const portalStops = portalObservers.map(observer => observer.subscribe(() => {}));
await Promise.all(portalObservers.map(observer => observer.refetch()));
const stopPortalLive = realtime.startRealtime(client); socket.onopen();
for (const entity of ["form", "project", "user", "team", "group", "role"]) {
  socket.onmessage({data: JSON.stringify({entity})}); await new Promise(resolve => setTimeout(resolve, 20));
}
assert.deepEqual(portalCalls, portalOptions.map(() => 7), "portal shares and eligible recipients refresh on form/identity/authority frames");
stopPortalLive(); portalStops.forEach(stop => stop()); client.clear();

const fieldOptions = [fieldSettings.fieldDirectoryQuery("", 0), fieldSettings.fieldDirectoryQuery("later", 1),
  fieldSettings.managedFieldQuery("one"), fieldSettings.managedFieldQuery("two"),
  fieldSettings.fieldProjectChoicesQuery("field.create", "", 0), fieldSettings.fieldProjectChoicesQuery("field.update", "", 0),
  fieldSettings.fieldProjectReferencesQuery(["p"]), fieldSettings.fieldSettingsSummaryQuery(),
  fieldSettings.fieldOptionsQuery("one", "", 0), fieldSettings.fieldOptionsQuery("two", "", 0),
  fieldSettings.fieldOptionsQuery("one", "", 1), fieldSettings.fieldOptionsQuery("one", "later", 0),
  fieldSettings.fieldOptionsQuery("one", "", 0, "excluded"), fieldSettings.fieldOptionsQuery("one", "", 0, "")];
const fieldCalls = fieldOptions.map(() => 0);
const fieldObservers = fieldOptions.map((options, index) => new QueryObserver(client, { ...options,
  queryFn: async () => { fieldCalls[index]++; return {}; } }));
const stopFieldObservers = fieldObservers.map(observer => observer.subscribe(() => {}));
await Promise.all(fieldObservers.map(observer => observer.refetch()));
const stopFields = realtime.startRealtime(client); socket.onopen();
assert.equal(new Set(socket.sent.at(-1).queries.map(sub => sub.id)).size, fieldOptions.length);
for (const entity of ["field", "project", "role", "user", "team", "group", "access_grant"]) {
  socket.onmessage({ data: JSON.stringify({ entity }) });
  await new Promise(resolve => setTimeout(resolve, 20));
}
assert.deepEqual(fieldCalls, fieldOptions.map(() => 8), "field windows, capabilities, choices and references refresh on authority/name changes");
stopFields(); stopFieldObservers.forEach(stop => stop()); client.clear();
globalThis.WebSocket = previousWebSocket;
delete globalThis.window;
console.log("Cache identity, realtime comments, complete relation pagination and account storage regressions passed.");

// A directory refresh must not replace the policy snapshot of an unfinished
// sharing edit. Only explicitly edited IDs are sent; unseen rows stay absent.
{
  const { emptySharingDraft, changeSharingGrant, sharingEdits } = evaluate(source('sharing-draft.ts'), {},
    ['emptySharingDraft', 'changeSharingGrant', 'sharingEdits']);
  const first = { id: 'first-page', access: 'viewer', effect: 'allow', expires_at: '2027-01-01T00:00:00Z' };
  const later = { id: 'later-page', access: 'owner', effect: 'deny', expires_at: null };
  let draft = changeSharingGrant(emptySharingDraft(), first, 'editor');
  draft = changeSharingGrant(draft, later, null);
  draft = changeSharingGrant(draft, { ...first, access: 'owner', expires_at: null }, 'owner');
  const edits = sharingEdits(draft);
  assert.equal(edits.changes.length, 2);
  assert.deepEqual(edits.changes[0], { id: first.id, access: 'owner', expected_access: 'viewer',
    expected_effect: 'allow', expected_expires_at: first.expires_at });
  assert.equal(edits.changes[1].expected_effect, 'deny');
  draft = changeSharingGrant(draft, first, 'viewer');
  assert.deepEqual(sharingEdits(draft).changes.map(row => row.id), ['later-page']);
}
