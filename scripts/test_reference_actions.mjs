import assert from 'node:assert/strict';
import {outputActions,outputActionMarkup,removeOutputs,restoreOutputs} from '../public/output-actions.js';
import {referenceShelfMarkup,cloneEdits,selectionPath,installReferenceShelf,toggleReferenceShelf} from '../public/reference-editor.js';
import {cloneDraft} from '../public/advanced.js';
import {assetReferences} from '../public/workspace-media.js';

const image={id:'image-1',type:'image',src:'example.png',published:true};
const video={id:'video-1',type:'video',src:'example.mp4'};
for(const o of [image,video])for(const library of [false,true]){
 const actions=outputActions(o,{library}),names=actions.map(a=>a.action);
 assert.equal(new Set(names).size,names.length,'viewer actions must be unique');
 assert(!names.includes('view'),'the image itself opens the viewer');
 assert(names.includes('save-output'),'both media kinds can be retained in the material vault');
 assert.equal(names.includes('to-video'),o.type==='image');
 assert.equal(names.includes('remove-work'),library);
 assert(!outputActionMarkup(o,{library,icons:!library}).includes('data-context'));
}
assert.match(outputActionMarkup(image,{icons:true}),/data-select="image-1"/);
assert(!outputActionMarkup(image,{icons:true}).includes('data-action="select-result"'),'one click has one selection handler');

const snapshot={refs:[{id:'图片1',assetId:'original'}],prompt:'preserve the original'};
const rows=[{o:image,j:{snapshot}},{o:video,j:{snapshot}}],before=JSON.stringify(snapshot);
assert.deepEqual(removeOutputs(rows,[image.id,video.id],123),[image.id,video.id]);
assert.equal(JSON.stringify(snapshot),before);assert.equal(image.src,'example.png');assert.equal(image.published,true);
assert.deepEqual(removeOutputs(rows,[image.id],124),[],'removing an already removed work is idempotent');
assert.deepEqual(restoreOutputs(rows,[image.id]),[image.id]);assert(!image.removedAt);assert.equal(video.removedAt,123);
restoreOutputs(rows,[video.id]);assert.equal(JSON.stringify(snapshot),before);

const refs=Array.from({length:6},(_,i)=>({id:'图片'+(i+1),kind:'image',src:`image-${i}.png`}));
const folded=referenceShelfMarkup(refs);
assert(folded.includes('aria-expanded="false"'));assert(folded.includes('添加参考素材'));
assert.equal((folded.match(/data-preview-ref=/g)||[]).length,6,'folding never discards references');
assert(referenceShelfMarkup(refs,{pinned:true}).includes('aria-expanded="true"'));

// Hover is temporary and anchored to the deck; explicit expansion pins the row above.
function surface(){
 const classes=new Set(),listeners=new Map();
 return{classList:{contains:k=>classes.has(k),toggle(k,on){on??=!classes.has(k);on?classes.add(k):classes.delete(k);return on;}},
 addEventListener(k,f){listeners.set(k,f);},removeEventListener(k,f){if(listeners.get(k)===f)listeners.delete(k);},emit(k,event={}){listeners.get(k)?.(event);},matches(){return false;}};
}
const shelf=surface(),row=surface(),button={setAttribute(){},focus(){}};
shelf.querySelector=()=>button;shelf.closest=()=>null;shelf.contains=x=>x===row||x===button;
const query=shelf.querySelector;shelf.querySelector=q=>q==='.api-reference-row'?row:query(q);
row.contains=x=>x===row;
const cleanup=installReferenceShelf(shelf),expanded=()=>shelf.classList.contains('expanded');
const settle=()=>new Promise(resolve=>setTimeout(resolve,120));
shelf.emit('pointerenter');assert(!expanded(),'a passing pointer does not instantly unfold');
await settle();assert(expanded(),'hover unfolds after the Jimeng delay');assert(!shelf.classList.contains('pinned'));
assert.equal(toggleReferenceShelf(shelf),true,'explicit expand pins an already hovered deck');
shelf.emit('pointerleave');assert(expanded(),'pinned expansion survives pointer exit');
assert.equal(toggleReferenceShelf(shelf),false);shelf.emit('pointerenter');await settle();assert(!expanded(),'explicit folding wins over hover');
shelf.emit('pointerleave');shelf.emit('pointerenter');await settle();assert(expanded(),'hover resumes after leaving the shelf');
shelf.emit('pointerleave');assert(!expanded(),'transient expansion ends when leaving the reference group');
shelf.emit('pointerenter');shelf.emit('pointerleave');await settle();assert(!expanded(),'leaving cancels a pending expansion');
shelf.emit('focusin',{target:row});assert(expanded(),'keyboard focus can unfold references');
shelf.emit('focusout',{relatedTarget:null});assert(!expanded(),'leaving keyboard focus folds transient expansion');
cleanup();shelf.emit('pointerenter');await settle();assert(!expanded(),'disposed shelves no longer react');

const edited={...refs[0],referenceEdits:{autoCutout:true,regions:[{kind:'rect',x:.1,y:.2,width:.3,height:.4}],cutouts:[]}};
const draft={refs:[edited]},copy=cloneDraft(draft),geometry=cloneEdits(edited.referenceEdits);
copy.refs[0].referenceEdits.regions[0].x=.8;geometry.regions.length=0;
assert.equal(edited.referenceEdits.regions[0].x,.1,'later editing must not alter a historical snapshot');
const calls=[],ctx={beginPath(){},rect(...args){calls.push(args)}};
selectionPath(ctx,edited.referenceEdits.regions[0],1000,500);assert.deepEqual(calls,[[100,100,300,200]]);
assert.equal(assetReferences({id:'matte'},[{id:'session',draft:{refs:[{id:'图片1',cutoutAssetId:'matte'}]},jobs:[]}]).length,1,'automatic matte is protected while referenced');
console.log(JSON.stringify({directActions:'passed',videoRetention:'passed',recoverableRemoval:'passed',foldingPreservesReferences:'passed',hoverPinAndExplicitFold:'passed',geometry:'passed',immutableEdits:'passed',cutoutAssetUsage:'passed'}));
