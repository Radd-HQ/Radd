import test from 'node:test';
import assert from 'node:assert/strict';
import { importTs } from './lib/load-ts.mjs';
import { existsSync, readdirSync, readFileSync } from 'node:fs';

let serial = 0;
async function fixture(importer, statics = {}) {
  const slots = new Set();
  const dataSources = new Set();
  const querySources = new Set();
  const commandSources = new Set();
  const liveDocuments = new Set();
  const key = `__pluginLoaderTest${serial++}`;
  globalThis[key] = {
    isUiApiCompatible: () => true,
    registerSlot: (_slot, _contribution, { plugin }) => slots.add(plugin),
    unregisterPlugin: (name) => slots.delete(name),
    registerCommandSource: name => commandSources.add(name),
    unregisterCommandSources: name => commandSources.delete(name),
    registerQuerySource: (name) => querySources.add(name),
    unregisterQuerySources: (name) => querySources.delete(name),
    registerDataSource: (name) => dataSources.add(name),
    unregisterDataSources: (name) => dataSources.delete(name),
    registerLiveDocumentSource: (name) => liveDocuments.add(name),
    unregisterLiveDocumentSources: (name) => liveDocuments.delete(name),
    setRemotesLoading: (value) => { globalThis[key].loading = value; },
    // RADD-1461: `[synced, entity types a loading remote declares live documents for]`.
    setLiveDocumentsArriving: (synced, entityTypes) => { globalThis[key].arriving = [synced, [...entityTypes].sort()]; },
    loading: undefined,
    arriving: undefined,
    statics,
    importer,
  };
  const loader = await importTs('web/src/lib/plugin-loader.ts', (source) => source
    .replace(/import \{[\s\S]*?\} from "@radd\/plugin-sdk";/,
      `const {isUiApiCompatible, registerSlot, unregisterPlugin, registerDataSource, unregisterDataSources, registerQuerySource, unregisterQuerySources, registerCommandSource, unregisterCommandSources, registerLiveDocumentSource, unregisterLiveDocumentSources, setRemotesLoading, setLiveDocumentsArriving} = globalThis.${key};`)
    // Bundled core plugins are exercised by the browser proofs; the remote lifecycle is tested here.
    .replace(/import \{ STATIC_PLUGINS \} from "[^"]+";/, `const STATIC_PLUGINS = globalThis.${key}.statics;`)
    .replace('import(/* @vite-ignore */ url)', `globalThis.${key}.importer(url)`));
  return { ...loader, slots, dataSources, querySources, commandSources, liveDocuments, arriving: () => globalThis[key].arriving };
}
const remote = (url = 'v1') => [{ name: 'fixture', remote_entry: url, ui_api_version: '1.0' }];
const contribution = { slot: 'issue.tab', title: 'Example' };
const deferred = () => {
  let resolve;
  const promise = new Promise(r => { resolve = r; });
  return { promise, resolve };
};

test('failed activation rolls back contributions', async () => {
  const f = await fixture(async () => ({ contributions: [contribution], activate() { throw Error('fixture failure'); } }));
  await f.syncPluginRemotes(remote());
  assert.equal(f.slots.size, 0);
});

test('disable while import is pending cannot resurrect UI', async () => {
  const wait = deferred();
  const f = await fixture(() => wait.promise);
  const pending = f.syncPluginRemotes(remote());
  await f.syncPluginRemotes([]);
  wait.resolve({ contributions: [contribution] });
  await pending;
  assert.equal(f.slots.size, 0);
});

test('disable while activation is pending suppresses late registrations and cleans up', async () => {
  const wait = deferred();
  let cleanup = 0;
  const f = await fixture(async () => ({ contributions: [contribution],
    async activate(ctx) { await wait.promise; ctx.registerSlot('issue.tab', contribution); },
    deactivate() { cleanup++; },
  }));
  const pending = f.syncPluginRemotes(remote());
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.slots.size, 1);
  await f.syncPluginRemotes([]);
  wait.resolve();
  await pending;
  assert.equal(f.slots.size, 0);
  assert.equal(cleanup, 1);
});

test('concurrent sync imports once and changing URL replaces the remote', async () => {
  const seen = [];
  const f = await fixture(async url => { seen.push(url); return { contributions: [contribution] }; });
  await Promise.all([f.syncPluginRemotes(remote()), f.syncPluginRemotes(remote())]);
  assert.deepEqual(seen, ['v1']);
  await f.syncPluginRemotes(remote('v2'));
  assert.deepEqual(seen, ['v1', 'v2']);
  assert.equal(f.slots.size, 1);
});


test('data-only remote is accepted and its sources withdraw on disable', async () => {
  const f = await fixture(async () => ({ dataSources: [{ kind: 'personIndicators', id: 'status' }] }));
  await f.syncPluginRemotes(remote());
  assert.equal(f.dataSources.size, 1);
  await f.syncPluginRemotes([]);
  assert.equal(f.dataSources.size, 0);
});

test('failed activation and late registrations cannot leave data sources behind', async () => {
  const wait = deferred();
  const source = { kind: 'personIndicators', id: 'status' };
  const f = await fixture(async () => ({ dataSources: [source], async activate(ctx) {
    await wait.promise; ctx.registerDataSource(source); throw Error('fixture failure');
  } }));
  const loading = f.syncPluginRemotes(remote());
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.dataSources.size, 1);
  await f.syncPluginRemotes([]);
  assert.equal(f.dataSources.size, 0);
  wait.resolve();
  await loading;
  assert.equal(f.dataSources.size, 0);
});


test('remote state distinguishes pending imports from success and failure', async () => {
  const wait = deferred();
  const f = await fixture(() => wait.promise);
  const loading = f.syncPluginRemotes(remote());
  assert.equal(f.readRemoteStates()[0].status, 'loading');
  wait.resolve({ contributions: [contribution] });
  await loading;
  assert.equal(f.readRemoteStates()[0].status, 'loaded');
  await f.syncPluginRemotes([]);
  assert.deepEqual(f.readRemoteStates(), []);
});

test('a stalled import becomes a visible error and cannot register after timeout', async t => {
  t.mock.timers.enable({apis:['setTimeout']});
  const wait = deferred();
  const f = await fixture(() => wait.promise);
  const loading = f.syncPluginRemotes(remote());
  t.mock.timers.tick(30_000);
  await loading;
  assert.equal(f.readRemoteStates()[0].status, 'errored');
  wait.resolve({ contributions: [contribution] });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.slots.size, 0);
});


test('SDK version gate rejects remotes requiring newer APIs or another major', async () => {
  const sdk = await importTs('web/packages/plugin-sdk/src/version.ts');
  assert.equal(sdk.UI_API_VERSION, '2.0.0', 'RADD-1465: the first major; bump this line with the ledger in docs/plugin-ui.md');
  for (const version of ['2.0.0', sdk.UI_API_VERSION]) assert(sdk.isUiApiCompatible(version), version);
  // Every 1.x is refused (the removed exports would be undefined at runtime), as is anything newer.
  for (const version of ['1.0.0','1.19.0','1.999.0','3.0.0','2.999.0',sdk.UI_API_VERSION.replace(/\d+$/, n => String(Number(n) + 1)),'','2.garbage.0']) assert(!sdk.isUiApiCompatible(version), version);
});

test('every in-repo remote, the example and the host defaults declare a ui_api_version the SDK accepts (RADD-1465)', async () => {
  // A manifest that still pins 1.x builds, type-checks and is refused by the loader at runtime — a
  // wire constant with no compiler behind it — so the declared versions are checked here.
  const sdk = await importTs('web/packages/plugin-sdk/src/version.ts');
  const manifests = [...readdirSync('server/src/radd/modules').map(m => `server/src/radd/modules/${m}/__init__.py`),
    'examples/acme-notes/src/acme_notes/__init__.py', 'server/src/radd/plugin_cli.py', 'server/src/radd/modules/capabilities/router.py'].filter(existsSync);
  const declared = manifests.flatMap(file => [...readFileSync(file, 'utf8').matchAll(/(?:ui_api_version="|DEFAULT_UI_API_VERSION = ")(\d+\.\d+\.\d+)"/g)].map(m => [file, m[1]]));
  assert(declared.length >= 15, `the scan reaches the remotes' manifests (${declared.length})`);
  assert.deepEqual(declared.filter(([, version]) => !sdk.isUiApiCompatible(version)), []);
});


test('query-only remote registers, withdraws and can be reactivated',async()=>{
  const f=await fixture(async()=>({querySources:[{key:'fixture.catalog',fetch:async()=>[]}]}));
  await f.syncPluginRemotes(remote());assert.equal(f.querySources.size,1);
  await f.syncPluginRemotes([]);assert.equal(f.querySources.size,0);
  await f.syncPluginRemotes(remote('v2'));assert.equal(f.querySources.size,1);
});
test('failed activation rolls back query sources and ignores late registration after withdrawal',async()=>{
  const source={key:'fixture.catalog',fetch:async()=>[]};
  const failed=await fixture(async()=>({querySources:[source],activate(){throw Error('failure');}}));
  await failed.syncPluginRemotes(remote());assert.equal(failed.querySources.size,0);
  const wait=deferred();const pending=await fixture(async()=>({querySources:[source],async activate(ctx){await wait.promise;ctx.registerQuerySource(source);}}));
  const loading=pending.syncPluginRemotes(remote());await new Promise(resolve=>setImmediate(resolve));
  assert.equal(pending.querySources.size,1);await pending.syncPluginRemotes([]);assert.equal(pending.querySources.size,0);
  wait.resolve();await loading;assert.equal(pending.querySources.size,0);
});

test('command-only remotes activate, withdraw and recover without duplicate registrations',async()=>{
  const source={id:'manual',entityType:'record',list:async()=>[],execute:async()=>{}};
  const f=await fixture(async()=>({commandSources:[source]}));
  await f.syncPluginRemotes(remote());assert.equal(f.commandSources.size,1);
  await f.syncPluginRemotes(remote());assert.equal(f.commandSources.size,1);
  await f.syncPluginRemotes([]);assert.equal(f.commandSources.size,0);
  await f.syncPluginRemotes(remote('v2'));assert.equal(f.commandSources.size,1);
});
test('failed or late activation cannot retain command registrations',async()=>{
  const source={id:'manual',entityType:'record',list:async()=>[],execute:async()=>{}};
  const failed=await fixture(async()=>({commandSources:[source],activate(){throw Error('failure');}}));
  await failed.syncPluginRemotes(remote());assert.equal(failed.commandSources.size,0);
  const gate=deferred(),f=await fixture(async()=>({async activate(ctx){await gate.promise;ctx.registerCommandSource(source);}}));
  const pending=f.syncPluginRemotes(remote());await new Promise(resolve=>setImmediate(resolve));
  await f.syncPluginRemotes([]);gate.resolve();await pending;assert.equal(f.commandSources.size,0);
});

test('a live-document-only remote registers, withdraws with its plugin and returns once (RADD-1397)',async()=>{
  const source={id:'fixture.pages',entityType:'page',open:()=>({finish:async()=>{},close(){}})};
  const f=await fixture(async()=>({liveDocuments:[source]}));
  await f.syncPluginRemotes(remote());assert.deepEqual([...f.liveDocuments],['fixture']);
  await f.syncPluginRemotes([]);assert.equal(f.liveDocuments.size,0);
  await f.syncPluginRemotes(remote('v2'));assert.deepEqual([...f.liveDocuments],['fixture']);
  const failed=await fixture(async()=>({liveDocuments:[source],activate(){throw Error('failure');}}));
  await failed.syncPluginRemotes(remote());assert.equal(failed.liveDocuments.size,0,'a failed activation leaves no provider');
});

test('a remote declaring live documents holds their surfaces only while it loads (RADD-1461)', async () => {
  const declaring = (url = 'v1') => [{ name: 'fixture', remote_entry: url, ui_api_version: '1.0', live_documents: ['page'] }];
  const source = { id: 'fixture.pages', entityType: 'page', open() {} };
  const wait = deferred();
  const f = await fixture(() => wait.promise);
  assert.deepEqual(f.arriving(), [false, []], 'before the manifest answers nothing is known, and every surface waits');
  const loading = f.syncPluginRemotes(declaring());
  assert.deepEqual(f.arriving(), [true, ['page']], 'the declared entity type is arriving while the import is pending');
  wait.resolve({ liveDocuments: [source] });
  await loading;
  assert.deepEqual(f.arriving(), [true, []], 'landed: the provider is registered and nothing is arriving');
  assert.deepEqual([...f.liveDocuments], ['fixture']);
  // A remote that fails releases the surface too: it runs its own editor, as if the plugin were off.
  const failing = await fixture(async () => { throw Error('fixture failure'); });
  await failing.syncPluginRemotes(declaring());
  assert.deepEqual(failing.arriving(), [true, []]);
  assert.equal(failing.readRemoteStates()[0].status, 'errored');
  // A remote declaring none holds nothing, even while it loads.
  const later = deferred();
  const plain = await fixture(() => later.promise);
  const plainLoading = plain.syncPluginRemotes(remote());
  assert.deepEqual(plain.arriving(), [true, []]);
  later.resolve({ contributions: [contribution] });
  await plainLoading;
});

test('bundled plugins register at boot, follow the enabled set, and never load as a remote (RADD-1373)', async () => {
  let registrations = 0;
  const core = { contributions: [contribution], activate: () => { registrations++; } };
  const imports = [];
  const loader = await fixture(async (url) => { imports.push(url); return { contributions: [contribution] }; }, { core });
  loader.syncStaticPlugins();
  assert(loader.slots.has('core'), 'registered before capabilities are known');
  loader.syncStaticPlugins(['core']);
  assert.equal(registrations, 1, 'idempotent while enabled');
  loader.syncStaticPlugins(['other']);
  assert(!loader.slots.has('core'), 'withdrawn when the server stops loading it');
  loader.syncStaticPlugins(['core']);
  assert(loader.slots.has('core') && registrations === 2, 're-registered once when it returns');
  await loader.syncPluginRemotes([{ name: 'core', remote_entry: 'x', ui_api_version: '1.0' }]);
  assert.deepEqual(imports, [], 'a bundled plugin is never imported as a remote');
  assert(loader.slots.has('core'));
});
