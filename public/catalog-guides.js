import {syncMultiCamera} from './multi-camera.js?v=60.1';
import {dragCamera,nudgeZoom} from './camera-motion.js?v=60.1';
import {cameraOrbitMarkup,updateCameraOrbit} from './camera-orbit.js?v=60.1';
// Direct-manipulation guides for two source-specific ComfyUI inputs.
const clamp=(n,min,max)=>Math.max(min,Math.min(max,n));
const control=(w,key)=>w?.interface?.controls?.find(f=>f.key===key);
const number=(w,d,key)=>Number(d.catalogValues?.[control(w,key)?.id]??control(w,key)?.value??0);
const padExtent=n=>60*(1-Math.exp(-Math.max(0,n)/600));
const padValue=n=>Math.min(16384,Math.max(0,Math.round(-600*Math.log(1-clamp(n,0,59.98)/60)/8)*8));
const setAttr=(element,values)=>{if(element)for(const [key,val] of Object.entries(values))element.setAttribute(key,String(val));};

function writeValue(panel,w,d,key,v){
 const f=control(w,key);if(!f)return;
 d.catalogValues||={};d.catalogValues[f.id]=v;applyOutpaintValue(w,d,key,v);
 for(const input of panel.querySelectorAll('[data-catalog-field]'))if(input.dataset.catalogField===f.id||f.kind==='outpaint')input.value=d.catalogValues[input.dataset.catalogField]??input.value;
}

export function cameraGuide(w,d){return cameraOrbitMarkup(number(w,d,'horizontal_angle'),number(w,d,'vertical_angle'),number(w,d,'zoom'));}
export function syncCameraGuide(root,w,d){syncMultiCamera(root,w,d);const guide=root.querySelector('[data-camera-guide]');if(guide&&w?.id==='local-card-14')updateCameraOrbit(guide,number(w,d,'horizontal_angle'),number(w,d,'vertical_angle'),number(w,d,'zoom'));}
export const outpaintLinked=(d,axis)=>d.catalogUi?.outpaintLinks?.[axis]!==false;
export function applyOutpaintValue(w,d,key,v){
 const f=control(w,key);if(w?.id!=='local-card-13'||f?.kind!=='outpaint')return;
 d.catalogValues||={};d.catalogValues[f.id]=v;
 const axis=['left','right'].includes(key)?'horizontal':'vertical',mate={left:'right',right:'left',top:'bottom',bottom:'top'}[key];
 if(outpaintLinked(d,axis)){const opposite=control(w,mate);if(opposite)d.catalogValues[opposite.id]=v;}
}

export function outpaintGuide(w,d){
 const names={left:'向左',top:'向上',right:'向右',bottom:'向下'};
 return '<div class="outpaint-links">'+[['horizontal','左右'],['vertical','上下']].map(([axis,label])=>'<button type="button" data-outpaint-link="'+axis+'" aria-pressed="'+outpaintLinked(d,axis)+'" title="点击切换'+label+'联动">'+label+'<span>'+ (outpaintLinked(d,axis)?'已绑定 · 解除':'未绑定 · 绑定')+'</span></button>').join('')+'</div><div class="catalog-outpaint-guide" data-outpaint-guide>'+
  '<svg data-outpaint-map viewBox="0 0 360 220" role="img" aria-label="拖动四边调整扩展范围">'+
  '<rect x="50" y="10" width="260" height="200" rx="10" fill="#15131b" stroke="#514658" stroke-dasharray="4 6"/>'+
  '<rect data-outpaint-area rx="5" fill="#73578e55" stroke="#c5a7df" stroke-width="2"/>'+
  '<rect x="110" y="70" width="140" height="80" rx="3" fill="#322c3c" stroke="#d9c6eb" stroke-width="2"/>'+
  '<text x="180" y="114" text-anchor="middle" fill="#eee5f6" font-size="12">原图</text>'+
  Object.entries(names).map(([side,label])=>'<circle data-outpaint-handle="'+side+'" r="11" tabindex="0" role="button" aria-label="拖动'+label+'扩展范围" fill="#f0ba68" stroke="#251c29" stroke-width="3"/>').join('')+
  '</svg><div class="outpaint-readout">'+Object.entries(names).map(([side,label])=>'<span>'+label+' <strong data-outpaint-value="'+side+'">0</strong> px</span>').join('')+
  '</div><small>拖动四边改变扩展范围；下方可精确填写像素。</small></div>';
}

export function syncOutpaintGuide(root,w,d){
 const guide=root.querySelector('[data-outpaint-guide]');if(!guide||w?.id!=='local-card-13')return;
 for(const input of root.querySelectorAll('[data-catalog-field]')){const f=w.interface.controls.find(f=>f.id===input.dataset.catalogField);if(f?.kind==='outpaint')input.value=number(w,d,f.key);}
 for(const button of root.querySelectorAll('[data-outpaint-link]')){const axis=button.dataset.outpaintLink,on=outpaintLinked(d,axis);button.setAttribute('aria-pressed',String(on));button.querySelector('span').textContent=on?'已绑定 · 解除':'未绑定 · 绑定';}
 const left=number(w,d,'left'),top=number(w,d,'top'),right=number(w,d,'right'),bottom=number(w,d,'bottom');
 const l=110-padExtent(left),t=70-padExtent(top),r=250+padExtent(right),b=150+padExtent(bottom);
 setAttr(guide.querySelector('[data-outpaint-area]'),{x:l,y:t,width:r-l,height:b-t});
 const labels={left:'向左',top:'向上',right:'向右',bottom:'向下'};
 for(const [side,x,y,n] of [['left',l,110,left],['top',180,t,top],['right',r,110,right],['bottom',180,b,bottom]]){
  setAttr(guide.querySelector('[data-outpaint-handle="'+side+'"]'),{cx:x,cy:y,'aria-label':labels[side]+' '+n+' 像素；方向键调整'});
  guide.querySelector('[data-outpaint-value="'+side+'"]').textContent=String(n);
 }
}

export function installCatalogVisualGuides({getContext,onCommit}){
 let dragging=null;
 const point=(svg,e)=>{const p=svg.createSVGPoint();p.x=e.clientX;p.y=e.clientY;const local=p.matrixTransform(svg.getScreenCTM().inverse());return {x:local.x,y:local.y};};
 const update=(kind,side,e)=>{
  const {w,d,panel}=getContext();if(!panel||!w)return;
  const svg=panel.querySelector(kind==='camera'?'[data-camera-map]':'[data-outpaint-map]');if(!svg)return;
  const p=point(svg,e);
  if(kind==='camera'){
   const next=dragCamera(dragging,p.x-dragging.start.x,p.y-dragging.start.y);
   for(const [key,value] of [['horizontal_angle',next.h],['vertical_angle',next.v],['zoom',next.z]])writeValue(panel,w,d,key,value);
   syncCameraGuide(panel,w,d);
  }else{
   const extent=side==='left'?110-p.x:side==='right'?p.x-250:side==='top'?70-p.y:p.y-150;
   writeValue(panel,w,d,side,padValue(extent));
   syncOutpaintGuide(panel,w,d);
  }
 };
 document.addEventListener('pointerdown',e=>{
  const handle=e.target.closest?.('[data-camera-handle],[data-outpaint-handle]');
  if(!handle)return;
  const {w,d,panel}=getContext(),kind=handle.hasAttribute('data-camera-handle')?'camera':'outpaint';
  if(!panel?.contains(handle)||w?.id!==(kind==='camera'?'local-card-14':'local-card-13'))return;
  dragging={handle,kind,side:handle.dataset.outpaintHandle,pointerId:e.pointerId,start:point(handle.closest('svg'),e),h:number(w,d,'horizontal_angle'),v:number(w,d,'vertical_angle'),z:number(w,d,'zoom')};
  panel.querySelector('[data-camera-guide]')?.classList.add('is-dragging');
  handle.setPointerCapture(e.pointerId);e.preventDefault();update(kind,dragging.side,e);
 });
 document.addEventListener('pointermove',e=>{if(dragging&&e.pointerId===dragging.pointerId)update(dragging.kind,dragging.side,e);});
 const finish=e=>{if(!dragging||e.pointerId!==dragging.pointerId)return;getContext().panel?.querySelector('[data-camera-guide]')?.classList.remove('is-dragging');dragging=null;onCommit();};
 document.addEventListener('pointerup',finish);
 document.addEventListener('pointercancel',finish);
 document.addEventListener('wheel',e=>{
  const map=e.target.closest?.('[data-camera-map]');if(!map)return;
  const {w,d,panel}=getContext();if(w?.id!=='local-card-14'||!panel?.contains(map))return;
  e.preventDefault();writeValue(panel,w,d,'zoom',nudgeZoom(number(w,d,'zoom'),e.deltaY<0?.3:-.3));syncCameraGuide(panel,w,d);onCommit();
 },{passive:false});
 document.addEventListener('input',e=>{
  if(!e.target.matches?.('[data-camera-zoom],[data-camera-elevation]'))return;
  const {w,d,panel}=getContext();if(w?.id!=='local-card-14'||!panel?.contains(e.target))return;
  writeValue(panel,w,d,e.target.hasAttribute('data-camera-elevation')?'vertical_angle':'zoom',Number(e.target.value));syncCameraGuide(panel,w,d);
 });
 document.addEventListener('change',e=>{if(e.target.matches?.('[data-camera-zoom],[data-camera-elevation]'))onCommit();});
 document.addEventListener('click',e=>{
  const link=e.target.closest('[data-outpaint-link]'),preset=e.target.closest('[data-camera-preset]');if(!link&&!preset)return;
  const {w,d,panel}=getContext();if(!panel?.contains(link||preset))return;
  if(link&&w?.id==='local-card-13'){const axis=link.dataset.outpaintLink;d.catalogUi={...(d.catalogUi||{}),outpaintLinks:{...(d.catalogUi?.outpaintLinks||{}),[axis]:!outpaintLinked(d,axis)}};syncOutpaintGuide(panel,w,d);}
  if(preset&&w?.id==='local-card-14'){writeValue(panel,w,d,'horizontal_angle',Number(preset.dataset.cameraPreset));syncCameraGuide(panel,w,d);}
  onCommit();
 });
 document.addEventListener('keydown',e=>{
  const handle=e.target.closest?.('[data-camera-handle],[data-outpaint-handle]');
  if(!handle||!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key))return;
  const {w,d,panel}=getContext();if(!panel?.contains(handle))return;
  e.preventDefault();
  if(handle.hasAttribute('data-camera-handle')){
   const key=e.key==='ArrowLeft'||e.key==='ArrowRight'?'horizontal_angle':'vertical_angle';
   const delta=e.key==='ArrowLeft'?-1:e.key==='ArrowRight'?1:e.key==='ArrowUp'?1:-1;
   writeValue(panel,w,d,key,clamp(number(w,d,key)+delta*(key==='horizontal_angle'?5:1),key==='horizontal_angle'?0:-30,key==='horizontal_angle'?360:60));
   syncCameraGuide(panel,w,d);
  }else{
   const side=handle.dataset.outpaintHandle;
   const outward={left:'ArrowLeft',right:'ArrowRight',top:'ArrowUp',bottom:'ArrowDown'}[side];
   const inward={left:'ArrowRight',right:'ArrowLeft',top:'ArrowDown',bottom:'ArrowUp'}[side];
   if(e.key!==outward&&e.key!==inward)return;
   const delta=e.key===outward?8:-8;
   writeValue(panel,w,d,side,clamp(number(w,d,side)+delta,0,16384));
   syncOutpaintGuide(panel,w,d);
  }
  onCommit();
 });
}
