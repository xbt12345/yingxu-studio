// Server hashes and request tokens identify an attempt; prompts/seeds do not.
export const remoteJobIdentity=job=>job?.remoteId||String(job?.id||'').match(/^live-([a-f0-9]{32})$/)?.[1]||'';
export const sameLiveJob=(a,b)=>a.id===b.id||!!(remoteJobIdentity(a)&&remoteJobIdentity(a)===remoteJobIdentity(b))||!!(a.token&&a.token===b.token);
export const matchesLiveRecord=(job,record)=>remoteJobIdentity(job)===record.id||!!(job.token&&job.token===record.request_token);

export function referenceProvenance(record){
 const original=record.original_asset_id||record.originalServerAssetId;
 return {...(original?{originalServerAssetId:original}:{}),...(record.original_src||record.originalSrc?{originalSrc:record.original_src||record.originalSrc}:{}),...(record.original_available!==undefined?{originalAvailable:record.original_available}:{}),...(record.annotation_mode||record.annotationMode?{annotationMode:record.annotation_mode||record.annotationMode}:{})};
}
const assetIdentity=ref=>ref?.serverAssetId||String(ref?.src||'').match(/^\/api\/assets\/([a-f0-9]{64})\/file(?:\?.*)?$/)?.[1]||'';
const richReference=ref=>!!(ref?.originalAssetId||ref?.originalServerAssetId||ref?.referenceEdits||ref?.annotationStrokes?.length||ref?.maskAssetId);
const genericUploadName=name=>typeof name==='string'&&/^reference-[1-9]\d*\.(?:png|jpe?g|webp|gif|mp4|webm|mov|wav|mp3|flac|ogg|m4a)$/i.test(name.trim());
const localDisplayName=name=>typeof name==='string'&&name.trim()&&!genericUploadName(name);

// References are immutable inputs of the same proven attempt. Server status
// refreshes update availability/URLs without discarding local original/mask IDs.
export function mergeReferenceSnapshots(existing=[],incoming=[],assets=[]){
 return incoming.map((ref,index)=>{
  const incomingAsset=assetIdentity(ref);
  let old=existing.find(candidate=>incomingAsset&&assetIdentity(candidate)===incomingAsset);
  if(!old&&ref.catalogSlot)old=existing.find(candidate=>candidate.catalogSlot===ref.catalogSlot&&(!assetIdentity(candidate)||!incomingAsset||assetIdentity(candidate)===incomingAsset));
  if(!old){const candidate=existing[index];if(candidate?.kind===ref.kind&&(!assetIdentity(candidate)||!incomingAsset||assetIdentity(candidate)===incomingAsset)&&(!candidate.catalogSlot||!ref.catalogSlot||candidate.catalogSlot===ref.catalogSlot))old=candidate;}
  const merged={...old,...ref};
  const identified=old&&((incomingAsset&&assetIdentity(old)===incomingAsset)||(ref.catalogSlot&&old.catalogSlot===ref.catalogSlot));
  if(identified&&genericUploadName(ref.name)){
   const localName=localDisplayName(old.name)?old.name:assets.find(asset=>asset.id===old.assetId&&localDisplayName(asset.name))?.name;
   if(localName)merged.name=localName;
  }
  // Missing fields in a server projection are absence of knowledge, not deletion.
  if(old)for(const key of ['originalAssetId','originalServerAssetId','originalSrc','originalAvailable','maskAssetId','maskSrc','maskEncoding','annotationMode','annotationStrokes','referenceEdits','cutoutAssetId','referenceStrength'])if(ref[key]===undefined&&old[key]!==undefined)merged[key]=old[key];
  return merged;
 });
}

const terminal=new Set(['done','failed','cancelled','abandoned']);
function combineEquivalentJobs(preferred,other){
 const authoritative=terminal.has(other.status)&&(!terminal.has(preferred.status)||Number(other.ended||0)>Number(preferred.ended||0))?other:preferred;
 const outputs=new Map();for(const output of [...(preferred.outputs||[]),...(other.outputs||[])]){const old=outputs.get(output.id);outputs.set(output.id,old?{...output,...old,...(output.removedAt&&(!old.removedAt||output.removedAt>old.removedAt)?{removedAt:output.removedAt}:{})}:output);}
 const chosen=preferred.snapshot||{},alternative=other.snapshot||{},chosenRefs=chosen.refs||[],alternativeRefs=alternative.refs||[];
 const refs=chosenRefs.length?mergeReferenceSnapshots(alternativeRefs,chosenRefs):alternativeRefs;
 const mergedSnapshot={...alternative,...chosen,refs};
 if(authoritative===other){
  for(const key of ['type','mode','workflowId','prompt','negative','ratio','quality','duration','catalogLive','catalogGeneric'])if(alternative[key]!==undefined)mergedSnapshot[key]=alternative[key];
  for(const key of ['catalogValues','catalogTexts','catalogAssets','liveSettings'])if(alternative[key])mergedSnapshot[key]={...(chosen[key]||{}),...alternative[key]};
 }
 // A bare server import must not erase proven local original identities.
 if(alternativeRefs.some(richReference)&&!chosenRefs.some(richReference))mergedSnapshot.refs=mergeReferenceSnapshots(chosenRefs,alternativeRefs);
 Object.assign(preferred,{...other,...preferred,remoteId:remoteJobIdentity(preferred)||remoteJobIdentity(other),token:preferred.token||other.token,snapshot:mergedSnapshot,outputs:[...outputs.values()]});
 for(const key of ['status','serverStatus','stage','started','ended','error','connection_error','cancelError','cancelPersisted','promptId','progress']){if(authoritative[key]!==undefined)preferred[key]=authoritative[key];else delete preferred[key];}
}

// Coalesce only equivalent attempts, retaining the optimistic row and its input
// identities. This also repairs previously persisted live-<server id> ghosts.
export function reconcileLiveJobs(sessions){
 let changed=false;const groups=[];
 for(const session of sessions)for(const job of session.jobs||[]){
  if(!job.real)continue;
  const matches=groups.filter(group=>group.some(entry=>sameLiveJob(entry.job,job)));
  if(matches.length){const group=matches[0];group.push({session,job});for(const other of matches.slice(1)){group.push(...other);groups.splice(groups.indexOf(other),1);}}else groups.push([{session,job}]);
 }
 for(const group of groups){if(group.length<2)continue;
  const score=job=>(/^live-[a-f0-9]{32}$/.test(job.id)?0:4)+(job.snapshot?.refs?.some(richReference)?2:0);
  const winner=group.reduce((best,item)=>score(item.job)>score(best.job)?item:best);
  for(const item of group)if(item!==winner){combineEquivalentJobs(winner.job,item.job);item.session.jobs=item.session.jobs.filter(job=>job!==item.job);changed=true;}
 }
 return changed;
}
