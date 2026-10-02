// Spatial diagram inspired by the original Qwen Multiangle Camera's orbit controls.
// The diagram changes camera position; it never claims to generate a novel image.
const radians=n=>n*Math.PI/180;
const point=(x,y,z)=>({x:180+70*(.866*x+.5*z),y:186+34*(-.5*x+.866*z)-64*y});
const xy=p=>`${p.x.toFixed(2)},${p.y.toFixed(2)}`;
export function cameraPosition(h,v,z){const a=radians(h),b=radians(v),r=2.6-z/10*2;return {x:r*Math.sin(a)*Math.cos(b),y:.9+r*Math.sin(b),z:r*Math.cos(a)*Math.cos(b)};}
export function cameraDescription(h,v,z){return `${['正面','右前方','右侧','右后方','背面','左后方','左侧','左前方'][Math.round(h/45)%8]} · ${v<-15?'仰视':v<15?'平视':v<45?'俯视':'高位俯视'} · ${z<2?'远景':z<6?'中景':'特写'}`;}
export const cameraFramingScale=z=>.72+Math.pow(Math.max(0,Math.min(10,z))/10,1.35)*2.3;
function path(points,close=false){return 'M'+points.map(xy).join('L')+(close?'Z':'');}
export function cameraOrbitMarkup(h,v,z){
 const grid=[];for(let n=-2;n<=2;n+=.5){grid.push(`<path d="${path([point(n,0,-2.2),point(n,0,2.2)])} ${path([point(-2.2,0,n),point(2.2,0,n)])}"/>`);}
 const ring=Array.from({length:73},(_,i)=>point(1.8*Math.sin(radians(i*5)),0,1.8*Math.cos(radians(i*5))));
 const front=point(0,0,1.2),nose=point(0,1.43,.35),head=point(0,1.5,0),shoulders=[point(-.4,1.14,0),point(.4,1.14,0)],feet=[point(-.18,0,0),point(.18,0,0)];
 return `<div class="catalog-camera-guide" data-camera-guide><div class="camera-direction"><strong data-camera-description>${cameraDescription(h,v,z)}</strong><small>机位示意</small></div>
 <div class="camera-visuals"><svg viewBox="0 0 360 295" data-camera-map role="img" aria-label="相机围绕人物移动的空间示意；拖动黄色相机调整机位和远近">
 <g fill="none" stroke="#a799b8" stroke-opacity=".1" stroke-width=".7">${grid.join('')}</g>
 <path d="${path(ring,true)}" fill="none" stroke="#b28bd4" stroke-width="2" stroke-dasharray="3 4"/>
 ${[[0,'正面'],[90,'右侧'],[180,'背面'],[270,'左侧']].map(([a,t])=>{const p=point(2.15*Math.sin(radians(a)),0,2.15*Math.cos(radians(a)));return `<text x="${p.x}" y="${p.y+4}" fill="#b4a5c1" text-anchor="middle" font-size="10">${t}</text>`}).join('')}
 <path d="${path([point(0,0,0),front])}" stroke="#9acace" stroke-width="3"/><circle cx="${front.x}" cy="${front.y}" r="3" fill="#9acace"/>
 <ellipse cx="180" cy="186" rx="28" ry="10" fill="#0005"/>
 <g stroke="#cbb9dc" stroke-linejoin="round"><path d="M${xy(shoulders[0])} Q180,102 ${xy(shoulders[1])} L${xy(point(.26,.53,0))} L${xy(point(-.26,.53,0))}Z" fill="#51465f"/>
 <path d="${path([point(-.16,.58,0),feet[0]])} ${path([point(.16,.58,0),feet[1]])}" fill="none" stroke-width="12" stroke-linecap="round"/>
 <path d="${path([shoulders[0],point(-.56,.54,0)])} ${path([shoulders[1],point(.56,.54,0)])}" fill="none" stroke-width="8" stroke-linecap="round"/>
 <ellipse cx="${head.x}" cy="${head.y}" rx="13" ry="17" fill="#d9ccdF"/><path d="M${head.x+5},${head.y} L${nose.x},${nose.y+3} L${head.x+5},${head.y+7}" fill="#ad97c0" stroke="none"/></g>
 <path data-camera-sight fill="#eabb6520" stroke="#eabb6566" stroke-width="1"/>
 <path data-camera-height stroke="#eabb6588" stroke-dasharray="4 3"/>
 <circle data-camera-shadow r="6" fill="#eabb6540" stroke="#eabb65"/>
 <g class="camera-orbit-point" data-camera-position><g data-camera-handle tabindex="0" role="button" aria-label="拖动相机调整视角"><circle r="22" fill="transparent"/><rect x="-13" y="-9" width="23" height="18" rx="5" fill="#edb962" stroke="#ffe3a8"/><path d="M10,-5L19,-10V10L10,5Z" fill="#edb962"/><circle cx="-2" cy="0" r="4" fill="#654623"/></g></g>
 </svg><figure class="camera-framing"><svg viewBox="0 0 120 150" role="img" aria-label="随镜头远近变化的景别示意"><path d="M12 20V10H22 M98 10H108V20 M12 130V140H22 M98 140H108V130" fill="none" stroke="#b79ccb" stroke-opacity=".5"/><g data-camera-framing-person fill="#9e8eae" stroke="#cdbeda" stroke-linejoin="round"><ellipse cx="60" cy="39" rx="11" ry="14" fill="#d6c8e1"/><path d="M45 57Q60 51 75 57L80 97H40Z"/><path d="M44 61L34 96 M76 61L86 96 M48 95L46 133 M72 95L74 133" fill="none" stroke-width="9" stroke-linecap="round"/></g></svg><figcaption><span data-camera-framing-label>中景</span><small>景别示意</small></figcaption></figure></div><div class="camera-orbit-presets" role="group" aria-label="常用观察方向">${[[0,'正面'],[90,'右侧'],[180,'背面'],[270,'左侧']].map(([a,label])=>`<button type="button" data-camera-preset="${a}" aria-pressed="${h===a}">${label}</button>`).join('')}</div>
 <label class="camera-elevation"><span>仰视</span><input data-camera-elevation type="range" min="-30" max="60" step="1" value="${v}" aria-label="相机俯仰"><span>俯视</span><strong data-camera-vertical>${v}°</strong></label>
 <label class="catalog-camera-distance"><span>远景</span><input data-camera-zoom type="range" min="0" max="10" step=".1" value="${z}" aria-label="镜头拉近程度"><span>特写</span><strong data-camera-zoom>${z}</strong></label>
 <small class="camera-instruction">拖动调机位与远近 · 滚轮单独调远近</small></div>`;
}
export function updateCameraOrbit(guide,h,v,z){
 const position=cameraPosition(h,v,z),p=point(position.x,position.y,position.z),floor=point(position.x,0,position.z);
 guide.querySelector('[data-camera-position]').setAttribute('transform',`translate(${p.x},${p.y})`);
 const target=point(0,.9,0),angle=Math.atan2(target.y-p.y,target.x-p.x)*180/Math.PI;
 guide.querySelector('[data-camera-handle]').setAttribute('transform',`rotate(${angle})`);
 guide.querySelector('[data-camera-handle]').setAttribute('aria-label',`水平 ${h} 度，垂直 ${v} 度，远近 ${z}；方向键调整`);
 guide.querySelector('[data-camera-height]').setAttribute('d',path([p,floor]));
 const shadow=guide.querySelector('[data-camera-shadow]');shadow.setAttribute('cx',floor.x);shadow.setAttribute('cy',floor.y);
 guide.querySelector('[data-camera-sight]').setAttribute('d',path([p,point(-.24,.6,0),point(.24,1.2,0)],true));
 guide.querySelector('[data-camera-description]').textContent=cameraDescription(h,v,z);
 guide.querySelector('[data-camera-framing-person]').setAttribute('transform',`translate(60 44) scale(${cameraFramingScale(z)}) translate(-60 -44)`);
 guide.querySelector('[data-camera-framing-label]').textContent=z<2?'远景':z<6?'中景':'特写';
 guide.querySelector('[data-camera-vertical]').textContent=v+'°';guide.querySelector('strong[data-camera-zoom]').textContent=z;
 guide.querySelector('input[data-camera-zoom]').value=z;guide.querySelector('input[data-camera-elevation]').value=v;
 guide.querySelector('input[data-camera-zoom]').style.setProperty('--range-progress',z*10+'%');guide.querySelector('input[data-camera-elevation]').style.setProperty('--range-progress',(v+30)/90*100+'%');
 guide.querySelectorAll('[data-camera-preset]').forEach(b=>b.setAttribute('aria-pressed',String(Number(b.dataset.cameraPreset)===h%360)));
}
