import test from 'node:test';
import assert from 'node:assert/strict';
import {importTs} from './lib/load-ts.mjs';
const {itemChange}=await importTs('server/src/radd/modules/items/ui/src/change-format.ts');
test('Items change presentation preserves absent keys, collection members and saved unknown values',()=>{
 assert.deepEqual(itemChange({field:'links'}),{field:'links',name:'Dependencies'});
 assert.deepEqual(itemChange({field:'description'}),{field:'description',name:'Description'});
 assert.deepEqual(itemChange({field:'priority',from:'low',to:'custom-priority'}),{field:'priority',name:'Priority',from:'Low',to:'custom-priority'});
 assert.deepEqual(itemChange({field:'links',added:[{key:'TEST-1',link_type:'blocks'},'unresolved',null]}).added,['TEST-1 (blocks)','unresolved',null]);
 assert.deepEqual(itemChange({field:'count',from:0,to:false}),{field:'count',name:undefined,from:0,to:false});
});
test('Items never formats withheld payloads and does not mutate the original change',()=>{
 const change={field:'priority',from:'sensitive-old',to:'sensitive-new',redacted:true};const before=structuredClone(change);
 assert.deepEqual(itemChange(change),{field:'priority',name:'Priority',redacted:true});assert.deepEqual(change,before);
});

const {roleChange}=await importTs('server/src/radd/modules/auth/ui/src/change-format.ts');
test('Auth owns role grant presentation and preserves unknown grant records',()=>{
 const grant={subject:'Alice',role:'manager',scope:'project TEST'};
 assert.deepEqual(roleChange({field:'grants',added:[grant,{future:true}]}),{field:'grants',added:['Alice as manager (project TEST)',{future:true}]});
 assert.deepEqual(roleChange({field:'grants'}),{field:'grants'});
 assert.deepEqual(roleChange({field:'grants',added:[grant],redacted:true}),{field:'grants',name:undefined,redacted:true});
});
