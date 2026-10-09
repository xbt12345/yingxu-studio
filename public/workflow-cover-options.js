import {esc} from './data.js';
import {catalogConnectionState} from './catalog-submission.js?v=88.0';

// Each example has a distinct operation grounded in its public workflow interface.
// Photos are existing layout samples; no image is presented as a workflow result.
const examples=[
  {id:'local-card-1',key:'generate',asset:'portal-ocean.png',feature:'Qwen 2.1 · 文字生图',keyword:'文字成图',detail:'Qwen Image 2.1',position:'60% 50%'},
  {id:'local-card-2',key:'edit',asset:'forest.jpg',feature:'原图 + 修改参考图',keyword:'双图编辑',detail:'Qwen Image 2.1',position:'48% 50%'},
  {id:'local-card-13',key:'expand',asset:'coast.jpg',feature:'Klein 9B · 四向扩展',keyword:'四向扩展',detail:'左右 / 上下独立设定',position:'50% 60%'},
  {id:'local-card-72',key:'camera',asset:'mountain.jpg',feature:'同一场景 · 九个机位',keyword:'九个机位',detail:'水平角度 · 俯仰角度 · 距离',position:'50% 48%'},
  {id:'h3-reference',key:'video',asset:'award-poster.jpg',feature:'H3 · 多参考 · 有声视频',keyword:'多参考视频',detail:'最多 9 张图 · 带声音',position:'45% 50%'},
  {id:'local-card-136',key:'files',asset:'dunes.jpg',feature:'目录读取 · 按索引选帧',keyword:'目录选帧',detail:'匹配文件 · 读取素材',position:'50% 55%'}
];
const schemes=[
  {id:'a',letter:'A',name:'作品海报',description:'画面更醒目，具体操作需要看特征标签。'},
  {id:'b',letter:'B',name:'用途图形',description:'一眼分清操作，作品氛围较少。'},
  {id:'c',letter:'C',name:'操作封面',description:'图片与操作一起辨认，画面会更紧凑。'}
];
const grid=document.getElementById('comparison');
const stroke='fill="none" stroke="#bba0db" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"';
const arrow=(x1,y1,x2,y2)=>{const angle=Math.atan2(y2-y1,x2-x1),a=angle+.55,b=angle-.55;return `<path d="M${x1} ${y1}L${x2} ${y2}m${-8*Math.cos(a)} ${-8*Math.sin(a)}L${x2} ${y2}l${-8*Math.cos(b)} ${-8*Math.sin(b)}" ${stroke}/>`;};
const sparkle=(x,y,size=11)=>`<path d="M${x} ${y-size}l${size*.28} ${size*.72} ${size*.72} ${size*.28}-${size*.72} ${size*.28}-${size*.28} ${size*.72}-${size*.28}-${size*.72}-${size*.72}-${size*.28} ${size*.72}-${size*.28}Z" fill="#dac1f1"/>`;
const wave=(x,y,width=100)=>Array.from({length:15},(_,i)=>{const h=[8,15,25,12,35,48,29,14,35,20,42,26,12,20,7][i];return `<path d="M${x+i*width/14} ${y-h/2}v${h}" stroke="#d6b6ee" stroke-width="2.4" stroke-linecap="round"/>`;}).join('');
const scene=(x,y,w,h)=>`<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="8" fill="#32243f" stroke="#8d70a9"/><circle cx="${x+w*.72}" cy="${y+h*.29}" r="${w*.07}" fill="#cab0df"/><path d="M${x+6} ${y+h-7}l${w*.23}-${h*.45} ${w*.22} ${h*.29} ${w*.18}-${h*.25} ${w*.29} ${h*.41}Z" fill="#78598e"/>`;
let photoIndex=0;
const photo=(asset,x,y,w,h,radius=8,position='xMidYMid')=>{const clip='cover-sample-'+(++photoIndex);return `<svg x="${x}" y="${y}" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" overflow="hidden"><defs><clipPath id="${clip}"><rect width="${w}" height="${h}" rx="${radius}"/></clipPath></defs><image href="assets/${esc(asset)}" width="${w}" height="${h}" preserveAspectRatio="${position} slice" clip-path="url(#${clip})"/></svg>`;};
const person=(x,y,scale=1)=>`<g transform="translate(${x} ${y}) scale(${scale})"><circle cy="-17" r="10" fill="#c8abdF"/><path d="M-17 29v-13c0-21 34-21 34 0v13" fill="#8b68a4"/></g>`;
const lens=(x,y,i)=>`<circle cx="${x}" cy="${y}" r="10" fill="#2c2038" stroke="#b799d1"/><circle cx="${x}" cy="${y}" r="3" fill="#cdb1e3"/>`;
function pureDiagram(example){
  const {key}=example;
  if(key==='generate')return `<rect x="39" y="43" width="96" height="84" rx="9" fill="#2b2136" stroke="#6b517f"/><path d="M55 65h63m-63 16h45m-45 16h59m-59 16h36" stroke="#c3a9da" stroke-width="2.5" stroke-linecap="round"/>${arrow(146,85,171,85)}${scene(185,34,115,102)}${sparkle(291,39,12)}`;
  if(key==='edit')return `${scene(41,32,103,92)}${scene(95,64,86,70)}<rect x="43" y="35" width="103" height="92" rx="8" fill="none" stroke="#dac2ee" stroke-width="1.5"/><path d="M191 86h22" ${stroke}/><path d="m238 99 30-45 14 9-31 45-17 10z" fill="#ab87c4" stroke="#e1c8f4"/><path d="m262 64 12 8m-41 46 6-18" ${stroke}/><path d="M233 132h52" stroke="#715a83" stroke-width="1.6" stroke-linecap="round"/>`;
  if(key==='expand')return `<rect x="56" y="23" width="222" height="127" rx="9" fill="#b497d207" stroke="#9575b4" stroke-dasharray="5 5"/>${scene(122,52,90,68)}${arrow(111,86,72,86)}${arrow(223,86,263,86)}${arrow(167,42,167,29)}${arrow(167,128,167,143)}`;
  if(key==='camera'){const cameras=Array.from({length:9},(_,i)=>{const a=(i*40-90)*Math.PI/180;return lens(169+106*Math.cos(a),91+51*Math.sin(a),i);}).join('');return `<ellipse cx="169" cy="91" rx="106" ry="51" fill="none" stroke="#655073" stroke-dasharray="3 5"/>${person(169,86,.9)}${cameras}<path d="m127 84-27-6m101 6 32-6m-64 38v16" stroke="#8c6da4" stroke-width="1"/>`;}
  if(key==='video')return `${scene(35,31,62,49)}${scene(46,61,62,49)}${scene(57,91,62,49)}${arrow(130,84,155,84)}<rect x="168" y="28" width="135" height="91" rx="9" fill="#332442" stroke="#b28acb"/><path d="m222 54 27 20-27 20Z" fill="#dfc5f4"/>${wave(188,143,94)}`;
  return `<path d="M36 68h90l13 16H36Z" fill="#8d6ea6"/><path d="M36 68V48h45l12 13h39v67H36Z" fill="#332442" stroke="#a382bd"/><path d="M47 79h79l-10 49H36Z" fill="#68517d" stroke="#b59acc"/>${arrow(145,90,166,90)}${[0,1,2].map(i=>`<g transform="translate(${180+i*36} ${44+i*9})">${scene(0,0,42,73)}<path d="m16 33 12 8-12 8Z" fill="#d8bced"/></g>`).join('')}<path d="M183 144h107m-99-5v10m30-10v10m30-10v10m30-10v10" ${stroke}/>`;
}
function imageDiagram(example){
  const {key,asset}=example;
  if(key==='generate')return `${photo(asset,140,18,186,112,10)}<path d="M26 43h82m-82 15h58m-58 15h70" stroke="#ae8dcc" stroke-width="2" stroke-linecap="round"/>${sparkle(125,51,11)}<rect x="151" y="28" width="166" height="92" rx="7" fill="none" stroke="#e7d9f63b"/>`;
  if(key==='edit')return `${photo(asset,134,20,191,116,10)}<rect x="221" y="44" width="66" height="60" rx="7" fill="#c1a1ed20" stroke="#eddefe" stroke-dasharray="4 4"/><path d="m38 71 24-35 10 7-24 35-13 6z" fill="#a983c4" stroke="#d1b2e8"/>${photo('dunes.jpg',76,63,70,58,7)}<path d="M88 55h60v47" fill="none" stroke="#b99acd" stroke-width="1.2"/>`;
  if(key==='expand')return `<rect x="33" y="17" width="274" height="109" rx="11" fill="#41295333" stroke="#a17abe" stroke-dasharray="5 5"/>${photo(asset,99,37,144,69,7)}${arrow(86,73,48,73)}${arrow(255,73,293,73)}${arrow(170,31,170,21)}${arrow(170,112,170,122)}`;
  if(key==='camera')return `${photo(asset,115,36,111,76,9)}<ellipse cx="170" cy="75" rx="127" ry="56" stroke="#9472b1" stroke-dasharray="3 6" fill="none"/>${Array.from({length:9},(_,i)=>{const a=(i*40-90)*Math.PI/180;return lens(170+127*Math.cos(a),75+56*Math.sin(a),i);}).join('')}`;
  if(key==='video')return `${photo(asset,116,17,210,119,10)}<path d="m201 52 25 17-25 17Z" fill="#fff" opacity=".85"/><g opacity=".85">${photo('coast.jpg',24,26,74,46,6)}${photo('forest.jpg',33,61,74,46,6)}</g>${wave(250,153,59)}`;
  return `<path d="M28 47h36l11 12h37v55H28Z" fill="#533b69" stroke="#b892d4"/><path d="M28 68h79l-8 46H28Z" fill="#7f5e99" stroke="#c8a5e4"/>${arrow(119,78,142,78)}${[0,1,2].map(i=>`${photo(asset,157+i*51,25+i*12,62,78,7)}<rect x="${161+i*51}" y="${29+i*12}" width="54" height="70" rx="4" fill="none" stroke="#e3d1f654"/>`).join('')}<path d="M165 135h134m-123-4v8m31-8v8m31-8v8m31-8v8" stroke="#9976b5" stroke-width="1.4"/>`;
}
const iconPaths={generate:'m8 1 2 5 5 2-5 2-2 5-2-5-5-2 5-2Z',edit:'m3 11 8-8 3 3-8 8-4 1Z',expand:'M5 1H1v4m10-4h4v4m0 6v4h-4M5 15H1v-4',camera:'M1 5h14v8H1Zm3 0 2-3h4l2 3M11 9a3 3 0 1 1-6 0 3 3 0 0 1 6 0',video:'M2 2h12v12H2Zm4 3 5 3-5 3Z',files:'M1 4h6l2 2h6v8H1Zm0 0V2h6l2 2'};
function cover(example,scheme){
  if(scheme==='a')return `<img src="assets/${esc(example.asset)}" alt="${esc(example.feature)}封面示例素材" style="object-position:${example.position}" loading="lazy"><span class="poster-shade"></span><span class="feature-label"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="${iconPaths[example.key]}"/></svg>${esc(example.feature)}</span>`;
  const graphic=scheme==='b'?pureDiagram(example):imageDiagram(example);
  return `<svg viewBox="0 0 340 191" role="img" aria-label="${esc(example.keyword)}用途示意：${esc(example.detail)}"><rect width="340" height="191" fill="${scheme==='b'?'#211a2c':'#1d1627'}"/>${graphic}</svg><span class="graphic-label">${esc(example.keyword)}</span>`;
}
function card(example,w,scheme){
  const state=w.state,connected=state.label==='已接入'||state.label==='已实测'||state.label.startsWith('已接入');
  return `<a class="cover-card cover-${scheme} scheme-${scheme}" href="studio.html#workflow/${encodeURIComponent(w.id)}" aria-label="打开${esc(w.name)} · ${schemes.find(s=>s.id===scheme).name}"><div class="cover-visual">${cover(example,scheme)}</div><div class="cover-info"><h3>${esc(w.name)}</h3><div class="cover-meta"><span>${esc(w.category)}</span><span class="cover-status ${connected?'connected':state.unknown?'unknown':''}" title="${esc(state.detail||'')}">${esc(state.label)}</span></div></div></a>`;
}
async function readJSON(url,optional=false){
  try{const response=await fetch(url,{signal:AbortSignal.timeout(8000)});if(!response.ok)throw new Error(String(response.status));return await response.json();}catch(error){if(optional)return null;throw error;}
}
async function init(){
  try{
    const [catalog,interfaces,live,connections]=await Promise.all([
      readJSON('local-catalog.json?v=21.2'),readJSON('workflow-interfaces.json?v=88.0',true),
      readJSON('/api/workflows',true),readJSON('/api/catalog-connections',true)
    ]);
    const local=catalog.workflows||[];
    const workflows=examples.map(example=>{
      const w={...local.find(w=>w.id===example.id)};
      if(example.id==='h3-reference'){
        const source=(live||[]).find(w=>w.id===example.id);
        if(source)return {...source,category:'参考图生视频',state:{label:'已接入',detail:'读取当前工作流目录；生成效果以实际返回为准。'}};
        return {id:example.id,name:'H3 多参考图生视频',category:'参考图生视频',state:{label:'状态待读取',unknown:true,detail:'未读到当前工作流服务。'}};
      }
      if(!w.id)throw new Error('工作流目录缺少 '+example.id);
      const cfg=interfaces?.workflows?.[w.id],connection=(connections||[]).find(entry=>entry.id===w.id&&entry.name===w.name&&entry.source_hash===cfg?.sourceHash);
      if(connection){w.catalogConnection=connection;w.catalogConnected=true;w.catalogPendingApi=connection.validation==='api-pending';}
      w.state=connections&&interfaces?catalogConnectionState(w):{label:'状态待读取',unknown:true,detail:'未读到当前连接状态；未推断模型是否可生成。'};
      return w;
    });
    grid.innerHTML=schemes.map(s=>`<header class="scheme-heading scheme-${s.id}"><span class="scheme-letter">${s.letter}</span><div><h2>${s.name}</h2><p>${s.description}</p></div></header>`).join('')+examples.map((example,i)=>schemes.map(s=>card(example,workflows[i],s.id)).join('')).join('');
    grid.setAttribute('aria-busy','false');
  }catch(error){
    grid.innerHTML='';grid.setAttribute('aria-busy','false');
    const message=document.getElementById('load-error');message.hidden=false;message.textContent='工作流目录没有载入。请确认本地服务正在运行，然后刷新。';
    console.error('封面方案载入失败',error);
  }
}
document.querySelector('.view-switch').addEventListener('click',event=>{
  const button=event.target.closest('[data-view]');if(!button)return;
  grid.dataset.view=button.dataset.view;
  document.querySelectorAll('[data-view]').forEach(item=>{if(item.tagName==='BUTTON')item.setAttribute('aria-pressed',String(item===button));});
  document.getElementById('options').scrollLeft=0;
});
init();
