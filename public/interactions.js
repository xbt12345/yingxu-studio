const escape=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let pending=false;
export function confirmAction({title,message,label='确认删除'}){
  if(pending)return Promise.resolve(false);
  pending=true;
  return new Promise(resolve=>{
    const d=document.createElement('dialog');d.className='confirm-dialog';
    d.innerHTML=`<form method="dialog"><div class="dialog-head"><h2>${escape(title)}</h2><button class="icon-button" value="cancel" aria-label="关闭确认框">×</button></div><p class="confirm-description">${escape(message)}</p><div class="dialog-actions"><button class="small-button" value="cancel" autofocus>返回</button><button class="button primary caution-action" value="confirm">${escape(label)}</button></div></form>`;
    document.body.append(d);d.addEventListener('close',()=>{const confirmed=d.returnValue==='confirm';d.remove();pending=false;resolve(confirmed);},{once:true});d.showModal();
  });
}

// Keep a native textarea for IME, undo and selection. Only its backdrop marks bindings.
export function mountMentions(input,getReferences){
  if(!input)return()=>{};
  const wrap=input.parentElement;wrap.classList.add('has-mention-overlay');
  const mirror=document.createElement('div');mirror.className='prompt-mirror';mirror.setAttribute('aria-hidden','true');
  const status=document.createElement('span');status.className='mention-feedback';status.id='mention-status';status.setAttribute('aria-live','polite');
  input.setAttribute('aria-describedby','mention-status');wrap.prepend(mirror);wrap.append(status);
  function sync(){
    const refs=getReferences().filter(r=>r.available!==false),ids=new Set(refs.map(r=>'@'+r.id));let count=0,missing=0;
    mirror.innerHTML=escape(input.value).replace(/@(图片|视频|音频)\d+/g,token=>{const bound=ids.has(token);bound?count++:missing++;return `<mark class="mention-${bound?'bound':'missing'}">${token}</mark>`;})+'\n';
    const msg=count||missing?`${count} 处素材引用已绑定${missing?`，${missing} 处未绑定`:''}`:'';
    if(status.textContent!==msg)status.textContent=msg;
    input.dataset.mentions=String(count);input.dataset.missingMentions=String(missing);
    const css=getComputedStyle(input);
    for(const key of ['fontFamily','fontSize','fontWeight','lineHeight','letterSpacing','paddingTop','paddingRight','paddingBottom','paddingLeft','textIndent','tabSize','wordBreak','overflowWrap'])mirror.style[key]=css[key];
    mirror.style.left=input.offsetLeft+'px';mirror.style.top=input.offsetTop+'px';mirror.style.width=input.clientWidth+'px';mirror.style.height=input.clientHeight+'px';
    mirror.scrollTop=input.scrollTop;mirror.scrollLeft=input.scrollLeft;
  }
  const ro=new ResizeObserver(sync);ro.observe(input);input.addEventListener('input',sync);input.addEventListener('scroll',sync);input.addEventListener('mentionchange',sync);sync();
  return()=>{ro.disconnect();input.removeEventListener('input',sync);input.removeEventListener('scroll',sync);input.removeEventListener('mentionchange',sync);mirror.remove();status.remove();};
}
