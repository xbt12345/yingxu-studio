import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {expectedDuration,expectedDurationText,pythonRound} from '../public/control-guidance.js';
import {controlField,syncControlChoices} from '../public/workflow-controls.js';

const recipe={kind:'h3-frame-grid',fps:24,minFrames:5,stepFrames:17,rounding:'python-round'};
const field={id:'132:value',key:'value',kind:'duration',label:'生成时长（秒）',type:'number',value:5,min:0,step:1,effectiveDuration:recipe};
// Expected frames include decoded 1-second real samples and exact Python tie cases.
for(const [seconds,frames] of [[0,5],[1,39],[5,124],[22/24,22],[22.5/24,22],[22.50001/24,39],
                             [21.5/24,22],[56.5/24,56],[56.50001/24,73],[124/24,124],[124.5/24,124],[124.50001/24,141]]){
 const got=expectedDuration(field,seconds);assert.equal(got.frames,frames,`seconds=${seconds}`);assert.equal(got.seconds,frames/24);
}
assert.equal(pythonRound(22.5),22);assert.equal(pythonRound(23.5),24);assert.equal(pythonRound(-2.5),-2);
assert.equal(expectedDurationText(field,1),'预计生成 1.625 秒');assert.equal(expectedDurationText(field,5),'预计生成 5.167 秒');
for(const value of ['',null,false,{},[],NaN,Infinity,-1,Number.MAX_VALUE])assert.equal(expectedDuration(field,value),null);
for(const effectiveDuration of [{...recipe,fps:16},{...recipe,rounding:'js-round'},{...recipe,kind:'arbitrary-expression'},{expression:'throw new Error()'}]){
 assert.equal(expectedDuration({...field,effectiveDuration},1),null);
}
const draft={catalogValues:{[field.id]:1}},before=structuredClone(field);
const html=controlField(draft,field);assert.match(html,/value="1"/);assert.match(html,/预计生成 1\.625 秒/);
assert.equal((html.match(/data-catalog-field=/g)||[]).length,1);assert.deepEqual(field,before);
const input={value:'1',selectionStart:1},hint={dataset:{effectiveDuration:field.id},textContent:'',parentElement:{setAttribute(name,value){this[name]=value;}}};
const root={querySelectorAll(selector){return selector==='[data-effective-duration]'?[hint]:[];},get innerHTML(){throw new Error('Input tree must not be replaced');},set innerHTML(v){throw new Error('No full render');}};
syncControlChoices(root,{interface:{controls:[field]}},draft);assert.equal(hint.textContent,'预计生成 1.625 秒');
draft.catalogValues[field.id]=5;syncControlChoices(root,{interface:{controls:[field]}},draft);
assert.equal(hint.textContent,'预计生成 5.167 秒');assert.match(hint.parentElement.title,/5\.167/);assert.equal(input.value,'1');assert.equal(input.selectionStart,1);
assert.deepEqual(field,before);assert.equal(draft.catalogValues[field.id],5,'display sync must not snap submitted seconds');
const schemas=JSON.parse(readFileSync('public/workflow-interfaces.json','utf8')).workflows;
for(const [card,id] of [[4,'69:value'],[52,'69:value'],[54,'121:value'],[56,'132:value'],[57,'8:value'],[65,'144:value'],[71,'16:value']]){
 const source=schemas['local-card-'+card].controls.find(c=>c.id===id);assert.deepEqual(source.effectiveDuration,recipe);
 assert.match(controlField({catalogValues:{[id]:1}},source),/预计生成 1\.625 秒/);
}
const repair=schemas['local-card-60'].controls.find(c=>c.id==='366:value');assert.equal(repair.effectiveDuration,undefined);assert.match(repair.help,/原片长度/);
console.log(JSON.stringify({realFrameSample:'passed',pythonHalfEvenBoundaries:'passed',typedRecipeOnly:'passed',liveHintWithoutInputReplacement:'passed',submittedSecondsUnchanged:'passed',sourcePinnedForms:7}));
