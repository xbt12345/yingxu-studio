import {rangeHint} from './control-guidance.js?v=60.1';
import {megapixelControl} from './parameter-controls.js?v=60.1';
import {I,esc} from './data.js';
import {controlSection,dimensionOptions} from './workflow-controls.js?v=62.0';

const options=(key,items,value,format=x=>x)=>`<div class="wf-options" role="group">${items.map(x=>`<button type="button" data-wf-choice="${key}" data-value="${esc(x)}" aria-pressed="${String(value)===String(x)}">${format(x)}</button>`).join('')}</div>`;
const section=(title,body,sub='')=>`<section class="wf-section"><div class="wf-section-title"><strong>${title}</strong>${sub?`<span>${sub}</span>`:''}</div>${body}</section>`;
const ratioLabel=v=>{const [a,b]=v.split(':').map(Number);return `<i class="wf-ratio-icon" style="aspect-ratio:${a}/${b}"></i>${v}`};
const qualityLabel=v=>({'0.2':'预览','0.5':'标准','1':'精细'})[v]||v;
const second=n=>`${Number(n).toFixed(2).replace(/\.?0+$/,'')} 秒`;
const trimPlayer=({id,src,name,replace,start,end,limit,kind})=>`<div class="wf-source wf-trim-source" data-trim-player="${kind}" aria-label="${esc(name)}，可在下方选择处理区间"><video id="${id}" src="${esc(src)}" preload="metadata" playsinline aria-label="${esc(name)}"></video><span>${esc(name)}</span><button type="button" data-action="${replace}">${replace==='replace-source'?'更换原视频':'选择素材'}</button><div class="wf-player-bar"><button type="button" data-trim-play="${kind}" aria-label="播放选定片段">▶</button><div class="wf-trim" style="--trim-start:${start/limit*100}%;--trim-end:${end/limit*100}%;--trim-playhead:${start/limit*100}%"><div class="wf-trim-track" data-trim-seek="${kind}"><span></span><i aria-hidden="true"></i></div><input type="range" min="0" max="${limit}" step="0.01" value="${start}" data-${kind}-trim="start" aria-label="片段起点"><input type="range" min="0" max="${limit}" step="0.01" value="${end}" data-${kind}-trim="end" aria-label="片段终点"></div><button type="button" data-trim-mute="${kind}" aria-label="静音">♪</button><button type="button" data-trim-fullscreen="${kind}" aria-label="全屏播放">⛶</button></div><div class="wf-trim-summary"><span>选取 <output data-trim-output="start">${second(start)}</output> — <output data-trim-output="end">${second(end)}</output></span><span>当前 <output data-trim-current aria-label="当前播放位置">${second(start)}</output></span></div></div>`;

const VIDEO_EDIT_IDS=new Set(['bernini-edit','video-edit','video-background','video-character','video-restyle','video-upscale']);
const isVideoEditWorkflow=w=>VIDEO_EDIT_IDS.has(w?.id)||w?.category==='video-edit'||w?.category==='视频编辑';
const referenceLabel=w=>({
 'bernini-edit':'参考画面',
 'video-edit':'修改参考图',
 'video-background':'新背景参考图',
 'video-character':'新角色参考图',
 'video-restyle':'风格参考图',
 'video-upscale':'参考素材'
}[w?.id]||'参考图片');

export function liveWorkflowEditor({w,d,values,refs,error,upload,imageUpload=upload,sourceUpload=upload,submitting}){
 const isEdit=w.id==='bernini-edit',source=d.refs.find(r=>r.kind==='video');
 const limit=Math.min(3615,Math.max(1,Math.floor((Number(d.sourceDuration)||15)*100)/100));
 const start=Math.min(Number(values.trim_start)||0,Math.max(0,limit-1)),end=Math.min(limit,start+Math.max(1,Number(values.duration)||1));
 const sourcePanel=isEdit?section('原视频',source?trimPlayer({id:'wf-source-video',src:source.src,name:source.name||'原视频',replace:'replace-source',start,end,limit,kind:'wf'}):`<div class="wf-source-empty">${sourceUpload}</div>`):'';
 const referencePanel=section(isEdit?'修改参考图':'参考素材',(refs&&d.refs.some(r=>!isEdit||r.kind==='image')?refs:imageUpload));
 const prompt=section(isEdit?'修改指令':'镜头描述',`<div class="writing-row"><div class="writing-area"><textarea id="prompt" aria-label="${isEdit?'修改指令':'镜头描述'}" spellcheck="false" maxlength="6000" placeholder="${esc(w.placeholder)}" rows="4">${esc(d.prompt||'')}</textarea></div></div>`);
 const controls=controlSection('',workflowPicturePanel(w,d,values)+(isEdit?'':liveDurationControl(w,values)))+controlSection('随机种子',liveSeedControl(w,d,values))+(isEdit?controlSection('反向提示词',`<textarea id="negative" class="negative-input" aria-label="反向提示词" placeholder="不希望出现的内容（可选）" rows="3">${esc(d.negative||'')}</textarea>`):'');
 return `<div class="wf-editor-scroll"><div class="wf-editor-inner">${sourcePanel+referencePanel+prompt+controls}${error}</div></div><footer class="wf-editor-footer"><button class="button primary generate" type="button" data-action="generate" ${submitting?'disabled':''}>${I('spark')}${submitting?'正在提交…':'生成 · 算力卡计费'} ${I('arrow')}</button></footer>`;
}

export function liveDurationControl(w,v){
 const f=w.fields.find(f=>f.key==='duration');
 return `<div class="duration-panel"><div class="duration-readout"><span>视频时长</span><strong><output id="live-duration-value">${v.duration}</output><small>秒</small></strong></div><input data-live-field="duration" id="live-duration" aria-label="视频时长" type="range" min="${f.min}" max="${f.max}" step="${f.step}" value="${v.duration}" style="--range-progress:${(v.duration-f.min)/(f.max-f.min)*100}%"><div class="duration-ends"><span>${f.min} 秒</span><span>${f.max} 秒</span></div></div>`;
}
export function liveSeedControl(w,d,v){
 const f=w.fields.find(f=>f.key==='seed'),mode=d.liveSeedMode||(v.seed<0?'random':'fixed');
 return `<div class="seed-setting"><div class="wf-options" role="group" aria-label="随机种子模式"><button type="button" data-live-seed-mode="random" aria-pressed="${mode==='random'}">每次随机</button><button type="button" data-live-seed-mode="fixed" aria-pressed="${mode==='fixed'}">固定种子</button></div><label class="live-field" for="live-seed"><span class="sr-only">固定种子值</span><input id="live-seed" data-live-field="seed" aria-label="固定种子值" required type="number" min="0" max="${f.max}" step="${f.step}" value="${Math.max(0,v.seed)}" ${mode==='random'?'disabled':''}></label></div>`;
}

export function outputDimensions(w,d,v){
 if(w.id==='h3-reference'){const [a,b]=(v.ratio||'16:9').split(':').map(Number),pixels=(v.megapixels||0.5)*1024*1024;return [Math.round(Math.sqrt(pixels*a/b)/32)*32,Math.round(Math.sqrt(pixels*b/a)/32)*32];}
 const video=document.getElementById('wf-source-video'),width=video?.videoWidth||d.sourceWidth,height=video?.videoHeight||d.sourceHeight;
 if(!width||!height)return null;
 const scale=(v.long_side||1024)/Math.max(width,height);return [Math.max(32,Math.round(width*scale/32)*32),Math.max(32,Math.round(height*scale/32)*32)];
}
export function parameterPreview(w,d,v){
 const dimensions=outputDimensions(w,d,v),ratio=dimensions?dimensions[0]/dimensions[1]:16/9;const width=Math.min(112,96*ratio),height=width/ratio;
 const ref=d.refs.find(r=>r.kind==='image'),src=ref?.src||`assets/${w.cover}`;
 return `<figure class="wf-dimension-preview"><div class="wf-preview-stage"><img src="${esc(src)}" alt="画幅示意" style="width:${width}px;height:${height}px"></div><figcaption><strong>${dimensions?`约 ${dimensions[0]} × ${dimensions[1]} px`:`长边 ${v.long_side} px`}</strong><span>${w.id==='h3-reference'?`${v.ratio} · ${v.megapixels} MP · ${v.duration} 秒`:'沿用原片比例 · '+(v.duration||1)+' 秒'}</span><small>画幅示意 · 非生成效果${!dimensions?'，导入视频后显示尺寸':''}</small></figcaption></figure>`;
}
export function workflowPicturePanel(w,d,v){
 const choose=(key,value,label,hint)=>`<button class="segment ${String(v[key])===String(value)?'selected':''}" data-live-choice="${key}" data-value="${value}" aria-pressed="${String(v[key])===String(value)}" ${hint?`data-help="${esc(hint)}"`:''}>${label}</button>`;
 const ratios=w.id==='h3-reference'?`<section class="picture-section"><h3>画面比例</h3><div class="catalog-ratio-options">${dimensionOptions(w.fields.find(f=>f.key==='ratio').options,v.ratio,r=>`data-live-choice="ratio" data-value="${esc(r)}"`)}</div></section>`:'<p class="panel-note">比例沿用原视频</p>';
 const f=w.fields.find(f=>f.key===(w.id==='h3-reference'?'megapixels':'long_side'));
 const resolution=f?.key==='megapixels'?megapixelControl({id:'live-megapixels',value:v.megapixels,min:f.min,max:f.max,step:f.step,options:f.options,inputAttrs:'data-live-field="megapixels"',presetAttrs:n=>`data-live-choice="megapixels" data-value="${n}"`}):f?`<section class="picture-section live-edge-controls"><h3>${w.id==='h3-reference'?'输出像素总量（百万像素）':'输出最长边（像素）'}</h3>${f.options?`<div class="segmented-options">${f.options.map(n=>choose(f.key,n,n+' px','')).join('')}</div>`:`<input type="number" data-live-field="${f.key}" value="${v[f.key]}" min="${f.min}" max="${f.max}" step="${f.step}" aria-label="输出像素总量">`}${rangeHint({...f,kind:'resolution'})}</section>`:'';
 return ratios+resolution;
}
export function referenceSizePanel(w,d,v){
 const size=outputDimensions(w,d,v)?.join(' × ')||'当前输出尺寸';
 return `<section class="picture-section"><h3>参考图处理尺寸</h3><div class="segmented-options">${[['match','匹配输出',`约 ${size} px`,'匹配输出画幅'],['max','自动上限','由节点决定','由模型决定尺寸']].map(([value,label,sub,hint])=>`<button class="segment ${v.ref_size===value?'selected':''}" data-live-choice="ref_size" data-value="${value}" aria-pressed="${v.ref_size===value}" ${hint?`data-help="${esc(hint)}"`:''}>${label}<small>${sub}</small></button>`).join('')}</div></section>`;
}

export function demoWorkflowMedia({w,d}){
 if(['image-edit','first-last','multi-video'].includes(w.id))return '';
 const isVideo=['video-edit','video-background','video-character','video-restyle','video-upscale'].includes(w.id);
 const needsSource=isVideo||['image-video','product','character','image-upscale'].includes(w.id);
 if(!needsSource)return '';
 const ref=d.refs.find(r=>r.kind===(isVideo?'video':'image'));
 const src=ref?.src||(isVideo?'assets/award-film-10s.mp4':`assets/${w.cover}`);
 const max=Math.max(1,Math.floor((Number(d.sourceDuration)||10)*100)/100);
 const start=Math.max(0,Math.min(Number(d.trimStart)||0,max-.01));
 const end=Math.min(max,Math.max(start+.01,Number(d.trimEnd)||max));
 return section(isVideo?'原视频':'参考画面',isVideo?trimPlayer({id:'wf-demo-video',src,name:ref?.name||'示例素材',replace:'replace-source',start,end,limit:max,kind:'demo'}):`<div class="wf-source wf-demo-source"><img src="${esc(src)}" alt="${ref?'已选参考素材':'示例画面'}"><span>${ref?esc(ref.name):'示例素材'}</span><button type="button" data-action="open-assets">${ref?'更换素材':'选择素材'}</button></div>`);
}

export function installTrimPlayback(){
 const updatePosition=video=>{const box=video.closest('.wf-source'),max=Number(box?.querySelector('input[type=range]')?.max)||1;box?.querySelector('.wf-trim')?.style.setProperty('--trim-playhead',Math.min(100,Math.max(0,video.currentTime/max*100))+'%');const output=box?.querySelector('[data-trim-current]');if(output)output.textContent=second(video.currentTime);};
 for(const event of ['seeked','loadedmetadata'])document.addEventListener(event,e=>{if(e.target.matches?.('#wf-source-video,#wf-demo-video'))updatePosition(e.target);},true);
 document.addEventListener('input',e=>{if(e.target.matches('[data-wf-trim],[data-demo-trim]'))queueMicrotask(()=>{const video=e.target.closest('.wf-source')?.querySelector('video');if(video)updatePosition(video);});});
 const videoFor=kind=>document.getElementById(kind==='wf'?'wf-source-video':'wf-demo-video');
 const limits=kind=>{const start=Number(document.querySelector(`[data-${kind}-trim="start"]`)?.value||0),end=Number(document.querySelector(`[data-${kind}-trim="end"]`)?.value||0);return{start,end};};
 const toggle=kind=>{const video=videoFor(kind);if(!video)return;if(!video.paused){video.pause();return;}const {start,end}=limits(kind);if(video.currentTime<start||video.currentTime>=end-0.03)video.currentTime=start;video.play().catch(()=>{});};
 document.addEventListener('click',e=>{
  const play=e.target.closest('[data-trim-play]');if(play){toggle(play.dataset.trimPlay);return;}
  const mute=e.target.closest('[data-trim-mute]');if(mute){const video=videoFor(mute.dataset.trimMute);if(video){video.muted=!video.muted;mute.textContent=video.muted?'♪̸':'♪';mute.setAttribute('aria-label',video.muted?'取消静音':'静音');}return;}
  const full=e.target.closest('[data-trim-fullscreen]');if(full){videoFor(full.dataset.trimFullscreen)?.closest('.wf-source')?.requestFullscreen?.();return;}
  const seek=e.target.closest('[data-trim-seek]');if(seek){const kind=seek.dataset.trimSeek,video=videoFor(kind),max=Number(document.querySelector(`[data-${kind}-trim="end"]`)?.max),{start,end}=limits(kind);if(video&&max){const box=seek.getBoundingClientRect(),position=Math.min(1,Math.max(0,(e.clientX-box.left)/box.width));video.currentTime=Math.min(end,Math.max(start,position*max));}return;}
  if(e.target.matches('#wf-source-video,#wf-demo-video'))toggle(e.target.id==='wf-source-video'?'wf':'demo');
 });
 document.addEventListener('timeupdate',e=>{const video=e.target;if(!video.matches?.('#wf-source-video,#wf-demo-video'))return;const kind=video.id==='wf-source-video'?'wf':'demo',{start,end}=limits(kind);updatePosition(video);if(!video.paused&&video.currentTime>=end-0.03&&end>start)video.pause();},true);
 document.addEventListener('play',e=>{if(!e.target.matches?.('#wf-source-video,#wf-demo-video'))return;const video=e.target,kind=video.id==='wf-source-video'?'wf':'demo',{start,end}=limits(kind);if(video.currentTime<start||video.currentTime>=end-0.03)video.currentTime=start;const button=video.closest('.wf-source')?.querySelector('[data-trim-play]');if(button){button.textContent='Ⅱ';button.setAttribute('aria-label','暂停选定片段');}},true);
 document.addEventListener('pause',e=>{if(!e.target.matches?.('#wf-source-video,#wf-demo-video'))return;const button=e.target.closest('.wf-source')?.querySelector('[data-trim-play]');if(button){button.textContent='▶';button.setAttribute('aria-label','播放选定片段');}},true);
 document.addEventListener('input',e=>{const kind=e.target.matches('[data-wf-trim]')?'wf':e.target.matches('[data-demo-trim]')?'demo':null;if(!kind)return;const video=videoFor(kind),{start,end}=limits(kind);if(video&&(video.currentTime<start||video.currentTime>end)){video.pause();video.currentTime=start;}},true);
}
