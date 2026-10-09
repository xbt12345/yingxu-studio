import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import {installTimecodeControls,timecodeControl,syncTimecodeControls} from '../public/timecode-control.js';

// Exercise the actual registered event handlers, not a duplicate conversion.
const handlers=new Map();let panel;
const attributeObject=()=>({attrs:{},setAttribute(key,value){this.attrs[key]=String(value);}});
const row=(offset,wheel)=>({...attributeObject(),dataset:{timeOffset:String(offset)},disabled:false,textContent:'',closest(selector){return selector==='[data-time-wheel]'?wheel:null;}});
const wheel=unit=>{const item={...attributeObject(),dataset:{timeWheel:unit},focus(){},matches(){return false},closest(selector){return selector==='[data-time-wheel]'?item:null;}};item.rows=[-2,-1,0,1,2].map(offset=>row(offset,item));item.querySelectorAll=selector=>selector==='[data-time-offset]'?item.rows:[];return item;};
globalThis.document={addEventListener(name,callback){handlers.set(name,callback);},createElement(){const wheels=[wheel('minute'),wheel('second')];return panel={...attributeObject(),style:{},wheels,querySelectorAll(selector){return selector==='[data-time-wheel]'?wheels:[];},querySelector(){return wheels[0];},getBoundingClientRect(){return {height:220,width:244};},remove(){},contains(){return true;}};},body:{append(){}},activeElement:null};
globalThis.window={addEventListener(){}};globalThis.innerWidth=1280;globalThis.innerHeight=800;
installTimecodeControls();
const evidence=[];
function runCase({raw,type='text',integer=true,minutes,seconds,next,step='second'}){
 const input={type,value:raw,dispatchEvent(){},checkValidity(){return true;}};
 const display={value:'',setCustomValidity(){},reportValidity(){},matches(){return true;}};
 const box={dataset:{...(integer?{timeIntegerSeconds:'true'}:{})},querySelector(selector){return selector==='[data-catalog-field]'?input:selector==='[data-time-display]'?display:{textContent:'片段终点（分:秒）'};}};
 const button={...attributeObject(),parentElement:{getBoundingClientRect(){return {left:120,top:180,bottom:220};}},closest(selector){return selector==='[data-timecode-control]'?box:null;}};
 syncTimecodeControls({querySelectorAll(){return [box];}});
 const displayed=display.value;
 handlers.get('click')({target:{closest(selector){return selector==='[data-time-open]'?button:null;}}});
 assert.equal(Number(panel.wheels[0].attrs['aria-valuenow']),minutes);
 assert.equal(Number(panel.wheels[1].attrs['aria-valuenow']),seconds);
 assert.equal(input.value,raw,'Opening must retain the saved native literal.');
 const selected=panel.wheels[step==='minute'?0:1];
 handlers.get('keydown')({target:selected,key:'ArrowDown',preventDefault(){}});
 assert.equal(input.value,next);
 evidence.push({nativeValue:raw,type,integer,displayed,openedMinutes:minutes,openedSeconds:seconds,step,after:input.value});
}

test('Review87 numeric text10: displays0:10, opens at10, first second step becomes0:11',()=>{
 const html=timecodeControl({label:'片段终点（分:秒）',type:'text',id:'159:end_time',kind:'segment',timecodeInput:'integer-seconds-or-mm:ss'},'10','test-end');
 assert.ok(html.includes('data-time-integer-seconds="true"'));
 assert.ok(html.includes('value="0:10"'));
 assert.ok(html.includes('data-catalog-field="159:end_time" type="text" value="10"'));
 runCase({raw:'10',minutes:0,seconds:10,next:'0:11'});
});
test('Integer text beyond one minute preserves its minute component',()=>runCase({raw:'120',minutes:2,seconds:0,next:'2:01'}));
test('Whitespace in a saved integer-text literal stays intact until editing',()=>runCase({raw:' 10 ',minutes:0,seconds:10,next:'0:11'}));
test('Existing mm:ss uses the same wheel offset as before',()=>runCase({raw:'1:42',integer:false,minutes:1,seconds:42,next:'1:43'}));
test('Reviewed integer-or-mm:ss metadata also accepts old nonpadded0:5',()=>runCase({raw:'0:5',minutes:0,seconds:5,next:'0:06'}));
test('Native numeric seconds remain numeric and retain fractions',()=>runCase({raw:2.5,type:'number',integer:false,minutes:0,seconds:2,next:3.5}));
test('Minute adjustment preserves existing seconds',()=>runCase({raw:'10',minutes:0,seconds:10,next:'1:10',step:'minute'}));

process.on('exit',()=>{fs.mkdirSync(new URL('../private/workflow-review88/',import.meta.url),{recursive:true});fs.writeFileSync(new URL('../private/workflow-review88/timecode-wheel-tests.json',import.meta.url),JSON.stringify({cases:evidence.length,evidence},null,2));});
