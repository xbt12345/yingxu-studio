import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {rangeText,taskMeaning} from '../public/control-guidance.js';
import {isProcessingDuration,processingDuration} from '../public/processing-duration.js';
import {cameraGroups,multiCameraPoint,legacyCameraRanges} from '../public/multi-camera.js';
import {dragCamera,nudgeZoom} from '../public/camera-motion.js';
import {isTimecode,parseTimecode,formatTimecode,timecodeControl,timecodeValue} from '../public/timecode-control.js';
import {advancedFields} from '../public/advanced.js';

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
console.log(JSON.stringify({knownRanges:'passed',processingDurations:durations.length,cameraNodes:groups.length,sourcePromptOrder:'passed',cameraDragZoom:'passed',timecodeFields:times.length,timeRoundTrip:'passed',demoParametersPreserved:'passed'}));
