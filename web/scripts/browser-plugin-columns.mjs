/**
 * RADD-1394: plugins contribute list columns and board-card cells (SDK 1.15 `itemAttribute`), and
 * the SLA timer is the first — drawn by the REAL slas remote over a mocked API:
 *
 *   - with slas listed, the list renders the SLA column from the remote, the board card shows its
 *     cell, and the card designer's palette offers it (its sample in the preview);
 *   - the batch source is asked ONCE per page of rows, and a second surface over the same rows
 *     shares that read;
 *   - a rogue plugin cannot claim `slas.timer`, a `cf.` id or a builtin — only its own namespace;
 *   - dropping slas from capabilities withdraws column, cell and palette entry, aborts the
 *     in-flight batch, and the saved view (which still names `slas.timer`) shows it unavailable;
 *   - re-listing restores it all with exactly one fresh read.
 */
import assert from 'node:assert/strict';
import http from 'node:http';
import { readFileSync, existsSync, statSync } from 'node:fs';
import { mkdtemp } from 'node:fs/promises';
import path from 'node:path';
import { openBrowser } from './lib/cdp.mjs';
import { CORE_PLUGINS } from './lib/core-plugins.mjs';

const root = new URL('../../', import.meta.url).pathname, dist = path.join(root, 'web/dist');
const OPTIONAL = new Set(['slas', 'rogue']);
const enabled = new Set([...CORE_PLUGINS, ...OPTIONAL]);
const batches = [], aborted = [], writes = [], pending = [], unknown = new Set(), checks = [];
let hold = false;

const project = { id: 'project-1', key: 'TEST', name: 'Service desk', description: '', permissions: ['item.read', 'item.update', 'item.create', 'view.update', 'project.manage'], public: false, contributions: false, created_at: '2026-09-01T00:00:00Z' };
const states = [
  { id: 's-todo', name: 'Todo', category: 'todo', position: 0, color: null, project_id: 'project-1' },
  { id: 's-doing', name: 'In Progress', category: 'in_progress', position: 1, color: null, project_id: 'project-1' },
  { id: 's-done', name: 'Done', category: 'done', position: 2, color: null, project_id: 'project-1' },
];
const item = (n, stateIndex, title) => ({
  id: `item-${n}`, project_id: 'project-1', key: `TEST-${n}`, number: n, kind: 'issue', title, description: '',
  state: { id: states[stateIndex].id, name: states[stateIndex].name, category: states[stateIndex].category },
  priority: 'normal', labels: [], parent: null, assignee: null, reporter: null, team: null, type: null,
  child_count: 0, comment_count: 0, start_date: null, target_date: null, cycle: null, release: null,
  flagged: false, starred: false, estimate_points: null, custom_fields: {}, visibility: 'public',
  rank: `0|${n}`, created_at: '2026-09-20T09:00:00Z', updated_at: '2026-09-25T09:00:00Z',
});
const items = [item(1, 0, 'Printer on fire'), item(2, 0, 'VPN drops hourly'), item(3, 1, 'Nice to have: dark mode')];
const timer = (patch) => ({ policy_name: 'Gold', kind: 'response', due_at: '2026-09-26T18:00:00Z', met_at: null, breached: false, paused: false, remaining_seconds: null, ...patch });
const SLA = { 'item-1': [timer({ breached: true })], 'item-2': [timer({ remaining_seconds: 5400 }), timer({ kind: 'resolution', remaining_seconds: 90000 })] };
const view = (id, name, patch) => ({
  id, project_id: 'project-1', name, view_type: 'list', query: '', group_by: null, swimlane_by: null, cycle_filter: null,
  quick_filters: [], wip_limits: null, columns: null, card_layout: null, column_order: null, swimlane_order: null,
  collapse_empty_columns: false, hidden_columns: null, owner_id: null, owner: null, global_access: 'editor', shares: [],
  shared: true, can_edit: true, can_manage: true, position: 0, query_string: 'project_id=project-1',
  created_at: '2026-09-01T00:00:00Z', updated_at: '2026-09-01T00:00:00Z', ...patch,
});
const views = {
  'view-list': view('view-list', 'SLA list', { columns: ['priority', 'slas.timer', 'state'] }),
  'view-board': view('view-board', 'SLA board', { view_type: 'board', group_by: 'state', position: 1, card_layout: { v: 1, max_labels: 3, cells: [
    { attr: 'title', row: 1, col: 0, span: 8, align: 'start' },
    { attr: 'slas.timer', row: 2, col: 0, span: 2, align: 'start' },
    { attr: 'assignee', row: 2, col: 7, span: 1, align: 'end' },
  ] } }),
};
// A second optional plugin that tries to claim ids that are not its own. Only `rogue.valid` may
// appear; its `slas.timer` must never draw into the SLA cells.
const rogue = `import{createElement as h}from'react';import{definePlugin,itemAttribute}from'@radd/plugin-sdk';
const cell=()=>h('span',{'data-rogue':1},'ROGUE');
const attr=(id,label)=>itemAttribute({id,label,width:90,minWidth:60,source:'rogue.values',render:cell});
export default definePlugin({querySources:[{key:'rogue.values',fetch:async()=>({})}],contributions:[
 attr('slas.timer','Rogue shadow'),attr('cf.cost','Rogue field'),attr('title','Rogue title'),attr('rogue','Rogue bare'),attr('rogue.valid','Rogue valid')]});`;

function grouped(url) {
  const column = url.searchParams.get('column_key');
  const base = { total_groups: states.length, lane_totals: { __all__: items.length }, column_points: null, lane_labels: { __all__: '__all__' }, epic_refs: {},
    column_totals: Object.fromEntries(states.map((s) => [s.id, items.filter((i) => i.state.id === s.id).length])),
    column_labels: Object.fromEntries(states.map((s) => [s.id, s.id])) };
  if (url.searchParams.get('summary_only') === 'true') return { ...base, cells: [] };
  return { ...base, cells: [{ column, lane: '__all__', items: items.filter((i) => i.state.id === column), next_cursor: null }] };
}

function api(req, url, body) {
  const p = url.pathname.replace(/^\/api\/v1/, '');
  if (p === '/auth/me') return { id: 'admin', name: 'Admin', email: 'admin@example.test', instance_role: 'admin', global_role: 'admin', permissions: ['*'], preferences: {} };
  if (p === '/capabilities') return { capabilities: [], plugins: [...enabled], nav: [], widget_types: [], view_types: [],
    remotes: [...enabled].filter((n) => OPTIONAL.has(n)).map((name) => ({ name, remote_entry: `/plugins/${name}/remoteEntry.js`, ui_api_version: '1.15.0' })) };
  if (p === '/items/sla/batch') {
    batches.push({ ids: [...body.item_ids] });
    return Object.fromEntries(body.item_ids.filter((id) => SLA[id]).map((id) => [id, SLA[id]]));
  }
  if (p === '/items/grouped') return grouped(url);
  if (p === '/items/ids') return { ids: items.map((i) => i.id), total: items.length };
  if (p === '/items/count') return { total: items.length };
  if (p === '/items') return items;
  if (p.startsWith('/views/') && views[p.split('/')[2]]) return views[p.split('/')[2]];
  if (p === '/views') return Object.values(views);
  if (p === '/projects/by-key/TEST' || p === '/projects/project-1') return project;
  if (p === '/projects') return [project];
  if (p === '/states' || p.startsWith('/states')) return states;
  if (p === '/instance') return { work_week_days: ['mon', 'tue', 'wed', 'thu', 'fri'], timelog_hours_per_day: 8, timelog_days_per_week: 5 };
  if (p.includes('notifications')) return { items: [], notifications: [], unread_count: 0, total: 0 };
  if (p.endsWith('/summary')) return { total: 0, related_count: 0, permissions: [] };
  if (p.includes('preferences') || p.includes('contribution-settings')) return {};
  if (!['/fields', '/cycles', '/users', '/labels', '/teams', '/issue-types', '/releases'].some((known) => p.startsWith(known))) unknown.add(`${req.method} ${p}`);
  return [];
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://fixture'), p = url.pathname;
  if (p.startsWith('/plugins/')) {
    const [, , name, ...parts] = p.split('/');
    const file = path.join(root, 'server/src/radd/modules', name, 'ui/dist', ...parts);
    res.setHeader('content-type', 'text/javascript');
    if (name === 'rogue') return res.end(rogue);
    if (!existsSync(file)) { res.statusCode = 404; return res.end(); }
    return res.end(readFileSync(file));
  }
  if (p.startsWith('/api/')) {
    let raw = ''; for await (const chunk of req) raw += chunk;
    const body = raw ? JSON.parse(raw) : null;
    if (!['GET', 'HEAD'].includes(req.method) && !/sla\/batch|preferences/.test(p)) writes.push(`${req.method} ${p}`);
    const data = api(req, url, body);
    if (p.endsWith('/items/sla/batch')) res.on('close', () => { if (!res.writableEnded) aborted.push(body.item_ids); });
    const finish = () => {
      if (res.destroyed) return;
      res.setHeader('content-type', 'application/json'); res.end(JSON.stringify(data));
    };
    if (hold && p.endsWith('/items/sla/batch')) pending.push(finish); else finish();
    return;
  }
  const file = path.join(dist, p), target = existsSync(file) && statSync(file).isFile() ? file : path.join(dist, 'index.html');
  res.setHeader('content-type', target.endsWith('.js') ? 'text/javascript' : target.endsWith('.css') ? 'text/css' : 'text/html');
  res.end(readFileSync(target));
});

await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
let browser;
try {
  browser = await openBrowser({ port: 18863, profile: await mkdtemp('/tmp/radd-plugin-columns-'), scale: 1 });
  const s = browser.session;
  const origin = `http://127.0.0.1:${server.address().port}`;
  const until = async (fn, label) => { for (let i = 0; i < 250; i++) { if (await fn()) return; await new Promise((r) => setTimeout(r, 40)); } throw Error(`${label}: ${await s.eval('document.body?.innerText ?? ""')} ${JSON.stringify(s.consoleErrors)} unknown=${[...unknown]}`); };
  const count = (selector) => s.eval(`document.querySelectorAll(${JSON.stringify(selector)}).length`);
  const text = (selector) => s.eval(`document.querySelector(${JSON.stringify(selector)})?.textContent?.trim() ?? null`);
  const refresh = () => s.eval("void window.__RADD_QUERY_CLIENT__.invalidateQueries({queryKey:['capabilities']})");
  const go = (to) => s.eval(`(() => { history.pushState({}, '', ${JSON.stringify(to)}); dispatchEvent(new PopStateEvent('popstate')); })()`);
  const cellOfRow = (key) => s.eval(`(() => { const row = [...document.querySelectorAll('li')].find((li) => li.textContent.includes(${JSON.stringify(key)}));
    const cells = row ? [...row.children].filter((el) => el.style.flexBasis) : [];
    const header = [...document.querySelectorAll('[data-column]')].map((el) => el.dataset.column);
    const cell = cells[header.indexOf('slas.timer')];
    return cell ? { text: cell.textContent.trim(), chip: cell.querySelector('[data-sla-chip]')?.dataset.slaChip ?? null } : null; })()`);
  // The match runs in the page, so it is built from source rather than closing over `label`.
  const button = (label) => s.click('button', new Function('text', `return text.trim() === ${JSON.stringify(label)}`));
  const openDisplay = async () => { await button('Display'); await until(() => s.eval("!!document.querySelector('[role=dialog], [data-popover]') || document.body.innerText.includes('Columns') || document.body.innerText.includes('Card layout')"), 'display menu'); };
  const closeOverlays = () => s.send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 }).then(() => s.send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 }));

  // 1. The list: the column comes from the remote, one batch per page of rows.
  await s.navigate(`${origin}/p/TEST/v/view-list`);
  await until(async () => (await count('[data-column="slas.timer"]')) === 1 && (await count('[data-sla-cell]')) === 2, 'SLA column rendered');
  assert.equal(await text('[data-column="slas.timer"]'), 'SLA');
  assert.deepEqual(await cellOfRow('TEST-1'), { text: 'Breached', chip: 'breached' });
  assert.deepEqual(await cellOfRow('TEST-2'), { text: '1h 30m left', chip: 'ticking' }, 'the nearest-to-breach timer of two');
  assert.deepEqual(await cellOfRow('TEST-3'), { text: '—', chip: null }, 'an item the batch did not answer shows the dash');
  assert.equal(batches.length, 1, 'one batch for the page of rows');
  assert.deepEqual(batches[0].ids, ['item-1', 'item-2', 'item-3']);
  assert.equal(await count('[data-rogue]'), 0, 'a rogue plugin claiming slas.timer draws nothing into its cells');
  checks.push('the list renders the SLA column from the slas remote (breached, nearest ticking, dash), asking the batch once per page');

  // The moved chips now use the status tier: text against its tint over the row, both themes.
  const contrast = () => s.eval(`[...document.querySelectorAll('[data-sla-chip]')].map((chip) => {
    const rgba = (css) => { const c = document.createElement('canvas').getContext('2d'); c.fillStyle = css; c.fillRect(0, 0, 1, 1); return [...c.getImageData(0, 0, 1, 1).data].map((v, i) => i === 3 ? v / 255 : v); };
    let under = null; for (let el = chip.parentElement; el && !under; el = el.parentElement) { const bg = rgba(getComputedStyle(el).backgroundColor); if (bg[3] === 1) under = bg; }
    const tint = rgba(getComputedStyle(chip).backgroundColor), fill = under.slice(0, 3).map((u, i) => tint[i] * tint[3] + u * (1 - tint[3]));
    const lum = (rgb) => rgb.slice(0, 3).map((v) => { v /= 255; return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }).reduce((sum, v, i) => sum + v * [0.2126, 0.7152, 0.0722][i], 0);
    const a = lum(rgba(getComputedStyle(chip).color)), b = lum(fill);
    return [chip.dataset.slaChip, Math.round(((Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)) * 100) / 100]; })`);
  const dark = await contrast();
  await s.eval("document.documentElement.classList.add('light')"); await new Promise((r) => setTimeout(r, 300));
  const light = await contrast();
  await s.screenshot('/tmp/radd-plugin-columns-light.png');
  await s.eval("document.documentElement.classList.remove('light')"); await new Promise((r) => setTimeout(r, 300));
  for (const [state, ratio] of [...dark, ...light]) assert(ratio >= 4.5, `${state} chip contrast ${ratio} (dark ${JSON.stringify(dark)}, light ${JSON.stringify(light)})`);
  checks.push(`SLA chips hold 4.5:1 in both themes (dark ${dark.map((d) => d.join(' ')).join(', ')}; light ${light.map((d) => d.join(' ')).join(', ')})`);

  await openDisplay();
  await s.click('button[aria-label="Add a column"]');
  await until(async () => (await count('[role=option]')) > 3, 'column options');
  const offered = await s.eval("[...document.querySelectorAll('[role=option]')].map((el) => el.textContent.trim())");
  assert(offered.includes('Rogue valid'), `a plugin's own namespaced attribute is offered: ${offered}`);
  for (const refused of ['Rogue shadow', 'Rogue field', 'Rogue title', 'Rogue bare']) assert(!offered.includes(refused), `${refused} refused`);
  assert(!offered.includes('SLA'), 'SLA is already a column, so not offered twice');
  const listed = await s.eval("[...document.querySelectorAll('li')].map((li) => li.textContent.trim()).filter((t) => t === 'SLA')");
  assert.equal(listed.length, 1, 'the columns editor lists SLA by its label');
  await closeOverlays(); await closeOverlays();
  checks.push('the columns picker offers contributed attributes and refuses ids outside the plugin namespace (a builtin, cf.*, another plugin, a bare name)');

  // 2. The board over the same rows: the card cell, and the batch is shared, not re-asked.
  await go('/p/TEST/v/view-board');
  await until(async () => (await count('[data-sla-cell]')) === 2 && (await count('[role=button][draggable=true]')) === 3, 'board cards with SLA cells');
  const cardChips = await s.eval("[...document.querySelectorAll('[role=button][draggable=true]')].map((card) => [card.textContent.match(/TEST-\\d/)?.[0], card.querySelector('[data-sla-chip]')?.dataset.slaChip ?? null])");
  assert.deepEqual(Object.fromEntries(cardChips), { 'TEST-1': 'breached', 'TEST-2': 'ticking', 'TEST-3': null });
  assert.equal(batches.length, 1, 'the board shares the list\'s read of the same rows');
  await s.screenshot('/tmp/radd-plugin-columns-board.png');
  checks.push('board cards draw the SLA cell from the remote (no cell for an item without timers), sharing the one batch');

  // 3. The card designer: palette offers it, the preview shows the owner's sample.
  await openDisplay();
  await button('Design card…');
  await until(() => s.eval("!!document.querySelector('[data-palette-group=plugins]')"), 'designer palette');
  const palette = await s.eval("[...document.querySelectorAll('[data-palette-group=plugins] button')].map((b) => [b.textContent.trim(), b.disabled]).sort()");
  assert.deepEqual(palette, [['Rogue valid', false], ['SLA', true]], 'placed SLA dims; the rogue\'s own attribute is offered');
  assert.equal(await s.eval("document.querySelector('[role=dialog] [data-sla-chip]')?.textContent"), '4h 0m left', 'the preview renders the declared sample');
  await new Promise((r) => setTimeout(r, 400)); // past the modal's fade-in
  await s.screenshot('/tmp/radd-plugin-columns-designer.png');
  await button('Cancel');
  checks.push('the card designer palette offers contributed attributes under "From plugins" and previews the owner\'s sample');

  // 4. Withdrawal: an in-flight read is aborted; column, cell and palette entry go; saved ids stay.
  await go('/p/TEST/v/view-list');
  await until(async () => (await count('[data-sla-cell]')) === 2, 'back on the list');
  hold = true;
  await s.eval("void window.__RADD_QUERY_CLIENT__.invalidateQueries({queryKey:['plugin-query','slas']})");
  await until(() => pending.length > 0, 'a batch read in flight');
  const before = batches.length;
  enabled.delete('slas'); await refresh();
  await until(async () => (await count('[data-column="slas.timer"]')) === 0, 'column withdrawn');
  await until(() => aborted.length > 0, 'in-flight batch aborted');
  hold = false; while (pending.length) pending.shift()();
  assert.equal(await count('[data-sla-cell]'), 0);
  assert.equal(await s.eval("[...document.querySelectorAll('li')].filter((li) => /TEST-\\d/.test(li.textContent)).length"), 3, 'the rows still render');
  await openDisplay();
  await until(() => s.eval("!!document.querySelector('[data-unavailable-column=\"slas.timer\"]')"), 'unavailable column in the editor');
  assert.equal(await text('[data-unavailable-column="slas.timer"]'), 'slas.timer (unavailable)');
  await closeOverlays();
  await go('/p/TEST/v/view-board');
  await until(async () => (await count('[role=button][draggable=true]')) === 3, 'board without slas');
  assert.equal(await count('[data-sla-cell]'), 0, 'no SLA cell on cards');
  await openDisplay(); await button('Design card…');
  await until(() => s.eval("!!document.querySelector('[data-stale-attrs]')"), 'stale note');
  assert.match(await text('[data-stale-attrs]'), /slas\.timer/);
  assert.deepEqual(await s.eval("[...document.querySelectorAll('[data-palette-group=plugins] button')].map((b) => b.textContent.trim())"), ['Rogue valid']);
  await button('Cancel');
  assert.equal(batches.length, before, 'nothing asks a withdrawn source');
  assert.deepEqual(views['view-list'].columns, ['priority', 'slas.timer', 'state']);
  assert.deepEqual(writes, [], 'the saved view and layout were never rewritten');
  checks.push('withdrawing slas aborts the in-flight batch and removes column, card cell and palette entry; the saved view keeps slas.timer and shows it unavailable');

  // 5. Re-listing restores it with exactly one fresh read.
  await go('/p/TEST/v/view-list');
  await until(async () => (await count('li')) > 0, 'list again');
  enabled.add('slas'); await refresh();
  await until(async () => (await count('[data-column="slas.timer"]')) === 1 && (await count('[data-sla-cell]')) === 2, 'SLA column restored');
  await new Promise((r) => setTimeout(r, 600));
  assert.equal(batches.length, before + 1, 'exactly one fresh read');
  checks.push('re-listing slas restores the column with exactly one fresh batch read');

  await s.screenshot('/tmp/radd-plugin-columns.png');
  assert.deepEqual(s.consoleErrors.filter((e) => /TypeError|Minified React error|Invalid hook|Uncaught|EXCEPTION/.test(e)), []);
  console.log(JSON.stringify({ passed: true, checks, batches: batches.length, aborted: aborted.length, unknown: [...unknown] }, null, 1));
} finally {
  hold = false; while (pending.length) pending.shift()();
  await browser?.close(); server.closeAllConnections(); await new Promise((resolve) => server.close(resolve));
}
