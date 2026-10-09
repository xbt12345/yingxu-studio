import {I,esc} from './data.js';

const finiteNumber=value=>{
 if(typeof value!=='number'&&typeof value!=='string'||typeof value==='string'&&!value.trim())return null;
 const fraction=typeof value==='string'?value.match(/^\s*(\d+)\s*\/\s*(\d+)\s*$/):null;
 const number=fraction?Number(fraction[2])>0?Number(fraction[1])/Number(fraction[2]):NaN:Number(value);
 return Number.isFinite(number)?number:null;
};
const displayNumber=number=>String(Number(number.toFixed(3)));

// Facts come from the saved output file. Never substitute generation inputs.
export function resultOutputFacts(output={}){
 const source=typeof output.metadata_source==='string'?output.metadata_source.trim():'';
 if(!source||/^(?:unknown|unavailable|none|input|inputs|request|estimate|estimated|workflow_inputs)$/i.test(source))return [];
 const width=finiteNumber(output.width),height=finiteNumber(output.height),duration=finiteNumber(output.duration),frameRate=finiteNumber(output.frame_rate),frameCount=finiteNumber(output.frame_count),rows=[];
 if(Number.isInteger(width)&&width>0&&Number.isInteger(height)&&height>0)rows.push({key:'resolution',label:'实际分辨率',value:`${width} × ${height}`});
 const animated=output.type==='video'||output.type==='image'&&(frameCount>1||/\.(?:gif|webp)(?:[?#]|$)/i.test(output.src||'')&&duration>0);
 if(animated&&frameRate>0)rows.push({key:'frame_rate',label:'实际帧率',value:`${displayNumber(frameRate)} FPS`});
 if(animated&&Number.isInteger(frameCount)&&frameCount>0)rows.push({key:'frame_count',label:'实际帧数',value:`${frameCount} 帧`});
 if((animated||output.type==='audio')&&duration>0)rows.push({key:'duration',label:'实际时长',value:`${displayNumber(duration)} 秒`});
 return rows;
}

export function resultOutputParametersMarkup(output,{title='作品实际参数'}={}){
 const rows=resultOutputFacts(output);if(!rows.length)return '';
 return `<section class="result-output-facts" aria-label="作品实际参数"><strong>${esc(title)}</strong><dl class="parameter-summary">${rows.map(row=>`<div><dt>${esc(row.label)}</dt><dd>${esc(row.value)}</dd></div>`).join('')}</dl></section>`;
}

export function resultMediaMarkup(output,{preview=false,label='生成结果',showFacts=false}={}){
 let media;
 if(output.type==='text')media=`<div class="text-result ${preview?'is-preview':''}"><pre>${esc(output.text||'')}</pre></div>`;
 else if(output.type==='audio')media=`<div class="audio-result"><span class="audio-result-mark" aria-hidden="true">${I('audio')}</span><audio src="${esc(output.src)}" controls preload="metadata" aria-label="${esc(label)}"></audio></div>`;
 else if(output.type==='video')media=`<video src="${esc(output.src)}" ${output.poster?`poster="${esc(output.poster)}"`:''} ${preview?'preload="metadata" muted':'controls autoplay muted'} playsinline></video>${preview?`<span class="video-play">${I('play')}</span>`:''}`;
 else media=`<img src="${esc(output.src)}" alt="${esc(label)}" ${preview?'loading="lazy"':''}>`;
 return media+(showFacts&&!preview?resultOutputParametersMarkup(output):'');
}

export function resultExtension(output){
 const suffix=(output.src||'').split('?')[0].match(/\.([a-zA-Z0-9]+)$/)?.[1]?.toLowerCase();
 if(suffix&&['png','jpg','jpeg','webp','gif','mp4','webm','wav','mp3','ogg','flac','m4a','txt'].includes(suffix))return suffix;
 return {image:'png',video:'mp4',audio:'wav',text:'txt'}[output.type]||'bin';
}
