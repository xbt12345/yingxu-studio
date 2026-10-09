import {esc} from './data.js';
import {workflowCoverProfiles,categoryCoverProfiles} from './workflow-cover-profiles.js?v=88.0';

const fallback={kind:'image-edit',label:'图像创作',feature:'按描述修改画面',asset:'portal-ocean.png',variant:'general'};
export function workflowCoverProfile(w,category=false){
 return {...fallback,...(category?categoryCoverProfiles[w?.category]:workflowCoverProfiles[w?.id]||categoryCoverProfiles[w?.category])};
}

function safeImage(value){
 if(typeof value!=='string'||!value||/[\u0000-\u0020\u007f\\]/.test(value))return '';
 if(/^(?:https?:\/\/|blob:|\/(?!\/)|(?:\.\/)?assets\/)/i.test(value))return value;
 return /^data:image\/(?:png|jpeg|webp|gif|avif);base64,[a-z0-9+/=]+$/i.test(value)?value:'';
}
const stroke='fill="none" stroke="#c4a8df" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"';
const arrow=(x,y,dx,dy)=>{const a=Math.atan2(dy,dx),tipX=x+dx,tipY=y+dy;return `<path d="M${x} ${y}l${dx} ${dy}m${-7*Math.cos(a-.55)} ${-7*Math.sin(a-.55)}L${tipX} ${tipY}l${-7*Math.cos(a+.55)} ${-7*Math.sin(a+.55)}" ${stroke}/>`;};
const star=(x,y,r=10)=>`<path d="M${x} ${y-r}l${r*.3} ${r*.7} ${r*.7} ${r*.3}-${r*.7} ${r*.3}-${r*.3} ${r*.7}-${r*.3}-${r*.7}-${r*.7}-${r*.3} ${r*.7}-${r*.3}Z" fill="#dcc5f1"/>`;
const textLines=(x,y,width=76)=>`<path d="M${x} ${y}h${width}m-${width} 14h${width*.7}m-${width*.7} 14h${width*.85}" stroke="#b494cc" stroke-width="2.5" stroke-linecap="round"/>`;
const play=(x,y,r=13)=>`<path d="m${x-r*.6} ${y-r} ${r*1.5} ${r}-${r*1.5} ${r}Z" fill="#efe3f8"/>`;
const waveform=(x,y,width=87)=>[8,16,28,13,34,47,27,14,37,19,31,21,10].map((h,i)=>`<path d="M${x+i*width/12} ${y-h/2}v${h}" stroke="#cdb0e5" stroke-width="2.2" stroke-linecap="round"/>`).join('');
const person=(x,y,color='#ae83cd',pose='stand')=>`<g transform="translate(${x} ${y})"><circle cy="-29" r="10" fill="#d6bfe7"/><path d="M-13-14h26l8 38h-42Z" fill="${color}"/><path d="M-8 23l-4 31m20-31 4 31M-13-8l-15 ${pose==='wave'?-29:28}m41-28 15 28" stroke="#b79aca" stroke-width="5" stroke-linecap="round"/></g>`;
const shirt=(x,y,color='#a783bf')=>`<path d="m${x} ${y} -18 12 8 19 10-6v47h43V${y+25}l10 6 8-19-18-12-22 12Z" fill="${color}" stroke="#d7bce9" stroke-width="1.2"/>`;
const camera=(x,y)=>`<circle cx="${x}" cy="${y}" r="8" fill="#30213e" stroke="#b79bcd"/><circle cx="${x}" cy="${y}" r="2.5" fill="#d6bde6"/>`;
const film=(x,y,w,h)=>`<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="8" fill="none" stroke="#b493cb"/>${[0,1,2,3,4].map(i=>`<rect x="${x+9+i*(w-22)/5}" y="${y+5}" width="12" height="4" rx="1" fill="#9c7fb3"/>`).join('')}`;
const folder=(x,y)=>`<path d="M${x} ${y+14}V${y}h35l12 12h40v65h-87Z" fill="#493354" stroke="#b798ce"/><path d="M${x} ${y+28}h85l-10 49h-75Z" fill="#795a8c" stroke="#c8acdd"/>`;

// Photos remain ordinary img elements so the existing error boundary can replace
// a failed private/history image with a genuinely image-free operation diagram.
export function renderWorkflowCover(w,media={},category=false){
 const p=workflowCoverProfile(w,category),omit=!!media.omitImages;
 const actual=omit?'':safeImage(media.primary),original=omit?'':safeImage(media.input);
 const sample=/^[\w.-]+\.(?:png|jpe?g|webp|avif)$/i.test(p.asset||'')?`assets/${p.asset}`:'assets/portal-ocean.png';
 const primary=actual||sample,input=actual&&original?original:primary;
 const references=(media.inputs||[]).map(safeImage).filter(Boolean),photos=[];
 const photo=(src,x,y,width,height,round=8)=>{
  photos.push({src,x,y,width,height,round});
  return `<rect x="${x}" y="${y}" width="${width}" height="${height}" rx="${round===50?Math.min(width,height)/2:round}" fill="none" stroke="#d9c4ec40"/>`;
 };
 const big=()=>photo(primary,148,20,175,112),ref=(i=0)=>references[i]||input;
 let art='';
 switch(p.kind){
 case'text-image':art=big()+textLines(25,47,78)+star(128,66,11);break;
 case'image-edit':art=big()+photo(input,31,60,80,62)+arrow(119,88,18,0)+`<rect x="236" y="46" width="61" height="57" rx="6" fill="#cba6ef19" stroke="#ead8fa" stroke-dasharray="4 4"/><path d="m44 41 17-23 9 7-17 23-13 5Z" fill="#ba90d7"/>`;break;
 case'multi-image':{
  if(['depth','line'].includes(p.variant)){
   art=photo(input,22,27,83,101)+photo(primary,231,27,90,101)+arrow(110,76,15,0)+arrow(208,76,15,0)+`<rect x="132" y="37" width="70" height="78" rx="7" fill="#24202c" stroke="#bfa8d073"/>`;
   art+=p.variant==='depth'?`<path d="M134 87l22-27 15 15 15-26 14 38v26h-66Z" fill="#514857"/><path d="M134 99l16-16 14 13 17-15 19 18v14h-66Z" fill="#93869e"/><path d="M134 109l24-12 20 11 22-7v12h-66Z" fill="#d0c3dc"/>`:`<path d="m137 99 17-29 15 17 18-34 12 45m-62 8 24-13 17 11 20-6M149 107l5-13 8 9" ${stroke}/>`;
   art+=`<text x="167" y="133" text-anchor="middle" fill="#c6b0d7" font-size="9">${p.variant==='depth'?'深度示意':'边缘示意'}</text>`;
   break;
  }
  art=photo(primary,194,26,130,106)+[0,1,2].map(i=>photo(ref(i),28+i*30,29+i*29,79,57)).join('')+arrow(155,89,25,0);
  if(p.variant==='compare')art+=`<path d="M256 27v105" stroke="#f0d9ff" stroke-dasharray="3 3"/>`;
  break;
 }
 case'outpaint':case'extend-video':art=`<rect x="29" y="19" width="281" height="116" rx="10" fill="none" stroke="#a280bc" stroke-dasharray="5 5"/>`+photo(input,97,41,145,71)+arrow(83,77,-38,0)+arrow(256,77,39,0)+arrow(170,34,0,-11)+arrow(170,121,0,9)+(p.kind==='extend-video'?play(170,75,10):'');break;
 case'camera':{
  const count=p.variant==='nine'?9:p.variant==='six'?6:3;
  art=photo(primary,118,43,107,71)+`<ellipse cx="170" cy="76" rx="124" ry="55" fill="none" stroke="#8d6ea9" stroke-dasharray="3 6"/>`+Array.from({length:count},(_,i)=>{const a=(i*360/count-90)*Math.PI/180;return camera(170+124*Math.cos(a),76+55*Math.sin(a));}).join('');
  if(count===3)art+=arrow(58,115,27,10);
  break;
 }
 case'outfit':art=photo(input,30,28,100,103)+photo(primary,213,28,109,103)+shirt(143,45)+arrow(140,123,51,0);break;
 case'face':art=photo(input,31,34,88,90,50)+photo(primary,209,24,114,110)+`<ellipse cx="267" cy="55" rx="19" ry="25" fill="none" stroke="#ecd7f6" stroke-dasharray="3 4"/>`+arrow(130,78,58,0);break;
 case'pose':art=photo(primary,192,20,130,115)+person(65,68,'#a381b8')+person(143,68,'#bd9dd2','wave')+arrow(91,107,23,0);break;
 case'inpaint':art=big()+`<rect x="224" y="48" width="64" height="55" rx="7" fill="#c69ae72b" stroke="#e4c2f4" stroke-dasharray="4 4"/><path d="m41 86 33-44 13 10-33 44-17 9Z" fill="#ae83cb"/>`+photo(input,38,22,63,42);break;
 case'colorize':art=photo(input,28,26,123,104)+photo(primary,199,26,123,104)+arrow(160,79,26,0)+[0,1,2,3].map((v)=>`<circle cx="${207+v*29}" cy="122" r="6" fill="${['#c895bc','#b5a0db','#a3c3d0','#dec4a1'][v]}"/>`).join('');break;
 case'cartoon-real':art=photo(input,27,28,113,104)+photo(primary,205,23,117,111)+`<path d="M35 36h97v88H35Z" fill="none" stroke="#ead7fa" stroke-dasharray="2 3"/>`+arrow(154,78,36,0)+star(310,29,9);break;
 case'upscale':case'video-upscale':art=photo(primary,31,25,140,103)+photo(primary,223,26,91,91,50)+`<circle cx="269" cy="71" r="47" fill="none" stroke="#dec6ed" stroke-width="3"/><path d="m297 106 22 23" stroke="#c6a5da" stroke-width="7" stroke-linecap="round"/>`+arrow(181,78,27,0)+(p.kind==='video-upscale'?play(99,77,10):'');break;
 case'cleanup':art=big()+`<path d="M29 58h46m-46 15h32m-32 15h43" stroke="#80668e" stroke-dasharray="3 4" stroke-width="3"/>`+arrow(86,76,46,0)+star(307,30,11);break;
 case'background':art=photo(input,26,26,123,104)+photo(primary,203,26,120,104)+`<rect x="203" y="26" width="120" height="104" rx="8" fill="${p.variant==='white'?'#ffffff26':'#cda6eb12'}" stroke="#dec5ee"/><path d="M223 109h82" stroke="#efe3f8" stroke-dasharray="3 4"/>`+arrow(160,79,27,0);break;
 case'text-video':art=photo(primary,147,24,176,103)+textLines(24,40,74)+arrow(109,76,27,0)+play(236,74,15)+film(145,21,180,109);break;
 case'image-video':art=photo(primary,150,20,174,110)+[0,1,2].map(i=>photo(ref(i),26+i*12,25+i*28,71,50)).join('')+arrow(116,80,23,0)+play(237,71,14);if(p.variant?.includes('audio'))art+=waveform(255,145,61);break;
 case'keyframes':art=photo(ref(0),26,33,92,85)+photo(ref(1),220,33,103,85)+`<path d="M127 77h84" stroke="#b99aca" stroke-dasharray="4 5"/>`+play(167,77,11)+`<circle cx="128" cy="77" r="4" fill="#d4b9e5"/><circle cx="207" cy="77" r="4" fill="#d4b9e5"/>`;break;
 case'video-edit':{
  art=photo(primary,157,27,162,103)+photo(input,29,47,84,68)+arrow(124,79,22,0)+film(153,21,170,113)+play(238,76,13);
  if(p.variant?.startsWith('outfit'))art+=shirt(27,21,'#b796d0');
  else if(['person','face'].includes(p.variant))art+=`<ellipse cx="229" cy="53" rx="19" ry="24" fill="#ac84ce18" stroke="#ead5fb" stroke-dasharray="3 3"/>`;
  else if(p.variant==='mask')art+=`<rect x="221" y="53" width="48" height="43" rx="7" fill="#c9a2e72b" stroke="#e7d2f5" stroke-dasharray="4 4"/>`;
  else if(p.variant==='background')art+=`<path d="M179 102l28-28 27 19 33-40 33 49" ${stroke}/>`;
  else if(p.variant==='two-pass')art+=`<circle cx="124" cy="54" r="8" fill="#b799cb"/><circle cx="144" cy="54" r="8" fill="#dcc8eb"/>`;
  break;
 }
 case'dance':art=photo(primary,194,20,128,115)+person(47,72,'#ac88c0','wave')+person(139,72,'#bca0d1','wave')+arrow(77,72,29,0)+`<path d="M107 44q-9 32 3 57" ${stroke}/>`;break;
 case'lipsync':art=photo(primary,154,20,169,115)+waveform(28,77,96)+arrow(131,78,15,0)+`<path d="M216 68q22 21 45 0" fill="none" stroke="#f2dfef" stroke-width="2.2"/>`;if(p.variant==='double')art+=photo(input,181,37,54,69);break;
 case'prompt':art=photo(input,29,25,118,104)+arrow(160,78,23,0)+`<rect x="194" y="29" width="122" height="99" rx="8" fill="#2b2037" stroke="#84659d"/>`+textLines(208,49,90)+star(302,107,8);break;
 case'gif':art=[0,1,2].map(i=>photo(ref(i),29+i*42,24+i*15,81,78)).join('')+`<path d="M221 77a41 41 0 1 1 6 35m-6-35 15 4-3-14" ${stroke}/>`+play(263,87,15);break;
 case'batch':art=folder(26,39)+arrow(118,83,23,0)+[0,1,2].map(i=>photo(primary,158+i*51,24+i*13,62,76)).join('')+`<path d="M164 135h137m-127-4v8m30-8v8m30-8v8m30-8v8" ${stroke}/>`;break;
 default:art=big()+textLines(27,53,70)+arrow(113,88,21,0);break;
 }
 const history=!!actual&&!omit&&['comparison','history'].includes(media.evidence);
 const requestedPair=history&&!!original&&media.evidence==='comparison';
 // A layout that foregrounds only one side still keeps a real companion image;
 // the pair label is never inferred from metadata without showing both sources.
 if(requestedPair&&!photos.some(box=>box.src===actual))art+=photo(actual,248,29,70,50);
 if(requestedPair&&!photos.some(box=>box.src===original))art+=photo(original,28,85,76,49);
 const paired=requestedPair&&photos.some(box=>box.src===actual)&&photos.some(box=>box.src===original);
 const evidence=paired?'原图 → 历史结果':history?'历史素材 · 用途示意':'用途示意';
 const emptyPicture='<svg viewBox="0 0 80 60" aria-hidden="true"><circle cx="59" cy="17" r="6" fill="#b79dc8"/><path d="m5 53 21-27 17 16 16-20 16 31Z" fill="#6e557f"/></svg>';
 const photoHTML=photos.map(box=>`<span class="cover-photo" style="left:${box.x/3.4}%;top:${box.y/1.91}%;width:${box.width/3.4}%;height:${box.height/1.91}%;border-radius:${box.round===50?'50%':box.round+'px'}">${emptyPicture}${omit?'':`<img src="${esc(box.src)}" alt="" loading="lazy" decoding="async">`}</span>`).join('');
 return `<span class="cover-art" data-cover-kind="${esc(p.kind)}" data-cover-variant="${esc(p.variant||'')}" role="img" title="${esc(p.feature||'')}" aria-label="${esc(p.label+'，'+(p.feature||'')+'，'+evidence)}">${photoHTML}<svg class="cover-operation" viewBox="0 0 340 191" aria-hidden="true">${art}</svg><span class="cover-evidence">${evidence}</span><span class="cover-feature">${esc(p.feature||'')}</span><span class="cover-operation-label">${esc(p.label)}</span></span>`;
}
