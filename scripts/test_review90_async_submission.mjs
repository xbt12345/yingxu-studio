import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import {declaration,installCreationSelectors} from './test_app_source.mjs';
import * as workspaceMedia from '../public/workspace-media.js';
import {normalizeDraft} from '../public/models.js';
import {effectiveCatalogInterface,catalogConnectionState,catalogPromptProblem,catalogSubmission} from '../public/catalog-submission.js';
import {matchesLiveRecord,reconcileLiveJobs,referenceProvenance} from '../public/live-history.js';

const source=readFileSync(new URL('../public/app.js',import.meta.url),'utf8');
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
const settle=()=>new Promise(resolve=>setImmediate(resolve));
const remoteId='a'.repeat(32),uploadedId='b'.repeat(64);
function fixture({creation=false,refs=[],hooks={}}={}){
 const w={id:'fixture',name:'fixture',output:'image',catalogOnly:true,catalogConnected:true,catalogConnection:{adapter:'generic'},interface:{sourceHash:'fixture',controls:[],texts:[{id:'p',role:'prompt'}],media:refs.map((ref,index)=>({id:ref.catalogSlot||'slot'+index,kind:ref.kind,required:true}))}};
 const session={id:'fixture-session',scope:creation?'model':'wf:fixture',draft:{type:creation?'video':'image',model:'baidu-sd2.5',mode:creation&&refs.length?'参考图':'纯文本',quality:'480p',ratio:'16:9',duration:'4 秒',prompt:'第一条描述',negative:'',catalogTexts:{p:'第一条描述'},refs:structuredClone(refs)},jobs:[]};
 const calls=[],messages=[];
 const receipt=(extra={})=>({id:remoteId,workflow_id:w.id,prompt:'第一条描述',settings:{},status:'queued',stage:'排队中',...extra});
 const context=vm.createContext({...workspaceMedia,effectiveCatalogInterface,catalogConnectionState,catalogPromptProblem,catalogSubmission,normalizeDraft,matchesLiveRecord,reconcileLiveJobs,referenceProvenance,
  active:()=>session,workflow:()=>w,cloneDraft:structuredClone,structuredClone,visibleRefs:d=>d.refs,renumberDraftReferences:d=>d,hasRemovedReference:()=>false,prepareCatalogSnapshot:()=>{},creationModes:{'纯文本':'text','参考图':'reference_image'},referenceProblem:()=>'',
  toast:message=>messages.push(message),inlineError:message=>assert.fail(message),showCatalogIssue:message=>assert.fail(message),crypto:globalThis.crypto,Date,state:{sessions:[session]},workspace:{assets:[]},
  refreshFeed:()=>{},sidebar:()=>{},scheduleSave:()=>{},refreshComposer:()=>{},closePanel:()=>{},render:()=>{},
  canReuseReferenceUpload:ref=>!!ref.serverAssetId,referenceUploadParts:async ref=>hooks.parts?hooks.parts(ref):{file:{type:'image/png'}},referenceUploadForm:()=>null,
  liveJson:value=>({method:'POST',body:value}),publicPreview:false,production:true,workflows:[w],$:()=>null,dialog:{open:false},route:()=>({name:'home'}),
  mergeLiveJob:(job,record)=>Object.assign(job,{remoteId:record.id,token:record.request_token||job.token,status:['done','failed','cancelled','abandoned'].includes(record.status)?record.status:'running',serverStatus:record.status,cancelPersisted:!!record.cancel_requested,stage:record.stage,submissionUncertain:false}),
  liveApi:async(path,options)=>{
   calls.push({path,method:options?.method||'GET',body:options?.body});
   if(path.startsWith('/api/assets'))return hooks.upload?hooks.upload():{id:uploadedId,src:'/api/assets/'+uploadedId+'/file'};
   if(path.endsWith('/cancel'))return hooks.cancel?hooks.cancel():receipt({status:'cancelling',cancel_requested:true});
   if(path.endsWith('/abandon'))return receipt({status:'abandoned'});
   if(path==='/api/jobs'&&!options)return hooks.poll?hooks.poll():[];
   return hooks.submit?hooks.submit():receipt();
  }});
 installCreationSelectors(context,source);
 vm.runInContext(['async function submitCatalogLive(','async function submitCreation(','async function rerunLive(','async function cancelLive(','async function abandonCreation(','function refreshHomeResume('].map(prefix=>declaration(source,prefix)).join('\n')+'\nlet livePollBusy=false;\n'+declaration(source,'async function syncLiveJobs('),context);
 return {context,session,calls,messages,hooks,receipt,submit:()=>creation?context.submitCreation(null,session):context.submitCatalogLive(null,session)};
}
const image=(extra={})=>({id:'图片1',kind:'image',name:'source.png',src:'/source.png',catalogSlot:'source',...extra});
const jobPosts=f=>f.calls.filter(call=>call.method==='POST'&&(/\/jobs$/.test(call.path)||call.path.endsWith('/rerun')));
const cancelPosts=f=>f.calls.filter(call=>call.path.endsWith('/cancel'));

test('cancel during local reference preparation prevents upload and generation',async()=>{
 const parts=deferred(),f=fixture({refs:[image()],hooks:{parts:()=>parts.promise}}),pending=f.submit();
 await settle();await f.context.cancelLive(f.session.jobs[0]);parts.resolve({file:{type:'image/png'}});await pending;
 assert.equal(f.calls.length,0);assert.equal(f.session.jobs[0].status,'cancelled');assert.equal(f.session.liveSubmitting,false);
});
test('cancel during upload prevents remaining uploads and generation',async()=>{
 const upload=deferred(),f=fixture({refs:[image(),image({id:'图片2',catalogSlot:'second',src:'/second.png'})],hooks:{upload:()=>upload.promise}}),pending=f.submit();
 await settle();await f.context.cancelLive(f.session.jobs[0]);upload.resolve({id:uploadedId});await pending;
 assert.equal(f.calls.filter(call=>call.path==='/api/assets').length,1);assert.equal(jobPosts(f).length,0);assert.equal(f.session.jobs[0].status,'cancelled');
});
test('cancelled upload failure stays a local cancellation without a generated task',async()=>{
 const upload=deferred(),f=fixture({refs:[image()],hooks:{upload:()=>upload.promise}}),pending=f.submit();
 await settle();await f.context.cancelLive(f.session.jobs[0]);upload.reject(new Error('upload disconnected'));await pending;
 assert.equal(jobPosts(f).length,0);assert.equal(f.session.jobs[0].status,'cancelled');
});
test('cancel while catalog POST is pending forwards once after the receipt',async()=>{
 const response=deferred(),f=fixture({hooks:{submit:()=>response.promise}}),pending=f.submit();
 await settle();await f.context.cancelLive(f.session.jobs[0]);response.resolve(f.receipt());await pending;
 assert.equal(jobPosts(f).length,1);assert.equal(cancelPosts(f).length,1);assert.equal(f.session.jobs[0].cancelPersisted,true);assert.equal(f.session.jobs[0].status,'running','remote acknowledgement is still cancelling, not cancelled');
});
test('rerun cancellation is forwarded after its receipt',async()=>{
 const response=deferred(),f=fixture({hooks:{submit:()=>response.promise}}),original={status:'done',remoteId:'original',snapshot:structuredClone(f.session.draft)},pending=f.context.rerunLive(original,f.session);
 await settle();await f.context.cancelLive(f.session.jobs[0]);response.resolve(f.receipt());await pending;
 assert.equal(jobPosts(f).length,1);assert.equal(cancelPosts(f).length,1);assert.equal(original.rerunning,false);
});
test('uncertain submission recovers by token and sends the pending cancellation',async()=>{
 const response=deferred(),f=fixture({hooks:{submit:()=>response.promise}}),pending=f.submit();
 await settle();const job=f.session.jobs[0];await f.context.cancelLive(job);response.reject(new Error('disconnected'));await pending;
 assert.equal(job.submissionUncertain,true);f.hooks.poll=()=>[f.receipt({request_token:job.token})];await f.context.syncLiveJobs();
 assert.equal(cancelPosts(f).length,1);assert.equal(job.cancelPersisted,true);
});
test('failed cancellation keeps its intent for the next successful poll',async()=>{
 const f=fixture();await f.submit();const job=f.session.jobs[0];f.hooks.cancel=()=>{throw new Error('cancel disconnected');};
 await f.context.cancelLive(job);assert.equal(job.cancelRequested,true);
 f.hooks.cancel=()=>f.receipt({status:'cancelling',cancel_requested:true});f.hooks.poll=()=>[f.receipt({request_token:job.token})];await f.context.syncLiveJobs();
 assert.equal(cancelPosts(f).length,2);assert.equal(job.cancelRequested,false);
});
test('a pending cancel and a simultaneous poll cannot send duplicate cancels',async()=>{
 const response=deferred(),f=fixture();await f.submit();const job=f.session.jobs[0];f.hooks.cancel=()=>response.promise;f.hooks.poll=()=>[f.receipt({request_token:job.token})];
 const first=f.context.cancelLive(job),second=f.context.cancelLive(job),poll=f.context.syncLiveJobs();await settle();const count=cancelPosts(f).length;
 response.resolve(f.receipt({status:'cancelling',cancel_requested:true}));await Promise.all([first,second,poll]);assert.equal(count,1);
 f.hooks.poll=()=>[f.receipt({request_token:job.token,status:'cancelling',cancel_requested:true})];await f.context.syncLiveJobs();assert.equal(cancelPosts(f).length,1);
});
test('a finished receipt is not sent a late cancel request',async()=>{
 const response=deferred(),f=fixture({hooks:{submit:()=>response.promise}}),pending=f.submit();
 await settle();await f.context.cancelLive(f.session.jobs[0]);response.resolve(f.receipt({status:'done'}));await pending;
 assert.equal(cancelPosts(f).length,0);assert.equal(f.session.jobs[0].status,'done');
});

for(const [name,edit]of [
 ['new prompt',draft=>{draft.prompt='第二条描述';}],
 ['new reference',draft=>{draft.refs.push(image({src:'/second.png'}));}],
 ['in-place reference edit',draft=>{draft.refs[0].referenceEdits={crop:{x:0.1}};}],
 ['replacement draft with identical content',null]
])test('creation receipt preserves '+name,async()=>{
 const response=deferred(),f=fixture({creation:true,refs:name==='in-place reference edit'?[image({serverAssetId:uploadedId})]:[],hooks:{submit:()=>response.promise}}),pending=f.submit();
 await settle();if(edit)edit(f.session.draft);else f.session.draft=structuredClone(f.session.draft);const expected=structuredClone(f.session.draft);
 response.resolve(f.receipt({creation:true}));await pending;assert.deepEqual(f.session.draft,expected);assert.equal(jobPosts(f)[0].body.prompt,'第一条描述');
});
test('unchanged creation draft clears after acceptance, including upload metadata writes',async()=>{
 const response=deferred(),f=fixture({creation:true,refs:[image()],hooks:{submit:()=>response.promise}}),pending=f.submit();
 await settle();assert.equal(f.session.draft.refs[0].serverAssetId,uploadedId);response.resolve(f.receipt({creation:true}));await pending;
 assert.equal(f.session.draft.prompt,'');assert.deepEqual(f.session.draft.refs,[]);assert.equal(f.session.jobs[0].snapshot.prompt,'第一条描述');assert.equal(f.session.jobs[0].snapshot.refs.length,1);
});
test('failed creation and accepted retry retain the editable draft',async()=>{
 const f=fixture({creation:true,hooks:{submit:()=>{throw Object.assign(new Error('rejected'),{httpStatus:400});}}});await f.submit();assert.equal(f.session.draft.prompt,'第一条描述');
 f.hooks.submit=()=>f.receipt({creation:true});await f.context.submitCreation(structuredClone(f.session.draft),f.session);assert.equal(f.session.draft.prompt,'第一条描述');
});
test('creation stop during submission remains stop-waiting and never remote cancellation',async()=>{
 const response=deferred(),f=fixture({creation:true,hooks:{submit:()=>response.promise}}),pending=f.submit();
 await settle();await f.context.abandonCreation(f.session.jobs[0]);response.resolve(f.receipt({creation:true}));await pending;
 assert.equal(cancelPosts(f).length,0);assert.equal(f.calls.filter(call=>call.path.endsWith('/abandon')).length,1);assert.equal(f.session.jobs[0].status,'abandoned');
});
