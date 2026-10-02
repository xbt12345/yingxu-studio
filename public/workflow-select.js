import {esc,I} from './data.js';

// Keep the original select as the value/option authority and enhance its presentation.
export function selectControl({id,label,value,options,attrs=''}){
 const items=options.map(x=>({value:String(x?.value??x),label:String(x?.label??String(x).match(/\d+:\d+/)?.[0]??x)}));
 const selected=items.find(x=>x.value===String(value))||items[0];
 return `<div class="wf-select" data-control-component="select"><select id="${esc(id)}" class="wf-select-value" tabindex="-1" aria-hidden="true" ${attrs}>${items.map(x=>`<option value="${esc(x.value)}" ${x===selected?'selected':''}>${esc(x.label)}</option>`).join('')}</select><button type="button" id="${esc(id)}-trigger" class="wf-select-trigger" role="combobox" aria-label="${esc(label)}" aria-haspopup="listbox" aria-expanded="false"><span>${esc(selected?.label||'选择')}</span>${I('down')}</button></div>`;
}

let installed=false,opened=null,sequence=0;
export function installWorkflowSelects(){
 if(installed)return;installed=true;
 const close=({restore=false}={})=>{if(!opened)return;const {button,menu}=opened;button.setAttribute('aria-expanded','false');button.removeAttribute('aria-activedescendant');button.removeAttribute('aria-controls');menu.remove();opened=null;if(restore)(button.isConnected?button:document.getElementById(button.id))?.focus({preventScroll:true});};
 const activate=index=>{if(!opened)return;const {menu,button}=opened,items=[...menu.children];opened.index=(index+items.length)%items.length;items.forEach((el,i)=>el.classList.toggle('is-active',i===opened.index));const item=items[opened.index];button.setAttribute('aria-activedescendant',item.id);if(item.offsetTop<menu.scrollTop)menu.scrollTop=item.offsetTop;else if(item.offsetTop+item.offsetHeight>menu.scrollTop+menu.clientHeight)menu.scrollTop=item.offsetTop+item.offsetHeight-menu.clientHeight;};
 const choose=index=>{if(!opened)return;const {select,button}=opened,option=select.options[index];if(!option||option.disabled)return;close();select.value=option.value;button.querySelector('span').textContent=option.textContent;select.dispatchEvent(new Event('input',{bubbles:true}));select.dispatchEvent(new Event('change',{bubbles:true}));(button.isConnected?button:document.getElementById(button.id))?.focus({preventScroll:true});};
 const open=button=>{
  close();const select=button.parentElement.querySelector('select');if(select.disabled)return;
  const menu=document.createElement('div');menu.className='wf-select-menu'+(select.id==='catalog-switch'?' wf-tool-menu':'');menu.id='wf-select-menu-'+(++sequence);menu.setAttribute('role','listbox');menu.setAttribute('aria-label',button.getAttribute('aria-label'));
  [...select.options].forEach((option,index)=>{const item=document.createElement('div');item.id=menu.id+'-'+index;item.setAttribute('role','option');item.setAttribute('aria-selected',String(option.selected));item.dataset.selectIndex=index;item.textContent=option.textContent;menu.append(item);});
  // A modal makes content outside it inert. Keep its menu inside the modal and
  // position in that scroll container's coordinates, without scrolling the page.
  const host=button.closest('dialog[open]');(host||document.body).append(menu);
  const rect=button.getBoundingClientRect(),bounds=host?.getBoundingClientRect(),left=bounds?bounds.left+12:12,right=bounds?bounds.right-12:innerWidth-12,top=bounds?bounds.top+12:12,bottom=bounds?bounds.bottom-12:innerHeight-12;
  const width=Math.min(Math.max(rect.width,Number(select.dataset.menuMinWidth)||170),right-left);menu.style.width=width+'px';const height=Math.min(menu.scrollHeight+2,260,bottom-top),below=bottom-rect.bottom-6;
  const x=Math.max(left,Math.min(rect.left,right-width)),y=below>=height?rect.bottom+6:Math.max(top,Math.min(rect.top-height-6,bottom-height));
  menu.style.maxHeight=height+'px';if(host){menu.style.position='absolute';menu.style.left=x-bounds.left+host.scrollLeft-host.clientLeft+'px';menu.style.top=y-bounds.top+host.scrollTop-host.clientTop+'px';}else{menu.style.left=x+'px';menu.style.top=y+'px';}
  opened={button,select,menu,index:Math.max(0,select.selectedIndex)};button.setAttribute('aria-expanded','true');button.setAttribute('aria-controls',menu.id);activate(opened.index);
  menu.addEventListener('pointerdown',e=>e.preventDefault());menu.addEventListener('click',e=>{const item=e.target.closest('[data-select-index]');if(item)choose(Number(item.dataset.selectIndex));});
 };
 document.addEventListener('click',e=>{const button=e.target.closest('.wf-select-trigger');if(button){if(opened?.button===button)close();else open(button);}else if(!e.target.closest('.wf-select-menu'))close();});
 document.addEventListener('keydown',e=>{
  const button=e.target.closest('.wf-select-trigger');if(!button)return;
  if(['ArrowDown','ArrowUp','Home','End','Enter',' '].includes(e.key)){e.preventDefault();if(!opened){open(button);return;}if(e.key==='Enter'||e.key===' ')choose(opened.index);else activate(e.key==='Home'?0:e.key==='End'?opened.select.options.length-1:opened.index+(e.key==='ArrowDown'?1:-1));}
  else if(e.key==='Escape'&&opened){e.preventDefault();close({restore:true});}else if(e.key==='Tab')close();
 });
 document.addEventListener('input',e=>{if(e.target.matches('.wf-select-value'))e.target.nextElementSibling.querySelector('span').textContent=e.target.selectedOptions[0]?.textContent||'';});
 document.addEventListener('scroll',e=>{if(opened&&!opened.menu.contains(e.target))close();},true);
 document.addEventListener('close',()=>close(),true);
 window.addEventListener('resize',()=>close());window.addEventListener('hashchange',()=>close());
}
