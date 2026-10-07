import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import {defaultModel,getModel} from '../public/models.js';
import {referenceResult} from '../public/catalog-submission.js';
import {boundReferences,sameMedia} from '../public/workspace-media.js';
import {nextReferenceId,renumberDraftReferences} from '../public/reference-numbering.js';

const source=readFileSync(new URL('../public/app.js',import.meta.url),'utf8');
const lineFor=prefix=>{const line=source.split(/\r?\n/).find(line=>line.startsWith(prefix));assert.ok(line,prefix);return line;};
const reuse=source.slice(source.indexOf('function attachGeneratedOutput('),source.indexOf('\nlet draggingOutputId=',source.indexOf('function attachGeneratedOutput(')));
const image={id:'result-image',type:'image',src:'/api/media/job/result.png'};
const tool={id:'image-tool',catalogOnly:true,interface:{media:[{id:'original',kind:'image'},{id:'style',kind:'image'}],controls:[]}};
const oldReference={id:'图片1',kind:'image',src:'/original.png',assetId:'protected-original',catalogSlot:'original',referenceEdits:{regions:[{x:.2,y:.2,width:.3,height:.3}]}};

function fixture({page='library',tool:currentTool=tool,draft={},output=image,modal=true,behavior='load'}={}){
 const current={id:'existing-session',scope:currentTool?'wf:'+currentTool.id:'model',draft:{type:'image',model:'seedream-4.5',mode:'全能参考',prompt:'原来的描述',refs:[structuredClone(oldReference)],...draft},jobs:[{id:'history-job',snapshot:{prompt:'历史描述',refs:[structuredClone(oldReference)]},outputs:[structuredClone(output)]}]};
 const state={sessions:[current],active:current.id},workflows=currentTool?[currentTool]:[],location={hash:'#'+(page==='session'?page+'/'+current.id:page)};
 const notices=[],messages=[],media=[],timers=new Map(),clearedSlots=[];let sequence=0,renders=0,saves=0,focuses=0,refreshes=0;
 const dialog={open:modal,querySelector(selector){if(selector==='[data-output-reference-error]')return notices[0]||null;if(selector==='.viewer-actions,.dialog-actions')return {before(node){notices.push(node);}};return null;},append(node){notices.push(node);},close(){this.open=false;}};
 const makeMedia=type=>{
  const element={type,naturalWidth:80,naturalHeight:60,load(){this.cancelled=true;},removeAttribute(name){assert.equal(name,'src');delete this.source;}};
  Object.defineProperty(element,'src',{set(value){element.source=value;if(behavior!=='pending')queueMicrotask(()=>{if(behavior==='error')element.onerror?.();else if(type==='image')element.onload?.();else element.onloadedmetadata?.();});}});
  media.push(element);return element;
 };
 const document={createElement(tag){if(tag==='p')return {dataset:{},setAttribute(name,value){this[name]=value;},textContent:''};return makeMedia(tag);}};
 const context=vm.createContext({state,workflows,workspace:{},location,dialog,document,Image:function(){return makeMedia('image');},defaultModel,getModel,referenceResult,boundReferences,sameMedia,nextReferenceId,renumberDraftReferences,crypto:globalThis.crypto,
  active:()=>state.sessions.find(session=>session.id===state.active),
  route:()=>({name:location.hash.slice(1).split('/')[0]}),
  workflow:session=>workflows.find(workflow=>session.scope==='wf:'+workflow.id)||null,
  findOutput:id=>{for(const session of state.sessions)for(const job of session.jobs)for(const result of job.outputs)if(result.id===id)return {o:result,j:job,s:session};return null;},
  kindLabel:kind=>({image:'图像',video:'视频',audio:'音频'})[kind],
  clearPointsForMedia:(_draft,_workflow,slot)=>clearedSlots.push(slot),
  refreshComposer:()=>refreshes++,scheduleSave:()=>saves++,render:()=>renders++,closePanel(){},toast:message=>messages.push(message),$:selector=>selector==='#prompt'?{focus:()=>focuses++}:null,
  setTimeout:callback=>{const id=++sequence;timers.set(id,callback);return id;},clearTimeout:id=>timers.delete(id),
  fetch(){assert.fail('reference reuse must never submit or generate');}
 });
 vm.runInContext([lineFor('function newDraft('),lineFor('function makeSession('),lineFor('function visibleRefs('),lineFor('const videoEditWorkflows='),lineFor('const videoSourceOnlyWorkflows='),lineFor('function liveWorkflow('),lineFor('function liveProblem('),lineFor('function referenceProblem('),reuse].join('\n'),context);
 return {context,state,current,location,dialog,messages,notices,media,timers,clearedSlots,stats:()=>({renders,saves,focuses,refreshes}),expire(){for(const callback of [...timers.values()])callback();}};
}

test('library reference opens an independent compatible draft and preserves the old workflow and history',async()=>{
 const f=fixture(),before=structuredClone(f.current);
 assert.equal(await f.context.openOutputTask(image.id,'reference'),true);
 assert.equal(f.state.sessions.length,2);assert.deepEqual(f.current,before);
 const created=f.state.sessions[1];assert.equal(created.scope,'model');assert.equal(created.draft.type,'image');assert.equal(created.draft.refs.length,1);assert.equal(created.draft.refs[0].sourceOutputId,image.id);
 assert.equal(f.location.hash,'session/'+created.id);assert.equal(f.dialog.open,false);assert.equal(f.stats().renders,1);assert.equal(f.timers.size,0);
});

test('a workflow viewer keeps the active editor and binds only an empty matching slot',async()=>{
 const f=fixture({page:'session'}),historyBefore=structuredClone(f.current.jobs);
 assert.equal(await f.context.openOutputTask(image.id,'reference'),true);
 assert.equal(f.state.sessions.length,1);assert.equal(f.current.draft.refs.length,2);assert.equal(f.current.draft.refs.find(ref=>ref.sourceOutputId===image.id).catalogSlot,'style');assert.deepEqual(f.current.draft.refs[0],oldReference);assert.deepEqual(f.current.jobs,historyBefore);
});

test('full workflow slots report inside the viewer without replacing material or creating a draft',async()=>{
 const full=[structuredClone(oldReference),{id:'图片2',kind:'image',src:'/style.png',catalogSlot:'style'}],f=fixture({page:'session',draft:{refs:full}}),before=structuredClone(f.current);
 assert.equal(await f.context.openOutputTask(image.id,'reference'),false);
 assert.deepEqual(f.current,before);assert.equal(f.state.sessions.length,1);assert.equal(f.dialog.open,true);assert.match(f.notices[0].textContent,/参考位已满/);assert.equal(f.notices[0].role,'alert');assert.equal(f.stats().renders,0);
});

test('text-only reference mode reveals an existing image without duplicating it',async()=>{
 const f=fixture({page:'create',tool:null,draft:{mode:'纯文本',refs:[{id:'图片1',kind:'image',src:image.src,sourceOutputId:image.id}]}});
 assert.equal(await f.context.openOutputTask(image.id,'reference'),true);assert.equal(f.current.draft.mode,'全能参考');assert.equal(f.current.draft.refs.length,1);assert.equal(f.stats().refreshes,1);
});

test('audio cannot be silently appended to an image editor',async()=>{
 const audio={id:'result-audio',type:'audio',src:'/result.wav'},f=fixture({page:'create',tool:null,output:audio,draft:{refs:[]}}),before=structuredClone(f.current);
 assert.equal(await f.context.openOutputTask(audio.id,'reference'),false);assert.deepEqual(f.current,before);assert.match(f.notices[0].textContent,/只接收图片/);assert.equal(f.stats().renders,0);
});

for(const type of ['video','audio'])test(`library ${type} opens a compatible video draft after readable metadata`,async()=>{
 const output={id:'result-'+type,type,src:'/result.'+(type==='video'?'mp4':'wav')},f=fixture({output});
 assert.equal(await f.context.openOutputTask(output.id,'reference'),true);
 const created=f.state.sessions[1];assert.equal(created.draft.type,'video');assert.ok(getModel(created.draft).kinds.includes(type));assert.equal(created.draft.refs[0].kind,type);assert.equal(f.media[0].preload,'metadata');assert.equal(f.media[0].cancelled,true);assert.equal(f.timers.size,0);
});

test('expired image sources show an error and preserve the viewer, history and draft',async()=>{
 const f=fixture({output:{...image,src:'blob:expired'},behavior:'error'}),before=structuredClone(f.state);
 assert.equal(await f.context.openOutputTask(image.id,'reference'),false);
 assert.deepEqual(f.state,before);assert.equal(f.dialog.open,true);assert.match(f.notices[0].textContent,/失效或无法读取/);assert.equal(f.stats().renders,0);assert.equal(f.timers.size,0);
});

for(const unavailable of [{available:false},{src:''},{removedAt:123}])test(`known unavailable output is rejected without loading: ${JSON.stringify(unavailable)}`,async()=>{
 const f=fixture({output:{...image,...unavailable}}),before=structuredClone(f.state);
 assert.equal(await f.context.openOutputTask(image.id,'reference'),false);assert.deepEqual(f.state,before);assert.equal(f.media.length,0);assert.match(f.notices[0].textContent,/不可用/);
});

test('a timed-out media read does not report success or leave a pending operation',async()=>{
 const f=fixture({behavior:'pending'}),before=structuredClone(f.state),pending=f.context.openOutputTask(image.id,'reference');f.expire();
 assert.equal(await pending,false);assert.deepEqual(f.state,before);assert.match(f.notices[0].textContent,/读取超时/);assert.equal(f.timers.size,0);assert.equal(f.context.openOutputTask.pendingReferences.size,0);
});

test('repeated clicks while loading create one draft and one reference',async()=>{
 const f=fixture({behavior:'pending'}),first=f.context.openOutputTask(image.id,'reference');assert.equal(await f.context.openOutputTask(image.id,'reference'),false);
 f.media[0].onload();assert.equal(await first,true);assert.equal(f.state.sessions.length,2);assert.equal(f.state.sessions[1].draft.refs.length,1);assert.equal(f.stats().renders,1);
});

test('navigation during a media read cancels reuse rather than mutating another editor',async()=>{
 const f=fixture({behavior:'pending'}),before=structuredClone(f.state),pending=f.context.openOutputTask(image.id,'reference');f.location.hash='#settings';f.media[0].onload();
 assert.equal(await pending,false);assert.deepEqual(f.state,before);assert.equal(f.location.hash,'#settings');assert.match(f.messages.at(-1),/已切换创作/);assert.equal(f.stats().renders,0);
});

test('explicit catalog replacement retains its slot and reference identity; saved history is immutable',()=>{
 const f=fixture({page:'session'}),historyBefore=structuredClone(f.current.jobs);
 assert.equal(f.context.attachGeneratedOutput(image,'original'),true);assert.equal(f.current.draft.refs.length,1);assert.equal(f.current.draft.refs[0].id,'图片1');assert.equal(f.current.draft.refs[0].catalogSlot,'original');assert.equal(f.current.draft.refs[0].sourceOutputId,image.id);assert.deepEqual(f.clearedSlots,['original']);assert.deepEqual(f.current.jobs,historyBefore);
});

test('the production action dispatcher reaches reference reuse',async()=>{
 const f=fixture();f.context.handleWorkspaceAction=()=>false;
 vm.runInContext(lineFor('function handleAction('),f.context);
 f.context.handleAction('reference',{dataset:{id:image.id}});
 for(let i=0;i<4&&f.context.openOutputTask.pendingReferences.size;i++)await Promise.resolve();
 assert.equal(f.state.sessions.length,2);assert.equal(f.state.sessions[1].draft.refs[0].sourceOutputId,image.id);assert.equal(f.stats().renders,1);
});
