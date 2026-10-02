import {I,esc} from './data.js?v=64.0';
// One action order for result overlays and the full-size viewer.
export function outputActions(output,{library=false,selected=false}={}){
 return [
  {action:'reference',icon:'reference',label:'用作参考'},
  ...(output.type==='image'?[{action:'to-video',icon:'video',label:'生成视频'}]:[]),
  {action:'save-output',icon:'assets',label:'保存到素材库'},
  {action:'publish-output',icon:'star',label:output.published?'取消发布':'发布到灵感库',pressed:!!output.published},
  ...(!library?[{action:'select-result',icon:'compare',label:selected?'取消对比':'加入对比',pressed:selected}]:[]),
  {action:'download',icon:'download',label:'下载文件'},
  ...(library?[{action:'remove-work',icon:'trash',label:'移除作品'}]:[])
 ];
}

export function removeOutputs(rows,ids,now=Date.now()){
 const selected=new Set(ids),changed=[];
 for(const {o} of rows)if(selected.has(o.id)&&!o.removedAt){
  o.removedAt=now;changed.push(o.id);
 }
 return changed;
}
export function restoreOutputs(rows,ids){
 const selected=new Set(ids),changed=[];
 for(const {o} of rows)if(selected.has(o.id)&&o.removedAt){delete o.removedAt;changed.push(o.id);}
 return changed;
}

export function outputActionMarkup(o,{icons=false,library=false,selected=false}={}){
 return outputActions(o,{library,selected}).map(item=>{
  const cls=icons?'output-action icon-button':'small-button',label=esc(item.label),icon=I(item.icon);
  if(item.action==='download')return `<a class="${cls} control" href="${esc(o.src)}" download aria-label="${label}" title="${label}">${icon}${icons?'':label}</a>`;
  const select=icons&&item.action==='select-result';
  return `<button type="button" class="${cls}${select?' select-output':''}${item.action==='remove-work'?' danger-action':''}${item.pressed?' active':''}" ${select?`data-select="${esc(o.id)}"`:`data-action="${item.action}" data-id="${esc(o.id)}"`} aria-label="${label}" title="${label}" ${item.pressed!==undefined?`aria-pressed="${item.pressed}"`:''}>${icon}${icons?'<span class="output-action-label">'+label+'</span>':label}</button>`;
 }).join('');
}

// Keep actions on the visible media, including centered portraits inside a wide stage.
export function installOutputActionPlacement(root){
 const place=output=>{
  const media=output?.querySelector('img,video');
  if(!media||!output.querySelector('.output-action-bar'))return;
  const width=media.naturalWidth||media.videoWidth,height=media.naturalHeight||media.videoHeight;
  let insetRight=0,insetBottom=0,visibleWidth=output.clientWidth;
  if(width&&height&&getComputedStyle(media).objectFit==='contain'){
   const box=media.getBoundingClientRect(),stage=output.getBoundingClientRect();
   const scale=Math.min(box.width/width,box.height/height);
   visibleWidth=width*scale;
   insetRight=Math.max(0,stage.right-box.right+(box.width-visibleWidth)/2-output.clientLeft);
   insetBottom=Math.max(0,stage.bottom-box.bottom+(box.height-height*scale)/2-output.clientTop);
  }
  output.style.setProperty('--output-media-inset-right',insetRight+'px');
  output.style.setProperty('--output-media-inset-bottom',insetBottom+'px');
  output.style.setProperty('--output-media-width',visibleWidth+'px');
 };
 const target=e=>place(e.target.closest?.('.output'));
 const resize=()=>root.querySelectorAll('.output').forEach(place);
 root.addEventListener('pointerover',target);root.addEventListener('focusin',target);
 root.addEventListener('load',target,true);root.addEventListener('loadedmetadata',target,true);
 const observer=new ResizeObserver(resize);observer.observe(root);
 window.addEventListener('resize',resize);resize();
 return()=>{observer.disconnect();window.removeEventListener('resize',resize);root.removeEventListener('pointerover',target);root.removeEventListener('focusin',target);root.removeEventListener('load',target,true);root.removeEventListener('loadedmetadata',target,true);};
}
