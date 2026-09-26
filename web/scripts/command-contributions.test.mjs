import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {stripTypeScriptTypes} from 'node:module';
const source=readFileSync('web/packages/plugin-sdk/src/commands.ts','utf8')
 .replace(/import[^;]+from "react";/,'const useId=()=>"test",useMemo=fn=>fn(),useSyncExternalStore=(_subscribe,snapshot)=>snapshot();')
 .replace(/import[^;]+from "@tanstack\/react-query";/,'const useQueryClient=()=>({invalidateQueries:async()=>{}});const useQueries=({queries})=>queries.map(()=>({data:[{id:"command",label:"Example"}],isError:false}));');
const api=await import(`data:text/javascript;base64,${Buffer.from(stripTypeScriptTypes(source)).toString('base64')}`);
const context={entityType:'record',entityId:'saved'};
const provider=execute=>({id:'actions',entityType:'record',list:async()=>[],execute});
test('a retained command refuses execution after withdrawal and after replacement',async()=>{
 let calls=0;
 api.registerCommandSource('example',provider(async()=>{calls++;}));
 const [old]=api.useContributedCommands(context);await old.run();assert.equal(calls,1);
 api.unregisterCommandSources('example');await assert.rejects(old.run(),/no longer available/);assert.equal(calls,1);
 api.registerCommandSource('example',provider(async()=>{calls++;}));
 await assert.rejects(old.run(),/no longer available/);
 const [fresh]=api.useContributedCommands(context);await fresh.run();assert.equal(calls,2);
 api.unregisterCommandSources('example');
});
test('withdrawal aborts in-flight execution and late results cannot report success',async()=>{
 let finish,signal;
 api.registerCommandSource('example',provider((_id,_context,s)=>{signal=s;return new Promise(resolve=>{finish=resolve;});}));
 const [command]=api.useContributedCommands(context);const pending=command.run();
 api.unregisterCommandSources('example');assert(signal.aborted);finish();await assert.rejects(pending,{name:'AbortError'});
});
test('command providers remain isolated and repeated registration replaces only its own source',()=>{
 api.registerCommandSource('a',provider(async()=>{}));api.registerCommandSource('b',provider(async()=>{}));
 api.registerCommandSource('a',provider(async()=>{}));assert.equal(api.useContributedCommands(context).length,2);
 api.unregisterCommandSources('a');assert.equal(api.useContributedCommands(context).length,1);
 assert.equal(api.useContributedCommands(context,false).length,0);
 api.unregisterCommandSources('b');
});
