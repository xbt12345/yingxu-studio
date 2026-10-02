import assert from 'node:assert/strict';
import fs from 'node:fs';
import {catalogEditor,catalogCommonPanel,prepareCatalogSnapshot} from '../public/catalog-ui.js';
import {cloneDraft} from '../public/advanced.js';

const catalog=JSON.parse(fs.readFileSync(new URL('../public/local-catalog.json',import.meta.url),'utf8')).workflows;
const interfaces=JSON.parse(fs.readFileSync(new URL('../public/workflow-interfaces.json',import.meta.url),'utf8')).workflows;
let seedCount=0;
for(const original of catalog){
 const w={...original,interface:interfaces[original.id]},untouched=JSON.stringify(w);
 const draft={prompt:'复现验证',refs:[],catalogValues:{},catalogTexts:{},catalogSeedModes:{}};
 const first=prepareCatalogSnapshot(w,cloneDraft(draft)),second=prepareCatalogSnapshot(w,cloneDraft(draft));
 assert.equal(first.workflowSourceHash,w.interface.sourceHash);
 for(const f of w.fields)if(!w.interface.controls.some(c=>c.kind==='seed'&&(c.members||[c]).some(m=>m.id===f.id)))assert.equal(first.catalogValues[f.id],f.value,`${w.id}: hidden default ${f.id}`);
 for(const f of w.interface.controls){
  assert.ok(Object.hasOwn(first.catalogValues,f.id),`${w.id}: missing snapshot ${f.id}`);
  if(f.kind!=='seed')continue;
  for(const m of f.members||[f])assert.equal(first.catalogValues[m.id],first.catalogValues[f.id]);
  seedCount++;assert.ok(Number.isSafeInteger(first.catalogValues[f.id])&&first.catalogValues[f.id]>=0);
  assert.notEqual(first.catalogValues[f.id],second.catalogValues[f.id]);
  assert.equal(first.catalogSeedModes[f.id],'fixed');
 }
 const panel=catalogCommonPanel(w,draft);
 for(const f of w.interface.controls.filter(c=>c.key==='megapixels')){
  const min=f.customRange?.min??f.min,max=f.customRange?.max??f.max,step=f.customRange?.step??f.step;
  const choices=[...panel.matchAll(/data-catalog-preset="([^"]+)" data-value="([^"]+)"/g)].filter(m=>m[1]===f.id).map(m=>Number(m[2]));
  assert.ok(choices.length,`${w.id}: no valid MP presets`);
  for(const n of choices){
   assert.ok((min===undefined||n>=min)&&(max===undefined||n<=max),`${w.id}: MP preset outside source range`);
   if(Number(step)>0){const k=(n-(min??0))/Number(step);assert.ok(Math.abs(k-Math.round(k))<1e-6,`${w.id}: MP preset violates source step`);}
  }
 }
 const restored=prepareCatalogSnapshot(w,cloneDraft(first));
 assert.deepEqual(restored.catalogValues,first.catalogValues,`${w.id}: fixed restoration`);
 const redraw=prepareCatalogSnapshot(w,cloneDraft(first),{redraw:true});
 for(const f of w.interface.controls){if(f.kind==='seed')assert.notEqual(redraw.catalogValues[f.id],first.catalogValues[f.id]);else assert.equal(redraw.catalogValues[f.id],first.catalogValues[f.id]);}
 assert.deepEqual(draft.catalogValues,{});assert.equal(JSON.stringify(w),untouched);
 const seed=w.interface.controls.find(f=>f.kind==='seed');if(seed){const invalid=cloneDraft(first);invalid.catalogValues[seed.id]=Number.MAX_SAFE_INTEGER+1;assert.throws(()=>prepareCatalogSnapshot(w,invalid),/整数/);}
 // Every configured media port must stay directly editable, empty and populated alike.
 for(const populated of [false,true]){
   const refs=populated?w.interface.media.map((m,i)=>({id:'图片'+(i+1),catalogSlot:m.id,kind:m.kind,src:'assets/coast.jpg',name:'test'})):[];
   const html=catalogEditor(w,{...cloneDraft(draft),refs});
   const shown=[...html.matchAll(/data-catalog-slot="([^"]+)"/g)].map(m=>m[1]).sort();
   assert.deepEqual(shown,w.interface.media.map(m=>m.id).sort(),`${w.id}: omitted or duplicate media port`);
   assert.ok(![...html.matchAll(/<details\b[^>]*>([\s\S]*?)<\/details>/g)].some(m=>m[1].includes('data-catalog-slot')),`${w.id}: media hidden in disclosure`);
   assert.ok(!html.includes('aria-label="引用素材"'),`${w.id}: duplicate reference toolbar`);
   assert.ok(!html.includes('data-popup='),`${w.id}: parameter popup remains`);
   assert.ok(!html.includes('<details'),`${w.id}: parameters remain collapsed`);
   const fields=[...html.matchAll(/data-catalog-field="([^"]+)"/g)].map(m=>m[1]).sort();
   assert.deepEqual(fields,w.interface.controls.map(f=>f.id).sort(),`${w.id}: changed, missing or duplicate inline parameter`);
   const texts=[...html.matchAll(/data-catalog-text="([^"]+)"/g)].map(m=>m[1]).sort();
   assert.deepEqual(texts,w.interface.texts.map(f=>f.id).sort(),`${w.id}: changed inline text inputs`);
   const apis=[...html.matchAll(/data-catalog-api="([^"]+)" data-api-field="mode"/g)].map(m=>m[1]).sort();
   assert.deepEqual(apis,(w.interface.apiProfiles||[]).map(f=>f.id).sort(),`${w.id}: changed API profiles`);
 }
}
assert.equal(catalog.length,151);
assert.equal(interfaces['local-card-1'].texts.find(t=>t.role==='prompt').id,'459:prompt');
assert.equal(interfaces['local-card-55'].controls.find(c=>c.kind==='duration').id,'105:value_1');
assert.deepEqual(interfaces['local-card-56'].media.map(m=>[m.id,m.label]),[['130','首帧'],['136','尾帧']]);
assert.equal(interfaces['local-card-72'].controls.filter(c=>c.kind==='camera').length,27);
assert.ok(!interfaces['local-card-98'].controls.some(c=>c.node==='ImageFromBatch'&&c.key==='length'));
assert.equal(interfaces['local-card-134'].controls[0].kind,'color');
console.log(JSON.stringify({workflows:catalog.length,seedBindings:seedCount,randomFixedRedrawRecovery:'passed',sourceDefaults:'preserved',criticalGraphBindings:'passed',mediaPortsAlwaysVisible:'passed',allParameterBindingsInline:'passed',megapixelPresetConstraints:'passed'}));

const clean=interfaces['local-card-92'];assert.ok(clean.controls.some(c=>c.kind==='mask'&&c.options.length===3));assert.ok(clean.texts.some(t=>t.id==='22:value'));assert.equal(clean.controls.filter(c=>c.kind==='seed').length,1);
assert.deepEqual(interfaces['local-card-103'].controls.filter(c=>c.kind==='seed').map(c=>c.id),['3:seed','79:seed','85:seed']);
assert.equal(interfaces['local-card-79'].texts[0].id,'19:prompt');assert.ok(interfaces['local-card-79'].controls.some(c=>c.kind==='count'));
assert.equal(interfaces['local-card-136'].media.length,0);assert.ok(interfaces['local-card-136'].controls.some(c=>c.label==='本地素材目录'));
assert.deepEqual(interfaces['local-card-136'].controls.find(c=>c.id==='61:mode').options.map(o=>o.value),['single_video','incremental_video','random']);
assert.deepEqual(interfaces['local-card-74'].controls.find(c=>c.id==='361:widget_0').targets.map(t=>t.input).sort(),['max_size','max_size','scale_to_length','scale_to_length']);
assert.equal(interfaces['local-card-34'].apiProfiles.length,2);assert.equal(interfaces['local-card-34'].controls.filter(c=>c.kind==='seed').length,2);
assert.ok(!JSON.stringify(interfaces).match(/sk-[A-Za-z0-9_-]{12,}/));assert.ok(interfaces['local-card-0'].texts.every(t=>t.id!=='579:prompt'));
for(const w of catalog.filter(w=>['文字生图','视频编辑与人物替换','参考图生视频'].includes(w.category)))
 assert.ok(interfaces[w.id].texts.some(t=>t.role==='prompt'),`${w.id}: missing source-bound positive prompt`);
assert.equal(interfaces['local-card-85'].texts.find(t=>t.role==='prompt').id,'67:value');
assert.equal(interfaces['local-card-85'].texts.find(t=>t.role==='negative').id,'66:text');
assert.equal(interfaces['local-card-108'].texts.find(t=>t.role==='prompt').id,'63:value');
assert.equal(interfaces['local-local-03ae6981ed'].texts.find(t=>t.role==='prompt').id,'400:value');
assert.equal(interfaces['local-local-16cf1a4ad1'].texts.find(t=>t.role==='prompt').id,'270:value');
assert.ok(!interfaces['local-card-118'].texts.some(t=>t.role==='prompt'));
assert.ok(!interfaces['local-card-135'].controls.some(c=>c.kind==='seed'));

// Single/two-image comparisons use one prompt and seed, bound to both native branches.
for(const id of ['local-card-17','local-card-18']){
 const cfg=interfaces[id],seed=cfg.controls.find(c=>c.kind==='seed');
 assert.deepEqual(cfg.media.map(m=>m.id),['76','81']);
 assert.deepEqual(seed.members.map(m=>m.nodeId),id.endsWith('17')?['101','118']:['104','117']);
 assert.equal(cfg.texts.filter(t=>t.role==='prompt').length,1);
 assert.deepEqual(cfg.texts.find(t=>t.role==='prompt').targets.map(t=>t.node),id.endsWith('17')?['109','121']:['107','127']);
}
assert.deepEqual(interfaces['local-card-20'].media.map(m=>m.id),['43']);
assert.deepEqual(interfaces['local-card-20'].controls.filter(c=>c.kind==='seed').map(c=>c.nodeId),['7']);
assert.deepEqual(interfaces['local-card-16'].media.map(m=>m.label),['待编辑原图','修改参考图']);
assert.equal(interfaces['local-card-16'].annotation.optional,true);
assert.deepEqual(interfaces['local-card-16'].annotation.slots,['36']);
assert.equal(interfaces['local-card-11'].controls.find(c=>c.key==='resolution').nodeId,'162');
assert.equal(interfaces['local-card-18'].texts.filter(t=>t.role==='negative').length,1);
for(const [id,label] of [['local-card-11','Qwen 分支 · 不希望出现的内容'],['local-card-18','不希望出现的内容']]){
 const w={...catalog.find(w=>w.id===id),interface:interfaces[id]};
 assert.ok(catalogEditor(w,{prompt:'',refs:[],catalogValues:{}}).includes(label));
}
const oldMultiNegative={...catalog.find(w=>w.id==='local-card-75'),interface:interfaces['local-card-75']};
assert.ok(catalogEditor(oldMultiNegative,{prompt:'',refs:[],catalogValues:{}}).includes('分支 1 · 不希望出现的内容'));

// These checks cover omissions found in the source graphs, not just agreement
// between a generated config and the UI that consumes it.
assert.ok(interfaces['local-card-5'].texts.some(t=>t.id==='414:string'&&t.role==='prompt'));
assert.equal(interfaces['local-card-44'].texts.find(t=>t.id==='5158:text').role,'negative');
assert.ok(interfaces['local-card-45'].controls.some(c=>c.id==='53:value'));
assert.ok(interfaces['local-card-123'].controls.some(c=>c.id==='1:scale'));
assert.ok(interfaces['local-card-8'].texts.some(t=>t.id==='2:system_prompt'));
for(const [id,node]of [[32,'31'],[33,'29']])assert.ok(interfaces['local-card-'+id].texts.some(t=>t.id===node+':role'));
assert.ok(!interfaces['local-card-102'].texts.some(t=>['56:prompt','57:prompt'].includes(t.id)));
assert.ok(interfaces['local-card-102'].controls.some(c=>c.id==='57:prompt'&&c.kind==='segment'));
assert.deepEqual(interfaces['local-card-34'].presentation.branches.map(b=>b.label),['文字扩写','图片反推']);
const migrated=(id,values)=>prepareCatalogSnapshot({...catalog.find(w=>w.id===id),interface:interfaces[id]},{prompt:'',refs:[],catalogValues:values});
assert.equal(migrated('local-card-7',{'45:frame_load_cap':48}).catalogValues['45:frame_load_cap:seconds'],2);
assert.equal(migrated('local-card-7',{'45:frame_load_cap:seconds':2.5}).catalogValues['45:frame_load_cap'],60);
const audio=migrated('local-card-98',{'15:offset_seconds':3,'15:duration_seconds':8});
assert.equal(audio.catalogValues['15:audio_end_seconds'],11);
assert.equal(migrated('local-card-98',{'15:offset_seconds':3,'15:audio_end_seconds':10}).catalogValues['15:duration_seconds'],7);
assert.throws(()=>migrated('local-card-98',{'15:offset_seconds':3,'15:audio_end_seconds':2}),/终点/);
for(const cfg of Object.values(interfaces))for(const f of [...cfg.controls,...cfg.texts])assert.ok(!f.help||(!f.help.includes('\n')&&f.help.length<=12));
console.log(JSON.stringify({sourceOmissions:'covered',secondsToNativeFrames:'passed',audioEndToNativeDuration:'passed',oldDraftMigration:'passed'}));
