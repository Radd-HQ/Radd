/** RADD-1425: Automations edits and validates only the actions it declares; a plugin's action is the
 * plugin's form and the server's verdict, never blocked by the editor. */
import test from 'node:test';
import assert from 'node:assert/strict';
import {readdirSync, readFileSync} from 'node:fs';
import path from 'node:path';
import {parse} from '@babel/parser';
import {importTs} from './lib/load-ts.mjs';

const ui='server/src/radd/modules/automations/ui/src';
const {hasCoreEditor,incompleteActionNodeIds,isBuiltinAction}=await importTs(`${ui}/builtin-actions.ts`);
const {ActionType}=await importTs(`${ui}/types.ts`);
// The remote imports the automations contract by package name; here it resolves by path.
const {isRecipientRole,withRecipientArity}=await importTs('server/src/radd/modules/mailintake/ui/src/send-email.ts',
  source=>source.replace('"@radd-plugin-ui/automations/types"','"../../../automations/ui/src/types"'));

test('a contributed action is drawn by its plugin and never blocks the save',()=>{
  for (const type of ['action.send_email','action.add_participant','action.from_a_new_plugin']) {
    assert.equal(hasCoreEditor(type),false,type);
    assert.equal(isBuiltinAction(type),false,type);
  }
  // Empty params the server would refuse: that is the server's 422 to give, not the editor's.
  const contributed=[
    {id:'mail',type:'action.send_email',params:{}},
    {id:'share',type:'action.add_participant',params:{user:''}},
    {id:'other',type:'action.from_a_new_plugin',params:{}},
  ];
  assert.deepEqual(incompleteActionNodeIds(contributed),[]);
});

test('a built-in action is still refused up front when incomplete',()=>{
  for (const type of ['action.set_priority','action.notify_user','gate.payload','trigger.event','verdict.block']) assert(hasCoreEditor(type),type);
  const nodes=[
    {id:'blank',type:'action.set_priority',params:{priority:' '}},
    {id:'set',type:'action.set_priority',params:{priority:'high'}},
    {id:'half',type:'action.notify_user',params:{user:'reporter',message:''}},
    {id:'gate',type:'gate.payload',params:{}},
  ];
  assert.deepEqual(incompleteActionNodeIds(nodes),['blank','half']);
});

test('the built-in set is exactly the server\'s ActionType',()=>{
  const source=readFileSync('server/src/radd/modules/automations/types.py','utf8');
  const start=source.indexOf('class ActionType(StrEnum):');
  assert(start>=0,'the server enum moved');
  const body=source.slice(start,source.indexOf('\nclass ',start+1));
  const server=[...body.matchAll(/^ {4}[A-Z_]+ = "([a-z_]+)"$/gm)].map(match=>match[1]).sort();
  assert(server.length>=25,'the scan must read the enum');
  assert.deepEqual(Object.values(ActionType).sort(),server);
});

test('Send email\'s recipient rule is mailintake\'s: a role runs once per issue',()=>{
  assert.deepEqual(withRecipientArity({to:' Reporter ',subject:'s'}),{to:' Reporter ',subject:'s',arity:'item'});
  assert.deepEqual(withRecipientArity({to:'contact',arity:'set'}),{to:'contact',arity:'item'});
  for (const params of [{to:'ops@example.com'},{to:'{{triage.owner}}',arity:'set'},{to:'assignee',arity:'item'}]) {
    assert.equal(withRecipientArity(params),params,'unchanged params are the same object: no edit, no re-render');
  }
  assert.equal(isRecipientRole('someone@example.com'),false);
});

test('Automations names none of the actions its plugins own',()=>{
  const files=readdirSync(ui).filter(name=>/\.tsx?$/.test(name)).map(name=>path.join(ui,name));
  assert(files.length>30,'the scan must reach the package');
  const moved=/send_?email|add_?participant|EmailRecipient/i;
  const found=[];
  for (const file of files) {
    const walk=node=>{
      if (!node||typeof node!=='object') return;
      if (Array.isArray(node)) {node.forEach(walk);return;}
      const text=node.type==='Identifier'||node.type==='JSXIdentifier'?node.name:node.type==='StringLiteral'?node.value
        :node.type==='TemplateElement'?node.value.raw:null;
      if (text!==null&&moved.test(text)) found.push(`${file}:${node.loc?.start.line}: ${text}`);
      for (const [key,value] of Object.entries(node)) if (key!=='loc'&&value&&typeof value==='object') walk(value);
    };
    walk(parse(readFileSync(file,'utf8'),{sourceType:'module',plugins:['typescript','jsx']}).program);
  }
  assert.deepEqual(found,[]);
});
