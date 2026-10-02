import assert from 'node:assert/strict';
import {readFileSync,writeFileSync,mkdirSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {catalogEditor} from '../public/catalog-ui.js';
import {controlField} from '../public/workflow-controls.js';
import {workflowControls,advancedFields} from '../public/advanced.js';
import {liveWorkflowEditor} from '../public/workflow-page.js';

// Audit the actual rendered forms, including the non-catalog entry points.
const catalog=JSON.parse(readFileSync('public/local-catalog.json')).workflows;
const schemas=JSON.parse(readFileSync('public/workflow-interfaces.json')).workflows;
const kinds={},totals={controls:0,texts:0,media:0,apis:0,exactSharedFields:0,sharedContextFields:0},rows=[];
const styleSheets=path=>[...readFileSync(path,'utf8').matchAll(/href="([^"]+\.css\?v=[^"]+)"/g)].map(m=>m[1]);
const productionStyles=styleSheets('public/studio.html');
const libraryStyles=styleSheets('public/workflow-control-library.html');
assert.deepEqual(libraryStyles.filter(x=>x!=='workflow-control-library.css?v=60.1'),productionStyles,'component library and production CSS must match');
for(const w of catalog){
 const cfg=schemas[w.id],draft={prompt:'',refs:[],catalogValues:{}},html=catalogEditor({...w,interface:cfg},draft);
 const ids=[...html.matchAll(/data-catalog-field="([^"]+)"/g)].map(x=>x[1]);
 assert.deepEqual(ids.toSorted(),cfg.controls.map(f=>f.id).toSorted(),w.id+' field identity');
 assert.equal(ids.length,new Set(ids).size,w.id+' duplicate values');
 const selects=[...html.matchAll(/<select\b[^>]*>/g)].map(x=>x[0]);
 assert.ok(selects.every(s=>s.includes('wf-select-value')),w.id+' native parameter menu');
 assert.ok(!html.includes('data-popup=')&&!html.includes('<details'),w.id+' hidden parameter group');
 const variants=[];
 for(const f of cfg.controls){
  kinds[f.kind]=(kinds[f.kind]||0)+1;
  const markup=controlField(draft,f);
  const variant=markup.match(/^<(?:div|label|section)\b[^>]*class="([^"]+)"/)?.[1]||markup.slice(0,70);
  const exact=html.includes(markup);
  const sharedContext=f.kind==='seed'||(f.kind==='camera'&&cfg.controls.filter(x=>x.kind==='camera').length>3);
  assert.ok(exact||sharedContext,w.id+' '+f.id+' drifted from shared renderer');
  if(exact)totals.exactSharedFields++;else totals.sharedContextFields++;
  variants.push({id:f.id,kind:f.kind,variant,sharedRender:exact?'exact':'shared-context'});
 }
 totals.controls+=cfg.controls.length;totals.texts+=cfg.texts.length;totals.media+=cfg.media.length;totals.apis+=(cfg.apiProfiles||[]).length;
 rows.push({id:w.id,name:w.name,controls:ids,kinds:[...new Set(cfg.controls.map(f=>f.kind))],variants,sharedSelects:selects.length,media:cfg.media.map(m=>m.kind),status:'render-contract-passed'});
}
const demos=Object.entries(workflowControls).map(([id,spec])=>{
 const html=advancedFields({advanced:{}},{id});
 for(const f of spec.fields)assert.ok(html.includes(`data-advanced${f.type==='choice'?'-choice':''}="${f.key}"`),id+' '+f.key);
 return {id,fields:spec.fields.length,renderer:'advancedFields',status:'render-contract-passed'};
});
const live=await fetch('http://127.0.0.1:8770/api/workflows').then(r=>r.json());
const independent=live.map(w=>{
 const values=Object.fromEntries(w.fields.map(f=>[f.key,f.default]));
 const html=liveWorkflowEditor({w,d:{prompt:'',refs:[]},values,refs:'',error:'',upload:''});
 if(w.id==='h3-reference')assert.ok(html.includes('catalog-ratio-option'),'H3 shares dimension cards');
 return {id:w.id,fields:[...new Set([...html.matchAll(/data-live-(?:choice|field)="([^"]+)"/g)].map(x=>x[1]))],renderer:'liveWorkflowEditor'};
});
const auditDir=process.argv[2]||'private/review59';
const baseline=JSON.parse(readFileSync(auditDir+'/parameter-baseline.json','utf8').replace(/^\uFEFF/,''));
const preservation=baseline.map(x=>{const hash=createHash('sha256').update(readFileSync(x.Path)).digest('hex').toUpperCase();assert.equal(hash,x.Hash,x.Path+' changed');return {file:x.Path.split('\\').at(-1),sha256:hash,unchanged:true};});
mkdirSync(auditDir,{recursive:true});
writeFileSync(auditDir+'/component-audit.json',JSON.stringify({scope:'rendered forms, shared component identity, and source preservation; not live generation or all-page visual acceptance',totals,kinds,sharedStyleSheets:productionStyles,preservation,localWorkflows:rows,independent,demos},null,2));
console.log(JSON.stringify({local:rows.length,independent:independent.length,demos:demos.length,...totals,kinds:Object.keys(kinds).length,sourceFilesUnchanged:preservation.length}));
