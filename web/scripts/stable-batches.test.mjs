import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { stripTypeScriptTypes } from 'node:module';
import { QueryClient, QueryObserver } from '../node_modules/@tanstack/react-query/build/modern/index.js';
const code = stripTypeScriptTypes(readFileSync(new URL('../src/lib/useStableItemBatches.ts', import.meta.url), 'utf8')).replace(/^import.*;$/m,'').replace('export ', '');
const ref = {current:[]};
const batches = Function('useRef', code+';return useStableItemBatches;')(()=>ref);
const first = batches(['c','b','a'],2);
assert.deepEqual(first,[['a','b'],['c']]);
const next = batches(['a','b','c','e','d'],2);
assert.deepEqual(next,[...first,['d','e']]);
assert.deepEqual(batches(['e','a','c','a'],2),[['a'],['c'],['e']]);
assert.deepEqual(batches([],2),[]);
assert.deepEqual(batches(['other-account'],2),[['other-account']]);
const client = new QueryClient({defaultOptions:{queries:{staleTime:60000,retry:false}}});
const calls=[];const stops=[];
const attach=ids=>{const observer=new QueryObserver(client,{queryKey:['batches',ids],meta:{entities:['item']},queryFn:async()=>{calls.push(ids);return ids;}});stops.push(observer.subscribe(()=>{}));return observer;};
const tick=()=>new Promise(r=>setTimeout(r,5));
try {
 first.forEach(attach); await tick();
 next.forEach(attach); await tick();
 assert.equal(calls.length,3,'Append requests only the new chunk');
 await client.invalidateQueries({predicate:q=>q.meta?.entities?.includes('item')});
 assert.equal(calls.length,6,'Mutation invalidation refreshes every active chunk');
} finally {stops.forEach(stop=>stop());client.clear();}
console.log('PASS stable append/prune/account replacement and active chunk invalidation');
