/** Render real comment components with an unknown import author. No live writes. */
import assert from 'node:assert/strict';
import { writeFile, rm, mkdtemp } from 'node:fs/promises';
import { createServer } from 'vite';
import { openBrowser } from './lib/cdp.mjs';
const root = new URL('../', import.meta.url).pathname;
const entry = root + '__import-author-proof.tsx';
let server, browser;
try {
  await writeFile(entry, `import React, {useRef} from 'react';
import {createRoot} from 'react-dom/client';
import {createRouter,createRootRoute,createRoute,RouterProvider} from '@tanstack/react-router';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {StorageChoiceProvider} from './src/components/attachments/StorageChoiceProvider';
import {PageComments} from './src/components/pages/PageComments';
import {PageInlineComments} from './src/components/pages/PageInlineComments';
import {CommentsThread} from './src/components/items/CommentsThread';
import {authStateQuery,pageCommentFeedQuery,itemCommentFeedQuery} from './src/lib/queries';
import './src/index.css';
const client=new QueryClient({defaultOptions:{queries:{retry:false,staleTime:Infinity}}});
client.setQueryData(authStateQuery.queryKey,{status:'anonymous'});
const row={id:'unknown',entity_id:'fixture',entity_type:'page',author:null,body:'Historical comment with no author',visibility:'public',visible_to_teams:[],created_at:'2018-04-25T05:46:56Z',updated_at:'2018-04-25T05:46:56Z',anchor:null,resolved_at:null,resolved_by:null};
const data=(r)=>({pages:[{comments:[r],older_cursor:null}],pageParams:[null]});
client.setQueryData(pageCommentFeedQuery('fixture').queryKey,data(row));
client.setQueryData(pageCommentFeedQuery('fixture','inline').queryKey,data({...row,id:'inline',anchor:{quote:'Quoted text',prefix:'',suffix:''}}));
client.setQueryData(itemCommentFeedQuery('fixture').queryKey,data({...row,entity_type:'item'}));
function Proof(){const ref=useRef(null);return <QueryClientProvider client={client}><StorageChoiceProvider><main style={{padding:32}}><h1>Imported comments</h1><div id="issue"><CommentsThread item={{id:'fixture',key:'TEST-1',labels:[],assignee:null}} project={{id:'p',permissions:[]}} /></div><PageComments pageId="fixture" canComment={false}/><div ref={ref}>Quoted text</div><PageInlineComments pageId="fixture" bodyRef={ref} bodyVersion={1} canComment={false}/></main></StorageChoiceProvider></QueryClientProvider>}
const rootRoute=createRootRoute({component:Proof});
const route=createRoute({getParentRoute:()=>rootRoute,path:'/__proof'});
const router=createRouter({routeTree:rootRoute.addChildren([route])});
createRoot(document.getElementById('root')).render(<RouterProvider router={router}/>);`);
  server = await createServer({root, server:{port:19431,host:'127.0.0.1'}, plugins:[{name:'proof-fixtures',configureServer(s){s.middlewares.use(async (req,res,next)=>{
    if(req.url==='/__proof'){res.setHeader('Content-Type','text/html');res.end(await s.transformIndexHtml('/__proof','<div id="root"></div><script type="module" src="/__import-author-proof.tsx"></script>'));return;}
    if(req.url.startsWith('/api/')){res.setHeader('Content-Type','application/json');res.end(JSON.stringify(req.url.includes('summary')?{total:0,permissions:[]}:[]));return;} next();
  });}}]});
  await server.listen();
  browser=await openBrowser({port:19432,profile:await mkdtemp('/tmp/radd-import-author-')});
  await browser.session.navigate('http://127.0.0.1:19431/__proof',4000);
  const text=await browser.session.eval('document.body.innerText');
  assert.ok((text.match(/Unknown author/g)||[]).length>=3,text);
  assert.equal(await browser.session.eval(`document.querySelectorAll('button[title="Delete comment"],button[title="Resolve"]').length`),0);
  assert.deepEqual(browser.session.consoleErrors,[]);
  await browser.session.screenshot('/tmp/radd-import-author-proof.png');
  console.log('PASS: issue, page and inline comments render Unknown author; anonymous visitor gains no author actions.');
}finally{browser?.close();await server?.close();await rm(entry,{force:true});}
