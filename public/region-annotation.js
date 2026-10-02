import {esc} from './data.js';

// Store strokes in original image coordinates, so exports retain exact alignment.
export async function annotateImage({src,mode='visual',help='',optional=false,initialStrokes=[],onSave}){
 const image=new Image();image.src=src;await image.decode();
 const dialog=document.createElement('dialog');dialog.className='region-dialog';
 dialog.innerHTML=`<header class="region-head"><div><strong>标注编辑区域</strong><p>${esc(help)}</p></div><button data-tool="close" aria-label="关闭">×</button></header><div class="region-toolbar"><div class="region-tool-group"><button data-tool="brush" aria-pressed="true">画笔</button><button data-tool="erase" aria-pressed="false">橡皮擦</button></div><label class="region-brush-size"><span>大小</span><input data-size aria-label="画笔大小" type="range" min="2" max="160" value="24" style="--brush-percent:14%"><output>24 px</output></label><div class="region-tool-history"><button data-tool="undo">撤销</button><button data-tool="clear">清空</button></div></div><div class="region-viewport"><div class="region-stage"><img alt="原图"><canvas aria-label="绘制编辑区域"></canvas></div></div><footer class="region-actions"><button data-tool="mask" class="region-download">下载掩膜</button><div><button data-tool="close">取消</button><button data-tool="save" class="button primary">应用标注</button></div></footer>`;
 document.body.append(dialog);dialog.querySelector('img').src=src;
 const canvas=dialog.querySelector('canvas');canvas.width=image.naturalWidth;canvas.height=image.naturalHeight;
 const ctx=canvas.getContext('2d');const strokes=initialStrokes.map(s=>({...s,points:s.points.map(p=>[...p])}));let current=null,tool='brush';
 const render=()=>{ctx.clearRect(0,0,canvas.width,canvas.height);for(const s of strokes){ctx.globalCompositeOperation=s.erase?'destination-out':'source-over';ctx.lineWidth=s.size;ctx.lineCap='round';ctx.lineJoin='round';ctx.strokeStyle='#ff465b';ctx.fillStyle='#ff465b';ctx.beginPath();ctx.moveTo(...s.points[0]);for(const point of s.points.slice(1))ctx.lineTo(...point);ctx.stroke();if(s.points.length===1){ctx.beginPath();ctx.arc(...s.points[0],s.size/2,0,2*Math.PI);ctx.fill();}}ctx.globalCompositeOperation='source-over';};
 const point=e=>{const r=canvas.getBoundingClientRect();return [(e.clientX-r.left)*canvas.width/r.width,(e.clientY-r.top)*canvas.height/r.height];};
 canvas.addEventListener('pointerdown',e=>{e.preventDefault();canvas.setPointerCapture(e.pointerId);current={erase:tool==='erase',size:Number(dialog.querySelector('[data-size]').value),points:[point(e)]};strokes.push(current);render();});
 canvas.addEventListener('pointermove',e=>{if(!current)return;current.points.push(point(e));render();});
 const end=()=>{current=null;};canvas.addEventListener('pointerup',end);canvas.addEventListener('pointercancel',end);
 dialog.querySelector('[data-size]').addEventListener('input',e=>{dialog.querySelector('output').value=e.target.value+' px';e.target.style.setProperty('--brush-percent',((Number(e.target.value)-2)/158*100)+'%');});
 const blob=c=>new Promise(resolve=>c.toBlob(resolve,'image/png'));
 async function exports(){
  const marks=ctx.getImageData(0,0,canvas.width,canvas.height);const mask=document.createElement('canvas');mask.width=canvas.width;mask.height=canvas.height;const mctx=mask.getContext('2d');const pixels=mctx.createImageData(mask.width,mask.height);
   let hasMarks=false;for(let i=0;i<pixels.data.length;i+=4){const a=marks.data[i+3];hasMarks ||= a>0;pixels.data[i]=pixels.data[i+1]=pixels.data[i+2]=a;pixels.data[i+3]=255;}mctx.putImageData(pixels,0,0);
  const annotated=document.createElement('canvas');annotated.width=canvas.width;annotated.height=canvas.height;const actx=annotated.getContext('2d');actx.drawImage(image,0,0);
  if(mode==='mask'){const original=actx.getImageData(0,0,canvas.width,canvas.height);for(let i=0;i<original.data.length;i+=4)original.data[i+3]=Math.min(original.data[i+3],255-marks.data[i+3]);actx.putImageData(original,0,0);}else{actx.globalAlpha=.65;actx.drawImage(canvas,0,0);}
   return {mask:await blob(mask),annotated:await blob(annotated),hasMarks};
 }
 dialog.addEventListener('click',async e=>{const action=e.target.closest('[data-tool]')?.dataset.tool;if(!action)return;
  if(action==='close')dialog.close();
  if(['brush','erase'].includes(action)){tool=action;for(const b of dialog.querySelectorAll('[aria-pressed]'))b.setAttribute('aria-pressed',String(b.dataset.tool===tool));}
  if(action==='undo'){strokes.pop();render();}if(action==='clear'){strokes.length=0;render();}
   if(action==='mask'||action==='save'){const result=await exports();if(action==='save'&&mode==='mask'&&!optional&&!result.hasMarks){dialog.querySelector('p').textContent='请先用画笔涂出要编辑的区域。';return;}if(action==='mask'){const a=document.createElement('a'),url=URL.createObjectURL(result.mask);a.href=url;a.download='编辑区域-白色为编辑区.png';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}else{e.target.disabled=true;try{await onSave({...result,mode,strokes});dialog.close();}catch(err){e.target.disabled=false;dialog.querySelector('p').textContent='保存失败：'+err.message;}}}
 });dialog.addEventListener('close',()=>dialog.remove());render();dialog.showModal();
}
