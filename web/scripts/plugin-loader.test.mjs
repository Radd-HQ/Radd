import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { stripTypeScriptTypes } from 'node:module';

let serial = 0;
async function fixture(importer) {
  const slots = new Set();
  const key = `__pluginLoaderTest${serial++}`;
  globalThis[key] = {
    isUiApiCompatible: () => true,
    registerSlot: (_slot, _contribution, { plugin }) => slots.add(plugin),
    unregisterPlugin: (name) => slots.delete(name),
    importer,
  };
  const source = readFileSync('web/src/lib/plugin-loader.ts', 'utf8')
    .replace(/import \{[\s\S]*?\} from "@radd\/plugin-sdk";/,
      `const {isUiApiCompatible, registerSlot, unregisterPlugin} = globalThis.${key};`)
    .replace('import(/* @vite-ignore */ url)', `globalThis.${key}.importer(url)`);
  const js = stripTypeScriptTypes(source, { mode: 'transform' });
  const loader = await import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`);
  return { ...loader, slots };
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
