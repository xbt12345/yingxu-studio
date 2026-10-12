import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import {taskOperation,similarWorkflows} from '../public/workflow-experience.js';
import {workflowTitle} from '../public/workflow-presentation.js';

const read=path=>JSON.parse(readFileSync(new URL(path,import.meta.url),'utf8'));
const schemas=read('../public/workflow-interfaces.json').workflows;
const catalog=read('../public/local-catalog.json').workflows;
const workflows=catalog.map(w=>({...w,interface:schemas[w.id]}));
const workflow=id=>workflows.find(w=>w.id===id);

test('video clothes editing is identified by its actual goal and joins the clothes editing family',()=>{
 for(const id of ['local-card-27','local-card-49','local-card-61','local-card-116']){
  const w=workflow(id);
  assert.equal(w.output,'video',id);
  assert.ok(w.interface.media.some(m=>m.kind==='video'),`${id}: source has a video input`);
  assert.match(w.name,/衣服|换装/,`${id}: authored purpose`);
  assert.deepEqual(taskOperation(w),{key:'outfit',title:'视频换衣'});
  assert.equal(workflowTitle(w),'视频换衣');
 }
 const family=similarWorkflows(workflow('local-card-116'),workflows).map(w=>w.id);
 assert.deepEqual(family,['local-card-49','local-card-61','local-card-116']);
 assert(!family.includes('local-card-68'),'pose reference is a different operation');
 assert.deepEqual(similarWorkflows(workflow('local-card-3'),workflows).map(w=>w.id),['local-card-3','local-card-73'],'image clothes editing retains its own category');
});

test('shared WanAnimate name prefixes do not replace the authored face, subject or background goal',()=>{
 const background=workflow('local-card-24');
 assert.ok(background.interface.media.some(m=>m.label==='背景图'));
 assert.equal(workflowTitle(background),'视频背景替换');
 assert.equal(workflowTitle(workflow('local-card-25')),'视频人物替换');
 assert.match(workflow('local-card-31').name,/人脸替换/);
 assert.equal(workflowTitle(workflow('local-card-31')),'视频换脸');
 const poseFamily=similarWorkflows(workflow('local-card-26'),workflows).map(w=>w.id);
 for(const id of ['local-card-24','local-card-25','local-card-27','local-card-31'])assert(!poseFamily.includes(id),`${id} is not a pose-only operation`);
 assert(poseFamily.includes('local-card-23')&&poseFamily.includes('local-card-30'));
});

test('operation classification is a read-only projection for all 151 source interfaces',()=>{
 const before=JSON.stringify(workflows);
 for(const w of workflows){assert.ok(workflowTitle(w));assert(similarWorkflows(w,workflows).some(other=>other.id===w.id));}
 assert.equal(workflows.length,151);
 assert.equal(JSON.stringify(workflows),before,'catalog metadata, field values and targets stay intact');
 const first=taskOperation(workflow('local-card-27'));first.title='changed';
 assert.equal(taskOperation(workflow('local-card-27')).title,'视频换衣','returned labels cannot mutate the shared definition');
});
