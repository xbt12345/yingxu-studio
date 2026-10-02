// Display capabilities are kept separate from the UI. No API is called in this prototype.
export const models = [
  {id:'seedream-4.5',name:'Seedream 4.5',provider:'ByteDance',type:'image',description:'多图参考 · 图像生成与编辑',qualities:['1K','1.5K','2K'],ratios:['16:9','9:16','1:1','4:3'],refLimit:14,kinds:['image'],factor:1},
  {id:'flux-2-pro',name:'FLUX.2 [pro]',provider:'Black Forest Labs',type:'image',description:'图像生成 · 多参考编辑',qualities:['1K','1.5K','2K'],ratios:['16:9','9:16','1:1','4:3'],refLimit:8,kinds:['image'],factor:1.25},
  {id:'seedance-2.0',name:'Seedance 2.0',provider:'ByteDance',type:'video',description:'4–15 秒 · 图像、视频与音频参考',qualities:['480p','720p','1080p'],ratios:['16:9','9:16','1:1','4:3'],durations:Array.from({length:12},(_,i)=>i+4),refLimit:12,kinds:['image','video','audio'],factor:1},
  {id:'veo-3.1',name:'Veo 3.1',provider:'Google',type:'video',description:'4 / 6 / 8 秒 · 图像参考与首尾帧',qualities:['480p','720p','1080p'],ratios:['16:9','9:16'],durations:[4,6,8],refLimit:3,kinds:['image'],factor:1.5}
];
export const defaultModel=type=>models.find(m=>m.type===type);
export const getModel=d=>models.find(m=>m.id===d.model&&m.type===d.type)||defaultModel(d.type);
export function durationOptions(d){const m=getModel(d);if(m.id==='veo-3.1'&&(d.quality!=='720p'||d.mode==='全能参考'&&d.refs.some(r=>r.kind==='image'&&r.slot===undefined)))return[8];return m.durations||[10];}
export function normalizeDraft(d){const m=getModel(d);d.model=m.id;if(!m.qualities.includes(d.quality))d.quality=m.qualities[0];if(!m.ratios.includes(d.ratio))d.ratio=m.ratios[0];if(d.type==='video'){const opts=durationOptions(d),n=parseInt(d.duration);d.duration=opts.reduce((a,b)=>Math.abs(b-n)<Math.abs(a-n)?b:a,opts[0])+' 秒';}return d;}
