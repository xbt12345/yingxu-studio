import assert from 'node:assert/strict';
import {liveWorkflowEditor} from '../public/workflow-page.js';

const workflows=await fetch((process.env.YINGXU_TEST_URL||'http://127.0.0.1:8770')+'/api/workflows').then(r=>{assert.ok(r.ok);return r.json();});
for(const w of workflows){
 const values=Object.fromEntries(w.fields.map(f=>[f.key,f.default]));
 for(const mode of ['random','fixed']){
  const d={prompt:'布局验证',negative:'',refs:[],liveSeedMode:mode};
  const html=liveWorkflowEditor({w,d,values,refs:'',error:'',upload:'<button>选择素材</button>'});
  assert.ok(!html.includes('data-popup='));assert.ok(!html.includes('<details'));
  const shown=[...new Set([...html.matchAll(/data-live-(?:field|choice)="([^"]+)"/g)].map(m=>m[1]))].sort();
  assert.deepEqual(shown,w.id==='h3-reference'?['duration','megapixels','ratio','seed']:['long_side','seed']);
  assert.equal([...html.matchAll(/data-live-field="seed"/g)].length,1);
  assert.ok(!html.match(/data-live-(?:field|choice)="(?:steps|cfg|fps|shift_video|shift_audio|ref_size)"/),'previously hidden defaults must stay hidden');
 }
}
console.log(JSON.stringify({liveWorkflows:workflows.length,previousVisibleAttributes:'preserved',parameterPopups:0,seedModes:'passed'}));
