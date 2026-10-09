import assert from 'node:assert/strict';
import {existsSync,readFileSync} from 'node:fs';
import {test} from 'node:test';
import {runInNewContext} from 'node:vm';
import {processingPreviewGeometry,previewPointInSource} from '../public/point-picker.js';
import {expectedDuration} from '../public/control-guidance.js';
import {controlField,syncControlChoices} from '../public/workflow-controls.js';
import {catalogSubmission,effectiveCatalogInterface} from '../public/catalog-submission.js';

const read=path=>JSON.parse(readFileSync(new URL(path,import.meta.url),'utf8'));
const ui=read('../public/workflow-interfaces.json').workflows;
const registry=read('../workflows/compiled-registry.json').workflows;
const workflow=id=>({id,interface:ui[id],catalogConnected:true,catalogConnection:{...registry[id],supportedControlIds:registry[id].controls.map(f=>f.id)}});
const recipe=ui['local-card-51'].controls.find(f=>f.id==='1095:points').previewRecipe;
const cases=[
 {name:'default-rounded-source',source:[638,360],values:{}},
 {name:'default-wide-source',source:[1920,1080],values:{}},
 {name:'custom-960x640',source:[1920,1080],values:{'1084:custom_width':960,'1084:custom_height':640}},
 {name:'custom-width-only',source:[1920,1080],values:{'1084:custom_width':960,'1084:custom_height':0}},
 {name:'custom-height-only',source:[1920,1080],values:{'1084:custom_width':0,'1084:custom_height':640}},
 {name:'negative-width',source:[1920,1080],values:{'1084:custom_width':-1},invalid:true},
 {name:'undersized-pair',source:[1920,1080],values:{'1084:custom_width':32,'1084:custom_height':32},invalid:true},
 {name:'rounds-to-zero-pair',source:[1920,1080],values:{'1084:custom_width':1,'1084:custom_height':1},invalid:true},
 {name:'beyond-native-max',source:[1920,1080],values:{'1084:custom_width':8193},invalid:true},
 {name:'native-legal-long-side-too-large',source:[1920,1080],values:{'1105:value':65536},invalid:true},
 {name:'native-legal-long-side-too-small',source:[1920,1080],values:{'1105:value':4},invalid:true},
];
function geometryFixture(c){
 const supplied={...recipe,customWidth:c.values['1084:custom_width']??0,customHeight:c.values['1084:custom_height']??0};
 try{return {...c,result:processingPreviewGeometry(...c.source,supplied,c.values['1105:value']??recipe.longSide)};}
 catch(error){return {...c,error:error.message};}
}

// DOM boundaries implement attribute matching and mutation only. Geometry,
// boolean conversion, selections and submission all run production functions.
function renderedMode(field,draft){
 const html=controlField(draft,field),nodes=[];
 for(const match of html.matchAll(/<(?:div|input|button|small)\b([^>]*)>/g)){
  const attrs=new Map([...match[1].matchAll(/([\w:-]+)(?:="([^"]*)")?/g)].map(m=>[m[1],m[2]??'']));
  const node={attrs,dataset:Object.fromEntries([...attrs].filter(([k])=>k.startsWith('data-')).map(([k,v])=>[k.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase()),v])),checked:attrs.has('checked'),type:attrs.get('type'),textContent:'',hidden:attrs.has('hidden'),
   setAttribute(k,v){attrs.set(k,String(v));},getAttribute(k){return attrs.get(k)??null;},classList:{toggle(k,on){const classes=new Set((attrs.get('class')||'').split(/\s+/));on?classes.add(k):classes.delete(k);attrs.set('class',[...classes].join(' '));}},
   closest(selector){if(selector==='[data-catalog-mode]')return attrs.has('data-catalog-mode')?node:null;if(selector==='.workflow-inline-controls'||selector==='.wf-editor')return panel;throw new Error('Unexpected closest '+selector);}};
  nodes.push(node);
 }
 const matches=(node,selector)=>{const m=selector.match(/^\[([^\]=]+)(?:="([^"]*)")?\]$/);return m&&node.attrs.has(m[1])&&(m[2]===undefined||node.attrs.get(m[1])===m[2]);};
 const panel={nodes,querySelectorAll(selector){return nodes.filter(n=>selector.split(',').some(s=>matches(n,s.trim())));},querySelector(selector){return this.querySelectorAll(selector)[0]||null;}};
 return panel;
}
function exerciseMode(){
 const w=workflow('local-card-23'),field=effectiveCatalogInterface(w).controls.find(f=>f.id==='575:value');
 const draft={catalogValues:{},catalogTexts:{},refs:[]},session={draft},panel=renderedMode(field,draft);
 const source=readFileSync(new URL('../public/app.js',import.meta.url),'utf8');
 const statement=source.split(/\r?\n/).find(line=>line.startsWith("document.addEventListener('click',e=>{const b=e.target.closest('[data-catalog-mode]')"));
 assert.ok(statement,'Run the actual app mode listener');
 let handler,saves=0;
 runInNewContext(statement,{document:{addEventListener(name,fn){assert.equal(name,'click');handler=fn;}},workflow(s){assert.equal(s,session);return w;},active:()=>session,effectiveCatalogInterface,syncControlChoices,scheduleSave(){saves++;}});
 const results=[];
 for(const value of [true,false,true,false]){
  const button=panel.nodes.find(n=>n.dataset.catalogMode==='575:value'&&n.dataset.value===String(value));
  handler({target:button});
  assert.equal(typeof draft.catalogValues[field.id],'boolean');assert.equal(draft.catalogValues[field.id],value);
  assert.equal(panel.querySelector('[data-catalog-field="575:value"]').checked,value);
  const buttons=panel.querySelectorAll('[data-catalog-mode]').filter(n=>n.getAttribute('aria-pressed')==='true');
  assert.deepEqual(buttons.map(n=>n.dataset.value),[String(value)]);
  assert.equal(panel.querySelector('[data-catalog-mode-help]').textContent,field.options.find(o=>o.value===value).help);
  const request=catalogSubmission(w,draft);
  assert.equal(typeof request.catalog_values[field.id],'boolean');assert.equal(request.catalog_values[field.id],value);
  results.push(request.catalog_values[field.id]);
 }
 assert.equal(saves,4);
 return results;
}

if(process.argv.includes('--fixtures')){
 const duration=ui['local-card-125'].controls.find(f=>f.id==='208:value');
 console.log(JSON.stringify({geometry:cases.map(geometryFixture),modes:exerciseMode(),durations:[0,1,2,5,10,655].map(seconds=>({seconds,result:expectedDuration(duration,seconds)}))}));
}else{
 for(const c of cases)test('actual point preview '+c.name,()=>{const result=geometryFixture(c);assert.equal(Boolean(result.error),Boolean(c.invalid),result.error);if(!c.invalid){const center=previewPointInSource({x:.5,y:.5},result.result.crop);assert.ok(Math.abs(center.x-c.source[0]/2)<1e-6);assert.ok(Math.abs(center.y-c.source[1]/2)<1e-6);}});
 test('actual mode click, renderer and submission preserve boolean values',()=>assert.deepEqual(exerciseMode(),[true,false,true,false]));
 test('connected LTX scale preserves execution bounds and submits common fractions',t=>{
  const w=workflow('local-card-49'),field=effectiveCatalogInterface(w).controls.find(f=>f.id==='467:value');
  const bound=registry[w.id].controls.find(f=>f.id===field.id);
  assert.deepEqual([field.min,field.max,field.step],[bound.min,bound.max,bound.step]);
  const evidence=new URL('../private/workflow-video-review-2026-10-08/ltx-live-nodeinfo.json',import.meta.url);
  if(existsSync(evidence)){
   const native=read('../private/workflow-video-review-2026-10-08/ltx-live-nodeinfo.json').ImageScaleBy.input.required.scale_by[1];
   assert.deepEqual([field.min,field.max,field.step],[native.min,native.max,native.step]);
  }else t.diagnostic('Private live node snapshot comparison is local-only; public execution bounds are checked.');
  for(const scale of [.5,1,8])assert.equal(catalogSubmission(w,{catalogValues:{'467:value':scale},catalogTexts:{},refs:[]}).catalog_values['467:value'],scale);
  for(const scale of [0,8.01])assert.throws(()=>catalogSubmission(w,{catalogValues:{'467:value':scale},catalogTexts:{},refs:[]}),/范围|超过/);
 });
 test('LTX duration uses the connected 25fps 8n+1 contract and execution bound',t=>{
  const w=workflow('local-card-125'),field=effectiveCatalogInterface(w).controls.find(f=>f.id==='208:value');
  const bound=registry[w.id].controls.find(f=>f.id===field.id);
  assert.equal(field.max,bound.max);
  const evidence=new URL('../private/workflow-video-review-2026-10-08/ltx-live-nodeinfo.json',import.meta.url);
  if(existsSync(evidence)){
   const native=read('../private/workflow-video-review-2026-10-08/ltx-live-nodeinfo.json').EmptyLTXVLatentVideo.input.required.length[1];
   assert.equal(field.max,Math.floor((native.max-1)/25));
  }else t.diagnostic('Private live node snapshot comparison is local-only; public execution bounds are checked.');
  assert.deepEqual(expectedDuration(field,2),{frames:49,fps:25,seconds:1.96});
  assert.deepEqual(expectedDuration(field,5),{frames:121,fps:25,seconds:4.84});
  assert.throws(()=>catalogSubmission(w,{catalogValues:{'208:value':656},catalogTexts:{},refs:[]}),/范围|超过/);
 });
}
