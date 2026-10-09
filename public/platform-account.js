const nativeFetch=globalThis.fetch.bind(globalThis);
const platform={user:null,identity:null,preview:false,localMode:false,installed:false,wrapped:false,authMode:'login',quotes:new Map(),quoteRequests:new Map(),currentWorkflow:null,creationQuotes:new Map(),creationQuoteRequests:new Map(),currentCreation:null,quoteView:null,pricingPolicy:null,pricingPolicyRequest:null,balanceLastAt:0,balancePending:null,balanceTimer:null,balanceDirty:false,balanceStopped:false,menuAnchor:null,recordTabs:{account:'ledger',recharge:'orders'}};
export const isLocalPlatform=()=>platform.localMode;
const escapeHtml=value=>String(value??'').replace(/[&<>"']/g,character=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character]));
const credits=value=>value===null||value===undefined||value===''?'—':Number.isFinite(Number(value))?Number(value).toLocaleString('zh-CN'):'—';
const available=user=>user?.available??user?.balance;
const money=(minor,currency='CNY')=>minor===null||minor===undefined?'—':new Intl.NumberFormat('zh-CN',{style:'currency',currency}).format(Number(minor)/100);
const date=value=>{if(!value)return '—';const parsed=typeof value==='number'?new Date(value<1e12?value*1000:value):new Date(value);return Number.isNaN(parsed.getTime())?'—':parsed.toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false});};
const signed=value=>value===null||value===undefined?'—':(Number(value)>0?'+':'')+credits(value);
const statusNames={pending:'待核对',confirmed:'已到账',cancelled:'已取消',expired:'已过期'};
const eventNames={recharge:'充值到账',reserve:'创作冻结',settle:'创作结算',release:'退回冻结积分',admin_adjustment:'管理员调整',adjustment:'管理员调整'};
const icon=kind=>`<svg class="icon" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${kind==='user'?'<circle cx="12" cy="8" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2"/>':kind==='admin'?'<path d="m12 3 8 3v6c0 5-8 9-8 9S4 17 4 12V6z"/><path d="m8 12 3 3 5-6"/>':'<circle cx="12" cy="12" r="9"/><path d="M8 10h8m-8 4h8m-4-7v10"/>'}</svg>`;
const button=(label,action,attrs='',primary=false)=>`<button type="button" class="platform-button${primary?' is-primary':''}" data-platform-action="${action}" ${attrs}>${escapeHtml(label)}</button>`;
const errorRegion=()=>'<p class="platform-error" data-platform-error role="alert" hidden></p>';
const empty=message=>`<p class="platform-empty">${escapeHtml(message)}</p>`;
const rows=value=>Array.isArray(value)?value:[];

function apiMessage(data,fallback){
 const detail=data?.detail??data?.error;
 if(typeof detail==='string')return detail;
 if(Array.isArray(detail))return detail.map(item=>item.msg||'请检查填写内容').join('；');
 return detail?.message||data?.message||fallback;
}
async function request(path,{body,method='GET',anonymous=false}={}){
 const options={method,credentials:'same-origin'};
 if(body!==undefined){options.headers={'Content-Type':'application/json'};options.body=JSON.stringify(body);}
 const response=await (anonymous?nativeFetch:globalThis.fetch)(path,options);
 let data;try{data=await response.json();}catch{throw new Error('服务没有返回有效信息，请稍后重试。');}
 if(!response.ok)throw new Error(apiMessage(data,'操作未完成，请稍后重试。'));
 return data;
}
function installApiFetch(){
 if(platform.wrapped)return;platform.wrapped=true;
 const identity=platform.identity;
 globalThis.fetch=async(input,init)=>{
  const url=new URL(typeof input==='string'||input instanceof URL?String(input):input.url,location.href);
  if(url.origin!==location.origin||!(url.pathname==='/api'||url.pathname.startsWith('/api/')))return nativeFetch(input,init);
  const headers=new Headers(init?.headers??(typeof Request!=='undefined'&&input instanceof Request?input.headers:undefined));
  const method=String(init?.method||(typeof Request!=='undefined'&&input instanceof Request?input.method:'GET')).toUpperCase();
  headers.set('X-Platform-Account',String(identity.id));
  if(method!=='GET')headers.set('X-CSRF-Token',identity.csrfToken);
  if(platform.localMode)headers.delete('X-Expected-Credits');
  let workflowId;
  if(!platform.localMode&&method==='POST'&&(url.pathname==='/api/jobs'||/^\/api\/jobs\/[^/]+\/rerun$/.test(url.pathname))){
   try{
    if(url.pathname==='/api/jobs'){
     const body=typeof init?.body==='string'?JSON.parse(init.body):typeof Request!=='undefined'&&input instanceof Request?await input.clone().json():null;
     workflowId=body?.workflow_id;
    }else workflowId=(await request(url.pathname.replace(/\/rerun$/,''))).workflow_id;
    if(!workflowId)return blockedSubmission('无法核对本次创作的积分费用，请刷新工作区。');
    let quote=platform.quotes.get(workflowId);
    if(!quote?.displayed){
     quote=await readGenerationQuote(workflowId,true);
     if(!quote.configured)return blockedSubmission('费用未配置，请联系管理员；免费演示仍可使用。');
     if(!globalThis.confirm(`本次创作需要 ${credits(quote.credits)} 积分。确认提交？`))return blockedSubmission('已取消本次提交，未扣除积分。');
     quote.displayed=true;
    }
    if(!quote.configured)return blockedSubmission('费用未配置，请联系管理员；免费演示仍可使用。');
    headers.set('X-Expected-Credits',String(quote.credits));
   }catch(error){return blockedSubmission(error.message||'无法读取积分费用，当前未提交创作。');}
  }
  const response=await nativeFetch(input,{...init,headers});
  if(response.status===401||response.status===403||response.status===409){
   try{
    const data=await response.clone().json(),message=apiMessage(data,''),code=data?.detail?.code||data?.code||'';
    if(response.status===401&&(code==='login_required'||/请先登录|登录.*过期|请重新登录/.test(message))){showAuthentication('登录已过期，请重新登录。');location.reload();}
    else if(code==='csrf_failed'||/account[_-]?(changed|mismatch)/i.test(code)||/账号.*切换|账户.*切换/.test(message)){showAuthentication('登录状态已变化，正在重新读取账号。');location.reload();}
    else if(workflowId&&response.status===409&&/积分报价|积分价格|积分费用|费用.*配置/.test(message)){platform.quotes.delete(workflowId);if(platform.currentWorkflow===workflowId)refreshGenerationQuote(workflowId);}
   }catch{}
  }
  const balanceRead=method==='GET'&&(url.pathname==='/api/jobs'||/^\/api\/jobs\/[^/]+$/.test(url.pathname));
  const balanceWrite=method==='POST'&&(url.pathname==='/api/jobs'||/^\/api\/jobs\/[^/]+\/(rerun|cancel|abandon|retrieve)$/.test(url.pathname));
  if(response.ok&&(balanceRead||balanceWrite))scheduleBalanceRefresh();
  return response;
 };
}
function scheduleBalanceRefresh(){
 if(platform.preview||platform.localMode||!platform.identity||platform.balanceStopped)return;
 platform.balanceDirty=true;
 if(platform.balancePending||platform.balanceTimer)return;
 const wait=Math.max(0,4000-(Date.now()-platform.balanceLastAt));
 if(wait){platform.balanceTimer=setTimeout(()=>{platform.balanceTimer=null;refreshNativeBalance();},wait);}
 else refreshNativeBalance();
}
async function refreshNativeBalance(){
 if(platform.balanceStopped||platform.balancePending||!platform.balanceDirty)return;
 platform.balanceDirty=false;platform.balanceLastAt=Date.now();
 const identity=platform.identity;
 const pending=(async()=>{
  const response=await nativeFetch('/api/account/me',{credentials:'same-origin',headers:{'X-Platform-Account':String(identity.id)}});
  let data;try{data=await response.json();}catch{return;}
  if(!response.ok){
   const code=data?.detail?.code||data?.code||'',message=apiMessage(data,'');
   if(code==='login_required'||code==='csrf_failed'||/account[_-]?(changed|mismatch)/i.test(code)||/请先登录|登录.*过期|账号.*切换|账户.*切换/.test(message)){showAuthentication('登录状态已变化，正在重新读取账号。');location.reload();}
   return;
  }
  if(platform.balanceStopped)return;
  if(!data.user||String(data.user.id)!==String(identity.id)){showAuthentication('账号已切换，正在重新载入。');location.reload();return;}
  updateUser(data.user);
 })();
 platform.balancePending=pending;
 try{await pending;}catch{}finally{platform.balancePending=null;if(platform.balanceDirty&&!platform.balanceStopped)scheduleBalanceRefresh();}
}
function blockedSubmission(message){return new Response(JSON.stringify({detail:message,code:'quote_unavailable'}),{status:409,headers:{'Content-Type':'application/json'}});}
async function readGenerationQuote(workflowId,force=false){
 const cached=platform.quotes.get(workflowId);if(!force&&cached&&Date.now()-cached.readAt<30000)return cached;
 if(platform.quoteRequests.has(workflowId))return platform.quoteRequests.get(workflowId);
 const pending=(async()=>{
  const data=await request('/api/account/quote/'+encodeURIComponent(workflowId));
  if(data.workflow_id&&String(data.workflow_id)!==String(workflowId))throw new Error('积分费用与当前工作流不一致，请刷新工作区。');
  if(data.configured===true&&(!Number.isSafeInteger(data.credits)||data.credits<0))throw new Error('服务返回的积分费用无效，请联系管理员。');
  const quote={workflowId,credits:data.configured===true?data.credits:null,configured:data.configured===true,amountMinor:quoteAmount(data),displayed:false,readAt:Date.now()};platform.quotes.set(workflowId,quote);return quote;
 })();
 platform.quoteRequests.set(workflowId,pending);try{return await pending;}finally{platform.quoteRequests.delete(workflowId);}
}
function quoteAmount(data){
 if(Number.isSafeInteger(data.amount_minor)&&data.amount_minor>=0&&(!data.currency||data.currency==='CNY'))return data.amount_minor;
 const rate=data.credit_policy?.credits_per_yuan??data.credits_per_yuan??platform.pricingPolicy?.credit_policy?.credits_per_yuan;
 return Number.isSafeInteger(data.credits)&&data.credits>=0&&Number.isFinite(rate)&&rate>0?Math.ceil(data.credits*100/rate):null;
}
async function readPricingPolicy(){
 if(platform.pricingPolicy)return platform.pricingPolicy;
 if(platform.pricingPolicyRequest)return platform.pricingPolicyRequest;
 const pending=request('/api/account/pricing-policy');platform.pricingPolicyRequest=pending;
 try{const policy=await pending;platform.pricingPolicy=policy;return policy;}finally{platform.pricingPolicyRequest=null;}
}
function quoteFooter(generate){
 const root=generate.closest('#composer-slot,.wf-editor,.composer-slot')||generate.parentElement;
 return root.querySelector('.composer-foot>span:last-child');
}
function clearQuoteView(kind){
 const view=platform.quoteView;if(!view||view.kind!==kind)return;
 const busy=generationBusy(view);
 const original=view.button.querySelector('[data-platform-original-generation]');
 if(original&&!busy){view.button.replaceChildren(...original.childNodes);view.button.classList.remove('platform-priced-generation');view.button.removeAttribute('data-platform-price-state');}
 if(view.kind==='creation'&&!busy){view.button.disabled=view.originalDisabled;if(view.originalTitle===null)view.button.removeAttribute('title');else view.button.setAttribute('title',view.originalTitle);}
 if(view.footer?.isConnected&&view.footerOriginal!==undefined)view.footer.innerHTML=view.footerOriginal;
 platform.quoteView=null;
}
function clearGenerationQuote(){const previous=platform.quotes.get(platform.currentWorkflow);if(previous)previous.displayed=false;clearQuoteView('workflow');platform.currentWorkflow=null;}
function clearCreationQuote(){clearQuoteView('creation');platform.currentCreation=null;}
function beginQuoteView(generate,kind,key){
 const previous=platform.quoteView;
 if(previous&&previous.button===generate&&previous.kind===kind&&previous.key===key)return previous;
 if(previous)clearQuoteView(previous.kind);
 const original=document.createElement('span');original.dataset.platformOriginalGeneration='';
 original.append(...generate.childNodes);generate.append(original);
 const footer=quoteFooter(generate),view={button:generate,kind,key,original,footer,footerOriginal:footer?.innerHTML,originalDisabled:generate.disabled,originalTitle:generate.getAttribute('title')};platform.quoteView=view;
 return view;
}
function quoteViewCurrent(view){return platform.quoteView===view&&view.button.isConnected&&document.querySelector('[data-action="generate"]')===view.button;}
function generationBusy(view){return view.button.getAttribute('aria-busy')==='true'||view.button.disabled&&/正在提交|提交中|正在生成|正在上传/.test(view.original.textContent+' '+view.button.textContent);}
function paintQuote(view,state,quote=null){
 if(platform.localMode||!quoteViewCurrent(view)||generationBusy(view))return false;
 const creation=view.kind==='creation',configured=state==='ready'&&quote?.configured===true;
 const label='生成';
 const cost=configured?`${creation?'参考 ':''}${credits(quote.credits)} 积分`:`${state==='loading'?'核对费用…':state==='error'?'费用读取失败':'费用待定'}`;
 const copy=document.createElement('span');copy.className='platform-generation-copy';
 const title=document.createElement('span');title.className='platform-generation-title';title.textContent=label;
 const detail=document.createElement('small');detail.className='platform-generation-cost';detail.textContent=cost;copy.append(title,detail);
 const icons=Array.from(view.original.querySelectorAll('svg')).map(element=>element.cloneNode(true));
 view.original.hidden=true;view.button.replaceChildren(view.original,...(icons.length?[icons[0]]:[]),copy,...(icons.length>1?[icons.at(-1)]:[]));
 view.button.classList.add('platform-priced-generation');view.button.dataset.platformPriceState=state;
 if(creation){view.button.disabled=!(configured&&quote.available===true);if(view.button.disabled)view.button.setAttribute('title',state==='loading'?'正在核对费用与生成服务。':state==='error'?'暂时无法核对生成服务，请稍后重试。':quote?.availabilityReason||'该模型尚未接入生成服务，暂不能生成。');else view.button.removeAttribute('title');}
 if(view.footer){
  const monetary=configured&&quote.amountMinor!==null?` · 约 ${money(quote.amountMinor)}`:'';
  if(creation&&state==='ready'&&quote?.available!==true)view.footer.innerHTML='该模型尚未接入 · <a class="text-control control" href="#workflows">查看创作工具</a>';
  else view.footer.textContent=creation?(configured?`费用以本次报价为准${monetary}`:state==='loading'?'正在核对费用与生成服务。':state==='error'?'暂时无法核对生成服务，请稍后重试。':'尚未定价，请联系管理员。'):configured?`费用以本次报价为准${monetary}`:state==='loading'?'正在核对本次费用。':state==='error'?'无法核对费用，请稍后重试。':'尚未定价，请联系管理员。';
 }
 return true;
}
export async function refreshGenerationQuote(workflowId){
 const generate=document.querySelector('[data-action="generate"]');
 if(platform.localMode){clearGenerationQuote();return null;}
 if(!workflowId||platform.preview||!platform.user||!generate||generate.dataset.creationGeneration!==undefined){clearGenerationQuote();return null;}
 if(platform.currentWorkflow&&platform.currentWorkflow!==String(workflowId)){const previous=platform.quotes.get(platform.currentWorkflow);if(previous)previous.displayed=false;}
 platform.currentWorkflow=String(workflowId);const view=beginQuoteView(generate,'workflow',String(workflowId));
 const cached=platform.quotes.get(workflowId);paintQuote(view,cached&&Date.now()-cached.readAt<30000?'ready':'loading',cached);
 try{
  const quote=await readGenerationQuote(workflowId);
  if(quote.amountMinor===null&&quote.configured){try{await readPricingPolicy();quote.amountMinor=quoteAmount(quote);}catch{}}
  if(platform.currentWorkflow===String(workflowId)&&paintQuote(view,'ready',quote))quote.displayed=true;
  return quote;
 }catch(error){platform.quotes.delete(workflowId);if(platform.currentWorkflow===String(workflowId))paintQuote(view,'error');return null;}
}
function creationParameters(draft){
 return {model:String(draft.model||''),kind:String(draft.type||''),quality:String(draft.quality||''),count:draft.type==='video'?1:Number(draft.count??1),duration:draft.type==='video'?Number.parseInt(draft.duration,10):null};
}
async function readCreationQuote(parameters){
 const key=JSON.stringify(parameters),cached=platform.creationQuotes.get(key);
 if(cached&&Date.now()-cached.readAt<30000)return cached;
 if(platform.creationQuoteRequests.has(key))return platform.creationQuoteRequests.get(key);
 const pending=(async()=>{
  const data=await request('/api/account/creation-quote',{method:'POST',body:parameters});
  const echoed=data.request||data.parameters||data;
  for(const [name,value] of Object.entries(parameters))if(echoed[name]!==undefined&&String(echoed[name])!==String(value))throw new Error('参考费用与当前创作参数不一致。');
  if(data.mode!=='reference')throw new Error('无法确认创作参考费率。');
  if(data.configured===true&&(!Number.isSafeInteger(data.credits)||data.credits<0))throw new Error('参考费率无效。');
  const quote={configured:data.configured===true,available:data.available===true,availabilityReason:typeof data.availability_reason==='string'?data.availability_reason:'该模型尚未接入生成服务，暂不能生成。',credits:data.configured===true?data.credits:null,amountMinor:quoteAmount(data),readAt:Date.now()};platform.creationQuotes.set(key,quote);return quote;
 })();
 platform.creationQuoteRequests.set(key,pending);try{return await pending;}finally{platform.creationQuoteRequests.delete(key);}
}
export async function refreshCreationQuote(draft){
 const generate=document.querySelector('[data-action="generate"]');
 if(!draft||platform.preview||!platform.user||!generate||generate.dataset.creationGeneration===undefined){clearCreationQuote();return null;}
 if(platform.localMode)return refreshLocalCreationAvailability(draft,generate);
 const parameters=creationParameters(draft),key=JSON.stringify(parameters);platform.currentCreation=key;
 const view=beginQuoteView(generate,'creation',key),cached=platform.creationQuotes.get(key);
 paintQuote(view,cached&&Date.now()-cached.readAt<30000?'ready':'loading',cached);
 try{
  const quote=await readCreationQuote(parameters);
  if(quote.amountMinor===null&&quote.configured){try{await readPricingPolicy();quote.amountMinor=quoteAmount(quote);}catch{}}
  if(platform.currentCreation===key)paintQuote(view,'ready',quote);return quote;
 }catch(error){platform.creationQuotes.delete(key);if(platform.currentCreation===key)paintQuote(view,'error');return null;}
}
function paintCreationAvailability(view,state,service=null){
 if(!quoteViewCurrent(view)||generationBusy(view))return false;
 view.button.disabled=!(state==='ready'&&service?.available===true);
 const message=state==='loading'?'正在核对生成服务。':state==='error'?'暂时无法核对生成服务，请稍后重试。':service?.availabilityReason||'该模型尚未接入生成服务，暂不能生成。';
 if(view.button.disabled)view.button.setAttribute('title',message);else view.button.removeAttribute('title');
 if(view.footer){
  if(state==='ready'&&service?.available!==true)view.footer.innerHTML='该模型尚未接入 · <a class="text-control control" href="#workflows">查看创作工具</a>';
  else view.footer.textContent=view.button.disabled?message:'';
 }
 return true;
}
async function refreshLocalCreationAvailability(draft,generate){
 const parameters=creationParameters(draft),key=JSON.stringify(parameters);platform.currentCreation=key;
 const view=beginQuoteView(generate,'creation',key),cached=platform.creationQuotes.get(key);
 paintCreationAvailability(view,cached&&Date.now()-cached.readAt<30000?'ready':'loading',cached);
 try{
  let service=cached&&Date.now()-cached.readAt<30000?cached:null;
  if(!service){
   let pending=platform.creationQuoteRequests.get(key);
   if(!pending){
    pending=(async()=>{
     const data=await request('/api/account/creation-availability',{method:'POST',body:parameters});
     for(const [name,value] of Object.entries(parameters))if(data[name]!==undefined&&String(data[name])!==String(value))throw new Error('生成服务与当前创作参数不一致。');
     const result={available:data.available===true,availabilityReason:typeof data.availability_reason==='string'?data.availability_reason:'该模型尚未接入生成服务，暂不能生成。',readAt:Date.now()};
     platform.creationQuotes.set(key,result);return result;
    })();
    platform.creationQuoteRequests.set(key,pending);
   }
   try{service=await pending;}finally{if(platform.creationQuoteRequests.get(key)===pending)platform.creationQuoteRequests.delete(key);}
  }
  if(platform.currentCreation===key)paintCreationAvailability(view,'ready',service);return service;
 }catch(error){platform.creationQuotes.delete(key);if(platform.currentCreation===key)paintCreationAvailability(view,'error');return null;}
}
function updateUser(user){
 if(!user)return;
 if(platform.identity&&String(user.id)!==String(platform.identity.id))throw new Error('账号已切换，请刷新页面后继续。');
 platform.user=user;
 if(platform.localMode)return;
 document.querySelectorAll('[data-platform-balance]').forEach(element=>{element.textContent=credits(element.dataset.platformBalance==='held'?user.held:available(user));});
}

export async function initializePlatform({publicPreview=false}={}){
 platform.preview=publicPreview;if(publicPreview)return null;
 installEvents();
 try{
  const response=await nativeFetch('/api/account/me',{credentials:'same-origin'});
  let data;try{data=await response.json();}catch{throw new Error('账号服务暂时不可用，请稍后重试。');}
  platform.localMode=data.local_mode===true;
  if(response.status===401||!data.user){showAuthentication(response.ok?'':apiMessage(data,''));return null;}
  if(!response.ok)throw new Error(apiMessage(data,'无法读取账号信息，请稍后重试。'));
  if(!data.csrf_token)throw new Error('账号校验信息不完整，请重新登录。');
  if(platform.wrapped&&String(platform.identity.id)!==String(data.user.id)){showAuthentication('账号已切换，正在重新载入。');location.reload();return null;}
  if(platform.identity)platform.identity.csrfToken=data.csrf_token;else platform.identity={id:data.user.id,csrfToken:data.csrf_token};platform.user=data.user;platform.balanceStopped=false;installApiFetch();
  if(platform.localMode)document.body.classList.add('platform-local-mode');else document.body.classList.remove('platform-local-mode');
  document.body.classList.remove('platform-auth-required');document.getElementById('platform-auth-screen')?.remove();
  return data.user;
 }catch(error){showAuthentication(error.message||'无法连接账号服务，请稍后重试。');return null;}
}
function showAuthentication(message=''){
 closeAccountMenu();
 platform.balanceStopped=true;platform.balanceDirty=false;if(platform.balanceTimer){clearTimeout(platform.balanceTimer);platform.balanceTimer=null;}
 document.querySelectorAll('dialog[open]').forEach(dialog=>dialog.close());
 document.body.classList.add('platform-auth-required');
 let screen=document.getElementById('platform-auth-screen');if(screen&&screen.dataset.platformAuthMode===platform.authMode&&message){setError(screen,message);return;}
 if(!screen){screen=document.createElement('section');screen.id='platform-auth-screen';screen.className='platform-auth-screen';document.body.append(screen);}screen.dataset.platformAuthMode=platform.authMode;
 if(platform.localMode){screen.innerHTML=`<div class="platform-auth-brand">映序 <small>YINGXU</small></div><div class="platform-auth-card"><h1>连接本地服务</h1><p class="platform-error" data-platform-error role="alert">${escapeHtml(message||'本地用户信息暂时不可用，请重新连接。')}</p><div class="platform-auth-help">${button('重新连接服务','retry-auth')}</div></div>`;return;}
 const register=platform.authMode==='register';
 screen.innerHTML=`<div class="platform-auth-brand">映序 <small>YINGXU</small></div><div class="platform-auth-card"><h1>${register?'创建账号':'登录映序'}</h1><div class="platform-auth-tabs" role="group" aria-label="登录或注册">${button('登录','auth-mode','data-mode="login" aria-pressed="'+!register+'"')}${button('注册','auth-mode','data-mode="register" aria-pressed="'+register+'"')}</div><form data-platform-form="${register?'register':'login'}"><label>用户名<input name="username" autocomplete="username" required maxlength="80" autofocus></label><label>${register?'密码（至少10位）':'密码'}<input name="password" type="password" autocomplete="${register?'new-password':'current-password'}" ${register?'minlength="10"':''} required></label>${register?'<label>再次输入密码<input name="password_confirm" type="password" autocomplete="new-password" minlength="10" required></label>':''}<p class="platform-error" data-platform-error role="alert" ${message?'':'hidden'}>${escapeHtml(message)}</p><button type="submit" class="platform-button is-primary">${register?'注册并登录':'登录'}</button></form><div class="platform-auth-help">${button('重新连接服务','retry-auth')}</div></div>`;
}

export function accountNavigation(){
 const user=platform.user;if(!user||platform.preview)return '';
 return `<div class="platform-nav-account"><button type="button" class="nav-item platform-nav-user" data-platform-action="account-menu" aria-haspopup="menu" aria-expanded="false" aria-controls="platform-account-menu" aria-label="打开${escapeHtml(user.username)}的账号菜单" title="账号菜单"><i class="platform-avatar" aria-hidden="true">${escapeHtml(String(user.username||'用户').slice(0,1).toUpperCase())}</i><span class="platform-nav-copy"><strong>${escapeHtml(user.username)}</strong><small>${platform.localMode?'本地用户':`<span data-platform-balance="available">${credits(available(user))}</span> 积分`}</small></span><svg class="platform-nav-chevron" viewBox="0 0 16 16" aria-hidden="true"><path d="m4 10 4-4 4 4"/></svg></button></div>`;
}
function accountMenuContents(){
 const user=platform.user;
 if(platform.localMode)return `<div class="platform-menu-identity"><strong>${escapeHtml(user.username)}</strong><small>本地用户</small></div><a role="menuitem" href="#account">${icon('user')}<span>用户信息</span></a><a role="menuitem" href="#settings"><svg class="icon" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M4 7h16M4 17h16M8 4v6M16 14v6"/></svg><span>偏好设置</span></a>`;
 return `<div class="platform-menu-identity"><strong>${escapeHtml(user.username)}</strong><small>${user.role==='admin'?'管理员':'普通账号'} · <span data-platform-balance="available">${credits(available(user))}</span> 积分</small></div><a role="menuitem" href="#account">${icon('user')}<span>我的账号</span></a><a role="menuitem" href="#recharge">${icon('credit')}<span>积分充值</span></a><a role="menuitem" href="#settings"><svg class="icon" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M4 7h16M4 17h16M8 4v6M16 14v6"/></svg><span>偏好设置</span></a>${user.role==='admin'?`<a role="menuitem" href="/admin.html">${icon('admin')}<span>管理员后台</span><small>↗</small></a>`:''}<div class="platform-menu-divider"></div><button type="button" role="menuitem" data-platform-action="logout"><svg class="icon" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M9 4H5v16h4M9 12h12m-5-5 5 5-5 5"/></svg><span>退出登录</span></button>${errorRegion()}`;
}
function positionAccountMenu(){
 const menu=document.getElementById('platform-account-menu'),anchor=platform.menuAnchor;if(!menu||!anchor?.isConnected){closeAccountMenu();return;}
 const rect=anchor.getBoundingClientRect(),width=menu.offsetWidth,height=menu.offsetHeight,padding=12;
 menu.style.left=Math.max(padding,Math.min(rect.left,innerWidth-width-padding))+'px';
 menu.style.top=Math.max(padding,Math.min(rect.top-height-8,innerHeight-height-padding))+'px';
}
function openAccountMenu(anchor,focusIndex=null){
 if(!platform.user||platform.preview||!anchor?.isConnected)return;
 const existing=document.getElementById('platform-account-menu');
 if(existing&&platform.menuAnchor===anchor){if(focusIndex!==null){const items=existing.querySelectorAll('[role="menuitem"]');items[focusIndex<0?items.length-1:Math.min(focusIndex,items.length-1)]?.focus({preventScroll:true});}positionAccountMenu();return;}
 closeAccountMenu();platform.menuAnchor=anchor;
 const menu=document.createElement('div');menu.id='platform-account-menu';menu.className='platform-account-menu';menu.setAttribute('role','menu');menu.setAttribute('aria-label','账号菜单');menu.innerHTML=accountMenuContents();document.body.append(menu);anchor.setAttribute('aria-expanded','true');document.body.classList.add('platform-account-menu-open');
 document.dispatchEvent(new CustomEvent('platform-account-menu-change',{detail:{open:true}}));positionAccountMenu();
 if(focusIndex!==null){const items=menu.querySelectorAll('[role="menuitem"]');items[focusIndex<0?items.length-1:Math.min(focusIndex,items.length-1)]?.focus({preventScroll:true});}
}
function closeAccountMenu(restoreFocus=false){
 const menu=document.getElementById('platform-account-menu'),anchor=platform.menuAnchor;
 menu?.remove();if(anchor)anchor.setAttribute('aria-expanded','false');platform.menuAnchor=null;document.body.classList.remove('platform-account-menu-open');
 if(restoreFocus&&anchor?.isConnected)anchor.focus({preventScroll:true});
 if(menu)document.dispatchEvent(new CustomEvent('platform-account-menu-change',{detail:{open:false}}));
}
export function accountPage(kind='account'){
 if(platform.localMode)return `<section class="platform-page platform-local-account" data-platform-page="account"><header class="platform-page-header"><h1>用户信息</h1>${button('刷新','refresh-page')}</header><div data-platform-content>${localAccountContents(platform.user)}</div></section>`;
 const title=kind==='recharge'?'积分充值':'我的账号';
 if(kind==='admin')return '<section class="platform-page"><a class="platform-button" href="/admin.html">打开管理员后台 ↗</a></section>';
 if(platform.preview)return `<section class="platform-page"><h1>${title}</h1>${empty('账户操作请使用正式入口。')}</section>`;
 return `<section class="platform-page" data-platform-page="${kind==='recharge'?'recharge':'account'}"><header class="platform-page-header"><h1>${title}</h1>${button('刷新','refresh-page')}</header><nav class="platform-page-tabs" aria-label="账号中心"><a href="#account" ${kind==='account'?'aria-current="page"':''}>账号</a><a href="#recharge" ${kind==='recharge'?'aria-current="page"':''}>充值</a></nav><div data-platform-content><p class="platform-loading" role="status">正在读取账号信息…</p></div></section>`;
}
export async function loadAccountPage(kind='account'){
 if(kind==='admin'&&!platform.localMode)return;
 const selected=!platform.localMode&&kind==='recharge'?'recharge':'account',host=document.querySelector(`[data-platform-page="${selected}"]`);if(!host||platform.preview)return;
 const content=host.querySelector('[data-platform-content]'),run=host.platformLoad=(host.platformLoad||0)+1;
 try{
  const data=await request(platform.localMode?'/api/account/me':'/api/account/dashboard');
  if(!host.isConnected||host.platformLoad!==run)return;
  if(data.user)updateUser(data.user);
  if(platform.localMode&&data.csrf_token)platform.identity.csrfToken=data.csrf_token;
  content.innerHTML=platform.localMode?localAccountContents(data.user||platform.user):accountContents(data,selected);
 }catch(error){if(host.isConnected&&host.platformLoad===run)content.innerHTML=`<p class="platform-error" role="alert">${escapeHtml(error.message)}</p>${button('重新读取','refresh-page')}`;}
}
function localAccountContents(user){
 const name=user?.username||'本地用户';
 return `<div class="platform-local-profile"><div class="platform-profile"><i class="platform-avatar" aria-hidden="true">${escapeHtml(String(name).slice(0,1).toUpperCase())}</i><div><strong title="${escapeHtml(name)}">${escapeHtml(name)}</strong><small>本地用户</small></div></div><dl class="platform-local-details"><div><dt>用户名</dt><dd>${escapeHtml(name)}</dd></div><div><dt>用户标识</dt><dd>${escapeHtml(user?.id||'—')}</dd></div></dl></div>`;
}

function paymentMethods(data){
 return rows(data.methods).map(method=>({...method,id:String(method.id||method.method||''),label:method.label||method.id||method.method,enabled:method.enabled===true,automatic:method.automatic===true})).filter(method=>method.id);
}
function rechargeForm(data){
 const packages=rows(data.packages).filter(item=>item.enabled===true),methods=paymentMethods(data),ready=methods.filter(method=>method.enabled),closed=data.payment_status?.enabled===false,canOrder=!closed&&packages.length&&ready.length;
 return `<div class="platform-recharge-grid"><section class="platform-section platform-recharge"><h2>选择积分套餐</h2>${canOrder?`<form data-platform-form="recharge"><fieldset><div class="platform-packages">${packages.map((item,index)=>`<label class="platform-package"><input type="radio" name="package_id" value="${escapeHtml(item.id)}" ${index?'':'checked'} required><span><strong>${escapeHtml(item.title)}</strong><b>${credits(item.credits)} <small>积分</small></b><span>${money(item.amount_minor,item.currency||'CNY')}</span></span></label>`).join('')}</div><div class="platform-payment-choice"><label>支付方式<select name="method" data-platform-method>${ready.map(method=>`<option value="${escapeHtml(method.id)}" ${ready[0]?.id===method.id?'selected':''}>${escapeHtml(method.label)}</option>`).join('')}</select></label><button type="submit" class="platform-button is-primary">${ready[0]?.automatic?'创建充值订单':'创建待核对订单'}</button></div><div class="platform-payment-note" data-platform-payment-note>${paymentNote(ready[0],data.contact)}</div>${errorRegion()}<div data-platform-order-result></div></fieldset></form>`:`<div class="platform-quiet-empty">${icon('credit')}<div><strong>${closed?'充值暂未开放':!packages.length?'暂无积分套餐':'支付方式暂未开通'}</strong><p>${closed?'请稍后再来。':!packages.length?'套餐开放后可在这里充值。':'开通后可选择套餐并创建订单。'}</p></div></div>${platform.user?.role==='admin'?'<a class="platform-text-link" href="/admin.html#pricing">前往后台设置套餐 ↗</a>':''}`}</section><aside class="platform-payment-methods"><h2>支付方式</h2>${methods.length?`<ul>${methods.map(method=>`<li><span>${escapeHtml(method.label)}</span><small class="${method.enabled?'is-ready':''}">${method.enabled?(method.automatic?'已开通':'人工核对'):'未开通'}</small></li>`).join('')}</ul>`:empty('暂未开通支付方式。')}<p class="platform-caption">积分到账以订单状态为准。</p></aside></div>`;
}
function paymentNote(method,contact){
 if(!method)return '支付方式尚未开通，暂时不能付款。';
 const instructions=typeof contact==='string'?contact:contact?.[method.id]||contact?.[method.method]||'',message=method.message||'';
 if(!method.automatic)return `<p>创建订单后，按管理员提供的方式核对付款。管理员确认后积分才会到账。</p>${instructions?`<p>${escapeHtml(instructions)}</p>`:''}${message&&message!==instructions?`<p>${escapeHtml(message)}</p>`:''}`;
 return `<p>创建订单后前往已开通的支付平台，返回页面刷新订单状态。</p>${message?`<p>${escapeHtml(message)}</p>`:''}`;
}
function accountContents(data,kind){
 if(platform.localMode)return localAccountContents(data.user||platform.user);
 const user=data.user||platform.user;
 const recordTab=platform.recordTabs[kind]||'ledger';
 return `<div class="platform-summary"><div class="platform-profile"><i class="platform-avatar" aria-hidden="true">${escapeHtml(String(user?.username||'用户').slice(0,1).toUpperCase())}</i><div><strong title="${escapeHtml(user?.username)}">${escapeHtml(user?.username)}</strong><small>${user?.role==='admin'?'管理员':'普通账号'}</small></div></div><div class="platform-summary-credit"><span>可用积分</span><strong data-platform-balance="available">${credits(available(user))}</strong></div><div class="platform-summary-credit is-held" title="正在处理的创作会暂时冻结积分"><span>冻结积分</span><strong data-platform-balance="held">${credits(user?.held)}</strong></div>${kind==='account'?'<a class="platform-button is-primary" href="#recharge">充值积分</a>':''}</div>${kind==='recharge'?rechargeForm(data):''}<section class="platform-section platform-records"><div class="platform-record-tabs" role="group" aria-label="积分与充值记录">${button('积分记录','records-tab',`data-records="ledger" aria-pressed="${recordTab==='ledger'}"`)}${button('充值订单','records-tab',`data-records="orders" aria-pressed="${recordTab==='orders'}"`)}</div><div data-platform-record-panel="ledger" ${recordTab==='ledger'?'':'hidden'}>${ledgerTable(rows(data.ledger))}</div><div data-platform-record-panel="orders" ${recordTab==='orders'?'':'hidden'}>${ordersTable(rows(data.orders))}</div></section>${kind==='account'?`<details class="platform-security"><summary><span>${icon('admin')}<strong>账号安全</strong></span><span class="platform-security-label">修改密码 <i aria-hidden="true">⌄</i></span></summary><form class="platform-password-form" data-platform-form="password"><label>当前密码<input name="current_password" type="password" autocomplete="current-password" required></label><label>新密码<input name="new_password" type="password" autocomplete="new-password" minlength="10" required placeholder="至少10位"></label><label>确认新密码<input name="new_password_confirm" type="password" autocomplete="new-password" minlength="10" required></label>${errorRegion()}<p class="platform-success" data-platform-success role="status" hidden></p><button type="submit" class="platform-button">保存新密码</button></form></details>`:''}`;
}
function ordersTable(orders){
 if(!orders.length)return empty('暂无充值订单。');
 return `<div class="platform-table-wrap"><table class="platform-table"><thead><tr><th>订单</th><th>积分 / 金额</th><th>方式</th><th>状态</th><th>创建时间</th><th>操作</th></tr></thead><tbody>${orders.map(order=>`<tr><td><span class="platform-order-id" title="${escapeHtml(order.id)}">${escapeHtml(order.id)}</span></td><td>${credits(order.credits)} 积分<small>${money(order.amount_minor,order.currency||'CNY')}</small></td><td>${escapeHtml(({alipay:'支付宝',wechat:'微信',bank:'银行卡',admin_contact:'联系管理员'})[order.method]||order.method)}</td><td><span class="platform-status${order.status==='confirmed'?' is-confirmed':''}">${escapeHtml(statusNames[order.status]||order.status||'待核对')}</span></td><td>${date(order.created_at)}</td><td>${button('核对状态','order-status',`data-order-id="${escapeHtml(order.id)}"`)}<p class="platform-error" data-platform-error role="alert" hidden></p><div data-platform-order-status></div></td></tr>`).join('')}</tbody></table></div>`;
}
function ledgerTable(ledger){
 if(!ledger.length)return empty('暂无积分记录。');
 return `<div class="platform-table-wrap"><table class="platform-table"><thead><tr><th>时间</th><th>事项</th><th>积分变动</th><th>冻结变动</th><th>可用 / 冻结余额</th></tr></thead><tbody>${ledger.map(entry=>`<tr><td>${date(entry.created_at)}</td><td>${escapeHtml(eventNames[entry.event]||entry.event||entry.description||'积分记录')}${entry.reason?`<small>${escapeHtml(entry.reason)}</small>`:''}${entry.resource_id?`<small class="platform-resource-id">${escapeHtml(entry.resource_id)}</small>`:''}</td><td>${signed(entry.amount)}</td><td>${signed(entry.held_amount)}</td><td>${credits(entry.balance_after)} / ${credits(entry.held_after)}</td></tr>`).join('')}</tbody></table></div>`;
}
function setError(host,message=''){
 const element=host?.querySelector('[data-platform-error]');if(element){element.textContent=message;element.hidden=!message;}
}
function safeCheckoutUrl(value){
 if(!value)return '';try{const url=new URL(value,location.href);return url.protocol==='https:'||url.origin===location.origin&&url.protocol==='http:'?url.href:'';}catch{return '';}
}
function orderResult(order,checkout){
 const details=checkout||order?.checkout||{},url=safeCheckoutUrl(details.url||details.checkout_url),state=statusNames[order?.status]||order?.status||'待核对';
 const qr=typeof details.qr_code==='string'?details.qr_code:'',image=typeof details.qr_code_image==='string'&&/^data:image\/png;base64,[a-z\d+/=]+$/i.test(details.qr_code_image)?details.qr_code_image:'';
 const bank=[['收款人',details.account_name],['银行',details.bank_name],['银行卡号',details.account_number]].filter(([,value])=>value);
 const payment=order?.status==='confirmed'?'<p>支付已由服务端确认，刷新账号信息可核对积分余额。</p>':order?.status!=='pending'?'<p>当前订单不能继续付款，请返回充值页面创建新订单。</p>':`<p>尚未确认到账。付款后请核对此订单；创建订单不会自动增加积分。</p>${image?`<img class="platform-payment-qr" src="${escapeHtml(image)}" alt="当前充值订单的真实支付二维码">`:''}${qr?`<label>支付信息<textarea class="platform-payment-string" data-platform-payment-string readonly rows="3">${escapeHtml(qr)}</textarea></label>${button('复制支付信息','copy-payment')}${!image?'<p>此订单尚未提供二维码图片，请使用支付平台支持的支付信息方式，或联系管理员。</p>':''}`:''}${url?`<a class="platform-button is-primary" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">前往支付平台</a>`:''}${bank.length?`<dl class="platform-bank-details">${bank.map(([label,value])=>`<dt>${label}</dt><dd>${escapeHtml(value)}</dd>`).join('')}</dl>`:''}${details.contact?`<p>${escapeHtml(details.contact)}</p>`:''}${details.instructions?`<p>${escapeHtml(details.instructions)}</p>`:''}${details.expires_at?`<p>支付信息有效期至 ${date(details.expires_at)}</p>`:''}`;
 return `<div class="platform-order-notice"><strong>订单${escapeHtml(state)}</strong><p>订单号：${escapeHtml(order?.id)}</p>${payment}${order?.id?button('核对此订单','order-status',`data-order-id="${escapeHtml(order.id)}"`):''}${errorRegion()}<div data-platform-order-status></div></div>`;
}
async function handleForm(form){
 if(form.dataset.platformBusy==='true')return;
 const kind=form.dataset.platformForm,values=new FormData(form),get=name=>String(values.get(name)||'');
 if(platform.localMode)return;
 if(kind==='register'&&get('password')!==get('password_confirm')){setError(form,'两次输入的密码不一致。');return;}
 if(kind==='password'&&get('new_password')!==get('new_password_confirm')){setError(form,'两次输入的新密码不一致。');return;}
 setError(form);form.dataset.platformBusy='true';const submit=form.querySelector('button[type="submit"]');if(submit)submit.disabled=true;
 try{
  if(kind==='login'||kind==='register'){await request('/api/account/'+kind,{method:'POST',anonymous:true,body:{username:get('username').trim(),password:get('password')}});location.reload();return;}
  if(kind==='password'){
   const data=await request('/api/account/password',{method:'POST',body:{current_password:get('current_password'),new_password:get('new_password')}});if(data.csrf_token)platform.identity.csrfToken=data.csrf_token;
   if(data.sessions_revoked){form.reset();platform.authMode='login';showAuthentication('密码已修改，请使用新密码重新登录。');location.reload();return;}
   form.reset();const notice=form.querySelector('[data-platform-success]');notice.textContent='密码已修改。';notice.hidden=false;return;
  }
  if(kind==='recharge'){
   const choice=get('package_id')+'|'+get('method');if(form.dataset.platformOrderChoice!==choice){form.dataset.platformOrderChoice=choice;form.dataset.platformIdempotency=crypto.randomUUID();}
   const data=await request('/api/account/orders',{method:'POST',body:{package_id:get('package_id'),method:get('method'),idempotency_key:form.dataset.platformIdempotency}});
   if(!data.order?.id)throw new Error('服务没有返回可核对的订单，请刷新订单列表确认后再试。');
   form.querySelector('[data-platform-order-result]').innerHTML=orderResult(data.order,data.checkout);return;
  }
  return;
 }catch(error){setError(form,error.message||'操作未完成，请稍后重试。');}
 finally{form.dataset.platformBusy='false';if(submit?.isConnected)submit.disabled=false;}
}
async function handleAction(element){
 const action=element.dataset.platformAction,host=element.closest('[data-platform-page]');
 if(platform.localMode&&['records-tab','auth-mode','logout','order-status','copy-payment'].includes(action))return;
 if(action==='account-menu'){if(platform.menuAnchor===element&&document.getElementById('platform-account-menu'))closeAccountMenu();else openAccountMenu(element);return;}
 if(action==='records-tab'){
  if(!host)return;const selected=element.dataset.records==='orders'?'orders':'ledger';platform.recordTabs[host.dataset.platformPage]=selected;
  host.querySelectorAll('[data-platform-action="records-tab"]').forEach(tab=>tab.setAttribute('aria-pressed',String(tab.dataset.records===selected)));
  host.querySelectorAll('[data-platform-record-panel]').forEach(panel=>{panel.hidden=panel.dataset.platformRecordPanel!==selected;});return;
 }
 if(action==='auth-mode'){platform.authMode=element.dataset.mode==='register'?'register':'login';showAuthentication();return;}
 if(action==='retry-auth'){element.disabled=true;const user=await initializePlatform();if(user)location.reload();else if(element.isConnected)element.disabled=false;return;}
 if(action==='refresh-page'){if(host){element.disabled=true;await loadAccountPage(host.dataset.platformPage);if(element.isConnected)element.disabled=false;}return;}
 if(action==='logout'){
  element.disabled=true;try{await request('/api/account/logout',{method:'POST',body:{}});location.reload();}catch(error){let notice=element.parentElement.querySelector('[data-platform-error]');if(!notice){notice=document.createElement('p');notice.className='platform-error';notice.dataset.platformError='';notice.setAttribute('role','alert');element.parentElement.append(notice);}notice.textContent=error.message;notice.hidden=false;element.disabled=false;}return;
 }
 const region=element.closest('td,.platform-order-notice')||host;if(!region)return;setError(region);element.disabled=true;
 try{
  if(action==='order-status'){
   const data=await request('/api/account/orders/'+encodeURIComponent(element.dataset.orderId)),order=data.order||data;
   region.querySelector('[data-platform-order-status]').innerHTML=`<p class="platform-caption">当前状态：${escapeHtml(statusNames[order.status]||order.status)}</p>`;
   if(order.status==='confirmed'&&host)await loadAccountPage(host.dataset.platformPage);
  }else if(action==='copy-payment'){await navigator.clipboard.writeText(region.querySelector('[data-platform-payment-string]').value);region.querySelector('[data-platform-order-status]').textContent='支付信息已复制。';}
 }catch(error){setError(region,error.message||'操作未完成，请稍后重试。');}
 finally{if(element.isConnected)element.disabled=false;}
}
function installEvents(){
 if(platform.installed)return;platform.installed=true;
 document.addEventListener('submit',event=>{const form=event.target.closest?.('[data-platform-form]');if(!form)return;event.preventDefault();handleForm(form);});
 document.addEventListener('click',event=>{const element=event.target.closest?.('[data-platform-action]');if(element&&!element.disabled)handleAction(element);if(event.target.closest?.('#platform-account-menu a'))closeAccountMenu();});
 document.addEventListener('pointerdown',event=>{const menu=document.getElementById('platform-account-menu');if(menu&&!menu.contains(event.target)&&!platform.menuAnchor?.contains(event.target))closeAccountMenu();});
 document.addEventListener('focusin',event=>{const menu=document.getElementById('platform-account-menu');if(menu&&!menu.contains(event.target)&&!platform.menuAnchor?.contains(event.target))closeAccountMenu();});
 document.addEventListener('keydown',event=>{
  const anchor=event.target.closest?.('[data-platform-action="account-menu"]'),menu=document.getElementById('platform-account-menu');
  if(anchor&&(event.key==='ArrowDown'||event.key==='ArrowUp')){event.preventDefault();event.stopImmediatePropagation();openAccountMenu(anchor,event.key==='ArrowUp'?-1:0);return;}
  if(!menu)return;
  if(event.key==='Escape'){event.preventDefault();event.stopImmediatePropagation();closeAccountMenu(true);return;}
  if(!menu.contains(event.target))return;
  if(event.key==='Tab'){closeAccountMenu(true);return;}
  if(!['ArrowDown','ArrowUp','Home','End'].includes(event.key))return;
  event.preventDefault();event.stopImmediatePropagation();const items=[...menu.querySelectorAll('[role="menuitem"]')],current=items.indexOf(document.activeElement);
  const next=event.key==='Home'?0:event.key==='End'?items.length-1:(current+(event.key==='ArrowUp'?-1:1)+items.length)%items.length;items[next]?.focus({preventScroll:true});
 },true);
 addEventListener('hashchange',()=>{closeAccountMenu();clearGenerationQuote();clearCreationQuote();});addEventListener('resize',positionAccountMenu);
 document.addEventListener('change',event=>{
  if(!event.target.matches?.('[data-platform-method]'))return;
  const form=event.target.closest('[data-platform-form="recharge"]'),option=event.target.selectedOptions[0];
  if(form){loadPaymentNote(form,option.value);}
 });
}
async function loadPaymentNote(form,methodId){
 try{const data=await request('/api/account/dashboard');if(!form.isConnected||form.querySelector('[data-platform-method]').value!==methodId)return;const method=paymentMethods(data).find(item=>item.id===methodId);form.querySelector('[data-platform-payment-note]').innerHTML=paymentNote(method,data.contact);form.querySelector('button[type="submit"]').textContent=method?.automatic?'创建充值订单':'创建待核对订单';}catch(error){if(form.isConnected)setError(form,error.message);}
}
