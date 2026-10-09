import {esc} from './data.js';

export function normalizeSpeakerRegions(value,{complete=false}={}){
 let regions;
 try{regions=typeof value==='string'?JSON.parse(value):value;}catch{throw new Error('人物区域记录无效，请重新框选。');}
 if(!Array.isArray(regions)||regions.length>2)throw new Error('请分别框选音频1和音频2对应的人物。');
 const result=[0,1].map(i=>{
  const r=regions[i];if(r==null)return null;
  if(typeof r!=='object'||Array.isArray(r)||Object.keys(r).sort().join(',')!=='height,width,x,y'||['x','y','width','height'].some(k=>typeof r[k]!=='number'||!Number.isFinite(r[k])))throw new Error('人物区域需要有效的框选坐标。');
  if(r.x<0||r.y<0||r.width<=0||r.height<=0||r.x+r.width<=r.x||r.y+r.height<=r.y||r.x+r.width>1+1e-12||r.y+r.height>1+1e-12)throw new Error('人物区域不能为空或超出参考图。');
  return {...r};
 });
 if(result[0]&&result[1]&&['x','y','width','height'].every(k=>Math.abs(result[0][k]-result[1][k])<=1e-12))throw new Error('两个人物不能使用完全相同的区域，请分别框选。');
 if(complete&&result.some(r=>!r))throw new Error('请在参考图上分别框选音频1和音频2对应的人物。');
 return result;
}
export const serializeSpeakerRegions=value=>JSON.stringify(normalizeSpeakerRegions(value));
export function clearSpeakerRegionsForMedia(d,w,slotId){
 for(const f of w?.interface?.controls||[])if(f.kind==='speaker_regions'&&f.mediaSlotId===slotId){d.catalogValues||={};d.catalogValues[f.id]='[]';}
}
export function normalizedRegion(a,b){return {x:Math.min(a.x,b.x),y:Math.min(a.y,b.y),width:Math.abs(a.x-b.x),height:Math.abs(a.y-b.y)};}
export function speakerRegionsControl(d,f,v,id){
 const ref=d.refs?.find(r=>r.kind==='image'&&r.catalogSlot===f.mediaSlotId);
 let regions,error='';try{regions=normalizeSpeakerRegions(v);}catch(e){regions=[null,null];error=e.message;}
 return `<section class="catalog-field catalog-speaker-regions" data-speaker-regions data-speaker-index="0"><strong>${esc(f.label||'说话人物区域')}</strong><input type="hidden" id="${id}" data-catalog-field="${esc(f.id)}" value="${esc(JSON.stringify(regions))}"><div class="speaker-region-tools" role="group" aria-label="选择音频对应的人物">${[0,1].map(i=>`<button type="button" data-speaker-select="${i}" aria-pressed="${i===0}">人物${i+1} · 音频${i+1}</button>`).join('')}<button type="button" data-speaker-clear>清空</button></div>${ref?`<div class="speaker-region-stage" data-speaker-stage tabindex="0" role="group" aria-label="在参考图上框选说话人物；方向键移动，回车开始或结束框选，删除键清除当前人物"><img src="${esc(ref.src)}" alt="双人参考图" draggable="false"><div class="speaker-region-layer" data-speaker-layer></div><span class="speaker-region-cursor" data-speaker-cursor hidden aria-hidden="true"></span></div>`:'<div class="speaker-region-empty">先添加双人参考图，再分别框选两个人物</div>'}<small class="catalog-field-help" data-speaker-status>按音频顺序框选人物；拖动选区，或用方向键与回车</small><div class="speaker-region-numbers" role="group" aria-label="当前人物区域坐标">${[['x','左'],['y','上'],['width','宽'],['height','高']].map(([axis,label])=>`<label><span>${label} %</span><input type="number" min="${axis==='width'||axis==='height'?0.1:0}" max="100" step="0.1" data-speaker-axis="${axis}" aria-label="当前人物区域${label}百分比"></label>`).join('')}</div><p class="inline-error" data-speaker-error role="alert" ${error?'':'hidden'}>${esc(error)}</p></section>`;
}
const installed=new WeakSet(),states=new WeakMap();
const input=box=>box.querySelector('[data-catalog-field]');
const roots=root=>[...(root.matches?.('[data-speaker-regions]')?[root]:[]),...root.querySelectorAll('[data-speaker-regions]')];
function showError(box,message){const el=box.querySelector('[data-speaker-error]');el.textContent=message;el.hidden=!message;}
function draw(box,{preview,editing=false}={}){
 let regions;try{regions=normalizeSpeakerRegions(input(box).value);}catch(error){showError(box,error.message);return;}
 const index=Number(box.dataset.speakerIndex)||0,stage=box.querySelector('[data-speaker-stage]'),active=regions[index];
 const displayed=regions.map((r,i)=>preview&&i===index?preview:r),layer=box.querySelector('[data-speaker-layer]');
 if(layer)layer.innerHTML=displayed.map((r,i)=>r?`<div class="speaker-region-box is-speaker-${i+1} ${i===index?'is-selected':''}" style="left:${r.x*100}%;top:${r.y*100}%;width:${r.width*100}%;height:${r.height*100}%"><span>人物${i+1} · 音频${i+1}</span></div>`:'').join('');
 for(const b of box.querySelectorAll('[data-speaker-select]'))b.setAttribute('aria-pressed',String(Number(b.dataset.speakerSelect)===index));
 if(!editing)for(const number of box.querySelectorAll('[data-speaker-axis]')){number.value=active?Number((active[number.dataset.speakerAxis]*100).toFixed(1)):'';number.disabled=!stage;number.setCustomValidity('');}
 box.querySelector('[data-speaker-status]').textContent=regions.every(Boolean)?'已框选两个人物 · 区域顺序对应音频1、音频2':'按音频顺序框选人物；拖动选区，或用方向键与回车';
}
function commit(box,regions){try{input(box).value=serializeSpeakerRegions(regions);}catch(error){showError(box,error.message);draw(box);return false;}showError(box,'');draw(box);input(box).dispatchEvent(new Event('input',{bubbles:true}));return true;}
export function syncSpeakerRegionPickers(root){
 for(const box of roots(root)){
  if(!installed.has(box)){
   installed.add(box);const stage=box.querySelector('[data-speaker-stage]'),state={cursor:{x:.5,y:.5},anchor:null,pointer:null};states.set(box,state);
   const position=e=>{const r=stage.getBoundingClientRect();return {x:Math.max(0,Math.min(1,(e.clientX-r.left)/r.width)),y:Math.max(0,Math.min(1,(e.clientY-r.top)/r.height))};};
   const finish=point=>{const selected=Number(box.dataset.speakerIndex)||0,region=normalizedRegion(state.anchor,point);state.anchor=null;if(region.width<.005||region.height<.005){draw(box);showError(box,'请框选人物的有效区域，不能只点一下。');return;}const regions=normalizeSpeakerRegions(input(box).value);regions[selected]=region;commit(box,regions);};
   box.addEventListener('click',e=>{const select=e.target.closest('[data-speaker-select]');if(select){box.dataset.speakerIndex=select.dataset.speakerSelect;state.anchor=null;showError(box,'');draw(box);return;}if(e.target.closest('[data-speaker-clear]')){state.anchor=null;commit(box,[null,null]);}});
   box.addEventListener('input',e=>{if(!e.target.matches('[data-speaker-axis]'))return;e.stopPropagation();e.target.setCustomValidity('');const numbers=[...box.querySelectorAll('[data-speaker-axis]')];for(const n of numbers)n.setCustomValidity('');if(numbers.some(n=>n.value===''||!n.validity.valid)){const incomplete=normalizeSpeakerRegions(input(box).value);incomplete[Number(box.dataset.speakerIndex)||0]=null;input(box).value=serializeSpeakerRegions(incomplete);showError(box,'请完整填写人物区域的四个坐标。');input(box).dispatchEvent(new Event('input',{bubbles:true}));return;}const region=Object.fromEntries(numbers.map(n=>[n.dataset.speakerAxis,Number(n.value)/100])),regions=normalizeSpeakerRegions(input(box).value);regions[Number(box.dataset.speakerIndex)||0]=region;try{normalizeSpeakerRegions(regions);input(box).value=serializeSpeakerRegions(regions);showError(box,'');draw(box,{editing:true});input(box).dispatchEvent(new Event('input',{bubbles:true}));}catch(error){const incomplete=normalizeSpeakerRegions(input(box).value);incomplete[Number(box.dataset.speakerIndex)||0]=null;input(box).value=serializeSpeakerRegions(incomplete);e.target.setCustomValidity(error.message);showError(box,error.message);input(box).dispatchEvent(new Event('input',{bubbles:true}));}});
   if(stage){
    const image=stage.querySelector('img'),fitImage=()=>{if(image.naturalWidth&&image.naturalHeight)stage.style.maxWidth=Math.min(500,320*image.naturalWidth/image.naturalHeight)+'px';};image.addEventListener('load',fitImage);fitImage();
    stage.addEventListener('pointerdown',e=>{if(e.button!==0)return;const image=stage.querySelector('img');if(!image.complete||!image.naturalWidth){showError(box,'参考图尚未读取，请稍后框选。');return;}e.preventDefault();stage.focus({preventScroll:true});state.anchor=position(e);state.pointer=e.pointerId;stage.setPointerCapture(e.pointerId);});
    stage.addEventListener('pointermove',e=>{if(state.anchor&&state.pointer===e.pointerId)draw(box,{preview:normalizedRegion(state.anchor,position(e)),editing:true});});
    stage.addEventListener('pointerup',e=>{if(state.anchor&&state.pointer===e.pointerId){finish(position(e));state.pointer=null;stage.releasePointerCapture(e.pointerId);}});
    stage.addEventListener('pointercancel',()=>{state.anchor=null;state.pointer=null;draw(box);});
    stage.addEventListener('keydown',e=>{
     if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Enter'].includes(e.key)&&(!image.complete||!image.naturalWidth)){e.preventDefault();showError(box,'参考图尚未读取，请稍后框选。');return;}
     if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key)){e.preventDefault();const step=e.shiftKey?.001:.01;if(e.key==='ArrowLeft')state.cursor.x=Math.max(0,state.cursor.x-step);if(e.key==='ArrowRight')state.cursor.x=Math.min(1,state.cursor.x+step);if(e.key==='ArrowUp')state.cursor.y=Math.max(0,state.cursor.y-step);if(e.key==='ArrowDown')state.cursor.y=Math.min(1,state.cursor.y+step);const cursor=box.querySelector('[data-speaker-cursor]');cursor.hidden=false;cursor.style.left=state.cursor.x*100+'%';cursor.style.top=state.cursor.y*100+'%';if(state.anchor)draw(box,{preview:normalizedRegion(state.anchor,state.cursor),editing:true});}
     if(e.key==='Enter'){e.preventDefault();if(state.anchor)finish({...state.cursor});else state.anchor={...state.cursor};}
     if(e.key==='Escape'){state.anchor=null;draw(box);}
     if(e.key==='Delete'||e.key==='Backspace'){e.preventDefault();const regions=normalizeSpeakerRegions(input(box).value);regions[Number(box.dataset.speakerIndex)||0]=null;commit(box,regions);}
    });
   }
  }
  const state=states.get(box);draw(box,{editing:!!state.anchor||box.contains(document.activeElement)&&document.activeElement.matches('[data-speaker-axis]')});
 }
}
