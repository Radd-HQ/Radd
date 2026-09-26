import test from 'node:test';
import assert from 'node:assert/strict';
import {importTs} from './lib/load-ts.mjs';
const router=import.meta.resolve('@tanstack/react-router');
const {auditEntityLink}=await importTs('server/src/radd/modules/audit/ui/src/audit.ts',source=>source.replace('from "@tanstack/react-router"',`from "${router}"`));
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
