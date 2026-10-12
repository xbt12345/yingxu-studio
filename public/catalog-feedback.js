// Keep submission errors visible and move the user to the input that needs work.
const errorId='catalog-submission-error';
export function clearCatalogIssue(root=document.querySelector('.catalog-editor')){
 if(!root)return;
 root.querySelector('#'+errorId)?.remove();
 for(const node of root.querySelectorAll('[data-catalog-invalid]')){
  node.removeAttribute('aria-invalid');node.removeAttribute('data-catalog-invalid');
  const ids=(node.getAttribute('aria-describedby')||'').split(' ').filter(id=>id&&id!==errorId);
  if(ids.length)node.setAttribute('aria-describedby',ids.join(' '));else node.removeAttribute('aria-describedby');
 }
}
export function showCatalogIssue(message,{textId,slotId,apiId,fieldId}={}){
 const root=document.querySelector('.catalog-editor');if(!root)return;
 clearCatalogIssue(root);
 const selector=textId?`[data-catalog-text="${CSS.escape(textId)}"]`:slotId?`[data-catalog-pick="${CSS.escape(slotId)}"]`:apiId?`[data-catalog-api="${CSS.escape(apiId)}"][data-api-field="apiKey"]`:fieldId?`[data-catalog-field="${CSS.escape(fieldId)}"]`:null;
 let input=selector?root.querySelector(selector):[...root.querySelectorAll('input:invalid,textarea:invalid')].find(node=>node.checkVisibility());
 if(fieldId&&input?.validity&&!input.validity.valid){
  const label=input.getAttribute('aria-label')||input.closest('.catalog-field')?.querySelector('label')?.textContent||'此参数';
  const bounds=input.min&&input.max?`${input.min}–${input.max}`:input.min?`至少 ${input.min}`:input.max?`最多 ${input.max}`:'';
  message=input.validity.valueMissing?`请填写${label}。`:`请检查${label}${bounds?'：'+bounds:''}${input.validity.stepMismatch&&input.step&&input.step!=='any'?'，步长 '+input.step:''}。`;
 }
 if(input?.matches('select.wf-select-value'))input=input.nextElementSibling;
 input=input?.closest('[data-timecode-control]')?.querySelector('[data-time-display]')||input;
 const note=document.createElement('p');note.id=errorId;note.className='catalog-submission-error';note.setAttribute('role','alert');note.textContent=message;
 root.querySelector('.wf-editor-footer').before(note);
 if(input){input.setAttribute('data-catalog-invalid','');input.setAttribute('aria-invalid','true');input.setAttribute('aria-describedby',[input.getAttribute('aria-describedby'),errorId].filter(Boolean).join(' '));input.scrollIntoView({block:'center'});input.focus({preventScroll:true});}
}
document.addEventListener('input',event=>{const root=event.target.closest('.catalog-editor');if(!root)return;const target=root.querySelector('[data-catalog-invalid]');if(!target||target===event.target)clearCatalogIssue(root);});
