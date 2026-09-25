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
