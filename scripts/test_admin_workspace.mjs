import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import {filteredUsers,parseCreditDelta,adjustmentPreview,adjustmentIdentity,parseAmountMinor,newUserPayload,filteredPricing,creditReference} from '../public/admin.js';

const admin={id:'admin-1',username:'管理员',role:'admin',balance:20,held:7};
const member={id:'user-1',username:'创作用户',role:'user',balance:100,held:12,enabled:true};
const source=readFileSync(new URL('../public/admin.js',import.meta.url),'utf8').replace(/^import .*\r?\n/,'').replace(/\bexport /g,'').replace(/if\(typeof document!==.*startAdmin\(\);\s*$/,'');

function fixture({user=admin,onFetch}={}){
 const nodes=new Map(['admin-shell','admin-main','admin-notice','admin-dialog'].map(id=>[id,{innerHTML:'',hidden:true,textContent:'',querySelector:()=>null,querySelectorAll(){return this.secretFields||[];},handlers:{},addEventListener(type,handler){this.handlers[type]=handler;},showModal(){this.open=true;},close(){this.closed=true;this.open=false;this.handlers.close?.();}}]));
 const data={users:[structuredClone(admin),structuredClone(member)],orders:[],packages:[],pricing:[],payment_reviews:[],generation_reviews:[],workflow_options:[{id:'image-job',name:'画面创作'}]};
 const calls=[],events=[];let key=0;
 const context=vm.createContext({initializePlatform:async()=>user,console,Intl,Number,JSON,Date,String,Object,Array,Map,Set,Promise,Error,
  crypto:{randomUUID:()=>`00000000-0000-4000-8000-${String(++key).padStart(12,'0')}`},
  document:{title:'',getElementById:id=>nodes.get(id),querySelector:()=>null,addEventListener:(type,handler)=>events.push([type,handler])},
  location:{hash:'#users',href:'http://local/admin.html'},URLSearchParams,addEventListener:(type,handler)=>events.push([type,handler]),
  queueMicrotask:callback=>callback(),setTimeout:()=>1,clearTimeout:()=>{},
  FormData:class{constructor(form){this.values=form.values;}get(name){return this.values[name]??null;}has(name){return Object.hasOwn(this.values,name);}},
  fetch:async(path,options)=>{calls.push({path,...options,body:options.body?JSON.parse(options.body):undefined});return onFetch?onFetch(path,options,calls,data):{ok:true,json:async()=>path==='/api/admin/audit'?{audit:[]}:path.startsWith('/api/admin/users?')?{users:data.users,total:data.users.length,limit:50,offset:0}:data};}
 });
 vm.runInContext(source+'\nglobalThis.subject={state,startAdmin,submit,loadUsers,usersPage,ordersPage,pricingPage,pricingRegion,reviewsPage,auditPage,openNewUser,closeDialog,restoreUserFilters,action};',context);
 function creditForm(values={}){const error={textContent:'',hidden:true},button={disabled:false,isConnected:true};return {dataset:{adminForm:'credits',userId:member.id},values:{direction:'add',amount:'5',reason:'核对积分调整',...values},querySelector:selector=>selector==='[data-admin-error]'?error:selector==='[type=submit]'?button:null,error,button};}
 function newUserForm(values={}){const form=creditForm();form.dataset={adminForm:'new-user'};form.values={username:'new-creator',password:'initial secret 123',password_confirm:'initial secret 123',role:'user',...values};form.secretFields=[{value:form.values.password},{value:form.values.password_confirm}];form.querySelectorAll=()=>form.secretFields;nodes.get('admin-dialog').secretFields=form.secretFields;return form;}
 return {context,subject:context.subject,nodes,calls,data,creditForm,newUserForm,events};
}
const response=(ok,data)=>({ok,json:async()=>data});

test('credit direction and magnitude reject zero, fractions, exponent notation and unsafe numbers',()=>{
 assert.equal(parseCreditDelta('27','add'),27);assert.equal(parseCreditDelta('27','subtract'),-27);
 for(const value of ['0','-2','1.2','1e3','9007199254740992',''])assert.throws(()=>parseCreditDelta(value,'add'));
 assert.throws(()=>parseCreditDelta('5','unexpected'));
});
test('credit preview changes available balance only and prevents spending frozen balance',()=>{
 assert.deepEqual(adjustmentPreview(member,-100),{before:100,after:0,held:12});
 assert.deepEqual(adjustmentPreview(member,10),{before:100,after:110,held:12});
 assert.throws(()=>adjustmentPreview(member,-101));assert.throws(()=>adjustmentPreview({...member,balance:Number.MAX_SAFE_INTEGER},1));
});
test('retry identity is retained for same account and parameters but changed for every different operation',()=>{
 let sequence=0;const key=()=>String(++sequence),payload={account_id:'a',delta:5,reason:'核对记录'};
 const first=adjustmentIdentity(null,payload,key);assert.equal(adjustmentIdentity(first,{...payload},key),first);
 for(const change of [{account_id:'b'},{delta:-5},{reason:'其他依据'}])assert.notEqual(adjustmentIdentity(first,{...payload,...change},key).key,first.key);
});
test('currency parsing preserves cents and rejects more than two decimals or invalid amounts',()=>{
 assert.equal(parseAmountMinor('29.9'),2990);assert.equal(parseAmountMinor('0.01'),1);assert.equal(parseAmountMinor('10'),1000);
 for(const value of ['0','0.001','1e2','-20','NaN','9007199254740992'])assert.throws(()=>parseAmountMinor(value));
});
test('user filters combine account name, role and enabled state without changing source records',()=>{
 const users=[admin,member,{id:'disabled-1',username:'停用创作用户',role:'user',disabled:true,balance:0,held:3}],before=structuredClone(users);
 assert.deepEqual(filteredUsers(users,{search:'创作',role:'user',status:'enabled'}),[member]);
 assert.equal(filteredUsers(users,{role:'user',status:'disabled'})[0].id,'disabled-1');
 assert.deepEqual(users,before);
});
test('ordinary users are rejected before any management API is requested',async()=>{
 const f=fixture({user:member});await f.subject.startAdmin();assert.equal(f.calls.length,0);
 assert.match(f.nodes.get('admin-shell').innerHTML,/需要管理员权限/);assert.doesNotMatch(f.nodes.get('admin-shell').innerHTML,/data-admin-form/);
});
test('anonymous initialization does not mount administrator data',async()=>{
 const f=fixture({user:null});await f.subject.startAdmin();assert.equal(f.calls.length,0);assert.equal(f.nodes.get('admin-shell').innerHTML,'');
});
test('admin startup reads data only and users view does not show unrelated package or payment forms',async()=>{
 const f=fixture();await f.subject.startAdmin();assert.equal(f.calls[0].path,'/api/admin/dashboard');assert.match(f.calls[1].path,/^\/api\/admin\/users\?/);assert.ok(f.calls.every(call=>call.method==='GET'));
 const html=f.nodes.get('admin-shell').innerHTML;assert.match(f.subject.usersPage(),/data-admin-action="credits"/);assert.match(html,/href="#audit"/);
 assert.doesNotMatch(html,/data-admin-form="(?:package|confirm-order|generation-review)"/);
});
test('account names and workflow names cannot inject markup into administrator tables',async()=>{
 const f=fixture();f.data.users[1].username='<img src=x onerror=alert(1)>';f.data.workflow_options[0].name='<script>bad()</script>';
 await f.subject.startAdmin();assert.match(f.subject.usersPage(),/&lt;img/);assert.doesNotMatch(f.subject.usersPage(),/<img src=x/);
 const pricing=f.subject.pricingPage();assert.match(pricing,/&lt;script&gt;/);assert.doesNotMatch(pricing,/<script>bad/);
});
test('credit error stays visible and retry uses the same operation key without repeating automatically',async()=>{
 const f=fixture({onFetch:(path,_options,_calls,data)=>path.endsWith('/credits')?response(false,{detail:'核对失败，请重试'}):response(true,path.startsWith('/api/admin/users?')?{users:data.users,total:data.users.length,limit:50,offset:0}:data)});
 await f.subject.startAdmin();const form=f.creditForm();await f.subject.submit(form);
 let mutations=f.calls.filter(call=>call.path.endsWith('/credits'));assert.equal(mutations.length,1);assert.match(form.error.textContent,/核对失败/);assert.equal(form.error.hidden,false);assert.equal(form.button.disabled,false);
 await f.subject.submit(form);mutations=f.calls.filter(call=>call.path.endsWith('/credits'));assert.equal(mutations.length,2);assert.equal(mutations[0].body.idempotency_key,mutations[1].body.idempotency_key);
 assert.deepEqual(Object.keys(mutations[0].body).sort(),['delta','idempotency_key','reason']);assert.equal(mutations[0].body.delta,5);
 form.values.reason='新的调整依据';await f.subject.submit(form);const next=f.calls.filter(call=>call.path.endsWith('/credits')).at(-1);assert.notEqual(next.body.idempotency_key,mutations[0].body.idempotency_key);
});
test('invalid deductions never request a credit mutation even when an account has frozen credits',async()=>{
 const f=fixture();await f.subject.startAdmin();const form=f.creditForm({direction:'subtract',amount:'101'});await f.subject.submit(form);
 assert.equal(f.calls.filter(call=>call.path.endsWith('/credits')).length,0);assert.match(form.error.textContent,/不能超过可用积分/);
});
test('successful credit adjustment requires returned ledger evidence and refreshes the authoritative dashboard',async()=>{
 const f=fixture({onFetch:(path,options,_calls,data)=>{
  if(path.endsWith('/credits')){const body=JSON.parse(options.body);data.users[1].balance+=body.delta;return response(true,{user:data.users[1],adjustment:{id:1,account_id:member.id,ledger_id:1,delta:body.delta,already_applied:false}});}
  return response(true,path.startsWith('/api/admin/users?')?{users:data.users,total:data.users.length,limit:50,offset:0}:data);
 }});
 await f.subject.startAdmin();await f.subject.submit(f.creditForm());assert.equal(f.calls.filter(call=>call.path==='/api/admin/dashboard').length,2);
 assert.equal(f.subject.state.data.users[1].balance,105);assert.equal(f.subject.state.data.users[1].held,12);assert.equal(f.nodes.get('admin-dialog').closed,true);
 assert.match(f.nodes.get('admin-notice').textContent,/账本和操作记录已保存/);
});
test('partial success responses keep the adjustment form and key for safe manual reconciliation',async()=>{
 const f=fixture({onFetch:(path,_options,_calls,data)=>path.endsWith('/credits')?response(true,{user:member}):response(true,path.startsWith('/api/admin/users?')?{users:data.users,total:data.users.length,limit:50,offset:0}:data)});await f.subject.startAdmin();const form=f.creditForm();await f.subject.submit(form);
 assert.match(form.error.textContent,/刷新账号余额核对/);assert.equal(f.nodes.get('admin-dialog').closed,undefined);assert.ok(form.adminIdentity.key);
});
test('server user search includes role, state and offset so accounts beyond dashboard history can be found',async()=>{
 const f=fixture();await f.subject.startAdmin();Object.assign(f.subject.state,{search:'创作 用户',role:'user',status:'disabled',userOffset:50});await f.subject.loadUsers();
 const url=new URL(f.calls.at(-1).path,'http://local');assert.equal(url.searchParams.get('query'),'创作 用户');assert.equal(url.searchParams.get('role'),'user');assert.equal(url.searchParams.get('state'),'disabled');assert.equal(url.searchParams.get('offset'),'50');assert.equal(url.searchParams.get('limit'),'50');
});
test('a stale search response cannot overwrite newer user results',async()=>{
 let controlled=false;const pending=[];
 const f=fixture({onFetch:(path,_options,_calls,data)=>{
  if(path.startsWith('/api/admin/users?')){if(controlled)return new Promise(resolve=>pending.push(resolve));return response(true,{users:data.users,total:data.users.length,offset:0,limit:50});}
  return response(true,data);
 }});
 await f.subject.startAdmin();controlled=true;f.subject.state.search='old';const old=f.subject.loadUsers();f.subject.state.search='new';const latest=f.subject.loadUsers();
 pending[1](response(true,{users:[],total:0,offset:0,limit:50}));await latest;
 pending[0](response(true,{users:[member],total:1,offset:0,limit:50}));await old;
 assert.equal(f.subject.state.users.length,0);assert.equal(f.subject.state.userTotal,0);assert.equal(f.subject.state.userLoading,false);
});
test('failed user loading shows the error instead of pretending no matching users exist',async()=>{
 let fail=false;const f=fixture({onFetch:(path,_options,_calls,data)=>path.startsWith('/api/admin/users?')?(fail?response(false,{detail:'账号服务读取失败'}):response(true,{users:data.users,total:data.users.length,offset:0,limit:50})):response(true,data)});
 await f.subject.startAdmin();fail=true;await f.subject.loadUsers();const html=f.subject.usersPage();assert.match(html,/账号服务读取失败/);assert.match(html,/reload-users/);assert.doesNotMatch(html,/没有符合筛选条件/);
});
test('a deduction replay can recover a lost response after the refreshed balance is lower',async()=>{
 let attempts=0;const f=fixture({onFetch:(path,options,_calls,data)=>{
  if(path.endsWith('/credits')){attempts++;const body=JSON.parse(options.body);if(attempts===1){data.users[1].balance=20;throw new Error('响应丢失');}return response(true,{user:data.users[1],adjustment:{account_id:member.id,ledger_id:1,delta:body.delta,already_applied:true}});}
  return response(true,path.startsWith('/api/admin/users?')?{users:data.users,total:data.users.length,offset:0,limit:50}:data);
 }});
 await f.subject.startAdmin();const form=f.creditForm({direction:'subtract',amount:'80'});await f.subject.submit(form);assert.match(form.error.textContent,/响应丢失/);
 await f.subject.loadUsers();assert.equal(f.subject.state.users[1].balance,20);await f.subject.submit(form);
 const calls=f.calls.filter(call=>call.path.endsWith('/credits'));assert.equal(calls.length,2);assert.equal(calls[0].body.idempotency_key,calls[1].body.idempotency_key);assert.equal(f.subject.state.users[1].balance,20);assert.match(f.nodes.get('admin-notice').textContent,/未重复修改积分/);
});

test('new user validation normalizes account names while preserving exact password contents',()=>{
 const payload=newUserPayload(' Ｎｅｗ-用户 ',' leading secret 123 ',' leading secret 123 ');
 assert.deepEqual(payload,{username:'New-用户',password:' leading secret 123 ',role:'user'});
 assert.equal(newUserPayload('a'.repeat(80),'initial secret 123','initial secret 123').username.length,80);assert.throws(()=>newUserPayload('a'.repeat(81),'initial secret 123','initial secret 123'));
 assert.equal(newUserPayload('Admin2','initial secret 123','initial secret 123','admin').role,'admin');
 for(const args of [['ab','initial secret 123','initial secret 123'],['a b','initial secret 123','initial secret 123'],['new','short','short'],['new','initial secret 123','initial secret 124'],['new','x'.repeat(129),'x'.repeat(129)],['new','initial secret 123','initial secret 123','owner']])assert.throws(()=>newUserPayload(...args));
});
test('invalid new user input never sends a user creation request',async()=>{
 const f=fixture();await f.subject.startAdmin();const form=f.newUserForm({password_confirm:'different secret'});await f.subject.submit(form);
 assert.equal(f.calls.filter(call=>call.path==='/api/admin/users').length,0);assert.match(form.error.textContent,/不一致/);assert.equal(form.button.disabled,false);
});
test('new user form defaults to ordinary role and clears credentials when closed',async()=>{
 const f=fixture();await f.subject.startAdmin();f.subject.openNewUser();const host=f.nodes.get('admin-dialog');
 assert.match(host.innerHTML,/data-admin-form="new-user"/);assert.match(host.innerHTML,/<option value="user" selected>/);assert.match(host.innerHTML,/type="password" autocomplete="new-password"/);assert.match(host.innerHTML,/积分均为 0/);
 const form=f.newUserForm();f.subject.closeDialog();assert.equal(host.closed,true);assert.ok(form.secretFields.every(input=>input.value===''));
});
test('new user success locates its row, preserves original filters, and never changes the current login',async()=>{
 const created={id:'new-1',username:'new-creator',role:'user',enabled:true,balance:0,held:0};
 const f=fixture({onFetch:(path,_options,_calls,data)=>{
  if(path==='/api/admin/users'){data.users.push(created);return response(true,{user:created});}
  if(path.startsWith('/api/admin/users?')){const query=new URL(path,'http://local').searchParams;return response(true,{users:data.users,total:120,offset:Number(query.get('offset')),limit:50});}
  return response(true,data);
 }});
 await f.subject.startAdmin();Object.assign(f.subject.state,{search:'原筛选',role:'admin',status:'enabled',userOffset:50});
 const form=f.newUserForm();await f.subject.submit(form);const call=f.calls.find(item=>item.path==='/api/admin/users');
 assert.deepEqual(Object.keys(call.body).sort(),['password','role','username']);assert.equal(call.body.role,'user');assert.equal(f.subject.state.user.id,admin.id);assert.ok(f.calls.every(item=>!item.path.includes('/api/account/login')));
 assert.equal(f.subject.state.search,created.username);assert.equal(f.subject.state.userOffset,0);assert.match(f.subject.usersPage(),/is-new-user/);assert.ok(form.secretFields.every(input=>input.value===''));
 await f.subject.restoreUserFilters();assert.equal(f.subject.state.search,'原筛选');assert.equal(f.subject.state.role,'admin');assert.equal(f.subject.state.status,'enabled');assert.equal(f.subject.state.userOffset,50);assert.equal(f.subject.state.creationFocus,null);
});
test('an incomplete creation result keeps the form for reconciliation and does not retry automatically',async()=>{
 const f=fixture({onFetch:(path,_options,_calls,data)=>path==='/api/admin/users'?response(true,{user:{id:'new-1'}}):response(true,path.startsWith('/api/admin/users?')?{users:data.users,total:2,offset:0,limit:50}:data)});
 await f.subject.startAdmin();const form=f.newUserForm();await f.subject.submit(form);
 assert.equal(f.calls.filter(item=>item.path==='/api/admin/users').length,1);assert.match(form.error.textContent,/先搜索用户名核对/);assert.equal(f.nodes.get('admin-dialog').closed,undefined);assert.equal(f.subject.state.creationFocus,null);
});
test('a pending creation blocks duplicate submits and cannot close a newer drawer',async()=>{
 let resolveCreation;const created={id:'new-1',username:'new-creator',role:'user',balance:0,held:0};
 const f=fixture({onFetch:(path,_options,_calls,data)=>path==='/api/admin/users'?new Promise(resolve=>{resolveCreation=resolve;}):response(true,path.startsWith('/api/admin/users?')?{users:data.users,total:2,offset:0,limit:50}:data)});
 await f.subject.startAdmin();const host=f.nodes.get('admin-dialog');host.adminRevision=1;const form=f.newUserForm(),first=f.subject.submit(form);await f.subject.submit(form);
 assert.equal(f.calls.filter(item=>item.path==='/api/admin/users').length,1);host.adminRevision=2;host.secretFields=[{value:'new drawer contents'}];
 resolveCreation(response(true,{user:created}));await first;assert.equal(host.closed,undefined);assert.equal(host.secretFields[0].value,'new drawer contents');assert.ok(form.secretFields.every(input=>input.value===''));
});
test('pricing filters distinguish zero-cost configuration from tools without a configured price',()=>{
 const options=[{id:'a',name:'图像 A'},{id:'b',name:'图像 B'},{id:'c',name:'视频 C'}],prices=[{workflow_id:'a',credits:0},{workflow_id:'c',credits:10}];
 assert.deepEqual(filteredPricing(options,prices,{status:'configured'}).map(item=>item.id),['a','c']);
 assert.deepEqual(filteredPricing(options,prices,{status:'unconfigured',search:'图像'}).map(item=>item.id),['b']);assert.equal(options.length,3);
});
test('pricing paginates long tool lists and keeps current page while saving inline prices',async()=>{
 const f=fixture();f.data.workflow_options=Array.from({length:43},(_,i)=>({id:'tool-'+i,name:'工具 '+i}));await f.subject.startAdmin();
 let html=f.subject.pricingRegion();assert.equal((html.match(/data-admin-form="pricing"/g)||[]).length,20);assert.match(html,/1–20 \/ 43/);
 f.subject.state.pricingOffset=40;html=f.subject.pricingRegion();assert.equal((html.match(/data-admin-form="pricing"/g)||[]).length,3);assert.match(html,/41–43 \/ 43/);
 const form=f.creditForm();form.dataset={adminForm:'pricing',workflowId:'tool-42'};form.values={credits:'15'};await f.subject.submit(form);
 assert.equal(f.subject.state.pricingOffset,40);assert.equal(f.nodes.get('admin-dialog').closed,undefined);
 f.subject.state.pricingStatus='unconfigured';f.data.pricing=f.data.workflow_options.map(item=>({workflow_id:item.id,credits:0}));html=f.subject.pricingRegion();assert.equal(f.subject.state.pricingOffset,0);assert.match(html,/0 个工具/);
});
test('reference amounts come only from the server credit policy and never replace actual package amounts',async()=>{
 assert.equal(creditReference(25,{credits_per_yuan:100,currency:'CNY'}),'¥0.25');assert.equal(creditReference(25,undefined),'');assert.equal(creditReference(25,{credits_per_yuan:0,currency:'CNY'}),'');
 const f=fixture();f.data.credit_policy={credits_per_yuan:100,currency:'CNY'};f.data.pricing=[{workflow_id:'image-job',credits:25}];f.data.packages=[{id:'gift',title:'赠分包',credits:1000,amount_minor:800,currency:'CNY',enabled:true}];await f.subject.startAdmin();
 const html=f.subject.pricingPage();assert.match(html,/参考金额 ¥0.25/);assert.match(html,/¥8.00/);assert.match(html,/套餐可包含赠送积分/);assert.doesNotMatch(html,/¥10.00/);
});
