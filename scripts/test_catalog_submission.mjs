import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {effectiveCatalogInterface,catalogConnectionState,catalogSubmission,catalogPromptProblem,catalogHistorySnapshot,catalogReferenceSnapshots,comparableResult,referenceResult,resultTypeLabel,validateCatalogConstraints} from '../public/catalog-submission.js';
import {catalogEditor,prepareCatalogSnapshot,apiPanel} from '../public/catalog-ui.js';
import {cloneDraft} from '../public/advanced.js';
import {boundReferences,missingMentions} from '../public/workspace-media.js';
import {renumberDraftReferences,hasRemovedReference} from '../public/reference-numbering.js';
import {outputActions} from '../public/output-actions.js';
import {resultMediaMarkup,resultExtension} from '../public/result-media.js';
import {normalizeObjectIndices} from '../public/object-indices.js';
import {controlField} from '../public/workflow-controls.js';
import {selectControl} from '../public/workflow-select.js';
import {MASK_ENCODING,canReuseReferenceUpload,referenceUploadParts,referenceUploadForm} from '../public/reference-upload.js';
import {referenceProvenance,mergeReferenceSnapshots} from '../public/live-history.js';

const schemas=JSON.parse(readFileSync(new URL('../public/workflow-interfaces.json',import.meta.url),'utf8')).workflows;
const catalog=JSON.parse(readFileSync(new URL('../public/local-catalog.json',import.meta.url),'utf8')).workflows;
// A server refresh must restore actual legacy seeds and independent branch text.
const historyApp=readFileSync(new URL('../public/app.js',import.meta.url),'utf8');
const historyMerge=historyApp.match(/function mergeCatalogJob\(j,r\)\{[\s\S]*?\n\}/)?.[0];
assert.ok(historyMerge,'test the actual production history merger');
for(const id of ['local-card-11','local-card-17','local-card-18','local-card-20']){
 const w={id,output:'image',catalogConnection:{adapter:'legacy'},interface:schemas[id]},field=w.interface.controls.find(f=>f.kind==='seed');
 const saved=catalogHistorySnapshot(w,{settings:{seed:714123},prompt:'保存的描述',negative:''});
 for(const member of field.members||[field])assert.equal(saved.catalogValues[member.id],714123,id+' restores the actual server seed');
 const context=vm.createContext({workflows:[w],catalogHistorySnapshot,effectiveCatalogInterface,catalogValuesFromSettings:(w,settings)=>catalogHistorySnapshot(w,{settings}).catalogValues,workspace:{assets:[]},mergeReferenceSnapshots:()=>[]});
 vm.runInContext(historyMerge,context);
 const job={outputs:[],snapshot:{catalogValues:{[field.id]:99},catalogTexts:{}}};
 context.mergeCatalogJob(job,{workflow_id:id,id:'receipt',settings:{seed:714123},prompt:'保存的描述',negative:'',status:'done'});
 assert.equal(job.snapshot.catalogValues[field.id],714123,'server actual value replaces the optimistic seed');
 context.mergeCatalogJob(job,{workflow_id:id,id:'partial-receipt',settings:{},status:'done'});
 assert.equal(job.snapshot.catalogValues[field.id],714123,'missing settings cannot erase a known actual value');
 assert.deepEqual(catalogHistorySnapshot(w,{settings:{}}).catalogValues,{});
}
const tripleHistoryTool={id:'local-card-12',interface:schemas['local-card-12']};
const tripleHistory=catalogHistorySnapshot(tripleHistoryTool,{settings:{seed:123,prompt_turn2real:'第二分支保留红衣',prompt_semireal:'第三分支保留姿势'},prompt:'第一分支描述'});
const stageTool={id:'local-card-107',interface:schemas['local-card-107']};
const recoveredStage=catalogHistorySnapshot(stageTool,{settings:{seed:711107},catalog_seed_values:{'80:seed':888,unknown:999}});
assert.equal(recoveredStage.catalogValues['3:seed'],711107);
assert.equal(recoveredStage.catalogValues['80:seed'],888);
assert.equal(recoveredStage.catalogValues.unknown,undefined);
assert.equal(catalogHistorySnapshot(stageTool,{catalog_values:{'80:seed':123},catalog_seed_values:{'80:seed':888}}).catalogValues['80:seed'],123,'saved form values retain priority');
for(const bad of [-1,4294967296,'888',true])assert.equal(catalogHistorySnapshot(stageTool,{settings:{},catalog_seed_values:{'80:seed':bad}}).catalogValues['80:seed'],undefined);
assert.equal(tripleHistory.catalogTexts['171:text'],'第二分支保留红衣');
assert.equal(tripleHistory.catalogTexts['180:text'],'第三分支保留姿势');
assert.equal(tripleHistory.catalogTexts['19:text'],'第一分支描述');
const cleanWorkflow={...catalog.find(w=>w.id==='local-card-92'),interface:schemas['local-card-92'],catalogConnected:true,catalogConnection:{adapter:'generic',validation:'structural-verified'}};
const cleanField=cleanWorkflow.interface.controls.find(f=>f.id==='47:index');
assert.equal(cleanField.value,2);assert.deepEqual(cleanField.options.map(o=>o.value),[0,1,2]);
assert.equal(cleanField.options[1].disabled,true);
const cleanMenu=selectControl({id:'clean-test',label:cleanField.label,value:1,options:cleanField.options});assert.match(cleanMenu,/<option value="1" selected disabled/);assert.match(cleanMenu,/网站尚不支持手工掩膜桥接/);
const oldCleanDraft={prompt:'去除标记',refs:[],catalogValues:{'47:index':1}};
assert.throws(()=>prepareCatalogSnapshot(cleanWorkflow,cloneDraft(oldCleanDraft)),/不支持手工掩膜桥接/);assert.throws(()=>catalogSubmission(cleanWorkflow,oldCleanDraft),/不支持手工掩膜桥接/);
for(const source of [0,2])assert.equal(catalogSubmission(cleanWorkflow,{...oldCleanDraft,catalogValues:{'47:index':source}}).catalog_values['47:index'],source,'automatic supported mask sources remain available');
const staleConnection={...cleanWorkflow,catalogConnection:{...cleanWorkflow.catalogConnection,controls:[{...cleanField,options:cleanField.options.map(({disabled,reason,...option})=>option)}]}};
assert.throws(()=>catalogSubmission(staleConnection,oldCleanDraft),/不支持手工掩膜桥接/,'a stale server projection cannot re-enable a confirmed unsupported UI choice');
assert(!catalogEditor({...catalog.find(w=>w.id==='local-card-133'),interface:schemas['local-card-133']},{refs:[{catalogSlot:'12',kind:'image',src:'example.png'}]}).includes('data-catalog-annotate'));
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
 referenceProvenance,mergeReferenceSnapshots,
  workflow:()=>current,effectiveCatalogInterface,catalogConnectionState,catalogPromptProblem,cloneDraft,visibleRefs:(d,workflow)=>boundReferences(d,workflow),missingMentions,renumberDraftReferences,hasRemovedReference,prepareCatalogSnapshot,catalogSubmission,canReuseReferenceUpload,referenceUploadParts,referenceUploadForm,
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
const expansionSpec=JSON.parse(readFileSync(new URL('../workflows/compiled-registry.json',import.meta.url),'utf8')).workflows['local-card-34'];
const expandTool={...catalog.find(item=>item.id==='local-card-34'),interface:schemas['local-card-34'],catalogConnected:true,catalogConnection:{adapter:'generic',validation:'structural-verified',supportedTextIds:expansionSpec.texts.map(t=>t.id)}};
assert.equal(expandTool.interface.texts.find(t=>t.id==='1488:text').preserveWhenEmpty,true);
const expansionDraft={prompt:'描述人物与场景',refs:expandTool.interface.media.map((slot,index)=>({id:'图片'+(index+1),kind:slot.kind,catalogSlot:slot.id,src:'/test-'+index,serverAssetId:'test-'+index})),catalogValues:{},catalogTexts:{'1488:text':'','1518:text':'','1520:text':'描述参考图中的物体','1514:prompt':'保留场景构图','1525:prompt':'描述合成物体'},catalogSeedModes:{}};
assert.equal(catalogPromptProblem(expandTool,{...expansionDraft,prompt:''}).id,'1479:text','restored user description must not be mistaken for a fixed helper instruction');
assert.equal(catalogPromptProblem(expandTool,expansionDraft),null,'fixed helper instructions may remain blank');
current=expandTool;session.draft=cloneDraft(expansionDraft);const beforeExpansion=submitted;
assert.equal(await context.submitCatalogLive(null,session),true);assert.equal(submitted,beforeExpansion+1);assert.equal(captured.prompt,'描述人物与场景');assert.equal(captured.catalog_texts['1479:text'],'描述人物与场景');assert.equal(captured.catalog_texts['1520:text'],'描述参考图中的物体');assert.equal(captured.catalog_texts['1488:text'],'');assert.equal(captured.catalog_texts['1518:text'],'');assert.equal(captured.catalog_texts['1514:prompt'],'保留场景构图');assert.equal(captured.catalog_texts['1525:prompt'],'描述合成物体');
for(const number of [32,33]){const tool={...catalog.find(item=>item.id==='local-card-'+number),interface:schemas['local-card-'+number],catalogConnected:true,catalogConnection:{adapter:'generic',validation:'structural-verified'}};const d={prompt:'描述这张合成图',refs:[],catalogTexts:{}};const body=catalogSubmission(tool,d);for(const text of tool.interface.texts.filter(t=>t.preserveWhenEmpty))assert.equal(body.catalog_texts[text.id],'','existing role instructions still preserve through empty payloads');}
for(const required of [false,true]){
 const requiredTool={...w,interface:{...w.interface,media:[],texts:[{id:'required:text',role:'prompt',label:'生成要求',required,...(required?{preserveWhenEmpty:true}:{})}]}};
 current=requiredTool;session.draft={...cloneDraft(draft),prompt:'',refs:[],catalogTexts:{}};const before=submitted,jobs=session.jobs.length;
 assert.equal(await context.submitCatalogLive(null,session),false);assert.equal(submitted,before);assert.equal(session.jobs.length,jobs);assert.match(messages.at(-1),/请先填写生成要求/);
}
const secondaryRequired={...w,interface:{...w.interface,media:[],texts:[{id:'fixed:text',role:'prompt',preserveWhenEmpty:true},{id:'secondary:text',role:'prompt',label:'分支描述',required:true}]}};
assert.equal(catalogPromptProblem(secondaryRequired,{prompt:'',catalogTexts:{}}).id,'secondary:text');
assert.equal(catalogPromptProblem(secondaryRequired,{prompt:'',catalogTexts:{'secondary:text':'明确的分支要求'}}),null);
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
// Real form-building paths must send original RGB + a separate mask, never the erased preview.
const rgb=new Blob(['ORIGINAL RGB'],{type:'image/png'}),mask=new Blob(['MASK'],{type:'image/png'});
const maskTool={...catalog.find(item=>item.id==='local-card-15'),interface:schemas['local-card-15'],catalogConnected:true,catalogConnection:{adapter:'legacy',validation:'structural-verified'}};
const masked={id:'图片1',catalogSlot:maskTool.interface.media[0].id,kind:'image',assetId:'damaged',originalAssetId:'original-rgb',maskAssetId:'edit-mask',annotationMode:'mask',serverAssetId:'obsolete-alpha-png',src:'blob:damaged',name:'source.png'};
context.workspace.assets=[{id:'original-rgb',blob:rgb},{id:'edit-mask',blob:mask},{id:'damaged',blob:new Blob(['BROKEN PREVIEW'],{type:'image/png'})}];
let pairedUploads=0;
context.liveApi=async(path,request)=>{if(path==='/api/assets'){pairedUploads++;assert.equal(await request.body.get('file').text(),'ORIGINAL RGB');assert.equal(await request.body.get('mask').text(),'MASK');return {id:'rgb-and-mask',src:'/safe-masked-image',original_asset_id:'server-original-rgb',original_src:'/api/assets/server-original-rgb/file',original_available:true,annotation_mode:'mask'};}assert.equal(path,'/api/jobs');captured=request;submitted++;return {};};
current=maskTool;session.draft={prompt:'局部编辑',refs:[masked],catalogValues:{},catalogTexts:{},catalogSeedModes:{}};
assert.equal(await context.submitCatalogLive(null,session),true);assert.equal(pairedUploads,1);assert.equal(captured.asset_ids[0],'rgb-and-mask');assert.equal(session.draft.refs[0].maskEncoding,MASK_ENCODING);assert.equal(session.draft.refs[0].originalServerAssetId,'server-original-rgb');assert.equal(session.jobs.at(-1).snapshot.refs[0].originalAssetId,'original-rgb');
assert.equal(await context.submitCatalogLive(null,session),true);assert.equal(pairedUploads,1,'subsequent requests may reuse only a paired-encoding cache');

const liveStart=app.indexOf('async function submitLive('),liveEnd=app.indexOf('\nlet livePollBusy=',liveStart),liveSession={id:'live-upload-test',draft:{prompt:'局部编辑',refs:[{...masked,maskEncoding:undefined,src:'blob:damaged'}],liveSettings:{}},jobs:[]};
Object.assign(context,{liveWorkflow:()=>({id:'live-upload-test',negative:false}),liveSettings:d=>d.liveSettings||{},liveProblem:()=>null,inlineError:()=>{},closePanel(){},render(){}});
vm.runInContext(app.slice(liveStart,liveEnd),context);
assert.equal(await context.submitLive(null,liveSession),true);assert.equal(pairedUploads,2);assert.equal(captured.asset_ids[0],'rgb-and-mask');assert.equal(liveSession.draft.refs[0].maskEncoding,MASK_ENCODING);assert.equal(liveSession.draft.refs[0].originalServerAssetId,'server-original-rgb');
assert.equal(await context.submitLive(null,liveSession),true);assert.equal(pairedUploads,2);

// Exercise the real action dispatch and rerun function. Retry keeps the seed;
// another version requests a new seed, which is recorded only from the response.
const retrySourceJob={id:'old-job',real:true,remoteId:'old-server-job',snapshot:{prompt:'复验描述',refs:[],catalogValues:{'1:seed':711051}}},retrySession={id:'retry-session',jobs:[]},dispatch=[];
const dispatchContext=vm.createContext({workspace:{assets:[]},handleWorkspaceAction:()=>false,findJob:()=>({j:retrySourceJob,s:retrySession}),rerunLive:(job,s,button,randomize)=>dispatch.push(randomize)});
const actionStart=app.indexOf('function handleAction('),actionEnd=app.indexOf("\ndocument.addEventListener('change'",actionStart);vm.runInContext(app.slice(actionStart,actionEnd),dispatchContext);
dispatchContext.handleAction('retry',{dataset:{job:'old-job'}});dispatchContext.handleAction('rerun',{dataset:{job:'old-job'}});assert.deepEqual(dispatch,[false,true]);
const rerunStart=app.indexOf('async function rerunLive('),rerunEnd=app.indexOf('\nasync function submitLive(',rerunStart),mergeStart=app.indexOf('function mergeCatalogJob('),mergeEnd=app.indexOf('\nfunction mergeLiveJob(',mergeStart),rerunMessages=[],requests=[];let respond;
const rerunTool={id:'retry-tool',output:'image',catalogConnection:{adapter:'generic'},interface:{controls:[{id:'1:seed',kind:'seed',value:711051}],texts:[{id:'4:text',role:'prompt'}],media:[]}};
const retryContext=vm.createContext({workflows:[rerunTool],referenceProvenance,mergeReferenceSnapshots,effectiveCatalogInterface,catalogHistorySnapshot,catalogReferenceSnapshots,crypto:globalThis.crypto,cloneDraft,Date,refreshFeed(){},scheduleSave(){},sidebar(){},liveJson:body=>body,toast:message=>rerunMessages.push(message),liveApi:(path,body)=>{requests.push({path,body});return new Promise(resolve=>{respond=resolve;});}});
vm.runInContext(app.slice(mergeStart,mergeEnd)+'\n'+app.slice(rerunStart,rerunEnd),retryContext);retryContext.mergeLiveJob=retryContext.mergeCatalogJob;
for(const randomize of [false,true]){const source={...retrySourceJob,snapshot:cloneDraft(retrySourceJob.snapshot)},session={jobs:[]},button={disabled:false},priorSnapshot=cloneDraft(source.snapshot),running=retryContext.rerunLive(source,session,button,randomize),job=session.jobs[0];assert.equal(requests.at(-1).body.randomize_seed,randomize);assert.equal(job.stage,'正在提交到算力卡');assert.equal(job.snapshot.catalogValues['1:seed'],711051,'the pending row must not invent a new seed');assert.equal(button.disabled,true);
 const recordedSeed=randomize?424242:711051;respond({id:'server-new-'+randomize,workflow_id:'retry-tool',status:'running',stage:'正在生成',prompt:'复验描述',started:job.started,catalog_values:{'1:seed':recordedSeed},catalog_texts:{'4:text':'复验描述'},outputs:[]});await running;assert.equal(job.snapshot.catalogValues['1:seed'],recordedSeed,'the server response is the seed authority');assert.deepEqual(source.snapshot,priorSnapshot);assert.equal(button.disabled,false);assert.match(rerunMessages.at(-1),randomize?/更换随机种子/:/原随机种子重试/);
}
console.log(JSON.stringify({schemaCoverage:catalog.length,duplicateKeys:'passed',multipleTexts:'passed',optionalMedia:'passed',tenReferences:'passed',supportedIds:'passed',blockedState:'passed',historySlotRecovery:'passed',typedResults:'passed',legacySubmission:'passed',fixedProviderApi:'passed',explicitSizeConstraints:'passed',independentObjectIndices:'passed',catalogAndLiveRgbMaskUploads:'passed',retryAndRerunSeedPolicies:'passed',pendingCaptionAndResponseSeed:'passed'}));
