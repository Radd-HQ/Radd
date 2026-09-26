import test from 'node:test';
import assert from 'node:assert/strict';
import {importTs} from './lib/load-ts.mjs';
const {defaultsFromSchema}=await importTs('web/packages/plugin-sdk/src/schema-defaults.ts');
test('schema starting values retain enum types and nested defaults',()=>{
 const schema={required:['mode','flag'],properties:{mode:{type:'integer',enum:[2,4]},flag:{type:'boolean',enum:[false,true]},options:{type:'object',properties:{summary:{type:'boolean',default:true},comments:{type:'boolean'}}}}};
 assert.deepEqual(defaultsFromSchema(schema),{mode:2,flag:false,options:{summary:true,comments:false}});
});
test('two forms never share mutable schema defaults or required enum objects',()=>{
 const schema={required:['choice'],properties:{object:{type:'object',default:{list:['saved']}},choice:{enum:[{nested:['value']}]}}};
 const first=defaultsFromSchema(schema),second=defaultsFromSchema(schema);
 first.object.list.push('edited');first.choice.nested.length=0;
 assert.deepEqual(second,{object:{list:['saved']},choice:{nested:['value']}});
 assert.deepEqual(schema.properties.object.default,{list:['saved']});
});
test('object-level defaults override inferred values without losing unnamed fields',()=>{
 const schema={type:'object',default:{known:true,extra:'kept'},properties:{known:{type:'boolean'},other:{type:'boolean'}}};
 assert.deepEqual(defaultsFromSchema(schema),{known:true,other:false,extra:'kept'});
});
