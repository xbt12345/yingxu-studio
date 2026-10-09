import {renderWorkflowCover} from './workflow-cover-art.js?v=88.0';

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
const durableSource=src=>typeof src==='string'&&src&&!src.startsWith('blob:')?src:'';
const currentAssetSource=(id,assets)=>{if(!id)return '';const asset=assets.find(a=>a.id===id);return asset?.src&&(asset.blob||durableSource(asset.src))?asset.src:'';};
const currentSource=(src,assets)=>durableSource(src)||(assets.some(a=>a.blob&&a.src===src)?src:'');
export function originalMediaReference(ref,assets=[]){
 const src=currentAssetSource(ref.originalAssetId===ref.serverAssetId&&ref.annotationMode==='mask'?null:ref.originalAssetId,assets)||(ref.originalAvailable===false?'':(ref.originalServerAssetId&&(ref.annotationMode!=='mask'||ref.originalServerAssetId!==ref.serverAssetId)?'/api/assets/'+encodeURIComponent(ref.originalServerAssetId)+'/file':'')||currentSource(ref.originalSrc,assets));
 if(src)return {...ref,src,available:true};
 const edited=ref.originalAssetId||ref.originalServerAssetId||ref.originalSrc||ref.annotationMode||ref.referenceEdits?.regions?.length||ref.referenceEdits?.cutouts?.length||ref.referenceEdits?.autoCutout;
 if(edited)return null; // A masked/edited input cannot stand in for a lost original.
 const plain=currentAssetSource(ref.assetId,assets)||(ref.serverAssetId?'/api/assets/'+encodeURIComponent(ref.serverAssetId)+'/file':'')||currentSource(ref.src,assets);
 return plain&&ref.available!==false?{...ref,src:plain}:null;
}
export function originalReferences(j,o,assets=[]){
 return (j.snapshot?.refs||[]).filter(r=>r.kind===o.type).map(r=>originalMediaReference(r,assets)).filter(Boolean);
}
export function originalReference(j,o,assets=[]){
 const ref=(j.snapshot?.refs||[]).find(r=>r.kind===o.type&&(r.src||r.assetId||r.serverAssetId||r.originalAssetId||r.originalServerAssetId||r.originalSrc));
 return ref?originalMediaReference(ref,assets):null;
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

export function taskCover(w,rows=[],category=false,assets=[],options={}){
 const candidates=rows.filter(({j,o})=>j.real&&j.status==='done'&&j.snapshot.workflowId===w.id);
 const last=candidates.at(-1);
 if(last&&(last.o.type!=='video'||last.o.poster)&&!options.omitImages){
  const {o,j}=last,refs=originalReferences(j,{type:'image'},assets),ref=o.type==='image'?originalReference(j,o,assets):refs[0];
  return renderWorkflowCover(w,{primary:o.type==='video'?o.poster:o.src,input:ref?.src,
   inputs:refs.map(r=>r.src),evidence:o.type==='image'&&ref?.src?'comparison':'history'},category);
 }
 return renderWorkflowCover(w,{omitImages:!!options.omitImages,evidence:'sample'},category);
}
