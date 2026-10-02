import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {boundReferences,sameMedia,missingMentions,clearSubmittedContent,assetReferences} from '../public/workspace-media.js';
import {nextReferenceId,renumberDraftReferences} from '../public/reference-numbering.js';

const w={catalogOnly:true,interface:{media:[{id:'original',kind:'image'},{id:'clothes',kind:'image'}]}};
const refs=[
 {id:'图片1',kind:'image',src:'/original.png',catalogSlot:'original',assetId:'a'},
 {id:'图片2',kind:'image',src:'/clothes.png',catalogSlot:'clothes'},
 {id:'图片3',kind:'image',src:'/old-api.png'},
 {id:'图片4',kind:'image',src:'/removed-slot.png',catalogSlot:'old-slot'},
 {id:'视频1',kind:'video',src:'/wrong-kind.mp4',catalogSlot:'original'}
];
const d={type:'image',mode:'全能参考',refs};
assert.deepEqual(boundReferences(d,w).map(r=>r.id),['图片1','图片2']);
assert.deepEqual(missingMentions('将@图片1 换成@图片2，参考@图片3 和@图片3',boundReferences(d,w)),['@图片3']);
assert.deepEqual(boundReferences({...d,refs:refs.map(r=>r.id==='图片1'?{...r,available:false}:r)},w).map(r=>r.id),['图片2']);
assert.deepEqual(boundReferences(d,{catalogOnly:true,interface:{media:[]}}),[],'text-only workflow must not expose legacy media');
assert.equal(refs.length,5,'filtering does not discard stored draft material');

assert.equal(sameMedia({kind:'image',sourceOutputId:'result-a',src:'blob:old'},{type:'image',id:'result-a',src:'blob:new'}),true);
assert.equal(sameMedia({kind:'image',src:'/result.png'},{type:'image',id:'other-id',src:'/result.png'}),true);
assert.equal(sameMedia({kind:'video',src:'/result.png'},{type:'image',src:'/result.png'}),false);
assert.equal(sameMedia({kind:'image',src:'/a.png'},{type:'image',src:'/b.png'}),false);

const session={scope:'model',draft:{prompt:'下一张图',refs:[...refs],negative:'水印',model:'selected-model',ratio:'9:16'},jobs:[]};
const snapshot=structuredClone(session.draft);
session.jobs.push({snapshot});
assert.equal(clearSubmittedContent(session,{retry:true}),false);
assert.equal(session.draft.prompt,'下一张图','retry or validation paths preserve pending content');
assert.equal(clearSubmittedContent(session),true);
assert.deepEqual(session.draft.refs,[]);
assert.equal(session.draft.prompt,'');
assert.equal(session.draft.negative,'');
assert.equal(session.draft.model,'selected-model');
assert.equal(session.draft.ratio,'9:16');
assert.equal(snapshot.prompt,'下一张图');
assert.equal(snapshot.refs.length,5,'history keeps the submitted inputs after clearing');
assert.equal(clearSubmittedContent({scope:'wf:edit',draft:structuredClone(snapshot)}),false);

const history=structuredClone(refs[0]);
const sessions=[{id:'s1',title:'图片换衣',draft:{refs:[refs[0]]},jobs:[{id:'j1',started:123,snapshot:{prompt:'换装',refs:[history]}}]},
 {id:'s2',title:'区域编辑',draft:{refs:[{id:'图片1',maskAssetId:'mask',originalAssetId:'a',src:'/annotated.png'}]},jobs:[]}];
const uses=assetReferences({id:'a',src:'blob:rehydrated'},sessions);
assert.deepEqual(uses.map(u=>[u.sessionId,u.type,u.jobId||u.refId]),[['s1','draft','图片1'],['s1','job','j1'],['s2','draft','图片1']]);
assert.equal(assetReferences({id:'mask'},sessions)[0].sessionId,'s2');
assert.equal(assetReferences({id:'different',name:'original.png'},sessions).length,0,'same filename is not proof of shared media');
assert.equal(assetReferences({id:'server-copy',serverAssetId:'remote-a'},[{id:'s3',draft:{refs:[]},jobs:[{id:'remote-job',snapshot:{refs:[{id:'图片1',serverAssetId:'remote-a'}]}}]}])[0].jobId,'remote-job');
assert.deepEqual(history,refs[0],'usage inspection leaves original inputs untouched');

// Exercise the production attachment path twice, rather than only its identity helper.
const source=readFileSync(new URL('../public/app.js',import.meta.url),'utf8');
const attachment=source.slice(source.indexOf('function attachGeneratedOutput('),source.indexOf('function bindOutputToCatalogDraft('));
const apiSession={scope:'model',draft:{type:'image',mode:'全能参考',prompt:'',refs:[]}};
const context=vm.createContext({active:()=>apiSession,workflow:()=>null,sameMedia,nextReferenceId,renumberDraftReferences,workspace:{},referenceProblem:()=>null,refreshComposer(){},scheduleSave(){},toast(){},kindLabel:k=>k});
vm.runInContext(attachment,context);
const result={id:'generated-a',type:'image',src:'/generated.png'};
assert.equal(context.attachGeneratedOutput(result),true);
assert.equal(context.attachGeneratedOutput(result),true);
assert.equal(apiSession.draft.refs.length,1,'two deliveries of one output add exactly one reference');
assert.equal(apiSession.draft.refs[0].sourceOutputId,result.id);
apiSession.draft.mode='首尾帧';apiSession.draft.refs=[];
context.workspace.pickerSlot=0;context.attachGeneratedOutput(result);
context.workspace.pickerSlot=1;context.attachGeneratedOutput(result);
assert.equal(apiSession.draft.refs.length,2,'explicit first/last frame choices may intentionally use the same image');
context.workspace.pickerSlot=0;context.attachGeneratedOutput({...result,id:'replacement',src:'/other.png'});
assert.equal(apiSession.draft.refs.length,2,'replacing one frame must not append a third reference');
assert.equal(apiSession.draft.refs.find(r=>r.slot===0).src,'/other.png');
console.log(JSON.stringify({boundWorkflowMedia:'passed',staleMentions:'passed',duplicateIdentity:'passed',acceptedSubmissionClearing:'passed',immutableHistory:'passed',draftAndJobUsage:'passed',annotationUsage:'passed'}));
