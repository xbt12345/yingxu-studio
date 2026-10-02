import {esc} from './data.js';

// Group by the operation a user wants, while preserving each workflow's schema.
const operations=[
 ['outfit','图片换衣',/换衣|服装|穿衣|换装/],
 ['outpaint','图像扩展',/图像扩展|扩图/],
 ['camera','视角调整',/多角度|多视角|视角|九视角/],
 ['pose','姿势迁移',/姿势|姿态/],
 ['face','人物替换',/换头|换脸|人物替换|角色替换/],
 ['real','动漫转真人',/动漫转真人/],
 ['inpaint','局部编辑',/局部重绘|标记替换|Inpaint/i],
 ['color','漫画上色',/漫画|韩漫|上色|去码|去白码/]
];
export function taskOperation(w){
 const name=w?.name||'';
 const known=operations.find(([, ,pattern])=>pattern.test(name));
 if(known)return {key:known[0],title:known[1]};
 return {key:w?.category||w?.id||'create',title:({'bernini-edit':'视频编辑','h3-reference':'参考图生视频'})[w?.id]||(/[\u4e00-\u9fff]/.test(w?.category||'')?w.category:w?.name)||'创作工具'};
}
export function similarWorkflows(w,list){
 const op=taskOperation(w);
 return list.filter(x=>x.id===w.id||(x.category===w.category&&taskOperation(x).key===op.key));
}
export function modelLabel(w){
 const name=w.name||'';
 const model=name.match(/Bernini|H3|qwen(?:image)?[\d.]*|klein[- ]?9b|nano[- ]?banana\d*|krea\d*|Z-Image[- ]?Turbo|flux[\w. -]*/i)?.[0];
 return model?model.replace(/^qwen/i,'Qwen').replace(/^klein/i,'Klein'):name.replace(/^\d{4}/,'');
}
export function originalReference(j,o){
 return (j.snapshot?.refs||[]).find(r=>r.kind===o.type&&r.src);
}
export function restoredInputs(snapshot,w){
 const d=JSON.parse(JSON.stringify(snapshot));
 d.error=null;
 if(d.catalogLive||d.liveSettings){
  d.liveSeedMode='fixed';d.catalogSeedModes={...(d.catalogSeedModes||{})};
  for(const f of w?.interface?.controls||[])if(f.kind==='seed'){
   for(const m of f.members||[f])if(d.catalogValues?.[m.id]!==undefined)d.catalogSeedModes[m.id]='fixed';
  }
 }
 return d;
}
export function matchesWork({o,j,s},query='',time='all',now=Date.now(),list=[]){
 const q=query.trim().toLowerCase(),w=list.find(x=>x.id===j.snapshot.workflowId);
 const searchable=[j.snapshot.prompt,o.label,s?.title,w?.name,w?.category].filter(Boolean).join(' ').toLowerCase();
 const age=time==='7'?7:time==='30'?30:0;
 return (!q||searchable.includes(q))&&(!age||Number(j.ended||j.started)>=now-age*86400000);
}

const categoryDescriptions={
 '文字生图':'写下描述，生成图像', '参考图与套图':'用参考图保持主体与风格',
 '图像编辑':'换装、扩图、换角度与局部修改', '图像增强与整理':'修复细节、放大与整理图像',
 '文字生视频':'用文字描述镜头与动作', '参考图生视频':'让参考画面动起来',
 '首尾帧生视频':'连接起始画面与结束画面', '视频编辑与人物替换':'修改人物或场景，保留原片运动',
 '动作迁移与舞蹈':'把动作参考迁移到新人物', '视频修复与扩展':'修复、放大与延展视频',
 '数字人与对口型':'结合人物与音频生成口型', '提示词辅助':'分析素材并整理描述',
 '素材格式工具':'读取、转换与整理素材'
};
export const categoryDescription=cat=>categoryDescriptions[cat]||cat;

function diagram(key){
 const picture=(x,y,w=95,h=78)=>`<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="8" fill="#2c263a" stroke="#756486"/><circle cx="${x+w*.72}" cy="${y+h*.27}" r="9" fill="#d2b9ec"/><path d="M${x+8} ${y+h-8}l${w*.28} -${h*.44} ${w*.23} ${h*.24} ${w*.2} -${h*.32} ${w*.21} ${h*.52}" fill="#75618d"/>`;
 const arrow='<path d="M145 90h32m-8-8 8 8-8 8" stroke="#d8c2f0" stroke-width="2" fill="none"/>';
 const person='<circle cx="160" cy="45" r="12" fill="#d3bbe8"/><path d="M145 64h30l13 38h-56z" fill="#9e83b9"/><path d="M149 102l-6 29m29-29 6 29" stroke="#c6a9e0" stroke-width="7" stroke-linecap="round"/>';
 if(key==='outfit')return `<path d="m62 38-32 19 13 30 18-8v61h67V79l18 8 13-30-32-19-23 17z" fill="#877096" stroke="#bfa3d5"/><path d="m202 38-32 19 13 30 18-8v61h67V79l18 8 13-30-32-19-23 17z" fill="#b6a3d6" stroke="#dec7f2"/>${arrow}`;
 if(key==='camera')return `<ellipse cx="160" cy="96" rx="117" ry="39" stroke="#685279" fill="none"/>${person}${[0,1,2,3,4,5,6,7,8].map(i=>{const a=i*Math.PI*2/9,x=160+116*Math.cos(a),y=96+39*Math.sin(a);return `<circle cx="${x}" cy="${y}" r="11" fill="#403149" stroke="#bd9fdb"/><text x="${x}" y="${y+4}" text-anchor="middle" fill="#eee1f6" font-size="11">${i+1}</text>`;}).join('')}`;
 if(key==='outpaint')return `<rect x="48" y="24" width="224" height="130" rx="9" stroke="#b9a2d4" stroke-dasharray="5 6" fill="#322637"/>${picture(108,48,104,84)}<path d="M95 89H65m9-8-9 8 9 8m151-8h30m-9-8 9 8-9 8" fill="none" stroke="#d8c2f0" stroke-width="2"/>`;
 if(key==='face'||key==='real'||key==='pose'||key==='动作迁移与舞蹈')return `<g transform="translate(-69 0)">${person}</g>${arrow}<g transform="translate(69 0)">${person}</g><path d="m80 75-18 18m178-18 18-18" stroke="#d1b3e8" stroke-width="7" stroke-linecap="round"/>`;
 if(key==='inpaint'||key==='color'||key==='图像编辑')return `${picture(58,30,204,122)}<rect x="152" y="60" width="74" height="62" rx="6" fill="#ceabf233" stroke="#e5cdf9" stroke-dasharray="4 4"/><path d="m177 102 15-24 17 10-15 24z" fill="#e3c9f6"/>`;
 if(key==='图像增强与整理')return `${picture(43,46,110,94)}<circle cx="216" cy="81" r="41" fill="#3d304a" stroke="#c9ace4" stroke-width="3"/><path d="m246 110 30 31" stroke="#c9ace4" stroke-width="8" stroke-linecap="round"/><path d="M192 80h47m-24-22v46" stroke="#d7b9ee" stroke-width="2"/>`;
 if(key==='数字人与对口型')return `${person}<path d="M50 76v26m12-45v62m12-37v18m172-24v26m12-45v62m12-37v18" stroke="#bea3d9" stroke-width="5" stroke-linecap="round"/><path d="M151 51q9 8 18 0" stroke="#675277" fill="none"/>`;
 if(key==='提示词辅助'||key==='文字生图'||key==='文字生视频')return `<rect x="38" y="45" width="97" height="93" rx="9" fill="#30273b" stroke="#705880"/><path d="M53 67h67M53 83h48M53 99h63M53 115h37" stroke="#c7acde" stroke-width="3"/>${arrow}${picture(190,45,92,93)}${key==='文字生视频'?'<path d="m222 77 21 14-21 14z" fill="#ede0fa"/>':''}`;
 if(key==='视频编辑与人物替换')return `<g transform="translate(-65 0)">${person}</g>${arrow}<g transform="translate(66 0)">${person}</g><rect x="30" y="24" width="260" height="130" rx="8" fill="none" stroke="#7e658e"/>${[0,1,2,3,4,5,6].map(i=>`<rect x="${43+i*35}" y="28" width="18" height="8" rx="2" fill="#756082"/>`).join('')}`;
 if(key==='视频修复与扩展')return `${picture(39,40,104,98)}${arrow}${picture(186,40,104,98)}<path d="M49 51l83 75M57 128l73-72" stroke="#635075" stroke-width="3"/><path d="m213 84 13 13 29-30" stroke="#e2c4f4" stroke-width="4" fill="none" stroke-linecap="round"/>`;
 if(key==='素材格式工具')return `<path d="M45 51h87l14 15h130v74H45z" fill="#4b3b59" stroke="#b799d1"/><rect x="69" y="36" width="65" height="92" rx="6" fill="#2b2435" stroke="#9978b3"/><path d="M83 62h35m-35 17h35m-35 17h25" stroke="#c8aadf" stroke-width="3"/><path d="M187 95h58m-10-10 10 10-10 10" stroke="#e0c6f3" fill="none" stroke-width="2"/>`;
 if(key==='参考图与套图')return `${picture(35,55,89,79)}${picture(116,35,89,79)}${picture(197,55,89,79)}`;
 return `${picture(38,40,106,101)}${arrow}${picture(187,40,96,101)}<path d="m219 76 23 14-23 14z" fill="#eeddfc"/>${key==='首尾帧生视频'?'<text x="63" y="162" fill="#a58bb8" font-size="11">首帧</text><text x="215" y="162" fill="#a58bb8" font-size="11">尾帧</text>':''}`;
}
export function taskCover(w,rows=[],category=false){
 const candidates=rows.filter(({j,o})=>j.real&&j.status==='done'&&j.snapshot.workflowId===w.id);
 const last=candidates.at(-1),op=taskOperation(w);
 if(last&&(last.o.type!=='video'||last.o.poster)){
  const {o,j}=last,ref=originalReference(j,o);
  if(o.type==='image'&&ref?.src&&ref.available!==false)return `<div class="task-cover-pair"><img src="${esc(ref.src)}" alt="原图" loading="lazy"><img src="${esc(o.src)}" alt="历史生成结果" loading="lazy"><span class="task-cover-arrow">→</span></div><span class="task-cover-note">原图 → 历史结果</span>`;
  return `${o.type==='video'?`<img src="${esc(o.poster)}" alt="历史视频封面" loading="lazy">`:`<img src="${esc(o.src)}" alt="历史生成结果" loading="lazy">`}<span class="task-cover-note">历史结果</span>`;
 }
 return `<svg class="task-cover-diagram" viewBox="0 0 320 180" role="img" aria-label="${esc(category?w.category:op.title)}任务示意"><rect width="320" height="180" fill="#201a29"/>${diagram(category?w.category:op.key)}</svg><span class="task-cover-note">任务示意</span>`;
}
