/** RADD-1198: actual mapping controls, representative large catalog, saved wire values. */
import assert from 'node:assert/strict';
import {writeFile,rm,mkdtemp} from 'node:fs/promises';
import {createServer} from 'vite';
import {openBrowser} from './lib/cdp.mjs';
const root=new URL('../',import.meta.url).pathname,entry=root+'__mapping-proof.tsx';
const field=(id,name,extra={})=>({jira_id:id,jira_name:name,action:'ignore',target_key:'',create_name:'',create_type:null,create_options:null,create_scope:'global',value_map:{},observed_values:[],samples:[],band:'unused',band_reason:'',extend_options:false,...extra});
let saved;
const confluenceWrites=[];
const confluencePlan={id:'fixture',mappings:{spaces:[{key:'DOC',name:'Docs',count:2,action:'create'},{key:'UNUSED',name:'Unused docs',count:0,action:'ignore'}],macros:[{name:'custom',count:1,action:'extension',extension:'toc'}],users:[{username:'old',count:1,action:'map',user_id:null}],groups:[{name:'group:old',count:1,action:'identity',group_id:null,team_id:null}],labels:[],jira_links:[]},options:{quiet:true,import_attachments:false,import_comments:false,unresolved_principal:'fail'}};
const plan={id:'fixture',name:'Mapping proof',radd_project_id:'project',radd_project_key:'DEV',radd_project_name:'Development',provisioned_at:null,options:{quiet:true},mappings:{fields:[field('severity','Severity',{band:'in_use',action:'map',target_key:'severity',observed_values:['P1','P2']}),field('domain','Domain',{band:'in_use',action:'native',builtin_target:'team',observed_values:['Pipeline','Support']}),...Array.from({length:335},(_,i)=>field(`f${i}`,`Unused ${i}`))],statuses:[{jira:'In Review',count:200,action:'map',state_name:'Old missing state',category:'todo'}],issue_types:[],priorities:[],users:[],sprints:[],versions:[],components:[],link_types:[]}};
let server,browser;
try{
 await writeFile(entry,`import React from 'react';import{createRoot}from'react-dom/client';import{QueryClient,QueryClientProvider}from'@tanstack/react-query';import{PlanEditor}from'./src/components/settings/jira/PlanEditor';import{PlanEditor as ConfluenceEditor}from'./src/components/settings/confluence/PlanEditor';import './src/index.css';const client=new QueryClient({defaultOptions:{queries:{retry:false}}});createRoot(document.getElementById('root')).render(<QueryClientProvider client={client}><main style={{padding:32}}>{location.search ? <ConfluenceEditor planId="fixture" focus={null} onRan={()=>{}}/> : <PlanEditor planId="fixture" onRunStarted={()=>{}}/>}</main></QueryClientProvider>);`);
 server=await createServer({root,server:{host:'127.0.0.1',port:19451},plugins:[{name:'fixtures',configureServer(s){s.middlewares.use(async(req,res,next)=>{
  if(req.url.startsWith('/__proof')){res.setHeader('content-type','text/html');res.end(await s.transformIndexHtml('/__proof','<div id="root"></div><script type="module" src="/__mapping-proof.tsx"></script>'));return;}
  if(req.url.startsWith('/api/')){let data=[];
   if(req.url.includes('/confluence/')){if(req.method==='PATCH'){let body='';for await(const chunk of req)body+=chunk;const draft=JSON.parse(body);confluencePlan.mappings=draft.mappings;confluencePlan.options=draft.options;confluenceWrites.push('save:'+draft.mappings.spaces[0].action);}else if(req.method==='POST')confluenceWrites.push(req.url.includes('/validate')?'validate':'run');data=req.url.includes('/validate')?[]:confluencePlan;}
   else if(req.url.includes('/plans/fixture')){if(req.method==='PATCH'){let body='';for await(const chunk of req)body+=chunk;saved=JSON.parse(body);plan.mappings=saved.mappings;}data=plan;}
   else if(req.url.includes('/page-spaces'))data=[{id:'space-target',name:'Company docs'}];
   else if(req.url.includes('/pages/extensions'))data=[{name:'toc',label:'Contents'},{name:'callout',label:'Callout'}];
   else if(req.url.includes('/users/directory')){data=[{id:'target-user',name:'Merged account'}];res.setHeader('X-Total-Count','1');}
   else if(req.url.includes('/fields'))data=[{key:'severity',name:'Severity',type:'select',options:['Critical','Normal'],project_ids:[]}];
   else if(req.url.includes('/states'))data=[{id:'review',name:'Review',category:'in_progress'},{id:'done',name:'Done',category:'done'}];
   else if(req.url.includes('/teams'))data=[{id:'pipeline',name:'Pipeline Engineering'},{id:'support',name:'Support'}];
   res.setHeader('content-type','application/json');res.end(JSON.stringify(data));return;
  }next();
 });}}]});await server.listen();browser=await openBrowser({port:19452,profile:await mkdtemp('/tmp/radd-mapping-proof-'),width:1440,height:1000});
 const s=browser.session;await s.navigate('http://127.0.0.1:19451/__proof',3000);
 const initial=await s.eval('document.body.innerText');assert.ok(initial.includes('Severity (severity)'),initial);
 await s.click('summary',text=>text.includes('Translate values'));
 await s.click('button[aria-haspopup="listbox"]',text=>text.includes('Keep “P1”'));
 await s.click('[role="option"]',text=>text==='Critical');
 await s.click('button',text=>text.startsWith('Statuses'));
 assert.ok((await s.eval('document.body.innerText')).includes('Reporting category'));
 await s.click('button[aria-haspopup="listbox"]',text=>text.includes('Old missing state'));
 await s.click('[role="option"]',text=>text==='Review (in_progress)');
 await s.click('button',text=>text.trim()==='Save mappings');
 for(let i=0;i<50&&!saved;i++)await new Promise(r=>setTimeout(r,50));
 assert.equal(saved.mappings.fields[0].value_map.P1,'Critical');
 assert.equal(saved.mappings.statuses[0].state_name,'Review');
 assert.equal(saved.mappings.statuses[0].category,'in_progress');
 await s.screenshot('/tmp/radd-import-mapping-status-proof.png');
 await s.click('button',text=>text.startsWith('Fields'));
 const before=Date.now();await s.click('input[placeholder="Filter fields by name, id, or target key…"]');await s.send('Input.insertText',{text:'Domain'});
 for(let i=0;i<50;i++){if(!(await s.eval('document.body.innerText')).includes('Severity (severity)'))break;await new Promise(r=>setTimeout(r,25));}
 const filtered=await s.eval('document.body.innerText');assert.ok(filtered.includes('Domain'));assert.ok(!filtered.includes('Severity (severity)'));
 await s.click('summary',text=>text.includes('Translate values'));
 await s.click('button[aria-haspopup="listbox"]',text=>text.includes('Keep “Pipeline”'));
 await s.click('[role="option"]',text=>text==='Pipeline Engineering');
 await s.click('button',text=>text.trim()==='Save mappings');await new Promise(r=>setTimeout(r,100));
 assert.equal(saved.mappings.fields[1].value_map.Pipeline,'Pipeline Engineering');
 assert.deepEqual(s.consoleErrors,[]);await s.screenshot('/tmp/radd-import-mapping-field-proof.png');
 await s.navigate('http://127.0.0.1:19451/__proof?confluence',1500);
 await s.click('button[aria-haspopup="listbox"]',text=>text.includes('Create a space'));
 await s.click('[role="option"]',text=>text==='Skip');
 await s.click('button',text=>text.trim()==='Check');
 for(let i=0;i<50&&!confluenceWrites.includes('validate');i++)await new Promise(r=>setTimeout(r,50));
 assert.deepEqual(confluenceWrites,['save:ignore','validate']);
 await s.click('button',text=>text.trim()==='Dry run');
 for(let i=0;i<50&&!confluenceWrites.includes('run');i++)await new Promise(r=>setTimeout(r,50));
 assert.deepEqual(confluenceWrites,['save:ignore','validate','save:ignore','run']);
 await s.click('summary',text=>text.includes('unused entries'));
 await s.eval("[...document.querySelectorAll('tr')].find(r=>r.textContent.includes('Unused docs')).setAttribute('data-unused','yes')");
 await s.click('[data-unused] button[aria-haspopup="listbox"]',text=>text==='Skip');
 await s.click('[role="option"]',text=>text==='Use existing space');await new Promise(r=>setTimeout(r,200));
 await s.click('button[aria-haspopup="listbox"]',text=>text.includes('Choose a destination'));
 await s.click('[role="option"]',text=>text==='Company docs');
 await s.click('button',text=>text.startsWith('People'));
 await s.click('button[aria-label="Choose attribution account"]');await new Promise(r=>setTimeout(r,250));
 await s.click('button',text=>text==='Merged account');
 await s.click('button',text=>text.startsWith('Macros'));await new Promise(r=>setTimeout(r,200));
 await s.click('button[aria-haspopup="listbox"]',text=>text==='Contents');
 await s.click('[role="option"]',text=>text==='Callout');
 await s.click('button',text=>text.trim()==='Save');
 await new Promise(r=>setTimeout(r,200));
 assert.ok(confluencePlan.mappings.spaces.some(x=>x.key==='UNUSED'&&x.action==='map'&&x.space_id==='space-target'));
 assert.equal(confluencePlan.mappings.users[0].user_id,'target-user');
 assert.equal(confluencePlan.mappings.macros[0].extension,'callout');
 assert.deepEqual(s.consoleErrors,[]);
 console.log('PASS: Confluence existing-space, account and renderer selections save, including unused entries.');
 console.log('PASS: Confluence Check and Dry run each save the edited mapping before the action.');
 console.log(`PASS: status dropdown saves name/category; field/team translations save existing targets; 337-field catalog filters correctly (interaction sequence ${Date.now()-before} ms).`);
}finally{browser?.close();await server?.close();await rm(entry,{force:true});}
