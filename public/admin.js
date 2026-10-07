import {initializePlatform} from './platform-account.js?v=81.0';

const state={user:null,data:null,audit:[],tab:'users',load:0,search:'',role:'all',status:'all',orderStatus:'pending',pricingSearch:'',pricingStatus:'all',pricingOffset:0,pricingLimit:20,users:[],userTotal:0,userOffset:0,userLimit:50,userLoading:true,userError:'',userLoad:0,creationFocus:null};
const tabs={users:{title:'用户管理',description:'管理账号权限、使用状态和积分'},orders:{title:'充值订单',description:'核对真实收款，再确认积分到账'},pricing:{title:'套餐与计价',description:'配置积分套餐和每次创作的费用'},reviews:{title:'账务核对',description:'处理需要人工核实的支付与创作记录'},audit:{title:'操作记录',description:'查看管理员变更，保留每一次操作依据'}};
const e=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const list=value=>Array.isArray(value)?value:[];
const n=value=>Number.isFinite(Number(value))?Number(value).toLocaleString('zh-CN'):'—';
const balance=user=>Number(user?.available??user?.balance??0);
const disabled=user=>user?.disabled===true||user?.disabled===1||user?.enabled===false;
const signed=value=>(Number(value)>0?'+':'')+n(value);
const date=value=>{if(!value)return '—';const d=new Date(typeof value==='number'&&value<1e12?value*1000:value);return Number.isNaN(d.getTime())?'—':d.toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false,month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});};
const money=(value,currency='CNY')=>new Intl.NumberFormat('zh-CN',{style:'currency',currency}).format(Number(value)/100);
const paymentName=method=>({alipay:'支付宝',wechat:'微信',bank:'银行卡',admin_contact:'联系管理员'})[method]||method||'—';
const statusName=status=>({pending:'待核对',confirmed:'已到账',cancelled:'已取消',expired:'已过期'})[status]||status||'—';
const tag=(text,kind='')=>`<span class="admin-tag${kind?' is-'+kind:''}">${e(text)}</span>`;
const btn=(label,action,attrs='',kind='')=>`<button type="button" class="admin-button${kind?' is-'+kind:''}" data-admin-action="${action}" ${attrs}>${e(label)}</button>`;
const errorBox=()=>'<p class="admin-error" data-admin-error role="alert" hidden></p>';
const table=(head,body)=>`<div class="admin-table-wrap"><table class="admin-table"><thead><tr>${head.map(text=>`<th>${e(text)}</th>`).join('')}</tr></thead><tbody>${body}</tbody></table></div>`;
const empty=(message,action='')=>`<div class="admin-empty"><p>${e(message)}</p>${action}</div>`;
const idText=id=>`<span class="admin-mono admin-id" title="${e(id)}">${e(id)}</span>`;
const icon=kind=>`<svg class="admin-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${({users:'<circle cx="9" cy="7" r="3"/><path d="M3 20v-3a6 6 0 0 1 12 0v3M17 5a3 3 0 0 1 0 6m2 9v-3a6 6 0 0 0-2-4"/>',orders:'<path d="M6 3h12v18l-3-2-3 2-3-2-3 2zM9 8h6M9 12h6"/>',pricing:'<path d="M3 12 12 3h8v8l-9 10z"/><circle cx="16" cy="7" r="1"/>',reviews:'<path d="M4 5h16v14H4zM8 9h8M8 13h4"/><path d="m16 14 2 2 4-4"/>',audit:'<path d="M4 5h16M4 12h16M4 19h16"/><circle cx="8" cy="5" r="2" fill="currentColor"/><circle cx="16" cy="12" r="2" fill="currentColor"/>',back:'<path d="m10 5-7 7 7 7M3 12h18"/>',search:'<circle cx="10" cy="10" r="6"/><path d="m15 15 5 5"/>'})[kind]||''}</svg>`;

export function filteredUsers(users,{search='',role='all',status='all'}={}){
 const needle=search.trim().toLocaleLowerCase();
 return list(users).filter(user=>(!needle||String(user.username).toLocaleLowerCase().includes(needle))&&(role==='all'||user.role===role)&&(status==='all'||(status==='disabled')===disabled(user)));
}
export function parseCreditDelta(amount,direction){
 const text=String(amount).trim();
 if(!/^\d+$/.test(text))throw new Error('请输入大于 0 的整数积分。');
 const value=Number(text);if(!Number.isSafeInteger(value)||value<1)throw new Error('请输入有效的整数积分。');
 if(direction!=='add'&&direction!=='subtract')throw new Error('请选择增加或扣减积分。');
 return direction==='subtract'?-value:value;
}
export function adjustmentPreview(user,delta){
 const before=balance(user),after=before+delta;
 if(!Number.isSafeInteger(delta)||delta===0||!Number.isSafeInteger(after))throw new Error('积分数量超出有效范围。');
 if(after<0)throw new Error('扣减数量不能超过可用积分；冻结积分不参与扣减。');
 return {before,after,held:Number(user.held||0)};
}
export function adjustmentIdentity(previous,payload,makeKey=()=>crypto.randomUUID()){
 const fingerprint=JSON.stringify([payload.account_id,payload.delta,payload.reason]);
 return previous?.fingerprint===fingerprint?previous:{fingerprint,key:makeKey()};
}
export function parseAmountMinor(amount){
 const text=String(amount).trim();if(!/^\d+(\.\d{1,2})?$/.test(text))throw new Error('金额最多保留两位小数。');
 const [whole,fraction='']=text.split('.'),value=Number(whole)*100+Number(fraction.padEnd(2,'0'));
 if(!Number.isSafeInteger(value)||value<1)throw new Error('请输入有效的套餐金额。');return value;
}
export function newUserPayload(username,password,confirmation,role='user'){
 const normalized=String(username??'').normalize('NFKC').trim(),secret=String(password??'');
 if([...normalized].length<3||[...normalized].length>80||!/^[\p{L}\p{N}_.@+\-]+$/u.test(normalized))throw new Error('用户名需为 3 至 80 个字母、数字、汉字或常用邮箱符号。');
 if([...secret].length<10||[...secret].length>128)throw new Error('初始密码需为 10 至 128 个字符。');
 if(secret!==String(confirmation??''))throw new Error('两次输入的密码不一致。');
 if(role!=='user'&&role!=='admin')throw new Error('请选择普通用户或管理员。');
 return {username:normalized,password:secret,role};
}
export function filteredPricing(options,items,{search='',status='all'}={}){
 const needle=search.trim().toLocaleLowerCase(),configured=new Set(list(items).map(item=>item.workflow_id));
 return list(options).filter(item=>(!needle||String(item.name).toLocaleLowerCase().includes(needle))&&(status==='all'||(status==='configured')===configured.has(item.id)));
}
export function creditReference(credits,policy){
 const rate=Number(policy?.credits_per_yuan);
 return policy?.currency==='CNY'&&Number.isFinite(rate)&&rate>0&&Number.isSafeInteger(Number(credits))&&Number(credits)>=0?money(Number(credits)*100/rate):'';
}
const pricingItems=value=>Array.isArray(value)?value:Object.entries(value||{}).map(([workflow_id,item])=>typeof item==='object'?{workflow_id,...item}:{workflow_id,credits:item});
const workflowName=id=>list(state.data?.workflow_options).find(item=>item.id===id)?.name||id;
const getUser=id=>list(state.users).find(user=>String(user.id)===String(id))||list(state.data?.users).find(user=>String(user.id)===String(id));

async function request(path,{method='GET',body}={}){
 const response=await fetch(path,{method,credentials:'same-origin',...(body===undefined?{}:{headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})});
 let data;try{data=await response.json();}catch{throw new Error('无法读取服务响应，请刷新核对结果后再试。');}
 if(!response.ok){const detail=data.detail;throw new Error(typeof detail==='string'?detail:Array.isArray(detail)?detail.map(item=>item.msg||'请检查输入').join('；'):detail?.message||data.message||'操作未完成，请稍后重试。');}
 return data;
}
function setError(host,message=''){const target=host?.querySelector('[data-admin-error]');if(target){target.textContent=message;target.hidden=!message;}}
let noticeTimer;
function notice(message){const host=document.getElementById('admin-notice');host.textContent=message;host.hidden=false;clearTimeout(noticeTimer);noticeTimer=setTimeout(()=>{host.hidden=true;},5000);}
function currentTab(){return Object.hasOwn(tabs,location.hash.slice(1))?location.hash.slice(1):'users';}

function navigation(){
 const data=state.data||{},pending=data.stats?.pending_orders??list(data.orders).filter(order=>order.status==='pending').length,review=list(data.payment_reviews).filter(item=>!item.decision).length+list(data.generation_reviews).length;
 return `<aside class="admin-side"><a class="admin-brand" href="studio.html#home"><img src="assets/brand-mark.svg" alt=""><span>映序<small>管理员后台</small></span></a><nav class="admin-nav" aria-label="后台导航">${Object.entries(tabs).map(([id,tab])=>`<a href="#${id}" ${state.tab===id?'aria-current="page"':''}>${icon(id)}<span>${tab.title}</span>${(id==='orders'?pending:id==='reviews'?review:0)?`<small class="admin-count">${n(id==='orders'?pending:review)}</small>`:''}</a>`).join('')}</nav><div class="admin-side-foot"><a class="admin-return" href="studio.html#home">${icon('back')}返回创作台</a><div class="admin-side-user"><b class="admin-avatar">${e(String(state.user.username).slice(0,1).toUpperCase())}</b><span title="${e(state.user.username)}">${e(state.user.username)}</span></div></div></aside>`;
}
function stats(){
 const users=list(state.data?.users),s=state.data?.stats||{users:users.length,enabled_users:users.filter(user=>!disabled(user)).length,available_credits:users.reduce((sum,user)=>sum+balance(user),0),held_credits:users.reduce((sum,user)=>sum+Number(user.held||0),0),pending_orders:list(state.data?.orders).filter(order=>order.status==='pending').length};
 return `<div class="admin-stats" aria-label="平台概览"><span>账号<b>${n(s.users)}</b></span><span>正常使用<b>${n(s.enabled_users)}</b></span><span>可用积分<b>${n(s.available_credits)}</b></span><span>冻结积分<b>${n(s.held_credits)}</b></span><span>待核对订单<b>${n(s.pending_orders)}</b></span></div>`;
}
function render(){
 const tab=tabs[state.tab];
 document.title=tab.title+' · 映序后台';
 document.getElementById('admin-shell').innerHTML=`<div class="admin-layout">${navigation()}<main id="admin-main" class="admin-main" tabindex="-1"><header class="admin-header"><div><h1>${tab.title}</h1><p>${tab.description}</p></div><div class="admin-header-actions"><a class="admin-button admin-return-mobile" href="studio.html#home">返回创作台</a>${btn('刷新','refresh')}</div></header>${stats()}${errorBox()}<div data-admin-content>${state.tab==='users'?usersPage():state.tab==='orders'?ordersPage():state.tab==='pricing'?pricingPage():state.tab==='reviews'?reviewsPage():auditPage()}</div></main></div>`;
}
async function load({quiet=false}={}){
 const run=++state.load;
 try{
  const [data,audit]=await Promise.all([request('/api/admin/dashboard'),state.tab==='audit'?request('/api/admin/audit'):Promise.resolve(null)]);
  if(run!==state.load)return;state.data=data;if(audit)state.audit=list(audit.audit);
  const current=list(data.users).find(user=>user.id===state.user.id);if(current)state.user=current;
  render();if(state.tab==='users')await loadUsers();if(!quiet)notice('已读取最新记录');
 }catch(error){if(run!==state.load)return;if(state.data)setError(document.getElementById('admin-main'),error.message);else document.getElementById('admin-shell').innerHTML=`<main id="admin-main" class="admin-denied"><h1>后台暂时无法读取</h1><p class="admin-error" role="alert">${e(error.message)}</p>${btn('重新读取','refresh')} <a class="admin-button" href="studio.html#home">返回创作台</a></main>`;}
}
function usersPage(){
 return `<div class="admin-toolbar"><label class="admin-search">${icon('search')}<input type="search" data-admin-search="users" aria-label="搜索用户名" placeholder="搜索用户名" value="${e(state.search)}"></label><select data-admin-filter="role" aria-label="按权限筛选"><option value="all">全部权限</option><option value="user" ${state.role==='user'?'selected':''}>普通用户</option><option value="admin" ${state.role==='admin'?'selected':''}>管理员</option></select><select data-admin-filter="status" aria-label="按状态筛选"><option value="all">全部状态</option><option value="enabled" ${state.status==='enabled'?'selected':''}>正常使用</option><option value="disabled" ${state.status==='disabled'?'selected':''}>已停用</option></select><span class="admin-result-count" data-admin-user-count></span>${btn('新增用户','new-user','','primary')}</div>${state.creationFocus?`<div class="admin-created-focus"><span>已定位新账号 <b>${e(state.creationFocus.user.username)}</b></span>${btn('返回原筛选','restore-user-filters','','quiet')}</div>`:''}<div data-admin-user-table>${usersTable()}</div>`;
}
function usersTable(){
 if(state.userLoading)return '<div class="admin-empty" role="status">正在读取账号…</div>';
 if(state.userError)return `<div class="admin-empty"><p class="admin-error" role="alert">${e(state.userError)}</p>${btn('重新读取账号','reload-users')}</div>`;
 const users=list(state.users);
 const content=users.length?table(['账号','权限','使用状态','可用积分','冻结积分','操作'],users.map(user=>`<tr${state.creationFocus?.user.id===user.id?' class="is-new-user"':''}><td><span class="admin-user-name">${e(user.username)}</span>${user.id===state.user.id?'<small>当前账号</small>':''}</td><td>${tag(user.role==='admin'?'管理员':'普通用户')}</td><td>${tag(disabled(user)?'已停用':'正常使用',disabled(user)?'muted':'good')}</td><td class="admin-number">${n(balance(user))}</td><td class="admin-number muted">${n(user.held)}</td><td>${btn('调整积分','credits',`data-user-id="${e(user.id)}"`,'small')} ${btn('管理','user',`data-user-id="${e(user.id)}"`,'small')}</td></tr>`).join('')):empty(state.search||state.role!=='all'||state.status!=='all'?'没有符合筛选条件的账号。':'暂无用户账号。');
 return content+`<div class="admin-pagination"><span>${state.userTotal?`${state.userOffset+1}–${Math.min(state.userOffset+users.length,state.userTotal)} / ${n(state.userTotal)} 个账号`:'0 个账号'}</span><div>${btn('上一页','previous-users',`${state.userOffset<1?'disabled':''}`,'small')} ${btn('下一页','next-users',`${state.userOffset+state.userLimit>=state.userTotal?'disabled':''}`,'small')}</div></div>`;
}
function userQuery(){return '/api/admin/users?'+new URLSearchParams({query:state.search.trim(),role:state.role,state:state.status,limit:String(state.userLimit),offset:String(state.userOffset)});}
function updateUsersRegion(){
 const region=document.querySelector('[data-admin-user-table]');if(region)region.innerHTML=usersTable();
 const count=document.querySelector('[data-admin-user-count]');if(count)count.textContent=state.userLoading?'正在读取…':state.userError?'读取未完成':`${n(state.userTotal)} 个账号`;
}
async function loadUsers(){
 const run=++state.userLoad;state.userLoading=true;state.userError='';updateUsersRegion();
 try{
  const data=await request(userQuery());if(run!==state.userLoad)return;
  if(!Array.isArray(data.users)||!Number.isSafeInteger(data.total)||data.total<0)throw new Error('账号列表返回不完整，请重新读取。');
  state.users=data.users;state.userTotal=data.total;state.userOffset=data.total>0?Number(data.offset)||0:0;state.userLimit=Number(data.limit)||50;
  // A concurrent account change can remove the final row of the last page.
  if(state.userOffset>0&&!state.users.length&&state.userTotal>0){state.userOffset=Math.floor((state.userTotal-1)/state.userLimit)*state.userLimit;return await loadUsers();}
 }catch(error){if(run!==state.userLoad)return;state.userError=error.message;}
 finally{if(run===state.userLoad){state.userLoading=false;if(state.tab==='users')updateUsersRegion();}}
}
function ordersPage(){
 const orders=list(state.data?.orders).filter(order=>state.orderStatus==='all'||order.status===state.orderStatus);
 return `<div class="admin-toolbar"><select data-admin-filter="orderStatus" aria-label="按订单状态筛选"><option value="pending" ${state.orderStatus==='pending'?'selected':''}>待核对订单</option><option value="all" ${state.orderStatus==='all'?'selected':''}>全部订单</option><option value="confirmed" ${state.orderStatus==='confirmed'?'selected':''}>已到账</option><option value="cancelled" ${state.orderStatus==='cancelled'?'selected':''}>已取消</option><option value="expired" ${state.orderStatus==='expired'?'selected':''}>已过期</option></select><span class="admin-caption">人工确认需要真实收款凭证；自动支付由服务端核验。</span><span class="admin-result-count">${orders.length} 笔订单</span></div>${orders.length?table(['订单 / 时间','用户','积分','金额','支付方式','状态','操作'],orders.map(order=>`<tr><td>${idText(order.id)}<small>${date(order.created_at)}</small></td><td>${e(order.username||getUser(order.account_id)?.username||getUser(order.user_id)?.username||'—')}</td><td class="admin-number">${n(order.credits)}</td><td>${money(order.amount_minor,order.currency)}</td><td>${e(paymentName(order.method))}</td><td>${tag(statusName(order.status),order.status==='confirmed'?'good':order.status==='pending'?'warn':'muted')}</td><td>${order.status==='pending'&&['bank','admin_contact'].includes(order.method)?btn('核对收款','confirm-order',`data-order-id="${e(order.id)}"`,'small'):order.status==='pending'?'<span class="admin-caption">等待支付平台回调</span>':'<span class="admin-caption">已记录</span>'}</td></tr>`).join('')):empty(state.orderStatus==='pending'?'暂无待核对订单。':'暂无此状态的充值订单。')}`;
}
function pricingPage(){
 const items=pricingItems(state.data?.pricing),options=list(state.data?.workflow_options);
 const packages=list(state.data?.packages);
 const policy=state.data?.credit_policy,conversion=creditReference(Number(policy?.credits_per_yuan),policy)?`1 元 = ${n(policy.credits_per_yuan)} 积分；套餐可包含赠送积分`:'';
 return `<section><div class="admin-section-head"><h2>积分套餐</h2>${btn('新增套餐','new-package','','primary')}</div>${conversion?`<p class="admin-caption">${e(conversion)}</p>`:''}${packages.length?table(['套餐名称','积分','价格','购买状态','操作'],packages.map(item=>`<tr><td><span class="admin-user-name">${e(item.title)}</span></td><td class="admin-number">${n(item.credits)}</td><td>${money(item.amount_minor,item.currency)}</td><td>${tag(item.enabled?'开放购买':'已停用',item.enabled?'good':'muted')}</td><td>${btn('编辑套餐','package',`data-package-id="${e(item.id)}"`,'small')}</td></tr>`).join('')):empty('尚未配置积分套餐。添加套餐后，用户才能创建充值订单。',btn('添加积分套餐','new-package','','primary'))}</section><section class="admin-section"><div class="admin-section-head"><h2>创作计价</h2><span>按每次任务收费；0 积分表示免费</span></div><div class="admin-toolbar"><label class="admin-search">${icon('search')}<input type="search" data-admin-search="pricing" aria-label="搜索创作工具" value="${e(state.pricingSearch)}" placeholder="搜索创作工具名称"></label><select data-admin-filter="pricingStatus" aria-label="按计价状态筛选"><option value="all">全部工具</option><option value="configured" ${state.pricingStatus==='configured'?'selected':''}>已配置费用</option><option value="unconfigured" ${state.pricingStatus==='unconfigured'?'selected':''}>未配置费用</option></select><span class="admin-result-count">${items.length} 项已配置 / ${options.length} 项可计价</span></div><div data-admin-pricing-table>${pricingRegion()}</div></section>`;
}
function pricingRegion(){
 const items=pricingItems(state.data?.pricing),options=filteredPricing(state.data?.workflow_options,items,{search:state.pricingSearch,status:state.pricingStatus});
 if(state.pricingOffset>=options.length)state.pricingOffset=options.length?Math.floor((options.length-1)/state.pricingLimit)*state.pricingLimit:0;
 const page=options.slice(state.pricingOffset,state.pricingOffset+state.pricingLimit);
 return pricingTable(page,items)+`<div class="admin-pagination"><span>${options.length?`${state.pricingOffset+1}–${state.pricingOffset+page.length} / ${n(options.length)} 个工具`:'0 个工具'}</span><div>${btn('上一页','previous-pricing',state.pricingOffset<1?'disabled':'','small')} ${btn('下一页','next-pricing',state.pricingOffset+state.pricingLimit>=options.length?'disabled':'','small')}</div></div>`;
}
function updatePricingRegion(){const region=document.querySelector('[data-admin-pricing-table]');if(region)region.innerHTML=pricingRegion();}
function pricingTable(options=list(state.data?.workflow_options),items=pricingItems(state.data?.pricing)){
 return options.length?table(['创作工具','当前费用','每次创作积分'],options.map(item=>{const price=items.find(entry=>entry.workflow_id===item.id),reference=price?creditReference(price.credits,state.data?.credit_policy):'';return `<tr><td><span class="admin-user-name">${e(item.name)}</span></td><td>${price?`${n(price.credits)} 积分${reference?`<small>参考金额 ${e(reference)}</small>`:''}`:tag('未配置','muted')}</td><td><form class="admin-inline-price" data-admin-form="pricing" data-workflow-id="${e(item.id)}"><input type="number" name="credits" min="0" step="1" required value="${price?e(price.credits):''}" aria-label="${e(item.name)}的每次创作积分" placeholder="积分"> <button class="admin-button is-small" type="submit">保存</button>${errorBox()}</form></td></tr>`;}).join('')):empty('没有符合条件的创作工具。');
}
function reviewsPage(){
 const payments=list(state.data?.payment_reviews),pending=payments.filter(item=>!item.decision),generations=list(state.data?.generation_reviews);
 return `<div class="admin-review-summary"><span>待处理支付异常 <b>${pending.length}</b></span><span>待核对创作 <b>${generations.length}</b></span></div><section><div class="admin-section-head"><h2>支付异常</h2><span>退款记录只登记已实际完成的退款</span></div>${payments.length?table(['订单 / 原因','收款证据','金额','处理状态','操作'],payments.map(item=>`<tr><td>${idText(item.order_id)}<small>${e(item.reason)} · ${date(item.created_at)}</small></td><td>${item.payment_reference?idText(item.payment_reference):'<span class="admin-caption">暂无收款凭证</span>'}</td><td>${money(item.amount_minor,item.currency)}</td><td>${tag(item.decision==='credit'?'已补记积分':item.decision==='refund_recorded'?'已登记退款':'待处理',item.decision?'good':'warn')}</td><td>${item.decision?'<span class="admin-caption">已记录</span>':btn('核对处理','payment-review',`data-review-id="${e(item.id)}"`,'small')}</td></tr>`).join('')):empty('暂无需要核对的支付异常。')}</section><section class="admin-section"><div class="admin-section-head"><h2>创作积分</h2><span>核对远端消耗后，再结算或退回冻结积分</span></div>${generations.length?table(['任务 / 用户','创作工具','任务状态','冻结积分','操作'],generations.map(item=>`<tr><td>${idText(item.job_id)}<small>${e(item.username||getUser(item.account_id)?.username||'—')} · ${date(item.created_at)}</small></td><td>${e(workflowName(item.workflow_id))}</td><td>${tag(({unknown:'状态不确定',abandoned:'已停止本地等待',failed:'作品取回失败',output_failed:'作品取回失败'})[item.status]||item.status,'warn')}</td><td class="admin-number">${n(item.credits)}</td><td>${btn('核对消耗','generation-review',`data-job-id="${e(item.job_id)}"`,'small')}</td></tr>`).join('')):empty('暂无需要人工核对的创作积分。')}</section>`;
}
const auditNames={create_user:'新增用户',set_role:'修改权限',disable_account:'修改账号状态',configure_package:'配置积分套餐',configure_pricing:'配置创作计价',review79_pricing_seed:'初始化套餐与计价',confirm_order:'确认充值到账',manual_credit_adjustment:'调整账号积分',adjust_credits:'调整账号积分',resolve_payment_review:'核对支付异常',resolve_generation_review:'核对创作积分',bootstrap_admin:'创建初始管理员'};
function auditDetail(value){
 let data=value;if(typeof value==='string'){try{data=JSON.parse(value);}catch{return value;}}if(!data||typeof data!=='object')return String(data??'');
 const labels={username:'用户名',delta:'积分变动',reason:'原因',role:'权限',disabled:'停用',credits:'积分',amount_minor:'金额(分)',enabled:'启用',title:'名称',payment_reference:'收款凭据',decision:'处理结论',note:'说明',confirmation_reference:'核对凭据',refund_reference:'退款凭据',balance_after:'可用余额',held_after:'冻结余额'};
 return Object.entries(data).map(([key,value])=>`${labels[key]||key}：${typeof value==='object'?JSON.stringify(value):value}`).join('；');
}
function auditPage(){return state.audit.length?table(['时间','操作人','操作','对象','变更说明'],state.audit.map(item=>`<tr><td>${date(item.created_at)}</td><td>${e(item.actor_username||getUser(item.actor_id)?.username||'—')}</td><td>${e(auditNames[item.action]||item.action)}</td><td>${e(item.action==='review79_pricing_seed'?'套餐与计价':getUser(item.target)?.username||list(state.data?.packages).find(pack=>pack.id===item.target)?.title||workflowName(item.target))}</td><td class="admin-audit-detail">${e(auditDetail(item.data))}</td></tr>`).join('')):empty('暂无管理员操作记录。');}

function dialog(title,subtitle,content){
 const host=document.getElementById('admin-dialog');host.adminRevision=(host.adminRevision||0)+1;host.innerHTML=`<header class="admin-dialog-head"><div><h2 id="admin-dialog-title">${e(title)}</h2>${subtitle?`<p>${e(subtitle)}</p>`:''}</div><button class="admin-dialog-close" type="button" data-admin-action="close-dialog" aria-label="关闭">×</button></header><div class="admin-dialog-body">${content}</div>`;
 host.showModal();return host;
}
function clearCreationSecrets(host){
 if(!host)return;
 for(const input of host.querySelectorAll?.('[data-admin-form="new-user"] input[type="password"]')||[])input.value='';
}
function closeDialog(){const host=document.getElementById('admin-dialog');clearCreationSecrets(host);host?.close();}
function openNewUser(){
 dialog('新增用户','创建后可在用户管理中调整权限与积分',`<form class="admin-form" data-admin-form="new-user"><label class="admin-field">用户名<input name="username" autocomplete="off" minlength="3" maxlength="80" required placeholder="3 至 80 个字母、数字或汉字" autofocus></label><label class="admin-field">初始密码<input name="password" type="password" autocomplete="new-password" minlength="10" maxlength="128" required placeholder="至少 10 个字符"></label><label class="admin-field">确认密码<input name="password_confirm" type="password" autocomplete="new-password" minlength="10" maxlength="128" required placeholder="再次输入初始密码"></label><label class="admin-field">账号权限<select name="role"><option value="user" selected>普通用户</option><option value="admin">管理员</option></select></label><p class="admin-caption">初始可用和冻结积分均为 0；创建后可单独调整积分。</p>${errorBox()}<div class="admin-form-foot">${btn('取消','close-dialog')}<button class="admin-button is-primary" type="submit">创建用户</button></div></form>`);
}
async function restoreUserFilters(){
 const previous=state.creationFocus?.previous;if(!previous)return;
 Object.assign(state,previous);state.creationFocus=null;render();await loadUsers();
}
function creditForm(user){return `<section class="admin-dialog-section"><h3>调整可用积分</h3><div class="admin-credit-summary"><span>可用 <strong>${n(balance(user))}</strong></span><span>冻结 <strong>${n(user.held)}</strong></span></div><form class="admin-form" data-admin-form="credits" data-user-id="${e(user.id)}"><div class="admin-form-pair"><label class="admin-field">操作<select name="direction"><option value="add">增加积分</option><option value="subtract">扣减积分</option></select></label><label class="admin-field">积分数量<input name="amount" type="number" min="1" step="1" required placeholder="正整数" autofocus></label></div><label class="admin-field">调整原因<textarea name="reason" rows="2" minlength="3" maxlength="1000" required placeholder="写明调整依据，至少三个字"></textarea></label><div class="admin-credit-preview" data-admin-credit-preview>修改前后会在这里预览；冻结积分保持不变。</div>${errorBox()}<div class="admin-form-foot"><span class="admin-caption">将记入积分账本和操作记录</span><button class="admin-button is-primary" type="submit">确认调整</button></div></form></section>`;}
async function openUser(id,onlyCredits=false){
 const user=getUser(id);if(!user)return;
 const host=dialog(onlyCredits?'调整积分':'账号管理',user.username,`${onlyCredits?'':`<section class="admin-dialog-section"><h3>权限与使用状态</h3><form class="admin-form" data-admin-form="role" data-user-id="${e(user.id)}"><label class="admin-field">账号权限<select name="role"><option value="user" ${user.role==='admin'?'':'selected'}>普通用户</option><option value="admin" ${user.role==='admin'?'selected':''}>管理员</option></select></label>${errorBox()}<div class="admin-form-foot"><button class="admin-button" type="submit">保存权限</button></div></form><div><p class="admin-caption">${disabled(user)?'已停用：该账号不能登录或提交创作。':'正常使用：可以登录并按积分余额创作。'}</p>${btn(disabled(user)?'恢复使用':'停用账号','user-status',`data-user-id="${e(user.id)}" data-disabled="${!disabled(user)}"`,disabled(user)?'':'danger')}${errorBox()}</div></section>`}${creditForm(user)}<section class="admin-dialog-section"><h3>最近积分记录</h3><div data-admin-ledger><p class="admin-caption" role="status">正在读取账本…</p></div></section>`);
 const revision=host.adminRevision;
 try{const data=await request('/api/admin/users/'+encodeURIComponent(id)+'/ledger');if(host.open&&host.adminRevision===revision){host.querySelector('[data-admin-ledger]').innerHTML=ledgerList(list(data.ledger));}}
 catch(error){if(host.open&&host.adminRevision===revision){const region=host.querySelector('[data-admin-ledger]');if(region)region.innerHTML=`<p class="admin-error" role="alert">${e(error.message)}</p>`;}}
}
const eventNames={recharge:'充值到账',reserve:'创作冻结',settle:'创作结算',release:'退回冻结积分',admin_adjust:'管理员调整',adjustment:'管理员调整',manual_adjustment:'管理员调整'};
function ledgerList(entries){return entries.length?`<ul class="admin-ledger">${entries.slice(0,20).map(item=>`<li><div>${e(eventNames[item.event]||item.event)}${item.description||item.reason?`<small>${e(item.description||item.reason)}</small>`:''}<small>${date(item.created_at)} · 可用 ${n(item.balance_after)} / 冻结 ${n(item.held_after)}</small></div><strong class="${Number(item.amount)>0?'positive':Number(item.amount)<0?'negative':''}">${signed(item.amount)}${Number(item.held_amount)?`<small>冻结 ${signed(item.held_amount)}</small>`:''}</strong></li>`).join('')}</ul>`:empty('该账号暂无积分记录。');}
function openPackage(id){
 const item=list(state.data?.packages).find(value=>value.id===id)||{},existing=!!item.id;
 dialog(existing?'编辑积分套餐':'新增积分套餐','套餐变更仅用于之后创建的充值订单',`<form class="admin-form" data-admin-form="package" data-package-id="${e(item.id)}"><label class="admin-field">套餐名称<input name="title" required maxlength="100" value="${e(item.title)}" placeholder="例如：创作积分包"></label><div class="admin-form-pair"><label class="admin-field">积分数量<input name="credits" type="number" min="1" step="1" required value="${item.credits===undefined?'':e(item.credits)}"></label><label class="admin-field">价格（元）<input name="amount" type="number" min="0.01" step="0.01" required value="${item.amount_minor===undefined?'':e(Number(item.amount_minor)/100)}"></label></div><label class="admin-check"><input name="enabled" type="checkbox" ${item.enabled===false?'':'checked'}>开放购买</label>${errorBox()}<div class="admin-form-foot"><button class="admin-button is-primary" type="submit">${existing?'保存套餐':'创建套餐'}</button></div></form>`);
}
function openOrder(id){
 const order=list(state.data?.orders).find(item=>item.id===id);if(!order)return;
 dialog('核对充值收款',(order.username||getUser(order.account_id)?.username||getUser(order.user_id)?.username||'')+' · '+paymentName(order.method),`<section class="admin-dialog-section"><div class="admin-credit-summary"><span>应收 <strong>${money(order.amount_minor,order.currency)}</strong></span><span>到账积分 <strong>${n(order.credits)}</strong></span></div><p class="admin-caption">订单号：${e(order.id)}<br>请核对实际到账金额和订单；填写真实凭据后才可确认。</p><form class="admin-form" data-admin-form="confirm-order" data-order-id="${e(id)}"><label class="admin-field">真实收款凭证<input name="payment_reference" minlength="3" maxlength="200" required placeholder="实际到账流水号或核对记录"></label>${errorBox()}<div class="admin-form-foot"><button class="admin-button is-primary" type="submit">确认已收到款项</button></div></form></section>`);
}
function openPaymentReview(id){
 const item=list(state.data?.payment_reviews).find(value=>value.id===id);if(!item)return;const proof=!!item.payment_reference;
 dialog('核对支付异常',item.reason||'',`<section class="admin-dialog-section"><p class="admin-caption">订单 ${e(item.order_id)}<br>实际收款 ${money(item.amount_minor,item.currency)}<br>收款凭证 ${e(item.payment_reference||'暂未提供')}</p><form class="admin-form" data-admin-form="payment-review" data-review-id="${e(id)}"><label class="admin-field">处理结论<select name="decision" data-admin-refund-decision><option value="credit" ${proof?'selected':'disabled'}>核实收款后，补记积分</option><option value="refund_recorded" ${proof?'':'selected'}>记录已完成的线下退款</option></select></label><label class="admin-field" data-admin-refund-field ${proof?'hidden':''}>真实退款凭证<input name="refund_reference" maxlength="200" minlength="3" ${proof?'disabled':'required'} placeholder="已完成退款的流水号"></label><label class="admin-field">核对说明<textarea name="note" minlength="3" maxlength="1000" required rows="3" placeholder="写明实际核对结果"></textarea></label><p class="admin-caption">记录退款只保存已完成的线下退款凭证，平台不会自动退款。</p>${errorBox()}<div class="admin-form-foot"><button class="admin-button is-primary" type="submit">保存核对结论</button></div></form></section>`);
}
function openGenerationReview(id){
 const item=list(state.data?.generation_reviews).find(value=>value.job_id===id);if(!item)return;
 dialog('核对创作消耗',workflowName(item.workflow_id),`<section class="admin-dialog-section"><div class="admin-credit-summary"><span>冻结积分 <strong>${n(item.credits)}</strong></span></div><p class="admin-caption">用户 ${e(item.username||getUser(item.account_id)?.username||'—')}<br>任务 ${e(item.job_id)}${item.prompt_id?'<br>远端任务 '+e(item.prompt_id):''}</p><form class="admin-form" data-admin-form="generation-review" data-job-id="${e(id)}"><label class="admin-field">核对结论<select name="decision"><option value="settle">确认已消耗，结算积分</option><option value="release">确认未消耗，退回积分</option></select></label><label class="admin-field">真实远端核对凭据<input name="confirmation_reference" minlength="3" maxlength="200" required placeholder="远端任务记录或核对凭据"></label><label class="admin-field">处理说明<textarea name="note" minlength="3" maxlength="1000" required rows="3" placeholder="写明是否执行及是否消耗资源"></textarea></label><p class="admin-caption">这里只结算或退回本平台积分，外部算力费用不会自动退还。</p>${errorBox()}<div class="admin-form-foot"><button class="admin-button is-primary" type="submit">保存核对结论</button></div></form></section>`);
}
function updatePreview(form){
 const user=getUser(form.dataset.userId),host=form.querySelector('[data-admin-credit-preview]');if(!user||!host)return;
 try{
  const delta=parseCreditDelta(form.elements.amount.value,form.elements.direction.value),fingerprint=JSON.stringify([user.id,delta,form.elements.reason.value.trim()]);
  if(form.adminIdentity?.attempted&&form.adminIdentity.fingerprint===fingerprint){host.textContent='此操作已经发送；原样重试将核对同一笔记录，不会重复修改积分。';return;}
  const preview=adjustmentPreview(user,delta);host.innerHTML=`可用积分 <b>${n(preview.before)} → ${n(preview.after)}</b><br>${delta>0?'增加':'扣减'} ${n(Math.abs(delta))} 积分；冻结 ${n(preview.held)} 积分保持不变。`;
 }
 catch(error){host.textContent=error.message;}
}
async function submit(form){
 if(form.dataset.adminBusy==='true')return;
 const values=new FormData(form),get=name=>String(values.get(name)||'').trim(),kind=form.dataset.adminForm;
 const dialogHost=document.getElementById('admin-dialog'),dialogRevision=dialogHost?.adminRevision;
 setError(form);form.dataset.adminBusy='true';const button=form.querySelector('[type=submit]');if(button)button.disabled=true;
 try{
  let result;
  if(kind==='credits'){
   const user=getUser(form.dataset.userId),delta=parseCreditDelta(get('amount'),get('direction')),reason=get('reason');if(!user)throw new Error('账号已变化，请刷新后再试。');if(reason.length<3||reason.length>1000)throw new Error('请填写 3 至 1000 字的调整原因。');
   const identity=adjustmentIdentity(form.adminIdentity,{account_id:user.id,delta,reason}),replay=identity===form.adminIdentity&&identity.attempted===true;
   // A lost response may mean the deduction already reduced the balance. Keep
   // its key and let the server replay the recorded result before balance checks.
   if(!replay)adjustmentPreview(user,delta);
   form.adminIdentity=identity;form.adminIdentity.attempted=true;
   result=await request('/api/admin/users/'+encodeURIComponent(user.id)+'/credits',{method:'POST',body:{delta,reason,idempotency_key:form.adminIdentity.key}});
   if(!result.user||String(result.user.id)!==String(user.id)||!result.adjustment||String(result.adjustment.account_id)!==String(user.id)||!Number.isSafeInteger(result.adjustment.ledger_id)||result.adjustment.delta!==delta)throw new Error('尚未收到完整的变更记录，请刷新账号余额核对后再试。');
  }else if(kind==='new-user'){
   const payload=newUserPayload(get('username'),values.get('password'),values.get('password_confirm'),get('role'));
   result=await request('/api/admin/users',{method:'POST',body:payload});
   if(!result.user?.id||result.user.username!==payload.username||result.user.role!==payload.role)throw new Error('未收到完整的新账号信息，请先搜索用户名核对是否创建成功，再重试。');
   for(const input of form.querySelectorAll?.('input[type="password"]')||[])input.value='';
   const previous=state.creationFocus?.previous||{search:state.search,role:state.role,status:state.status,userOffset:state.userOffset};
   state.creationFocus={user:result.user,previous};Object.assign(state,{search:result.user.username,role:'all',status:'all',userOffset:0});
  }else if(kind==='role'){await request('/api/admin/users/'+encodeURIComponent(form.dataset.userId),{method:'POST',body:{role:get('role')}});}
  else if(kind==='package'){
   const amount_minor=parseAmountMinor(get('amount')),credits=parseCreditDelta(get('credits'),'add');if(!form.dataset.packageId)form.dataset.packageId='package-'+crypto.randomUUID();
   await request('/api/admin/packages',{method:'POST',body:{id:form.dataset.packageId,title:get('title'),credits,amount_minor,enabled:values.has('enabled')}});
  }else if(kind==='pricing'){
   const credits=Number(get('credits'));if(!/^\d+$/.test(get('credits'))||!Number.isSafeInteger(credits)||credits<0)throw new Error('请输入 0 或大于 0 的整数积分。');
   await request('/api/admin/pricing',{method:'POST',body:{workflow_id:form.dataset.workflowId,credits}});
  }else if(kind==='confirm-order'){await request('/api/admin/orders/'+encodeURIComponent(form.dataset.orderId)+'/confirm',{method:'POST',body:{payment_reference:get('payment_reference')}});}
  else if(kind==='payment-review'){await request('/api/admin/payment-reviews/'+encodeURIComponent(form.dataset.reviewId)+'/resolve',{method:'POST',body:{decision:get('decision'),note:get('note'),refund_reference:get('refund_reference')||null}});}
  else if(kind==='generation-review'){await request('/api/admin/generation-reviews/'+encodeURIComponent(form.dataset.jobId)+'/resolve',{method:'POST',body:{decision:get('decision'),confirmation_reference:get('confirmation_reference'),note:get('note')}});}
  else return;
  if(kind!=='pricing'&&dialogHost?.adminRevision===dialogRevision)closeDialog();
  if(kind==='role'&&form.dataset.userId===state.user.id&&get('role')!=='admin'){location.href='studio.html#account';return;}
  await load({quiet:true});notice(kind==='credits'?(result.adjustment.already_applied?'该调整已记账，未重复修改积分。':'积分已调整，账本和操作记录已保存。'):kind==='new-user'?'用户已创建，初始积分为 0。已定位新账号，可返回原筛选。':'已保存并读取最新记录。');
 }catch(error){setError(form,error.message||'操作未完成，请稍后重试。');if(kind==='credits')updatePreview(form);}
 finally{form.dataset.adminBusy='false';if(button?.isConnected)button.disabled=false;}
}
async function action(element){
 const type=element.dataset.adminAction;if(type==='close-dialog'){closeDialog();return;}
 if(type==='refresh'){element.disabled=true;await load();if(element.isConnected)element.disabled=false;return;}
 if(type==='reload-users'){await loadUsers();return;}
 if(type==='previous-users'||type==='next-users'){state.userOffset=Math.max(0,state.userOffset+(type==='next-users'?1:-1)*state.userLimit);await loadUsers();return;}
 if(type==='previous-pricing'||type==='next-pricing'){state.pricingOffset=Math.max(0,state.pricingOffset+(type==='next-pricing'?1:-1)*state.pricingLimit);updatePricingRegion();return;}
 if(type==='new-user'){openNewUser();return;}
 if(type==='restore-user-filters'){await restoreUserFilters();return;}
 if(type==='user'||type==='credits'){await openUser(element.dataset.userId,type==='credits');return;}
 if(type==='new-package'||type==='package'){openPackage(element.dataset.packageId);return;}
 if(type==='confirm-order'){openOrder(element.dataset.orderId);return;}
 if(type==='payment-review'){openPaymentReview(element.dataset.reviewId);return;}
 if(type==='generation-review'){openGenerationReview(element.dataset.jobId);return;}
 if(type==='user-status'){
  const host=element.parentElement;setError(host);element.disabled=true;
  try{await request('/api/admin/users/'+encodeURIComponent(element.dataset.userId),{method:'POST',body:{disabled:element.dataset.disabled==='true'}});document.getElementById('admin-dialog').close();await load({quiet:true});notice(element.dataset.disabled==='true'?'账号已停用。':'账号已恢复使用。');}
  catch(error){setError(host,error.message);}finally{if(element.isConnected)element.disabled=false;}
 }
}
let userSearchTimer;
function installEvents(){
 document.getElementById('admin-dialog')?.addEventListener?.('close',()=>clearCreationSecrets(document.getElementById('admin-dialog')));
 document.addEventListener('click',event=>{const element=event.target.closest?.('[data-admin-action]');if(element&&!element.disabled)action(element);});
 document.addEventListener('submit',event=>{const form=event.target.closest?.('[data-admin-form]');if(form){event.preventDefault();submit(form);}});
 document.addEventListener('input',event=>{
  const target=event.target,kind=target.dataset.adminSearch;
  if(kind==='users'){state.search=target.value;state.userOffset=0;state.userLoad++;clearTimeout(userSearchTimer);userSearchTimer=setTimeout(()=>loadUsers(),250);}
  else if(kind==='pricing'){state.pricingSearch=target.value;state.pricingOffset=0;updatePricingRegion();}
  const form=target.closest?.('[data-admin-form="credits"]');if(form)updatePreview(form);
 });
 document.addEventListener('change',event=>{
  const target=event.target,key=target.dataset.adminFilter;if(key&&['role','status','orderStatus','pricingStatus'].includes(key)){state[key]=target.value;if(key==='pricingStatus'){state.pricingOffset=0;updatePricingRegion();}else if(key==='orderStatus')document.querySelector('[data-admin-content]').innerHTML=ordersPage();else{clearTimeout(userSearchTimer);state.userOffset=0;loadUsers();}}
  if(target.matches?.('[data-admin-refund-decision]')){const form=target.closest('form'),field=form.querySelector('[data-admin-refund-field]'),input=field.querySelector('input'),refund=target.value==='refund_recorded';field.hidden=!refund;input.disabled=!refund;input.required=refund;}
  const form=target.closest?.('[data-admin-form="credits"]');if(form)updatePreview(form);
 });
 addEventListener('hashchange',()=>{if(!state.user||state.user.role!=='admin')return;clearTimeout(userSearchTimer);state.userLoad++;state.tab=currentTab();if(state.tab==='audit')load({quiet:true});else if(state.data){state.load++;render();if(state.tab==='users')loadUsers();}});
}
export async function startAdmin(){
 installEvents();state.user=await initializePlatform();if(!state.user)return;
 if(state.user.role!=='admin'){document.getElementById('admin-shell').innerHTML='<main id="admin-main" class="admin-denied"><h1>需要管理员权限</h1><p>当前账号没有进入管理后台的权限。</p><a class="admin-button is-primary" href="studio.html#home">返回创作台</a></main>';return;}
 state.tab=currentTab();await load({quiet:true});
}
if(typeof document!=='undefined'&&document.getElementById('admin-shell'))startAdmin();
