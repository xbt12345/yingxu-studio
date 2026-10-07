import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source=readFileSync(new URL('../public/platform-account.js',import.meta.url),'utf8').replace(/export /g,'');
const admin={id:'admin-id',username:'admin-example',role:'admin',balance:0,held:0};

function fixture(user=admin){
 const listeners=new Map(),windowListeners=new Map(),events=[],classes=new Set(),elements=new Map(),network=[];
 const document={activeElement:null,body:{classList:{add:value=>classes.add(value),remove:value=>classes.delete(value)},append(element){elements.set(element.id,element);element.isConnected=true;}},
  getElementById:id=>elements.get(id)||null,querySelector:()=>null,querySelectorAll:()=>[],
  addEventListener(type,callback,capture=false){const list=listeners.get(type)||[];list.push({callback,capture});listeners.set(type,list);},
  dispatchEvent(event){events.push(event);for(const {callback} of listeners.get(event.type)||[])callback(event);},
  createElement(){return {style:{},attributes:{},offsetWidth:252,offsetHeight:290,setAttribute(key,value){this.attributes[key]=value;},set innerHTML(value){this.markup=value;this.items=[...value.matchAll(/<(?:a|button)\b[^>]*role="menuitem"[^>]*>/g)].map((match,index)=>({index,markup:match[0],focus(){document.activeElement=this;},closest(){return null;}}));},querySelectorAll(){return this.items;},contains(element){return this.items?.includes(element)||element===this;},remove(){this.isConnected=false;elements.delete(this.id);}};}};
 const anchor={isConnected:true,attributes:{},setAttribute(key,value){this.attributes[key]=value;},getBoundingClientRect:()=>({left:12,top:570,bottom:614}),contains:element=>element===anchor,closest:selector=>selector.includes('account-menu')?anchor:null,focus(){document.activeElement=anchor;}};
 const context=vm.createContext({document,location:{href:'http://127.0.0.1/studio.html#account',origin:'http://127.0.0.1',reload(){},hash:'#account'},innerWidth:669,innerHeight:681,
  addEventListener(type,callback){windowListeners.set(type,callback);},CustomEvent:class{constructor(type,options={}){this.type=type;this.detail=options.detail;}},
  URL,Headers,Request,Response,Intl,Map,Number,String,Date,JSON,crypto:globalThis.crypto,setTimeout,clearTimeout,
  fetch:async(input,init)=>{network.push({input,init});return new Response(JSON.stringify(String(input).includes('/quote/')?{workflow_id:'tool-one',configured:true,credits:17}:String(input)==='/api/account/me'?{user}:{ok:true}),{status:200,headers:{'Content-Type':'application/json'}});}
 });
 vm.runInContext(source,context);context.testUser=user;vm.runInContext('platform.user=testUser;platform.identity={id:testUser.id,csrfToken:"csrf-example"};',context);
 const fire=(type,target,extra={})=>{const event={target,preventDefault(){this.prevented=true;},stopImmediatePropagation(){this.stopped=true;},...extra};for(const {callback} of listeners.get(type)||[]){callback(event);if(event.stopped)break;}return event;};
 return {context,document,anchor,classes,elements,events,network,fire,windowListeners};
}

test('sidebar has one account button; management and settings live inside its menu',()=>{
 const f=fixture(),navigation=f.context.accountNavigation();
 assert.equal((navigation.match(/<button /g)||[]).length,1);assert.equal((navigation.match(/<a /g)||[]).length,0);
 assert.match(navigation,/aria-haspopup="menu" aria-expanded="false"/);
 const menu=f.context.accountMenuContents();assert.match(menu,/href="#settings"/);assert.match(menu,/href="#recharge"/);assert.match(menu,/href="\/admin\.html"/);assert.doesNotMatch(menu,/href="#admin"/);
 const normal=fixture({...admin,role:'user',username:'<unsafe>&name'});assert.doesNotMatch(normal.context.accountMenuContents(),/admin\.html/);assert.match(normal.context.accountNavigation(),/&lt;unsafe&gt;&amp;name/);
});

test('opening the portal changes only menu state and fits the viewport without layout mutation',()=>{
 const f=fixture();f.context.openAccountMenu(f.anchor);
 const menu=f.elements.get('platform-account-menu');assert.ok(menu);assert.equal(f.anchor.attributes['aria-expanded'],'true');assert.ok(f.classes.has('platform-account-menu-open'));
 assert.equal(menu.style.left,'12px');assert.equal(menu.style.top,'272px');assert.equal(f.events.at(-1).detail.open,true);
 assert.equal(f.network.length,0);f.context.closeAccountMenu();assert.equal(f.elements.size,0);assert.equal(f.anchor.attributes['aria-expanded'],'false');assert.equal(f.events.at(-1).detail.open,false);assert.ok(!f.classes.has('platform-account-menu-open'));
});

test('keyboard opens, navigates, and closes with Escape before the studio navigation handler',()=>{
 const f=fixture();f.context.installEvents();
 let event=f.fire('keydown',f.anchor,{key:'ArrowDown'});assert.ok(event.prevented&&event.stopped);
 const menu=f.elements.get('platform-account-menu');assert.equal(f.document.activeElement,menu.items[0]);
 f.fire('keydown',menu.items[0],{key:'End'});assert.equal(f.document.activeElement,menu.items.at(-1));
 f.fire('keydown',menu.items.at(-1),{key:'ArrowDown'});assert.equal(f.document.activeElement,menu.items[0]);
 event=f.fire('keydown',menu.items[0],{key:'Escape'});assert.ok(event.prevented&&event.stopped);assert.equal(f.document.activeElement,f.anchor);assert.equal(f.elements.size,0);
});

test('outside pointer and route changes close the portal, while menu clicks keep it open',()=>{
 const f=fixture();f.context.installEvents();f.context.openAccountMenu(f.anchor);
 f.fire('pointerdown',f.elements.get('platform-account-menu').items[0]);assert.equal(f.elements.size,1);
 f.fire('pointerdown',{});assert.equal(f.elements.size,0);
 f.context.openAccountMenu(f.anchor);f.windowListeners.get('hashchange')();assert.equal(f.elements.size,0);assert.ok(!f.classes.has('platform-account-menu-open'));
});

test('record tabs preserve the selected panel and never submit a request',async()=>{
 const f=fixture(),tabs=['ledger','orders'].map(kind=>({dataset:{records:kind},attributes:{},setAttribute(key,value){this.attributes[key]=value;}})),panels=['ledger','orders'].map(kind=>({dataset:{platformRecordPanel:kind},hidden:kind!=='ledger'}));
 const host={dataset:{platformPage:'account'},querySelectorAll:selector=>selector.includes('records-tab')?tabs:panels};
 await f.context.handleAction({dataset:{platformAction:'records-tab',records:'orders'},closest:()=>host});
 assert.equal(panels[0].hidden,true);assert.equal(panels[1].hidden,false);assert.equal(tabs[1].attributes['aria-pressed'],'true');assert.equal(f.network.length,0);
 const html=f.context.accountContents({user:admin},'account');assert.match(html,/data-platform-record-panel="ledger" hidden/);assert.doesNotMatch(html,/data-platform-record-panel="orders" hidden/);
 assert.match(html,/<details class="platform-security">/);assert.doesNotMatch(html,/<details class="platform-security" open/);
});

test('unconfigured recharge renders an accurate compact state without a usable payment form',()=>{
 const f=fixture({...admin,role:'user'}),data={packages:[],methods:[{id:'alipay',label:'支付宝',enabled:false},{id:'wechat',label:'微信',enabled:false},{id:'admin_contact',label:'联系管理员',enabled:true,automatic:false}]};
 const html=f.context.accountContents({...data,user:admin},'recharge');assert.match(html,/暂无积分套餐/);assert.doesNotMatch(html,/data-platform-form="recharge"/);assert.match(html,/人工核对/);assert.match(html,/未开通/);
 assert.match(html,/data-platform-balance="available">0/);assert.match(html,/data-platform-record-panel="ledger" hidden/);assert.doesNotMatch(html,/admin\.html/);
});

test('generation requests retain account, CSRF, and approved-credit headers',async()=>{
 const f=fixture();vm.runInContext('platform.quotes.set("tool-one",{configured:true,credits:17,displayed:true});installApiFetch();',f.context);
 const response=await f.context.fetch('/api/jobs',{method:'POST',body:JSON.stringify({workflow_id:'tool-one'}),headers:{'Content-Type':'application/json'}});
 assert.equal(response.status,200);assert.equal(f.network.filter(call=>call.input==='/api/jobs').length,1);const headers=f.network.find(call=>call.input==='/api/jobs').init.headers;
 assert.equal(headers.get('X-Platform-Account'),admin.id);assert.equal(headers.get('X-CSRF-Token'),'csrf-example');assert.equal(headers.get('X-Expected-Credits'),'17');
});

test('an unconfigured generation price blocks submission without contacting the job endpoint',async()=>{
 const f=fixture();vm.runInContext('platform.quotes.set("tool-one",{configured:false,credits:null,displayed:true});installApiFetch();',f.context);
 const response=await f.context.fetch('/api/jobs',{method:'POST',body:JSON.stringify({workflow_id:'tool-one'})});
 assert.equal(response.status,409);assert.equal(f.network.length,0);assert.match((await response.json()).detail,/费用未配置/);
});

test('external requests never receive the account or CSRF headers',async()=>{
 const f=fixture();vm.runInContext('installApiFetch();',f.context);const options={method:'POST',headers:{'Content-Type':'text/plain'},body:'public-data'};
 await f.context.fetch('https://public.example/api/upload',options);
 assert.equal(f.network.length,1);assert.equal(f.network[0].init,options);assert.equal(options.headers['X-Platform-Account'],undefined);assert.equal(options.headers['X-CSRF-Token'],undefined);
});
