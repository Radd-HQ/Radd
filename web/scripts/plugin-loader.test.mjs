import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { stripTypeScriptTypes } from 'node:module';

let serial = 0;
async function fixture(importer) {
  const slots = new Set();
  const dataSources = new Set();
  const querySources = new Set();
  const key = `__pluginLoaderTest${serial++}`;
  globalThis[key] = {
    isUiApiCompatible: () => true,
    registerSlot: (_slot, _contribution, { plugin }) => slots.add(plugin),
    unregisterPlugin: (name) => slots.delete(name),
    registerQuerySource: (name) => querySources.add(name),
    unregisterQuerySources: (name) => querySources.delete(name),
    registerDataSource: (name) => dataSources.add(name),
    unregisterDataSources: (name) => dataSources.delete(name),
    importer,
  };
  const source = readFileSync('web/src/lib/plugin-loader.ts', 'utf8')
    .replace(/import \{[\s\S]*?\} from "@radd\/plugin-sdk";/,
      `const {isUiApiCompatible, registerSlot, unregisterPlugin, registerDataSource, unregisterDataSources, registerQuerySource, unregisterQuerySources} = globalThis.${key};`)
    .replace('import(/* @vite-ignore */ url)', `globalThis.${key}.importer(url)`);
  const js = stripTypeScriptTypes(source, { mode: 'transform' });
  const loader = await import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`);
  return { ...loader, slots, dataSources, querySources };
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


test('SDK version gate rejects remotes requiring newer APIs', async () => {
  const js = stripTypeScriptTypes(readFileSync('web/packages/plugin-sdk/src/version.ts','utf8'));
  const sdk = await import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`);
  for (const version of ['1.0.0','1.1.0','1.2.0','1.3.0',sdk.UI_API_VERSION]) assert(sdk.isUiApiCompatible(version));
  for (const version of ['2.0.0','1.999.0',sdk.UI_API_VERSION.replace(/\d+$/, n => String(Number(n) + 1)),'','1.garbage.0']) assert(!sdk.isUiApiCompatible(version));
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
