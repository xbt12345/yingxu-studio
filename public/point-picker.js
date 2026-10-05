import {esc} from './data.js';

export const POINT_LIMIT=12;
export const emptyPointSelection=()=>({positive:[],negative:[]});

// The stored coordinates describe the processed frame, never the uncropped source.
export function normalizePointSelection(raw){
 const points=raw===undefined||raw===null||raw===''?emptyPointSelection():typeof raw==='string'?JSON.parse(raw):raw;
 if(!points||typeof points!=='object'||Array.isArray(points)||Object.keys(points).some(key=>!['positive','negative'].includes(key)))throw new Error('主体点位格式有误，请清空后重新选择。');
 const result=emptyPointSelection();
 for(const kind of ['positive','negative']){
  if(!Array.isArray(points[kind]))throw new Error('主体点位格式有误，请清空后重新选择。');
  if(points[kind].length>POINT_LIMIT)throw new Error(`保留与排除点各最多 ${POINT_LIMIT} 个。`);
  result[kind]=points[kind].map(point=>{
   if(!point||!Number.isFinite(point.x)||!Number.isFinite(point.y)||point.x<0||point.x>1||point.y<0||point.y>1)throw new Error('主体点位必须位于画面内，请重新选择。');
   return {x:Math.round(point.x*1e6)/1e6,y:Math.round(point.y*1e6)/1e6};
  });
 }
 return result;
}
export const serializePointSelection=raw=>JSON.stringify(normalizePointSelection(raw));

// LayerStyle scales the long side, truncates the short side, then rounds both up.
export function sourceFrameSize(width,height,sourceMultiple=0){
 if(![width,height,sourceMultiple].every(Number.isFinite)||width<=0||height<=0||sourceMultiple<0||!Number.isInteger(sourceMultiple))throw new Error('视频尺寸无效。');
 const round=n=>sourceMultiple?Math.max(sourceMultiple,Math.floor(n/sourceMultiple+.5)*sourceMultiple):n;
 return {width:round(width),height:round(height)};
}
export function processingFrameSize(width,height,longSide=1024,multiple=32,sourceMultiple=0){
 if(![width,height,longSide,multiple].every(Number.isFinite)||width<=0||height<=0||longSide<=0||multiple<=0||!Number.isInteger(multiple))throw new Error('视频尺寸或处理边长无效。');
 ({width,height}=sourceFrameSize(width,height,sourceMultiple));
 const scale=longSide/Math.max(width,height),round=n=>Math.ceil(Math.max(1,Math.floor(n))/multiple)*multiple;
 return {width:round(width*scale),height:round(height*scale)};
}
// Core ImageScaleBy uses Python's ties-to-even round, with crop disabled.
// In card51 the preceding dimensions are multiples of32 and postScale=.5,
// so the result is a multiple of16; LTXVPreprocess's even-edge crop is a no-op.
export function postScaledFrameSize(width,height,postScale=1){
 if(![width,height,postScale].every(Number.isFinite)||width<=0||height<=0||postScale<=0)throw new Error('点选处理缩放无效。');
 const round=n=>{const floor=Math.floor(n),fraction=n-floor;return fraction===.5?(floor%2?floor+1:floor):Math.round(n);};
 const size={width:round(width*postScale),height:round(height*postScale)};
 if(size.width<=0||size.height<=0)throw new Error('点选处理尺寸无效。');
 return size;
}
export function coverCropRect(width,height,targetWidth,targetHeight){
 if(![width,height,targetWidth,targetHeight].every(n=>Number.isFinite(n)&&n>0))throw new Error('预览尺寸无效。');
 const scale=Math.max(targetWidth/width,targetHeight/height),cropWidth=targetWidth/scale,cropHeight=targetHeight/scale;
 return {x:(width-cropWidth)/2,y:(height-cropHeight)/2,width:cropWidth,height:cropHeight};
}
export function previewPointInSource(point,crop){return {x:crop.x+point.x*crop.width,y:crop.y+point.y*crop.height};}
export function processingPreviewGeometry(width,height,recipe,longSide=recipe.longSide??1024){
 const source=sourceFrameSize(width,height,recipe.sourceMultiple??0),layerTarget=processingFrameSize(source.width,source.height,longSide,recipe.multiple??32),target=postScaledFrameSize(layerTarget.width,layerTarget.height,recipe.postScale??1);
 const first=coverCropRect(width,height,source.width,source.height),second=coverCropRect(source.width,source.height,layerTarget.width,layerTarget.height);
 const crop={x:first.x+second.x/source.width*first.width,y:first.y+second.y/source.height*first.height,width:second.width/source.width*first.width,height:second.height/source.height*first.height};
 const scale=Math.max(layerTarget.width/source.width,layerTarget.height/source.height);
 return {source,layerTarget,target,crop,framePercent:{width:source.width*scale/layerTarget.width*100,height:source.height*scale/layerTarget.height*100}};
}
export function pointFromPointer(clientX,clientY,rect){
 if(!rect||rect.width<=0||rect.height<=0)throw new Error('预览尚未准备好。');
 return {x:Math.min(1,Math.max(0,(clientX-rect.left)/rect.width)),y:Math.min(1,Math.max(0,(clientY-rect.top)/rect.height))};
}
export function previewFrameTime(recipe,skipFrames=0,duration=Infinity){
 if(!Number.isSafeInteger(skipFrames)||skipFrames<0)throw new Error('跳过帧数需要填写非负整数。');
 if(skipFrames===0)return 0;
 if(!Number.isFinite(recipe.frameRate)||recipe.frameRate<=0)throw new Error('缺少已确认的工作流帧率，不能预览指定帧。');
 const time=skipFrames/recipe.frameRate;
 if(Number.isFinite(duration)&&time>=duration)throw new Error('跳过帧数超出视频时长，请减少帧数。');
 return time;
}
export function clearPointsForMedia(d,w,slotId){
 for(const field of w?.interface?.controls||[]){
  if(field.kind==='points'&&field.mediaSlotId===slotId){d.catalogValues||={};d.catalogValues[field.id]=serializePointSelection(emptyPointSelection());}
 }
}

export function pointPickerControl(d,f,value,id){
 const ref=(d.refs||[]).find(r=>r.catalogSlot===f.mediaSlotId&&r.kind==='video'&&r.src&&r.available!==false),recipe=f.previewRecipe||{},longSide=d.catalogValues?.[recipe.longSideControlId]??recipe.longSide??1024,skipFrames=d.catalogValues?.[recipe.skipControlId]??recipe.skipFrames??0;
 // Invalid saved input stays visible as an error; it is never silently coerced.
 let stored,error='';try{stored=serializePointSelection(value);}catch(err){stored=String(value??'');error=err.message;}
 return `<section class="catalog-field catalog-point-picker" data-point-picker data-point-mode="positive" data-point-recipe="${esc(JSON.stringify({...recipe,longSide,skipFrames}))}"><strong>${esc(f.label||'选择跟踪主体')}</strong><input type="hidden" id="${id}" data-catalog-field="${esc(f.id)}" value="${esc(stored)}"><div class="point-picker-tools" role="group" aria-label="点选方式"><button type="button" data-point-mode="positive" aria-pressed="true"><i class="point-positive-dot" aria-hidden="true"></i>保留主体</button><button type="button" data-point-mode="negative" aria-pressed="false"><i class="point-negative-dot" aria-hidden="true"></i>排除区域</button><button type="button" data-point-clear>清空</button><span data-point-count>0 / 0</span></div>${ref?`<div class="point-picker-stage" data-point-stage tabindex="0" role="group" aria-label="视频起始帧点选；方向键移动位置，回车添加；点击已有点移除"><div class="point-picker-source-frame" data-point-source-frame><video src="${esc(ref.src)}" muted playsinline preload="auto" aria-hidden="true" tabindex="-1"></video></div><div class="point-picker-layer" data-point-layer></div><span class="point-picker-cursor" data-point-cursor hidden aria-hidden="true"></span><span class="point-picker-loading" data-point-loading>正在读取视频起始帧…</span></div>`:'<div class="point-picker-empty">先添加原视频，再点击起始帧选择主体</div>'}<small class="catalog-field-help">绿点保留，红点排除；点击点可移除，每类最多 ${POINT_LIMIT} 个。</small>${f.id==='1095:points'?'<small class="catalog-field-help">选区用于跟踪与生成引导；其他区域也可能变化。</small>':''}<p class="point-picker-error" data-point-error role="alert" ${error?'':'hidden'}>${esc(error)}</p></section>`;
}

const installed=new WeakSet();
const nodeState=new WeakMap();
const roots=root=>[...(root.matches?.('[data-point-picker]')?[root]:[]),...root.querySelectorAll('[data-point-picker]')];
const hiddenInput=box=>box.querySelector('[data-catalog-field]');
function showError(box,message){const error=box.querySelector('[data-point-error]');error.textContent=message;error.hidden=!message;}
function getPoints(box){return normalizePointSelection(hiddenInput(box).value);}
function drawPoints(box){
 let points;try{points=getPoints(box);showError(box,'');}catch(error){showError(box,error.message);box.querySelector('[data-point-clear]').disabled=false;return;}
 const serialized=JSON.stringify(points),mode=box.dataset.pointMode||'positive',state=nodeState.get(box)||{};
 const layer=box.querySelector('[data-point-layer]');
 if(layer&&state.serialized!==serialized){
  layer.innerHTML=['positive','negative'].flatMap(kind=>points[kind].map((p,index)=>`<button type="button" class="point-picker-dot is-${kind}" data-point-remove="${kind}" data-point-index="${index}" style="left:${p.x*100}%;top:${p.y*100}%" aria-label="移除${kind==='positive'?'保留':'排除'}点 ${index+1}" title="点击移除">${index+1}</button>`)).join('');
 }
 for(const button of box.querySelectorAll('button[data-point-mode]'))button.setAttribute('aria-pressed',String(button.dataset.pointMode===mode));
 box.querySelector('[data-point-count]').textContent=`保留 ${points.positive.length} · 排除 ${points.negative.length}`;
 box.querySelector('[data-point-clear]').disabled=!points.positive.length&&!points.negative.length;
 nodeState.set(box,{...state,serialized});
}
function writePoints(box,points){
 const input=hiddenInput(box);input.value=serializePointSelection(points);drawPoints(box);
 input.dispatchEvent(new Event('input',{bubbles:true}));
}
function syncFrame(box){
 const video=box.querySelector('video'),stage=box.querySelector('[data-point-stage]');if(!video||!stage)return;
 if(!video.videoWidth||!video.videoHeight)return;
 const recipe=JSON.parse(box.dataset.pointRecipe),scope=box.closest('.catalog-editor')||box.closest('.library-example')||box;
 const sizeInput=[...scope.querySelectorAll('[data-catalog-field]')].find(n=>n.dataset.catalogField===recipe.longSideControlId);
 const skipInput=[...scope.querySelectorAll('[data-catalog-field]')].find(n=>n.dataset.catalogField===recipe.skipControlId);
 const longSide=sizeInput?Number(sizeInput.value):Number(recipe.longSide??1024),loading=box.querySelector('[data-point-loading]');
 try{
  const geometry=processingPreviewGeometry(video.videoWidth,video.videoHeight,recipe,longSide),size=geometry.target;
  const targetTime=previewFrameTime(recipe,skipInput?Number(skipInput.value):Number(recipe.skipFrames??0),video.duration),state=nodeState.get(box)||{};
  nodeState.set(box,{...(nodeState.get(box)||{}),targetTime});
  if(state.targetTime!==undefined&&state.targetTime!==targetTime)writePoints(box,emptyPointSelection());
  stage.style.aspectRatio=`${size.width} / ${size.height}`;stage.style.maxWidth=`${Math.min(500,280*size.width/size.height)}px`;
  const sourceFrame=box.querySelector('[data-point-source-frame]');sourceFrame.style.width=geometry.framePercent.width+'%';sourceFrame.style.height=geometry.framePercent.height+'%';
  stage.dataset.pointWidth=size.width;stage.dataset.pointHeight=size.height;
  video.pause();if(Math.abs(video.currentTime-targetTime)>.001&&!video.seeking)video.currentTime=targetTime;
  const ready=video.readyState>=2&&!video.seeking&&Math.abs(video.currentTime-targetTime)<=.001;
  stage.dataset.pointReady=String(ready);loading.hidden=ready;
  if((!sizeInput||sizeInput.validity.valid)&&(!skipInput||skipInput.validity.valid)){getPoints(box);showError(box,'');}
 }catch(error){stage.dataset.pointReady='false';loading.hidden=true;showError(box,error.message);}
}
export function syncPointPickers(root){for(const box of roots(root)){drawPoints(box);syncFrame(box);}}
function addPoint(box,point){
 const stage=box.querySelector('[data-point-stage]');if(stage?.dataset.pointReady!=='true'){showError(box,'视频起始帧尚未就绪，请稍候。');return;}
 let points;try{points=getPoints(box);}catch(error){showError(box,error.message);return;}
 const mode=box.dataset.pointMode||'positive';if(points[mode].length>=POINT_LIMIT){showError(box,`此类点已满 ${POINT_LIMIT} 个，请先移除一个点。`);return;}
 points[mode].push(point);writePoints(box,points);stage.focus({preventScroll:true});
}
export function installPointPickers(root=document){
 if(installed.has(root))return;installed.add(root);syncPointPickers(root);
 root.addEventListener('loadedmetadata',event=>{const box=event.target.closest?.('[data-point-picker]');if(box)syncFrame(box);},true);
 root.addEventListener('loadeddata',event=>{const box=event.target.closest?.('[data-point-picker]');if(box)syncFrame(box);},true);
 root.addEventListener('seeked',event=>{const box=event.target.closest?.('[data-point-picker]');if(box)syncFrame(box);},true);
 root.addEventListener('error',event=>{const box=event.target.closest?.('[data-point-picker]');if(box&&event.target.tagName==='VIDEO'){box.querySelector('[data-point-loading]').hidden=true;box.querySelector('[data-point-stage]').dataset.pointReady='false';showError(box,'无法读取原视频，请重新选择可播放的视频。');}},true);
 root.addEventListener('input',event=>{
  if(!event.target.dataset.catalogField)return;
  const own=event.target.closest('[data-point-picker]');if(own){drawPoints(own);return;}
  for(const box of roots(event.target.closest('.catalog-editor')||event.target.closest('.library-example')||root)){
   const recipe=JSON.parse(box.dataset.pointRecipe);if([recipe.longSideControlId,recipe.skipControlId].includes(event.target.dataset.catalogField))syncFrame(box);
  }
 });
 root.addEventListener('click',event=>{
  const box=event.target.closest?.('[data-point-picker]');if(!box)return;
  const mode=event.target.closest('button[data-point-mode]');if(mode){box.dataset.pointMode=mode.dataset.pointMode;drawPoints(box);return;}
  if(event.target.closest('[data-point-clear]')){writePoints(box,emptyPointSelection());return;}
  const remove=event.target.closest('[data-point-remove]');if(remove){try{const points=getPoints(box);points[remove.dataset.pointRemove].splice(Number(remove.dataset.pointIndex),1);writePoints(box,points);box.querySelector('[data-point-stage]')?.focus({preventScroll:true});}catch(error){showError(box,error.message);}return;}
  const stage=event.target.closest('[data-point-stage]');if(stage){const point=pointFromPointer(event.clientX,event.clientY,stage.getBoundingClientRect());addPoint(box,point);}
 });
 root.addEventListener('keydown',event=>{
  const stage=event.target.closest?.('[data-point-stage]');if(!stage||event.target!==stage)return;
  const box=stage.closest('[data-point-picker]'),point={x:Number(stage.dataset.cursorX??.5),y:Number(stage.dataset.cursorY??.5)};
  const moves={ArrowLeft:[-.02,0],ArrowRight:[.02,0],ArrowUp:[0,-.02],ArrowDown:[0,.02]};
  if(moves[event.key]){event.preventDefault();point.x=Math.min(1,Math.max(0,point.x+moves[event.key][0]));point.y=Math.min(1,Math.max(0,point.y+moves[event.key][1]));stage.dataset.cursorX=point.x;stage.dataset.cursorY=point.y;const cursor=stage.querySelector('[data-point-cursor]');cursor.hidden=false;cursor.style.left=point.x*100+'%';cursor.style.top=point.y*100+'%';}
  else if(event.key==='Enter'||event.key===' '){event.preventDefault();addPoint(box,point);}
 });
}
