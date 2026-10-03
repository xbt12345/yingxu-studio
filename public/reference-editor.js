import {I,esc} from './data.js?v=64.0';

const canvasBlob=canvas=>new Promise((resolve,reject)=>canvas.toBlob(blob=>blob?resolve(blob):reject(new Error('无法保存图片')),'image/png'));
export const cloneEdits=edits=>JSON.parse(JSON.stringify(edits||{regions:[],cutouts:[]}));

// All geometry is normalized to the image, independent of its displayed size.
export function selectionPath(ctx,shape,width,height){
 ctx.beginPath();
 if(shape.kind==='rect')ctx.rect(shape.x*width,shape.y*height,shape.width*width,shape.height*height);
 else if(shape.kind==='polygon'){
  shape.points.forEach((p,i)=>i?ctx.lineTo(p[0]*width,p[1]*height):ctx.moveTo(p[0]*width,p[1]*height));ctx.closePath();
 }else{
  ctx.lineWidth=shape.size*Math.min(width,height);ctx.lineCap='round';ctx.lineJoin='round';
  shape.points.forEach((p,i)=>i?ctx.lineTo(p[0]*width,p[1]*height):ctx.moveTo(p[0]*width,p[1]*height));
  if(shape.points.length===1)ctx.lineTo(shape.points[0][0]*width+.01,shape.points[0][1]*height);
 }
}
export function paintSelections(ctx,shapes,width,height){
 for(const shape of shapes){ctx.globalCompositeOperation=shape.erase?'destination-out':'source-over';selectionPath(ctx,shape,width,height);shape.kind==='brush'?ctx.stroke():ctx.fill();}
 ctx.globalCompositeOperation='source-over';
}

export async function editReference({ref,originalSrc,cutoutSrc,onSave}){
 const source=new Image();source.src=originalSrc||ref.src;await source.decode();
 const edits=cloneEdits(ref.referenceEdits),undo=[];
 edits.regions||=[];edits.cutouts||=[];
 const imageSignature=value=>JSON.stringify({regions:value.regions,cutouts:value.cutouts,autoCutout:!!value.autoCutout});
 const initialEdits=imageSignature(edits),initialStrength=Math.max(0,Math.min(100,Number(ref.referenceStrength??75)||0));
 let strength=initialStrength,strengthGesture=false;
 const modal=document.createElement('dialog');modal.className='reference-editor-dialog';modal.setAttribute('aria-label','编辑参考图');
 modal.innerHTML=`<div class="dialog-head"><h2>编辑参考图</h2><button type="button" class="icon-button" data-ref-close aria-label="关闭参考图编辑">${I('close')}</button></div><div class="reference-editor-stage"><canvas aria-label="参考图编辑画布"></canvas><div class="reference-editor-tools"><button type="button" data-ref-tool="region" aria-pressed="false">${I('region')}选定编辑区域</button><button type="button" data-ref-tool="cutout" aria-pressed="false">${I('cutout')}抠图</button><button type="button" data-ref-tool="strength" aria-pressed="false">${I('settings')}参考强度</button></div></div><div class="reference-tool-options" hidden><div class="reference-selection-options"><div class="reference-shape-tools"><button type="button" data-ref-shape="rect" aria-pressed="true">框选</button><button type="button" data-ref-shape="polygon" aria-pressed="false">圈选</button><button type="button" data-ref-shape="brush" aria-pressed="false">画笔</button><button type="button" data-ref-erase aria-pressed="false">橡皮擦</button></div><div class="reference-selection-adjustments"><label class="reference-brush-control"><span>画笔大小</span><input type="range" data-ref-size min="1" max="15" value="4" aria-label="参考图画笔大小"><output data-ref-size-value>4%</output></label><button type="button" data-ref-clear>清除选区</button></div><p data-ref-help>拖动框选要修改的区域。</p><details class="reference-precise"><summary>精确选区</summary><div>${[['x','左',10],['y','上',10],['width','宽',80],['height','高',80]].map(([key,label,value])=>`<label>${label} (%)<input type="number" min="0" max="100" step="1" value="${value}" data-ref-bound="${key}" aria-label="选区${label}百分比"></label>`).join('')}<button type="button" data-ref-apply>应用框选</button></div></details></div><div class="reference-strength-options" hidden><label>参考强度 <output>${Number(ref.referenceStrength??75)}%</output><input type="range" min="0" max="100" value="${Number(ref.referenceStrength??75)}" aria-label="参考强度"></label><div><span>0 · 自由发挥</span><span>100 · 贴近参考</span></div><p>仅保存为参考偏好，当前尚未接入生成参数。</p></div></div><div class="reference-editor-footer"><span class="reference-edit-status" role="status">${esc(ref.id)} · 未修改</span><button type="button" class="small-button" data-ref-undo>撤销</button><button type="button" class="small-button" data-ref-reset>恢复原图</button><button type="button" class="button primary" data-ref-save>保存</button></div><p class="reference-edit-error" role="alert"></p>`;
 document.body.append(modal);
 const q=s=>modal.querySelector(s),canvas=q('canvas'),ctx=canvas.getContext('2d');
 canvas.width=source.naturalWidth;canvas.height=source.naturalHeight;
 const mask=document.createElement('canvas');mask.width=canvas.width;mask.height=canvas.height;
 const mctx=mask.getContext('2d');let tool=null,shape='rect',erase=false,current=null,busy=false,foreground=null;
 const localURLs=[];
 if(cutoutSrc&&edits.autoCutout){foreground=new Image();foreground.src=cutoutSrc;try{await foreground.decode();}catch(e){modal.remove();throw e;}}
 q('.reference-shape-tools').insertAdjacentHTML('afterbegin',`<button type="button" data-ref-auto-cutout hidden>${I('cutout')}自动抠图</button>`);
 const remember=()=>{undo.push({edits:cloneEdits(edits),foreground,strength});if(undo.length>30)undo.shift();};
 const syncRange=input=>{const value=Number(input.value),min=Number(input.min),max=Number(input.max);input.style.setProperty('--reference-range-progress',((value-min)/(max-min)*100)+'%');input.setAttribute('aria-valuetext',value+'%'+(input.hasAttribute('data-ref-size')?'，相对图片短边':''));};
 const isDirty=()=>imageSignature(edits)!==initialEdits||strength!==initialStrength;
 function syncTools(){
  modal.querySelectorAll('[data-ref-shape]').forEach(b=>b.setAttribute('aria-pressed',String(!erase&&b.dataset.refShape===shape)));
  q('[data-ref-erase]').setAttribute('aria-pressed',String(erase));
  q('[data-ref-size]').disabled=busy||shape!=='brush';
  q('[data-ref-size]').title=shape==='brush'?'画笔直径，相对图片短边':'选择画笔或橡皮擦后调整大小';
  q('[data-ref-undo]').disabled=busy||!undo.length;
  q('[data-ref-clear]').disabled=busy||!(list().length||tool==='cutout'&&edits.autoCutout);
  q('[data-ref-clear]').textContent=tool==='cutout'?'清除抠图':'清除选区';
  q('[data-ref-reset]').disabled=busy||!(edits.regions.length||edits.cutouts.length||edits.autoCutout||strength!==initialStrength);
  q('[data-ref-apply]').disabled=busy||erase;
 }
 function setBusy(value,message=''){
  busy=value;modal.setAttribute('aria-busy',String(value));
  modal.querySelectorAll('button,input').forEach(e=>e.disabled=value);
  q('[data-ref-save]').textContent=value&&message==='正在保存…'?'保存中…':'保存';
  if(value)q('.reference-edit-status').textContent=message;else draw();
 }
 const maskFor=(shapes,opaque=false)=>{mctx.clearRect(0,0,mask.width,mask.height);mctx.fillStyle='#fff';mctx.strokeStyle='#fff';if(opaque)mctx.fillRect(0,0,mask.width,mask.height);paintSelections(mctx,shapes,mask.width,mask.height);return mask;};
 const list=()=>tool==='cutout'?edits.cutouts:edits.regions;
 function drawForeground(target){
  if(edits.autoCutout&&foreground){
   target.drawImage(foreground,0,0,canvas.width,canvas.height);
   for(const selection of edits.cutouts){
    const selected=maskFor([{...selection,erase:false}]);
    if(selection.erase){target.globalCompositeOperation='destination-out';target.drawImage(selected,0,0);target.globalCompositeOperation='source-over';}
    else{mctx.globalCompositeOperation='source-in';mctx.drawImage(source,0,0);mctx.globalCompositeOperation='source-over';target.drawImage(selected,0,0);}
   }
  }else{
   target.drawImage(source,0,0);if(edits.cutouts.length){target.globalCompositeOperation='destination-in';target.drawImage(maskFor(edits.cutouts,!!edits.cutouts[0].erase),0,0);target.globalCompositeOperation='source-over';}
  }
 }
 function draw(){
  ctx.clearRect(0,0,canvas.width,canvas.height);drawForeground(ctx);
  if(edits.regions.length){const selected=maskFor(edits.regions);mctx.globalCompositeOperation='source-in';mctx.fillStyle='rgba(196,162,255,.44)';mctx.fillRect(0,0,mask.width,mask.height);mctx.globalCompositeOperation='source-over';ctx.drawImage(selected,0,0);}
  if(current){ctx.save();ctx.strokeStyle='#d8c3ff';ctx.fillStyle='rgba(196,162,255,.25)';ctx.setLineDash([8,6]);ctx.lineWidth=Math.max(2,canvas.width/500);selectionPath(ctx,current,canvas.width,canvas.height);current.kind==='brush'?ctx.stroke():(ctx.fill(),ctx.stroke());ctx.restore();}
  syncEditorState();
 }
 function syncEditorState(){
  q('.reference-strength-options input').value=strength;q('.reference-strength-options output').textContent=strength+'%';
  modal.querySelectorAll('input[type="range"]').forEach(syncRange);q('[data-ref-size-value]').textContent=q('[data-ref-size]').value+'%';
  syncTools();if(!busy)q('.reference-edit-status').textContent=ref.id+' · '+(isDirty()?'有修改，尚未保存':'未修改');
 }
 function setTool(value){q('.reference-edit-error').textContent='';tool=tool===value?null:value;current=null;q('.reference-tool-options').hidden=!tool;q('.reference-selection-options').hidden=tool==='strength';q('.reference-strength-options').hidden=tool!=='strength';q('[data-ref-auto-cutout]').hidden=tool!=='cutout';modal.querySelectorAll('[data-ref-tool]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.refTool===tool)));q('[data-ref-help]').textContent=tool==='cutout'?'自动分离主体；画笔保留或补回主体，橡皮擦去除背景。':'选中区域用于局部修改；画笔大小按图片短边计算。';canvas.classList.toggle('editing',!!tool&&tool!=='strength');draw();}
 const point=e=>{const box=canvas.getBoundingClientRect();return[Math.max(0,Math.min(1,(e.clientX-box.left)/box.width)),Math.max(0,Math.min(1,(e.clientY-box.top)/box.height))];};
 canvas.onpointerdown=e=>{if(!tool||tool==='strength'||busy)return;e.preventDefault();canvas.setPointerCapture(e.pointerId);const p=point(e);current=shape==='rect'?{kind:'rect',x:p[0],y:p[1],width:0,height:0,start:p,erase}:{kind:shape,points:[p],size:Number(q('[data-ref-size]').value)/100,erase};draw();};
 canvas.onpointermove=e=>{if(!current)return;const p=point(e);if(current.kind==='rect'){const start=current.start;current.x=Math.min(p[0],start[0]);current.y=Math.min(p[1],start[1]);current.width=Math.abs(p[0]-start[0]);current.height=Math.abs(p[1]-start[1]);}else current.points.push(p);draw();};
 function finish(){if(!current)return;const valid=current.kind==='rect'?current.width>.002&&current.height>.002:current.kind==='polygon'?current.points.length>=3:current.points.length>0;if(valid){remember();delete current.start;list().push(current);}current=null;draw();}
 canvas.onpointerup=finish;canvas.onpointercancel=()=>{current=null;draw();};
 modal.addEventListener('click',e=>{
  if(busy)return;const b=e.target.closest('button');if(!b)return;
  if(b.hasAttribute('data-ref-close'))modal.close();
  if(b.dataset.refTool)setTool(b.dataset.refTool);
  if(b.dataset.refShape){shape=b.dataset.refShape;erase=false;syncTools();}
  if(b.hasAttribute('data-ref-erase')){shape='brush';erase=true;syncTools();}
  if(b.hasAttribute('data-ref-undo')&&undo.length){const previous=undo.pop();for(const key of Object.keys(edits))delete edits[key];Object.assign(edits,previous.edits);foreground=previous.foreground;strength=previous.strength;strengthGesture=false;q('.reference-edit-error').textContent='';draw();}
  if(b.hasAttribute('data-ref-clear')){remember();list().length=0;if(tool==='cutout')edits.autoCutout=false;current=null;draw();}
  if(b.hasAttribute('data-ref-reset')){remember();edits.regions=[];edits.cutouts=[];edits.autoCutout=false;strength=initialStrength;current=null;q('.reference-edit-error').textContent='';draw();}
  if(b.hasAttribute('data-ref-apply')){const values=Object.fromEntries([...modal.querySelectorAll('[data-ref-bound]')].map(input=>[input.dataset.refBound,Number(input.value)/100]));if(Object.values(values).some(v=>!Number.isFinite(v)||v<0||v>1)||!values.width||!values.height||values.x+values.width>1||values.y+values.height>1){q('.reference-edit-error').textContent='选区需要落在图片范围内，宽和高不能为零。';return;}q('.reference-edit-error').textContent='';remember();list().push({kind:'rect',...values,erase});draw();}
 });
 q('[data-ref-auto-cutout]').onclick=async()=>{
  if(busy)return;setBusy(true,'正在分离主体…');q('.reference-edit-error').textContent='';
  try{
   const original=document.createElement('canvas');original.width=canvas.width;original.height=canvas.height;original.getContext('2d').drawImage(source,0,0);
   const body=new FormData();body.append('file',await canvasBlob(original),'reference.png');const bounds=edits.cutouts.filter(s=>s.kind==='rect'&&!s.erase).at(-1);body.append('bounds',JSON.stringify(bounds||{}));
   const response=await fetch('/api/image/cutout',{method:'POST',body,signal:AbortSignal.timeout(45000)});if(!response.ok){const error=await response.json().catch(()=>({}));throw new Error(error.detail||'自动抠图暂不可用，可使用圈选。');}
   const url=URL.createObjectURL(await response.blob()),image=new Image();localURLs.push(url);image.src=url;await image.decode();remember();foreground=image;edits.autoCutout=true;edits.cutouts=[];draw();
  }catch(e){q('.reference-edit-error').textContent=e.name==='TimeoutError'?'抠图超时，可缩小图片或使用圈选。':e.message;}finally{setBusy(false);}
 };
 q('[data-ref-size]').oninput=e=>{syncRange(e.target);q('[data-ref-size-value]').textContent=e.target.value+'%';};
 const strengthInput=q('.reference-strength-options input');
 strengthInput.oninput=e=>{const value=Number(e.target.value);if(value!==strength){if(!strengthGesture)remember();strengthGesture=true;strength=value;syncEditorState();}};
 strengthInput.onchange=strengthInput.onblur=()=>{strengthGesture=false;};
 q('[data-ref-save]').onclick=async()=>{
  if(busy)return;if(!isDirty()){modal.close();return;}setBusy(true,'正在保存…');q('.reference-edit-error').textContent='';
  try{
   if(imageSignature(edits)===initialEdits){await onSave({settingsOnly:true,edits:cloneEdits(edits),strength});modal.close();return;}
   const result=document.createElement('canvas');result.width=canvas.width;result.height=canvas.height;const resultCtx=result.getContext('2d');drawForeground(resultCtx);
   let cutout=null;if(edits.autoCutout&&foreground){const base=document.createElement('canvas');base.width=canvas.width;base.height=canvas.height;base.getContext('2d').drawImage(foreground,0,0,base.width,base.height);cutout=await canvasBlob(base);}
   let regionMask=null;if(edits.regions.length){regionMask=await canvasBlob(maskFor(edits.regions));resultCtx.globalCompositeOperation='destination-out';resultCtx.drawImage(mask,0,0);resultCtx.globalCompositeOperation='source-over';}
   await onSave({image:await canvasBlob(result),mask:regionMask,cutout,edits:cloneEdits(edits),strength,changed:!!(edits.autoCutout||edits.regions.length||edits.cutouts.length)});modal.close();
  }catch(e){q('.reference-edit-error').textContent=e.message||'保存失败，请重试。';}finally{setBusy(false);}
 };
 modal.addEventListener('cancel',e=>{if(busy)e.preventDefault();});modal.addEventListener('close',()=>{localURLs.forEach(URL.revokeObjectURL);modal.remove();},{once:true});draw();modal.showModal();
}

export function referenceShelfMarkup(refs,{pinned=false}={}){
 // Jimeng's public reference group: 48 × 64 cards, a 4 px gap and one upload item.
 const foldedAngles=[8,-4,22,-8,8,-4,7,-4,8,-8,22,-4],openAngles=[8,-5,8,-5,8,-4,8,-4,8,-5,8,-5];
 return `<div class="api-reference-shelf ${pinned?'pinned expanded':''}" style="--reference-row-width:${(refs.length+1)*52+12}px" aria-label="本次参考素材，${refs.length}项"><div class="api-reference-head"><button type="button" data-action="reference-stack" aria-label="${pinned?'收起全部参考图':'全部展开参考图'}" aria-expanded="${pinned}" title="${pinned?'收起参考图':'固定展开参考图'}">${I(pinned?'down':'expand')}<span>${pinned?'收起':'全部展开'}</span></button></div><div class="api-reference-row">${refs.map((r,i)=>`<div class="api-reference-tile" style="--ref-index:${i};--folded-angle:${foldedAngles[i%12]}deg;--open-angle:${openAngles[i%12]}deg"><button type="button" data-preview-ref="${esc(r.id)}" aria-label="${r.kind==='image'?'编辑':'查看'}${esc(r.id)}">${r.kind==='image'?`<img src="${esc(r.src)}" alt="${esc(r.id)}">`:r.kind==='video'?`<video src="${esc(r.src)}" ${r.poster?`poster="${esc(r.poster)}"`:''} muted preload="metadata" playsinline></video>`:I('audio')}<span class="api-ref-label">${esc(r.id)}</span></button><button type="button" class="api-reference-remove" data-remove="${esc(r.id)}" aria-label="移除${esc(r.id)}">${I('close')}</button>${r.referenceEdits?.autoCutout||r.referenceEdits?.regions?.length||r.referenceEdits?.cutouts?.length?'<i class="reference-edited" title="已编辑"></i>':''}</div>`).join('')}<button type="button" class="api-reference-add" style="--ref-index:${refs.length}" data-action="add-reference" aria-haspopup="dialog" aria-expanded="false" aria-label="添加参考素材" title="添加参考素材">${I('plus')}</button></div></div>`;
}

function expandShelf(shelf,expanded){
 shelf.classList.toggle('expanded',expanded);
 const button=shelf.querySelector('[data-action="reference-stack"]');
 button.setAttribute('aria-expanded',String(expanded));
 const pinned=shelf.classList.contains('pinned');
 button.setAttribute('aria-label',pinned?'收起全部参考图':'全部展开参考图');
 button.title=pinned?'收起参考图':'固定展开参考图';
 button.innerHTML=I(pinned?'down':'expand')+'<span>'+(pinned?'收起':'全部展开')+'</span>';
}

// An explicit fold wins over hover until the pointer or keyboard leaves the shelf.
export function toggleReferenceShelf(shelf){
 const expanded=!shelf.classList.contains('pinned');
 shelf.classList.toggle('pinned',expanded);shelf.foldedByUser=!expanded;
 shelf.hideReferencePreview?.();
 expandShelf(shelf,expanded);return expanded;
}

export function installReferenceShelf(shelf){
 if(!shelf)return()=>{};
 const row=shelf.querySelector('.api-reference-row'),layout=shelf.closest('.api-prompt-layout');
 const doc=shelf.ownerDocument,win=doc?.defaultView;
 let enterTimer,previewTimer,preview=null,previewTarget=null,pointerInside=false,disposed=false;
 const hidePreview=()=>{clearTimeout(previewTimer);previewTarget=null;preview?.remove();preview=null;};
 shelf.hideReferencePreview=hidePreview;
 const measure=()=>{
  if(!layout)return;
  const width=Math.max(80,layout.getBoundingClientRect().right-shelf.getBoundingClientRect().left);
  shelf.style.setProperty('--reference-available-width',width+'px');
  const requested=parseFloat(shelf.style.getPropertyValue('--reference-row-width'));
  row.classList.toggle('scrollable',requested>width);
  refreshPreview();
 };
 const observer=win?.ResizeObserver?new win.ResizeObserver(measure):null;
 if(layout)observer?.observe(layout);measure();
 const showPreview=button=>{
  hidePreview();const media=button?.querySelector('img,video');if(!media||!doc)return;
  previewTarget=button;
  previewTimer=setTimeout(()=>{
   if(disposed||previewTarget!==button||!shelf.classList.contains('expanded'))return;
   const box=button.getBoundingClientRect(),width=Math.min(180,win.innerWidth-24);
   const ratio=media.naturalWidth&&media.naturalHeight?media.naturalWidth/media.naturalHeight:media.videoWidth&&media.videoHeight?media.videoWidth/media.videoHeight:1;
   const height=Math.min(width/ratio,280,Math.max(96,win.innerHeight-40));
   // Prefer the space above a bottom composer; flip below when the top has less room.
   const above=box.top-12>=height+2||box.top>win.innerHeight-box.bottom;
   const top=above?Math.max(12,box.top-height-14):Math.min(win.innerHeight-height-14,box.bottom+12);
   const left=Math.max(12,Math.min(box.left+box.width/2-width/2,win.innerWidth-width-12));
   preview=doc.createElement('div');preview.className='reference-hover-preview';preview.setAttribute('aria-hidden','true');
   preview.style.cssText=`left:${left}px;top:${top}px;width:${width}px;--reference-preview-height:${height}px`;
   const large=media.cloneNode(false);large.removeAttribute('id');large.removeAttribute('style');large.removeAttribute('title');
   if(large.tagName==='VIDEO'){large.muted=true;large.controls=false;large.autoplay=true;large.loop=true;}
   preview.append(large);doc.body.append(preview);
  },350);
 };
 function refreshPreview(){const button=previewTarget;hidePreview();if(button&&(button.matches(':hover')||button.contains(doc.activeElement)))showPreview(button);}
 const enter=()=>{pointerInside=true;};
 const leave=()=>{
  pointerInside=false;clearTimeout(enterTimer);shelf.foldedByUser=false;hidePreview();
  if(!shelf.classList.contains('pinned')&&!shelf.matches(':focus-within')){expandShelf(shelf,false);row.scrollLeft=0;}
 };
 const over=e=>{
  // Only the image deck unfolds. Hovering the add button must leave its hit area still.
  const tile=e.target.closest?.('.api-reference-tile');
  clearTimeout(enterTimer);
  if(tile&&!shelf.foldedByUser&&!shelf.classList.contains('expanded'))enterTimer=setTimeout(()=>{if(!disposed&&pointerInside)expandShelf(shelf,true);},100);
  const button=e.target.closest?.('[data-preview-ref]');if(button&&!button.contains(e.relatedTarget))showPreview(button);
 };
 const out=e=>{clearTimeout(enterTimer);if(previewTarget&&!previewTarget.contains(e.relatedTarget))hidePreview();};
 const focus=e=>{
  clearTimeout(enterTimer);
  if(e.target.closest?.('.api-reference-tile')&&!shelf.foldedByUser){expandShelf(shelf,true);const button=e.target.closest?.('[data-preview-ref]');if(button)showPreview(button);}
 };
 const blur=e=>{hidePreview();if(shelf.contains(e.relatedTarget))return;shelf.foldedByUser=false;if(!shelf.classList.contains('pinned')&&!pointerInside){expandShelf(shelf,false);row.scrollLeft=0;}};
 const escape=e=>{if(e.key==='Escape'){e.preventDefault();clearTimeout(enterTimer);hidePreview();const button=shelf.querySelector('[data-action="reference-stack"]');if(shelf.classList.contains('pinned'))button.click();shelf.foldedByUser=true;expandShelf(shelf,false);button.focus();}};
 shelf.addEventListener('pointerenter',enter);shelf.addEventListener('pointerleave',leave);
 row.addEventListener('pointerover',over);row.addEventListener('pointerout',out);
 shelf.addEventListener('focusin',focus);shelf.addEventListener('focusout',blur);shelf.addEventListener('keydown',escape);shelf.addEventListener('click',hidePreview);
 win?.addEventListener('scroll',refreshPreview,true);win?.addEventListener('resize',measure);
 return()=>{disposed=true;clearTimeout(enterTimer);hidePreview();observer?.disconnect();delete shelf.hideReferencePreview;shelf.removeEventListener('pointerenter',enter);shelf.removeEventListener('pointerleave',leave);row.removeEventListener('pointerover',over);row.removeEventListener('pointerout',out);shelf.removeEventListener('focusin',focus);shelf.removeEventListener('focusout',blur);shelf.removeEventListener('keydown',escape);shelf.removeEventListener('click',hidePreview);win?.removeEventListener('scroll',refreshPreview,true);win?.removeEventListener('resize',measure);};
}
