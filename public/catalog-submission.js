// Catalog IDs are the binding identity. Display keys may repeat across branches.
import {normalizeObjectIndices} from './object-indices.js?v=81.0';
import {referenceProvenance} from './live-history.js?v=81.0';
import {browserNumericControl,validateBrowserNumbers} from './numeric-contract.js?v=81.0';
const browserInterface=cfg=>({...cfg,controls:(cfg.controls||[]).map(browserNumericControl)});
export function effectiveCatalogInterface(w){
 const cfg=w?.interface||{controls:[],texts:[],media:[]},connection=w?.catalogConnection;
 if(connection?.adapter!=='generic'||catalogConnectionState(w).blocked)return browserInterface(cfg);
 const select=(items,ids)=>Array.isArray(ids)?items.filter(item=>ids.includes(item.id)):items;
 const merge=(items,overrides)=>items.map(item=>{const merged={...item,...(overrides||[]).find(other=>other.id===item.id)};if(merged.options&&item.options)merged.options=merged.options.map(option=>{const policy=item.options.find(old=>String(old?.value??old)===String(option?.value??option));return policy?.disabled?{...(typeof option==='object'?option:{value:option}),disabled:true,reason:policy.reason||''}:option;});return merged;});
 const media=select(cfg.media,connection.mediaIds??connection.supportedMediaIds).map(slot=>{
  const remote=connection.media?.find(m=>m.id===slot.id);
  const required=remote?.required??(remote?.optional===true?false:slot.required??(slot.optional===true?false:undefined));
  return {...slot,...remote,...(required===undefined?{}:{required})};
 });
 const profiles=Array.isArray(connection.apiProfiles)?(cfg.apiProfiles||[]).filter(profile=>connection.apiProfiles.some(item=>item.id===profile.id)):cfg.apiProfiles||[];
 return browserInterface({...cfg,controls:merge(select(cfg.controls,connection.supportedControlIds),connection.controls),texts:merge(select(cfg.texts,connection.textIds??connection.supportedTextIds),connection.texts),media,apiProfiles:merge(profiles,connection.apiProfiles)});
}

export function catalogConnectionState(w){
 const c=w?.catalogConnection,blocked=c?.validation==='blocked'||c?.available===false,verified=c?.validation==='live-verified',external=c?.adapter==='generic'&&c.external_api_account===true,feeNote=external?' · 外部 API 可能另收费':'',button=external?'生成 · 算力 / API 计费':'生成 · 算力卡计费';
 if(blocked)return {blocked:true,label:'暂不可生成',detail:c.blocking_reason||'需要先补齐运行依赖',button:'暂不可生成'};
 if(w?.catalogPendingApi)return {blocked:false,label:'待自有 API 验证',detail:'平台 API 额度不足 · 可填写自有 API'+feeNote,button:external?button:'生成 · 自有 API 计费'};
 if(w?.catalogConnected)return {blocked:false,label:verified?'已实测':'已接入 · 待实测',detail:(verified?'已有生成验证':'参数与执行图已核对，尚未生成验证')+feeNote,button};
 return {blocked:false,label:'演示模式',detail:'内置素材 · 不调用模型',button:'演示生成 · 免费'};
}

export function validateCatalogConstraints(w,d){
 const connection=w?.catalogConnection;if(connection?.adapter!=='generic')return;
 const cfg=effectiveCatalogInterface(w);
 for(const rule of connection.constraints||[]){
  if(rule.type!=='nonzero-size')continue;
  const width=cfg.controls.find(f=>f.id===rule.width),height=cfg.controls.find(f=>f.id===rule.height);
  if(!width||!height)throw new Error('工作流尺寸校验配置缺失，请刷新后重试。');
  if(Number(d.catalogValues?.[width.id]??width.value)===0&&Number(d.catalogValues?.[height.id]??height.value)===0)throw new Error('输出宽度和高度不能同时为 0。请至少填写一边的像素值，另一边可填 0 自动保持比例。');
 }
}

export function validateCatalogOptions(cfg,d){
 for(const field of cfg.controls||[]){const value=d.catalogValues?.[field.id]??field.value,option=field.options?.find(option=>String(option?.value??option)===String(value));if(option?.disabled===true)throw new Error(option.reason||`${field.label}的此选项暂不可用，请选择其他方式。`);}
}

function catalogTextValues(cfg,d){
 const primary=cfg.texts.find(t=>t.role==='prompt');
 return Object.fromEntries(cfg.texts.map(t=>[t.id,t.id===primary?.id?(d.prompt??d.catalogTexts?.[t.id]??t.value??''):(d.catalogTexts?.[t.id]??t.value??'')]));
}

export function catalogPromptProblem(w,d){
 const cfg=effectiveCatalogInterface(w),primary=cfg.texts.find(t=>t.role==='prompt'),texts=catalogTextValues(cfg,d);
 const missing=cfg.texts.find(t=>(t.required===true||t===primary&&!t.preserveWhenEmpty)&&!String(texts[t.id]).trim());
 return missing?{id:missing.id,message:`请先填写${missing.label||'创作描述'}。`}:null;
}

export function catalogSubmission(w,d,assetMap={}){
 validateCatalogConstraints(w,d);
 const cfg=effectiveCatalogInterface(w);
 validateBrowserNumbers(cfg,d);
 validateCatalogOptions(cfg,d);
 const values=Object.fromEntries(cfg.controls.map(f=>{const value=d.catalogValues?.[f.id]??f.value;return [f.id,f.kind==='indices'?normalizeObjectIndices(value):value];}));
 const texts=catalogTextValues(cfg,d);
 const assets=Object.fromEntries(cfg.media.filter(slot=>assetMap[slot.id]).map(slot=>[slot.id,assetMap[slot.id]]));
 return {catalog_values:values,catalog_texts:texts,catalog_assets:assets};
}

export function catalogHistorySnapshot(w,r){
 const values={...(r.catalog_values||{})},texts={...(r.catalog_texts||{})},assets={...(r.catalog_assets||{})};
 if(r.catalog_values===undefined&&r.settings){
  const sharedSeed=['local-card-11','local-card-15','local-card-16','local-card-17','local-card-18','local-card-20'].includes(w?.id);
  for(const f of w?.interface?.controls||[]){
   const key=f.kind==='seed'&&sharedSeed?'seed':f.key;
   if(!Object.hasOwn(r.settings,key)||r.settings[key]===undefined)continue;
   if(f.kind==='seed')for(const member of f.members||[f])values[member.id]=r.settings[key];
   else values[f.id]=r.settings[key];
  }
  const primary=w?.interface?.texts?.find(t=>t.role==='prompt'),negative=w?.interface?.texts?.find(t=>t.role==='negative');
  if(primary&&typeof r.prompt==='string')texts[primary.id]=r.prompt;
  if(negative&&typeof r.negative==='string')texts[negative.id]=r.negative;
  if(w?.id==='local-card-12')for(const [id,key]of [['171:text','prompt_turn2real'],['180:text','prompt_semireal']])if(Object.hasOwn(r.settings,key)&&typeof r.settings[key]==='string')texts[id]=r.settings[key];
 }
 for(const f of w?.interface?.controls||[])if(f.kind==='seed'){
  const executed=r.catalog_seed_values?.[f.id];
  if(!Object.hasOwn(values,f.id)&&Number.isSafeInteger(executed)&&executed>=Math.max(0,f.min??0)&&executed<=Math.min(f.max??Number.MAX_SAFE_INTEGER,Number.MAX_SAFE_INTEGER))values[f.id]=executed;
  if(values[f.id]!==undefined)for(const member of f.members||[f])values[member.id]=values[f.id];
 }
 return {catalogValues:values,catalogTexts:texts,catalogAssets:assets};
}

export function catalogReferenceSnapshots(w,r){
 const slots=Object.entries(r.catalog_assets||{}),counts={image:0,video:0,audio:0};
 return (r.references||[]).map((a,index)=>{
  const catalogSlot=a.catalog_slot||a.catalogSlot||slots.find(([,id])=>id===a.id)?.[0]||(w?.catalogConnection?.adapter!=='generic'?w?.interface?.media?.[index]?.id:undefined);
  const kind=Object.hasOwn(counts,a.kind)?a.kind:w?.interface?.media?.find(slot=>slot.id===catalogSlot)?.kind||'image';
  return {id:({image:'图片',video:'视频',audio:'音频'})[kind]+(++counts[kind]),kind,name:a.name,src:a.src,serverAssetId:a.id,available:a.available,catalogSlot,...referenceProvenance(a)};
 });
}

export const resultTypeLabel=type=>({image:'图像',video:'视频',audio:'音频',text:'文本'}[type]||'文件');
export const comparableResult=output=>['image','video'].includes(output.type);
export const referenceResult=output=>['image','video','audio'].includes(output.type);
