import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {similarWorkflows,originalReference,originalReferences,originalMediaReference,restoredInputs,matchesWork,taskCover} from '../public/workflow-experience.js';
import {selectControl} from '../public/workflow-select.js';
import {esc} from '../public/data.js';
const catalog=JSON.parse(readFileSync(new URL('../public/local-catalog.json',import.meta.url),'utf8')).workflows;
const schemas=JSON.parse(readFileSync(new URL('../public/workflow-interfaces.json',import.meta.url),'utf8')).workflows;
const workflows=catalog.map(w=>({...w,interface:schemas[w.id]}));
const outfit=workflows.find(w=>w.id==='local-card-3');
assert.deepEqual(similarWorkflows(outfit,workflows).map(w=>w.id),['local-card-3','local-card-73']);
const refs=[{kind:'image',src:'/original.png',catalogSlot:'551'},{kind:'image',src:'/clothes.png',catalogSlot:'547'}];
const field=outfit.interface.controls.find(f=>f.kind==='seed');
const snapshot={workflowId:outfit.id,catalogLive:true,prompt:'换成蓝色衣服',negative:'文字',refs,catalogValues:{[field.id]:424254},catalogSeedModes:{}};
const before=structuredClone(snapshot),restored=restoredInputs(snapshot,outfit);
assert.deepEqual(restored.refs,refs);
assert.equal(restored.catalogSeedModes[field.id],'fixed');
assert.equal(restored.catalogValues[field.id],424254);
restored.refs[0].src='/edited-draft.png';
assert.deepEqual(snapshot,before,'editing a restored draft must never change historical input');
const o={type:'image',src:'/result.png'},j={real:true,status:'done',started:1000,snapshot};
assert.equal(originalReference(j,o).src,'/original.png');
assert.ok(taskCover(outfit,[{o,j}]).includes('/original.png'));
assert.ok(taskCover(outfit,[{o,j}]).includes('/result.png'));
assert.doesNotThrow(()=>taskCover(outfit,[{o,j:{...j,snapshot:{...snapshot,refs:[]}}}]));
assert.ok(!taskCover(outfit,[{o,j:{...j,real:false}}]).includes('/result.png'),'demo output must not be presented as a real cover');
const now=Date.now(),row={o,j:{...j,started:now-8*86400000}};
assert.equal(matchesWork(row,'蓝色','all',now,workflows),true);
assert.equal(matchesWork(row,'换衣','all',now,workflows),false);
assert.equal(matchesWork(row,'服装','all',now,workflows),true);
assert.equal(matchesWork(row,'','7',now,workflows),false);
assert.equal(matchesWork(row,'','30',now,workflows),true);

// Comparison must use the saved original, rather than the erased RGB model input.
const editedRefs=[{id:'图片1',name:'原图',kind:'image',assetId:'masked',originalAssetId:'original-a',originalSrc:'blob:before-reload-a',src:'/masked-a.png',annotationMode:'mask'},{id:'图片2',name:'第二参考',kind:'image',assetId:'masked-b',originalAssetId:'original-b',originalSrc:'blob:before-reload-b',src:'/masked-b.png',referenceEdits:{regions:[{}]}}];
const assets=[{id:'original-a',src:'blob:current-a',blob:new Blob(['original A'])},{id:'original-b',src:'blob:current-b',blob:new Blob(['original B'])}],editedJob={...j,snapshot:{...snapshot,refs:editedRefs},outputs:[{...o,id:'result-a'}]},editedBefore=structuredClone(editedJob);
assert.equal(originalReference(editedJob,o,assets).src,'blob:current-a','current hydrated original asset wins over persisted blob URLs');
assert.deepEqual(originalReferences(editedJob,o,assets).map(r=>r.src),['blob:current-a','blob:current-b']);
assert.equal(originalMediaReference({...editedRefs[0],originalServerAssetId:'original-server'},[]).src,'/api/assets/original-server/file');
assert.equal(originalMediaReference({...editedRefs[0],originalAssetId:undefined,originalSrc:'/durable-original.png'},[]).src,'/durable-original.png');
assert.equal(originalMediaReference(editedRefs[0],[]),null,'an expired original blob must not fall back to a masked input');
assert.equal(originalMediaReference({...editedRefs[0],originalAssetId:undefined,originalSrc:undefined},[]),null,'a mask without original identity cannot be called an original');
assert.equal(originalMediaReference({kind:'image',assetId:'original-a',src:'blob:before-reload-a'},assets).src,'blob:current-a','ordinary local inputs also use the hydrated asset');
assert.equal(originalMediaReference({kind:'video',src:'/original.mp4'},[]).src,'/original.mp4');
assert.equal(originalMediaReference({kind:'image',src:'blob:expired'},[]),null);
assert.equal(originalMediaReference({...editedRefs[0],available:false},assets).src,'blob:current-a','missing remote model input does not hide an available local original');
assert.equal(originalMediaReference({...editedRefs[0],originalServerAssetId:'missing-server-original',originalAvailable:false},[]),null,'a proven but unavailable original must not substitute the paired input');
assert.equal(originalMediaReference({...editedRefs[0],originalAvailable:false},assets).src,'blob:current-a','a valid local original remains usable when the server original has been removed');
const cover=taskCover(outfit,[{o,j:editedJob}],false,assets);assert(cover.includes('blob:current-a'));assert(!cover.includes('/masked-a.png'));

const app=readFileSync(new URL('../public/app.js',import.meta.url),'utf8'),compareStart=app.indexOf('function compareOriginal('),compareEnd=app.indexOf('\nfunction attachGeneratedOutput(',compareStart),rendered=[],messages=[],imageNodes=[{},{}];let closed=0;
const compareContext=vm.createContext({findOutput:()=>({o:editedJob.outputs[0],j:editedJob}),workspace:{assets},originalReference,originalReferences,selectControl,esc,workflowOutputLabel:(_id,label)=>label,B:()=>'',modal:(title,html)=>rendered.push({title,html}),toast:text=>messages.push(text),$$:()=>imageNodes,dialog:{close(){closed++;}}});vm.runInContext(app.slice(compareStart,compareEnd),compareContext);
compareContext.compareOriginal('result-a');assert.equal(rendered.length,1);assert(rendered[0].html.includes('src="blob:current-a"'));assert(rendered[0].html.includes('value="blob:current-b"'),'each selectable reference uses its own unedited source');assert(!rendered[0].html.includes('/masked-')&&!rendered[0].html.includes('blob:before-reload'));
imageNodes[0].onerror();assert.equal(closed,1);assert.match(messages.at(-1),/未编辑原图无法读取/);
compareContext.workspace.assets=[];compareContext.compareOriginal('result-a');assert.equal(rendered.length,1,'missing originals do not open a misleading mask comparison');assert.match(messages.at(-1),/未编辑原图已不可用/);
assert.deepEqual(editedJob,editedBefore,'comparison resolves copies and never replaces historical input identities');

// Execute production hydration against isolated saved fixtures, without browser state.
const hydrateRows=structuredClone(editedRefs);hydrateRows.forEach((r,i)=>r.serverAssetId='paired-input-'+i);
const persistedFixture={sessions:[{id:'s-hydrate',scope:'wf:local-card-15',draft:{prompt:'刷新合同',refs:hydrateRows},jobs:[{id:'real-job',real:true,status:'done',snapshot:{refs:structuredClone(hydrateRows)}}]}],active:'s-hydrate',nextSession:3,nextJob:3},fixtureBefore=structuredClone(persistedFixture),hydrateStart=app.indexOf('async function initializeWorkspace('),hydrateEnd=app.indexOf("\ndocument.addEventListener('click',scheduleSave)",hydrateStart);let freshCounter=0;
class HydrationURL extends URL{}HydrationURL.createObjectURL=()=>`blob:hydrated-${++freshCounter}`;
const hydration=vm.createContext({production:true,openStorage:async()=>{},readAssets:async()=>structuredClone(assets),readState:async()=>structuredClone(persistedFixture),state:{sessions:[]},workspace:{},URL:HydrationURL,URLSearchParams,location:{search:'?review=71.3'},workflow:()=>({interface:{media:[]}}),renumberDraftReferences(){},normalizeDraft(){assert.fail('a workflow draft must not be normalized as free creation');},workspaceSnapshot:()=>({}),workspaceSaveBaseline:null,storageReady:false,render(){},scheduleSave(){},toast:message=>assert.fail(message)});
vm.runInContext(app.slice(hydrateStart,hydrateEnd),hydration);await hydration.initializeWorkspace();
for(const ref of [hydration.state.sessions[0].draft.refs[0],hydration.state.sessions[0].jobs[0].snapshot.refs[0]]){assert.equal(ref.originalAssetId,'original-a');assert.equal(ref.originalSrc,hydration.workspace.assets.find(a=>a.id==='original-a').src);assert.match(ref.originalSrc,/^blob:hydrated-/);assert.equal(ref.src,'/api/assets/paired-input-0/file');assert.equal(originalReference({snapshot:{refs:[ref]}},o,hydration.workspace.assets).src,ref.originalSrc);}
assert.deepEqual(persistedFixture,fixtureBefore,'hydration preserves the stored original identity and does not mutate its read fixture');

// Changed modules must share the entry release key, not retain a stale module URL.
const studio=readFileSync(new URL('../public/studio.html',import.meta.url),'utf8'),release=studio.match(/src="app\.js\?v=([^"]+)"/)[1],changedModules=new Set(['app.js','workflow-control-library.js','design-preview.js','catalog-ui.js','catalog-submission.js','reference-editor.js','reference-upload.js','workflow-experience.js','storage.js','workspace-merge.js','workflow-controls.js','workflow-select.js','workflow-page.js','processing-duration.js','point-picker.js','workflow-interfaces.json','live-history.js']);
for(const file of ['studio.html','workflow-control-library.html','design-preview.html','app.js','catalog-ui.js','reference-upload.js','storage.js','workflow-controls.js','workflow-page.js','processing-duration.js','workflow-control-library.js','design-preview.js','catalog-submission.js','workspace-merge.js']){const source=readFileSync(new URL('../public/'+file,import.meta.url),'utf8');for(const match of source.matchAll(/([\w-]+\.(?:js|json))\?v=([0-9.]+)/g))if(changedModules.has(match[1]))assert.equal(match[2],release,file+' retains a different release for '+match[1]);}
console.log(JSON.stringify({similarTasks:'passed',originalInputRestoration:'passed',fixedSeedRestoration:'passed',immutableHistory:'passed',coverEvidence:'passed',searchAndTime:'passed',uneditedComparisonSources:'passed',freshAssetAndServerFallback:'passed',multiReferenceOriginalOptions:'passed',lostOriginalAndDecodeError:'passed',actualCompareRendering:'passed',actualHydrationIdentity:'passed',entryModuleCacheChain:'passed'}));
