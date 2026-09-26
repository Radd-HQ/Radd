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

test('Monitoring UI consumes contributions instead of importing AI or mail features',()=>{
  const violations=[];
  for (const file of files('server/src/radd/modules/monitoring/ui/src')) for(const node of nodes(file)) {
    if (node.type==='StringLiteral' && /^(?:\/(?:ai|mail)(?:\/|$)|(?:ai|mailintake)(?:\.|$))/.test(node.value)) violations.push(`${file}: ${node.value}`);
  }
  assert.deepEqual(violations,[]);
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

test('federation shim exports every runtime value in the public SDK',()=>{
  function exportsOf(file){
    const names=[];
    for(const node of nodes(file)){
      if(node.type==='ExportAllDeclaration'&&node.exportKind!=='type'){
        assert(node.source.value.startsWith('.'),'only local SDK star exports are supported');
        names.push(...exportsOf(path.resolve(path.dirname(file),node.source.value+'.ts')));
      }
      if(node.type!=='ExportNamedDeclaration'||node.exportKind==='type')continue;
      if(node.declaration?.type==='FunctionDeclaration')names.push(node.declaration.id.name);
      if(node.declaration?.type==='VariableDeclaration')for(const declaration of node.declaration.declarations){
        assert.equal(declaration.id.type,'Identifier');names.push(declaration.id.name);
      }
      for(const specifier of node.specifiers??[])if(specifier.exportKind!=='type')names.push(specifier.exported.name??specifier.exported.value);
    }
    return names;
  }
  assert.deepEqual(exportsOf('web/public/shared/radd-plugin-sdk.js').sort(),exportsOf('web/packages/plugin-sdk/src/index.ts').sort());
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

test('VCS settings and connector transport are owned by plugins',()=>{
  const violations=[];
  for (const file of files('web/src')) for (const node of nodes(file)) {
    if (node.type==='StringLiteral' && /^(?:\/(?:github|forgejo|gitlab)\/(?:connections|repos)|\/vcs\/(?:identities|[^/]+\/connections)|\/settings\/(?:vcs|github|forgejo|gitlab))/.test(node.value)) violations.push(`${file}:${node.loc.start.line}: ${node.value}`);
    if (node.type==='ImportDeclaration' && /(?:vcs-hosts|VcsHostSettings|VcsIdentityMap|settings\/vcs)/.test(node.source.value)) violations.push(file+': '+node.source.value);
  }
  assert.deepEqual(violations,[]);
  for(const file of ['web/src/routes/settings/vcs.tsx','web/src/components/settings/vcs-hosts.ts','web/src/components/settings/VcsHostSettings.tsx','web/src/components/settings/VcsIdentityMap.tsx'])assert(!existsSync(file),file);
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
