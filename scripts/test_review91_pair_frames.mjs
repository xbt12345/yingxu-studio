import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import {declaration,installCreationSelectors} from './test_app_source.mjs';
import {models,defaultModel,getModel,normalizeDraft} from '../public/models.js';
import {boundReferences,sameMedia,missingMentions} from '../public/workspace-media.js';
import {nextReferenceId,renumberDraftReferences} from '../public/reference-numbering.js';
import {esc} from '../public/data.js';

const source=readFileSync(new URL('../public/app.js',import.meta.url),'utf8');
const asset=(id,kind='image')=>({id,kind,name:id+'.png',src:'/'+id+'.png'});
function fixture(){
 const session={id:'pair-session',scope:'model',draft:{type:'video',model:'seedance-2.0',mode:'首尾帧',prompt:'镜头从首帧到尾帧',negative:'',ratio:'16:9',quality:'720p',duration:'10 秒',count:1,refs:[]},jobs:[]};
 const state={sessions:[session],active:session.id},workspace={assets:[],collections:[],assetSelected:new Set(),picker:false},messages=[],dialogs=[],popups=[],listeners={},imports=[];let sequence=0;
 const context=vm.createContext({state,workspace,workflows:[],models,defaultModel,getModel,normalizeDraft,boundReferences,sameMedia,missingMentions,nextReferenceId,renumberDraftReferences,esc,I:()=>'',structuredClone,
  active:()=>state.sessions[0],workflow:()=>null,liveWorkflow:()=>null,videoEditWorkflows:new Set(),videoSourceOnlyWorkflows:new Set(),production:true,
  kindLabel:kind=>({image:'图像',video:'视频',audio:'音频'})[kind],issueHTML:()=>'',advancedCount:()=>0,placeholder:()=>'',apiReferenceShelf:()=>'<div class="unexpected-general-shelf"></div>',
  document:{addEventListener:(name,listener)=>{listeners[name]=listener;},querySelectorAll:()=>[],querySelector:()=>null},dialog:{open:false,close(){this.open=false;}},location:{hash:'#session/pair-session'},
  panel:{classList:{add(){}},setAttribute(){},querySelector:()=>null},popup:(anchor,title,html)=>popups.push({title,html}),positionPanel(){},
  toast:message=>messages.push(message),inlineError:message=>messages.push(message),clearCatalogIssue(){},refreshComposer(){},render(){},closePanel(){},scheduleSave(){},saveWorkspace(){},
  assetPanel:()=>'<div>asset picker</div>',modal:(title,html)=>{dialogs.push({title,html});context.dialog.open=true;},$:()=>({focus(){}}),
  importAssets:async files=>{imports.push(files);return files.map(file=>{const added=asset('import-'+(++sequence));workspace.assets.push(added);return added;});},
  nextSession:1,nextJob:1});
 installCreationSelectors(context,source);
 const prefixes=['const B=','const creationRatioLabel=','function visibleRefs(','function rebindCreationMode(','function refsExpandedMarkup(','function uploadControl(','function composer(','function allowedKinds(','function referenceProblem(','function openAssetPicker(','function attachAsset(','function attachSelected(','async function addFiles(','function saveRef(','function workspaceSnapshot(','function options(','function openIntent(','function submit('];
 vm.runInContext(prefixes.map(prefix=>declaration(source,prefix)).join('\n'),context);
 const click=source.split('\n').find(line=>line.startsWith("document.addEventListener('click',e=>{const p=e.target.closest('[data-popup]')"));vm.runInContext(click,context);
 const clickTarget=target=>listeners.click({target:{closest:selector=>selector===target.selector?target:null}});
 return {context,session,state,workspace,messages,dialogs,popups,imports,mode:value=>clickTarget({selector:'[data-param]',dataset:{param:'mode',value}}),remove:id=>clickTarget({selector:'[data-remove]',dataset:{remove:id}})};
}
const localFile={type:'image/png',name:'local.png'};
const slots=draft=>draft.refs.map(ref=>[ref.slot,ref.assetId]).sort((a,b)=>a[0]-b[0]);

test('empty pair mode exposes both frame slots beside the prompt',()=>{
 const f=fixture(),html=f.context.composer();assert.match(html,/aria-label="选择首帧"/);assert.match(html,/aria-label="选择尾帧"/);assert.match(html,/data-files[^>]*data-slot="0"/);assert.match(html,/data-files[^>]*data-slot="1"/);assert.doesNotMatch(html,/unexpected-general-shelf/);
});
test('occupied pair mode keeps roles, removal and direct replacement for both frames',()=>{
 const f=fixture();f.context.attachAsset(asset('first'),f.session.draft,0);f.context.attachAsset(asset('last'),f.session.draft,1);
 const html=f.context.composer();for(const name of ['首帧','尾帧']){assert.match(html,new RegExp('aria-label="查看'+name+'"'));assert.match(html,new RegExp('aria-label="移除'+name+'"'));assert.match(html,new RegExp('aria-label="上传'+name+'"'));assert.match(html,new RegExp('aria-label="从素材库选择'+name+'"'));}assert.doesNotMatch(html,/unexpected-general-shelf/);
});
test('direct uploads bind numeric first and last slots independently',async()=>{
 const f=fixture();await f.context.addFiles([localFile],'0');await f.context.addFiles([localFile],'1');assert.deepEqual(slots(f.session.draft),[[0,'import-1'],[1,'import-2']]);assert.equal(f.session.draft.mode,'首尾帧');
});
test('replacing one uploaded frame preserves the other and the existing mention ID',async()=>{
 const f=fixture();await f.context.addFiles([localFile],'0');await f.context.addFiles([localFile],'1');const first=f.session.draft.refs.find(ref=>ref.slot===0),last=f.session.draft.refs.find(ref=>ref.slot===1);f.session.draft.prompt='从@'+first.id+'到@'+last.id;
 await f.context.addFiles([localFile],'0');assert.deepEqual(slots(f.session.draft),[[0,'import-3'],[1,'import-2']]);assert.equal(f.session.draft.refs.find(ref=>ref.slot===0).id,first.id);assert.equal(f.session.draft.refs.find(ref=>ref.slot===1).id,last.id);assert.equal(f.session.draft.prompt,'从@'+first.id+'到@'+last.id);
});
test('removal and re-addition affect only the chosen frame',async()=>{
 const f=fixture();await f.context.addFiles([localFile],'0');await f.context.addFiles([localFile],'1');f.remove(f.session.draft.refs.find(ref=>ref.slot===0).id);assert.deepEqual(slots(f.session.draft),[[1,'import-2']]);assert.match(f.context.composer(),/aria-label="选择首帧"/);
 await f.context.addFiles([localFile],'0');assert.deepEqual(slots(f.session.draft),[[0,'import-3'],[1,'import-2']]);
});
test('material picker uses the chosen slot and replaces only that frame',()=>{
 const f=fixture();f.workspace.assets=[asset('first'),asset('last'),asset('replacement')];
 for(const [slot,id]of [[0,'first'],[1,'last'],[1,'replacement']]){f.context.openAssetPicker(String(slot));assert.equal(f.workspace.pickerSlot,slot);assert.equal(f.workspace.imageReferenceOnly,true);f.workspace.assetSelected.add(id);f.context.attachSelected();}
 assert.deepEqual(slots(f.session.draft),[[0,'first'],[1,'replacement']]);
});
test('general material entry selects the remaining empty frame and never creates an invisible reference',()=>{
 const f=fixture();f.context.attachAsset(asset('first'),f.session.draft,0);f.workspace.assets=[asset('last')];f.context.openAssetPicker();assert.equal(f.workspace.pickerSlot,1);assert.equal(f.dialogs.at(-1).title,'选择尾帧');f.workspace.assetSelected.add('last');f.context.attachSelected();assert.deepEqual(slots(f.session.draft),[[0,'first'],[1,'last']]);
});
test('general entry with two occupied frames requests an explicit replacement slot',async()=>{
 const f=fixture();f.context.attachAsset(asset('first'),f.session.draft,0);f.context.attachAsset(asset('last'),f.session.draft,1);f.context.openAssetPicker();assert.equal(f.dialogs.length,0);assert.match(f.messages.at(-1),/首帧.*尾帧/);await f.context.addFiles([localFile]);assert.equal(f.imports.length,0);assert.deepEqual(slots(f.session.draft),[[0,'first'],[1,'last']]);
});
test('a generic upload without a slot fills the first empty frame',async()=>{
 const f=fixture();await f.context.addFiles([localFile]);await f.context.addFiles([localFile]);assert.deepEqual(slots(f.session.draft),[[0,'import-1'],[1,'import-2']]);
});
test('frame import rejects video and multiple-file ambiguity before storing anything',async()=>{
 const f=fixture();await f.context.addFiles([{type:'video/mp4'}],'0');await f.context.addFiles([localFile,localFile],'1');assert.equal(f.imports.length,0);assert.equal(f.session.draft.refs.length,0);
});
test('material frame selection rejects incompatible or multiple assets without changing either slot',()=>{
 const f=fixture();f.workspace.assets=[asset('video','video'),asset('one'),asset('two')];f.context.openAssetPicker('0');f.workspace.assetSelected.add('video');f.context.attachSelected();assert.equal(f.session.draft.refs.length,0);f.workspace.assetSelected=new Set(['one','two']);f.context.attachSelected();assert.equal(f.session.draft.refs.length,0);
});
test('switching between pair, text and general modes preserves the two stored frame bindings',async()=>{
 const f=fixture();await f.context.addFiles([localFile],'0');await f.context.addFiles([localFile],'1');const expected=slots(f.session.draft);for(const mode of ['纯文本','全能参考','首尾帧'])f.mode(mode);assert.deepEqual(slots(f.session.draft),expected);assert.match(f.context.composer(),/aria-label="查看尾帧"/);
 const saved=f.context.workspaceSnapshot();assert.deepEqual(slots(saved.sessions[0].draft),expected,'persisted snapshots retain both exact frame roles');
});
for(const [field,value]of [['mode','纯文本'],['model','veo-3.1'],['type','image']])test('an import finishing after a '+field+' change preserves the updated editor and leaves the file in the library',async()=>{
 const f=fixture();let finish;f.context.importAssets=()=>new Promise(resolve=>{finish=resolve;});const pending=f.context.addFiles([localFile],'0');if(field==='mode')f.mode(value);else f.session.draft[field]=value;finish([asset('late-import')]);await pending;assert.equal(f.session.draft[field],value);assert.equal(f.session.draft.refs.length,0);assert.match(f.messages.at(-1),/素材库/);
});
test('pair references do not unlock an unconnected model or invent Baidu pair support',()=>{
 const f=fixture();f.context.attachAsset(asset('first'),f.session.draft,0);f.context.attachAsset(asset('last'),f.session.draft,1);assert.equal(f.context.submit(),false);assert.match(f.messages.at(-1),/尚未接入/);
 for(const model of models.filter(model=>model.creationApi)){assert(!model.modes.includes('首尾帧'));f.session.draft.model=model.id;f.context.openIntent({dataset:{popup:'reference'}});assert.doesNotMatch(f.popups.at(-1).html,/data-value="首尾帧"/);}
});
