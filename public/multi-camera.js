import {esc} from './data.js';
import {cameraDescription} from './camera-orbit.js?v=60.1';
import {dragCamera,nudgeZoom} from './camera-motion.js?v=60.1';

// Limits from the exact Qwen revision recorded in graph-072, not current upstream.
export const legacyCameraRanges={horizontal_angle:{min:0,max:360,step:1},vertical_angle:{min:-30,max:90,step:1},zoom:{min:0,max:10,step:0.1}};
export function cameraInputRanges(inputs){return ['horizontal_angle','vertical_angle','zoom'].map((key,index)=>{
 const input=inputs[index],fallback=legacyCameraRanges[key],read=(name)=>input?.[name]!==''&&input?.[name]!=null&&Number.isFinite(Number(input[name]))?Number(input[name]):fallback[name];
 return {min:read('min'),max:read('max'),step:read('step')};
});}
export function boundCameraInputs(inputs,next){const ranges=cameraInputRanges(inputs);return Object.fromEntries(['h','v','z'].map((key,index)=>{const r=ranges[index],clamped=Math.max(r.min,Math.min(r.max,next[key]));return [key,r.step>0?Number((Math.max(r.min,Math.min(r.max,Math.round(clamped/r.step)*r.step))).toFixed(6)):clamped];}));}
const describe=(h,v,z)=>cameraDescription(h,0,5).split(' · ')[0]+' · '+(v < -15?'仰视':v < 15?'平视':v < 45?'俯视':v < 75?'鸟瞰':'正俯视')+' · '+(z < 2?'远景':z < 4?'中远景':z < 6?'中景':z < 8?'近景':'特写');
export function cameraGroups(fields){const groups=new Map();for(const f of fields.filter(f=>f.kind==='camera')){const key=String(f.nodeId??f.id.split(':')[0]);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(f);}const ordered=["108","109","110","111","112","119","121","122","120"];return groups.size===9&&ordered.every(id=>groups.has(id))?ordered.map(id=>[id,groups.get(id)]):[...groups.entries()];}
const values=(fields,d)=>Object.fromEntries(fields.map(f=>[f.key,Number(d.catalogValues?.[f.id]??f.value)]));
// Same spherical model as the camera node; no clamping of imported legacy angles.
export function multiCameraPoint(h,v,z){const a=h*Math.PI/180,e=v*Math.PI/180,r=2.6-z/10*2,x=r*Math.sin(a)*Math.cos(e),y=r*Math.sin(e),q=r*Math.cos(a)*Math.cos(e);return {x:220+65*(.866*x+.5*q),y:172+32*(-.5*x+.866*q)-53*y};}
function positions(groups,d){
 const placed=[];return groups.map(([node,fields],index)=>{
  const v=values(fields,d),p=multiCameraPoint(v.horizontal_angle,v.vertical_angle,v.zoom);let x=p.x,y=p.y;
  for(let attempt=0;attempt<10&&placed.some(o=>Math.hypot(o.x-x,o.y-y)<29);attempt++){x=p.x+Math.cos(attempt*2.4)*32;y=p.y+Math.sin(attempt*2.4)*32;}
  placed.push({x,y});return {node,index,v,p,x,y};
 });
}
function marks(groups,d){return positions(groups,d).map(({node,index,v,p,x,y})=>`<g class="multi-camera-marker" data-camera-node="${esc(node)}" role="button" tabindex="0" aria-label="视角 ${index+1}：${esc(describe(v.horizontal_angle,v.vertical_angle,v.zoom))}；拖动调整机位，滚轮调整远近"><path class="multi-camera-ray" d="M220 172 L${p.x} ${p.y}"/><path class="multi-camera-leader" d="M${p.x} ${p.y} L${x} ${y}"/><circle cx="${x}" cy="${y}" r="12"/><text x="${x}" y="${y+4}" text-anchor="middle">${index+1}</text></g>`).join('');}
export function multiCameraGuide(fields,d){const groups=cameraGroups(fields);return `<div class="multi-camera-guide" data-multi-camera-guide><p class="multi-camera-explanation">${groups.length} 视角批量出图 · 拖动编号调机位，滚轮调远近</p><svg viewBox="0 0 440 285" role="group" aria-label="全部视角位置示意，拖动编号调整对应机位"><ellipse cx="220" cy="199" rx="157" ry="61" fill="none" stroke="#54465f"/><path d="M58 199H382 M220 132V267" stroke="#39313f" stroke-dasharray="4 6"/><text x="322" y="252" class="multi-camera-axis">正面 0°</text><text x="72" y="133" class="multi-camera-axis">背面 180°</text><text x="351" y="150" class="multi-camera-axis">右侧 90°</text><text x="38" y="238" class="multi-camera-axis">左侧 270°</text><ellipse cx="220" cy="202" rx="21" ry="7" fill="#0004"/><g fill="#b4a0c8" stroke="#d9c5e8" stroke-width="2"><circle cx="220" cy="130" r="10"/><path d="M206 146Q220 139 234 146L239 175H229L227 199H219L216 174L212 199H205L209 172H201Z"/></g><text x="220" y="223" text-anchor="middle" class="multi-camera-axis">主体</text><g data-multi-camera-points>${marks(groups,d)}</g></svg></div>`;}
export function syncMultiCamera(root,w,d){
 const guide=root.querySelector('[data-multi-camera-guide]');if(!guide)return;
 const groups=cameraGroups(w.interface?.controls||[]),active=guide.dataset.activeCamera;
 // Keep captured pointer targets alive while values update during a drag.
 for(const {node,index,v,p,x,y} of positions(groups,d)){
  const marker=guide.querySelector(`[data-camera-node="${node}"]`);if(!marker)continue;
  marker.querySelector('.multi-camera-ray').setAttribute('d',`M220 172 L${p.x} ${p.y}`);
  marker.querySelector('.multi-camera-leader').setAttribute('d',`M${p.x} ${p.y} L${x} ${y}`);
  for(const [attribute,value] of [['cx',x],['cy',y]])marker.querySelector('circle').setAttribute(attribute,value);
  marker.querySelector('text').setAttribute('x',x);marker.querySelector('text').setAttribute('y',y+4);
  marker.setAttribute('aria-label',`视角 ${index+1}：${describe(v.horizontal_angle,v.vertical_angle,v.zoom)}；拖动调整机位，滚轮调整远近`);
 }
 for(const [node,fields] of groups){const v=values(fields,d),out=root.querySelector(`[data-camera-description="${node}"]`);if(out)out.textContent=describe(v.horizontal_angle,v.vertical_angle,v.zoom);}
 if(active)highlight(root,active);
}
function highlight(root,node){root.querySelector('[data-multi-camera-guide]').dataset.activeCamera=node;for(const el of root.querySelectorAll('[data-camera-node],[data-camera-row]'))el.classList.toggle('is-active',(el.dataset.cameraNode||el.dataset.cameraRow)===node);}
export function installMultiCamera(){
 let dragging=null,suppressClick=false;
 const coordinates=(svg,e)=>{const p=svg.createSVGPoint();p.x=e.clientX;p.y=e.clientY;return p.matrixTransform(svg.getScreenCTM().inverse());};
 const context=point=>{const root=point.closest('[data-control-module="multi-camera"]'),row=root.querySelector(`[data-camera-row="${point.dataset.cameraNode}"]`),inputs=JSON.parse(row.dataset.cameraFields).map(id=>[...row.querySelectorAll('[data-catalog-field]')].find(el=>el.dataset.catalogField===id));return {root,inputs};};
 const write=(inputs,next,commit=false)=>{const bounded=boundCameraInputs(inputs,next);inputs.forEach((input,index)=>{input.value=[bounded.h,bounded.v,bounded.z][index];input.dispatchEvent(new Event(commit?'change':'input',{bubbles:true}));});};
 const read=inputs=>({h:Number(inputs[0].value),v:Number(inputs[1].value),z:Number(inputs[2].value)});
 document.addEventListener('pointerdown',e=>{const point=e.target.closest('[data-camera-node]');if(!point)return;const {root,inputs}=context(point);highlight(root,point.dataset.cameraNode);dragging={point,root,inputs,start:coordinates(point.closest('svg'),e),initial:read(inputs),pointerId:e.pointerId};suppressClick=false;point.setPointerCapture(e.pointerId);point.classList.add('is-dragging');e.preventDefault();});
 document.addEventListener('pointermove',e=>{if(!dragging||e.pointerId!==dragging.pointerId)return;const p=coordinates(dragging.point.closest('svg'),e),dx=p.x-dragging.start.x,dy=p.y-dragging.start.y;if(Math.hypot(dx,dy)<2&&!suppressClick)return;suppressClick=true;write(dragging.inputs,dragCamera(dragging.initial,dx,dy,{sx:65,sy:32,vertical:53,maxElevation:cameraInputRanges(dragging.inputs)[1].max}));});
 const finish=e=>{if(!dragging||e.pointerId!==dragging.pointerId)return;dragging.point.classList.remove('is-dragging');write(dragging.inputs,read(dragging.inputs),true);dragging=null;};
 document.addEventListener('pointerup',finish);document.addEventListener('pointercancel',finish);
 document.addEventListener('click',e=>{const point=e.target.closest('[data-camera-node]');if(!point)return;e.preventDefault();if(suppressClick){suppressClick=false;return;}const {root,inputs}=context(point);highlight(root,point.dataset.cameraNode);inputs[0].focus();});
 document.addEventListener('wheel',e=>{const point=e.target.closest('[data-camera-node]');if(!point)return;e.preventDefault();const {root,inputs}=context(point);highlight(root,point.dataset.cameraNode);const next=read(inputs);next.z=nudgeZoom(next.z,e.deltaY<0?.3:-.3);write(inputs,next);write(inputs,next,true);},{passive:false});
 document.addEventListener('keydown',e=>{const point=e.target.closest('[data-camera-node]');if(!point)return;const {root,inputs}=context(point);if(['Enter',' '].includes(e.key)){e.preventDefault();inputs[0].focus();return;}if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','+','-','='].includes(e.key))return;e.preventDefault();highlight(root,point.dataset.cameraNode);const next=read(inputs);if(e.key==='ArrowLeft'||e.key==='ArrowRight')next.h=(next.h+(e.key==='ArrowRight'?5:-5)+360)%360;else if(e.key==='ArrowUp'||e.key==='ArrowDown')next.v=Math.max(-30,Math.min(90,next.v+(e.key==='ArrowUp'?1:-1)));else next.z=nudgeZoom(next.z,e.key==='-'?-.1:.1);write(inputs,next);write(inputs,next,true);});
 document.addEventListener('focusin',e=>{const row=e.target.closest('[data-camera-row]');if(row)highlight(row.closest('[data-control-module="multi-camera"]'),row.dataset.cameraRow);});
}
