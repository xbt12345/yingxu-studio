const paths={download:'M10 2v11m-4-4 4 4 4-4M3 14v4h14v-4',reference:'M3 3h12v12H3zM3 11l4-4 4 4M11 7h.01M13 17h5m-2-3 3 3-3 3',compare:'M3 3h6v14H3zM11 3h6v14h-6z',trash:'M3 5h14M7 5V2h6v3M5 5l1 13h8l1-13M8 8v7m4-7v7',region:'M3 6V3h3m8 0h3v3m0 8v3h-3M6 17H3v-3M8 7l8 3-4 2-2 4Z',cutout:'M10 3a3 3 0 1 1 0 6 3 3 0 0 1 0-6M5 16v-2a5 5 0 0 1 10 0v2ZM2 7V3h3m10 0h3v4M2 13v5h3m10 0h3v-5',clock:'M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0M10 5v5h4',arrow:'M4 10h12m-5-5 5 5-5 5',down:'m6 8 4 4 4-4',image:'M3 3h14v14H3zM3 13l4-4 4 4 3-3 3 3M12 6h.01',video:'M3 5h10v10H3z m10 3 5-3v10l-5-3',plus:'M10 4v12M4 10h12',expand:'M3 7V3h4m6 0h4v4m0 6v4h-4M7 17H3v-4',settings:'M4 5h12M4 10h12M4 15h12M7 3v4m6 1v4m-5 1v4',history:'M3 5v4h4M3 9a7 7 0 1 1 2 6M10 6v5l3 2',grid:'M3 3h5v5H3zM12 3h5v5h-5zM3 12h5v5H3zM12 12h5v5h-5z',search:'M14 14l4 4M15 9A6 6 0 1 1 3 9a6 6 0 0 1 12 0',play:'m7 4 9 6-9 6Z',pause:'M7 5v10M13 5v10',star:'m10 2 2.5 5 5.5.8-4 3.9.9 5.5-4.9-2.6-4.9 2.6.9-5.5-4-3.9 5.5-.8Z',close:'m5 5 10 10M15 5 5 15',back:'M16 10H4m5-5-5 5 5 5',spark:'m10 2 2.1 5.9L18 10l-5.9 2.1L10 18l-2.1-5.9L2 10l5.9-2.1Z',check:'m4 10 4 4 8-8',audio:'M8 14V4l8-2v10M8 14c0 3-5 4-5 1 0-2 3-3 5-1M16 12c0 3-5 4-5 1 0-2 3-3 5-1',folder:'M2 5h6l2 2h8v10H2ZM2 5V3h6l2 2',assets:'M3 5h14v12H3zM5 2h10M6 12l3-3 5 5',home:'m2 9 8-7 8 7M4 8v10h12V8M8 18v-6h4v6',help:'M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0M7 7a3 3 0 0 1 6 0c0 2-3 2-3 5M10 15h.01',menu:'M3 5h14M3 10h14M3 15h14',wallet:'M3 5h14v12H3zM3 5V3h12v2M13 9h5v4h-5z',bell:'M5 13V8a5 5 0 0 1 10 0v5l2 2H3ZM8 18h4',lock:'M5 9h10v8H5zM7 9V6a3 3 0 0 1 6 0v3',checklist:'M7 5h10M7 10h10M7 15h10M3 5h.01M3 10h.01M3 15h.01'};
const I=n=>`<svg class="icon" viewBox="0 0 20 20" aria-hidden="true"><path d="${paths[n]||paths.spark}"/></svg>`;
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const referencePage='https://www.reply.com/en/newsroom/news/love-at-first-sight-by-jacopo-reale-is-the-winning-short-film-of-the-reply-ai-film-festival-the-international-competition-that-bridges-cinema-and-ai';
const film={src:'assets/award-film-10s.mp4',poster:'assets/award-poster.jpg',title:'Love at First Sight',author:'Jacopo Reale',award:'Reply AI Film Festival 2025 · 一等奖',excerpt:'00:28–00:38'};
const categories=['全部','视频生成','视频编辑','图像生成','图像处理'];
const workflows=[
 {id:'multi-video',name:'多参考视频创作',category:'视频生成',tag:'多素材参考',desc:'组合人物、场景与动作参考，把多份素材组织成一个镜头。',input:'图片 / 视频 / 音频 + 描述',cover:'award-poster.jpg',mode:'multi'},
 {id:'image-video',name:'让静帧动起来',category:'视频生成',tag:'图生视频',desc:'以图片为起点，描述主体动作、画面变化与镜头运动。',input:'参考图片 + 镜头描述',cover:'portal-ocean.png',mode:'image'},
 {id:'first-last',name:'首尾帧过渡',category:'视频生成',tag:'首尾帧',desc:'上传镜头的起点与终点，让两个画面自然连接。',input:'首帧 + 尾帧 + 过渡描述',cover:'coast.jpg',mode:'pair'},
 {id:'video-edit',name:'视频局部编辑',category:'视频编辑',tag:'视频编辑',desc:'保留原始镜头，描述需要替换或修改的画面元素。',input:'原视频 + 图片参考 + 描述',cover:'award-poster.jpg',mode:'multi'},
 {id:'video-background',name:'视频换背景',category:'视频编辑',tag:'场景替换',desc:'保留人物与动作，替换身后的场景。',input:'原视频 + 场景参考 + 描述',cover:'forest.jpg',mode:'multi'},
 {id:'video-character',name:'视频换角色',category:'视频编辑',tag:'人物替换',desc:'保留原片动作与镜头，替换出镜人物。',input:'原视频 + 人物参考 + 描述',cover:'award-poster.jpg',mode:'multi'},
 {id:'video-restyle',name:'视频风格转换',category:'视频编辑',tag:'风格转换',desc:'延续原有的动作与构图，重新设定镜头的视觉语言。',input:'视频 + 风格参考',cover:'mountain.jpg',mode:'multi'},
 {id:'video-upscale',name:'视频清晰度增强',category:'视频编辑',tag:'视频修复',desc:'改善已有素材的清晰度，让细节与纹理更加完整。',input:'视频素材',cover:'coast.jpg',mode:'video'},
 {id:'product',name:'产品场景创作',category:'图像生成',tag:'产品图',desc:'用产品图片与场景描述，探索新的布景与光线。',input:'产品图片 + 场景描述',cover:'portal-ocean.png',mode:'image'},
 {id:'character',name:'角色形象探索',category:'图像生成',tag:'角色创作',desc:'结合多张角色与服饰参考，探索统一的视觉方向。',input:'多张图片 + 角色描述',cover:'award-poster.jpg',mode:'image'},
 {id:'image-edit',name:'图像局部重绘',category:'图像处理',tag:'局部编辑',desc:'延续已有画面，替换局部内容或补充新的细节。',input:'原图 + 修改描述',cover:'dunes.jpg',mode:'image'},
 {id:'image-upscale',name:'图像高清放大',category:'图像处理',tag:'图像超分',desc:'增强原图的纹理与边缘，让画面适合更大的展示尺寸。',input:'图片素材',cover:'forest.jpg',mode:'image'}
];

export {I,esc,film,referencePage,categories,workflows};
