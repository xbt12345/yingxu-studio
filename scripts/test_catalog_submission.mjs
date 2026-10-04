import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {effectiveCatalogInterface,catalogConnectionState,catalogSubmission,catalogHistorySnapshot,catalogReferenceSnapshots,comparableResult,referenceResult,resultTypeLabel,validateCatalogConstraints} from '../public/catalog-submission.js';
import {catalogEditor,prepareCatalogSnapshot,apiPanel} from '../public/catalog-ui.js';
import {cloneDraft} from '../public/advanced.js';
import {boundReferences,missingMentions} from '../public/workspace-media.js';
import {renumberDraftReferences,hasRemovedReference} from '../public/reference-numbering.js';
import {outputActions} from '../public/output-actions.js';
import {resultMediaMarkup,resultExtension} from '../public/result-media.js';
import {normalizeObjectIndices} from '../public/object-indices.js';
import {controlField} from '../public/workflow-controls.js';

const schemas=JSON.parse(readFileSync(new URL('../public/workflow-interfaces.json',import.meta.url),'utf8')).workflows;
const catalog=JSON.parse(readFileSync(new URL('../public/local-catalog.json',import.meta.url),'utf8')).workflows;
for(const item of catalog){
 const w={...item,interface:schemas[item.id],catalogConnected:true,catalogConnection:{adapter:'generic',validation:'structural-verified'}};
 const catalogValues=Object.fromEntries(w.interface.controls.filter(f=>f.kind==='points').map(f=>[f.id,'{"positive":[{"x":0.5,"y":0.5}],"negative":[]}']));
 const draft=prepareCatalogSnapshot(w,{prompt:'契约验证',refs:[],catalogValues,catalogTexts:{},catalogSeedModes:{}}),payload=catalogSubmission(w,draft);
 assert.deepEqual(Object.keys(payload.catalog_values).sort(),w.interface.controls.map(f=>f.id).sort(),w.id+' loses a control identity');
 assert.deepEqual(Object.keys(payload.catalog_texts).sort(),w.interface.texts.map(t=>t.id).sort(),w.id+' loses a text branch');
 for(const f of w.interface.controls)assert.notEqual(payload.catalog_values[f.id],undefined,w.id+' missing value '+f.id);
}

const field=(id,value)=>({id,nodeId:id.split(':')[0],key:'seed',type:'number',kind:'seed',label:id,value,min:0,max:100,step:1});
const controls=[field('1:seed',2),field('2:seed',3)],texts=[{id:'3:text',role:'prompt',label:'创作描述'},{id:'4:text',role:'prompt',label:'分支描述'},{id:'5:text',role:'negative',label:'负面提示词'}];
const media=Array.from({length:11},(_,i)=>({id:'input-'+i,kind:'image',label:'参考图 '+i,required:i<10}));
const w={id:'catalog-contract',name:'契约验证',category:'图像编辑',output:'image',fields:[],catalogOnly:true,catalogConnected:true,catalogConnection:{adapter:'generic',validation:'structural-verified'},interface:{sourceHash:'abc',schemaVersion:2,controls,texts,media,apiProfiles:[]}};
const draft={prompt:'主描述',refs:media.slice(0,10).map((m,i)=>({id:'图片'+(i+1),kind:'image',catalogSlot:m.id,serverAssetId:'asset-'+i,src:'/asset-'+i})),catalogValues:{'1:seed':11,'2:seed':22},catalogTexts:{'4:text':'独立分支','5:text':'独立反向'},catalogSeedModes:{'1:seed':'fixed','2:seed':'fixed'}};
const assets=Object.fromEntries(draft.refs.map(r=>[r.catalogSlot,r.serverAssetId]));
const payload=catalogSubmission(w,draft,assets);
assert.equal(payload.catalog_values['1:seed'],11);assert.equal(payload.catalog_values['2:seed'],22);
assert.equal(payload.catalog_texts['4:text'],'独立分支');assert.equal(payload.catalog_texts['5:text'],'独立反向');
assert.equal(Object.keys(payload.catalog_assets).length,10);assert(!Object.hasOwn(payload.catalog_assets,'input-10'));
const projected={...w,catalogConnection:{...w.catalogConnection,supportedControlIds:['2:seed'],textIds:['4:text','5:text'],mediaIds:['input-4','input-10']}};
const selected=catalogSubmission(projected,{...draft,prompt:'新主描述'},assets);
assert.deepEqual(selected.catalog_values,{'2:seed':22});assert.deepEqual(selected.catalog_assets,{'input-4':'asset-4'});
assert.equal(selected.catalog_texts['4:text'],'新主描述');assert(!Object.hasOwn(selected.catalog_texts,'3:text'));
const html=catalogEditor(projected,draft);
assert(!html.includes('data-catalog-field="1:seed"'));assert(html.includes('data-catalog-field="2:seed"'));
assert(!html.includes('data-catalog-slot="input-0"'));assert(html.includes('catalog-optional'));
assert(!html.includes('真实生成'),'structural checks do not prove real generation');
const blocked={...projected,catalogConnection:{...projected.catalogConnection,validation:'blocked',blocking_reason:'缺少已确认的输出节点'}};
assert.equal(effectiveCatalogInterface(blocked).controls.length,2,'blocked editor retains the reviewable schema');
assert.equal(catalogConnectionState(blocked).blocked,true);assert.match(catalogEditor(blocked,draft),/缺少已确认的输出节点/);
assert.match(catalogEditor(blocked,draft),/data-action="generate" disabled/);
const unavailable={...w,catalogConnection:{...w.catalogConnection,available:false,blocking_reason:'执行模板缺失'}};
assert.equal(catalogConnectionState(unavailable).blocked,true);
const metadata={...w,catalogConnection:{...w.catalogConnection,controls:[{...controls[1],max:20}],media:[{id:'input-0',optional:true}]}};
assert.equal(effectiveCatalogInterface(metadata).controls[1].max,20,'native runtime constraints override a stale presentation');
assert.equal(effectiveCatalogInterface(metadata).media[0].required,false);
const externalApi={...w,catalogConnection:{...w.catalogConnection,external_api_account:true}};
assert.equal(catalogConnectionState(externalApi).button,'生成 · 算力 / API 计费');assert.match(catalogConnectionState(externalApi).detail,/外部 API 可能另收费/);assert.match(catalogEditor(externalApi,draft),/生成 · 算力 \/ API 计费/);
assert.equal(catalogConnectionState({...externalApi,catalogPendingApi:true}).button,'生成 · 算力 / API 计费');
assert.equal(catalogConnectionState(w).button,'生成 · 算力卡计费');
assert.equal(catalogConnectionState({...externalApi,catalogConnection:{...externalApi.catalogConnection,adapter:'legacy'}}).button,'生成 · 算力卡计费','fees use confirmed generic metadata, never inferred node names');
const instruction={...w,interface:{...w.interface,texts:[{id:'3:text',role:'prompt',label:'创作描述'},{id:'4:text',role:'prompt',label:'扩写指令',preserveWhenEmpty:true}]}};
assert.match(catalogEditor(instruction,draft),/placeholder="留空沿用工作流指令"/);
const emptyPrompt=prepareCatalogSnapshot(instruction,{...cloneDraft(draft),prompt:'',catalogTexts:{'3:text':'旧描述','4:text':''}});
assert.equal(emptyPrompt.catalogTexts['3:text'],'','clearing the main description must not recover stale text');assert.equal(catalogSubmission(instruction,emptyPrompt).catalog_texts['4:text'],'','empty optional instruction delegates to the server template');

const profile={id:'7',label:'图片生成 API',keyOnly:true,model:'model-a',modelOptions:['model-a','model-b'],bindings:{model:{node:'7',input:'model'},apiKey:{node:'7',input:'apikey'}}};
const apiWorkflow={...w,interface:{...w.interface,media:[],apiProfiles:[profile]}};
const customDraft={...cloneDraft(draft),catalogApis:{'7':{mode:'custom',model:'model-b'}}};
const prepared=prepareCatalogSnapshot(apiWorkflow,customDraft);
assert.equal(prepared.catalogApis['7'].model,'model-b');assert(!Object.hasOwn(prepared.catalogApis['7'],'baseUrl'));
const apiMarkup=apiPanel(apiWorkflow,customDraft);
assert(!apiMarkup.includes('data-api-field="baseUrl"'));assert.match(apiMarkup,/data-api-field="model"/);assert.match(apiMarkup,/<select/);
assert.throws(()=>prepareCatalogSnapshot(apiWorkflow,{...cloneDraft(draft),catalogApis:{'7':{mode:'custom',model:'unknown'}}}),/支持的模型/);

const history=catalogHistorySnapshot(w,{catalog_values:{'1:seed':11,'2:seed':22},catalog_texts:payload.catalog_texts,catalog_assets:{'input-4':'asset-4'}});
assert.deepEqual(history.catalogValues,{'1:seed':11,'2:seed':22});assert.deepEqual(history.catalogTexts,payload.catalog_texts);
const recovered=catalogReferenceSnapshots(w,{catalog_assets:{'input-4':'asset-4'},references:[{id:'asset-4',kind:'image',name:'参考',src:'/asset-4'}]});
assert.equal(recovered[0].catalogSlot,'input-4','optional empty slots must not shift restored references');

for(const type of ['text','audio']){
 const output={id:type,type,text:'<script>不是 HTML</script>',src:type==='text'?'/file.txt':'/file.wav'};
 const actions=outputActions(output).map(a=>a.action);
 assert(!actions.includes('select-result'));assert(!actions.includes('to-video'));assert(!actions.includes('publish-output'));
 assert.equal(actions.includes('save-output'),type==='audio');assert.equal(actions.includes('reference'),type==='audio');
 assert.equal(actions.includes('copy-output'),type==='text');assert(actions.includes('download'));
 const markup=resultMediaMarkup(output);assert(!markup.includes('<img'));assert(!markup.includes('<script>'));
 assert.equal(comparableResult(output),false);assert.equal(referenceResult(output),type==='audio');
 assert.equal(resultExtension(output),type==='text'?'txt':'wav');
}

// Exercise the actual app submission path with uploads already present; no network or GPU.
const app=readFileSync(new URL('../public/app.js',import.meta.url),'utf8'),start=app.indexOf('async function submitCatalogLive('),end=app.indexOf('\nfunction submit(',start);
 let current=w,captured,submitted=0;const messages=[];
const session={draft:cloneDraft(draft),jobs:[],id:'session'};
const context=vm.createContext({
 workflow:()=>current,effectiveCatalogInterface,catalogConnectionState,cloneDraft,visibleRefs:(d,workflow)=>boundReferences(d,workflow),missingMentions,renumberDraftReferences,hasRemovedReference,prepareCatalogSnapshot,catalogSubmission,
 toast(message){messages.push(message);},$:()=>null,getCatalogApiKey:()=>'mock-key-in-memory',crypto:globalThis.crypto,Date,state:{},refreshFeed(){},sidebar(){},scheduleSave(){},refreshComposer(){},workspace:{assets:[]},resultExtension,
 liveJson:body=>body,liveApi:async(path,body)=>{assert.equal(path,'/api/jobs');captured=body;submitted++;return {};},mergeLiveJob(){},
});
vm.runInContext(app.slice(start,end),context);
assert.equal(await context.submitCatalogLive(null,session),true);
assert.equal(captured.catalog_values['1:seed'],11);assert.equal(captured.catalog_values['2:seed'],22);
assert.equal(Object.keys(captured.catalog_assets).length,10);assert.equal(captured.asset_ids.length,0,'generic submission must not carry positional legacy assets');
assert.equal(captured.catalog_texts['4:text'],'独立分支');
current=blocked;assert.equal(await context.submitCatalogLive(null,session),false);assert.equal(submitted,1,'blocked workflow cannot silently start a demo');
current={...w,catalogConnection:{adapter:'legacy',validation:'live-verified'},interface:{...w.interface,media:[],controls:[{...controls[0],key:'seed'}]}};
session.draft.refs=[];
assert.equal(await context.submitCatalogLive(null,session),true);assert.equal(captured.settings.seed,11);assert.equal(captured.catalog_values,undefined,'legacy adapters retain their original payload');
current=apiWorkflow;session.draft={...cloneDraft(draft),refs:[],catalogApis:{'7':{mode:'custom',model:'model-b'}}};
assert.equal(await context.submitCatalogLive(null,session),true);assert.equal(captured.api_profiles['7'].model,'model-b');assert.equal(captured.api_profiles['7'].base_url,undefined);assert.equal(captured.api_profiles['7'].api_key,'mock-key-in-memory');
assert(!JSON.stringify(session.draft).includes('mock-key-in-memory'),'API secrets must not enter the draft');
const sizeTool={...catalog.find(item=>item.id==='local-card-125'),interface:schemas['local-card-125'],catalogConnected:true,catalogConnection:{adapter:'generic',validation:'structural-verified',constraints:[{type:'nonzero-size',width:'225:value',height:'226:value'}]}};
assert.equal(sizeTool.interface.controls.find(f=>f.id==='225:value').min,0);assert.equal(sizeTool.interface.controls.find(f=>f.id==='226:value').min,0);
const sizeDraft={prompt:'尺寸契约验证',refs:sizeTool.interface.media.map((slot,index)=>({id:'参考'+index,catalogSlot:slot.id,kind:slot.kind,src:'/test-'+index,serverAssetId:'test-'+index})),catalogValues:{'225:value':0,'226:value':0},catalogTexts:{},catalogSeedModes:{}};
assert.throws(()=>validateCatalogConstraints(sizeTool,sizeDraft),/宽度和高度不能同时为 0/);assert.throws(()=>catalogSubmission(sizeTool,sizeDraft),/自动保持比例/);assert.throws(()=>prepareCatalogSnapshot(sizeTool,cloneDraft(sizeDraft)),/宽度和高度不能同时为 0/);
current=sizeTool;session.draft=cloneDraft(sizeDraft);const beforeInvalidSize=submitted,beforeInvalidJobs=session.jobs.length;
assert.equal(await context.submitCatalogLive(null,session),false);assert.equal(submitted,beforeInvalidSize,'invalid size must not send a job');assert.equal(session.jobs.length,beforeInvalidJobs,'invalid size is caught before uploads and creation of a running job');assert.match(messages.at(-1),/请至少填写一边的像素值/);
for(const [width,height] of [[0,720],[1280,0]]){session.draft=cloneDraft(sizeDraft);session.draft.catalogValues={'225:value':width,'226:value':height};assert.equal(await context.submitCatalogLive(null,session),true);assert.equal(captured.catalog_values['225:value'],width);assert.equal(captured.catalog_values['226:value'],height);}
validateCatalogConstraints({...sizeTool,catalogConnection:{adapter:'legacy',constraints:sizeTool.catalogConnection.constraints}},sizeDraft);
assert.equal(normalizeObjectIndices(''),'');assert.equal(normalizeObjectIndices('   '),'');assert.equal(normalizeObjectIndices(' 0, 2 ,3 '),'0,2,3');assert.equal(normalizeObjectIndices('1000000000000000000000000000'),'1000000000000000000000000000','the interface must not guess the detector object count');
for(const bad of ['all','-1','0,-2','1.5','1e3','0,,2','0,','0，2','0 2'])assert.throws(()=>normalizeObjectIndices(bad),/非负整数/);
for(const [toolId,ids] of [['local-card-22',['197:object_indices','579:object_indices']],['local-card-23',['527:object_indices']]]){
 const indexTool={...catalog.find(item=>item.id===toolId),interface:schemas[toolId],catalogConnected:true,catalogConnection:{adapter:'generic',validation:'structural-verified'}};
 const indexFields=indexTool.interface.controls.filter(f=>f.kind==='indices');assert.deepEqual(indexFields.map(f=>f.id).sort(),ids.sort());
 for(const field of indexFields){assert.equal(field.type,'string');assert.equal(field.value,'');const html=controlField({refs:[],catalogValues:{}},field);assert.match(html,/type="text"/);assert.match(html,/placeholder="全部对象；或填写 0,2"/);assert.match(html,/检测/);assert(!html.includes(' max=')&&!html.includes('required')&&!html.includes('<img'),'object bounds and previews need detector evidence');}
 const indexDraft={prompt:'对象契约验证',refs:indexTool.interface.media.map((slot,index)=>({id:'参考'+index,catalogSlot:slot.id,kind:slot.kind,src:'/test-'+index,serverAssetId:'test-'+index})),catalogValues:{},catalogTexts:{},catalogSeedModes:{}};
 let indexSnapshot=prepareCatalogSnapshot(indexTool,cloneDraft(indexDraft));let indexPayload=catalogSubmission(indexTool,indexSnapshot);for(const id of ids)assert.equal(indexPayload.catalog_values[id],'','empty delegates all objects to the node');
 indexDraft.catalogValues=Object.fromEntries(ids.map((id,index)=>[id,index?'1':'0, 2']));indexSnapshot=prepareCatalogSnapshot(indexTool,cloneDraft(indexDraft));indexPayload=catalogSubmission(indexTool,indexSnapshot);for(const [index,id] of ids.entries())assert.equal(indexPayload.catalog_values[id],index?'1':'0,2','equal keys retain independent node identities');
 const restored=catalogHistorySnapshot(indexTool,{catalog_values:indexPayload.catalog_values});for(const id of ids)assert.equal(restored.catalogValues[id],indexPayload.catalog_values[id]);
 current=indexTool;session.draft=cloneDraft(indexDraft);assert.equal(await context.submitCatalogLive(null,session),true);for(const id of ids)assert.equal(captured.catalog_values[id],indexPayload.catalog_values[id]);
 for(const id of ids){const invalid=cloneDraft(indexDraft);invalid.catalogValues[id]='-1';assert.throws(()=>prepareCatalogSnapshot(indexTool,invalid),/非负整数/);assert.throws(()=>catalogSubmission(indexTool,invalid),/非负整数/);session.draft=invalid;const before=submitted;assert.equal(await context.submitCatalogLive(null,session),false);assert.equal(submitted,before,'invalid indices cannot start a remote job');}
}
console.log(JSON.stringify({schemaCoverage:catalog.length,duplicateKeys:'passed',multipleTexts:'passed',optionalMedia:'passed',tenReferences:'passed',supportedIds:'passed',blockedState:'passed',historySlotRecovery:'passed',typedResults:'passed',legacySubmission:'passed',fixedProviderApi:'passed',explicitSizeConstraints:'passed',independentObjectIndices:'passed'}));
