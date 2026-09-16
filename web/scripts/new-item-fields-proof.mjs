/** RADD-1158: real API + built SPA. Run only against an isolated disposable instance.
 * Requires --base and RADD_PROOF_EMAIL/RADD_PROOF_PASSWORD. Creates synthetic
 * projects, fields and items, then removes them. Never defaults to a live host.
 */
import assert from 'node:assert/strict';
import { mkdtemp } from 'node:fs/promises';
import { openBrowser, sleep } from './lib/cdp.mjs';
const args = process.argv.slice(2);
const base = args[args.indexOf('--base') + 1];
assert(args.includes('--base') && new URL(base).hostname === '127.0.0.1', 'Isolated localhost base required');
assert(process.env.RADD_PROOF_EMAIL && process.env.RADD_PROOF_PASSWORD, 'Synthetic test credentials required');
const browser = await openBrowser({port: 19358, profile: await mkdtemp('/tmp/radd-fields-proof-')});
const s = browser.session;
const projects = [], fields = [];
const suffix = Date.now().toString(36).slice(-5);
async function api(method, path, body) {
  const result = await s.eval(`(async()=>{const r=await fetch('/api/v1'+${JSON.stringify(path)}, {method:${JSON.stringify(method)},headers:{'Content-Type':'application/json'},body:${body === undefined ? 'undefined' : `JSON.stringify(${JSON.stringify(body)})`}});return {status:r.status,text:await r.text()};})()`);
  assert(result.status < 300, `${method} ${path}: ${result.status} ${result.text}`);
  return result.text ? JSON.parse(result.text) : null;
}
try {
  await s.navigate(base + '/login');
  await s.login(base, process.env.RADD_PROOF_EMAIL, process.env.RADD_PROOF_PASSWORD);
  for (const letter of ['A', 'B']) projects.push(await api('POST','/projects',{key:`PF${letter}${suffix}`.toUpperCase(),name:`Field proof ${letter}`}));
  for (const [name, project_ids] of [['Global proof', []], ['Alpha proof', [projects[0].id]], ['Beta proof', [projects[1].id]], ['Shared proof', projects.map(p=>p.id)]]) {
    fields.push(await api('POST','/fields',{key: name.split(' ')[0].toLowerCase()+'_'+suffix,name,type:'text',project_ids}));
  }
  for (const index of [0,1,0]) {
    const project=projects[index];
    await s.navigate(`${base}/p/${project.key}/issues`, 800);
    await s.click('button', text=>/^\s*new item\s*$/i.test(text));
    await sleep(500);
    if (await s.eval(`document.querySelector('[role=dialog]').innerText.includes('choose a project')`)) {
      await s.click('[role=dialog] input');
      await s.send('Input.insertText', {text:project.key});
      await sleep(500);
      await s.click('[role=dialog] button', new Function('text', `return text.includes(${JSON.stringify(project.key)})`));
      await sleep(500);
    }
    const text=await s.eval(`document.querySelector('[role=dialog]').innerText`);
    assert(text.includes('Global proof') && text.includes('Shared proof'));
    assert(text.includes(index===0?'Alpha proof':'Beta proof'));
    assert(!text.includes(index===0?'Beta proof':'Alpha proof'));
    const chosen=fields[index+1];
    await s.eval(`(() => {
      const d=document.querySelector('[role=dialog]');
      const fill=(label,value)=>{
        const l=[...d.querySelectorAll('label')].find(n=>n.textContent.trim()===label);
        const input=l?.control ?? l?.querySelector('input') ?? d.querySelector('#'+CSS.escape(l?.htmlFor));
        if(!input) throw new Error('Missing input '+label);
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,value);
        input.dispatchEvent(new Event('input',{bubbles:true}));
      };
      fill('Title',${JSON.stringify('Scope proof '+Date.now())});
      fill(${JSON.stringify(chosen.name)},'saved value');
    })()`);
    await s.click('button[type=submit]',text=>/Create item/i.test(text));
    for(let i=0;i<50 && await s.eval(`!!document.querySelector('[role=dialog]')`);i++) await sleep(100);
    assert.equal(await s.eval(`!!document.querySelector('[role=dialog]')`),false,'Create should succeed');
    const items=await api('GET',`/items?project_id=${project.id}`);
    assert(items.some(item=>item.custom_fields[chosen.key]==='saved value'));
    assert(items.every(item=>!(fields[2-index].key in item.custom_fields)));
  }
  assert.deepEqual(s.consoleErrors, []);
  console.log('PASS: A → B → A creation, global/shared/project fields, excluded fields absent, saved values verified by API.');
} finally {
  for(const field of fields.reverse()) await api('DELETE',`/fields/${field.id}`).catch(console.error);
  for(const project of projects.reverse()) await api('DELETE',`/projects/${project.id}`).catch(console.error);
  await browser.close();
}
