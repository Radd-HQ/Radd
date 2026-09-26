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
  for(const owner of ['automations','backup']){
    const ast=owner === "automations" ? [] : nodes(`web/src/components/${owner}/ScheduleEditor.tsx`);
    assert(ast.filter(n=>n.type==='ImportDeclaration').every(n=>n.source.value==='@radd/plugin-sdk'||n.source.value.endsWith('/schedule-contract')));
    assert(!ast.some(n=>n.type==='CallExpression'&&['useState','useEffect','useQuery'].includes(n.callee?.name)));
    const implementation=nodes(`server/src/radd/modules/${owner}/ui/src/ScheduleEditor.tsx`);
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

test('editor, read-mode, issue and draft AI are the ai plugin\'s: the host and the SDK name none of it (RADD-1395)',()=>{
  for (const file of ['web/src/components/editor/ai.ts','web/src/components/editor/ai-run.ts','web/src/components/editor/ai-protect.ts',
    'web/src/components/editor/AiRunPanel.tsx','web/src/components/editor/AiSelectionToolbar.tsx','web/src/components/editor/AiActionPicker.tsx',
    'web/src/components/editor/AiReadMenu.tsx','web/src/components/items/AiResultsPanel.tsx','web/src/components/items/AiResultsPane.tsx',
    'web/src/components/items/AiSection.tsx','web/src/components/items/ai-results.ts','web/src/lib/sse.ts']) assert(!existsSync(file),file);
  // The palette's Ask mode and the query bar's natural-language ask are the host's last AI surfaces:
  // each needs a contribution point of its own. What they read is listed here and may not grow.
  const residue=new Set(['web/src/components/CommandPalette.tsx','web/src/components/views/QueryBar.tsx','web/src/lib/ai.ts',
    'web/src/lib/queries/ai-search.ts','web/src/lib/types/ai.ts','web/src/lib/types/index.ts','web/src/lib/cache.ts',
    'web/src/lib/queries/shared.ts','web/src/lib/constants/api.ts']);
  const residueNames=new Set(['aiStatusQuery','aiStatus','AiStatus','AiFeature','AiFeatureValue','aiProvider','aiRole','isAiGone','aiErrorText']);
  const residueStrings=new Set(['/ai/status','../../lib/ai','./ai']);
  const vocabulary=/(?:^|[a-z])Ai(?:[A-Z]|$)|^ai[A-Z]|^data-ai-/;
  const violations=[];
  for (const file of [...files('web/src'),...files('web/packages/plugin-sdk/src'),...files('server/src/radd/modules/pages/ui/src')]) {
    const allowed=residue.has(file);
    for (const node of nodes(file)) {
      const name=node.type==='Identifier'||node.type==='JSXIdentifier'?node.name:null;
      if (name!==null && vocabulary.test(name) && !(allowed && residueNames.has(name))) violations.push(`${file}:${node.loc.start.line}: ${name}`);
      const text=node.type==='StringLiteral'?node.value:node.type==='TemplateElement'?node.value.raw:null;
      if (text!==null && /\/ai(?:\/|$)/.test(text) && !(allowed && residueStrings.has(text))) violations.push(`${file}:${node.loc.start.line}: ${text}`);
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
