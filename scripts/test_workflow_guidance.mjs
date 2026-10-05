import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {rangeText,taskMeaning} from '../public/control-guidance.js';
import {isProcessingDuration,processingDuration} from '../public/processing-duration.js';
import {cameraGroups,multiCameraPoint,legacyCameraRanges,cameraInputRanges,boundCameraInputs} from '../public/multi-camera.js';
import {dragCamera,nudgeZoom} from '../public/camera-motion.js';
import {isTimecode,parseTimecode,formatTimecode,timecodeControl,timecodeValue} from '../public/timecode-control.js';
import {advancedFields} from '../public/advanced.js';
import {installTrimPlayback,demoWorkflowMedia} from '../public/workflow-page.js';

const schemas=JSON.parse(readFileSync('public/workflow-interfaces.json')).workflows;
assert.equal(rangeText({min:1,step:1,kind:'resolution'}),'范围 ≥ 1 px · 步长 1');
assert.equal(rangeText({kind:'strength'}),'');
assert.equal(rangeText({min:0,max:10,step:.1,kind:'color'}),'范围 0–10 · 步长 0.1');
assert.equal(rangeText({min:0,max:1,kind:'seed'}),'');
const durations=Object.values(schemas).flatMap(w=>w.controls.filter(isProcessingDuration));
assert.equal(durations.length,9);
for(const f of durations){const html=processingDuration(f,f.value,'test');assert.ok(html.includes(`value="${f.value}"`));assert.equal((html.match(/data-catalog-field=/g)||[]).length,1);}
const generated=Object.values(schemas).flatMap(w=>w.controls).find(f=>f.kind==='duration'&&!f.label.includes('全部'));
assert.equal(isProcessingDuration(generated),false);
assert.ok(taskMeaning('r2v').includes('参考图生成视频'));
assert.ok(taskMeaning('rv2v').includes('视频编辑'));
const fields=schemas['local-card-72'].controls;
const groups=cameraGroups(fields);
// Real prompt-list routing order in graph-072, not incidental JSON node order.
assert.deepEqual(groups.map(([id])=>id),['108','109','110','111','112','119','121','122','120']);
assert.equal(groups.flatMap(([,fs])=>fs).length,27);
assert.equal(legacyCameraRanges.vertical_angle.max,90);
const realCameraInputs=['horizontal_angle','vertical_angle','zoom'].map(key=>{const field=fields.find(f=>f.key===key);return {min:String(field.min),max:String(field.max),step:String(field.step)};});
assert.equal(cameraInputRanges(realCameraInputs)[1].max,60);
assert.deepEqual(boundCameraInputs(realCameraInputs,{h:400,v:90,z:11}),{h:360,v:60,z:10});
assert.deepEqual(boundCameraInputs(realCameraInputs,{h:20.7,v:-31,z:5.17}),{h:21,v:-30,z:5.2});
assert.equal(cameraInputRanges([{},{},{}])[1].max,90);
assert.notDeepEqual(multiCameraPoint(0,0,5),multiCameraPoint(180,0,5));
assert.ok(multiCameraPoint(0,90,5).y<multiCameraPoint(0,0,5).y);
const center={x:220,y:172},distance=p=>Math.hypot(p.x-center.x,p.y-center.y);
assert.ok(distance(multiCameraPoint(90,0,10))<distance(multiCameraPoint(90,0,0)));
const start={h:0,v:30,z:5};
assert.deepEqual(dragCamera(start,0,0),start);
assert.ok(dragCamera(start,-35,8).z>start.z,'dragging toward the subject changes zoom');
assert.ok(dragCamera(start,35,-8).z<start.z,'dragging away changes zoom');
for(const h of [0,90,180,270,359])for(const v of [-30,0,60,90])for(const z of [0,5,10]){
 const n=dragCamera({h,v,z},30,16,{sx:65,sy:32,vertical:53,maxElevation:90});
 assert.ok(n.h>=0&&n.h<=360&&n.v>=-30&&n.v<=90&&n.z>=0&&n.z<=10);
}
assert.equal(nudgeZoom(9.9,.3),10);assert.equal(nudgeZoom(0,-.3),0);
const times=Object.values(schemas).flatMap(w=>w.controls.filter(isTimecode));assert.equal(times.length,12);
for(const f of times){const html=timecodeControl(f,f.value,'test');assert.equal((html.match(/data-catalog-field=/g)||[]).length,1);assert.ok(html.includes(`type="${f.type}" value="${f.value}"`),'original format remains untouched on render');}
for(const n of [0,5,59,60,102,3601,125.25])assert.equal(parseTimecode(formatTimecode(n)),n);
assert.equal(parseTimecode('0:5'),5);assert.equal(parseTimecode('60:01'),3601);
for(const text of ['1:60','-1:30','abc','1:2:3','1.5:30'])assert.equal(parseTimecode(text),null);
assert.equal(timecodeValue(90,'number'),90);assert.equal(timecodeValue(90,'text'),'1:30');
const demo=advancedFields({advanced:{}},{id:'image-video'});assert.ok(!demo.includes('<svg'));assert.ok(demo.includes('data-advanced="motion"')&&demo.includes('data-advanced="structure"'));
// Exercise the shared production play/reload handlers. This surface verifies
// asynchronous lifecycle/error behavior; native decoding remains a browser gate.
assert.match(demoWorkflowMedia({w:{id:'video-edit'},d:{refs:[]}}),/data-trim-feedback role="status" hidden/);
const notices=[],mediaListeners=new Map(),startInput={value:'1.25',max:'10'},endInput={value:'3.25',max:'10'};
const feedback={hidden:true,dataset:{}},message={textContent:'',title:''},retry={disabled:false},playButton={textContent:'▶',setAttribute(key,value){this[key]=value;}},currentOutput={textContent:''},trimStyle={setProperty(){}},box={querySelector(selector){return selector==='[data-trim-feedback]'?feedback:selector==='[data-trim-message]'?message:selector==='[data-trim-reload]'?retry:selector==='[data-trim-play]'?playButton:selector==='[data-trim-current]'?currentOutput:selector==='.wf-trim'?{style:trimStyle}:selector==='input[type=range]'?startInput:null;}};
const mediaDocument={addEventListener(type,listener){if(!mediaListeners.has(type))mediaListeners.set(type,[]);mediaListeners.get(type).push(listener);},getElementById:id=>id==='wf-source-video'?currentVideo:null,querySelector:selector=>selector==='[data-wf-trim="start"]'?startInput:selector==='[data-wf-trim="end"]'?endInput:null};
const emit=(type,target,extra={})=>{for(const listener of mediaListeners.get(type)||[])listener({target,...extra});};
class TestVideo extends EventTarget{
 constructor(){super();this.id='wf-source-video';this.source='/safe-sample.mp4';this.isConnected=true;this.currentTime=0;this.readyState=0;this.paused=true;this.playCalls=0;this.loadCalls=0;}
 getAttribute(name){return name==='src'?this.source:null;}
 closest(){return box;}
 matches(selector){return selector.includes('#wf-source-video');}
 pause(){this.paused=true;emit('pause',this);}
 load(){this.loadCalls++;this.readyState=0;}
 play(){this.playCalls++;return this.behavior().then(()=>{this.paused=false;emit('play',this);});}
}
let currentVideo=new TestVideo();currentVideo.behavior=()=>Promise.reject(Object.assign(new Error('No supported source was found.'),{name:'NotSupportedError'}));
const click=(selector,key)=>{const target={dataset:{[key]:'wf'},closest:other=>other===selector?target:null,matches:()=>false};emit('click',target);},settle=async()=>{for(let index=0;index<6;index++)await Promise.resolve();};
const previousDocument=globalThis.document,previousWarn=console.warn;globalThis.document=mediaDocument;console.warn=(label,error)=>notices.push({label,error});
try{
 installTrimPlayback();const handlers=mediaListeners.get('click').length;installTrimPlayback();assert.equal(mediaListeners.get('click').length,handlers,'shared playback installation is idempotent');
 assert.equal(feedback.hidden,true);click('[data-trim-play]','trimPlay');await settle();assert.equal(feedback.hidden,false);assert.match(message.textContent,/重新加载/);assert.match(message.title,/NotSupportedError/);assert.equal(feedback.dataset.trimError,'NotSupportedError');assert.equal(notices.length,1);assert.equal(notices[0].error.message,'No supported source was found.');
 currentVideo.behavior=()=>Promise.resolve();click('[data-trim-reload]','trimReload');assert.equal(currentVideo.loadCalls,1);assert.equal(retry.disabled,true);assert.equal(currentVideo.playCalls,1,'reload waits for metadata before starting selected playback');currentVideo.readyState=1;currentVideo.dispatchEvent(new Event('loadedmetadata'));await settle();assert.equal(currentVideo.playCalls,2);assert.equal(currentVideo.currentTime,1.25);assert.equal(feedback.hidden,true);assert.equal(retry.disabled,false);assert.equal(playButton.textContent,'Ⅱ');
 currentVideo.currentTime=3.394097;emit('timeupdate',currentVideo);assert.equal(currentVideo.paused,true);assert.equal(currentVideo.currentTime,3.25,'a delayed native timeupdate must clamp overshoot back to the selected endpoint');assert.equal(currentOutput.textContent,'3.25 秒','the displayed position is updated from the clamped time');assert.equal(playButton.textContent,'▶','selected playback still stops at the chosen endpoint');emit('timeupdate',currentVideo);assert.equal(currentVideo.currentTime,3.25,'the paused endpoint stays stable on the following seek/time event');
 const oldVideo=currentVideo;let rejectOld;oldVideo.behavior=()=>new Promise((resolve,reject)=>{rejectOld=reject;});click('[data-trim-play]','trimPlay');oldVideo.isConnected=false;currentVideo=new TestVideo();currentVideo.behavior=()=>Promise.resolve();rejectOld(Object.assign(new Error('old detached source'),{name:'AbortError'}));await settle();assert.equal(notices.length,1);assert.equal(feedback.hidden,true,'a rejected play promise on a replaced node cannot overwrite the new source UI');
 click('[data-trim-reload]','trimReload');currentVideo.error={code:4,message:'reload source unsupported'};currentVideo.dispatchEvent(new Event('error'));await settle();assert.equal(retry.disabled,false);assert.equal(feedback.dataset.trimError,'NotSupportedError');assert.match(message.title,/reload source unsupported/);assert.equal(notices.length,2);
 currentVideo.error=null;currentVideo.behavior=()=>Promise.reject(Object.assign(new Error('user activation required'),{name:'NotAllowedError'}));click('[data-trim-play]','trimPlay');await settle();assert.match(message.textContent,/再次点击播放/);
}finally{globalThis.document=previousDocument;console.warn=previousWarn;}
console.log(JSON.stringify({knownRanges:'passed',processingDurations:durations.length,cameraNodes:groups.length,sourcePromptOrder:'passed',cameraDragZoom:'passed',timecodeFields:times.length,timeRoundTrip:'passed',demoParametersPreserved:'passed',trimPlaybackFailureFeedback:'passed',metadataReloadRecovery:'passed',detachedMediaPromiseProtection:'passed'}));
