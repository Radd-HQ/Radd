/** AST boundary checks. Ownership coverage remains in the complete audit ledger. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
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
  const file='web/src/components/PeopleDirectorySelect.tsx';
  const imports=nodes(file).filter(n=>n.type==='ImportDeclaration').map(n=>n.source.value);
  assert.deepEqual(imports,['@radd/plugin-sdk']);
  assert(!readFileSync('web/src/lib/queries/users.ts','utf8').includes('peopleChoicesQuery'));
});

test('directory query providers belong to Auth or Teams, not the SDK control',()=>{
  const sdk=readFileSync('web/packages/plugin-sdk/src/directory.tsx','utf8');
  assert(!/\/(?:users|teams)|auth\.people|teams\.candidates/.test(sdk));
});

test('automation canvas is contributed; graph queries and algorithms belong to Automations',()=>{
  const adapter=nodes('web/src/components/automations/LazyGraphCanvas.tsx');
  const imports=adapter.filter(n=>n.type==='ImportDeclaration').map(n=>n.source.value);
  assert.deepEqual(imports,['@radd/plugin-sdk','../../../../server/src/radd/modules/automations/ui/src/canvas-contract']);
  for(const file of ['web/src/lib/node-shapes.ts','web/src/lib/automation-layout.ts','web/src/lib/automation-nodes.ts','web/src/lib/automation-outputs.ts','web/src/lib/types/automations.ts','web/src/components/automations/node-visuals.ts']){
    assert(nodes(file).every(n=>n.type!=='ImportDeclaration'&&n.type!=='FunctionDeclaration'&&n.type!=='VariableDeclaration'),file+' must remain a transitional barrel only');
  }
  assert(!files('web/src').some(f=>f.endsWith('/GraphCanvas.tsx')));
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
  const adapter=nodes('web/src/components/DirectoryChoices.tsx');
  assert(adapter.filter(n=>n.type==='ExportNamedDeclaration').every(n=>n.source?.value==='@radd/plugin-sdk'));
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
  for(const file of ['web/src/components/TokenMultiSelect.tsx','web/src/components/ErrorText.tsx']){
    assert(nodes(file).filter(n=>n.type==='ExportNamedDeclaration').every(n=>n.source?.value==='@radd/plugin-sdk'));
    assert(!nodes(file).some(n=>n.type==='FunctionDeclaration'));
  }
  for(const file of ['web/packages/plugin-sdk/src/token-multi-select.tsx','web/packages/plugin-sdk/src/error-text.tsx']){
    assert(!nodes(file).some(n=>n.type==='ImportDeclaration'&&/modules|web\/src|components\//.test(n.source.value)));
  }
});
