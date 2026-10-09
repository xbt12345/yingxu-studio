import {esc} from './data.js';
import {selectControl} from './workflow-select.js?v=88.0';

export const isProcessingDuration=f=>f.kind==='duration'&&f.type==='number'&&f.min===0&&f.label.includes('0 为全部');
export const durationDescription=value=>Number(value)===0?'处理全部剩余视频':`从起点处理 ${Number(Number(value).toFixed(3))} 秒`;
export function processingDuration(f,value,id){
 const items=[{value:'all',label:'处理全部剩余视频'},{value:'custom',label:'指定处理时长'}];
 return `<div class="catalog-field processing-duration" data-processing-duration><label>处理时长</label>${selectControl({id:id+'-mode',label:'处理时长',value:Number(value)===0?'all':'custom',options:items,attrs:'data-duration-mode'})}<label class="duration-seconds" ${Number(value)===0?'hidden':''}><span>处理</span><input id="${id}" data-catalog-field="${esc(f.id)}" type="number" required min="${f.min}" ${f.max!==undefined?`max="${f.max}"`:''} step="${f.step||'any'}" value="${esc(value)}" aria-label="指定处理秒数"><span>秒</span></label><small class="catalog-field-help" data-duration-description>${Number(value)===0?'从起点处理至视频结尾。':durationDescription(value)}</small></div>`;
}
export function syncProcessingDurations(root){for(const box of root.querySelectorAll('[data-processing-duration]')){
 const input=box.querySelector('[data-catalog-field]'),select=box.querySelector('[data-duration-mode]'),all=Number(input.value)===0;
 if(!all)box.dataset.lastSeconds=input.value;
 select.value=all?'all':'custom';box.querySelector('.wf-select-trigger span').textContent=select.selectedOptions[0].textContent;
 box.querySelector('.duration-seconds').hidden=all;
 box.querySelector('[data-duration-description]').textContent=all?'从起点处理至视频结尾。':durationDescription(input.value);
}}
export function installProcessingDurations(){document.addEventListener('change',event=>{
 const select=event.target;if(!select.matches('[data-duration-mode]'))return;
 const box=select.closest('[data-processing-duration]'),input=box.querySelector('[data-catalog-field]');
 if(Number(input.value)>0)box.dataset.lastSeconds=input.value;
 input.value=select.value==='all'?0:box.dataset.lastSeconds||5;
 box.querySelector('.duration-seconds').hidden=select.value==='all';
 input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));
 syncProcessingDurations(box.parentElement);
});}
