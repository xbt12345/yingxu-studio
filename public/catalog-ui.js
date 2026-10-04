import {taskOperation,similarWorkflows,modelLabel} from './workflow-experience.js?v=62.0';
import {multiCameraGuide,legacyCameraRanges,cameraGroups} from './multi-camera.js?v=60.1';
import {esc,I} from './data.js';
import {selectControl} from './workflow-select.js?v=62.0';
import {workflowPresentation} from './workflow-presentation.js?v=55.0';
import {controlValue as value,controlField as field,controlSection,seedControls} from './workflow-controls.js?v=70.1';
import {normalizePointSelection,serializePointSelection} from './point-picker.js?v=70.1';
import {normalizeObjectIndices} from './object-indices.js?v=70.1';
import {effectiveCatalogInterface,catalogConnectionState,validateCatalogConstraints} from './catalog-submission.js?v=70.0';
import {hasRemovedReference} from './reference-numbering.js';
import {cameraGuide,outpaintGuide,syncCameraGuide,syncOutpaintGuide,installCatalogVisualGuides,applyOutpaintValue} from './catalog-guides.js?v=60.1';
export {syncCameraGuide,syncOutpaintGuide,installCatalogVisualGuides,applyOutpaintValue};

export const randomSeed=()=>{const words=crypto.getRandomValues(new Uint32Array(2));return (words[0]&65535)*4294967296+words[1];};
const ui=effectiveCatalogInterface;
const textValue=(d,t)=>d.catalogTexts?.[t.id]??t.value??'';
const controls=w=>ui(w).controls.filter(f=>f.kind!=='seed');
const seeds=w=>ui(w).controls.filter(f=>f.kind==='seed');
export const catalogSeedMode=(d,f)=>d.catalogSeedModes?.[f.id]||'random';
function migrateLegacyFlux4bSize(w,d){
 if(w?.id!=='local-card-19'||d.catalogValues?.['site:size'])return;
 const saved=d.catalogValues||{},ratio=saved['86:ratio'],mp=Number(saved['86:megapixels']);
 const sides={'1:1':[1,1],'16:9':[16,9],'9:16':[9,16],'4:3':[4,3],'3:4':[3,4],'3:2':[3,2],'2:3':[2,3]}[ratio];
 if(!sides||!Number.isFinite(mp)||mp<=0)return;
 const pixels=mp*1024*1024,width=Math.round(Math.sqrt(pixels*sides[0]/sides[1])/32)*32,height=Math.round(Math.sqrt(pixels*sides[1]/sides[0])/32)*32;
 saved['site:size']=width+'x'+height;d.catalogValues=saved;
}

export function seedPanel(w,d,group){const fields=seeds(w).filter(f=>!group||f.uiGroup===group);return seedControls(fields,d,{compact:w.id==='local-card-108',showTitle:fields.length>1});}
export function prepareCatalogSnapshot(w,d,{redraw=false}={}){
 migrateLegacyFlux4bSize(w,d);
 const config=ui(w);if(!w.interface)throw new Error('工作流控件配置未加载，请刷新后重试。');
 const previous=d.catalogValues||{};
 d.catalogValues={...Object.fromEntries([...(w.fields||[]),...config.controls].map(f=>[f.id,f.derived?value({catalogValues:previous},f):f.value])),...previous};d.catalogSeedModes={...(d.catalogSeedModes||{})};
 for(const f of seeds(w)){const mode=redraw?'random':catalogSeedMode(d,f);const seed=mode==='random'?randomSeed()%(Math.min(f.max??Number.MAX_SAFE_INTEGER,Number.MAX_SAFE_INTEGER)+1):Number(value(d,f));if(!Number.isSafeInteger(seed)||seed<0||seed>(f.max??Number.MAX_SAFE_INTEGER))throw new Error(`${f.label}需要填写 0 至 ${f.max??Number.MAX_SAFE_INTEGER} 的整数。`);for(const m of f.members||[f]){d.catalogValues[m.id]=seed;d.catalogSeedModes[m.id]='fixed';}}
 for(const f of controls(w)){const v=value(d,f),r=f.customRange;if(f.kind==='indices'){d.catalogValues[f.id]=normalizeObjectIndices(v);continue;}if(f.kind==='points'){const points=normalizePointSelection(v);if(!points.positive.length)throw new Error('请在原视频起始帧上至少点选一个要保留的主体。');d.catalogValues[f.id]=serializePointSelection(points);continue;}if(r&&f.key==='size'){const m=String(v).match(/^([0-9]{3,4})x([0-9]{3,4})$/);if(!m||[Number(m[1]),Number(m[2])].some(n=>n<r.min||n>r.max||n%r.step))throw new Error('画面尺寸需填写 '+r.min+'–'+r.max+' 的 '+r.step+' 像素倍数。');continue;}if(f.type==='number'&&(!Number.isFinite(Number(v))||(f.integer&&!Number.isInteger(Number(v)))||(r?Number(v)<r.min||Number(v)>r.max||Math.abs(Number(v)/r.step-Math.round(Number(v)/r.step))>1e-6:(f.min!==undefined&&Number(v)<f.min)||(f.max!==undefined&&Number(v)>f.max))))throw new Error(`请检查${f.label}的范围。`);if(f.options&&!r&&!f.options.some(x=>String(x?.value??x)===String(v)))throw new Error(`请选择有效的${f.label}。`);}
 for(const f of controls(w)){if(!f.derived)continue;const v=Number(value(d,f)),r=f.derived;if(r.operation==='frames')d.catalogValues[r.targetId]=Math.round(v*r.fps);else if(r.operation==='audio-end'){const start=Number(d.catalogValues[r.startId]);if(v<=start)throw new Error('音频终点需要晚于起点。');d.catalogValues[r.targetId]=v-start;}}
 validateCatalogConstraints(w,d);
 d.workflowSourceHash=config.sourceHash;d.parameterSchemaVersion=config.schemaVersion;
 d.catalogApis={...(d.catalogApis||{})};for(const p of config.apiProfiles||[]){const v=d.catalogApis[p.id]||{mode:'platform'},hasBase=!!p.bindings?.baseUrl&&!p.keyOnly;if(v.mode==='custom'){if(hasBase){let url;try{url=new URL(v.baseUrl??p.baseUrl);}catch{throw new Error(`${p.label}的 Base URL 格式有误。`);}if(!['https:','http:'].includes(url.protocol)||!url.hostname)throw new Error(`${p.label}需要 HTTP 或 HTTPS 地址。`);}const model=v.model??p.model;if(!model?.trim())throw new Error(`请填写${p.label}的 Model 名称。`);if(p.modelOptions&&!p.modelOptions.some(option=>(option?.value??option)===model))throw new Error(`请选择${p.label}支持的模型。`);}d.catalogApis[p.id]={mode:v.mode==='custom'?'custom':'platform',...(hasBase?{baseUrl:v.mode==='custom'?(v.baseUrl??p.baseUrl):p.baseUrl}:{}),model:v.mode==='custom'?(v.model??p.model):p.model};}
 const primary=config.texts.find(t=>t.role==='prompt');if(primary)d.catalogTexts={...(d.catalogTexts||{}),[primary.id]:d.prompt??textValue(d,primary)};
 return d;
}
export function catalogEditor(w,d){
 migrateLegacyFlux4bSize(w,d);
 const cfg=ui(w),connectionState=catalogConnectionState(w),presentation=workflowPresentation[w.id],slotMarkup=slot=>{const ref=d.refs.find(r=>r.catalogSlot===slot.id),info=presentation?.slots[slot.id],label=info?.label||slot.label,canAnnotate=ref?.kind==='image'&&cfg.annotation&&(!cfg.annotation.slots||cfg.annotation.slots.includes(slot.id));return `<article class="catalog-input-card" data-catalog-drop-slot="${esc(slot.id)}" data-media-kind="${esc(slot.kind)}"><header><strong>${esc(label)}</strong>${slot.required===false?'<small class="catalog-optional">可选</small>':''}${ref?`<button type="button" class="catalog-ref-link" data-mention="${esc(ref.id)}" aria-label="引用${esc(ref.id)}">@${esc(ref.id)}</button>`:''}</header>${info?.help?`<small class="catalog-input-purpose">${esc(info.help)}</small>`:''}<div class="catalog-input-preview">${ref?`${ref.kind==='image'?`<button type="button" class="catalog-input-view" data-preview-slot="${esc(slot.id)}" aria-label="查看${esc(label)}"><img src="${esc(ref.src)}" alt=""></button>`:ref.kind==='video'?`<video src="${esc(ref.src)}" controls preload="metadata" playsinline></video>`:`<audio src="${esc(ref.src)}" controls></audio>`}<button class="catalog-input-remove" data-catalog-remove="${esc(slot.id)}" aria-label="移除${esc(label)}">${I('close')}</button>`:`<button type="button" class="catalog-input-empty" data-catalog-pick="${esc(slot.id)}">${I(slot.kind)}<span>选择${slot.kind==='image'?'图片':slot.kind==='video'?'视频':'音频'}</span></button>`}</div><div class="catalog-input-actions"><button type="button" data-catalog-pick="${esc(slot.id)}">${ref?'更换素材':'素材库'}</button><label>上传<input type="file" data-catalog-slot="${esc(slot.id)}" accept="${slot.kind}/*"></label>${canAnnotate?`<button type="button" class="catalog-input-annotate" data-catalog-annotate="${esc(slot.id)}">${ref.annotationStrokes?.length?'修改标注':'标注区域'}${cfg.annotation.optional?' · 可选':''}</button>`:''}</div></article>`};const slots=cfg.media.map(slotMarkup).join('');
 const positive=cfg.texts.filter(t=>t.role==='prompt'),negative=cfg.texts.filter(t=>t.role==='negative'),primary=positive[0];
 const extra=positive.slice(1).map(t=>`<label class="catalog-text-field"><span>${esc(t.label||'分支描述')}</span><textarea data-catalog-text="${esc(t.id)}" rows="3" placeholder="${esc(t.preserveWhenEmpty?'留空沿用工作流指令':t.label||'此分支的描述')}">${esc(textValue(d,t))}</textarea>${t.help?`<small class="catalog-field-help">${esc(t.help)}</small>`:''}</label>`).join('');
 const prompt=primary?`<section class="wf-section"><div class="wf-section-title"><strong>${esc(taskOperation(w).key==='outfit'?'换装描述':primary.label||'创作描述')}</strong></div><textarea id="prompt" data-catalog-text="${esc(primary.id)}" aria-label="工作流描述" rows="4" placeholder="${esc(primary.preserveWhenEmpty?'留空沿用工作流指令':promptHint(w))}">${esc(d.prompt??textValue(d,primary))}</textarea>${primary.help?`<small class="catalog-field-help">${esc(primary.help)}</small>`:''}</section>`:'';
 const main=controls(w),seedFields=seeds(w);
 const specialized=cfg.presentation?.kind&&cfg.presentation.kind!=='generic';
 const textMarkup=t=>t===primary?prompt:`<label class="catalog-text-field"><span>${esc(t.label)}</span><textarea data-catalog-text="${esc(t.id)}" rows="${t.label==='扩写指令'?3:4}" placeholder="${esc(t.preserveWhenEmpty?'留空沿用工作流指令':t.label)}">${esc(textValue(d,t))}</textarea>${t.help?`<small class="catalog-field-help">${esc(t.help)}</small>`:''}</label>`;
 const quick=(group,title)=>{
  if(!cfg.controls.some(c=>c.uiGroup===group))return '';
  return controlSection(group.startsWith('seed')?title:'',group.startsWith('seed')?seedPanel(w,d,group):catalogCommonPanel(w,d,group));
 };
 const mediaSection=items=>items.length?`<section class="wf-section catalog-media-inputs"><div class="wf-section-title"><strong>${w.category==='数字人与对口型'?'驱动素材':w.category==='视频修复与扩展'?'原始素材':'参考素材'}</strong></div><div class="catalog-input-grid">${items.map(slotMarkup).join('')}</div></section>`:'';
 let tailored='';
 if(specialized){
  if(w.category==='提示词辅助')tailored=(cfg.presentation.branches||[]).map(b=>`<section class="catalog-operation"><div class="catalog-operation-title"><strong>${esc(b.label)}</strong></div>${mediaSection(cfg.media.filter(m=>m.branchId===b.id))}${positive.filter(t=>t.branchId===b.id).map(textMarkup).join('')}<div class="catalog-inline-groups">${quick('seed:'+b.id,'提示词种子')}</div>${apiPanel(w,d,b.id)}</section>`).join('');
  else if(w.category==='素材格式工具')tailored=`<section class="wf-section catalog-source-fields"><div class="wf-section-title"><strong>素材来源</strong></div>${main.filter(f=>f.uiGroup==='location').map(f=>field(d,f)).join('')}</section><section class="wf-section"><div class="wf-section-title"><strong>读取与播放</strong></div><div class="catalog-inline-groups">${quick('read','读取设置')}${quick('playback','播放设置')}${quick('seed','素材抽取种子')}</div></section>`;
  else tailored=`${mediaSection(cfg.media)}${positive.map(textMarkup).join('')}<section class="wf-section"><div class="wf-section-title"><strong>${w.category==='数字人与对口型'?'片段与生成':'修复与输出'}</strong></div><div class="catalog-inline-groups">${quick('clip',w.category==='数字人与对口型'?'音频与片段':'处理片段')}${quick('output','输出设置')}${quick('seed',w.category==='数字人与对口型'&&seedFields.length>1?'分段生成种子':'随机种子')}</div></section>${apiPanel(w,d)}`;
 }
 const mediaBlock=slots?`<section class="wf-section catalog-media-inputs"><div class="wf-section-title"><strong>参考素材</strong><span>${cfg.media.filter(s=>d.refs.some(r=>r.catalogSlot===s.id)).length} / ${cfg.media.length} 已绑定</span></div><div class="catalog-input-grid">${slots}</div></section>`:'';
 const writingBlock=`${prompt}${extra?`<div class="catalog-prompt-variants">${extra}</div>`:''}`;
 const generic=`${mediaBlock}${writingBlock}${main.length?controlSection('',catalogCommonPanel(w,d)):''}${seedFields.length?controlSection(taskOperation(w).key==='outfit'?'随机种子':seedFields.length===1?seedFields[0].label:'随机种子',seedPanel(w,d)):''}${apiPanel(w,d)}`;

 return `<section class="wf-editor catalog-editor ${specialized?'catalog-tailored':''} ${w.category==='图像编辑'?'catalog-image-edit':''}"><div class="wf-editor-scroll"><div class="wf-editor-inner"><div class="catalog-status ${connectionState.blocked?'is-blocked':''}"><span>${esc(connectionState.label)}</span><small>${esc(connectionState.detail)}</small></div><p class="inline-error" data-removed-reference role="alert" ${hasRemovedReference(d.prompt)?'':'hidden'}>描述中有已移除的素材引用，请先修改。</p>${!w.interface?'<p class="inline-error">控件配置未加载，请刷新页面。</p>':''}${specialized?tailored:generic}${negative.length?`<section class="catalog-parameters workflow-inline-controls"><div class="wf-section-title"><strong>${taskOperation(w).key==='outfit'?'负面提示词':'反向提示词'}</strong><span>可选</span></div>${negative.map((t,i)=>`<label class="catalog-text-field"><span class="${negative.length===1?'sr-only':''}">${esc((negative.some((other,j)=>j!==i&&other.label===t.label)?'分支 '+(i+1)+' · ':'')+(t.label||'不希望出现的内容'))}</span><textarea data-catalog-text="${esc(t.id)}" rows="3" aria-label="${negative.length===1?'负面提示词':esc(t.label||'负面提示词')}" placeholder="可选">${esc(textValue(d,t))}</textarea></label>`).join('')}</section>`:''}${!prompt&&!slots&&!main.length&&!seedFields.length?'<p class="catalog-note">此工作流沿用原始配置，当前没有已确认的创作控件。</p>':''}</div></div><footer class="wf-editor-footer catalog-footer"><button type="button" class="button catalog-save" data-action="save-catalog">保存草稿</button><button type="button" class="button primary generate" data-action="generate" ${!w.interface||connectionState.blocked?'disabled':''}>${I('spark')}${esc(connectionState.button)} ${I('arrow')}</button></footer></section>`;
}
function promptHint(w){if(w.category==='提示词辅助')return '填写待分析的内容与要求';if(w.category==='数字人与对口型')return '描述人物表情与动作';if(w.category==='首尾帧生视频')return '描述从首帧到尾帧的变化';if(w.category==='动作迁移与舞蹈')return '说明人物、动作与背景的要求';if(w.category.includes('编辑'))return '说明修改对象与需要保留的部分';return '描述你想得到的结果';}
export function catalogSummary(w,d){return `<div class="catalog-draft-summary"><strong>草稿已保存</strong><p>${esc(w.name)}</p><small>未调用模型</small></div>`;}
export function catalogSelector(w,workflows){const family=similarWorkflows(w,workflows),title=workflowPresentation[w.id]?.title||taskOperation(w).title;return `<div class="catalog-tool-heading"><div class="catalog-tool-title"><h1>${esc(title)}</h1><small title="${esc(w.desc)}">${esc((workflowPresentation[w.id]?.help||w.desc||'').replace(/\n/g,' '))}</small></div>${selectControl({id:'catalog-switch',label:'切换相似创作工具',value:w.id,options:family.map(x=>({value:x.id,label:family.filter(y=>modelLabel(y)===modelLabel(x)).length>1?x.name.replace(/^\d{4}/,''):modelLabel(x)})),attrs:'data-menu-min-width="300"'})}</div>`;}
export function catalogOverview(w){const cfg=ui(w),status=catalogConnectionState(w),hasPrompt=cfg.texts.some(t=>t.role==='prompt'),input=hasPrompt?'准备描述与素材':cfg.media.length===2?'选择两张图片':'选择素材与参数';return `<div class="catalog-overview"><div class="wf-empty-art" aria-hidden="true">${I(w.output==='video'?'video':w.output==='audio'?'audio':w.output==='text'?'checklist':'image')}</div><h2>${status.blocked?'此工具需要先补齐依赖':'等待第一版作品'}</h2><p>${status.blocked?esc(status.detail):`在左侧${input}，再点击${w.catalogConnected?'生成':'演示生成'}。`}</p><small>${status.blocked?'已保留参数，可先审查编辑区。':w.catalogConnected?'提交后由算力卡执行；结果以实际返回为准。':'演示使用内置素材，不代表模型生成效果。'}</small></div>`;}

export function catalogCommonPanel(w,d,group){
 const all=controls(w).filter(f=>!group||f.uiGroup===group),grid=fields=>`<div class="catalog-fields">${fields.map(f=>field(d,f)).join('')}</div>`;
 if(!group&&w.id==='local-card-13')return controlSection('扩展范围',outpaintGuide(w,d)+grid(all.filter(f=>f.kind==='outpaint')),'data-control-module="outpaint"')+grid(all.filter(f=>f.kind!=='outpaint'));
 if(!group&&w.id==='local-card-14')return controlSection('视角设置',cameraGuide(w,d)+`<div class="catalog-camera-values">${grid(all.filter(f=>f.kind==='camera'))}</div>`,'data-control-module="camera"')+grid(all.filter(f=>f.kind!=='camera'));
 if(all.filter(f=>f.kind==='camera').length>3){
  const groups=new Map(cameraGroups(all));
  const batch=`<div class="catalog-camera-batch" data-control-module="multi-camera">${multiCameraGuide(all,d)}${[...groups.entries()].map(([node,fields],index)=>`<fieldset data-camera-row="${node}" data-camera-fields="${esc(JSON.stringify(['horizontal_angle','vertical_angle','zoom'].map(key=>fields.find(f=>f.key===key).id)))}"><legend><b>${index+1}</b>视角 ${index+1}<span data-camera-description="${node}"></span></legend>${grid(fields.map(f=>({...f,label:f.label.split(' · ').at(-1),guidanceRange:w.id==='local-card-72'?legacyCameraRanges[f.key]:undefined})))}</fieldset>`).join('')}</div>`;
  return batch+grid(all.filter(f=>f.kind!=='camera'));
 }
 return grid(all);
}

// API keys stay in memory for this tab; never serialize them into drafts or jobs.
const apiKeys=new Map();
export function setCatalogApiKey(wid,pid,key){apiKeys.set(wid+':'+pid,key);}
export function getCatalogApiKey(wid,pid){return apiKeys.get(wid+':'+pid)||'';}
export function apiPanel(w,d,branch){return (ui(w).apiProfiles||[]).filter(p=>!branch||p.branchId===branch).map(p=>{
 const v=d.catalogApis?.[p.id]||{},custom=v.mode==='custom',hasBase=!!p.bindings?.baseUrl&&!p.keyOnly,model=custom?(v.model??p.model):p.model;
 const modelInput=custom&&p.modelOptions?selectControl({id:'catalog-api-model-'+p.id.replace(/[^a-zA-Z0-9]/g,'-'),label:'Model 名称',value:model,options:p.modelOptions,attrs:`data-catalog-api="${esc(p.id)}" data-api-field="model"`}):`<input data-catalog-api="${esc(p.id)}" data-api-field="model" value="${esc(model)}" ${!custom?'readonly':''}>`;
 return `<section class="catalog-parameters catalog-api workflow-inline-controls"><div class="wf-section-title"><strong>${esc(p.label)}</strong><span>${custom?'自定义':'平台默认'}</span></div><label class="catalog-text-field"><span>API 来源</span>${selectControl({id:'catalog-api-mode-'+p.id.replace(/[^a-zA-Z0-9]/g,'-'),label:'API 来源',value:custom?'custom':'platform',options:[{value:'platform',label:'平台默认 API'},{value:'custom',label:'使用自己的 API'}],attrs:`data-catalog-api="${esc(p.id)}" data-api-field="mode"`})}</label>${hasBase?`<label class="catalog-text-field"><span>Base URL</span><input type="url" data-catalog-api="${esc(p.id)}" data-api-field="baseUrl" value="${esc(custom?(v.baseUrl??p.baseUrl):p.baseUrl)}" ${!custom?'readonly':''}></label>`:''}<label class="catalog-text-field"><span>Model 名称</span>${modelInput}</label><label class="catalog-text-field"><span>API key</span>${custom?`<input type="password" autocomplete="off" data-catalog-api="${esc(p.id)}" data-api-field="apiKey" value="${esc(apiKeys.get(w.id+':'+p.id)||'')}" placeholder="填写自己的密钥">`:'<input type="password" readonly placeholder="平台托管">'}</label>${custom?'<small class="catalog-field-help">密钥不会写入浏览器草稿</small>':''}</section>`;
 }).join('');}
