import {isTimecode,timecodeControl,syncTimecodeControls} from './timecode-control.js?v=60.1';
import {rangeHint,taskMeaning,syncTaskMeaning} from './control-guidance.js?v=60.1';
import {isProcessingDuration,processingDuration,syncProcessingDurations} from './processing-duration.js?v=60.1';
import {esc} from './data.js';
import {selectControl} from './workflow-select.js?v=60.1';
import {megapixelControl} from './parameter-controls.js?v=60.1';

export const controlValue=(d,f)=>{const saved=d.catalogValues||{};if(saved[f.id]!==undefined)return saved[f.id];const r=f.derived;if(r&&saved[r.targetId]!==undefined)return r.operation==='frames'?Number(saved[r.targetId])/r.fps:Number(saved[r.targetId])+Number(saved[r.startId]??0);return f.value;};
const value=controlValue;

function resolutionField(d,f,v,id){
 const range=f.customRange,mp=f.key==='megapixels',unit=mp?'MP':f.key==='output_pixels'?'千像素':'px';
 const options=f.options||[0.5,1,1.5,2,4].filter(x=>x>=range.min&&x<=range.max);
 const custom=`<label class="catalog-custom-number"><span>自定义</span><input id="${id}" data-catalog-field="${esc(f.id)}" type="number" required value="${esc(v)}" min="${range.min}" max="${range.max}" step="${range.step}" aria-label="自定义${esc(f.label)}"><span>${unit}</span></label>`;
 return `<div class="catalog-field catalog-resolution-field ${mp?'is-megapixels':''}"><label for="${id}">${esc(f.label)}</label><div class="catalog-preset-options" role="group" aria-label="常用${esc(f.label)}">${options.map(x=>{const raw=x?.value??x,label=x?.label??`${raw} ${unit}`;return `<button type="button" data-catalog-preset="${esc(f.id)}" data-value="${esc(raw)}" aria-pressed="${Number(raw)===Number(v)}">${esc(label)}</button>`}).join('')}${custom}</div>${rangeHint(f)}</div>`;
}
export function dimensionOptions(options,value,buttonAttrs){return options.map(option=>{const raw=String(option?.value??option),dimension=raw.match(/^(\d+)x(\d+)$/),ratio=raw.match(/(\d+):(\d+)/),label=ratio?.[0]||(option?.label??(dimension?`${dimension[1]}×${dimension[2]}`:raw)),[a,b]=dimension?[Number(dimension[1]),Number(dimension[2])]:ratio?[Number(ratio[1]),Number(ratio[2])]:[1,1],width=Math.round(a>=b?20:20*a/b),height=Math.round(b>=a?20:20*b/a),chosen=raw===String(value);return `<button type="button" class="catalog-ratio-option ${chosen?'chosen':''}" ${buttonAttrs(raw)} title="${esc(label)}" aria-pressed="${chosen}"><span class="ratio-symbol" aria-hidden="true" style="width:${width}px;height:${height}px"></span><span>${esc(label)}</span>${dimension&&option?.label&&option.label!==`${dimension[1]}×${dimension[2]}`?`<small>${dimension[1]}×${dimension[2]}</small>`:''}</button>`}).join('');}

export function controlField(d,f){const v=value(d,f),id='catalog-field-'+f.id.replace(/[^a-zA-Z0-9]/g,'-');
 if(isTimecode(f))return timecodeControl(f,v,id);
 if(isProcessingDuration(f))return processingDuration(f,v,id);
 if(f.kind==='task')return `<div class="catalog-field catalog-task-field" data-task-mode><label for="${id}">任务模式（代码）</label><input id="${id}" data-catalog-field="${esc(f.id)}" type="text" value="${esc(v)}"><small class="catalog-field-help" data-task-meaning>${esc(taskMeaning(String(v)))}</small></div>`;
 if(f.kind==='filesystem'&&f.type==='text'&&f.key!=='pattern'&&!f.options)return `<div class="catalog-field catalog-directory-field"><label for="${id}">${esc(f.label)}</label><div class="catalog-directory-input"><input id="${id}" data-catalog-field="${esc(f.id)}" type="text" value="${esc(v)}"><button type="button" data-local-directory="${esc(f.id)}" aria-label="选择${esc(f.label)}">选择文件夹</button></div><small class="catalog-field-help" data-directory-status>选择本机文件夹，或填写运行端可访问的目录。</small></div>`;
 if(f.key==='megapixels'&&f.type==='number')return `<div class="catalog-field catalog-megapixels">${megapixelControl({id,value:v,min:f.customRange?.min??f.min,max:f.customRange?.max??f.max,step:f.customRange?.step??f.step,help:f.help,options:f.options,inputAttrs:`data-catalog-field="${esc(f.id)}"`,presetAttrs:n=>`data-catalog-preset="${esc(f.id)}" data-value="${esc(n)}"`})}</div>`;
 if(f.kind==='ratio'&&f.options){const options=dimensionOptions(f.options,v,raw=>`data-catalog-choice="${esc(f.id)}" data-value="${esc(raw)}"`);const custom=f.customRange?`<label class="catalog-custom-size">自定义尺寸 <input type="text" inputmode="numeric" data-catalog-custom-size="${esc(f.id)}" value="${f.options.some(x=>String(x?.value??x)===String(v))?'':esc(String(v).replace('x','×'))}" placeholder="宽 × 高，例如 1024 × 1024" aria-label="自定义画面尺寸"></label>`:'';return `<div class="catalog-field catalog-ratio-field"><label for="${id}">${esc(f.label)}</label><input type="hidden" id="${id}" data-catalog-field="${esc(f.id)}" value="${esc(v)}"><div class="catalog-ratio-options" role="group" aria-label="${esc(f.label)}">${options}</div>${custom}${rangeHint(f)}</div>`;}
 if(f.kind==='resolution'&&f.customRange)return resolutionField(d,f,v,id);
 if(f.kind==='toggle'){return `<label class="catalog-field catalog-toggle-field"><span>${esc(f.label)}</span><input id="${id}" data-catalog-field="${esc(f.id)}" type="checkbox" ${v?'checked':''}><span class="catalog-switch-track" aria-hidden="true"></span>${f.help?`<small class="catalog-field-help">${esc(f.help)}</small>`:''}</label>`;}
 const input=f.options?selectControl({id,label:f.label,value:v,options:f.options,attrs:`data-catalog-field="${esc(f.id)}"`}):`<input id="${id}" data-catalog-field="${esc(f.id)}" type="${f.type}" ${f.type==='checkbox'?(v?'checked':''):`value="${esc(v)}"`} ${f.type==='number'?`required step="${f.step||'any'}" ${f.min!==undefined?`min="${f.min}"`:''} ${f.max!==undefined?`max="${f.max}"`:''}`:''}>`;
 return `<div class="catalog-field ${f.kind==='strength'?'catalog-strength-field':''}">${f.showLabel===false?'':`<label for="${id}">${esc(f.label)}</label>`}${input}${rangeHint(f)}</div>`;
}

export function controlSection(title,body,attrs=''){
 return body?`<section class="workflow-inline-controls" ${attrs}>${title?`<div class="wf-section-title"><strong>${esc(title)}</strong></div>`:''}${body}</section>`:'';
}
export function seedControls(fields,d,{compact=false,showTitle=true}={}){
 return `<div class="seed-settings ${compact?'seed-settings-compact':''}">${fields.map(f=>{
  const mode=d.catalogSeedModes?.[f.id]||'random',v=value(d,f);
  const input=controlField(d,{...f,showLabel:false,help:'',value:Number(v)<0?0:v}).replace('<input ',`<input aria-label="${esc(f.label)}固定值" ${mode==='random'?'disabled ':''}`);
  return `<section class="seed-setting" data-seed-setting="${esc(f.id)}">${showTitle?`<strong>${esc(f.label)}</strong>`:''}${f.help?`<small class="catalog-field-help">${esc(f.help)}</small>`:''}<div class="wf-options" role="group" aria-label="${esc(f.label)}模式"><button type="button" data-catalog-seed-mode="${esc(f.id)}" data-value="random" aria-pressed="${mode==='random'}">每次随机</button><button type="button" data-catalog-seed-mode="${esc(f.id)}" data-value="fixed" aria-pressed="${mode==='fixed'}">固定种子</button></div>${input}</section>`;
 }).join('')}</div>`;
}

// Update selection and diagrams without replacing the input being edited.
export function syncControlChoices(root,w,d){
 syncTimecodeControls(root);syncProcessingDurations(root);syncTaskMeaning(root);
 const fields=w.interface?.controls||[];
 for(const button of root.querySelectorAll('[data-catalog-preset],[data-catalog-choice]')){
  const id=button.dataset.catalogPreset||button.dataset.catalogChoice,f=fields.find(f=>f.id===id);if(!f)continue;
  const on=button.dataset.catalogPreset?Number(value(d,f))===Number(button.dataset.value):String(value(d,f))===button.dataset.value;
  button.setAttribute('aria-pressed',String(on));button.classList.toggle('chosen',on);
 }
 for(const item of root.querySelectorAll('[data-seed-setting]')){
  const id=item.dataset.seedSetting,mode=d.catalogSeedModes?.[id]||'random',f=fields.find(f=>f.id===id);
  for(const button of item.querySelectorAll('[data-catalog-seed-mode]'))button.setAttribute('aria-pressed',String(button.dataset.value===mode));
  const input=item.querySelector('[data-catalog-field]');if(input){input.disabled=mode==='random';if(mode==='fixed')input.value=value(d,f);}
 }
}
