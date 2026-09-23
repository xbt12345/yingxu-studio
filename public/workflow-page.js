import {I,esc} from './data.js';

const options=(key,items,value,format=x=>x)=>`<div class="wf-options" role="group">${items.map(x=>`<button type="button" data-wf-choice="${key}" data-value="${esc(x)}" aria-pressed="${String(value)===String(x)}">${format(x)}</button>`).join('')}</div>`;
const section=(title,body,sub='')=>`<section class="wf-section"><div class="wf-section-title"><strong>${title}</strong>${sub?`<span>${sub}</span>`:''}</div>${body}</section>`;
const ratioLabel=v=>{const [a,b]=v.split(':').map(Number);return `<i class="wf-ratio-icon" style="aspect-ratio:${a}/${b}"></i>${v}`};
const qualityLabel=v=>({'0.2':'预览','0.5':'标准','1':'精细'})[v]||v;
const second=n=>`${Math.round(Number(n)*10)/10} 秒`;

export function liveWorkflowEditor({w,d,values,refs,error,upload,submitting}){
 const isEdit=w.id==='bernini-edit';
 const source=d.refs.find(r=>r.kind==='video');
 const limit=Math.min(3615,Math.max(1,Math.floor(Number(d.sourceDuration)||15)));
 const start=Math.min(Number(values.trim_start)||0,Math.max(0,limit-1));
 const end=Math.min(limit,start+Number(values.duration||1));
 const sourcePanel=section('原视频',`${source?`<div class="wf-source"><video id="wf-source-video" src="${esc(source.src)}" controls preload="metadata" playsinline></video><span>${esc(source.name||'原视频')}</span><button type="button" data-action="replace-source">更换原视频</button></div>`:`<div class="wf-source-empty">${upload}<p>先选择一段原视频，再定位要修改的片段。</p></div>`}${source?`<div class="wf-trim" style="--trim-start:${start/limit*100}%;--trim-end:${end/limit*100}%"><div class="wf-trim-track"><span></span></div><input type="range" min="0" max="${limit}" step="1" value="${start}" data-wf-trim="start" aria-label="片段起点"><input type="range" min="0" max="${limit}" step="1" value="${end}" data-wf-trim="end" aria-label="片段终点"><div class="wf-trim-readout"><output data-trim-output="start">${second(start)}</output><span>选取片段 · 最长 15 秒</span><output data-trim-output="end">${second(end)}</output></div></div>`:''}`);
 const materialPanel=section(isEdit?'参考画面':'参考素材',refs||upload,isEdit?'可选 · 最多 8 张图片':'可选 · 最多 9 张图片');
 const promptPanel=section(isEdit?'修改指令':'镜头描述',`<textarea id="prompt" spellcheck="false" maxlength="6000" placeholder="${esc(w.placeholder)}" rows="5">${esc(d.prompt||'')}</textarea>`,isEdit?'说明要改变什么、保留什么':'可在描述中用 @ 引用素材');
 const duration=section('视频时长',`<div class="wf-range-row"><input type="range" data-wf-field="duration" min="5" max="15" step="1" value="${values.duration}" aria-label="视频时长"><output data-wf-output="duration">${values.duration} 秒</output></div><div class="wf-range-ends"><span>5 秒</span><span>15 秒</span></div>`);
 const visual=isEdit?section('输出清晰度',options('long_side',[384,512,768,1024],values.long_side,x=>`${x} px`)):section('画面比例',options('ratio',['21:9','16:9','4:3','1:1','3:4','9:16'],values.ratio,ratioLabel))+section('输出清晰度',options('megapixels',[0.2,0.5,1],values.megapixels,qualityLabel));
 const behavior=isEdit?section('描述遵循程度',`<div class="wf-range-row"><input type="range" min="1" max="10" step="0.5" value="${values.cfg}" data-wf-field="cfg" aria-label="描述遵循程度"><output data-wf-output="cfg">${values.cfg}</output></div><div class="wf-range-ends"><span>保留原片</span><span>更多改动</span></div>`):section('参考图细节',options('ref_size',['match','max'],values.ref_size,x=>x==='match'?'适配画面':'保留更多细节'));
 const steps=isEdit?section('生成精度',`<div class="wf-range-row"><input type="range" min="12" max="60" step="2" value="${values.steps}" data-wf-field="steps" aria-label="生成精度"><output data-wf-output="steps">${values.steps} 步</output></div>`):section('生成精度',options('steps',[4,8],values.steps,x=>x===4?'快速 · 4 步':'标准 · 8 步'));
 return `<div class="wf-editor-scroll"><div class="wf-editor-inner">${isEdit?sourcePanel+materialPanel+promptPanel+visual+behavior+steps:materialPanel+promptPanel+visual+duration+behavior+steps}${error}<details class="wf-advanced"><summary>高级设置</summary><label>随机种子 <input data-wf-field="seed" type="number" min="-1" max="9007199254740991" step="1" value="${values.seed}"></label><small>-1 为每次随机；固定数值可复现。</small></details></div></div><footer class="wf-editor-footer"><button class="button primary generate" type="button" data-action="generate" ${submitting?'disabled':''}>${I('spark')}${submitting?'正在提交…':'生成 · 算力卡计费'} ${I('arrow')}</button><span>费用由算力卡计时</span></footer>`;
}

export function demoWorkflowMedia({w,d}){
 if(['image-edit','first-last','multi-video'].includes(w.id))return '';
 const isVideo=['video-edit','video-restyle','video-upscale'].includes(w.id);
 const needsSource=isVideo||['image-video','product','character','image-upscale'].includes(w.id);
 if(!needsSource)return '';
 const ref=d.refs.find(r=>r.kind===(isVideo?'video':'image'));
 const src=ref?.src||(isVideo?'assets/award-film-10s.mp4':`assets/${w.cover}`);
 const max=Math.max(1,Math.floor(Number(d.sourceDuration)||10));
 const start=Math.max(0,Math.min(Number(d.trimStart)||0,max-1));
 const end=Math.min(max,Math.max(start+1,Number(d.trimEnd)||max));
 const trim=isVideo?`<div class="wf-trim" style="--trim-start:${start/max*100}%;--trim-end:${end/max*100}%"><div class="wf-trim-track"><span></span></div><input type="range" min="0" max="${max}" step="1" value="${start}" data-demo-trim="start" aria-label="片段起点"><input type="range" min="0" max="${max}" step="1" value="${end}" data-demo-trim="end" aria-label="片段终点"><div class="wf-trim-readout"><output data-trim-output="start">${second(start)}</output><span>选取要处理的片段</span><output data-trim-output="end">${second(end)}</output></div></div>`:'';
 return section(isVideo?'原视频 · 定位要处理的片段':'参考画面',`<div class="wf-source wf-demo-source">${isVideo?`<video id="wf-demo-video" src="${esc(src)}" controls preload="metadata" playsinline></video>`:`<img src="${esc(src)}" alt="${ref?'已选参考素材':'示例画面'}">`}<span>${ref?esc(ref.name):'示例素材'}</span><button type="button" data-action="open-assets">${ref?'更换素材':'选择素材'}</button></div>${trim}`);
}
