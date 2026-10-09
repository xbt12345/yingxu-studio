import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import {controlField,controlValue,syncControlChoices} from '../public/workflow-controls.js';
import {catalogCommonPanel,catalogEditor,prepareCatalogSnapshot} from '../public/catalog-ui.js';
import {catalogSubmission,catalogHistorySnapshot,effectiveCatalogInterface} from '../public/catalog-submission.js';
import {cloneDraft} from '../public/advanced.js';

const readJson=path=>JSON.parse(readFileSync(new URL(path,import.meta.url),'utf8'));
const schemas=readJson('../public/workflow-interfaces.json').workflows;
const catalog=readJson('../public/local-catalog.json').workflows;
const registry=readJson('../workflows/compiled-registry.json').workflows;
const workflow=id=>{
 const spec=registry[id];
 return {...catalog.find(w=>w.id===id),interface:schemas[id],catalogConnected:true,
  catalogConnection:{...spec,supportedControlIds:spec.controls.map(f=>f.id),textIds:spec.texts.map(f=>f.id),mediaIds:spec.media.map(f=>f.id)}};
};
const freshDraft=()=>({prompt:'保持原图构图，改为清晰漫画风格',refs:[],catalogValues:{},catalogTexts:{},catalogSeedModes:{}});
const branches=[['local-card-86','705:value',30],['local-card-87','711:value',40],['local-card-88','693:value',40]];

// DOM boundary fixture built from the actual shared renderer's HTML. It only
// implements attribute selection/mutation, never visibility or value logic.
// Production syncControlChoices decides visibility and selected preset state.
function renderedPanel(html){
 const nodes=[];
 for(const match of html.matchAll(/<(?:div|input|button)\b([^>]*)>/g)){
  const attributes=new Map([...match[1].matchAll(/([\w:-]+)(?:="([^"]*)")?/g)].map(m=>[m[1],m[2]??'']));
  const classes=new Set((attributes.get('class')||'').split(/\s+/).filter(Boolean));
  const node={
   attributes,dataset:Object.fromEntries([...attributes].filter(([key])=>key.startsWith('data-')).map(([key,value])=>[key.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase()),value])),
   value:attributes.get('value')||'',hidden:attributes.has('hidden'),type:attributes.get('type'),
   disabled:attributes.has('disabled'),checked:attributes.has('checked'),
   getAttribute(key){return attributes.get(key)??null;},
   setAttribute(key,value){attributes.set(key,String(value));},
   classList:{toggle(key,on){if(on)classes.add(key);else classes.delete(key);},contains(key){return classes.has(key);}},
   replaceChildren(){assert.fail('Sync must preserve the existing input tree');},
   set innerHTML(_){assert.fail('Sync must preserve input DOM identity');},
   set outerHTML(_){assert.fail('Sync must preserve input DOM identity');},
  };
  nodes.push(node);
 }
 const matches=(node,selector)=>{
  const match=selector.match(/^\[([^\]=]+)(?:="([^"]*)")?\]$/);
  return match&&node.attributes.has(match[1])&&(match[2]===undefined||node.attributes.get(match[1])===match[2]);
 };
 return {nodes,
  querySelectorAll(selector){return nodes.filter(node=>selector.split(',').some(part=>matches(node,part.trim())));},
  querySelector(selector){return this.querySelectorAll(selector)[0]||null;},
  replaceChildren(){assert.fail('Sync must preserve the existing editor');},
  set innerHTML(_){assert.fail('Sync must not redraw the editor');},
  set outerHTML(_){assert.fail('Sync must not replace the editor');},
 };
}
const branchWrappers=panel=>panel.querySelectorAll('[data-catalog-visible-control]');
const numericInput=(panel,id)=>panel.querySelector(`[data-catalog-field="${id}"]`);
const visibleBranch=panel=>branchWrappers(panel).filter(node=>!node.hidden).map(node=>node.dataset.catalogVisibleValue);

test('real connected Anima schemas render one current branch and source-defined custom ranges',()=>{
 for(const [id,toggle,standard]of branches){
  const w=workflow(id),draft=freshDraft(),before=structuredClone(draft),fields=effectiveCatalogInterface(w).controls;
  const panel=renderedPanel(catalogCommonPanel(w,draft));
  const stepFields=fields.filter(field=>field.kind==='steps');
  assert.equal(stepFields.length,2,id);
  assert.deepEqual(stepFields.map(field=>field.id),['sub0/107:value','sub0/108:value']);
  assert.deepEqual(stepFields.map(field=>field.value),[standard,8]);
  assert.deepEqual(visibleBranch(panel),['true'],`${id}: initial authored Turbo choice`);
  assert.equal(panel.querySelector(`[data-catalog-field="${toggle}"]`).checked,true);
  assert.equal(numericInput(panel,'sub0/108:value').value,'8');
  assert.equal(numericInput(panel,'sub0/107:value').value,String(standard));
  for(const field of stepFields){
   const input=numericInput(panel,field.id);
   assert.equal(input.type,'number');
   assert.deepEqual(['min','max','step'].map(key=>input.getAttribute(key)),['1','10000','1']);
   assert.equal(field.options,undefined,'Presets are shortcuts, not an enum restriction');
   assert.deepEqual(field.visibleWhen,{controlId:toggle,equals:field.key==='turbo_steps',defaultValue:true});
   const buttonValues=panel.querySelectorAll(`[data-catalog-preset="${field.id}"]`).map(button=>Number(button.dataset.value));
   assert.deepEqual(buttonValues,field.presets,'Actual shared markup must expose the reviewed shortcuts');
  }
  assert.deepEqual(draft,before,'Rendering must preserve the authored draft');
 }
});

test('switching Turbo updates visibility in place and preserves each edited step value',()=>{
 for(const [id,toggle,standard]of branches){
  const w=workflow(id),draft=freshDraft(),panel=renderedPanel(catalogCommonPanel(w,draft));
  const nodes=[...panel.nodes],turbo=numericInput(panel,'sub0/108:value'),normal=numericInput(panel,'sub0/107:value');
  const wrappers=branchWrappers(panel),wrapperAttributes=wrappers.map(node=>[node.dataset.catalogVisibleControl,node.dataset.catalogVisibleValue]);
  turbo.value='12';draft.catalogValues['sub0/108:value']=12;
  draft.catalogValues[toggle]=false;
  const before=structuredClone(draft);syncControlChoices(panel,w,draft);
  assert.deepEqual(draft,before,'Sync reads draft state without changing stored branch values');
  assert.deepEqual(visibleBranch(panel),['false']);
  assert.equal(normal.value,String(standard));
  normal.value='17';draft.catalogValues['sub0/107:value']=17;
  draft.catalogValues[toggle]=true;
  syncControlChoices(panel,w,draft);
  assert.deepEqual(visibleBranch(panel),['true']);
  assert.equal(turbo.value,'12');assert.equal(normal.value,'17');
  const selectedTurbo=panel.querySelectorAll('[data-catalog-preset="sub0/108:value"]').filter(button=>button.getAttribute('aria-pressed')==='true');
  assert.deepEqual(selectedTurbo.map(button=>Number(button.dataset.value)),[12]);
  draft.catalogValues[toggle]=false;syncControlChoices(panel,w,draft);
  assert.deepEqual(visibleBranch(panel),['false']);
  assert.equal(controlValue(draft,w.interface.controls.find(field=>field.key==='standard_steps')),17);
  assert.equal(controlValue(draft,w.interface.controls.find(field=>field.key==='turbo_steps')),12);
  assert.equal(numericInput(panel,'sub0/108:value'),turbo);
  assert.equal(numericInput(panel,'sub0/107:value'),normal);
  assert.deepEqual(panel.nodes,nodes,'Input and wrapper identities must survive every switch');
  assert.deepEqual(wrappers.map(node=>[node.dataset.catalogVisibleControl,node.dataset.catalogVisibleValue]),wrapperAttributes);
 }
});

test('custom step counts beyond shortcuts stay valid and source ranges reject invalid integers',()=>{
 for(const [id,toggle]of branches){
  const w=workflow(id),draft=freshDraft();
  draft.catalogValues={...draft.catalogValues,[toggle]:false,'sub0/107:value':17,'sub0/108:value':9};
  const snapshot=prepareCatalogSnapshot(w,cloneDraft(draft));
  assert.equal(snapshot.catalogValues['sub0/107:value'],17);
  assert.equal(snapshot.catalogValues['sub0/108:value'],9);
  const render=renderedPanel(controlField(snapshot,w.interface.controls.find(field=>field.key==='standard_steps')));
  assert.equal(numericInput(render,'sub0/107:value').value,'17');
  for(const count of [1,10000]){
   const changed=cloneDraft(draft);changed.catalogValues['sub0/107:value']=count;
   assert.equal(prepareCatalogSnapshot(w,changed).catalogValues['sub0/107:value'],count);
  }
  for(const count of [0,10001,3.5,Number.NaN]){
   const changed=cloneDraft(draft);changed.catalogValues['sub0/107:value']=count;
   assert.throws(()=>prepareCatalogSnapshot(w,changed),/范围|整数/,`${id}: reject ${count}`);
  }
 }
});

test('snapshots, submissions and recovered history retain both visible and hidden branch values',()=>{
 for(const [id,toggle]of branches){
  const w=workflow(id),draft=freshDraft();
  draft.catalogValues={[toggle]:true,'sub0/107:value':23,'sub0/108:value':9};
  const original=structuredClone(draft),snapshot=prepareCatalogSnapshot(w,cloneDraft(draft));
  const before=structuredClone(snapshot),payload=catalogSubmission(w,snapshot);
  assert.equal(payload.catalog_values['sub0/107:value'],23,'Hidden standard branch remains source-addressable');
  assert.equal(payload.catalog_values['sub0/108:value'],9);
  assert.equal(payload.catalog_values[toggle],true);
  assert.deepEqual(draft,original);assert.deepEqual(snapshot,before);
  const history=catalogHistorySnapshot(w,{catalog_values:payload.catalog_values,catalog_texts:payload.catalog_texts});
  const restored={...freshDraft(),...history};
  restored.catalogValues[toggle]=false;
  const rerun=prepareCatalogSnapshot(w,cloneDraft(restored)),request=catalogSubmission(w,rerun);
  assert.equal(request.catalog_values['sub0/107:value'],23);
  assert.equal(request.catalog_values['sub0/108:value'],9);
  assert.equal(request.catalog_values[toggle],false);
 }
});

test('portrait collections expose one user description while quantity only controls number of results',()=>{
 for(const id of ['local-card-80','local-card-81']){
  const w=workflow(id),cfg=effectiveCatalogInterface(w),count=cfg.controls.find(field=>field.kind==='count');
  assert.equal(cfg.texts.length,1,id+' must not surface the internal prompt templates');
  assert.equal(cfg.texts[0].role,'prompt');
  assert.deepEqual([count.min,count.max,count.step],[1,1000,1]);
  for(const quantity of [1,3,8,1000]){
   const draft=freshDraft();draft.prompt='同一人物，海边写真，每张采用不同构图';draft.catalogValues[count.id]=quantity;
   const before=structuredClone(draft),html=catalogEditor(w,draft,{localMode:true});
   assert.deepEqual([...html.matchAll(/data-catalog-text="([^"]+)"/g)].map(match=>match[1]),[cfg.texts[0].id]);
   assert.deepEqual(draft,before,'Changing count must not write prompt state during render');
   const snapshot=prepareCatalogSnapshot(w,cloneDraft(draft)),payload=catalogSubmission(w,snapshot);
   assert.equal(payload.catalog_values[count.id],quantity);
   assert.deepEqual(payload.catalog_texts,{[cfg.texts[0].id]:draft.prompt});
  }
  for(const quantity of [0,1001,2.5]){
   const draft=freshDraft();draft.catalogValues[count.id]=quantity;
   assert.throws(()=>prepareCatalogSnapshot(w,draft),/范围|整数/);
  }
 }
});
