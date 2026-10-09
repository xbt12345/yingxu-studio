import {legacyStrokesToRegions,paintSelections} from './reference-editor.js?v=88.0';

export const MASK_ENCODING='rgb-mask-v1';
const editedMask=ref=>ref.annotationMode==='mask';
export const canReuseReferenceUpload=ref=>!!ref.serverAssetId&&(!editedMask(ref)||ref.maskEncoding===MASK_ENCODING);

async function readBlob(src){
 const response=await fetch(src);if(!response.ok)throw new Error('素材链接已失效');return response.blob();
}
async function restoreMask(ref,original){
 const url=URL.createObjectURL(original),image=new Image();image.src=url;
 try{
  await image.decode();const canvas=document.createElement('canvas');canvas.width=image.naturalWidth;canvas.height=image.naturalHeight;
  const regions=ref.referenceEdits?.regions??legacyStrokesToRegions(ref.annotationStrokes,canvas.width,canvas.height),ctx=canvas.getContext('2d');
  ctx.fillStyle=ctx.strokeStyle='#fff';paintSelections(ctx,regions,canvas.width,canvas.height);
  return await new Promise((resolve,reject)=>canvas.toBlob(blob=>blob?resolve(blob):reject(new Error('无法恢复编辑掩膜')),'image/png'));
 }finally{URL.revokeObjectURL(url);}
}

// Preserve original RGB separately: browser destination-out discards hidden pixel colors.
export async function referenceUploadParts(ref,assets,{fetchBlob=readBlob,renderMask=restoreMask}={}){
 if(!editedMask(ref)){const asset=assets.find(a=>a.id===ref.assetId);return {file:asset?.blob||await fetchBlob(ref.src),paired:false};}
 const originalAsset=assets.find(a=>a.id===ref.originalAssetId),originalSrc=originalAsset?.src||(ref.originalServerAssetId?'/api/assets/'+ref.originalServerAssetId+'/file':ref.originalSrc);
 let file;
 try{file=originalAsset?.blob||(originalSrc?await fetchBlob(originalSrc):null);}catch{throw new Error('编辑原图已失效，请重新导入原图并标注；不能使用丢失颜色的透明预览生成。');}
 if(!file)throw new Error('找不到编辑原图，请重新导入原图并标注；不能使用透明预览代替原图。');
 const maskAsset=assets.find(a=>a.id===ref.maskAssetId);let mask=maskAsset?.blob;
 if(!mask&&ref.maskSrc)try{mask=await fetchBlob(ref.maskSrc);}catch{}
 if(!mask&&(ref.referenceEdits?.regions||ref.annotationStrokes?.length))mask=await renderMask(ref,file);
 if(!mask)throw new Error('编辑掩膜已失效，请重新标注编辑区域后生成。');
 return {file,mask,paired:true,encoding:MASK_ENCODING};
}

export function referenceUploadForm(parts,filename){
 const form=new FormData();form.append('file',parts.file,filename);if(parts.mask)form.append('mask',parts.mask,'edit-mask.png');return form;
}
