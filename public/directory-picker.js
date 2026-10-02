// Shared by the real editor and the local component examples.
export function installDirectoryPicker({getCommit}){
 document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-local-directory]');if(!button)return;
  const field=button.closest('.catalog-directory-field'),input=field.querySelector('input'),status=field.querySelector('[data-directory-status]'),commit=getCommit(button);
  if(!commit)return;
  button.disabled=true;status.textContent='请在系统窗口中选择文件夹…';
  try{
   const response=await fetch('/api/local-directory',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({initial:input.value})});
   if(!response.ok){let message='本机目录选择服务不可用，请直接填写路径。';try{message=(await response.json()).detail||message;}catch{}throw new Error(message);}
   const result=await response.json();
   if(result.path){input.value=result.path;commit(result.path);status.textContent='已选择本机目录；生成时仍需运行端可访问此路径。';}
   else status.textContent='已取消，原目录未改变。';
  }catch(error){status.textContent=error.message;}
  finally{button.disabled=false;}
 });
}
