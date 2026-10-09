import {esc} from './data.js';

// Only explain bounds recorded in the workflow contract. Missing is not unlimited.
export function rangeText(f){
 const r=f.guidanceRange||f.customRange||f;if(f.kind==='seed'||f.showLabel===false)return '';
 const min=Number.isFinite(r.min)?r.min:null,max=Number.isFinite(r.max)?r.max:null;
 const bounds=min!==null&&max!==null?`${min}–${max}`:min!==null?`≥ ${min}`:max!==null?`≤ ${max}`:'';
 if(!bounds)return '';
 const unit=f.unit?' '+f.unit:f.kind==='resolution'?(f.key==='megapixels'?' MP':f.key==='output_pixels'?' 千像素':' px'):f.kind==='duration'?' 秒':'';
 return `范围 ${bounds}${unit}${Number.isFinite(r.step)?` · 步长 ${r.step}`:''}`;
}
// Reviewed H3 metadata describes a frame grid, never executable expressions.
export function pythonRound(value){const low=Math.floor(value),fraction=value-low;return fraction===.5?(low%2===0?low:low+1):Math.round(value);}
export function expectedDuration(f,value=f.value){
 const recipe=f.effectiveDuration;
 if(recipe?.kind==='ltx-frame-grid'&&recipe.fps===25&&recipe.stepFrames===8&&recipe.extraFrames===1&&recipe.rounding==='floor'){
  if(!['number','string'].includes(typeof value)||typeof value==='string'&&!value.trim())return null;
  const seconds=Number(value),requested=seconds*recipe.fps+recipe.extraFrames;
  if(!Number.isFinite(seconds)||seconds<0||!Number.isSafeInteger(requested))return null;
  const frames=Math.floor((requested-recipe.extraFrames)/recipe.stepFrames)*recipe.stepFrames+recipe.extraFrames;
  return {frames,fps:recipe.fps,seconds:frames/recipe.fps};
 }
 if(recipe?.kind!=='h3-frame-grid'||recipe.fps!==24||recipe.minFrames!==5||recipe.stepFrames!==17||recipe.rounding!=='python-round')return null;
 if(!['number','string'].includes(typeof value)||typeof value==='string'&&!value.trim())return null;
 const seconds=Number(value);if(!Number.isFinite(seconds)||seconds<0||seconds*recipe.fps>Number.MAX_SAFE_INTEGER)return null;
 const requested=Math.max(recipe.minFrames,pythonRound(seconds*recipe.fps));
 const frames=requested+((recipe.minFrames-requested)%recipe.stepFrames+recipe.stepFrames)%recipe.stepFrames;
 return {frames,fps:recipe.fps,seconds:frames/recipe.fps};
}
export function expectedDurationText(f,value=f.value){const estimate=expectedDuration(f,value);return estimate?`预计生成 ${Number(estimate.seconds.toFixed(3))} 秒`:'';}
export const rangeHint=(f,value=f.value)=>{const text=[rangeText(f),f.help].filter(Boolean).join(' · '),estimate=expectedDurationText(f,value),complete=[text,estimate].filter(Boolean).join(' · ');return complete?`<small class="control-range" title="${esc(complete)}">${esc(text)}${text&&estimate?' · ':''}${estimate?`<span data-effective-duration="${esc(f.id)}">${esc(estimate)}</span>`:''}</small>`:'';};
export function syncExpectedDurations(root,fields,valueForField){
 const byId=new Map(fields.map(f=>[f.id,f]));
 for(const hint of root.querySelectorAll('[data-effective-duration]')){
  const field=byId.get(hint.dataset.effectiveDuration);if(!field)continue;
  const text=expectedDurationText(field,valueForField(field));hint.textContent=text;
  hint.parentElement?.setAttribute('title',[rangeText(field),field.help,text].filter(Boolean).join(' · '));
 }
}

export function taskMeaning(code){return ({
 r2v:'参考图生成视频，文字指定动作与场景。',
 rv2v:'参考图引导视频编辑，沿用原片动作。',
 v2v:'视频编辑：根据文字指令修改原视频。',
 t2v:'文字生成视频：根据文字描述生成画面。',
 t2i:'文字生成图片。',i2i:'图片编辑：根据文字修改原图。',r2i:'参考图生成图片。',
 i2v:'图片生成视频。',mv2v:'修改视频中的动作或姿态。',ads2v:'在视频场景中植入广告或标识。',vi2v:'将首帧的编辑结果延续到视频。'
 })[code]||'填写原工作流支持的生成或编辑代码。';}
export function syncTaskMeaning(root){for(const field of root.querySelectorAll('[data-task-mode]')){const input=field.querySelector('[data-catalog-field]');field.querySelector('[data-task-meaning]').textContent=taskMeaning(input.value);}}
