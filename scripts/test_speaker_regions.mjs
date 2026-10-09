import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import {
 normalizeSpeakerRegions,serializeSpeakerRegions,normalizedRegion,
 clearSpeakerRegionsForMedia,speakerRegionsControl,syncSpeakerRegionPickers,
} from '../public/speaker-regions.js';
import {catalogSubmission,catalogHistorySnapshot} from '../public/catalog-submission.js';
import {prepareCatalogSnapshot} from '../public/catalog-ui.js';
import {clearPointsForMedia} from '../public/point-picker.js';
import {controlField} from '../public/workflow-controls.js';

const field={id:'194:speaker_regions',nodeId:'194',key:'speaker_regions',kind:'speaker_regions',type:'text',value:'[]',label:'说话人物区域',mediaSlotId:'284'};
const pair=[{x:.05,y:.1,width:.35,height:.8},{x:.6,y:.1,width:.35,height:.8}];
const workflow=()=>({id:'local-card-101',catalogConnected:true,interface:{controls:[{...field}],texts:[],media:[{id:'284',kind:'image',required:true}],sourceHash:'source-fixture'},catalogConnection:{adapter:'generic',validation:'structural-verified',supportedControlIds:[field.id],controls:[{...field}],media:[{id:'284',kind:'image',required:true}]}});
const draft=value=>({catalogValues:{[field.id]:value},catalogTexts:{},refs:[{catalogSlot:'284',kind:'image',src:'/reference.png'}]});

test('partial draft keeps audio ordering and complete submission rejects missing second person',()=>{
 assert.deepEqual(normalizeSpeakerRegions([]),[null,null]);
 assert.deepEqual(normalizeSpeakerRegions([null,pair[1]]),[null,pair[1]]);
 assert.deepEqual(normalizeSpeakerRegions(JSON.stringify([pair[0]])),[pair[0],null]);
 for(const value of ['[]',JSON.stringify([pair[0]]),JSON.stringify([null,pair[1]])]){
  assert.throws(()=>catalogSubmission(workflow(),draft(value)),/分别框选/);
  assert.throws(()=>prepareCatalogSnapshot(workflow(),draft(value)),/分别框选/);
 }
});

test('valid historical regions keep normalized coordinates and audio identity after restore and submission',()=>{
 const w=workflow(),snapshot=catalogHistorySnapshot(w,{catalog_values:{[field.id]:JSON.stringify(pair)},catalog_assets:{284:'reference-id'}});
 assert.deepEqual(normalizeSpeakerRegions(snapshot.catalogValues[field.id]),pair);
 const restored={...draft(snapshot.catalogValues[field.id]),...snapshot};
 const submission=catalogSubmission(w,restored,{284:'reference-id'});
 assert.deepEqual(JSON.parse(submission.catalog_values[field.id]),pair);
 assert.deepEqual(submission.catalog_assets,{284:'reference-id'});
 assert.deepEqual(pair,[{x:.05,y:.1,width:.35,height:.8},{x:.6,y:.1,width:.35,height:.8}]);
});

for(const value of [null,{},'malformed',[pair[0],pair[1],pair[0]], [{...pair[0],extra:1},pair[1]], [{...pair[0],x:'0.1'},pair[1]], [{...pair[0],height:0},pair[1]], [{...pair[0],x:-.1},pair[1]], [{...pair[0],width:2},pair[1]], [{...pair[0],x:NaN},pair[1]], [{...pair[0],width:Infinity},pair[1]], [pair[0],pair[0]]]){
 test('invalid geometry cannot pass complete validation '+String(value),()=>assert.throws(()=>normalizeSpeakerRegions(value,{complete:true})));
}

test('subpixel floating point overflow has the same boundary as Python admission',()=>{
 assert.throws(()=>normalizeSpeakerRegions([{x:.5,y:0,width:.5000000005,height:1},pair[1]],{complete:true}),/超出/);
 assert.throws(()=>normalizeSpeakerRegions([{x:.5,y:0,width:Number.MIN_VALUE,height:1},pair[1]],{complete:true}),/有效|空|超出/);
});

test('submission canonicalizes valid padded historical JSON before Python length limit',()=>{
 const padded=' '.repeat(6001)+JSON.stringify(pair);
 const request=catalogSubmission(workflow(),draft(padded));
 assert.equal(request.catalog_values[field.id],serializeSpeakerRegions(pair));
 assert.equal(prepareCatalogSnapshot(workflow(),draft(padded)).catalogValues[field.id],serializeSpeakerRegions(pair));
});

test('replacing or removing this image invalidates only its speaker regions',()=>{
 const w=workflow();w.interface.controls.push({id:'other-regions',kind:'speaker_regions',mediaSlotId:'other'}, {id:'points',kind:'points',mediaSlotId:'video'});
 for(const clear of [clearSpeakerRegionsForMedia,clearPointsForMedia]){
  const d={catalogValues:{[field.id]:JSON.stringify(pair),'other-regions':JSON.stringify(pair),points:'old-points'},refs:[{id:'image-original'}]};
  clear(d,w,'284');
  assert.deepEqual(normalizeSpeakerRegions(d.catalogValues[field.id]),[null,null]);
  assert.equal(d.catalogValues['other-regions'],JSON.stringify(pair));
  assert.equal(d.catalogValues.points,'old-points');
  assert.deepEqual(d.refs,[{id:'image-original'}]);
 }
});

test('actual asset-binding function clears regions on a new picture and preserves them for same picture',()=>{
 const source=readFileSync(new URL('../public/app.js',import.meta.url),'utf8'),statement=source.split(/\r?\n/).find(line=>line.startsWith('function bindCatalogAsset('));
 assert.ok(statement);
 const w=workflow(),session={draft:draft(JSON.stringify(pair))};
 let refresh=0,saves=0;
 const context={workflow:()=>w,active:()=>session,clearPointsForMedia,toast:()=>{throw new Error('Unexpected rejection');},nextReferenceId:()=> '图片1',renumberDraftReferences:()=>{},refreshComposer:()=>{refresh++;},scheduleSave:()=>{saves++;}};
 runInNewContext(statement,context);
 assert.equal(context.bindCatalogAsset({id:'same',kind:'image',src:'/reference.png',name:'same'},'284',session),true);
 assert.deepEqual(normalizeSpeakerRegions(session.draft.catalogValues[field.id]),pair);
 assert.equal(context.bindCatalogAsset({id:'new',kind:'image',src:'/new-reference.png',name:'new'},'284',session),true);
 assert.deepEqual(normalizeSpeakerRegions(session.draft.catalogValues[field.id]),[null,null]);
 assert.equal(refresh,2);assert.equal(saves,2);
});

test('renderer uses the shared input identity and safely escapes labels and media URLs',()=>{
 const dangerous={...field,label:'<script>bad</script>'},d=draft(JSON.stringify(pair));d.refs[0].src='/image.png?x="<bad>';
 const html=speakerRegionsControl(d,dangerous,JSON.stringify(pair),'speaker-input');
 assert.ok(html.includes('data-catalog-field="194:speaker_regions"'));
 assert.ok(html.includes('&lt;script&gt;bad&lt;/script&gt;'));
 assert.equal(html.includes('<script>bad</script>'),false);
 assert.ok(html.includes('/image.png?x=&quot;&lt;bad&gt;'));
 assert.ok(controlField(d,field).includes('data-speaker-stage'));
 assert.equal(speakerRegionsControl({refs:[]},field,'[]','missing').includes('data-speaker-stage'),false);
});

test('renderer reports corrupt history instead of treating it as a valid complete region pair',()=>{
 const bad='[{"x":1,"y":0,"width":1,"height":1}]',html=speakerRegionsControl(draft(bad),field,bad,'bad-history');
 assert.match(html,/超出参考图/);
 assert.throws(()=>catalogSubmission(workflow(),draft(bad)),/超出参考图/);
});

// Minimal DOM boundary: production sync/event handlers perform every mutation,
// coordinate conversion, validation, selection, serialization and notification.
// No copies of the interaction implementation are used in this fixture.
class Element {
 constructor(attrs={},parent=null){this.attrs={...attrs};this.dataset=Object.fromEntries(Object.entries(attrs).filter(([k])=>k.startsWith('data-')).map(([k,v])=>[k.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase()),String(v)]));this.parent=parent;this.children=[];this.listeners={};this.style={};this.value='';this.textContent='';this.hidden=false;this.disabled=false;this.custom='';if(parent)parent.children.push(this);}
 matches(selector){return selector.split(',').some(s=>{const m=s.trim().match(/^\[([^\]=]+)(?:="([^"]*)")?\]$/);return m&&Object.hasOwn(this.attrs,m[1])&&(m[2]===undefined||this.attrs[m[1]]===m[2]);});}
 closest(selector){return this.matches(selector)?this:this.parent?.closest(selector)||null;}
 contains(node){return node===this||this.children.some(child=>child.contains(node));}
 querySelectorAll(selector){return this.children.flatMap(child=>[...(child.matches(selector)?[child]:[]),...child.querySelectorAll(selector)]);}
 querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
 setAttribute(k,v){this.attrs[k]=String(v);}
 addEventListener(name,fn){(this.listeners[name]||=[]).push(fn);}
 dispatchEvent(event){if(!event.target)Object.defineProperty(event,'target',{value:this,configurable:true});for(const fn of this.listeners[event.type]||[])fn(event);if(event.bubbles&&!event.stopped&&this.parent)this.parent.dispatchEvent(event);return true;}
 fire(type,extra={}){const e={type,target:this,bubbles:true,stopped:false,preventDefault(){this.prevented=true;},stopPropagation(){this.stopped=true;},...extra};this.dispatchEvent(e);return e;}
 setCustomValidity(message){this.custom=message;}
 get validity(){const n=Number(this.value),empty=this.value==='',min=Number(this.attrs.min),max=Number(this.attrs.max),step=Number(this.attrs.step);return {valid:!this.custom&&(empty?!this.attrs.required:Number.isFinite(n)&&n>=min&&n<=max&&Math.abs(n/step-Math.round(n/step))<1e-7)};}
 focus(){document.activeElement=this;}
 setPointerCapture(id){this.capture=id;}
 releasePointerCapture(id){assert.equal(this.capture,id);this.capture=null;}
 getBoundingClientRect(){return this.rect||{left:100,top:50,width:400,height:200};}
}
function fixture(t,{value=JSON.stringify(pair),image=true,loaded=true}={}){
 const oldDoc=globalThis.document;globalThis.document={activeElement:null};t.after(()=>{if(oldDoc===undefined)delete globalThis.document;else globalThis.document=oldDoc;});
 const box=new Element({'data-speaker-regions':'','data-speaker-index':'0'}),hidden=new Element({'data-catalog-field':field.id},box);hidden.value=value;
 const selects=[0,1].map(i=>new Element({'data-speaker-select':String(i)},box)),clear=new Element({'data-speaker-clear':''},box);
 let stage,photo,layer,cursor;
 if(image){stage=new Element({'data-speaker-stage':''},box);photo=new Element({},stage);photo.complete=loaded;photo.naturalWidth=loaded?400:0;photo.naturalHeight=loaded?200:0;layer=new Element({'data-speaker-layer':''},stage);cursor=new Element({'data-speaker-cursor':''},stage);cursor.hidden=true;stage.querySelector=((old)=>selector=>selector==='img'?photo:old(selector))(stage.querySelector.bind(stage));}
 const rendered=speakerRegionsControl(draft(value),field,value,'fixture'),numberAttributes=Object.fromEntries([...rendered.matchAll(/<input\b([^>]*data-speaker-axis="([^"]+)"[^>]*)>/g)].map(match=>[match[2],Object.fromEntries([...match[1].matchAll(/([\w:-]+)(?:="([^"]*)")?/g)].map(attr=>[attr[1],attr[2]??true]))]));
 const numbers=Object.fromEntries(['x','y','width','height'].map(axis=>[axis,new Element(numberAttributes[axis],box)])),status=new Element({'data-speaker-status':''},box),error=new Element({'data-speaker-error':''},box);
 const d=draft(value);let notifications=0;
 hidden.addEventListener('input',()=>{d.catalogValues[field.id]=hidden.value;notifications++;});
 syncSpeakerRegionPickers(box);
 return {box,hidden,selects,clear,stage,photo,layer,cursor,numbers,status,error,d,get notifications(){return notifications;},drag(a,b,id=7){const rect=stage.getBoundingClientRect(),event=p=>({button:0,pointerId:id,clientX:rect.left+rect.width*p.x,clientY:rect.top+rect.height*p.y});stage.fire('pointerdown',event(a));stage.fire('pointermove',event(b));stage.fire('pointerup',event(b));},key:key=>stage.fire('keydown',{key})};
}

test('drag in either direction commits clamped normalized coordinates and one draft notification',t=>{
 const f=fixture(t,{value:'[]'});
 f.drag({x:.8,y:.9},{x:.2,y:.1});
 const region=normalizeSpeakerRegions(f.hidden.value)[0];
 for(const [key,expected]of Object.entries({x:.2,y:.1,width:.6,height:.8}))assert.ok(Math.abs(region[key]-expected)<1e-12);
 assert.equal(f.notifications,1);assert.equal(f.stage.capture,null);assert.equal(f.numbers.x.value,20);
 assert.deepEqual(normalizedRegion({x:.8,y:.9},{x:.2,y:.1}),region);
});

test('choosing audio 2 keeps the other person and duplicate rectangle produces inline error without throwing',t=>{
 const f=fixture(t);f.selects[1].fire('click');
 assert.doesNotThrow(()=>f.drag({x:pair[0].x,y:pair[0].y},{x:pair[0].x+pair[0].width,y:pair[0].y+pair[0].height}));
 assert.deepEqual(normalizeSpeakerRegions(f.hidden.value),pair);
 assert.match(f.error.textContent,/相同|不同/);
 assert.equal(f.stage.capture,null);
 assert.equal(f.notifications,0);
});

test('small click is rejected while a later real drag still works',t=>{
 const f=fixture(t,{value:'[]'});f.drag({x:.1,y:.1},{x:.101,y:.101});
 assert.equal(f.notifications,0);assert.deepEqual(normalizeSpeakerRegions(f.hidden.value),[null,null]);
 assert.match(f.error.textContent,/有效区域/);
 f.drag({x:.1,y:.1},{x:.4,y:.8});assert.equal(f.notifications,1);
});

test('Escape cancels keyboard selection and Delete clears only the active audio person',t=>{
 const f=fixture(t);f.selects[1].fire('click');f.key('Enter');f.key('ArrowRight');f.key('Escape');
 assert.deepEqual(normalizeSpeakerRegions(f.hidden.value),pair);
 f.key('Delete');assert.deepEqual(normalizeSpeakerRegions(f.hidden.value),[pair[0],null]);assert.equal(f.notifications,1);
 f.clear.fire('click');assert.deepEqual(normalizeSpeakerRegions(f.hidden.value),[null,null]);assert.equal(f.notifications,2);
});

test('keyboard-only Enter and arrows create a region and prevent page movement',t=>{
 const f=fixture(t,{value:'[]'});assert.equal(f.key('Enter').prevented,true);
 assert.equal(f.key('ArrowRight').prevented,true);f.key('ArrowDown');f.key('Enter');
 const region=normalizeSpeakerRegions(f.hidden.value)[0];
 assert.equal(region.x,.5);assert.equal(region.y,.5);
 assert.ok(Math.abs(region.width-.01)<1e-12);assert.ok(Math.abs(region.height-.01)<1e-12);
 assert.equal(f.notifications,1);
});

test('pointer and keyboard cannot create regions before the image has loaded',t=>{
 const f=fixture(t,{value:'[]',loaded:false});
 f.drag({x:.1,y:.1},{x:.4,y:.8});
 assert.equal(f.notifications,0);assert.match(f.error.textContent,/尚未读取/);
 f.key('Enter');f.key('ArrowRight');f.key('ArrowDown');f.key('Enter');
 assert.equal(f.notifications,0);assert.deepEqual(normalizeSpeakerRegions(f.hidden.value),[null,null]);
});

test('number editing updates current person only and preserves a complete valid serialized payload',t=>{
 const f=fixture(t);f.selects[1].fire('click');f.numbers.x.value='55';f.numbers.x.fire('input');
 const selected=normalizeSpeakerRegions(f.d.catalogValues[field.id]);
 assert.equal(selected[1].x,.55);assert.deepEqual(selected[0],pair[0]);
 assert.equal(f.notifications,1);assert.equal(f.error.hidden,true);
 assert.deepEqual(JSON.parse(catalogSubmission(workflow(),f.d).catalog_values[field.id]),selected);
});

test('invalid or incomplete numeric editing cannot silently remain a valid old selection',t=>{
 const f=fixture(t);f.numbers.x.value='90';f.numbers.x.fire('input');
 assert.equal(f.numbers.x.validity.valid,false);assert.match(f.error.textContent,/超出/);
 assert.throws(()=>catalogSubmission(workflow(),f.d),/分别框选/);
 f.numbers.x.value='';f.numbers.x.fire('input');
 assert.equal(normalizeSpeakerRegions(f.hidden.value)[0],null,'Blank edited axis must invalidate the current speaker before explicit submission validation');
 assert.throws(()=>catalogSubmission(workflow(),f.d),/分别框选/);
 assert.deepEqual(normalizeSpeakerRegions(f.hidden.value)[1],pair[1]);
});

test('initializing the same control twice does not duplicate handlers or draft writes',t=>{
 const f=fixture(t);syncSpeakerRegionPickers(f.box);f.clear.fire('click');assert.equal(f.notifications,1);
});

test('without a reference image the numeric area controls are disabled',t=>{
 const f=fixture(t,{value:'[]',image:false});assert.ok(Object.values(f.numbers).every(n=>n.disabled));
});

test('loading a tall image constrains the entire stage and keeps region coordinates unchanged',t=>{
 const f=fixture(t),before=f.hidden.value;
 f.photo.naturalWidth=1000;f.photo.naturalHeight=2000;f.photo.fire('load');
 assert.equal(Number.parseFloat(f.stage.style.maxWidth)/(.5),320);
 assert.equal(f.hidden.value,before);assert.equal(f.notifications,0);
 f.photo.naturalWidth=2000;f.photo.naturalHeight=1000;f.photo.fire('load');
 assert.ok(Number.parseFloat(f.stage.style.maxWidth)/2<=320);
 assert.equal(f.hidden.value,before);
});
