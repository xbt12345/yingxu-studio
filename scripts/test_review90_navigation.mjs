import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import {declaration} from './test_app_source.mjs';
import {matchesLiveRecord,reconcileLiveJobs} from '../public/live-history.js';

const source=readFileSync(new URL('../public/app.js',import.meta.url),'utf8');
function fixture(hash){
 const state={active:'existing-h3',sessions:[{id:'existing-h3',scope:'wf:h3-reference',draft:{type:'video',prompt:'已有草稿',refs:[]},jobs:[]},{id:'s61',scope:'model',draft:{type:'image',prompt:'旧链接仍可打开',refs:[]},jobs:[]}]};
 const workflows=[{id:'h3-reference',category:'视频生成',name:'H3',output:'video'},{id:'valid-other',category:'图像生成',name:'Other',output:'image'}],listeners={},calls={editor:0,observer:0,submit:0};
 const main={innerHTML:''},location={hash},context=vm.createContext({state,workflows,location,decodeURIComponent,crypto:globalThis.crypto,
  history:{replaceState:(a,b,value)=>{location.hash=value;}},newDraft:type=>({type,prompt:'',refs:[]}),defaultModel:type=>({id:type+'-default'}),
  active:()=>state.sessions.find(session=>session.id===state.active)||state.sessions[0],production:true,main,shell:{},dialog:{open:false,close(){}},
  document:{body:{classList:{remove(){}},className:''},title:'',addEventListener:(name,listener)=>{listeners[name]=listener;}},
  cleanup:[],closeApiMentionMenu(){},closePanel(){},sidebar(){},sidebarPointerInside:false,sidebarPeekDismissed:false,
  resizeObserver:{disconnect(){}},feedResizeObserver:{disconnect(){}},I:()=>'',esc:value=>String(value),workflowTitle:w=>w.name,
  workflowCreation:()=>{calls.editor++;return '<textarea id="prompt"></textarea><button data-action="generate">生成</button>';},creation:()=>{calls.editor++;return '<textarea id="prompt"></textarea><button data-action="generate">生成</button>';},
  observeComposer(){calls.observer++;},syncSelection(){},syncWorkSelection(){},setupWorkflowMask(){},fitCatalogSelector(){},revealAssetUse(){},
  $:selector=>selector==='#prompt'&&main.innerHTML.includes('id="prompt"')?{}:null,submit(){calls.submit++;}
 });
 const prefixes=['function route(','const workflow=','function makeSession(','function resolveSession(','function render('];
 for(const prefix of ['function missingCreationRoute(','function missingCreationPage('])if(source.includes(prefix))prefixes.unshift(prefix);
 vm.runInContext(prefixes.map(prefix=>declaration(source,prefix)).join('\n'),context);
 const keyboard=source.split('\n').find(line=>line.startsWith("document.addEventListener('keydown',e=>{if(e.key==='Escape')"));vm.runInContext(keyboard,context);
 return {context,state,workflows,location,main,calls,listeners};
}

for(const hash of ['#workflow/nonexistent','#session/nonexistent','#workflow','#session']){
 test(hash+' never resolves to the previously active session',()=>{
  const f=fixture(hash),before=structuredClone(f.state);assert.equal(f.context.resolveSession(),null);assert.deepEqual(f.state,before);assert.equal(f.location.hash,hash);
 });
 test(hash+' renders recovery links without an editor or keyboard generation',()=>{
  const f=fixture(hash);f.context.render();assert.match(f.main.innerHTML,/未找到/);assert.match(f.main.innerHTML,/href="#workflows"/);assert.match(f.main.innerHTML,/href="#new"/);
  assert.doesNotMatch(f.main.innerHTML,/id="prompt"|data-action="generate"|composer-slot/);assert.equal(f.calls.editor,0);assert.equal(f.calls.observer,0);
  for(const key of ['ctrlKey','metaKey'])f.listeners.keydown({key:'Enter',[key]:true,preventDefault(){assert.fail('missing editor has no generation shortcut');}});
  assert.equal(f.calls.submit,0);assert.match(f.context.document.title,/未找到/);
 });
}
test('existing workflow, legacy session and reference deep links retain their exact targets',()=>{
 const f=fixture('#workflow/h3-reference');assert.equal(f.context.resolveSession().id,'existing-h3');assert.equal(f.state.sessions.length,2);
 for(const hash of ['#session/s61','#session/s61/ref/图片1']){f.location.hash=hash;assert.equal(f.context.resolveSession().id,'s61');f.context.render();assert.equal(f.state.active,'s61');assert.match(f.main.innerHTML,/id="prompt"/);}
 assert.equal(f.state.sessions[1].apiRefsPinned,true);
});
test('a valid workflow with no prior session creates its own draft only once',()=>{
 const f=fixture('#workflow/valid-other'),session=f.context.resolveSession();assert.equal(session.scope,'wf:valid-other');assert.equal(session.draft.type,'image');assert.equal(f.state.sessions.length,3);assert.equal(f.context.resolveSession(),session);assert.equal(f.state.sessions.length,3);
});
test('leaving a missing route restores a valid editor without altering earlier drafts',()=>{
 const f=fixture('#workflow/nonexistent');f.context.render();f.location.hash='#workflow/h3-reference';f.context.render();assert.equal(f.calls.editor,1);assert.equal(f.state.sessions[0].draft.prompt,'已有草稿');assert.doesNotMatch(f.main.innerHTML,/未找到/);
});

test('first asynchronous history sync updates only the home resume region',async()=>{
 const f=fixture('#home'),region={outerHTML:'',contains:()=>false,querySelectorAll:()=>[]};let release;
 Object.assign(f.context,{publicPreview:false,Date,matchesLiveRecord,reconcileLiveJobs,taskOperation:w=>({title:w.name}),creationRecord:()=>false,creationJob:()=>false,
  liveApi:()=>new Promise(resolve=>{release=resolve;}),scheduleSave(){},$:selector=>selector==='.home-resume'?region:null,
  mergeLiveJob:(job,record)=>Object.assign(job,{status:'done',started:record.started,stage:'已完成',outputs:record.outputs})});
 const helpers=['function resumeTime(','function homeResume(','function homeResumeCard('];if(source.includes('function refreshHomeResume('))helpers.push('function refreshHomeResume(');
 vm.runInContext(helpers.map(prefix=>declaration(source,prefix)).join('\n')+'\nlet livePollBusy=false;\n'+declaration(source,'async function syncLiveJobs('),f.context);
 region.outerHTML=f.context.homeResume();f.main.innerHTML='unrelated home sections';assert.match(region.outerHTML,/开始一次创作后/);
 const pending=f.context.syncLiveJobs();release([{id:'a'.repeat(32),workflow_id:'h3-reference',prompt:'从服务端找回的历史',settings:{},started:1000,outputs:[]}]);await pending;
 assert.match(region.outerHTML,/home-resume-card/);assert.equal(f.main.innerHTML,'unrelated home sections');assert.equal(f.calls.editor,0);
});

for(const id of ['works-search','inspiration-search'])test(id+' accepts input while the first history request is pending',async()=>{
 const listeners={},workspace={},output={innerHTML:''};let release,refreshes=0;
 const pending=new Promise(resolve=>{release=resolve;}),context=vm.createContext({production:true,publicPreview:false,workspace,document:{addEventListener:(name,listener)=>{listeners[name]=listener;}},syncLiveJobs:()=>pending,setInterval(){},refreshLibrary(){refreshes++;},$:()=>output,inspirationContent:()=>workspace.inspirationQuery});
 const startup=source.split('\n').find(line=>line.startsWith('if(production&&!publicPreview){'));
 const input=source.indexOf("if(e.target.id==='works-search')"),start=source.lastIndexOf("document.addEventListener('input',e=>{",input),end=source.indexOf('\n});',input)+4;
 const task=vm.runInContext('(async()=>{'+startup+'\n'+source.slice(start,end)+'\n})()',context);
 const listener=listeners.input;listener?.({target:{id,value:'early impossible query'}});release();await task;
 assert.equal(typeof listener,'function','visible inputs must already have their handlers while history is loading');
 assert.equal(workspace[id==='works-search'?'workQuery':'inspirationQuery'],'early impossible query');assert.equal(id==='works-search'?refreshes:output.innerHTML,id==='works-search'?1:'early impossible query');
});
