import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,readFileSync,writeFileSync,rmSync,symlinkSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
const dir=mkdtempSync(join(tmpdir(),'radd-audit-links-'));
symlinkSync(resolve('web/node_modules'),join(dir,'node_modules'),'dir');
writeFileSync(join(dir,'audit.ts'),readFileSync('web/src/lib/audit.ts','utf8'));
const {auditEntityLink}=await import(join(dir,'audit.ts'));
const entry={entity_owner:'fixture',entity_url:'/things?number=123&id=abc#selected'};
test('audit links use owner destinations and preserve router query types and fragments',()=>{
 const link=auditEntityLink(entry,new Set(['fixture']));assert.equal(link.to,'/things#selected');assert.deepEqual({...link.search},{number:123,id:'abc'});
});
test('cached destinations withdraw while rows and labels remain intact',()=>{
 const before=structuredClone(entry);
 assert.equal(auditEntityLink(entry,new Set()),null);
 assert.deepEqual(entry,before);
 assert(auditEntityLink(entry,new Set(['fixture'])));
 assert.equal(auditEntityLink({...entry,entity_owner:undefined},new Set(['fixture'])),null);
});
test('untrusted URL schemes and browser authority escapes are not links',()=>{
 for(const entity_url of ['//outside.test','https://outside.test','javascript:alert(1)','/\\outside.test','/\n/outside.test'])assert.equal(auditEntityLink({...entry,entity_url},new Set(['fixture'])),null);
});
process.on('exit',()=>rmSync(dir,{recursive:true,force:true}));
