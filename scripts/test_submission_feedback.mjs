import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {effectiveCatalogInterface,catalogHistorySnapshot,catalogReferenceSnapshots} from '../public/catalog-submission.js';
import {esc} from '../public/data.js';

const app=readFileSync(new URL('../public/app.js',import.meta.url),'utf8');
const schemas=JSON.parse(readFileSync(new URL('../public/workflow-interfaces.json',import.meta.url),'utf8')).workflows;
function source(from,to){const start=app.indexOf(from),end=app.indexOf(to,start);assert(start>=0&&end>start,`production source boundaries: ${from}`);return app.slice(start,end);}
const submissionSource=source('function flushCatalogCustomSize(','\nfunction complete(');
const saveSource=source('function saveRef(','\nasync function initializeWorkspace(');
const actionSource=source('function handleAction(',"\ndocument.addEventListener('change',e=>{const id=e.target.dataset.historySelect");
const keyboardSource=app.split('\n').find(line=>line.startsWith("document.addEventListener('keydown',e=>{if(e.key==='Escape')"));
assert(keyboardSource,'use the production Ctrl / Cmd + Enter listener');

function form({invalid=null,custom=[],floating=[],hiddenFloating=[]}={}){
 const session={id:'active',draft:{catalogValues:{},refs:[]},jobs:[]},w={id:'local-card-19',catalogConnected:true,interface:schemas['local-card-19']},calls=[],listeners={},hidden={dataset:{catalogField:'site:size'},value:'1024x1024'},unrelated={dataset:{catalogField:'unrelated'},value:'keep this number'},panelHidden={dataset:{catalogField:'site:size'},value:'1024x1024'};
 const root=(fields,inputs)=>({querySelectorAll:selector=>selector==='[data-catalog-field]'?fields:selector==='[data-catalog-custom-size]'?inputs:[]}),inlineRoot=root([unrelated,hidden],custom),panelRoot=root([{dataset:{catalogField:'different'},value:'keep panel value'},panelHidden],floating);
 const context=vm.createContext({active:()=>session,workflow:()=>w,document:{querySelectorAll:selector=>[...(selector.includes('#composer-slot')?custom:[]),...(selector.includes('#floating-panel')?floating:[]),...(selector.includes('#floating-panel')&&!selector.includes('#floating-panel:not([hidden])')?hiddenFloating:[])],querySelector:selector=>{assert.match(selector,/\.wf-editor input:invalid/);return invalid;},addEventListener:(name,listener)=>{listeners[name]=listener;}},submitCatalogLive:(snapshot,s)=>{calls.push({snapshot:structuredClone(snapshot||s.draft),session:s});return true;},syncControlChoices(){},scheduleSave(){},refreshComposer(){assert.fail('submission validation must not redraw the editor');},$(selector){return selector==='#composer-slot'?inlineRoot:{};},dialog:{open:false},workspace:{assets:[]},handleWorkspaceAction:()=>false});
 vm.runInContext(submissionSource+'\n'+actionSource+'\n'+keyboardSource,context);
 for(const [inputs,container,location] of [[custom,inlineRoot,'.workflow-inline-controls'],[floating,panelRoot,'#floating-panel'],[hiddenFloating,panelRoot,'#floating-panel']])for(const input of inputs){input.closest=selector=>selector===location?container:null;input.dataset={catalogCustomSize:'site:size'};input.setCustomValidity=message=>{input.validationMessage=message;};input.reportValidity=()=>{input.reported=(input.reported||0)+1;};}
 return {context,session,w,calls,listeners,hidden,unrelated,panelHidden};
}

test('existing native number validity blocks Generate and Ctrl / Cmd + Enter through the same dispatch',()=>{
 for(const state of ['empty required value','below minimum','above maximum','invalid step']){
  let reports=0;const f=form({invalid:{reportValidity(){reports++;}}});
  assert.equal(f.context.submit(),false,state);f.context.handleAction('generate',{});
  for(const key of ['ctrlKey','metaKey']){let prevented=false;f.listeners.keydown({key:'Enter',[key]:true,repeat:false,preventDefault(){prevented=true;}});assert.equal(prevented,true);}
  assert.equal(f.calls.length,0,state+' cannot submit the old valid draft value');assert.equal(reports,4);
 }
 const valid=form();assert.equal(valid.context.submit(),true);assert.equal(valid.calls.length,1,'valid current input keeps its original dispatch');
});

test('saved retries and a different session do not validate or flush the current form',()=>{
 const input={value:'broken'},f=form({invalid:{reportValidity(){assert.fail('history cannot be blocked by current input');}},custom:[input]});
 const snapshot={catalogValues:{'site:size':'1152x896'},refs:[]};assert.equal(f.context.submit(snapshot),true);
 assert.equal(f.calls[0].snapshot.catalogValues['site:size'],'1152x896');assert.equal(input.reported,undefined);assert.equal(input.validationMessage,undefined);
 const other={draft:{catalogValues:{'site:size':'896x1152'},refs:[]}};assert.equal(f.context.submit(undefined,other),true);assert.equal(f.calls[1].session,other);
});

test('custom dimensions are flushed before blur, or block without silently using the previous dimensions',()=>{
 for(const value of ['1000x1024','128x1024','8192x1024','broken']){
  const input={value},f=form({custom:[input]});f.session.draft.catalogValues['site:size']='1024x1024';
  assert.equal(f.context.submit(),false,value);assert.equal(f.calls.length,0);assert.equal(f.session.draft.catalogValues['site:size'],'1024x1024');assert.match(input.validationMessage,/512–4096.*32/);
 }
 const input={value:' 2048 × 1024 '},f=form({custom:[input]});f.session.draft.catalogValues['site:size']='1024x1024';
 let prevented=false;f.listeners.keydown({key:'Enter',ctrlKey:true,repeat:false,preventDefault(){prevented=true;}});
 assert.equal(prevented,true);assert.equal(f.calls.length,1);assert.equal(f.calls[0].snapshot.catalogValues['site:size'],'2048x1024');assert.equal(f.hidden.value,'2048x1024');assert.equal(input.validationMessage,'');assert.equal(f.unrelated.value,'keep this number','a shared group must not write its first unrelated field');
 input.value='';assert.equal(f.context.submit(),false,'clearing an active custom size cannot reuse its old value');
 f.session.draft.catalogValues['site:size']='1152x896';assert.equal(f.context.submit(),true,'the intentionally empty optional custom input is valid while a preset is selected');
});

test('visible floating dimensions flush before keyboard submission, preserve companion controls, and ignore a hidden old panel',()=>{
 for(const value of ['invalid','1000x1024']){const input={value},f=form({floating:[input]});f.listeners.keydown({key:'Enter',ctrlKey:true,repeat:false,preventDefault(){}});assert.equal(f.calls.length,0);assert.match(input.validationMessage,/512–4096.*32/);}
 const inline={value:''},input={value:' 2048 X 1024 '},stale={value:'invalid stale panel'},f=form({custom:[inline],floating:[input],hiddenFloating:[stale]});
 f.listeners.keydown({key:'Enter',ctrlKey:true,repeat:false,preventDefault(){}});assert.equal(f.calls.length,1);assert.equal(f.calls[0].snapshot.catalogValues['site:size'],'2048x1024');assert.equal(f.hidden.value,'2048x1024');assert.equal(f.panelHidden.value,'2048x1024');assert.equal(inline.value,'2048 × 1024');assert.equal(f.unrelated.value,'keep this number');assert.equal(stale.reported,undefined);
 assert.equal(f.context.submit(),true,'the synchronized inline text must not block a subsequent submission');
});

function storage({ready=true,readonly=false,write=async()=>{},snapshotError=false}={}){
 const session={id:'active',draft:{prompt:'current input',refs:[]},jobs:[]},messages=[],writes=[],timers=[],box={hidden:true,innerHTML:''};
 const context=vm.createContext({state:{sessions:[session],active:session.id},workspace:{collections:[],reviewSeeded:false},nextSession:1,nextJob:1,storageReady:ready,saveTimer:null,structuredClone:snapshotError?()=>{throw new Error('cannot clone');}:structuredClone,Promise,location:{search:readonly?'?review-readonly=1':''},URLSearchParams,writeState:async(...args)=>{writes.push(args);await write(...args);},toast:message=>messages.push(message),active:()=>session,workflow:()=>({catalogOnly:true}),$:()=>box,catalogOverview:()=>'<p>saved overview</p>',setTimeout:fn=>{timers.push(fn);return timers.length;},clearTimeout(){}});
 vm.runInContext(saveSource,context);return {context,session,messages,writes,timers,box};
}

test('manual save reports success only after persistence succeeds',async()=>{
 const s=storage();assert.equal(await s.context.saveCatalogDraft(),true);assert.equal(s.writes.length,1);assert.deepEqual(s.messages,['草稿已保存 · 未调用模型']);assert.equal(s.box.hidden,false);
 const unavailable=storage({ready:false});assert.equal(await unavailable.context.saveWorkspace(),false);assert.equal(await unavailable.context.saveCatalogDraft(),false);assert.equal(unavailable.writes.length,0);assert(!unavailable.messages.some(message=>message.includes('草稿已保存')));
 const failed=storage({write:async()=>{throw new Error('quota full');}});assert.equal(await failed.context.saveCatalogDraft(),false);assert.equal(failed.writes.length,1);assert.equal(failed.box.innerHTML,'');assert(!failed.messages.some(message=>message.includes('草稿已保存')));assert.match(failed.messages[0],/本地保存失败/);
});

test('automatic save resolves failure, leaves its baseline intact, and permits a later successful queued save',async()=>{
 let fail=true;const s=storage({write:async()=>{if(fail)throw new Error('disk quota');}});
 s.context.scheduleSave();assert.equal(s.timers.length,1);assert.equal(await s.timers[0](),false,'the timer callback cannot create an unhandled rejection');assert.equal(vm.runInContext('workspaceSaveBaseline',s.context),null);
 fail=false;s.session.draft.prompt='recovered input';assert.equal(await s.context.saveWorkspace(),true);assert.equal(vm.runInContext('workspaceSaveBaseline.sessions[0].draft.prompt',s.context),'recovered input');
 const broken=storage({snapshotError:true});assert.equal(await broken.context.saveWorkspace(),false,'snapshot errors follow the same safe automatic-save result');assert.equal(broken.writes.length,0);
});

test('the explicit read-only comparison URL never writes state or reports a save error',async()=>{
 const s=storage({readonly:true});assert.equal(await s.context.saveWorkspace(),false);assert.equal(await s.context.saveCatalogDraft(),false);
 s.context.scheduleSave();for(const callback of s.timers)assert.equal(await callback(),false);
 assert.equal(s.writes.length,0);assert.deepEqual(s.messages,[]);assert.equal(s.box.innerHTML,'');
});

const mergeSource=source('function mergeCatalogJob(','\nasync function retrieveLiveOutputs(');
const recoverySource=source('async function retrieveLiveOutputs(','\nasync function submitLive(');
const statusSource=source('function liveJobStatus(','\nfunction mergeCatalogJob(');
const buttonSource=app.split('\n').find(line=>line.startsWith('const B='));assert(buttonSource);
function recovery({response,requestError}={}){
 const w={id:'catalog',catalogConnected:true,output:'image',catalogConnection:{adapter:'generic'},interface:{controls:[],texts:[],media:[]}},requests=[],messages=[];
 const context=vm.createContext({workflows:[w],workspace:{assets:[]},effectiveCatalogInterface,catalogHistorySnapshot,catalogReferenceSnapshots,catalogValuesFromSettings:(tool,settings)=>catalogHistorySnapshot(tool,{settings}).catalogValues,mergeReferenceSnapshots:()=>[],cloneDraft:structuredClone,crypto:globalThis.crypto,refreshFeed(){},sidebar(){},scheduleSave(){},toast:message=>messages.push(message),liveJson:value=>value,liveApi:async(path,options)=>{requests.push({path,options});if(requestError)throw requestError;return typeof response==='function'?response():response;},esc,I:()=>'',formatTime:()=>'',Promise,Date});
 vm.runInContext(buttonSource+'\n'+mergeSource+'\n'+recoverySource+'\n'+statusSource,context);return {context,requests,messages,w};
}
const receipt=(status='done',extra={})=>({id:'remote-job',workflow_id:'catalog',status,stage:'作品已保存',prompt:'original input',prompt_id:'original-prompt',settings:{},catalog_values:{},catalog_texts:{},catalog_assets:{},outputs:[],...extra});
const outputFailure=()=>({id:'local-job',remoteId:'remote-job',promptId:'original-prompt',real:true,status:'failed',failurePhase:'output',error:'file too large',outputs:[],snapshot:{prompt:'original input',refs:[]}});

test('output failure renders retrieval rather than a paid generation retry, while ordinary failures retain retry',()=>{
 const r=recovery({response:receipt()}),markup=r.context.liveJobStatus(outputFailure());assert.match(markup,/重新取回作品/);assert.match(markup,/retrieve-output/);assert.doesNotMatch(markup,/算力卡计费|data-action="retry"|修改后重试/);
 const ordinary=r.context.liveJobStatus({...outputFailure(),failurePhase:null});assert.match(ordinary,/重试 · 算力卡计费/);assert.match(ordinary,/data-action="retry"/);
});

test('both merge paths preserve an output failure and clear it when the authoritative phase or state changes',()=>{
 const r=recovery();
 for(const merge of [r.context.mergeCatalogJob,r.context.mergeLiveJob]){
  const j=outputFailure();merge(j,receipt('failed',{failure_phase:'output'}));assert.equal(j.failurePhase,'output');
  merge(j,receipt('failed'));assert.equal(j.failurePhase,'output','a partial failure response does not erase a known phase');
  merge(j,receipt('failed',{failure_phase:null}));assert.equal(j.failurePhase,null,'an explicit generation failure clears the old output phase');
  merge(j,receipt('failed',{failure_phase:'output'}));merge(j,receipt('downloading'));assert.equal(j.failurePhase,null);assert.equal(j.status,'running');
  merge(j,receipt('done',{failure_phase:null,error:null,connection_error:null}));assert.equal(j.failurePhase,null);assert.equal(j.error,null);assert.equal(j.connection_error,null);
 }
 const legacy=recovery();legacy.w.catalogConnected=false;const j=outputFailure();legacy.context.mergeLiveJob(j,receipt('failed',{failure_phase:'output'}));assert.equal(j.failurePhase,'output');legacy.context.mergeLiveJob(j,receipt('done'));assert.equal(j.failurePhase,null);
});

test('retrieval keeps the original task identity, does not append a job, and cannot dispatch rerun or prompt',async()=>{
 const r=recovery({response:receipt()}),j=outputFailure(),session={jobs:[j]},before=structuredClone(j.snapshot);
 await r.context.rerunLive(j,session,{},false);assert.equal(session.jobs.length,1);assert.equal(j.id,'local-job');assert.equal(j.remoteId,'remote-job');assert.deepEqual(j.snapshot.refs,before.refs);assert.equal(j.status,'done');assert.equal(j.retrieving,false);
 assert.deepEqual(structuredClone(r.requests),[{path:'/api/jobs/remote-job/retrieve',options:{method:'POST'}}]);assert.deepEqual(r.messages,['作品已重新取回。']);
});

test('retrieval is single-flight and handles a rejected request without generating again',async()=>{
 let resolve;const r=recovery({response:()=>new Promise(done=>{resolve=done;})}),j=outputFailure(),pending=r.context.retrieveLiveOutputs(j);
 assert.equal(j.retrieving,true);assert.equal(await r.context.retrieveLiveOutputs(j),false);assert.equal(r.requests.length,1);resolve(receipt('downloading',{stage:'正在取回作品'}));await pending;assert.equal(j.status,'running');assert.equal(j.retrieving,false);
 const failed=recovery({requestError:new Error('offline')}),unavailable=outputFailure();assert.equal(await failed.context.retrieveLiveOutputs(unavailable),true);assert.equal(unavailable.status,'failed');assert.equal(unavailable.failurePhase,'output');assert.equal(unavailable.retrieving,false);assert.match(failed.messages[0],/取回作品失败/);assert.equal(failed.requests[0].path,'/api/jobs/remote-job/retrieve');
});

test('even a stale ordinary Retry action routes an output failure to retrieval',async()=>{
 const r=recovery({response:receipt()}),j=outputFailure();let pending;
 const retrieve=r.context.retrieveLiveOutputs;r.context.retrieveLiveOutputs=job=>(pending=retrieve(job));r.context.findJob=()=>({j,s:{jobs:[j]}});r.context.handleWorkspaceAction=()=>false;
 vm.runInContext(actionSource,r.context);r.context.handleAction('retry',{dataset:{job:j.id}});await pending;
 assert.equal(r.requests.length,1);assert.equal(r.requests[0].path,'/api/jobs/remote-job/retrieve');assert.equal(j.status,'done');
});

function submitting(kind,error){
 const w={id:'catalog',name:'测试工具',output:'image',catalogConnected:true,catalogConnection:{adapter:'generic'},interface:{sourceHash:'source',controls:[],texts:[],media:[]}},session={id:'session',draft:{prompt:'existing input',refs:[],catalogValues:{},liveSettings:{}},jobs:[]},requests=[];
 const context=vm.createContext({active:()=>session,workflow:()=>w,liveWorkflow:()=>w,state:{active:session.id},workspace:{assets:[]},effectiveCatalogInterface,catalogConnectionState:()=>({blocked:false}),catalogPromptProblem:()=>null,catalogSubmission:()=>({}),cloneDraft:structuredClone,visibleRefs:d=>d.refs,missingMentions:()=>[],hasRemovedReference:()=>false,renumberDraftReferences:d=>d,prepareCatalogSnapshot(){},liveSettings:d=>d.liveSettings,liveProblem:()=>null,crypto:globalThis.crypto,Date,refreshFeed(){},refreshComposer(){},sidebar(){},scheduleSave(){},closePanel(){},render(){},toast(){},liveJson:value=>value,liveApi:async(path,options)=>{requests.push({path,options});throw error;}});
 const chunk=kind==='catalog'?source('async function submitCatalogLive(','\nfunction flushCatalogCustomSize('):source('async function submitLive(','\nlet livePollBusy=');
 vm.runInContext(chunk,context);return {context,session,requests};
}

test('explicit 409 rejection fails each creation path immediately instead of leaving an uncertain running task',async()=>{
 for(const kind of ['catalog','legacy']){
  const error=Object.assign(new Error('积分报价已变化，请确认当前费用后重试。'),{httpStatus:409}),f=submitting(kind,error);
  await (kind==='catalog'?f.context.submitCatalogLive(undefined,f.session):f.context.submitLive(undefined,f.session));
  assert.equal(f.requests.length,1);assert.equal(f.requests[0].path,'/api/jobs');assert.equal(f.session.liveSubmitting,false);
  const j=f.session.jobs[0];assert.equal(j.status,'failed');assert.equal(j.submissionUncertain,false);assert.equal(j.error,error.message);assert.equal(typeof j.ended,'number');
 }
 const error=Object.assign(new Error('本次创作未提交。'),{httpStatus:409}),r=recovery({requestError:error}),original={...outputFailure(),failurePhase:null},session={jobs:[original]};
 await r.context.rerunLive(original,session,{disabled:false},false);const retried=session.jobs[1];assert.equal(retried.status,'failed');assert.equal(retried.error,error.message);assert.equal(original.rerunning,false);assert.equal(retried.submissionUncertain,undefined);
});

test('an actual lost connection still preserves uncertain submission recovery',async()=>{
 for(const kind of ['catalog','legacy']){
  const f=submitting(kind,new Error('connection lost'));
  await (kind==='catalog'?f.context.submitCatalogLive(undefined,f.session):f.context.submitLive(undefined,f.session));
  const j=f.session.jobs[0];assert.equal(j.status,'running');assert.equal(j.submissionUncertain,true);assert.match(j.error,/请勿重复/);assert.equal(j.ended??null,null);assert.equal(f.session.liveSubmitting,false);
 }
});

test('old demo job values never reappear as payable retry fees',()=>{
 const context=vm.createContext({Date,DEMO_DURATION:12000,I:()=>'',formatTime:()=>'',esc});
 vm.runInContext(buttonSource+'\n'+source('function statusInfo(','\nfunction promptMarkup('),context);
 for(const status of ['failed','cancelled']){
  const html=context.progressHTML({id:'old-demo',status,cost:999,started:Date.now()-1000,snapshot:{type:'image'}});
  assert.match(html,/预览|预览记录/);assert.doesNotMatch(html,/999|积分|演示生成|不扣费/);
 }
});

function freeSubmission(){
 const session={id:'free-session',scope:'model',draft:{prompt:'保留我的描述',refs:[{id:'图片1',src:'private-input',kind:'image'}],model:'seedream-4.5',type:'image'},jobs:[]},listeners={},messages=[],batchError={textContent:''};
 const context=vm.createContext({production:true,active:()=>session,workflow:()=>null,liveWorkflow:()=>null,document:{querySelectorAll:()=>[],querySelector:()=>null,addEventListener:(name,listener)=>{listeners[name]=listener;}},inlineError:(text,fix)=>{messages.push({text,fix});session.draft.error={text,fix};},handleWorkspaceAction:()=>false,$:selector=>selector==='#batch-error'?batchError:selector==='#prompt'?{}:null,dialog:{open:false,close(){assert.fail('unavailable creation cannot close the batch dialog');}},workspace:{prompts:['第一条保留','第二条保留']},state:{active:session.id},scheduleSave(){assert.fail('unavailable creation must not save a fake job');},findJob:()=>null});
 vm.runInContext(submissionSource+'\n'+actionSource+'\n'+keyboardSource+'\n'+source('async function runPrompts(','\nfunction handleWorkspaceAction('),context);
 return {context,session,listeners,messages,batchError};
}

test('unconnected free creation blocks Generate and keyboard submissions without creating jobs or clearing input',()=>{
 const f=freeSubmission(),before=structuredClone(f.session.draft);
 assert.equal(f.context.submit(),false);f.context.handleAction('generate',{});
 for(const modifier of ['ctrlKey','metaKey']){let prevented=false;f.listeners.keydown({key:'Enter',[modifier]:true,repeat:false,preventDefault(){prevented=true;}});assert.equal(prevented,true);}
 assert.equal(f.session.jobs.length,0);assert.equal(f.session.draft.prompt,before.prompt);assert.deepEqual(f.session.draft.refs,before.refs);assert.equal(f.messages.length,4);assert(f.messages.every(message=>message.fix==='creation-service'&&/尚未接入/.test(message.text)));
});

test('retry and rerun of old free previews cannot mutate the old record or create another fake job',()=>{
 for(const action of ['retry','rerun']){
  const f=freeSubmission(),job={id:'old-preview',status:'done',outputs:[{id:'original',src:'assets/coast.jpg'}],snapshot:structuredClone(f.session.draft)},before=structuredClone(job);f.session.jobs.push(job);f.context.findJob=()=>({j:job,s:f.session});f.context.cloneDraft=structuredClone;
  f.context.handleAction(action,{dataset:{job:job.id}});assert.equal(f.session.jobs.length,1);assert.deepEqual(job,before);assert.equal(f.session.draft.prompt,before.snapshot.prompt);assert.deepEqual(f.session.draft.refs,before.snapshot.refs);
 }
});

test('unconnected free batch creation preserves every prompt and the open dialog without a success toast',async()=>{
 const f=freeSubmission(),before=structuredClone(f.session.draft),prompts=structuredClone(f.context.workspace.prompts);
 assert.equal(await f.context.runPrompts(),false);assert.deepEqual(f.context.workspace.prompts,prompts);assert.deepEqual(f.session.draft,before);assert.equal(f.session.jobs.length,0);assert.match(f.batchError.textContent,/尚未接入/);
});

test('a cancelled real task describes platform credit handling without asserting an unverified refund',()=>{
 const context=vm.createContext({esc,B:()=>'',Date,formatTime:()=>''});vm.runInContext(source('function liveJobStatus(','\nfunction mergeCatalogJob('),context);
 const html=context.liveJobStatus({status:'cancelled'});assert.match(html,/平台冻结积分按取消结果处理/);assert.doesNotMatch(html,/已用费用不退|已退|已退款/);
});

test('all demo review routes seed free jobs without a removed cost calculator',()=>{
 for(const mode of ['results','progress','error']){
  const session={draft:{refs:[]},jobs:[]},context=vm.createContext({location:{search:'?demo='+mode},production:true,URLSearchParams,Date,crypto:globalThis.crypto,DEMO_DURATION:12000,resolveSession(){},active:()=>session,complete:j=>{j.status='done';}});
  vm.runInContext(source('function seedReview(','\nfunction viewportHeight('),context);context.seedReview();
  assert.equal(session.jobs.length,mode==='results'?2:1);assert(session.jobs.every(j=>j.cost===0));assert.equal(session.draft.prompt,'');
 }
});
