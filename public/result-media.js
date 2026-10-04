import {I,esc} from './data.js';

export function resultMediaMarkup(output,{preview=false,label='生成结果'}={}){
 if(output.type==='text')return `<div class="text-result ${preview?'is-preview':''}"><pre>${esc(output.text||'')}</pre></div>`;
 if(output.type==='audio')return `<div class="audio-result"><span class="audio-result-mark" aria-hidden="true">${I('audio')}</span><audio src="${esc(output.src)}" controls preload="metadata" aria-label="${esc(label)}"></audio></div>`;
 if(output.type==='video')return `<video src="${esc(output.src)}" ${output.poster?`poster="${esc(output.poster)}"`:''} ${preview?'preload="metadata" muted':'controls autoplay muted'} playsinline></video>${preview?`<span class="video-play">${I('play')}</span>`:''}`;
 return `<img src="${esc(output.src)}" alt="${esc(label)}" ${preview?'loading="lazy"':''}>`;
}

export function resultExtension(output){
 const suffix=(output.src||'').split('?')[0].match(/\.([a-zA-Z0-9]+)$/)?.[1]?.toLowerCase();
 if(suffix&&['png','jpg','jpeg','webp','mp4','webm','wav','mp3','ogg','flac','m4a','txt'].includes(suffix))return suffix;
 return {image:'png',video:'mp4',audio:'wav',text:'txt'}[output.type]||'bin';
}
