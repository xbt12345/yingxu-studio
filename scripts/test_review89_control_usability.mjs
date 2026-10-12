import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import {catalogConnectionState,effectiveCatalogInterface,catalogSubmission} from '../public/catalog-submission.js';
import {catalogEditor,catalogOverview,apiPanel,prepareCatalogSnapshot} from '../public/catalog-ui.js';
import {controlField,syncControlChoices} from '../public/workflow-controls.js';
import {rangeText,syncTaskMeaning} from '../public/control-guidance.js';

const json=path=>JSON.parse(readFileSync(new URL(path,import.meta.url),'utf8'));
const schemas=json('../public/workflow-interfaces.json').workflows;
const catalog=json('../public/local-catalog.json').workflows;
const registry=json('../workflows/compiled-registry.json').workflows;
const workflow=id=>({...catalog.find(w=>w.id===id),interface:schemas[id],catalogConnected:!!registry[id],catalogConnection:registry[id]});
const draft=()=>({prompt:'描述',refs:[],catalogValues:{},catalogTexts:{},catalogSeedModes:{}});

test('local display preserves demo and blocked actions while hiding costs',()=>{
 const cases=[
  [{},'演示生成','演示模式'],
  [{catalogConnection:{validation:'blocked',blocking_reason:'缺少依赖'}},'暂不可生成','暂不可生成'],
  [{catalogConnected:true},'生成','已接入'],
  [{catalogConnected:true,catalogConnection:{adapter:'generic',external_api_account:true}},'生成','已接入'],
  [{catalogPendingApi:true},'生成','待自有 API 验证'],
 ];
 for(const [w,button,label]of cases){const local=catalogConnectionState(w,{hideCosts:true}),normal=catalogConnectionState(w);assert.equal(local.button,button);assert.equal(local.label,label);assert.equal(local.blocked,normal.blocked);assert.doesNotMatch(local.button,/计费|免费/);}
});

test('actual mixed media workflows name uploads and mark every required kind',()=>{
 for(const id of ['local-card-0','local-card-98','local-card-99']){
  const w=workflow(id),cfg=effectiveCatalogInterface(w),html=catalogEditor(w,draft(),{localMode:true});
  for(const article of html.matchAll(/<article class="catalog-input-card" data-catalog-drop-slot="([^"]+)"[\s\S]*?<\/article>/g)){
   const slot=cfg.media.find(item=>item.id===article[1]);assert.ok(slot);
   assert.match(article[0],/<input type="file"[^>]+aria-label="上传[^"]+"/);
   assert.equal(article[0].includes('class="catalog-required"'),slot.required!==false,`${id} ${slot.id}`);
  }
 }
 const imported={...workflow('local-card-0'),catalogConnected:false,catalogConnection:undefined,interface:{controls:[],texts:[],media:[{id:'optional-video',kind:'video',label:'参考视频',optional:true}]}};
 const optionalHtml=catalogEditor(imported,draft());assert.match(optionalHtml,/class="catalog-optional">可选/);assert.doesNotMatch(optionalHtml,/class="catalog-required"/);
});

test('empty guidance distinguishes image video and audio and does not invent media',()=>{
 const base={id:'test-overview',output:'video',interface:{controls:[],texts:[],media:[]}};
 const overview=(media,texts=[])=>catalogOverview({...base,interface:{...base.interface,media,texts}});
 assert.match(overview([{kind:'image'},{kind:'video'}]),/1 张图片、1 段视频/);
 assert.match(overview([{kind:'image'},{kind:'audio'}]),/1 张图片、1 段音频/);
 assert.match(overview([{kind:'image'},{kind:'image'}]),/2 张图片/);
 assert.doesNotMatch(overview([{kind:'image',required:false}]),/1 张图片/);
 assert.match(overview([],[{role:'prompt'}]),/填写描述并设置参数/);
});

test('API model names have explicit labels for readonly text and custom menus',()=>{
 const w=workflow('local-card-0'),profile=effectiveCatalogInterface(w).apiProfiles[0];assert.ok(profile);
 const modelId='catalog-api-model-'+profile.id.replace(/[^a-zA-Z0-9]/g,'-');
 const text=apiPanel(w,draft());assert.ok(text.includes(`for="${modelId}"`));
 assert.match(text,/<input id="catalog-api-model-[^"]+" aria-label="[^"]+模型名称"/);
 const menus={...w,catalogConnection:undefined,interface:{...w.interface,apiProfiles:[{...profile,modelOptions:['a','b'],model:'a'}]}};
 const custom=apiPanel(menus,{...draft(),catalogApis:{[profile.id]:{mode:'custom',model:'b'}}});
 assert.ok(custom.includes(`for="${modelId}-trigger"`));assert.match(custom,/role="combobox" aria-label="[^"]+模型名称"/);
});

test('native frame counts retain frames and derived duration controls retain seconds',()=>{
 for(const id of ['local-card-39','local-card-40','local-card-126']){
  const f=schemas[id].controls.find(f=>f.label==='生成帧数');assert.ok(f);
  const before=structuredClone(f),html=controlField(draft(),f);
  assert.match(rangeText(f),/ 帧(?: ·|$)/);assert.doesNotMatch(rangeText(f),/ 秒/);
  assert.ok(html.includes(`value="${f.value}"`));assert.deepEqual(f,before);
 }
 for(const f of Object.values(schemas).flatMap(w=>w.controls).filter(f=>f.derived?.operation==='frames'))assert.match(rangeText(f),/ 秒/);
});

test('compiled task enums use the shared selector without changing task values or submission',()=>{
 for(const id of ['local-card-39','local-card-40']){
  const w=workflow(id),f=effectiveCatalogInterface(w).controls.find(f=>f.kind==='task');assert.equal(f.options.length,12);
  const state=draft(),html=controlField(state,f);assert.match(html,/data-task-mode/);assert.match(html,/<select[^>]+data-catalog-field=/);assert.match(html,/参考图生成视频/);
  assert.deepEqual([...html.matchAll(/<option value="([^"]+)"/g)].map(m=>m[1]),f.options);
  assert.equal(catalogSubmission(w,state).catalog_values[f.id],f.value);
  const input={value:'v2v'},meaning={textContent:''};syncTaskMeaning({querySelectorAll:()=>[{querySelector:selector=>selector==='[data-catalog-field]'?input:meaning}]});assert.match(meaning.textContent,/根据文字指令修改原视频/);
 }
 const unknown=controlField(draft(),{id:'task',key:'task_type',kind:'task',type:'text',label:'任务模式',value:'custom'});
 assert.match(unknown,/type="text" value="custom"/);assert.doesNotMatch(unknown,/<select/);
});

test('hidden conditional inputs are disabled without erasing values or enabling existing disabled controls',()=>{
 const w=workflow('local-card-86'),field=effectiveCatalogInterface(w).controls.find(f=>f.kind==='steps'&&f.visibleWhen.equals===false),state=draft();
 const hiddenHtml=controlField(state,field);assert.match(hiddenHtml,/<input[^>]+required[^>]+disabled data-catalog-condition-disabled="true"/);
 const makeInput=(value,disabled=false)=>{const attrs=new Map();return {value,disabled,getAttribute:key=>attrs.get(key)??null,setAttribute:(key,value)=>attrs.set(key,value),removeAttribute:key=>attrs.delete(key)};};
 const blank=makeInput(''),locked=makeInput('7',true),wrapper={hidden:false,dataset:{catalogVisibleControl:field.visibleWhen.controlId,catalogVisibleValue:'false'},querySelectorAll:()=>[blank,locked]};
 const root={querySelectorAll:selector=>selector==='[data-catalog-visible-control]'?[wrapper]:[]};
 const before=structuredClone(state);syncControlChoices(root,w,state);
 assert.equal(wrapper.hidden,true);assert.equal(blank.disabled,true);assert.equal(locked.disabled,true);assert.equal(blank.value,'');assert.deepEqual(state,before);
 state.catalogValues[field.visibleWhen.controlId]=false;syncControlChoices(root,w,state);
 assert.equal(wrapper.hidden,false);assert.equal(blank.disabled,false);assert.equal(locked.disabled,true);assert.equal(blank.value,'');assert.equal(locked.value,'7');
 state.catalogValues[field.visibleWhen.controlId]=true;syncControlChoices(root,w,state);syncControlChoices(root,w,state);
 state.catalogValues[field.visibleWhen.controlId]=false;syncControlChoices(root,w,state);assert.equal(blank.disabled,false);assert.equal(locked.disabled,true);
});

test('inactive invalid step values use source defaults only in prepared snapshots and requests',()=>{
 for(const id of ['local-card-86','local-card-87','local-card-88']){
  const w=workflow(id),cfg=effectiveCatalogInterface(w),schemaBefore=structuredClone(w.interface),seedValues=Object.fromEntries(cfg.controls.filter(f=>f.kind==='seed').map(f=>[f.id,1]));
  for(const field of cfg.controls.filter(f=>f.kind==='steps'&&f.visibleWhen)){
   const rule=field.visibleWhen;
   for(const bad of ['', ' ',0,-1,10001,3.5,NaN,Infinity,'invalid']){
    const original={...draft(),refs:cfg.media.map(slot=>({id:slot.id,kind:slot.kind,catalogSlot:slot.id,serverAssetId:'asset-'+slot.id,src:'/asset.png'})),catalogValues:{...seedValues,[rule.controlId]:!rule.equals,[field.id]:bad}},before=structuredClone(original);
    const assets=Object.fromEntries(original.refs.map(ref=>[ref.catalogSlot,ref.serverAssetId]));
    const snapshot=prepareCatalogSnapshot(w,structuredClone(original));
    assert.equal(snapshot.catalogValues[field.id],field.value,`${id} inactive ${field.id}`);
    assert.equal(catalogSubmission(w,snapshot,assets).catalog_values[field.id],field.value);
    assert.equal(catalogSubmission(w,original,assets).catalog_values[field.id],field.value,'direct submission shares the same repair');
    assert.deepEqual(original,before,'the editable draft must retain the invalid value');
    const restored=structuredClone(original);restored.catalogValues[rule.controlId]=rule.equals;
    assert.throws(()=>prepareCatalogSnapshot(w,structuredClone(restored)),/范围|整数/,'switching back still requires a valid value');
    assert.throws(()=>catalogSubmission(w,restored,assets),/范围|整数/);
   }
   for(const valid of [1,17,10000]){
    const original={...draft(),catalogValues:{...seedValues,[rule.controlId]:!rule.equals,[field.id]:valid}};
    const snapshot=prepareCatalogSnapshot(w,structuredClone(original));
    assert.equal(snapshot.catalogValues[field.id],valid);assert.equal(catalogSubmission(w,original).catalog_values[field.id],valid);
   }
  }
  assert.deepEqual(w.interface,schemaBefore,'source defaults and constraints are unchanged');
 }
});

test('inactive custom dimensions recover invalid enums and numbers without erasing the draft',()=>{
 const w=workflow('local-card-79'),cfg=effectiveCatalogInterface(w),conditional=cfg.controls.filter(f=>f.visibleWhen);
 const original={...draft(),catalogValues:{'485:switch':false,'486:aspect_ratio':'invalid ratio','486:megapixels':''}},before=structuredClone(original);
 const snapshot=prepareCatalogSnapshot(w,structuredClone(original)),request=catalogSubmission(w,snapshot),direct=catalogSubmission(w,original);
 for(const field of conditional){assert.equal(snapshot.catalogValues[field.id],field.value);assert.equal(request.catalog_values[field.id],field.value);assert.equal(direct.catalog_values[field.id],field.value);}
 assert.deepEqual(original,before);
 const active=structuredClone(original);active.catalogValues['485:switch']=true;
 assert.throws(()=>prepareCatalogSnapshot(w,active),/请选择|范围/);
 assert.throws(()=>catalogSubmission(w,{...original,catalogValues:{...original.catalogValues,'485:switch':true}}),/范围/);
 const invalidRatio={...draft(),catalogValues:{'485:switch':true,'486:aspect_ratio':'invalid ratio','486:megapixels':1.2}};
 assert.throws(()=>catalogSubmission(w,invalidRatio),/请选择有效的画面比例/,'active invalid enums must not enter a request');
});
