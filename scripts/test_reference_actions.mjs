import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {outputActions,outputActionMarkup,removeOutputs,restoreOutputs} from '../public/output-actions.js';
import {referenceShelfMarkup,cloneEdits,selectionPath,installReferenceShelf,toggleReferenceShelf,legacyStrokesToRegions,regionEditorOptions,referenceToolMarkup} from '../public/reference-editor.js';
import {cloneDraft} from '../public/advanced.js';
import {assetReferences} from '../public/workspace-media.js';
import {MASK_ENCODING,canReuseReferenceUpload,referenceUploadParts,referenceUploadForm} from '../public/reference-upload.js';

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
const tile={closest:selector=>selector==='.api-reference-tile'?tile:null};
const add={closest:()=>null};
const hoverDeck=()=>{shelf.emit('pointerenter');row.emit('pointerover',{target:tile});};
shelf.emit('pointerenter');row.emit('pointerover',{target:add});await settle();
assert(!expanded(),'hovering the folded add button never moves it out from under the pointer');
shelf.emit('focusin',{target:add});assert(!expanded(),'keyboard focus on add must also leave it still');
shelf.emit('pointerleave');
hoverDeck();row.emit('pointerout',{target:tile,relatedTarget:add});row.emit('pointerover',{target:add});await settle();
assert(!expanded(),'moving from the deck to add cancels the pending expansion');shelf.emit('pointerleave');
hoverDeck();assert(!expanded(),'a passing pointer does not instantly unfold');
await settle();assert(expanded(),'hover unfolds after the Jimeng delay');assert(!shelf.classList.contains('pinned'));
row.emit('pointerover',{target:add});await settle();assert(expanded(),'the expanded add item stays reachable');
assert.equal(toggleReferenceShelf(shelf),true,'explicit expand pins an already hovered deck');
shelf.emit('pointerleave');assert(expanded(),'pinned expansion survives pointer exit');
assert.equal(toggleReferenceShelf(shelf),false);hoverDeck();await settle();assert(!expanded(),'explicit folding wins over hover');
shelf.emit('pointerleave');hoverDeck();await settle();assert(expanded(),'hover resumes after leaving the shelf');
shelf.emit('pointerleave');assert(!expanded(),'transient expansion ends when leaving the reference group');
hoverDeck();shelf.emit('pointerleave');await settle();assert(!expanded(),'leaving cancels a pending expansion');
shelf.emit('focusin',{target:tile});assert(expanded(),'keyboard focus on an image can unfold references');
shelf.emit('focusout',{relatedTarget:null});assert(!expanded(),'leaving keyboard focus folds transient expansion');
cleanup();hoverDeck();await settle();assert(!expanded(),'disposed shelves no longer react');

const edited={...refs[0],referenceEdits:{autoCutout:true,regions:[{kind:'rect',x:.1,y:.2,width:.3,height:.4}],cutouts:[]}};
const draft={refs:[edited]},copy=cloneDraft(draft),geometry=cloneEdits(edited.referenceEdits);
copy.refs[0].referenceEdits.regions[0].x=.8;geometry.regions.length=0;
assert.equal(edited.referenceEdits.regions[0].x,.1,'later editing must not alter a historical snapshot');
const calls=[],ctx={beginPath(){},rect(...args){calls.push(args)}};
selectionPath(ctx,edited.referenceEdits.regions[0],1000,500);assert.deepEqual(calls,[[100,100,300,200]]);
assert.equal(assetReferences({id:'matte'},[{id:'session',draft:{refs:[{id:'图片1',cutoutAssetId:'matte'}]},jobs:[]}]).length,1,'automatic matte is protected while referenced');

// Imported old brush and circular one-point strokes retain original-pixel geometry.
const strokes=[{size:24,points:[[250,100],[400,200]],erase:false},{size:40,points:[[600,250]],erase:true}],legacyBefore=JSON.stringify(strokes);
const migrated=legacyStrokesToRegions(strokes,1000,500);
assert.deepEqual(migrated,[{kind:'brush',size:.048,points:[[.25,.2],[.4,.4]],erase:false},{kind:'brush',size:.08,points:[[.6,.5]],erase:true}]);
const pathCalls=[],brushCtx={beginPath(){},moveTo(...args){pathCalls.push(['move',...args]);},lineTo(...args){pathCalls.push(['line',...args]);}};
selectionPath(brushCtx,migrated[0],1000,500);assert.equal(brushCtx.lineWidth,24);assert.deepEqual(pathCalls,[['move',250,100],['line',400,200]]);
pathCalls.length=0;selectionPath(brushCtx,migrated[1],1000,500);assert.equal(brushCtx.lineWidth,40);assert.deepEqual(pathCalls,[['move',600,250],['line',600.01,250]]);
assert.equal(JSON.stringify(strokes),legacyBefore,'migration never alters a saved historical annotation');
assert.throws(()=>legacyStrokesToRegions(strokes,0,500),/原图尺寸/);assert.throws(()=>legacyStrokesToRegions([{size:4,points:[[NaN,2]]}],100,100),/历史标注/);

const schemas=JSON.parse(readFileSync(new URL('../public/workflow-interfaces.json',import.meta.url),'utf8')).workflows;
for(const id of ['local-card-15','local-card-86','local-card-131']){
 const options=regionEditorOptions(schemas[id].annotation);assert.deepEqual(options.allowedTools,['region']);assert.equal(options.requireRegion,true);
 const markup=referenceToolMarkup(options.allowedTools);assert(markup.includes('data-ref-tool="region"'));assert(!markup.includes('data-ref-tool="strength"'));assert(!markup.includes('data-ref-tool="cutout"'));
}
assert.equal(regionEditorOptions(schemas['local-card-2'].annotation),null,'visual annotation retains its own explicit semantics');
assert.equal(schemas['local-card-133'].annotation,null);assert.equal(schemas['local-card-92'].annotation,null);
for(const id of ['local-card-86','local-card-131'])assert.match(schemas[id].annotation.help,/未选区域保留原图/);

// Run the production Save handler with supplied canvas pixels to verify its gate.
// Rendering correctness still needs the real browser; this checks Save control flow.
const editorSource=readFileSync(new URL('../public/reference-editor.js',import.meta.url),'utf8'),saveStart=editorSource.indexOf("q('[data-ref-save]').onclick=async()=>{"),saveEnd=editorSource.indexOf("modal.addEventListener('cancel'",saveStart),saveHandler=editorSource.slice(saveStart,saveEnd).trim();
async function regionSaveGate({alpha=255,region=false,maskAlpha=0,dirty=true}){
 let closed=0,saved=0;const error={textContent:''},surface={alpha},target={drawImage(){surface.alpha=maskAlpha;},getImageData(){return {data:Uint8ClampedArray.from([120,80,50,surface.alpha])};}};
 const gate=vm.createContext({q:()=>error,busy:false,requireRegion:true,canvas:{width:1,height:1},mask:{},document:{createElement:()=>({getContext:()=>target})},drawForeground:()=>{surface.alpha=alpha;},maskFor:()=>({}),edits:{regions:region?[{kind:'rect',x:0,y:0,width:1,height:1}]:[],cutouts:[]},isDirty:()=>dirty,modal:{close(){closed++;}},setBusy(){},imageSignature:()=>1,initialEdits:0,canvasBlob:async()=>new Blob(['pixels']),cloneEdits,strength:75,onSave:async()=>{saved++;}});
 vm.runInContext(saveHandler,gate);await gate.q('[data-ref-save]').onclick();return {closed,saved,error:error.textContent};
}
assert.match((await regionSaveGate({})).error,/请先框选/);assert.equal((await regionSaveGate({})).saved,0,'empty opaque sources cannot be saved as required regions');
assert.match((await regionSaveGate({region:true,maskAlpha:255})).error,/请先框选/,'a fully erased selection is still empty');
assert.equal((await regionSaveGate({region:true})).saved,1,'a nonempty rendered mask can reach the save callback');
assert.equal((await regionSaveGate({alpha:0,dirty:false})).closed,1,'an imported alpha mask remains usable without a new brush gesture');

// Exercise the actual app save path. Edited alpha PNG, mask and original have distinct IDs.
const app=readFileSync(new URL('../public/app.js',import.meta.url),'utf8'),start=app.indexOf('async function openReferenceEditor('),end=app.indexOf('\nfunction issueHTML(',start);
const sourceRef={id:'图片1',kind:'image',assetId:'original',serverAssetId:'original-server',src:'blob:original',annotationMode:'mask',annotationStrokes:strokes};
const originalSnapshot=cloneDraft({refs:[sourceRef]}),session={draft:{refs:[sourceRef]}},workspace={assets:[{id:'original',src:'blob:original'}]};
let editorConfig,saves=0,serial=0;
const context=vm.createContext({active:()=>session,workspace,editReference:async config=>{editorConfig=config;},File:globalThis.File,refreshComposer(){},toast(){},saveWorkspace:async()=>{saves++;},transientAsset:async file=>{const a={id:'edited-'+(++serial),src:'blob:edited-'+serial,blob:file};workspace.assets.push(a);return a;}});
vm.runInContext(app.slice(start,end),context);
const options=regionEditorOptions(schemas['local-card-15'].annotation);
await context.openReferenceEditor(sourceRef,options);assert.equal(editorConfig.originalSrc,'blob:original');assert.equal(editorConfig.requireRegion,true);
await editorConfig.onSave({image:new Blob(['alpha PNG']),mask:new Blob(['mask PNG']),edits:{regions:migrated,cutouts:[]},strength:75,changed:true});
assert.equal(sourceRef.originalAssetId,'original');assert.equal(sourceRef.originalServerAssetId,'original-server');assert.equal(sourceRef.assetId,'edited-1');assert.equal(sourceRef.maskAssetId,'edited-2');assert.equal(sourceRef.maskSrc,'blob:edited-2');assert(!sourceRef.serverAssetId,'modified image must be uploaded rather than reusing the original server asset');
assert.equal(assetReferences(workspace.assets[2],[{id:'test',draft:session.draft,jobs:[]}]).length,1,'the separate mask is protected and can be rehydrated by ID');
await context.openReferenceEditor(sourceRef,options);assert.equal(editorConfig.originalSrc,'blob:original','later editing starts from original pixels, not the previously erased PNG');
assert.deepEqual(originalSnapshot.refs[0].annotationStrokes,strokes);assert(!originalSnapshot.refs[0].referenceEdits);assert.equal(saves,1);

const originalBlob=new Blob(['original RGB'],{type:'image/png'}),brokenBlob=new Blob(['transparent preview has lost RGB'],{type:'image/png'}),maskBlob=new Blob(['separate mask'],{type:'image/png'});
const mediaAssets=[{id:'original',blob:originalBlob},{id:'edited',blob:brokenBlob},{id:'mask',blob:maskBlob}],maskedRef={assetId:'edited',originalAssetId:'original',maskAssetId:'mask',annotationMode:'mask',serverAssetId:'old-broken-upload',src:'blob:broken'};
assert.equal(canReuseReferenceUpload(maskedRef),false,'old cached transparent PNG must be encoded again');
const parts=await referenceUploadParts(maskedRef,mediaAssets),form=referenceUploadForm(parts,'original.png');
assert.equal(parts.paired,true);assert.equal(parts.encoding,MASK_ENCODING);assert.equal(await form.get('file').text(),'original RGB');assert.equal(await form.get('mask').text(),'separate mask');assert.deepEqual([...form.keys()],['file','mask']);
assert.equal(canReuseReferenceUpload({...maskedRef,maskEncoding:MASK_ENCODING}),true);
const opaque=await referenceUploadParts({assetId:'original'},mediaAssets);assert.equal(opaque.paired,false);assert(!referenceUploadForm(opaque,'plain.png').has('mask'),'new plain imports preserve the ordinary upload contract');
const fetches=[];let restored=false;
const restoredParts=await referenceUploadParts({annotationMode:'mask',originalServerAssetId:'safe-original',maskSrc:'blob:expired',annotationStrokes:strokes},[],{fetchBlob:async src=>{fetches.push(src);if(src==='blob:expired')throw new Error('expired');return originalBlob;},renderMask:async(ref,blob)=>{assert.equal(blob,originalBlob);assert.equal(ref.annotationStrokes,strokes);restored=true;return maskBlob;}});
assert(restored);assert.equal(restoredParts.mask,maskBlob);assert.deepEqual(fetches,['/api/assets/safe-original/file','blob:expired']);
await assert.rejects(referenceUploadParts({...maskedRef,originalAssetId:'missing'},mediaAssets),/找不到编辑原图/);
await assert.rejects(referenceUploadParts({...maskedRef,originalAssetId:undefined,originalSrc:'blob:expired'},mediaAssets,{fetchBlob:async()=>{throw new Error('expired');}}),/编辑原图已失效/);
await assert.rejects(referenceUploadParts({...maskedRef,maskAssetId:'missing'},mediaAssets),/编辑掩膜已失效/);
console.log(JSON.stringify({directActions:'passed',videoRetention:'passed',recoverableRemoval:'passed',foldingPreservesReferences:'passed',hoverPinAndExplicitFold:'passed',geometry:'passed',immutableEdits:'passed',cutoutAssetUsage:'passed',legacyOriginalPixelMigration:'passed',strictRegionTools:'passed',requiredRegionSaveGate:'passed',savedOriginalAndMaskIdentity:'passed',originalRgbMaskPairUpload:'passed',oldMaskCacheInvalidation:'passed',lostOriginalRejected:'passed'}));
