import {rangeHint} from './control-guidance.js?v=60.1';
import {esc} from './data.js';

// One geometry for pixel totals; callers retain their existing limits and bindings.
export function megapixelControl({id,value,min,max,step='any',help,options,inputAttrs,presetAttrs}){
  const presets=(options||[0.5,1,1.5,2,4]).filter(x=>{
    const n=Number(x?.value??x),increment=Number(step),offset=(n-(min??0))/increment;
    return(min===undefined||n>=min)&&(max===undefined||n<=max)&&(!Number.isFinite(increment)||increment<=0||Math.abs(offset-Math.round(offset))<1e-6);
  });
  return `<div class="megapixel-control"><div class="megapixel-heading"><label for="${esc(id)}">百万像素</label><label class="megapixel-value"><input id="${esc(id)}" type="number" required value="${esc(value)}" ${inputAttrs} ${min!==undefined?`min="${min}"`:''} ${max!==undefined?`max="${max}"`:''} step="${step}" aria-label="自定义百万像素"><span>MP</span></label></div><div class="megapixel-presets" style="--mp-options:${Math.max(1,presets.length)}" role="group" aria-label="常用百万像素">${presets.map(x=>{const n=x?.value??x;return `<button type="button" ${presetAttrs(n)} aria-pressed="${Number(n)===Number(value)}">${esc(n)}<small>MP</small></button>`;}).join('')}</div>${rangeHint({min,max,step,help,kind:'resolution',key:'megapixels'})}</div>`;
}
