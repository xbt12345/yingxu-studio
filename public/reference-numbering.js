const prefixes={image:'图片',video:'视频',audio:'音频'};
export const hasRemovedReference=text=>/\[已移除(?:图片|视频|音频)\d+\]/.test(text||'');

export function nextReferenceId(draft,kind){
 const prefix=prefixes[kind];if(!prefix)throw new Error('未知素材类型');
 const used=(draft.refs||[]).filter(r=>r.kind===kind).map(r=>Number(String(r.id).slice(prefix.length))).filter(Number.isSafeInteger);
 return prefix+(Math.max(0,...used)+1);
}

// IDs belong to one creation draft. Keep historical job snapshots untouched.
export function renumberDraftReferences(draft,{removedIds=[],slotOrder=[]}={}){
 const counts={image:0,video:0,audio:0},mapping=new Map();
 if(draft.mode==='首尾帧')draft.refs.sort((a,b)=>(a.slot??99)-(b.slot??99));
 if(slotOrder.length){const order=new Map(slotOrder.map((id,i)=>[id,i]));draft.refs.sort((a,b)=>(order.get(a.catalogSlot)??999)-(order.get(b.catalogSlot)??999));}
 for(const ref of draft.refs||[]){
  const next=prefixes[ref.kind]+(++counts[ref.kind]);
  mapping.set('@'+ref.id,'@'+next);ref.id=next;
 }
 const removed=new Set(removedIds.map(id=>'@'+id));
 const rewrite=value=>typeof value==='string'?value.replace(/@(图片|视频|音频)\d+/g,token=>removed.has(token)?`[已移除${token.slice(1)}]`:mapping.get(token)||token):value;
 draft.prompt=rewrite(draft.prompt);
 draft.negative=rewrite(draft.negative);
 if(draft.catalogTexts)for(const id of Object.keys(draft.catalogTexts))draft.catalogTexts[id]=rewrite(draft.catalogTexts[id]);
 return draft;
}
