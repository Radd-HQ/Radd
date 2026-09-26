/** Real graph algorithms: explicit shape inputs cannot leak across graph consumers. */
import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,readFileSync,writeFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
const dir=mkdtempSync(join(tmpdir(),'radd-graph-model-'));
writeFileSync(join(dir,'schedule.ts'),readFileSync('web/packages/plugin-sdk/src/schedule.ts','utf8'));
for(const file of ['types','shape-contract','automation-outputs','automation-layout']) {
 const source=readFileSync(`server/src/radd/modules/automations/ui/src/${file}.ts`,'utf8').replaceAll('from "@radd/plugin-sdk"','from "./schedule.ts"').replace(/from "\.\/([\w-]+)"/g,'from "./$1.ts"');
 writeFileSync(join(dir,file+'.ts'),source);
}
const {shapeKey}=await import(join(dir,'shape-contract.ts'));
const {outputsOfNode,upstreamProducers}=await import(join(dir,'automation-outputs.ts'));
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
process.on('exit',()=>rmSync(dir,{recursive:true,force:true}));
