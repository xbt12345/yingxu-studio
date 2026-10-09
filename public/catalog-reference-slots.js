// This is display state only. The reviewed media ports retain their binding IDs.
export function catalogReferenceLayout(cfg,d={}){
 const media=cfg?.media||[],policy=cfg?.referencePolicy;
 if(policy?.presentation!=='progressive')return {progressive:false,visible:media,next:null};
 const images=media.filter(slot=>slot.kind==='image');
 const minimum=Math.min(images.length,Math.max(1,Number(policy.minImages)||1));
 const opened=new Set(d.catalogOpenSlots||[]),bound=new Set((d.refs||[]).map(ref=>ref.catalogSlot));
 const first=new Set(images.slice(0,minimum).map(slot=>slot.id));
 const visible=media.filter(slot=>slot.kind!=='image'||first.has(slot.id)||opened.has(slot.id)||bound.has(slot.id));
 const shown=new Set(visible.map(slot=>slot.id));
 return {progressive:true,visible,next:images.find(slot=>!shown.has(slot.id))||null,minimum,maximum:images.length,
  boundCount:images.filter(slot=>bound.has(slot.id)).length};
}

export function openCatalogReferenceSlot(cfg,d){
 const layout=catalogReferenceLayout(cfg,d);
 if(!layout.progressive||!layout.next)return null;
 const known=new Set((cfg.media||[]).map(slot=>slot.id));
 d.catalogOpenSlots=[...new Set([...(d.catalogOpenSlots||[]).filter(id=>known.has(id)),layout.next.id])];
 return layout.next.id;
}

export function closeCatalogReferenceSlot(d,id){
 d.catalogOpenSlots=(d.catalogOpenSlots||[]).filter(slotId=>slotId!==id);
}

export function compactCatalogReferenceSlots(cfg,d,removedSlot){
 const layout=catalogReferenceLayout(cfg,d);if(!layout.progressive)return;
 const images=(cfg.media||[]).filter(slot=>slot.kind==='image');
 const ordered=images.map(slot=>(d.refs||[]).find(ref=>ref.catalogSlot===slot.id&&ref.kind==='image')).filter(Boolean);
 const occupied=new Set(ordered.map(ref=>ref.catalogSlot));
 const emptyCount=layout.visible.filter(slot=>slot.kind==='image'&&slot.id!==removedSlot&&!occupied.has(slot.id)).length;
 ordered.forEach((ref,index)=>{ref.catalogSlot=images[index].id;});
 const initial=Math.max(layout.minimum,ordered.length);
 d.catalogOpenSlots=images.slice(initial,initial+emptyCount).map(slot=>slot.id);
}
