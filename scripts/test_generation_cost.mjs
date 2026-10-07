import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source=readFileSync(new URL('../public/platform-account.js',import.meta.url),'utf8').replace(/export /g,'');
class Node {
 constructor(tag='#text',value=''){this.tag=tag;this.value=value;this.childNodes=[];this.dataset={};this.attributes={};this.classes=new Set();this.classList={add:name=>this.classes.add(name),remove:name=>this.classes.delete(name)};this.isConnected=true;this.hidden=false;this.disabled=false;}
 append(...nodes){for(const node of nodes){if(node.parentElement)node.parentElement.childNodes=node.parentElement.childNodes.filter(child=>child!==node);this.childNodes.push(node);node.parentElement=this;}}
 replaceChildren(...nodes){for(const node of this.childNodes)node.parentElement=null;this.childNodes=[];this.append(...nodes);}
 get textContent(){return this.tag==='#text'?this.value:this.childNodes.map(node=>node.textContent).join('');}
 set textContent(value){this.replaceChildren(new Node('#text',String(value)));}
 get innerHTML(){return this.textContent;}
 set innerHTML(value){this.textContent=value;}
 setAttribute(name,value){this.attributes[name]=value;}
 getAttribute(name){return this.attributes[name]??null;}
 removeAttribute(name){delete this.attributes[name];if(name==='data-platform-price-state')delete this.dataset.platformPriceState;}
 querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
 querySelectorAll(selector){const key=selector==='[data-platform-original-generation]'?'platformOriginalGeneration':null;const result=[];for(const child of this.childNodes){if(selector==='svg'&&child.tag==='svg'||key&&child.dataset[key]!==undefined)result.push(child);result.push(...child.querySelectorAll(selector));}return result;}
 closest(){return this.root||this.parentElement;}
 cloneNode(deep){const clone=new Node(this.tag,this.value);clone.dataset={...this.dataset};clone.attributes={...this.attributes};if(deep)clone.append(...this.childNodes.map(node=>node.cloneNode(true)));return clone;}
}
const json=(value,status=200)=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json'}});
function fixture(handler=()=>json({workflow_id:'tool-one',configured:true,credits:17,amount_minor:17,currency:'CNY'}),{label='生成 · 算力卡计费',disabled=false,creationGeneration=false}={}){
 const footer=new Node('span');footer.textContent='费用按当前卡计时，本站不收积分';
 const button=new Node('button');button.disabled=disabled;if(creationGeneration)button.dataset.creationGeneration='';const left=new Node('svg'),right=new Node('svg'),text=new Node('#text',label);button.append(left,text,right);
 const root={querySelector:selector=>selector==='.composer-foot>span:last-child'?footer:null};button.root=root;
 let currentButton=button;const network=[];
 const document={querySelector:selector=>selector==='[data-action="generate"]'?currentButton:null,querySelectorAll:()=>[],createElement:tag=>new Node(tag)};
 const context=vm.createContext({document,location:{href:'http://127.0.0.1/studio.html#create',origin:'http://127.0.0.1',reload(){}},URL,Headers,Request,Response,Intl,Map,Number,String,Date,JSON,setTimeout,clearTimeout,confirm:()=>true,fetch:async(input,init)=>{network.push({input,init});return handler(input,init);}});
 vm.runInContext(source,context);vm.runInContext('platform.user={id:"user-one"};platform.identity={id:"user-one",csrfToken:"csrf-one"};',context);
 return {context,button,footer,network,left,right,text,switchButton(value){currentButton=value;}};
}
const draft={model:'seedream-4.5',type:'image',quality:'2K',count:2,duration:'10 秒',prompt:'private prompt',refs:[{src:'private material'}]};
const creation=(parameters,credits=4)=>({mode:'reference',configured:true,available:false,availability_reason:'该模型尚未接入生成服务，暂不能生成。',credits,amount_minor:credits,request:parameters});

test('configured workflow fee is inside the original button, with original icons recoverable',async()=>{
 const f=fixture();await f.context.refreshGenerationQuote('tool-one');
 assert.match(f.button.textContent,/生成17 积分/);assert.match(f.footer.textContent,/¥0\.17/);assert.doesNotMatch(f.footer.textContent,/不收积分/);
 assert.equal(f.button.disabled,false);assert.equal(f.button.childNodes[0].childNodes[0],f.left);assert.equal(f.button.querySelectorAll('svg').length,4);
 f.context.clearGenerationQuote();assert.deepEqual(f.button.childNodes,[f.left,f.text,f.right]);assert.match(f.footer.textContent,/本站不收积分/);
});

test('late quote from a previous workflow cannot change the new button or approve its fee',async()=>{
 let release;const f=fixture(input=>String(input).endsWith('tool-one')?new Promise(resolve=>{release=()=>resolve(json({configured:true,credits:99,amount_minor:99}));}):json({workflow_id:'tool-two',configured:true,credits:12,amount_minor:12}));
 const first=f.context.refreshGenerationQuote('tool-one');await f.context.refreshGenerationQuote('tool-two');release();await first;
 assert.match(f.button.textContent,/12 积分/);assert.doesNotMatch(f.button.textContent,/99 积分/);assert.equal(vm.runInContext('platform.quotes.get("tool-one").displayed',f.context),false);
});

test('a detached button never makes an unseen price approved',async()=>{
 let release;const f=fixture(()=>new Promise(resolve=>{release=()=>resolve(json({configured:true,credits:17,amount_minor:17}));}));
 const pending=f.context.refreshGenerationQuote('tool-one');f.button.isConnected=false;f.switchButton(null);release();await pending;
 assert.equal(vm.runInContext('platform.quotes.get("tool-one").displayed',f.context),false);
});

test('submitting and disabled states remain intact during quotation',async()=>{
 const f=fixture(undefined,{label:'正在提交…',disabled:true});await f.context.refreshGenerationQuote('tool-one');
 assert.equal(f.button.disabled,true);assert.equal(f.button.childNodes[0].hidden,false);assert.match(f.button.textContent,/正在提交/);assert.doesNotMatch(f.button.textContent,/17 积分/);assert.equal(vm.runInContext('platform.quotes.get("tool-one").displayed',f.context),false);
 const blocked=fixture(undefined,{disabled:true});await blocked.context.refreshGenerationQuote('tool-one');assert.equal(blocked.button.disabled,true);assert.match(blocked.button.textContent,/17 积分/);
});

test('missing price and failed quotes stay visibly unavailable rather than showing zero',async()=>{
 for(const handler of [()=>json({configured:false,credits:null}),()=>json({detail:'暂不可用'},503),()=>json({configured:true,credits:null})]){
  const f=fixture(handler);await f.context.refreshGenerationQuote('tool-one');assert.match(f.button.textContent,/费用待定|费用读取失败/);assert.doesNotMatch(f.button.textContent,/0 积分/);
 }
});

test('an explicitly configured zero fee is distinct from an absent fee',async()=>{
 const f=fixture(()=>json({configured:true,credits:0,amount_minor:0}));await f.context.refreshGenerationQuote('tool-one');assert.match(f.button.textContent,/0 积分/);assert.match(f.footer.textContent,/¥0\.00/);
});

test('free image quotation sends only pricing parameters and disables models without a generation provider',async()=>{
 const f=fixture((input,init)=>json(creation(JSON.parse(init.body))),{label:'生成',creationGeneration:true});vm.runInContext('installApiFetch();',f.context);
 await f.context.refreshCreationQuote(draft);
 const call=f.network[0],body=JSON.parse(call.init.body);assert.deepEqual(body,{model:'seedream-4.5',kind:'image',quality:'2K',count:2,duration:null});
 assert.match(f.button.textContent,/生成参考 4 积分/);assert.doesNotMatch(f.button.textContent,/演示|不扣费/);assert.match(f.footer.textContent,/尚未接入/);assert.equal(f.button.disabled,true);assert.equal(call.init.headers.get('X-CSRF-Token'),'csrf-one');assert.equal(call.init.headers.get('X-Expected-Credits'),null);assert.equal(f.network.length,1);
});

test('changes in model, quality, output count, kind, or video duration receive their own quote',async()=>{
 const f=fixture((input,init)=>json(creation(JSON.parse(init.body),JSON.parse(init.body).duration||JSON.parse(init.body).count)),{label:'生成',creationGeneration:true});
 const variants=[draft,{...draft,model:'flux-2-pro'},{...draft,quality:'1K'},{...draft,count:4},{...draft,type:'video',model:'seedance-2.0',quality:'720p',duration:'5 秒'},{...draft,type:'video',model:'seedance-2.0',quality:'720p',duration:'10 秒'}];
 for(const variant of variants)await f.context.refreshCreationQuote(variant);
 assert.equal(f.network.length,6);assert.match(f.button.textContent,/参考 10 积分/);
 await f.context.refreshCreationQuote(variants.at(-1));assert.equal(f.network.length,6);
});

test('video reference fees price the one video actually generated instead of a retained image count',async()=>{
 const f=fixture((input,init)=>json(creation(JSON.parse(init.body),JSON.parse(init.body).count*17)),{label:'生成',creationGeneration:true});
 for(const count of [2,4]){
  await f.context.refreshCreationQuote({...draft,type:'video',model:'seedance-2.0',quality:'720p',duration:'10 秒',count});
  assert.match(f.button.textContent,/参考 17 积分/);
 }
 assert.equal(f.network.length,1,'an image-only count does not change the current video quote');
 assert.equal(JSON.parse(f.network[0].init.body).count,1);
});

test('a quote resolving after submission begins cannot overwrite its busy state or approve an unseen price',async()=>{
 let release;const f=fixture(()=>new Promise(resolve=>{release=()=>resolve(json({configured:true,credits:17,amount_minor:17}));}));
 const pending=f.context.refreshGenerationQuote('tool-one');f.button.setAttribute('aria-busy','true');f.button.disabled=true;f.button.textContent='正在提交…';release();await pending;
 assert.equal(f.button.textContent,'正在提交…');assert.equal(f.button.disabled,true);assert.equal(vm.runInContext('platform.quotes.get("tool-one").displayed',f.context),false);
});

test('a quote from a left workflow cannot paint the free creation route',async()=>{
 let release;const f=fixture((input,init)=>String(input).startsWith('/api/account/quote/')?new Promise(resolve=>{release=()=>resolve(json({configured:true,credits:99,amount_minor:99}));}):json(creation(JSON.parse(init.body),4)));
 const pending=f.context.refreshGenerationQuote('tool-one');const free=new Node('button');free.textContent='生成';free.dataset.creationGeneration='';free.root=f.button.root;f.button.isConnected=false;f.switchButton(free);
 await f.context.refreshGenerationQuote(null);await f.context.refreshCreationQuote(draft);release();await pending;
 assert.match(free.textContent,/参考 4 积分/);assert.equal(free.disabled,true);assert.doesNotMatch(free.textContent,/99 积分/);assert.equal(vm.runInContext('platform.quotes.get("tool-one").displayed',f.context),false);
});

test('overlapping same-parameter requests share a network operation and restore only one original span',async()=>{
 let release;const f=fixture((input,init)=>new Promise(resolve=>{release=()=>resolve(json(creation(JSON.parse(init.body))));}),{label:'生成',creationGeneration:true});
 const first=f.context.refreshCreationQuote(draft),second=f.context.refreshCreationQuote(draft);assert.equal(f.network.length,1);release();await Promise.all([first,second]);
 assert.equal(f.button.querySelectorAll('[data-platform-original-generation]').length,1);f.context.clearCreationQuote();assert.deepEqual(f.button.childNodes,[f.left,f.text,f.right]);
});

test('creation quotation is identified by its explicit marker instead of presentation text',async()=>{
 const unrelated=fixture(undefined,{label:'生成'});await unrelated.context.refreshCreationQuote(draft);assert.equal(unrelated.network.length,0);assert.equal(unrelated.button.disabled,false);
 const marked=fixture((input,init)=>json(creation(JSON.parse(init.body))),{label:'生成',creationGeneration:true});await marked.context.refreshGenerationQuote('tool-one');assert.equal(marked.network.length,0);await marked.context.refreshCreationQuote(draft);assert.equal(marked.network.length,1);assert.equal(marked.button.disabled,true);
});

test('creation stays disabled while checking and when availability is omitted even if its fee is configured',async()=>{
 let release;const pending=fixture((input,init)=>new Promise(resolve=>{release=()=>resolve(json(creation(JSON.parse(init.body))));}),{label:'生成',creationGeneration:true});
 const request=pending.context.refreshCreationQuote(draft);assert.equal(pending.button.disabled,true);assert.match(pending.button.textContent,/核对费用/);release();await request;assert.equal(pending.button.disabled,true);
 const missing=fixture((input,init)=>json({...creation(JSON.parse(init.body)),available:undefined}),{label:'生成',creationGeneration:true});await missing.context.refreshCreationQuote(draft);assert.equal(missing.button.disabled,true);assert.match(missing.button.getAttribute('title'),/尚未接入/);
});

test('a configured and explicitly available service enables its button, and clearing restores its original attributes',async()=>{
 const f=fixture((input,init)=>json({...creation(JSON.parse(init.body)),available:true}),{label:'生成',disabled:true,creationGeneration:true});f.button.setAttribute('title','原始服务提示');
 await f.context.refreshCreationQuote(draft);assert.equal(f.button.disabled,false);assert.equal(f.button.getAttribute('title'),null);
 f.context.clearCreationQuote();assert.equal(f.button.disabled,true);assert.equal(f.button.getAttribute('title'),'原始服务提示');assert.deepEqual(f.button.childNodes,[f.left,f.text,f.right]);
 const ordinary=fixture((input,init)=>json(creation(JSON.parse(init.body))),{label:'生成',creationGeneration:true});await ordinary.context.refreshCreationQuote(draft);assert.equal(ordinary.button.disabled,true);ordinary.context.clearCreationQuote();assert.equal(ordinary.button.disabled,false);assert.equal(ordinary.button.getAttribute('title'),null);
});

test('clearing a creation quote cannot overwrite a submitting button or reenable it',async()=>{
 const f=fixture((input,init)=>json(creation(JSON.parse(init.body))),{label:'生成',creationGeneration:true});await f.context.refreshCreationQuote(draft);
 f.button.setAttribute('aria-busy','true');f.button.disabled=true;f.button.textContent='正在提交…';f.context.clearCreationQuote();assert.equal(f.button.disabled,true);assert.equal(f.button.textContent,'正在提交…');
});

test('out-of-order creation quote cannot replace the current parameter cost',async()=>{
 let release;const f=fixture((input,init)=>{const parameters=JSON.parse(init.body);return parameters.count===2?new Promise(resolve=>{release=()=>resolve(json(creation(parameters,4)));}):json(creation(parameters,8));},{label:'生成',creationGeneration:true});
 const first=f.context.refreshCreationQuote(draft);await f.context.refreshCreationQuote({...draft,count:4});release();await first;assert.match(f.button.textContent,/参考 8 积分/);assert.doesNotMatch(f.button.textContent,/参考 4 积分/);
});

test('unknown, failed, and conflicting creation quotes disable generation without pretending it is free',async()=>{
 for(const handler of [()=>json({mode:'reference',configured:false,reason:'unsupported_model'}),()=>json({detail:'too many requests'},429),()=>{throw new Error('offline');},()=>json({mode:'reference',configured:true,credits:5,model:'wrong-model'})]){
  const f=fixture(handler,{label:'生成',creationGeneration:true});await f.context.refreshCreationQuote(draft);assert.equal(f.button.disabled,true);assert.match(f.button.textContent,/费用待定|费用读取失败/);assert.doesNotMatch(f.button.textContent,/演示|不扣费/);assert.doesNotMatch(f.button.textContent,/0 积分/);
 }
});

test('malformed creation fees cannot be interpreted as a configured free generation',async()=>{
 for(const invalid of [null,'0',-1,0.5]){
  const f=fixture(()=>json({mode:'reference',configured:true,credits:invalid}),{label:'生成',creationGeneration:true});await f.context.refreshCreationQuote(draft);
  assert.match(f.button.textContent,/费用读取失败/);assert.doesNotMatch(f.button.textContent,/0 积分|演示|不扣费/);assert.equal(f.button.disabled,true);
 }
});

test('monetary reference uses the declared exchange policy rather than an invented default',async()=>{
 const f=fixture(input=>String(input)==='/api/account/pricing-policy'?json({credit_policy:{credits_per_yuan:100}}):json({workflow_id:'tool-one',configured:true,credits:17}));
 await f.context.refreshGenerationQuote('tool-one');assert.match(f.footer.textContent,/¥0\.17/);assert.equal(f.network.length,2);
 const missing=fixture(input=>String(input)==='/api/account/pricing-policy'?json({credit_policy:{}}):json({workflow_id:'tool-one',configured:true,credits:17}));
 await missing.context.refreshGenerationQuote('tool-one');assert.match(missing.button.textContent,/17 积分/);assert.doesNotMatch(missing.footer.textContent,/¥/);
});

test('returning from a paid workflow to free creation removes stale paid consent',async()=>{
 const f=fixture();await f.context.refreshGenerationQuote('tool-one');assert.equal(vm.runInContext('platform.quotes.get("tool-one").displayed',f.context),true);
 await f.context.refreshGenerationQuote(null);assert.equal(vm.runInContext('platform.quotes.get("tool-one").displayed',f.context),false);assert.deepEqual(f.button.childNodes,[f.left,f.text,f.right]);
});

test('fetch consent headers use the server quote and never charge retrieve operations',async()=>{
 const f=fixture((input)=>String(input).startsWith('/api/account/quote/')?json({configured:true,credits:17,amount_minor:17}):json({ok:true}));vm.runInContext('installApiFetch();',f.context);await f.context.refreshGenerationQuote('tool-one');
 await f.context.fetch('/api/jobs',{method:'POST',body:JSON.stringify({workflow_id:'tool-one'})});const submit=f.network.find(call=>call.input==='/api/jobs');assert.equal(submit.init.headers.get('X-Expected-Credits'),'17');assert.equal(submit.init.headers.get('X-CSRF-Token'),'csrf-one');
 await f.context.fetch('/api/jobs/job-one/retrieve',{method:'POST'});const retrieve=f.network.find(call=>String(call.input).endsWith('/retrieve'));assert.equal(retrieve.init.headers.get('X-Expected-Credits'),null);
});
