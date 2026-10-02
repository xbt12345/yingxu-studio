import {esc} from './data.js';

// Only explain bounds recorded in the workflow contract. Missing is not unlimited.
export function rangeText(f){
 const r=f.guidanceRange||f.customRange||f;if(f.kind==='seed'||f.showLabel===false)return '';
 const min=Number.isFinite(r.min)?r.min:null,max=Number.isFinite(r.max)?r.max:null;
 const bounds=min!==null&&max!==null?`${min}–${max}`:min!==null?`≥ ${min}`:max!==null?`≤ ${max}`:'';
 if(!bounds)return '';
 const unit=f.kind==='resolution'?(f.key==='megapixels'?' MP':f.key==='output_pixels'?' 千像素':' px'):f.kind==='duration'?' 秒':'';
 return `范围 ${bounds}${unit}${Number.isFinite(r.step)?` · 步长 ${r.step}`:''}`;
}
export const rangeHint=f=>{const text=[rangeText(f),f.help].filter(Boolean).join(" · ");return text?`<small class="control-range" title="${esc(text)}">${esc(text)}</small>`:'';};

export function taskMeaning(code){return ({
 r2v:'参考图生成视频，文字指定动作与场景。',
 rv2v:'参考图引导视频编辑，沿用原片动作。',
 v2v:'视频编辑：根据文字指令修改原视频。',
 t2v:'文字生成视频：根据文字描述生成画面。',
 t2i:'文字生成图片。',i2i:'图片编辑：根据文字修改原图。',r2i:'参考图生成图片。',
 i2v:'图片生成视频。',mv2v:'修改视频中的动作或姿态。',ads2v:'在视频场景中植入广告或标识。',vi2v:'将首帧的编辑结果延续到视频。'
 })[code]||'填写原工作流支持的生成或编辑代码。';}
export function syncTaskMeaning(root){for(const field of root.querySelectorAll('[data-task-mode]')){const input=field.querySelector('[data-catalog-field]');field.querySelector('[data-task-meaning]').textContent=taskMeaning(input.value);}}
