import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {browserNumericControl,validateBrowserNumbers} from '../public/numeric-contract.js';
import {catalogSubmission,effectiveCatalogInterface} from '../public/catalog-submission.js';
import {catalogEditor,prepareCatalogSnapshot} from '../public/catalog-ui.js';

const schemas=JSON.parse(readFileSync(new URL('../public/workflow-interfaces.json',import.meta.url),'utf8')).workflows;
const catalog=JSON.parse(readFileSync(new URL('../public/local-catalog.json',import.meta.url),'utf8')).workflows;
const registry=JSON.parse(readFileSync(new URL('../workflows/compiled-registry.json',import.meta.url),'utf8')).workflows;
const affected=[[45,'53:value'],[50,'425:value'],[54,'121:value'],[55,'105:value_1'],[56,'132:value'],[57,'8:value'],[58,'14:value'],[63,'7:value'],[65,'144:value'],[71,'16:value'],[135,'12:widget_2']];
for(const [number,id] of affected)test(`exact integer boundary for local-card-${number} ${id}`,()=>{
 const ident=`local-card-${number}`,native=registry[ident].controls.find(f=>f.id===id);
 // A real response for these native INT64 bounds uses the browser-safe maximum.
 // test_browser_numeric_contract.py checks the production server projection.
 const projection={...native,max:Number.MAX_SAFE_INTEGER};
 const w={...catalog.find(w=>w.id===ident),interface:schemas[ident],catalogConnected:true,catalogConnection:{adapter:'generic',validation:'structural-verified',controls:[projection]}};
 const original=JSON.stringify(w.interface);
 assert(native.max>Number.MAX_SAFE_INTEGER);
 const cfg=effectiveCatalogInterface(w),field=cfg.controls.find(f=>f.id===id);
 assert.equal(field.max,Number.MAX_SAFE_INTEGER);
 const valid={prompt:'整数边界验证',refs:[],catalogValues:Object.fromEntries(cfg.controls.filter(f=>f.kind==='points').map(f=>[f.id,'{"positive":[{"x":0.5,"y":0.5}],"negative":[]}']))};
 const snapshot=prepareCatalogSnapshot(w,structuredClone(valid));
 assert.equal(catalogSubmission(w,snapshot).catalog_values[id],native.value);
 const html=catalogEditor(w,snapshot),input=html.match(new RegExp(`<input[^>]*data-catalog-field="${id}"[^>]*>`))?.[0];
 assert(input?.includes(`max="${Number.MAX_SAFE_INTEGER}"`),`${ident} must show the exact editable upper bound`);
 for(const value of [Number.MAX_SAFE_INTEGER+1,native.max,...(native.integer?[1.5]:[]),Infinity]){
  const draft=structuredClone(snapshot);draft.catalogValues[id]=value;
  assert.throws(()=>prepareCatalogSnapshot(w,draft),/整数|范围/);
  assert.throws(()=>catalogSubmission(w,draft),/整数|范围/);
 }
 assert.equal(JSON.stringify(w.interface),original,'raw schema and native limits are preserved');
});
test('safe integer values retain exact JSON identity and fractional controls retain their native ranges',()=>{
 const field={id:'integer',type:'number',integer:true,min:-9223372036854775808,max:9223372036854775807};
 const bounded=browserNumericControl(field);
 assert.equal(bounded.min,Number.MIN_SAFE_INTEGER);assert.equal(bounded.max,Number.MAX_SAFE_INTEGER);
 for(const number of [Number.MIN_SAFE_INTEGER,-1,0,1,Number.MAX_SAFE_INTEGER]){
  const draft=JSON.parse(JSON.stringify({catalogValues:{integer:number}}));
  validateBrowserNumbers({controls:[bounded]},draft);assert.equal(draft.catalogValues.integer,number);
 }
 const fractional={id:'seconds',type:'number',integer:false,max:1e18};
 assert.equal(browserNumericControl(fractional),fractional);
 validateBrowserNumbers({controls:[fractional]},{catalogValues:{seconds:1.5}});
});
