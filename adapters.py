"""Bindings to the two exported, user-owned ComfyUI graphs. No external LLM calls."""
import copy
import json
import math
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def field(key, label, default, minimum=None, maximum=None, step=1, options=None, hidden=False):
    return dict(key=key, label=label, default=default, min=minimum, max=maximum, step=step, options=options, hidden=hidden)

WORKFLOWS = [
    dict(id='h3-reference', name='H3 多参考图生视频', category='video-gen', mode='multi',
         desc='用文字与最多 9 张参考图生成带声音的视频。按上传顺序在描述中使用“图片1、图片2”。',
         cover='assets/coast.jpg', negative=False, minImages=0, maxImages=9, minVideos=0, maxVideos=0,
         placeholder='描述场景、人物动作与镜头；例如：图片1中的海岸，镜头缓慢向前，海浪拍打礁石。',
         fields=[field('duration','视频时长（秒）',15,5,15), field('ratio','画幅','9:16',options=['21:9','16:9','4:3','1:1','3:4','9:16']),
                 field('megapixels','清晰度',0.5,0.2,1,0.1),
                 field('steps','生成精度',8,options=[4,8]),
                 field('ref_size','参考图细节','max',options=['match','max']),
                 field('shift_video','视频采样偏移',12,1,20,0.5,hidden=True),
                 field('shift_audio','声音采样偏移',3,1,10,0.5,hidden=True),
                 field('seed','随机种子',-1,-1,9007199254740991)],
         source='minimax-重生八零提示词优化版-分集001-片段018_a273f7ba.json'),
    dict(id='bernini-edit', name='Bernini 视频编辑', category='video-edit', mode='multi',
         desc='上传 1 段视频，描述要修改的内容；可加入最多 8 张参考图。保留原片声音，使用原工作流的标准采样分支。',
         cover='assets/portal-ocean.png', negative=True, minImages=0, maxImages=8, minVideos=1, maxVideos=1,
         placeholder='描述要改什么、保留什么；例如：将天空改为日落暖色，保留海浪运动与原有镜头。',
         fields=[field('duration','处理前几秒',13,1,15),field('long_side','清晰度',1024,options=[384,512,768,1024]),
                 field('steps','生成精度',40,12,60,2),field('cfg','描述遵循程度',5,1,10,0.5),
                 field('fps','输出帧率',16,options=[8,16,24],hidden=True),
                 field('seed','随机种子',-1,-1,9007199254740991)],
         source='0629官方wan2.2bernini视频编辑.json')
]

def manifest(workflow_id):
    return next((w for w in WORKFLOWS if w['id']==workflow_id), None)

def settings_for(w, supplied):
    if set(supplied)-{f['key'] for f in w['fields']}:
        raise ValueError('含有不属于此工作流的参数，请刷新后重试。')
    result={}
    for f in w['fields']:
        v=supplied.get(f['key'],f['default'])
        if f['options']:
            if v not in f['options']:raise ValueError(f"{f['label']}不在支持范围内。")
        else:
            if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not f['min']<=v<=f['max']:
                raise ValueError(f"{f['label']}必须在 {f['min']}–{f['max']} 之间。")
            if abs((v-f['min'])/f['step']-round((v-f['min'])/f['step']))>1e-6:
                raise ValueError(f"{f['label']}的步长为 {f['step']}。")
        result[f['key']]=v
    if result['seed']==-1:result['seed']=secrets.randbelow(2**48)
    return result

def prune(g, outputs):
    used=set()
    def visit(k):
        if k in used:return
        used.add(k)
        for v in g[k]['inputs'].values():
            if isinstance(v,list) and len(v)==2 and isinstance(v[0],str) and v[0] in g:visit(v[0])
    for k in outputs:visit(k)
    return {k:v for k,v in g.items() if k in used}

def build_graph(workflow_id,prompt,negative,settings,assets,job_id):
    g=json.loads((ROOT/'private'/f'{workflow_id}.api.json').read_text('utf-8'))
    def put(k,**values):g[k]['inputs'].update(values)
    images=[a for a in assets if a['kind']=='image'];videos=[a for a in assets if a['kind']=='video']
    if workflow_id=='h3-reference':
        s=settings
        put('72',value=prompt)
        put('71',aspect_ratio={'16:9':'16:9 (Widescreen)','9:16':'9:16 (Portrait Widescreen)','1:1':'1:1 (Square)','21:9':'21:9 (Ultrawide)','4:3':'4:3 (Standard)','3:4':'3:4 (Portrait Standard)'}[s['ratio']],megapixels=s['megapixels'])
        put('69',value=s['duration'])
        model='40' if s['steps']==8 else '41'
        put('47',steps=s['steps'],model=[model,0],shift_video=s['shift_video'],shift_audio=s['shift_audio'])
        put('49',model=[model,0])
        put('149',shift_video=s['shift_video'],shift_audio=s['shift_audio'])
        put('55',noise_seed=s['seed'])
        g['144']['inputs']={k:v for k,v in g['144']['inputs'].items() if not k.startswith('ref_')}
        put('144',ref_image_size=s['ref_size'])
        for ix,a in enumerate(images):
            key=f'upload_{ix}';g[key]={'class_type':'LoadImage','inputs':{'image':a['remote']}}
            g['144']['inputs'][f'ref_images.ref_image_{ix}']=[key,0]
        put('54',filename_prefix=f'yingxu/{job_id}',format='mp4',**{'format.codec':'h264'})
        return prune(g,['54'])
    s=settings
    # The source explicitly contains standard and LoRA-accelerated branches.
    # Select its standard branch: this card has no high-noise acceleration LoRA.
    put('384',model=['436',0],noise_seed=s['seed'],cfg=s['cfg'])
    put('386',model=['440',0],noise_seed=s['seed'],cfg=s['cfg'])
    put('385',steps=s['steps']);put('379',step=s['steps']//2)
    put('378',text=negative)
    prefix='You are a helpful assistant specialized in video editing'+(' with reference.' if images else '.')
    put('388',text=prefix+'\n'+prompt)
    put('425',video=videos[0]['remote'],force_rate=s['fps'],frame_load_cap=int(s['duration']*s['fps'])+1,format='Wan')
    put('434',scale_to_length=s['long_side'])
    g['387']['inputs']={k:v for k,v in g['387']['inputs'].items() if not k.startswith('reference_images.')}
    put('387',ref_max_size=s['long_side'])
    for ix,a in enumerate(images):
        key=f'upload_{ix}';g[key]={'class_type':'LoadImage','inputs':{'image':a['remote']}}
        g['387']['inputs'][f'reference_images.reference_image_{ix}']=[key,0]
    put('443',filename_prefix=f'yingxu/{job_id}',crf=19,save_metadata=False)
    return prune(g,['443'])
