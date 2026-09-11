import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {stripTypeScriptTypes} from 'node:module';
import {QueryClient, QueryObserver, InfiniteQueryObserver} from '../node_modules/@tanstack/react-query/build/modern/index.js';

const source=path=>readFileSync(new URL('../src/lib/'+path,import.meta.url),'utf8');
function evaluate(code,imports,names){
  const js=stripTypeScriptTypes(code).replace(/^import[\s\S]*?from ["'][^"']+["'];\n/gm,'').replaceAll('export ','');
  return Function(...Object.keys(imports),js+';return {'+names.join(',')+'}')( ...Object.values(imports));
}
const {queryKeys}=evaluate(source('queries/shared.ts'),{},['queryKeys']);
const {Entity,entityMeta,projectEntityMeta}=evaluate(source('cache.ts'),{},['Entity','entityMeta','projectEntityMeta']);
globalThis.window={location:{origin:'http://test',pathname:'/projects'}};
const pending=[];
const oldFetch=globalThis.fetch;
globalThis.fetch=(url,options)=>new Promise((resolve,reject)=>{
  if(options.signal?.aborted){reject(options.signal.reason);return;}
  const row={url:String(url),...options,resolve};pending.push(row);
  options.signal?.addEventListener('abort',()=>reject(options.signal.reason),{once:true});
});
const {api}=evaluate(source('api.ts'),{
  API_BASE:'/api/v1',On401:{redirect:'redirect'},RoutePath:{login:'/login'},pushToast(){},FORBIDDEN_FALLBACK_MESSAGE:'Denied',
},['api']);
const imports={api,Entity,entityMeta,projectEntityMeta,queryKeys,queryOptions:x=>x,keepPreviousData:undefined,
 ApiPath:{search:'/search',aiSimilar:'/ai/similar',searchSemantic:'/search/semantic',searchDeflect:'/search/deflect',items:'/items'},
 DEFLECT_MIN_QUERY_CHARS:2,apiItemSimilarPath:id=>'/items/'+id+'/similar',
 apiItemLinkSearchPath:()=>'/items/link-search',apiItemHistoryPath:id=>'/items/'+id+'/history',
 apiItemVcsLinksPath:()=>'',apiItemWebLinksPath:()=>'',
 ITEMS_PAGE_LIMIT:200,ROADMAP_MEMBERS_LIMIT:200,ROADMAP_TRAY_PAGE_LIMIT:50,VIEW_COUNTS_MAX_VIEWS:50,VIEW_COUNTS_REFETCH_MS:60000,
};
const ai=evaluate(source('queries/ai-search.ts'),imports,['searchQuery','similarToTextQuery','semanticSearchQuery','deflectQuery']);
const provisioning=evaluate(source('queries/provisioning.ts'),imports,['provisioningReferencesQuery']);
const fieldSettings=evaluate(source('queries/field-settings.ts'),imports,['fieldDirectoryQuery','managedFieldQuery','fieldProjectChoicesQuery','fieldProjectReferencesQuery','fieldOptionsQuery']);
const formSharing=evaluate(source('queries/forms.ts'),{...imports,apiFormPath:id=>'/forms/'+id},['formSharingQuery','formShareCandidatesQuery']);
const teams=evaluate(source('queries/users.ts'),{...imports,ApiPath:{teams:'/teams'}},['teamReferencesQuery']);
const serviceAccounts=evaluate(source('queries/integrations.ts'),{...imports,apiServiceAccountKeysPath:id=>'/service-accounts/'+id+'/keys'},['serviceAccountDirectoryQuery','serviceAccountQuery','serviceKeyDirectoryQuery']);
const resourceGrants=evaluate(source('queries/fields.ts'),imports,['resourceGrantsPageQuery']);
const activity=evaluate(source('queries/activity.ts'),imports,['linkSearchQuery']);
const views=evaluate(source('queries/views.ts'),imports,['infiniteViewItemsQuery']);
const client=new QueryClient({defaultOptions:{queries:{retry:false}}});
const tick=()=>new Promise(resolve=>setTimeout(resolve,0));
try {
  for(const [name,factory,paged=false] of [
    ['form share search',q=>formSharing.formSharingQuery('form',q,0),true],
    ['form share recipient search',q=>formSharing.formShareCandidatesQuery('form','user',q,0),true],
    ['form share recipient form',q=>formSharing.formShareCandidatesQuery(q,'team','',0),true],
    ['team references',q=>teams.teamReferencesQuery([q])],
    ['team counts',q=>teams.teamReferencesQuery([q],true)],
    ['text search',q=>ai.searchQuery(q,20)],
    ['semantic search',q=>ai.semanticSearchQuery(q)],
    ['similarity POST',q=>ai.similarToTextQuery('comment',q,'issue')],
    ['deflection',q=>ai.deflectQuery(q,'project')],
    ['link picker',q=>activity.linkSearchQuery('project',q)],
    ['provisioning references',q=>provisioning.provisioningReferencesQuery([q],[],[])],
    ['service account directory',q=>serviceAccounts.serviceAccountDirectoryQuery(q,0),true],
    ['service account detail',q=>serviceAccounts.serviceAccountQuery(q)],
    ['service key search',q=>serviceAccounts.serviceKeyDirectoryQuery('id',q,0),true],
    ['service key account',q=>serviceAccounts.serviceKeyDirectoryQuery(q,'',0),true],
    ['field directory',q=>fieldSettings.fieldDirectoryQuery(q,0),true],
    ['field definition',q=>fieldSettings.managedFieldQuery(q)],
    ['field option search',q=>fieldSettings.fieldOptionsQuery('id',q,0),true],
    ['field option exclusion',q=>fieldSettings.fieldOptionsQuery('id','',0,q),true],
    ['field project choices',q=>fieldSettings.fieldProjectChoicesQuery('field.update',q,0),true],
    ['field project references',q=>fieldSettings.fieldProjectReferencesQuery([q])],
    ['resource grant scope',q=>resourceGrants.resourceGrantsPageQuery('builtin_field','assignee','',0,q),true],
    ['resource grant search',q=>resourceGrants.resourceGrantsPageQuery('field','id',q,0),true],
  ]){
    const observer=new QueryObserver(client,factory('before'));
    const stop=observer.subscribe(()=>{});
    await tick();const old=pending.at(-1);
    assert(old.signal instanceof AbortSignal,name+' must reach fetch with a signal');
    observer.setOptions(factory('after'));
    await tick();const latest=pending.at(-1);
    assert(old.signal.aborted,name+' must abort superseded requests');
    assert.notEqual(old,latest);
    latest.resolve(new Response(JSON.stringify(paged ? ['current'] : {results:['current']}),{headers:{'Content-Type':'application/json','X-Total-Count':'1'}}));
    await tick();await tick();
    assert.deepEqual(observer.getCurrentResult().data,paged ? {rows:['current'],total:1} : {results:['current']});
    observer.setOptions(factory('closing'));
    await tick();const closing=pending.at(-1);
    stop();
    assert(closing.signal.aborted,name+' must abort on last reader removal');
  }
  const grantObserver=new QueryObserver(client,resourceGrants.resourceGrantsPageQuery('field','first','',0));
  const stopGrant=grantObserver.subscribe(()=>{});await tick();
  pending.at(-1).resolve(new Response(JSON.stringify([{id:'first-grant'}]),{headers:{'X-Total-Count':'126'}}));
  await tick();await tick();
  grantObserver.setOptions(resourceGrants.resourceGrantsPageQuery('field','first','',1));await tick();
  assert.deepEqual(grantObserver.getCurrentResult().data.rows,[{id:'first-grant'}],'paging retains the current window while loading');
  const pageRequest=pending.at(-1);
  grantObserver.setOptions(resourceGrants.resourceGrantsPageQuery('page','second','',0));await tick();
  assert(pageRequest.signal.aborted);
  assert.equal(grantObserver.getCurrentResult().data,undefined,'a different resource never receives the previous resource grant rows');
  stopGrant();
  const sharedA=new QueryObserver(client,ai.searchQuery('shared',20));
  const sharedB=new QueryObserver(client,ai.searchQuery('shared',20));
  const stopA=sharedA.subscribe(()=>{});const stopB=sharedB.subscribe(()=>{});await tick();
  const shared=pending.at(-1);stopA();
  assert(!shared.signal.aborted,'one departing reader must not cancel another active reader');
  stopB();assert(shared.signal.aborted,'the last reader cancels shared work');
  const observer=new InfiniteQueryObserver(client,views.infiniteViewItemsQuery({id:'view',query_string:'project_id=p'}));
  const stop=observer.subscribe(()=>{});await tick();
  pending.at(-1).resolve(new Response(JSON.stringify(Array.from({length:200},(_,id)=>({id})))));
  await tick();await tick();
  const next=observer.fetchNextPage();await tick();const loading=pending.at(-1);
  assert(loading.url.includes('offset=200'));
  stop();await next;
  assert(loading.signal.aborted,'next-page request must abort when its screen closes');
  // Plugin remotes have their own SDK API implementation; verify that boundary too.
  const sdkSource=readFileSync(new URL('../packages/plugin-sdk/src/api.ts',import.meta.url),'utf8').replace('export { API_BASE };','');
  const sdk=evaluate(sdkSource,{},['api']);
  const controller=new AbortController();
  const request=sdk.api.get('/remote',{signal:controller.signal});
  const rejection=assert.rejects(request);controller.abort();await rejection;
  assert(pending.at(-1).signal.aborted,'plugin SDK must forward cancellation');
  console.log('Query observers cancel superseded GET/POST search, closed pages and plugin requests.');
} finally {client.clear();globalThis.fetch=oldFetch;delete globalThis.window;}
