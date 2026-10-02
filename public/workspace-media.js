// A workflow can reference only the media bound to its current input slots.
export function boundReferences(d,w){
 const refs=(d.refs||[]).filter(r=>r.src&&r.available!==false);
 if(w?.catalogOnly)return (w.interface?.media||[]).map(slot=>refs.find(r=>r.catalogSlot===slot.id&&r.kind===slot.kind)).filter(Boolean);
 return d.mode==='纯文本'?[]:refs.filter(r=>(d.type!=='image'||r.kind==='image')&&(d.mode==='首尾帧'?r.slot!==undefined:r.slot===undefined));
}

export function sameMedia(a,b){
 if((a.kind||a.type)!==(b.kind||b.type))return false;
 return !!((a.sourceOutputId&&a.sourceOutputId===(b.sourceOutputId||b.id))||(a.assetId&&a.assetId===(b.assetId||b.id))||(a.serverAssetId&&a.serverAssetId===b.serverAssetId)||(a.src&&a.src===b.src));
}

export function missingMentions(text,refs){
 const ids=new Set(refs.map(r=>'@'+r.id));
 return [...new Set((text||'').match(/@(图片|视频|音频)\d+/g)||[])].filter(token=>!ids.has(token));
}

// Clear content only after an accepted submission. Keep model/output preferences.
export function clearSubmittedContent(session,{retry=false}={}){
 if(session.scope!=='model'||retry)return false;
 Object.assign(session.draft,{prompt:'',negative:'',refs:[],error:null});
 return true;
}

export function assetReferences(asset,sessions){
 const links=[];
 const matches=r=>[r.assetId,r.originalAssetId,r.maskAssetId,r.cutoutAssetId].includes(asset.id)||
  !!(asset.serverAssetId&&asset.serverAssetId===r.serverAssetId)||
  !!(asset.src&&[r.src,r.originalSrc,r.maskSrc].includes(asset.src));
 for(const s of sessions){
  for(const r of s.draft?.refs||[])if(matches(r))links.push({sessionId:s.id,refId:r.id,slot:r.catalogSlot,type:'draft',title:s.draft.prompt||s.title});
  for(const j of s.jobs||[])for(const r of j.snapshot?.refs||[])if(matches(r))links.push({sessionId:s.id,jobId:j.id,refId:r.id,slot:r.catalogSlot,type:'job',title:j.snapshot.prompt||s.title,started:j.started});
 }
 return links;
}
