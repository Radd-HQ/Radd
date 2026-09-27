/** AST boundary checks. Ownership coverage remains in the complete audit ledger. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, existsSync } from 'node:fs';
import path from 'node:path';
import { parse } from '@babel/parser';

function files(root) {
  return readdirSync(root,{withFileTypes:true}).flatMap(entry => {
    if (['node_modules','dist','.git','__pycache__'].includes(entry.name)) return [];
    const name = path.join(root,entry.name);
    return entry.isDirectory()?files(name):/\.(ts|tsx)$/.test(name)?[name]:[];
  });
}
function nodes(file) {
  const result=[];
  function walk(node) {
    if (!node || typeof node!=='object') return;
    if (typeof node.type==='string') result.push(node);
    for (const value of Object.values(node)) {
      if (Array.isArray(value)) value.forEach(walk);
      else if (value && typeof value==='object') walk(value);
    }
  }
  walk(parse(readFileSync(file,'utf8'),{sourceType:'module',plugins:['typescript','jsx']}));
  return result;
}

test('plugin UI imports stay inside its own bundle or public packages',()=>{
  const violations=[];
  for (const file of [...files('server/src/radd/modules'),...files('examples')]) {
    if (!file.includes('/ui/src/')) continue;
    const root=path.resolve(file.split('/ui/src/')[0]+'/ui');
    for (const node of nodes(file)) {
      const source=node.source?.value ?? (node.type==='CallExpression'&&node.callee.type==='Import'?node.arguments[0]?.value:undefined);
      if (typeof source!=='string' || !source.startsWith('.')) continue;
      const resolved=path.resolve(path.dirname(file),source);
      if (!resolved.startsWith(root+path.sep)) violations.push(`${file}:${node.loc.start.line}: ${source}`);
    }
  }
  assert.deepEqual(violations,[]);
});

test('Leave owns its endpoint vocabulary; host integrations use generic data contracts',()=>{
  const violations=[];
  for (const file of files('web/src')) {
    for (const node of nodes(file)) {
      if (node.type==='StringLiteral' && (/^\/leave(?:\/|$)/.test(node.value) || node.value==='leave')) {
        violations.push(`${file}:${node.loc.start.line}: ${node.value}`);
      }
    }
  }
  assert.deepEqual(violations,[]);
});

test('Scripts and Monitoring settings have no host-owned routes or endpoint vocabulary',()=>{
  const violations=[];
  for (const file of files('web/src')) for (const node of nodes(file)) {
    if (node.type==='StringLiteral' && /^(?:\/(?:settings\/)?(?:scripts|monitoring)(?:\/|$)|(?:scripts|monitoring)$)/.test(node.value)) {
      violations.push(`${file}:${node.loc.start.line}: ${node.value}`);
    }
  }
  assert.deepEqual(violations,[]);
});

test('sso owns its provider registry; the host keeps only the pre-sign-in login buttons',()=>{
  // RADD-1380: the registry is the plugin's section of the host's Sign-in page. `/auth/sso/providers`
  // (the unauthenticated login buttons) is the one sso path the host may name.
  const violations=[];
  for (const file of files('web/src')) for (const node of nodes(file)) {
    if (node.type==='StringLiteral' && (/^\/sso(?:\/|$)/.test(node.value) || ['sso','sso_provider'].includes(node.value))) {
      violations.push(`${file}:${node.loc.start.line}: ${node.value}`);
    }
  }
  assert.deepEqual(violations,[]);
  assert(!existsSync('web/src/components/settings/signin'),'the provider panel is the sso remote');
});

test('Monitoring UI consumes contributions instead of importing AI or mail features',()=>{
  const violations=[];
  for (const file of files('server/src/radd/modules/monitoring/ui/src')) for(const node of nodes(file)) {
    if (node.type==='StringLiteral' && /^(?:\/(?:ai|mail)(?:\/|$)|(?:ai|mailintake)(?:\.|$))/.test(node.value)) violations.push(`${file}: ${node.value}`);
  }
  assert.deepEqual(violations,[]);
});

test('Settings → AI is the ai plugin\'s page: the host has no route, registry endpoint or query for it (RADD-1379)',()=>{
  for (const file of ['web/src/routes/settings/ai.tsx','web/src/lib/queries/ai-admin.ts',
    ...['Features','Presets','Providers','Roles'].map(name=>`web/src/components/settings/Ai${name}Section.tsx`)]) assert(!existsSync(file),file);
  const violations=[];
  for (const file of files('web/src')) for (const node of nodes(file)) {
    if (node.type==='StringLiteral' && /^\/(?:settings\/ai|ai\/(?:providers|roles|presets|local-embed|embeddings))(?:\/|$)/.test(node.value)) {
      violations.push(`${file}:${node.loc.start.line}: ${node.value}`);
    }
  }
  assert.deepEqual(violations,[]);
  const page=files('server/src/radd/modules/ai/ui/src').flatMap(nodes);
  assert(page.some(n=>n.type==='StringLiteral'&&n.value==='/settings/ai'),'the remote contributes the page');
});


test('host directory adapter owns no queries or feature implementation',()=>{
  // RADD-1375: the compatibility adapter is gone; callers use the SDK DirectorySelect directly.
  assert(!existsSync('web/src/components/PeopleDirectorySelect.tsx'));
  assert(!readFileSync('web/src/lib/queries/users.ts','utf8').includes('peopleChoicesQuery'));
});

test('directory query providers belong to Auth or Teams, not the SDK control',()=>{
  const sdk=readFileSync('web/packages/plugin-sdk/src/directory.tsx','utf8');
  assert(!/\/(?:users|teams)|auth\.people|teams\.candidates/.test(sdk));
});

test('automation canvas is contributed; graph queries and algorithms belong to Automations',()=>{
  assert(!existsSync('web/src/components/automations/LazyGraphCanvas.tsx'));
  for(const file of ['web/src/lib/node-shapes.ts','web/src/lib/automation-layout.ts','web/src/lib/automation-nodes.ts','web/src/lib/automation-outputs.ts','web/src/components/automations/node-visuals.ts']) assert(!existsSync(file), file);
  const owner=nodes('server/src/radd/modules/automations/ui/src/node-shapes.ts');
  assert(!owner.some(n=>n.type==='CallExpression'&&n.callee?.name==='useSyncExternalStore'),'shapes must not use a global mutable store');
});

test('shared control implementations have no feature component dependencies',()=>{
  const forbidden=[];
  for(const file of ['web/src/host-components.tsx','web/src/components/CodeEditor.tsx','web/src/lib/code-languages.ts','web/src/lib/code-highlight.ts']) for(const node of nodes(file)){
    const source=node.source?.value??(node.type==='CallExpression'&&node.callee.type==='Import'?node.arguments[0]?.value:undefined);
    if(typeof source==='string'&&(/(?:automations|scripts|components\/editor)\//.test(source)||source.includes('@milkdown')))forbidden.push(`${file}: ${source}`);
  }
  assert.deepEqual(forbidden,[]);
  assert(!files('web/src').some(f=>f.endsWith('/SchemaFields.tsx')||f.endsWith('/PythonEditor.tsx')));
  for(const file of ['web/packages/plugin-sdk/src/schema-form.tsx','web/packages/plugin-sdk/src/schema-defaults.ts']) for(const node of nodes(file)){
    if(node.type==='ImportDeclaration')assert(!/automation|scripts|web\/src|\/modules\//.test(node.source.value));
  }
});

test('generic option controls have no feature endpoints or owner catalog',()=>{
  const controls=nodes('web/packages/plugin-sdk/src/options.tsx');
  assert(!controls.some(n=>n.type==='ImportDeclaration'&&n.importKind!=='type'&&/api|web\/src|modules/.test(n.source.value)));
  assert(!controls.some(n=>n.type==='StringLiteral'&&/^\/(?:users|teams|roles|states|issue-types|releases|forms|page-spaces|groups)/.test(n.value)));
  assert(!existsSync('web/src/components/DirectoryChoices.tsx'),'the Choices alias is gone (RADD-1375)');
  const legacy=nodes('web/src/lib/queries/options.ts');
  assert(!legacy.some(n=>n.type==='CallExpression'||n.type==='FunctionDeclaration'||n.type==='ArrowFunctionExpression'));
});

test('all former option resources are declared only by their owning remote',()=>{
  const owners={auth:['users','users/directory','roles','roles/assignable'],teams:['teams','teams/directory'],workflow:['states'],itemtypes:['issue-types'],releases:['releases'],forms:['forms'],pages:['page-spaces'],groups:['groups']};
  for(const [owner,resources] of Object.entries(owners)){
    const ast=nodes(`server/src/radd/modules/${owner}/ui/src/options.ts`);
    const declared=ast.filter(n=>n.type==='ObjectProperty'&&n.key.name==='resource').map(n=>n.value.value);
    assert.deepEqual(declared,resources);
    const endpoints=ast.filter(n=>n.type==='StringLiteral'&&n.value.startsWith('/')).map(n=>n.value);
    assert.deepEqual([...new Set(endpoints)],resources.map(r=>`/${r}/options`));
  }
});

test('project and cycle picker host paths contain only contribution adapters',()=>{
  const filesToCheck=['web/src/components/projects/ProjectSelect.tsx','web/src/components/projects/ProjectPicker.tsx','web/src/components/cycles/CycleSelect.tsx'];
  for(const file of filesToCheck){
    const ast=nodes(file);
    const imports=ast.filter(n=>n.type==='ImportDeclaration').map(n=>n.source.value);
    assert(imports.every(s=>s==='@radd/plugin-sdk'||s.endsWith('/picker-contract')),file);
    assert(!ast.some(n=>n.type==='CallExpression'&&['useQuery','useMutation','useState'].includes(n.callee?.name)),file);
  }
  for(const file of ['web/packages/plugin-sdk/src/paged-directory.ts','web/packages/plugin-sdk/src/switch.tsx']){
    assert(!nodes(file).some(n=>n.type==='ImportDeclaration'&&/modules|web\/src/.test(n.source.value)));
    assert(!nodes(file).some(n=>n.type==='StringLiteral'&&/^\/(?:projects|cycles)/.test(n.value)));
  }
});


test('team relationship adapters own no reference queries, selection state or feature copy',()=>{
  for(const file of ['web/src/components/teams/TeamSelect.tsx','web/src/components/teams/TeamAudience.tsx']) {
    const ast=nodes(file);
    assert(ast.filter(n=>n.type==='ImportDeclaration').every(n=>n.source.value==='@radd/plugin-sdk'||n.source.value.endsWith('/relationship-contract')),file);
    assert(!ast.some(n=>n.type==='CallExpression'&&['useQuery','useQueries','useState'].includes(n.callee?.name)),file);
  }
  for(const file of files('server/src/radd/modules/teams/ui/src')) {
    assert(!readFileSync(file,'utf8').includes('internal notes'),file+' must not own comment policy copy');
  }
});

test('Fields owns registry form rendering and the SDK token/error primitives are domain-independent',()=>{
  const adapter=nodes('web/src/components/items/CustomFieldsForm.tsx');
  assert(adapter.filter(n=>n.type==='ImportDeclaration').every(n=>n.source.value==='@radd/plugin-sdk'||n.source.value.endsWith('/control-contract')));
  assert(!adapter.some(n=>n.type==='SwitchStatement'||n.type==='CallExpression'&&['useQuery','useState'].includes(n.callee?.name)));
  for(const file of ['web/src/components/TokenMultiSelect.tsx','web/src/components/ErrorText.tsx']) assert(!existsSync(file),`${file} re-exported the SDK (RADD-1375)`);
  for(const file of ['web/packages/plugin-sdk/src/token-multi-select.tsx','web/packages/plugin-sdk/src/error-text.tsx']){
    assert(!nodes(file).some(n=>n.type==='ImportDeclaration'&&/modules|web\/src|components\//.test(n.source.value)));
  }
});


test('catalog transport belongs to owners and contributed-query registry has no feature vocabulary',()=>{
  const sdk=nodes('web/packages/plugin-sdk/src/query-sources.ts');
  assert(!sdk.some(n=>n.type==='ImportDeclaration'&&/modules|web\/src/.test(n.source.value)));
  assert(!sdk.some(n=>n.type==='StringLiteral'&&/^(?:fields|labels)(?:\.|$)|^\/(?:fields|labels)/.test(n.value)));
  const consumer=nodes('server/src/radd/modules/automations/ui/src/ActionsBuilder.tsx');
  assert(!consumer.some(n=>n.type==='ImportDeclaration'&&n.source.value.includes('/queries')));
  assert(!consumer.some(n=>n.type==='CallExpression'&&n.callee?.name==='useQuery'));
});

test('schedule arithmetic UI is generic and both owners supply their own transport',()=>{
  for(const file of ['web/packages/plugin-sdk/src/schedule.ts','web/packages/plugin-sdk/src/schedule-editor.tsx']){
    const ast=nodes(file);
    assert(!ast.some(n=>n.type==='ImportDeclaration'&&/api|modules|web\/src/.test(n.source.value)),file);
    assert(!ast.some(n=>n.type==='StringLiteral'&&/automations|backups|Create issue/.test(n.value)),file);
  }
  assert(!files('web/src').includes('web/src/components/ScheduleEditor.tsx'));
  // The host reaches Backup's editor through a thin slot adapter. Automations' editor is drawn only
  // inside its own bundled package, so the host has no adapter for it at all.
  assert(!existsSync('web/src/components/automations'),'the host keeps no automations adapter');
  const adapter=nodes('web/src/components/backup/ScheduleEditor.tsx');
  const adapterImports=adapter.filter(n=>n.type==='ImportDeclaration').map(n=>n.source.value);
  assert(adapterImports.length>0&&adapterImports.every(s=>s==='@radd/plugin-sdk'||s.endsWith('/schedule-contract')),adapterImports.join());
  assert(!adapter.some(n=>n.type==='CallExpression'&&['useState','useEffect','useQuery'].includes(n.callee?.name)));
  // Each owner's implementation: the SDK's generic editor and its own contract, over its own endpoint.
  for(const owner of ['automations','backup']){
    const implementation=nodes(`server/src/radd/modules/${owner}/ui/src/ScheduleEditor.tsx`);
    const imports=implementation.filter(n=>n.type==='ImportDeclaration').map(n=>n.source.value);
    assert(imports.includes('@radd/plugin-sdk')&&imports.every(s=>s==='@radd/plugin-sdk'||s==='./schedule-contract'),`${owner}: ${imports}`);
    assert(!implementation.some(n=>n.type==='CallExpression'&&['useState','useEffect','useQuery'].includes(n.callee?.name)),owner);
    const endpoints=implementation.filter(n=>n.type==='StringLiteral'&&n.value.startsWith('/')).map(n=>n.value);
    assert.deepEqual(endpoints,[owner==='backup'?'/backups/schedule/preview':'/automations/schedule/preview']);
  }
});

test('audit navigation has no feature destination table or entity-specific routing branches',()=>{
  const ast=nodes('server/src/radd/modules/audit/ui/src/audit.ts');
  assert(ast.filter(n=>n.type==='ImportDeclaration').every(n=>n.source.value==='./types'||n.source.value==='@tanstack/react-router'));
  assert(!ast.some(n=>n.type==='StringLiteral'&&/^\/(?:settings|issues|pages|p\/)/.test(n.value)));
  assert(!ast.some(n=>n.type==='MemberExpression'&&n.property?.name==='entity_type'));
});


test('Audit is contributed: host has no page, endpoint, access decision or footer implementation',()=>{
  assert(!files('web/src').includes('web/src/routes/settings/audit.tsx'));
  for(const file of files('web/src')) for(const node of nodes(file)) {
    if(node.type==='StringLiteral') assert(!/^\/(?:settings\/)?audit(?:\/|$)/.test(node.value), file);
  }
  for(const file of ['web/src/components/history/ChangeHistoryPanel.tsx','web/src/components/settings/SettingsPage.tsx']){
    assert(!nodes(file).some(n=>n.type==='CallExpression'&&['useQuery','usePermissions'].includes(n.callee?.name)),file);
  }
  for(const file of ['web/packages/plugin-sdk/src/ChangeLines.tsx','web/packages/plugin-sdk/src/changes.ts']){
    assert(!nodes(file).some(n=>n.type==='StringLiteral'&&/^(?:item|flagged|priority|links|subject|role|scope)$/.test(n.value)),file);
    assert(!nodes(file).some(n=>n.type==='ImportDeclaration'&&/modules|web\/src/.test(n.source.value)),file);
  }
});

test('cross-plugin public imports resolve through declared package exports, never private source',()=>{
  const packages=new Map();
  for(const folder of readdirSync('server/src/radd/modules',{withFileTypes:true}).filter(entry=>entry.isDirectory()).map(entry=>entry.name)) {
    const file=`server/src/radd/modules/${folder}/ui/package.json`;
    try {const pkg=JSON.parse(readFileSync(file,'utf8'));packages.set(pkg.name,{pkg,root:path.dirname(file)});}catch(error){if(error.code!=='ENOENT')throw error;}
  }
  for(const file of files('server/src/radd/modules')){
    if(!file.includes('/ui/src/'))continue;
    const consumer=JSON.parse(readFileSync(file.split('/ui/src/')[0]+'/ui/package.json','utf8'));
    for(const node of nodes(file)){
      const source=node.source?.value;
      if(typeof source!=='string'||!source.startsWith('@radd-plugin-ui/'))continue;
      const [scope,name,...subpath]=source.split('/');const packageName=scope+'/'+name;
      const provider=packages.get(packageName);assert(provider,source);
      assert(consumer.dependencies?.[packageName],file+' must declare its dependency');
      const exported=provider.pkg.exports?.['./'+subpath.join('/')];assert(typeof exported==='string',source+' must be a public export');
      const entry=path.resolve(provider.root,exported);assert(entry.startsWith(path.resolve(provider.root)+path.sep));
      for(const n of nodes(entry)){
        assert(!['FunctionDeclaration','ArrowFunctionExpression','CallExpression','JSXElement'].includes(n.type),entry+' exports contract data/types only');
        if(n.type==='ImportDeclaration')assert.equal(n.importKind,'type',entry+' must not load another implementation');
      }
    }
  }
});

test('the host has no automation editor, transport or catalog lifecycle knowledge',()=>{
  for(const file of ['web/src/routes/settings/automations.tsx','web/src/components/settings/IntegrationAutomations.tsx','web/src/lib/queries/automations.ts']) assert(!existsSync(file),file);
  const violations=[];
  for(const file of files('web/src')) for(const node of nodes(file)) {
    if(node.type==='StringLiteral'&&/^\/automations(?:\/|$)/.test(node.value)) violations.push(file+': '+node.value);
    if(node.type==='ImportDeclaration'&&/automations\/ui\/src\/(?!types$)/.test(node.source.value)) violations.push(file+': '+node.source.value);
  }
  assert.deepEqual(violations,[]);
  for(const file of ['web/packages/plugin-sdk/src/commands.ts','web/packages/plugin-sdk/src/ConfirmDialog.tsx','web/packages/plugin-sdk/src/positioned-error.ts']) {
    assert(!nodes(file).some(node=>node.type==='StringLiteral'&&/automations|\/items|\/pages/.test(node.value)),file);
  }
});

test('the SLA report is the slas plugin\'s and the chart kit is reporting\'s (RADD-1386)',()=>{
  for(const file of ['web/src/components/reports/SlaCard.tsx','web/src/components/charts']) assert(!existsSync(file),file);
  const violations=[];
  for (const file of files('web/src')) for (const node of nodes(file)) {
    if (node.type==='StringLiteral' && /^\/(?:reports\/sla|sla-report)(?:\/|$)/.test(node.value)) violations.push(`${file}:${node.loc.start.line}: ${node.value}`);
  }
  assert.deepEqual(violations,[]);
});

test('the SLA feature is the slas plugin\'s: web/src names none of it (RADD-1394, RADD-1396)',()=>{
  for (const file of ['web/src/components/items/SlaChips.tsx','web/src/lib/queue.ts','web/src/routes/project-settings/sla.tsx',
    'web/src/components/settings/SlaPolicyForm.tsx','web/src/components/settings/SlaMetOnField.tsx']) assert(!existsSync(file),file);
  // SLA-named code: `Sla…`/`…Sla…`/`sla…` identifiers (components, hooks, types, queries, paths, atoms, entity tags)
  // and the timers' old helpers; the queue's host helpers are gone with it.
  const named=/(?:^|[a-z0-9_])Sla(?=[A-Z_0-9]|$)|(?:^|_)SLA(?=_|$)|^sla(?=[A-Z_0-9]|$)/;
  const helpers=/^(?:nearestToBreach|SAMPLE_SLA|QueueLinks|QueueLink|isQueue|urgencyKey|DEFAULT_QUEUE_[A-Z_]+|metRuleSummary|metRuleValid|parseClockMinutes)$/;
  // SLA wire vocabulary: every slas endpoint, the policy entity and its tag, the atoms, the settings segment, the
  // plugin's own ids (`slas.timer`, `slas.queue`) and the old builtin `queue` view type.
  const wire=/^(?:\/(?:sla-|items\/sla\b|reports\/sla\b)|sla(?:_policy|Policy|Policies)?$|sla\.|slas?(?:[._-]|$)|queue$)|\/sla(?:[/?]|$)/;
  // The one exception is NOTIFY's vocabulary, not this feature's: the core notify module owns the
  // `sla_breach`/`sla_due_soon` notification kinds (`notify.types.NotificationType`), and the inbox row mirrors them.
  const notify=new Set(['slaBreach','slaDueSoon','sla_breach','sla_due_soon']);
  for (const sample of ['SlaPolicy','slaPoliciesQuery','apiSlaPolicyPath','useSlaBatch','ProjectSlaSettings','SLA_POLICY']) assert(named.test(sample),sample);
  for (const sample of ['/sla-policies','/sla-queue-items','/items/sla/batch','sla_policy','slaPolicy','sla.update','sla','slas.queue','slas.timer','queue']) assert(wire.test(sample),sample);
  for (const sample of ['slack','SLACK_SPACER_CLASS','SlackSpacer','Island','translate','slash','queued','repliesLabel','settingsLabels']) assert(!named.test(sample)&&!wire.test(sample),sample);
  const violations=[];
  const scanned=files('web/src');
  assert(scanned.length>300,'the scan must reach the whole host');
  for (const file of scanned) for (const node of nodes(file)) {
    const line=`${file}:${node.loc?.start.line}`;
    if (node.type==='Identifier' && !notify.has(node.name) && (named.test(node.name) || helpers.test(node.name))) violations.push(`${line}: ${node.name}`);
    if (node.type==='StringLiteral' && !notify.has(node.value) && wire.test(node.value)) violations.push(`${line}: "${node.value}"`);
    if (node.type==='TemplateElement' && /\/sla(?:[/?-]|$)|\/sla-/.test(node.value.raw)) violations.push(`${line}: ${node.value.raw}`);
    if (node.type==='MemberExpression' && node.object?.name==='ViewType' && node.property?.name==='queue') violations.push(`${line}: ViewType.queue`);
  }
  assert.deepEqual(violations,[]);
  // …and the owner really does contribute every piece, so the absence above is not vacuous.
  const remote=readFileSync('server/src/radd/modules/slas/ui/src/index.tsx','utf8');
  assert.match(remote,/itemAttribute<[^>]*>\(\{\s*id: "slas\.timer"/);
  assert.match(remote,/slot: SlotId\.issuePanelSection/);
  assert.match(remote,/slot: SlotId\.projectSettingsPage,\s*match: SETTINGS_SEGMENT/);
  assert.match(remote,/const SETTINGS_SEGMENT = "sla";/);
  assert.match(readFileSync('server/src/radd/modules/slas/ui/src/timers.ts','utf8'),/key: "slas\.timers"/);
  assert(existsSync('server/src/radd/modules/slas/ui/src/settings/SlaSettingsPage.tsx'));
  const manifest=readFileSync('server/src/radd/modules/slas/__init__.py','utf8');
  assert.match(manifest,/section=NavSection\.PROJECT_SETTINGS/);
  assert.match(manifest,/ViewTypeSpec\([\s\S]*?key=SlaViewType\.QUEUE[\s\S]*?list_surface=ViewListSpec\([\s\S]*?rows_path=QUEUE_ROWS_PATH/);
  assert.match(manifest,/sidebar_section="Queues"/);
  // The host's side is generic: a project-settings page slot and a list surface read from the manifest.
  assert.match(readFileSync('web/src/routes/project-settings/layout.tsx','utf8'),/SlotId\.projectSettingsPage/);
  assert.match(readFileSync('web/src/routes/view.tsx','utf8'),/list_surface/);
});

test('Dashboards is its bundled package and "Awaiting my approval" is the approvals remote\'s (RADD-1393)',()=>{
  for(const file of ['web/src/components/dashboards','web/src/routes/dashboard.tsx','web/src/lib/types/dashboards.ts',
    'web/src/lib/types/approvals.ts','web/src/lib/queries/approvals.ts']) assert(!existsSync(file),file);
  // `/dashboards` alone is also the route prefix the shell's nav and pins know; the transport is not.
  const violations=[];
  for (const file of files('web/src')) for (const node of nodes(file)) {
    const text=node.type==='StringLiteral'?node.value:node.type==='TemplateElement'?node.value.raw:null;
    if (text!==null && /^\/(?:dashboards\/(?:my-work|summary)|approvals)(?:\/|$)/.test(text)) violations.push(`${file}:${node.loc.start.line}: ${text}`);
  }
  assert.deepEqual(violations,[]);
  const remote=nodes('server/src/radd/modules/approvals/ui/src/AwaitingApproval.tsx');
  assert(remote.some(n=>n.type==='StringLiteral'&&n.value==='/approvals/pending'),'the remote reads its own queue');
});

test('VCS settings and connector transport are owned by plugins',()=>{
  const violations=[];
  for (const file of files('web/src')) for (const node of nodes(file)) {
    if (node.type==='StringLiteral' && /^(?:\/(?:github|forgejo|gitlab)\/(?:connections|repos)|\/vcs\/(?:identities|[^/]+\/connections)|\/settings\/(?:vcs|github|forgejo|gitlab))/.test(node.value)) violations.push(`${file}:${node.loc.start.line}: ${node.value}`);
    if (node.type==='ImportDeclaration' && /(?:vcs-hosts|VcsHostSettings|VcsIdentityMap|settings\/vcs)/.test(node.source.value)) violations.push(file+': '+node.source.value);
  }
  assert.deepEqual(violations,[]);
  for(const file of ['web/src/routes/settings/vcs.tsx','web/src/components/settings/vcs-hosts.ts','web/src/components/settings/VcsHostSettings.tsx','web/src/components/settings/VcsIdentityMap.tsx'])assert(!existsSync(file),file);
  // RADD-1435: a connector's tab is its manifest's wording, served by vcs (`GET /vcs/connectors`); no connector ships a UI.
  for(const plugin of ['forgejo','github','gitlab'])assert(!existsSync(`server/src/radd/modules/${plugin}/ui`),`${plugin} ships no UI package`);
  const page=nodes('server/src/radd/modules/vcs/ui/src/queries.ts');
  assert(page.some(n=>n.type==='StringLiteral'&&n.value==='/vcs/connectors'),'the vcs page asks the server which connectors are loaded');
});

test('Directory settings and directory administration transport are owned by the ldap plugin (RADD-1381)',()=>{
  const violations=[];
  for (const file of files('web/src')) for (const node of nodes(file)) {
    if (node.type==='StringLiteral' && /^\/(?:ldap|settings\/directory)(?:\/|$)/.test(node.value)) violations.push(`${file}:${node.loc.start.line}: ${node.value}`);
  }
  assert.deepEqual(violations,[]);
  for(const file of ['web/src/routes/settings/directory.tsx','web/src/components/settings/DirectoryGroupsSection.tsx','web/src/components/settings/MirroredGroupsSection.tsx','web/src/components/settings/DirectoryImportDialogs.tsx','web/src/components/settings/DirectoryImportReview.tsx'])assert(!existsSync(file),file);
  const page=nodes('server/src/radd/modules/ldap/ui/src/index.tsx');
  assert(page.some(n=>n.type==='StringLiteral'&&n.value==='/settings/directory'),'the ldap remote contributes the page');
});

test('Settings → Email and mail configuration transport are owned by mailintake (RADD-1378)',()=>{
  const violations=[];
  for (const file of files('web/src')) for (const node of nodes(file)) {
    const text=node.type==='StringLiteral'?node.value:node.type==='TemplateElement'?node.value.raw:null;
    if (text!==null && /^(?:\/mail\/(?:sources|senders|rules|kinds)|\/settings\/email)(?:\/|$)/.test(text)) violations.push(`${file}:${node.loc.start.line}: ${text}`);
    if (node.type==='ImportDeclaration' && /(?:settings\/email|mail-admin)/.test(node.source.value)) violations.push(file+': '+node.source.value);
  }
  assert.deepEqual(violations,[]);
  for(const file of ['web/src/routes/settings/email.tsx','web/src/components/settings/email','web/src/lib/queries/mail-admin.ts'])assert(!existsSync(file),file);
});

test('the host never imports plugin source by relative path, only declared package exports (RADD-1373)',()=>{
  const root=new URL('../src',import.meta.url).pathname;
  const violations=[];
  for (const file of files(root)) for (const node of nodes(file)) {
    const source=(node.type==='ImportDeclaration'||node.type==='ExportNamedDeclaration'||node.type==='ExportAllDeclaration')?node.source?.value:
      node.type==='ImportExpression'||node.type==='CallExpression'&&node.callee?.type==='Import'?node.arguments?.[0]?.value??node.source?.value:undefined;
    if (typeof source==='string'&&source.includes('server/src/radd/modules')) violations.push(`${path.relative(root,file)} -> ${source}`);
  }
  assert.deepEqual(violations,[]);
});

test('the bundled core plugin list is generated from the packages that declare it (RADD-1373)',async()=>{
  const {discover,staticListSource,STATIC_LIST}=await import('./plugin-packages.mjs');
  const packages=discover();
  assert.equal(readFileSync(STATIC_LIST,'utf8'),staticListSource(packages),'run node web/scripts/prepare-federation.mjs');
  for (const pkg of packages.filter(p=>p.bundled)) assert(!pkg.remote,`${pkg.pkg.name} is bundled and builds a remote`);
  assert(packages.filter(p=>p.bundled).length>=15);
});

test('remotes see every SDK export: the shared shim is derived from the SDK source (RADD-1377)',async()=>{
  const {sdkShimSource,valueExports,SDK_SHIM}=await import('./sdk-exports.mjs');
  assert.equal(readFileSync(SDK_SHIM,'utf8'),sdkShimSource(),'run node web/scripts/gen-shared-shims.mjs');
  const names=valueExports();
  // The derivation must see through `export *` and skip type-only exports, or the check is vacuous.
  for (const name of ['definePlugin','formatDate','ScopedSettings','toast','useKeyedRows']) assert(names.includes(name),name);
  for (const name of ['HostComponents','ScopedSettingsProps','RoleGrantSubject']) assert(!names.includes(name),name);
});

test('the host never re-exports the SDK or a plugin package (RADD-1375)',()=>{
  // A forwarding address for something that moved is a compatibility shim; callers import the
  // owner directly. Barrels over the host's OWN modules (relative sources) are fine.
  const offenders=[];
  for (const file of files('web/src')) {
    const body=parse(readFileSync(file,'utf8'),{sourceType:'module',plugins:['typescript','jsx']}).program.body;
    if (body.some(n=>(n.type==='ExportNamedDeclaration'||n.type==='ExportAllDeclaration')&&/^@radd/.test(n.source?.value??''))) offenders.push(file);
  }
  assert.deepEqual(offenders,[]);
});

test('status colours use the status-* tokens that exist (RADD-1388)',()=>{
  // `text-danger-text` & co. read like tokens but index.css defines none of them, and Tailwind emits
  // nothing for an unknown colour — the error text simply came out uncoloured on three pages.
  const roots=['web/src','web/packages/plugin-sdk/src',...readdirSync('server/src/radd/modules').map(m=>`server/src/radd/modules/${m}/ui/src`).filter(existsSync)];
  const guessed=/(?<![\w-])(?:text|bg|border|ring|outline|fill|divide)-(?:danger|success|warning)\b/g;
  const found=roots.flatMap(files).flatMap(file=>[...readFileSync(file,'utf8').matchAll(guessed)].map(m=>`${file}: ${m[0]}`));
  assert.deepEqual(found,[]);
  assert.match('text-danger-text',new RegExp(guessed.source),'the pattern must catch the class it was written for');
});

test('plugin UIs ask the SDK whether the user is an instance admin, never `instance_role` (RADD-1422)',()=>{
  // `instance_role` is the account's column; `global_role` is what the server's bypass answers for
  // the credential, and it is what `useIsInstanceAdmin`/`usePermissions` read. Five pages compared
  // the account column, so an admin page could disagree with the API behind it.
  const reads=file=>nodes(file)
    .filter(n=>['MemberExpression','OptionalMemberExpression','ObjectProperty'].includes(n.type)&&(n.property??n.key)?.name==='instance_role')
    .map(n=>`${file}:${n.loc.start.line}`);
  assert(reads('web/packages/plugin-sdk/src/hooks.ts').length>0,'the scan must see the SDK\'s own read');
  const found=[...files('server/src/radd/modules'),...files('examples')].filter(f=>f.includes('/ui/src/')).flatMap(reads);
  assert.deepEqual(found,[]);
  // RADD-1464: the host's own pages are held to the same rule. Two files may name the column: the
  // type that declares it, and the Users page, which EDITS other accounts' ladder — reading a row's
  // `instance_role` there is the feature, not a permission check. Its gate on the caller is the hook.
  const hostAllowed=new Set(['web/src/lib/types/users.ts','web/src/routes/settings/users.tsx']);
  const hostFound=files('web/src').filter(f=>!hostAllowed.has(f)).flatMap(reads);
  assert.deepEqual(hostFound,[]);
  const users=nodes('web/src/routes/settings/users.tsx');
  assert(users.some(n=>n.type==='CallExpression'&&n.callee?.name==='useIsInstanceAdmin'),'the Users page gates on the hook');
  const callerReads=users.filter(n=>['MemberExpression','OptionalMemberExpression'].includes(n.type)&&n.property?.name==='instance_role'&&n.object?.name==='me');
  assert.deepEqual(callerReads.map(n=>n.loc.start.line),[],'the Users page never reads the caller\'s column');
  assert(reads('web/src/routes/settings/users.tsx').length>0,'the allowance is not stale: the ladder still reads rows');
});

test('every plugin nav icon is a name the one icon registry ships (RADD-1390)',()=>{
  // Manifests name icons; the host resolves them through lib/icons.ts. A second, PascalCase
  // whitelist in the settings nav needed a host edit per plugin, and Automations' "Zap" was never
  // added, so its entry showed the fallback glyph.
  const registry=readFileSync('web/src/lib/icons.ts','utf8');
  const map=registry.slice(registry.indexOf('const ICONS'),registry.indexOf('};',registry.indexOf('const ICONS')));
  const known=new Set([...map.matchAll(/^\s*(?:"([a-z0-9-]+)"|([a-z0-9]+)):/gm)].map(m=>m[1]??m[2]));
  const declared=readdirSync('server/src/radd/modules').flatMap(m=>{
    const file=`server/src/radd/modules/${m}/__init__.py`;
    if(!existsSync(file))return [];
    return [...readFileSync(file,'utf8').matchAll(/NavItemSpec\([^)]*?icon="([^"]+)"/gs)].map(x=>`${m}: ${x[1]}`);
  });
  assert(declared.length>=10,'the scan must find the manifests\' nav icons');
  assert.deepEqual(declared.filter(d=>!known.has(d.split(': ')[1])),[]);
});

test('co-editing is the collab plugin\'s: the host and the SDK name none of it (RADD-1397)',()=>{
  assert(!existsSync('web/src/components/editor/collab'),'the client moved into the collab remote');
  // Every way the host could know co-editing: its words, the CRDT and its transport, the room.
  // Comments count too: a comment explaining the room is the host knowing there is one.
  const vocabulary=/collab|\byjs\b|y-(?:websocket|protocols|prosemirror)|\bawareness\b|\bY\.Doc\b|editing ?now|live ?room|LiveSession|useLiveSession|elected saver/i;
  for (const sample of ['collab_session','/collab/pages','COLLAB_WS_PATH','yjs','y-websocket','EditingNow','useLiveSession','awareness']) assert(vocabulary.test(sample),sample);
  for (const sample of ['EditorBinding','bindableEditor','LiveDocument','BOUND_SERIALIZE_MS','collapse','Collapsible']) assert(!vocabulary.test(sample),sample);
  const scanned=[...files('web/src'),...files('web/packages/plugin-sdk/src')];
  assert(scanned.length>300,'the scan must reach the whole host');
  const violations=[];
  for (const file of scanned) for (const node of nodes(file)) {
    const text=node.type==='Identifier'||node.type==='JSXIdentifier'?node.name
      :node.type==='StringLiteral'?node.value:node.type==='TemplateElement'?node.value.raw
      :node.type==='CommentLine'||node.type==='CommentBlock'?node.value:null;
    if (text!==null && vocabulary.test(text)) violations.push(`${file}:${node.loc?.start.line}: ${text.trim().slice(0,80)}`);
  }
  assert.deepEqual([...new Set(violations)],[]);
  for (const text of [readFileSync('web/index.html','utf8'),readFileSync('web/package.json','utf8')]) assert(!/plugin-collab/.test(text));
  // …and it is not vacuous: the host offers the two generic points, the wiki asks, collab answers.
  const editor=readFileSync('web/src/components/editor/RichEditor.tsx','utf8');
  assert.match(editor,/binding\?: EditorBinding;/);
  assert.match(editor,/bindableEditor\(editor, contentRef\.current\)/);
  assert.match(readFileSync('server/src/radd/modules/pages/ui/src/view/usePageEditing.ts','utf8'),/useLiveDocument\(\{\s*entityType: "page"/);
  const remote=readFileSync('server/src/radd/modules/collab/ui/src/index.tsx','utf8');
  assert.match(remote,/entityType: "page", open: openPageSession/);
  assert.match(remote,/definePlugin\(\{ liveDocuments: \[pages\] \}\)/);
  const binder=nodes('server/src/radd/modules/collab/ui/src/bind-editor.ts').filter(n=>n.type==='ImportDeclaration').map(n=>n.source.value);
  for (const source of ['prosemirror-state','y-prosemirror','yjs']) assert(binder.includes(source),`the remote's binding imports ${source}`);
  assert.match(readFileSync('server/src/radd/modules/collab/__init__.py','utf8'),/remote="\/plugins\/collab\/remoteEntry\.js"/);
});

test('the shared singletons are one list the import map, the remote build and the host agree on (RADD-1397)',async()=>{
  const {EAGER_MODULES,LAZY_MODULES,SDK_MODULE,SHARED_SPECIFIERS,importMap}=await import('./shared-modules.mjs');
  const html=readFileSync('web/index.html','utf8');
  const map=JSON.parse(/<script type="importmap">([\s\S]*?)<\/script>/.exec(html)[1]).imports;
  assert.deepEqual(map,importMap());
  const vite=readFileSync('web/packages/plugin-sdk/vite.mjs','utf8');
  const external=[.../const SHARED = new Set\(\[([\s\S]*?)\]\)/.exec(vite)[1].matchAll(/"([^"]+)"/g)].map(m=>m[1]);
  assert.deepEqual(new Set(external),new Set(SHARED_SPECIFIERS));
  const runtime=readFileSync('web/src/shared-runtime.ts','utf8');
  for (const [id] of [...EAGER_MODULES,SDK_MODULE]) assert(runtime.includes(`\n  ${JSON.stringify(id)}:`)||runtime.includes(`\n  ${id}:`),`shared-runtime publishes ${id}`);
  for (const [id,slug,host] of LAZY_MODULES) {
    assert(runtime.includes(`${JSON.stringify(id)}: () => import(${JSON.stringify(host)})`),`shared-runtime loads ${id} through ${host}`);
    const shim=readFileSync(`web/public/shared/${slug}.js`,'utf8');
    assert.match(shim,/const M = await load\(\);/,`${slug} awaits the host's loader`);
  }
  assert(LAZY_MODULES.length>=3 && SHARED_SPECIFIERS.includes('prosemirror-state'),'the editor runtime is shared');
  // A shim for a module no longer on the list is dead weight nothing regenerates or removes.
  const slugs=[...EAGER_MODULES,SDK_MODULE,...LAZY_MODULES].map(([,slug])=>`${slug}.js`).sort();
  assert.deepEqual(readdirSync('web/public/shared').sort(),slugs);
});

test('editor, read-mode, issue and draft AI are the ai plugin\'s: the host and the SDK name none of it (RADD-1395)',()=>{
  for (const file of ['web/src/components/editor/ai.ts','web/src/components/editor/ai-run.ts','web/src/components/editor/ai-protect.ts',
    'web/src/components/editor/AiRunPanel.tsx','web/src/components/editor/AiSelectionToolbar.tsx','web/src/components/editor/AiActionPicker.tsx',
    'web/src/components/editor/AiReadMenu.tsx','web/src/components/items/AiResultsPanel.tsx','web/src/components/items/AiResultsPane.tsx',
    'web/src/components/items/AiSection.tsx','web/src/components/items/ai-results.ts','web/src/lib/sse.ts']) assert(!existsSync(file),file);
  // Since RADD-1400 the palette's Ask and the query bar's natural language are contributed modes too:
  // the host, the SDK and the bundled pages package name no AI at all — no identifier, no endpoint,
  // not even the semantic search and natural-language routes the ai remote asks.
  const vocabulary=/(?:^|[a-z])Ai(?:[A-Z]|$)|^ai[A-Z]|^data-ai-|^[Ss]emantic(?:[A-Z]|$)|^[Nn]l[A-Z]/;
  const endpoints=/\/ai(?:\/|$)|\/search\/semantic|\/slq\/nl/;
  const violations=[];
  for (const file of [...files('web/src'),...files('web/packages/plugin-sdk/src'),...files('server/src/radd/modules/pages/ui/src')]) {
    for (const node of nodes(file)) {
      const name=node.type==='Identifier'||node.type==='JSXIdentifier'?node.name:null;
      if (name!==null && vocabulary.test(name)) violations.push(`${file}:${node.loc.start.line}: ${name}`);
      const text=node.type==='StringLiteral'?node.value:node.type==='TemplateElement'?node.value.raw:null;
      if (text!==null && endpoints.test(text)) violations.push(`${file}:${node.loc.start.line}: ${text}`);
    }
  }
  assert.deepEqual(violations,[]);
  // …and it is not vacuous: the host places each extension point, and the ai remote fills them.
  const slotsOf=file=>new Set(nodes(file).filter(n=>n.type==='MemberExpression'&&n.object.name==='SlotId').map(n=>n.property.name));
  const anchors={'web/src/components/editor/RichEditor.tsx':['editorToolbarAction'],
    'web/src/components/editor/SelectionActions.tsx':['editorSelectionAction'],
    'web/src/routes/item-detail.tsx':['contentReadAction','issueRailTop'],
    'web/src/components/items/CommentsThread.tsx':['contentReadAction'],
    'web/src/components/forms/FormAssistPanel.tsx':['itemDraftAssist'],
    'server/src/radd/modules/pages/ui/src/view/PageReading.tsx':['contentReadAction']};
  for (const [file,ids] of Object.entries(anchors)) for (const id of ids) assert(slotsOf(file).has(id),`${file} places ${id}`);
  const contributed=new Set(nodes('server/src/radd/modules/ai/ui/src/index.tsx')
    .filter(n=>n.type==='ObjectProperty'&&n.key.name==='slot'&&n.value.type==='MemberExpression').map(n=>n.value.property.name));
  for (const id of ['editorToolbarAction','editorSelectionAction','contentReadAction','issueRailTop','itemDraftAssist','profileSection']) {
    assert(contributed.has(id),`the ai remote contributes ${id}`);
  }
  // RADD-1274's guarantee travels with the transform: the remote masks and restores protected blocks.
  const transform=readFileSync('server/src/radd/modules/ai/ui/src/editor/transform.ts','utf8');
  assert.match(transform,/maskProtected\(input\.document\)/);
  assert.match(transform,/restoreProtected\(text, kept\)/);
});

test('the palette and the query bar take contributed modes, and the ai remote contributes Ask to both (RADD-1400)',()=>{
  for (const file of ['web/src/lib/ai.ts','web/src/lib/types/ai.ts','web/src/lib/queries/ai-search.ts']) assert(!existsSync(file),file);
  const calls=file=>new Set(nodes(file).filter(n=>n.type==='CallExpression'&&n.callee.type==='Identifier').map(n=>n.callee.name));
  // The host asks for modes where it offers them, and draws them itself.
  assert(calls('web/src/components/CommandPalette.tsx').has('usePaletteModes'),'the palette asks for its modes');
  assert(calls('web/src/components/CommandPalette.tsx').has('usePaletteAnswer'),'the palette runs a mode\'s answer');
  assert(calls('web/src/components/views/QueryBar.tsx').has('useQueryInputModes'),'the query bar asks for its input modes');
  // With none contributed the bar is plain SLQ: the toggle is drawn only over available modes.
  assert.match(readFileSync('web/src/components/views/QueryBar.tsx','utf8'),/\{modes\.length > 0 && \(\s*<div\s+role="group"/);
  // The ai remote contributes both, built with the SDK's helpers, over the endpoints the host no longer names.
  const root='server/src/radd/modules/ai/ui/src';
  const listed=nodes(`${root}/index.tsx`).filter(n=>n.type==='ObjectProperty'&&n.key.name==='contributions')
    .flatMap(n=>n.value.elements??[]).filter(e=>e.type==='Identifier').map(e=>e.name);
  assert.deepEqual(listed.filter(name=>['askPaletteMode','naturalLanguageMode'].includes(name)).sort(),['askPaletteMode','naturalLanguageMode']);
  assert(calls(`${root}/palette/ask.ts`).has('paletteMode'),'Ask is a palette mode');
  assert(calls(`${root}/query-bar/natural-language.ts`).has('queryInputMode'),'natural language is a query-bar input mode');
  const strings=new Set(nodes(`${root}/transport.ts`).filter(n=>n.type==='StringLiteral').map(n=>n.value));
  for (const endpoint of ['/search/semantic','/slq/nl','/ai/status']) assert(strings.has(endpoint),`the ai remote owns ${endpoint}`);
  const members=file=>new Set(nodes(file).filter(n=>n.type==='MemberExpression'&&n.object.name==='AiEndpoint').map(n=>n.property.name));
  assert(members(`${root}/palette/ask.ts`).has('searchSemantic'));
  assert(members(`${root}/query-bar/natural-language.ts`).has('nlQuery'));
});

test('the survey page is csat\'s and a mailed body reads as mailintake draws it: the host names neither (RADD-1401)',async()=>{
  for (const file of ['web/src/routes/public-csat.tsx','web/src/components/editor/EmailBody.tsx','web/src/lib/types/csat.ts']) assert(!existsSync(file),file);
  // csat's words (the survey, its page, endpoint and types) and mail's (the signature annotation and
  // its restore route, contacts, the inbound origin, the channel's events, the plugin's own name) —
  // in code, copy AND comments: a comment naming the plugin is the host knowing it is there.
  const vocabulary=/csat|satisfaction|\bsurveys?\b|mailintake|email_?signature|EmailBody|MailContact|mail[-_]contacts?|inbound_mail|\/mail\/|^mail\.[a-z]|\bmail\.(?:received|sent|failed)\b|(?:show|not a) signature/i;
  for (const sample of ['PublicCsatPage','/public/csat/$token','satisfaction survey','email_signature','EmailBody','/mail/signatures/','mail.failed','"mail.sent"','Show signature','Not a signature','MailContact','mail-contacts','inbound_mail','mailintake provisions one']) assert(vocabulary.test(sample),sample);
  for (const sample of ['surveying the thread','signature: JSON.stringify(drafts)','a presigned link has a signature','mailto:','email','Mail','email_images_allowed','emailed']) assert(!vocabulary.test(sample),sample);
  // The one named exception, and why. The issue's History tab is a LEDGER: one switch renders every
  // plugin's events — approvals, participants, vcs, worklogs, csat.* and mail.* alike — and an event
  // outlives the plugin that emitted it, so a disabled plugin's past rows must still read as
  // sentences. Giving the ledger contributed event sentences is one mechanism for every plugin, not
  // a csat or mail move; until it exists, these rows stay the ledger's.
  const EXCEPTIONS={'web/src/components/items/HistoryTab.tsx':'the History ledger\'s event sentences'};
  const history=readFileSync('web/src/components/items/HistoryTab.tsx','utf8');
  for (const row of ['case "csat.responded"','case "mail.failed"']) assert(history.includes(row),`the exception is stale: HistoryTab no longer carries ${row}`);
  const {discover}=await import('./plugin-packages.mjs');
  const bundled=discover().filter(p=>p.bundled).map(p=>path.join(p.dir,'src'));
  assert(bundled.length>=15,'the scan reaches the core packages bundled into the host');
  const scanned=[...files('web/src'),...files('web/packages/plugin-sdk/src'),...bundled.flatMap(files)];
  assert(scanned.length>300,'the scan must reach the whole host');
  const violations=new Set();
  for (const file of scanned) {
    if (EXCEPTIONS[path.relative(process.cwd(),file)]) continue;
    for (const node of nodes(file)) {
      const text=node.type==='Identifier'||node.type==='JSXIdentifier'?node.name
        :node.type==='StringLiteral'||node.type==='JSXText'?node.value:node.type==='TemplateElement'?node.value.raw
        :node.type==='CommentLine'||node.type==='CommentBlock'?node.value:null;
      if (text!==null && vocabulary.test(text)) violations.add(`${file}:${node.loc?.start.line}: ${text.trim().slice(0,80)}`);
    }
  }
  assert.deepEqual([...violations],[]);
  // …and it is not vacuous: the host offers two generic points, and the two plugins fill them.
  const router=readFileSync('web/src/router.tsx','utf8');
  assert.match(router,/path: RoutePath\.publicPage,[\s\S]*?component: PublicPage,/,'a root-level route mounts the public frame');
  assert.match(readFileSync('web/src/lib/constants/routes.ts','utf8'),/publicPage: "\/public\/\$"/);
  const frame=readFileSync('web/src/components/shell/PublicPage.tsx','utf8');
  assert.match(frame,/<ContributedPage slot=\{SlotId\.publicPage\} \/>/);
  assert.match(frame,/<PluginRemotes \/>/,'the frame loads remotes itself: the shell that does is not mounted');
  assert.match(readFileSync('web/src/components/shell/ContributedPage.tsx','utf8'),/usePageMatch\(slot, key\)/,'contributed pages match by pattern');
  const body=readFileSync('web/src/components/editor/ContentBody.tsx','utf8');
  assert.match(body,/useContentBodyClaim\(record\)/);
  assert.match(body,/id=\{SlotId\.contentBody\}/);
  for (const file of ['web/src/components/items/CommentsThread.tsx','web/src/components/comments/CommentReplies.tsx','web/src/routes/item-detail.tsx','web/src/components/requests/RequestPanelBody.tsx']) {
    assert(nodes(file).some(n=>n.type==='JSXIdentifier'&&n.name==='ContentBody'),`${file} draws its bodies through ContentBody`);
  }
  const csat='server/src/radd/modules/csat';
  const survey=readFileSync(`${csat}/ui/src/index.tsx`,'utf8');
  assert.match(survey,/slot: SlotId\.publicPage,\s*match: SURVEY_PAGE,/,'csat contributes the survey page');
  const wire=readFileSync(`${csat}/ui/src/survey.ts`,'utf8');
  assert.match(wire,/SURVEY_PAGE = "\/public\/csat\/\$token"/);
  assert.match(wire,/`\/public\/csat\/\$\{encodeURIComponent\(token\)\}`/,'csat owns its public endpoint');
  const mail='server/src/radd/modules/mailintake';
  const signed=readFileSync(`${mail}/ui/src/SignedBody.tsx`,'utf8');
  assert.match(signed,/contentBody\(\{\s*id: "mailintake\.signature"/,'mailintake claims mailed bodies');
  assert.match(signed,/\/mail\/signatures\/\$\{context\.entityType\}\/\$\{context\.entityId\}\/restore/,'mailintake owns the restore route');
  assert(nodes(`${mail}/ui/src/index.tsx`).some(n=>n.type==='Identifier'&&n.name==='signedBody'),'the remote lists the claim');
  for (const manifest of [`${csat}/__init__.py`,`${mail}/__init__.py`]) assert.match(readFileSync(manifest,'utf8'),/ui_api_version="2\.0\.0"/,manifest);
});

test('raw palette utilities stay out of every UI tree: plugin UIs, the SDK and the example use the semantic tokens (RADD-1463)',()=>{
  // `text-amber-300` reads in dark and fails 4.5:1 in light: the remap under the semantic tokens
  // (web/src/index.css) is what makes a colour hold in both themes, and a raw palette class bypasses
  // it. Every plugin UI, the SDK and examples/ are held to the whole palette; the host keeps its
  // documented invariant (zero zinc/indigo). `text-black` on a fixed, un-themed fill is the exception.
  const prefixes='(?:bg|text|border|ring|from|to|via)';
  const palette=`\\b${prefixes}-(?:zinc|indigo|amber|red|emerald|green|blue|yellow|orange|sky|slate|gray|neutral|stone|rose|pink|purple|violet|fuchsia|cyan|teal|lime)-\\d{2,3}\\b`;
  const remap=`\\b${prefixes}-(?:zinc|indigo)-\\d{2,3}\\b`;
  for (const sample of ['bg-amber-500/15','text-red-400','hover:text-emerald-300','border-zinc-800']) assert.match(sample,new RegExp(palette),sample);
  for (const sample of ['text-black','text-status-danger-ink','bg-callout-warning-fill','border-subtle','--color-zinc-800','text-fg-muted']) assert.doesNotMatch(sample,new RegExp(palette),sample);
  const scan=(fileList,pattern)=>fileList.flatMap(file=>[...readFileSync(file,'utf8').matchAll(new RegExp(pattern,'g'))].map(m=>`${file}: ${m[0]}`));
  const pluginUis=[...readdirSync('server/src/radd/modules').map(m=>`server/src/radd/modules/${m}/ui/src`).filter(existsSync).flatMap(files),
    ...files('web/packages/plugin-sdk/src'),...files('examples').filter(f=>f.includes('/ui/src/'))];
  assert(pluginUis.length>200,'the scan reaches every plugin UI, the SDK and the example');
  assert.deepEqual(scan(pluginUis,palette),[]);
  const host=files('web/src');
  assert(host.length>300,'the scan reaches the whole host');
  assert.deepEqual(scan(host,remap),[]);
});
