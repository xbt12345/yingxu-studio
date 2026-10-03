import {referenceShelfMarkup,editReference,installReferenceShelf,toggleReferenceShelf} from './reference-editor.js?v=69.0';
import {outputActionMarkup,installOutputActionPlacement} from './output-actions.js?v=67.0';
import {installTimecodeControls} from './timecode-control.js?v=60.1';
import {installMultiCamera} from './multi-camera.js?v=60.1';
import {installProcessingDurations} from './processing-duration.js?v=60.1';
import {liveDurationControl,liveWorkflowEditor,installTrimPlayback} from './workflow-page.js?v=63.0';
import {installDirectoryPicker} from './directory-picker.js?v=60.1';
import {installWorkflowSelects} from './workflow-select.js?v=63.0';
import {annotateImage} from './region-annotation.js?v=54.0';
import {esc} from './data.js';
import {advancedFields} from './advanced.js?v=60.1';
import {controlField,controlSection,seedControls,syncControlChoices} from './workflow-controls.js?v=62.0';
import {catalogEditor,catalogCommonPanel,apiPanel,syncCameraGuide,syncOutpaintGuide,installCatalogVisualGuides,applyOutpaintValue} from './catalog-ui.js?v=63.0';

// The library renders production components with harmless sample values; no saving or generation.
const [catalog,schemas,live]=await Promise.all([
 fetch('local-catalog.json').then(r=>r.json()),fetch('workflow-interfaces.json').then(r=>r.json()),fetch('/api/workflows').then(r=>r.ok?r.json():[]).catch(()=>[])
]);
const records=catalog.workflows.map(w=>({...w,interface:schemas.workflows[w.id]}));
const blank=()=>({prompt:'保留原图主体，调整背景与光线。',refs:[],catalogValues:{},catalogTexts:{},catalogSeedModes:{}});
const source=id=>records.find(w=>w.id===id);
const examples=[];
const add=(id,title,note,w,render)=>{const d=blank();examples.push({id,title,note,w,d,render});};
function fieldExample(id,title,note,predicate){
 const w=records.find(w=>w.interface.controls.some(predicate)),f=w?.interface.controls.find(predicate);
 if(!f)throw new Error('Missing production control: '+id);
 add(id,title,note,w,d=>controlSection('',`<div class="catalog-fields">${controlField(d,f)}</div>`));
}
fieldExample('size','画面尺寸','原生宽高选项：三列尺寸卡；仅原节点允许时提供自定义输入。',f=>f.kind==='ratio'&&f.options?.some(o=>String(o.value??o)==='1024x1024')&&f.options.every(o=>/^\d+x\d+$/.test(String(o.value??o)))&&!f.customRange);
fieldExample('custom-size','自定义宽高','沿用原有像素范围及步长；预设和自定义对应同一字段。',f=>f.kind==='ratio'&&f.customRange);
fieldExample('ratio','画面比例','比例与具体宽高分开；比例卡的图形随比例变化。',f=>f.kind==='ratio'&&f.options?.some(o=>String(o.value??o).includes('16:9')));
fieldExample('megapixels','百万像素','像素总量使用 MP；标题右侧直接填写，下方等宽预设。',f=>f.key==='megapixels');
fieldExample('edge','边长与处理尺寸','预设与自定义均两项一行；输入聚焦只保留外层高亮。',f=>f.kind==='resolution'&&f.customRange&&f.key==='output_long_side');
add('choice','枚举选择','LoRA 分支、放大倍数和遮罩模式使用同一个圆角菜单；支持方向键、回车选择和 Esc 关闭。',source('local-card-109'),(d,w)=>controlSection('',`<div class="catalog-fields">${w.interface.controls.filter(f=>f.options&&['choice','upscale'].includes(f.kind)).map(f=>controlField(d,f)).join('')}</div>`));
fieldExample('toggle','功能开关','只用于原图确实支持的布尔功能；标签直接描述开启的作用。',f=>f.kind==='toggle');
fieldExample('number','数值与强度','强度、色彩、数量和修复值使用原范围及步长，不造统一百分比。',f=>f.kind==='strength');
fieldExample('color','调色强度','独立于视角与扩图；保留真实节点的数值范围和步长。',f=>f.kind==='color');
fieldExample('motion','动作参数','按源节点的帧数或强度直接输入，不推断为统一百分比。',f=>f.kind==='motion');
fieldExample('count','生成数量','套图数量沿用原节点的整数输入。',f=>f.kind==='count');
fieldExample('restoration','修复幅度','重绘与修复数值保留工作流自己的范围。',f=>f.kind==='restoration');
fieldExample('mask-source','掩膜来源','只列出此工作流实际连通的掩膜分支。',f=>f.kind==='mask');
fieldExample('style','风格选择','源工作流允许的风格选项共用圆角菜单。',f=>f.kind==='style');
fieldExample('playback','播放帧率','播放速度与输出尺寸分开，保持真实帧率单位。',f=>f.kind==='playback');
fieldExample('plain-edge','数值边长','只有数值的像素节点直接填写，不擅自补充预设或改变单位。',f=>f.kind==='resolution'&&!f.options&&!f.customRange);
fieldExample('text','任务模式','生成或编辑的方式；代码含义直接解释，修改对象仍在创作描述中填写。',f=>f.kind==='task'&&f.type==='text');
fieldExample('timecode','时间码','分、秒滚动选择，也可直接填写；保持节点原始单位。',f=>f.kind==='segment'&&f.type==='text');
fieldExample('segment','处理时长','选择处理全部剩余视频或指定秒数，沿用原有秒与帧的换算。',f=>f.kind==='duration'&&f.derived);
add('path','目录与匹配规则','选择本机文件夹取得完整路径，也可直接填写运行端目录；匹配规则保留原输入。',source('local-card-136'),(d,w)=>controlSection('',`<div class="catalog-fields">${w.interface.controls.filter(f=>f.kind==='filesystem'&&f.type==='text').map(f=>controlField(d,{...f,value:f.key==='pattern'?f.value:'示例目录'})).join('')}</div>`));
add('seed','随机与固定种子','随机模式保留数值框但禁用；切换固定后直接编辑。多路种子保留各自含义。',source('local-card-108'),(d,w)=>controlSection('',seedControls(w.interface.controls.filter(f=>f.kind==='seed'),d,{compact:true})));
add('camera','视角示意','拖动相机调机位与远近；滚轮单独调远近。',source('local-card-14'),(d,w)=>controlSection('',catalogCommonPanel({...w,interface:{...w.interface,controls:w.interface.controls.filter(f=>f.kind==='camera')}},d)));
add('multi-camera','多视角提示','每个编号均可拖动，参数与图示双向同步。',source('local-card-72'),(d,w)=>controlSection('',catalogCommonPanel(w,d)));
add('outpaint','扩图示意','左右、上下默认分别联动，可单独解除；输出尺寸与强度独立展示。',source('local-card-13'),(d,w)=>controlSection('',catalogCommonPanel({...w,interface:{...w.interface,controls:w.interface.controls.filter(f=>f.kind==='outpaint')}},d)));
function fragment(w,d,selector){const template=document.createElement('template');template.innerHTML=catalogEditor(w,d);return template.content.querySelector(selector)?.outerHTML||'';}
add('prompt','创作描述与反向提示词','正向、多分支和反向描述保持独立绑定；反向描述直接展示。',source('local-card-18'),(d,w)=>fragment({...w,interface:{...w.interface,texts:w.interface.texts.map(t=>({...t,value:t.role==='negative'?'模糊、水印':''}))}},d,'.wf-section:has(#prompt)')+fragment({...w,interface:{...w.interface,texts:w.interface.texts.map(t=>({...t,value:t.role==='negative'?'模糊、水印':''}))}},d,'.catalog-parameters'));
add('media','素材与区域标注','标题、预览和操作三块分离；标注是否必填以工作流为准。按钮跳转到真实工作区操作。',source('local-card-16'),(d,w)=>fragment(w,{...d,refs:[{id:'图片1',catalogSlot:w.interface.media[0].id,kind:'image',src:'assets/coast.jpg',name:'示例海岸'}]},'.catalog-media-inputs'));
for(const kind of ['video','audio']){
 const w=records.find(w=>w.interface.media.some(m=>m.kind===kind)),m=w.interface.media.find(m=>m.kind===kind);
 add('media-'+kind,kind==='video'?'视频素材':'音频素材','沿用正式素材卡，保留素材类型、替换与上传；原生播放控件按媒体类型显示。',w,(d,w)=>fragment(w,{...d,refs:kind==='video'?[{id:'视频1',catalogSlot:m.id,kind,src:'assets/award-film-10s.mp4',name:'示例视频'}]:[]},`[data-catalog-drop-slot="${m.id}"]`));
}
add('demo-range','演示滑轨与分段选项','仅用于内置演示工作流；不能把这些百分比复制为真实节点的参数。',{id:'image-video'},(d,w)=>controlSection('',advancedFields(d,w)));
const apiSource=records.find(w=>w.interface.apiProfiles?.length);
add('api','工作流自有 API','保持来源、地址、模型及密钥布局；真实密钥只在工作区填写。',apiSource,(d,w)=>apiPanel({...w,interface:{...w.interface,apiProfiles:[{...w.interface.apiProfiles[0],baseUrl:'https://api.example.com/v1',model:'示例模型'}]}},d));

const h3=live.find(w=>w.id==='h3-reference'),bernini=live.find(w=>w.id==='bernini-edit');
if(h3)add('duration-slider','视频时长滑轨','滑轨范围取自当前已接入工作流，数值随拖动实时变化。',h3,(d,w)=>controlSection('',liveDurationControl(w,{duration:w.fields.find(f=>f.key==='duration').default})));
if(bernini)add('video-trim','原视频与片段区间','预览、起止滑轨和时长来自同一个原视频组件；不会调用生成。',bernini,(d,w)=>{
 const values=Object.fromEntries(w.fields.map(f=>[f.key,f.default])),draft={...d,sourceDuration:10,refs:[{kind:'video',src:'assets/award-film-10s.mp4',name:'示例视频'}]};values.duration=3;
 const template=document.createElement('template');template.innerHTML=liveWorkflowEditor({w,d:draft,values,refs:'',error:'',upload:''});return template.content.querySelector('.wf-source').outerHTML;
});

const referenceSamples=[{id:'图片1',kind:'image',src:'assets/coast.jpg',name:'海岸参考'},{id:'图片2',kind:'image',src:'assets/forest.jpg',name:'森林参考'},{id:'图片3',kind:'image',src:'assets/portal-ocean.png',name:'场景参考'},{id:'图片4',kind:'image',src:'assets/mountain.jpg',name:'山景参考'},{id:'图片5',kind:'image',src:'assets/dunes.jpg',name:'沙丘参考'}];
let clearExampleShelf=()=>{};
function referenceExample(pinned=false,prompt=''){return `<div class="api-composer"><div class="api-prompt-layout">${referenceShelfMarkup(referenceSamples,{pinned})}<div class="writing-row"><div class="writing-area"><textarea aria-label="参考图布局示例" rows="4" placeholder="描述画面；参考图叠放在左侧，悬停向右展开。">${esc(prompt)}</textarea></div></div></div></div>`;}
add('reference-shelf','参考图折叠与编辑','左侧叠放，悬停向右展开并预览大图；全部展开可固定在上方。编辑只更新本页示例。',{id:'model'},()=>referenceExample());
add('output-actions','作品直接操作','悬停或聚焦显示图标；对比可在本页切换，其他按钮前往正式工作区。',{id:'model'},()=>`<article class="output" tabindex="0"><img src="assets/forest.jpg" alt="操作示例" style="width:100%;max-height:220px;object-fit:cover"><div class="output-action-bar" role="group" aria-label="作品操作示例">${outputActionMarkup({id:'library-example',type:'image',src:'assets/forest.jpg'},{icons:true})}</div></article>`);

function renderDemo(e){
 const template=document.createElement('template');template.innerHTML=e.render(e.d,e.w);
 for(const node of template.content.querySelectorAll('[id]')){const previous=node.id;if(previous==='wf-source-video')continue;node.id=e.id+'-'+previous;for(const label of template.content.querySelectorAll('[for]'))if(label.htmlFor===previous)label.htmlFor=node.id;}
 return template.innerHTML;
}
const root=document.getElementById('component-library');
root.innerHTML=examples.map(e=>`<article class="library-example" id="${e.id}"><header><h2>${e.title}</h2><p title="${esc(e.note)}">${esc(e.note)}</p><a href="studio.html?review=69.0#${e.w.id==='model'?'create':'workflow/'+e.w.id}" target="_blank" rel="noopener">在对应工作流中查看 ↗</a></header><div class="library-demo catalog-editor">${renderDemo(e)}</div></article>`).join('');
document.getElementById('library-index').innerHTML=examples.map(e=>`<a href="#${e.id}">${e.title}</a>`).join('');
const counts={};for(const w of records)for(const f of w.interface.controls)counts[f.kind]=(counts[f.kind]||0)+1;
document.getElementById('library-counts').textContent=`${records.length} 个本地工作流 · ${Object.values(counts).reduce((a,b)=>a+b,0)} 个已配置参数 · ${examples.length} 组组件示例 · 2 个独立接入页 / 12 个内置演示共用控件`;
let active=examples[0];
const context=e=>examples.find(x=>x.id===e.target.closest('.library-example')?.id);
const update=e=>{const host=document.getElementById(e.id);syncControlChoices(host,e.w,e.d);syncCameraGuide(host,e.w,e.d);syncOutpaintGuide(host,e.w,e.d);};
examples.forEach(update);
for(const type of ['pointerdown','focusin'])document.addEventListener(type,e=>{const example=context(e);if(example)active=example;},true);
installCatalogVisualGuides({getContext:()=>({w:active.w,d:active.d,panel:document.getElementById(active.id)}),onCommit:()=>update(active)});
document.addEventListener('input',event=>{
 const e=context(event);if(!e)return;
 if(event.target.dataset.liveField==='duration'){event.target.closest('.duration-panel').querySelector('output').textContent=event.target.value;event.target.style.setProperty('--range-progress',(Number(event.target.value)-Number(event.target.min))/(Number(event.target.max)-Number(event.target.min))*100+'%');return;}
 const id=event.target.dataset.catalogField,f=e.w.interface?.controls.find(f=>f.id===id);
 if(event.target.dataset.advanced){e.d.advanced||={};e.d.advanced[event.target.dataset.advanced]=Number(event.target.value);event.target.previousElementSibling.querySelector('output').innerHTML=esc(event.target.value)+'<small>%</small>';event.target.style.setProperty('--range-progress',event.target.value+'%');event.target.setAttribute('aria-valuetext',event.target.value+'%');return;}
 if(!f||!event.target.validity.valid)return;
 e.d.catalogValues[id]=f.type==='checkbox'?event.target.checked:f.type==='number'?Number(event.target.value):event.target.value;applyOutpaintValue(e.w,e.d,f.key,e.d.catalogValues[id]);update(e);
});
document.addEventListener('click',event=>{
 const e=context(event),button=event.target.closest('button');if(!e||!button)return;
 if(button.dataset.advancedChoice){e.d.advanced||={};e.d.advanced[button.dataset.advancedChoice]=button.dataset.value;button.parentElement.querySelectorAll('button').forEach(b=>{b.setAttribute('aria-pressed',String(b===button));b.classList.toggle('chosen',b===button);});return;}
 const id=button.dataset.catalogPreset||button.dataset.catalogChoice;
 if(id){const f=e.w.interface?.controls.find(f=>f.id===id);e.d.catalogValues[id]=f.type==='number'?Number(button.dataset.value):button.dataset.value;const input=[...document.getElementById(e.id).querySelectorAll('[data-catalog-field]')].find(n=>n.dataset.catalogField===id);if(input)input.value=button.dataset.value;update(e);}
 if(button.dataset.catalogSeedMode){e.d.catalogSeedModes[button.dataset.catalogSeedMode]=button.dataset.value;update(e);}
 if(e.id==='media'&&button.dataset.catalogAnnotate){annotateImage({src:'assets/coast.jpg',mode:'visual',optional:true,help:'组件示例，标注不写入素材库。',onSave:async()=>{}});return;}
 if(e.id.startsWith('media'))window.open(`studio.html?review=69.0#workflow/${e.w.id}`,'_blank','noopener');
});
document.addEventListener('change',event=>{
 const e=context(event);if(!e)return;
 const id=event.target.dataset.catalogCustomSize;
 if(id){const f=e.w.interface.controls.find(f=>f.id===id),v=event.target.value.replace(/[×X\s]+/g,'x'),m=v.match(/^(\d{3,4})x(\d{3,4})$/),r=f.customRange;
  const valid=m&&m.slice(1).every(x=>Number(x)>=r.min&&Number(x)<=r.max&&Number(x)%r.step===0);event.target.setCustomValidity(valid?'':'请按此工作流允许的范围与像素步长填写。');if(valid){e.d.catalogValues[id]=v;update(e);}else event.target.reportValidity();
 }
 if(event.target.dataset.apiField==='mode'){e.d.catalogApis={[event.target.dataset.catalogApi]:{mode:event.target.value}};document.querySelector('#api .library-demo').innerHTML=renderDemo(e);const key=document.querySelector('#api [data-api-field="apiKey"]');if(key){key.disabled=true;key.placeholder='请在真实工作区填写密钥';}}
});

// Trim example shares the production markup; changes remain local to this page.
document.addEventListener('input',event=>{
 if(!event.target.dataset.wfTrim)return;const box=event.target.closest('.wf-source'),start=box.querySelector('[data-wf-trim="start"]'),end=box.querySelector('[data-wf-trim="end"]');
 if(Number(start.value)>Number(end.value)-1){if(event.target===start)start.value=Math.max(0,Number(end.value)-1);else end.value=Math.min(Number(end.max),Number(start.value)+1);}
 box.querySelector('[data-trim-output="start"]').textContent=Number(start.value)+' 秒';box.querySelector('[data-trim-output="end"]').textContent=Number(end.value)+' 秒';
 const video=box.querySelector('video');video.pause();video.currentTime=event.target===start?Number(start.value):Math.max(Number(start.value),Number(end.value)-.01);
 const track=box.querySelector('.wf-trim');track.style.setProperty('--trim-start',Number(start.value)/Number(start.max)*100+'%');track.style.setProperty('--trim-end',Number(end.value)/Number(end.max)*100+'%');
});

clearExampleShelf=installReferenceShelf(document.querySelector('#reference-shelf .api-reference-shelf'));
installTrimPlayback();
installWorkflowSelects();
installProcessingDurations();
installMultiCamera();
installTimecodeControls();
installDirectoryPicker({getCommit:button=>{const e=examples.find(x=>x.id===button.closest('.library-example')?.id);return e?path=>{e.d.catalogValues[button.dataset.localDirectory]=path;}:null;}});

document.addEventListener('click',event=>{
 const output=event.target.closest('#output-actions button');if(output){if(output.dataset.select){const selected=output.getAttribute('aria-pressed')!=='true';output.setAttribute('aria-pressed',String(selected));output.classList.toggle('active',selected);output.setAttribute('aria-label',selected?'取消对比':'加入对比');output.title=selected?'取消对比':'加入对比';}else window.open('studio.html?review=69.0#create','_blank','noopener');return;}
 const example=event.target.closest('#reference-shelf');if(!example)return;
 const remove=event.target.closest('[data-remove]');if(remove){const index=referenceSamples.findIndex(r=>r.id===remove.dataset.remove);if(index>=0){if(referenceSamples[index].cutoutSrc)URL.revokeObjectURL(referenceSamples[index].cutoutSrc);referenceSamples.splice(index,1);}const pinned=example.querySelector('.api-reference-shelf').classList.contains('pinned');const prompt=example.querySelector('textarea').value;clearExampleShelf();example.querySelector('.api-composer').outerHTML=referenceExample(pinned,prompt);clearExampleShelf=installReferenceShelf(example.querySelector('.api-reference-shelf'));return;}
 const add=event.target.closest('[data-action="add-reference"]');if(add){window.open('studio.html?review=69.0#create','_blank','noopener');return;}
 const toggle=event.target.closest('[data-action="reference-stack"]');if(toggle){const shelf=toggle.closest('.api-reference-shelf');toggleReferenceShelf(shelf);}
 const preview=event.target.closest('[data-preview-ref]');if(preview){const ref=referenceSamples.find(r=>r.id===preview.dataset.previewRef);editReference({ref,cutoutSrc:ref.cutoutSrc,onSave:async result=>{ref.referenceEdits=result.edits;ref.referenceStrength=result.strength;if(result.settingsOnly)return;if(ref.cutoutSrc)URL.revokeObjectURL(ref.cutoutSrc);ref.cutoutSrc=result.cutout?URL.createObjectURL(result.cutout):null;const image=preview.querySelector('img');if(image.dataset.previousBlob)URL.revokeObjectURL(image.dataset.previousBlob);const url=URL.createObjectURL(result.image);image.src=url;image.dataset.previousBlob=url;}}).catch(console.error);}
});

installOutputActionPlacement(root);
