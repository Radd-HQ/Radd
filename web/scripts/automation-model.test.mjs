/** Real graph algorithms: explicit shape inputs cannot leak across graph consumers. */
import test from 'node:test';
import assert from 'node:assert/strict';
import {importTs} from './lib/load-ts.mjs';
const ui='server/src/radd/modules/automations/ui/src';
const {shapeKey}=await importTs(`${ui}/shape-contract.ts`);
const {outputsOfNode,upstreamProducers}=await importTs(`${ui}/automation-outputs.ts`);
const catalog={nodes:[{key:'fixture.classify',kind:'gate',ports:[],outputs:[]}],node_arity:[]};
const node={id:'a',type:'fixture.classify',name:'classification',kind:'gate',params:{answers:['yes','no']}};
const downstream={id:'b',type:'action.update',kind:'action',params:{}};
const shapes={[shapeKey(node)]:{ports:['yes','no','unavailable'],outputs:[{name:'answer'}]}};
test('dynamic outputs require this graph’s exact current shape',()=>{
 assert.deepEqual(outputsOfNode(node,catalog,shapes),[{name:'answer'}]);
 assert.deepEqual(outputsOfNode(node,catalog),[]);
 assert.deepEqual(outputsOfNode({...node,params:{answers:['changed']}},catalog,shapes),[]);
 assert.deepEqual(outputsOfNode(node,catalog,{}),[]);
});
test('tokens respect resolved fallback ports and per-item publishing',()=>{
 const edge=port=>[{source:'a',port,target:'b'}];
 assert.equal(upstreamProducers('b',[node,downstream],edge('yes'),catalog,shapes).length,1);
 assert.equal(upstreamProducers('b',[node,downstream],edge('unavailable'),catalog,shapes).length,0);
 const perItem={...catalog,node_arity:[{type:node.type,default:'item',options:['item']}]};
 assert.equal(upstreamProducers('b',[node,downstream],edge('yes'),perItem,shapes).length,0);
});
