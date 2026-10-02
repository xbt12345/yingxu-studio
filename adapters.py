"""Bindings to the two exported, user-owned ComfyUI graphs. No external LLM calls."""
import copy
import json
import math
import re
import secrets
from pathlib import Path
from configuration import workflow_path

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
         fields=[field('duration','片段时长',13,1,15,0.01),field('trim_start','片段起点（秒）',0,0,3600,0.01),field('long_side','清晰度',1024,options=[384,512,768,1024]),
                 field('steps','生成精度',40,12,60,2),field('cfg','描述遵循程度',5,1,10,0.5),
                 field('fps','输出帧率',16,options=[8,16,24],hidden=True),
                 field('seed','随机种子',-1,-1,9007199254740991)],
         source='0629官方wan2.2bernini视频编辑.json')
]

# Promote catalog entries one at a time only after the exact platform graph has
# compiled and produced an output. Keep the original card name and source hash.
CATALOG_WORKFLOWS = [
    dict(id='local-card-11', name='0221flux-2-klein9b-单-多图编辑对比aio', category='catalog-image', output='image',
         source='Flux.2 Klein/0221flux-2-klein9b-单-多图编辑对比aio.json',
         source_hash='7187415a3c6356f0e08fef5d4fad85711a8b8924fe1f24b3fcc29b82c2323a82',
         negative=True, minImages=2, maxImages=2, minVideos=0, maxVideos=0),
    dict(id='local-card-15', name='0221klein-9b局部重绘流', category='catalog-image', output='image',
         source='Flux.2 Klein/0221klein-9b局部重绘流.json',
         source_hash='1fcd6f4702e3bfd443f125453ba9ac00a8ad8bd19cefda5b524e795bd74b24ea',
         negative=False, minImages=1, maxImages=1, minVideos=0, maxVideos=0),
    dict(id='local-card-16', name='0221klein9b-图像标记替换流', category='catalog-image', output='image',
         source='Flux.2 Klein/0221klein9b-图像标记替换流.json',
         source_hash='488bc1847380fc0fdda205de3e42b0c51286d5075c526ed5db471ef205b71947',
         negative=False, minImages=2, maxImages=2, minVideos=0, maxVideos=0),
    dict(id='local-card-17', name='基础-Flux.2 Klein 4B 蒸馏加速 图生图', category='catalog-image', output='image',
         source='Flux.2 Klein/基础-Flux.2 Klein 4B 蒸馏加速 图生图.json',
         source_hash='6525111eec21bdb4d034bfba9ff4abcc5c5accf70a1fcdffe6808bad5ffb4337',
         negative=False, minImages=2, maxImages=2, minVideos=0, maxVideos=0),
    dict(id='local-card-18', name='基础-Flux.2 Klein 4b图生图', category='catalog-image', output='image',
         source='Flux.2 Klein/基础-Flux.2 Klein 4b图生图.json',
         source_hash='cb11a2ca057fa2ef65ca4b0b413d589a8f7cd10717d14a138eb13fa0570f50b1',
         negative=True, minImages=2, maxImages=2, minVideos=0, maxVideos=0),
    dict(id='local-card-20', name='基础-Flux.2 Klein 9B 蒸馏加速 图生图', category='catalog-image', output='image',
         source='Flux.2 Klein/基础-Flux.2 Klein 9B 蒸馏加速 图生图.json',
         source_hash='e4083d6210f4e70554db86f8f03f5389c74d85b33f4312818d4ba3c501ab31fb',
         negative=False, minImages=1, maxImages=1, minVideos=0, maxVideos=0),
    dict(id='local-card-85', name='0427Anima文生图', category='catalog-image', output='image',
         source='动漫系列生图/0427Anima文生图.json',
         source_hash='dd292b96f8e6f02fab2ccdb63b9e29b5e95976fbd26b71a8415fc139da571ef1',
         negative=True, minImages=0, maxImages=0, minVideos=0, maxVideos=0),
    dict(id='local-card-1', name='0921qwenimage2.1图像生成', category='catalog-image', output='image',
         source='0921qwenimage2.1图像生成.json',
         source_hash='fbac8d2ce1b8a6e693df3b09b73581f298fd0ea83a19d7e45a71b23fb0bd1b78',
         negative=True, minImages=0, maxImages=0, minVideos=0, maxVideos=0),
    dict(id='local-card-2', name='0921qwenimage2.1图像编辑', category='catalog-image', output='image',
         source='0921qwenimage2.1图像编辑.json',
         source_hash='815d61d4572bc26b5b48887b81898a320b0b9ef59bceb92f7872914a27ebf7b4',
         negative=True, minImages=2, maxImages=2, minVideos=0, maxVideos=0),
    dict(id='local-card-3', name='0923qwenimage2.1服装衣服穿衣工作流', category='catalog-image', output='image',
         source='0923qwenimage2.1服装衣服穿衣工作流.json',
         source_hash='de7a0f266cbe0ad9a55b11ab2773432ae3c89c06287b6a445c3bad4d57d72cbe',
         negative=True, minImages=2, maxImages=2, minVideos=0, maxVideos=0),
    dict(id='local-card-9', name='0221flux-2-klein-9b-文生图base', category='catalog-image', output='image',
         source='Flux.2 Klein/0221flux-2-klein-9b-文生图base.json',
         source_hash='8339e1d3615812835f52933c4b7ce69fbd6c775e3a470544e6d65364e07ee3a2',
         negative=True, minImages=0, maxImages=0, minVideos=0, maxVideos=0),
    dict(id='local-card-10', name='0221flux-2-klein-9b-文生图标准流', category='catalog-image', output='image',
         source='Flux.2 Klein/0221flux-2-klein-9b-文生图标准流.json',
         source_hash='3f9a342cb1e531341c814e8d2957a204478c4a9d5e59dba4b853e39c9b630aa3',
         negative=False, minImages=0, maxImages=0, minVideos=0, maxVideos=0),
    dict(id='local-card-12', name='0221klein-9b-动漫转真人多模型对比', category='catalog-image', output='image',
         source='Flux.2 Klein/0221klein-9b-动漫转真人多模型对比.json',
         source_hash='f92ee25a601ac4c605a55a7fbf1d4d94a07171b2435aedf58a83d315004cadbe',
         negative=False, minImages=1, maxImages=1, minVideos=0, maxVideos=0),
    dict(id='local-card-13', name='0221klein-9b图像扩展流', category='catalog-image', output='image',
         source='Flux.2 Klein/0221klein-9b图像扩展流.json',
         source_hash='c5162db5193c1dff4f51dfaf16bbf1ba22c93b92352909ebe56260d4cd9664a7',
         negative=False, minImages=1, maxImages=1, minVideos=0, maxVideos=0),
    dict(id='local-card-14', name='0221klein-9b多角度转换流', category='catalog-image', output='image',
         source='Flux.2 Klein/0221klein-9b多角度转换流.json',
         source_hash='2734f9df96bc0dd7ba8157e2acb935033db8a9c39d873d79c094272f72ee86f5',
         negative=False, minImages=1, maxImages=1, minVideos=0, maxVideos=0),
    dict(id='local-card-19', name='基础-Flux.2 Klein 4b文生图', category='catalog-image', output='image',
         source='Flux.2 Klein/基础-Flux.2 Klein 4b文生图.json',
         source_hash='4fa997540b221c326a4cc9654fe50e2f1db81811db845f2cd086c879d70da64c',
         negative=True, minImages=0, maxImages=0, minVideos=0, maxVideos=0),
    dict(id='local-card-21', name='基础Flux.2 Klein 9B 蒸馏加速 文生图', category='catalog-image', output='image',
         source='Flux.2 Klein/基础Flux.2 Klein 9B 蒸馏加速 文生图.json',
         source_hash='0d0f6179a85560ba6bf70fbd919656822538818827656caf68edae65817ab3fb',
         negative=False, minImages=0, maxImages=0, minVideos=0, maxVideos=0),
    dict(id='local-card-78', name='Qwen-Edit-2511-多角度切换', category='catalog-image', output='image',
         source='qwen功能性工作流/Qwen-Edit-2511-多角度切换.json',
         source_hash='bd512fb31963713cf5889c1955686cc1876d50df245990ad8fac883e619ce039',
         negative=True, minImages=1, maxImages=1, minVideos=0, maxVideos=0),
    dict(id='local-card-82', name='0111qwen2511动漫转真人', category='catalog-image', output='image',
         source='动漫和真人转换/0111qwen2511动漫转真人.json',
         source_hash='9e36f21f798e2a6d437c28118ef69323b48eadca7c152e22d6b549bb7f7fb1cd',
         negative=True, minImages=1, maxImages=1, minVideos=0, maxVideos=0),
    dict(id='local-card-83', name='0907krea2动漫转真人', category='catalog-image', output='image',
         source='动漫和真人转换/0907krea2动漫转真人.json',
         source_hash='88af59b77e0db30315ed1aa41a347630d19681782f8c895ff0a95c097df8128d',
         negative=False, minImages=1, maxImages=1, minVideos=0, maxVideos=0),
    dict(id='local-card-84', name='0923qwenimage2.1动漫转真人', category='catalog-image', output='image',
         source='动漫和真人转换/0923qwenimage2.1动漫转真人.json',
         source_hash='70cd011f73d8d258352a0016c26d0aae4425d1ac922de94d55b17e74b8db8976',
         negative=True, minImages=1, maxImages=1, minVideos=0, maxVideos=0),
    dict(id='local-card-104', name='0531z_image文生图全量版本', category='catalog-image', output='image',
         source='文生图/0531z_image文生图全量版本.json',
         source_hash='37c0484ccf564d9e5769c2aadbef0cec6ebcde95b38ed69df12fa9d66507cd74',
         negative=True, minImages=0, maxImages=0, minVideos=0, maxVideos=0),
    dict(id='local-card-105', name='0608image_ideogram4_t2i -破', category='catalog-image', output='image',
         source='文生图/0608image_ideogram4_t2i -破.json',
         source_hash='f0ea70c0c25837b9c2fe5e79604bb0ed5dca9896c824f3db083231690c9d9eeb',
         negative=False, minImages=0, maxImages=0, minVideos=0, maxVideos=0),
    dict(id='local-card-106', name='0608image_ideogram4_t2i ', category='catalog-image', output='image',
         source='文生图/0608image_ideogram4_t2i .json',
         source_hash='77992d83327c2bf1bb68d1f33a4632a937f171b5b6a066409cc7ba229bb832f2',
         negative=False, minImages=0, maxImages=0, minVideos=0, maxVideos=0),
    dict(id='local-card-107', name='qwen2512文生图8步', category='catalog-image', output='image',
         source='文生图/qwen2512文生图8步.json',
         source_hash='396a12617c7e9e3fafc8aba2dee7fadb5f9f2d3fc8cdc20498b1ebfaa8ea67b2',
         negative=True, minImages=0, maxImages=0, minVideos=0, maxVideos=0),
    dict(id='local-card-108', name='文生图_krea2_turbo_t2i', category='catalog-image', output='image',
         source='文生图/文生图_krea2_turbo_t2i.json',
         source_hash='7160984252903e474a53f61e9effa339223cd0bae6dc9400fd5e63405def9de1',
         negative=False, minImages=0, maxImages=0, minVideos=0, maxVideos=0),
    dict(id='local-card-109', name='0531_z_image_turbo文生图', category='catalog-image', output='image',
         source='文生图/0531_z_image_turbo文生图.json',
         source_hash='28d3c6cd298a1f5d348807ac1caf72c9b92057bec8179bcc400c1a881a7ff6bc',
         negative=True, minImages=0, maxImages=0, minVideos=0, maxVideos=0),
    dict(id='local-card-110', name='krea2_sq大师v2文生图', category='catalog-image', output='image',
         source='文生图/krea2_sq大师v2文生图.json',
         source_hash='69cf3e255fe0527a4b4e1376f1719d8424deabfa93495e2f7b52f673cda19728',
         negative=True, minImages=0, maxImages=0, minVideos=0, maxVideos=0),
    dict(id='local-card-128', name='0531_z_image_turbo', category='catalog-image', output='image',
         source='z-image/0531_z_image_turbo.json',
         source_hash='090f7382dcc16a1e83fdf5a79d98b82047b878afb33585a713b503792aa3bf2e',
         negative=True, minImages=0, maxImages=0, minVideos=0, maxVideos=0),
    dict(id='local-card-129', name='0531z_image全量版本', category='catalog-image', output='image',
         source='z-image/0531z_image全量版本.json',
         source_hash='9c180931c17ca7d0fadc0f15bdac5c7e1df4bbfa0d1773a9aab1f2aa5a1b7c89',
         negative=True, minImages=0, maxImages=0, minVideos=0, maxVideos=0),
    dict(id='local-card-130', name='1215Red-Z-Image+Detail去网红感真实文生图', category='catalog-image', output='image',
         source='z-image/1215Red-Z-Image+Detail去网红感真实文生图.json',
         source_hash='9496874c21af745f76cf41b7c8184558b90bb7c44b6a1b4fd97389fc77ec36a9',
         negative=False, minImages=0, maxImages=0, minVideos=0, maxVideos=0),
    dict(id='local-card-134', name='图像调色', category='catalog-image', output='image',
         source='实用工具/图像调色.json',
         source_hash='1f4f35340bab02e20910677ec2c176089eb3a07c67e5c398828ed4477ec27afe',
         negative=False, minImages=2, maxImages=2, minVideos=0, maxVideos=0),
]

def manifest(workflow_id):
    return next((w for w in WORKFLOWS+CATALOG_WORKFLOWS if w['id']==workflow_id), None)

def _validate_custom_size(value):
    if not isinstance(value,str) or not re.fullmatch(r'[0-9]{3,4}x[0-9]{3,4}',value):
        raise ValueError('画面尺寸请填写宽×高，例如 1024x1024。')
    width,height=map(int,value.split('x'))
    if not all(512<=side<=2048 and side%8==0 for side in (width,height)):
        raise ValueError('宽和高需在 512–2048 像素之间，且为 8 的倍数。')
    return value

def settings_for(w, supplied):
    if w['id'] in ('local-card-11','local-card-15','local-card-16','local-card-17','local-card-18','local-card-20'):
        allowed={'seed'}
        if w['id']=='local-card-11':allowed.add('resolution')
        if w['id']=='local-card-15':allowed.add('strength')
        if set(supplied)-allowed:raise ValueError('含有不属于此工作流的参数，请刷新后重试。')
        seed=supplied.get('seed',-1)
        if isinstance(seed,bool) or not isinstance(seed,int) or not -1<=seed<=9007199254740991:
            raise ValueError('图像生成种子需要填写有效整数。')
        result={'seed':secrets.randbelow(2**48) if seed==-1 else seed}
        if 'resolution' in allowed:
            resolution=supplied.get('resolution','1344x768')
            if resolution not in ('1024x1024','1152x896','896x1152','1216x832','832x1216','1344x768','768x1344','1536x640','640x1536'):
                raise ValueError('请选择原工作流支持的画面尺寸。')
            result['resolution']=resolution
        if 'strength' in allowed:
            value=supplied.get('strength',0.4)
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<=10 or abs(value*100-round(value*100))>1e-6:
                raise ValueError('调色强度应在 0–10 之间，按 0.01 调整。')
            result['strength']=value
        return result
    if w['id']=='local-card-134':
        if set(supplied)-{'strength'}:raise ValueError('含有不属于此工作流的参数，请刷新后重试。')
        strength=supplied.get('strength',0.5)
        if isinstance(strength,bool) or not isinstance(strength,(int,float)) or not math.isfinite(strength) or not 0<=strength<=10 or abs(strength*10-round(strength*10))>1e-6:
            raise ValueError('调色强度应在 0–10 之间，按 0.1 调整。')
        return {'strength':strength}
    if w['id']=='local-card-13':
        allowed={'seed','left','top','right','bottom','strength','output_long_side'}
        if set(supplied)-allowed:raise ValueError('含有不属于此工作流的参数，请刷新后重试。')
        seed=supplied.get('seed',-1)
        if isinstance(seed,bool) or not isinstance(seed,int) or not -1<=seed<=9007199254740991:
            raise ValueError('图像生成种子需要填写有效整数。')
        padding={}
        for key,default in [('left',504),('top',0),('right',504),('bottom',0)]:
            value=supplied.get(key,default)
            if isinstance(value,bool) or not isinstance(value,int) or not 0<=value<=16384 or value%8:
                raise ValueError('扩展范围需填写 0–16384 的 8 像素倍数。')
            padding[key]=value
        strength=supplied.get('strength',0.4)
        if isinstance(strength,bool) or not isinstance(strength,(int,float)) or not math.isfinite(strength) or not 0<=strength<=10 or abs(strength*10-round(strength*10))>1e-6:
            raise ValueError('调色强度应在 0–10 之间，按 0.1 调整。')
        side=supplied.get('output_long_side',1324)
        if isinstance(side,bool) or not isinstance(side,int) or not 256<=side<=4096:
            raise ValueError('输出最长边需在 256–4096 像素之间。')
        return {'seed':secrets.randbelow(2**48) if seed==-1 else seed,**padding,'strength':strength,'output_long_side':side}
    if w['id']=='local-card-108':
        if set(supplied)-{'seed','prompt_seed','aspect_ratio','megapixels','lora_enabled','prompt_optimize','model_strength'}:
            raise ValueError('含有不属于此工作流的参数，请刷新后重试。')
        seed=supplied.get('seed',-1);prompt_seed=supplied.get('prompt_seed',-1)
        for label,value in [('图像种子',seed),('提示词种子',prompt_seed)]:
            if isinstance(value,bool) or not isinstance(value,int) or not -1<=value<=9007199254740991:
                raise ValueError(f'{label}需要填写有效整数。')
        if prompt_seed>4294967295:raise ValueError('提示词种子需在 0–4294967295 之间。')
        ratios=('16:9 (Widescreen)','1:1 (Square)','21:9 (Ultrawide)','3:4 (Portrait Standard)','4:3 (Standard)','9:16 (Portrait Widescreen)','2:3 (Portrait Photo)','3:2 (Photo)')
        ratio=supplied.get('aspect_ratio','1:1 (Square)')
        if ratio not in ratios:raise ValueError('画面比例不在源节点支持范围内。')
        mp=supplied.get('megapixels',1)
        if isinstance(mp,bool) or not isinstance(mp,(int,float)) or not math.isfinite(mp) or not 0.1<=mp<=16 or abs(mp*10-round(mp*10))>1e-6:
            raise ValueError('百万像素需在 0.1–16 MP 之间，按 0.1 调整。')
        lora_enabled=supplied.get('lora_enabled',False);prompt_optimize=supplied.get('prompt_optimize',True)
        if not isinstance(lora_enabled,bool) or not isinstance(prompt_optimize,bool):raise ValueError('功能开关需要选择开启或关闭。')
        strength=supplied.get('model_strength',0.8)
        if isinstance(strength,bool) or not isinstance(strength,(int,float)) or not math.isfinite(strength) or not 0<=strength<=2 or abs(strength*20-round(strength*20))>1e-6:
            raise ValueError('LoRA 模型强度需在 0–2 之间，按 0.05 调整。')
        return {'seed':secrets.randbelow(2**48) if seed==-1 else seed,'prompt_seed':secrets.randbelow(2**32) if prompt_seed==-1 else prompt_seed,'aspect_ratio':ratio,'megapixels':mp,'lora_enabled':lora_enabled,'prompt_optimize':prompt_optimize,'model_strength':strength}
    if w['id']=='local-card-110':
        if set(supplied)-{'seed','size'}:
            raise ValueError('含有不属于此工作流的参数，请刷新后重试。')
        seed=supplied.get('seed',-1)
        if isinstance(seed,bool) or not isinstance(seed,int) or not -1<=seed<=9007199254740991:
            raise ValueError('图像生成种子需要填写有效整数。')
        size=supplied.get('size','800x1200')
        size=_validate_custom_size(size)
        return {'seed':secrets.randbelow(2**48) if seed==-1 else seed,'size':size}
    if w['id']=='local-card-130':
        if set(supplied)-{'seed','size','lora_strength'}:
            raise ValueError('含有不属于此工作流的参数，请刷新后重试。')
        seed=supplied.get('seed',-1)
        if isinstance(seed,bool) or not isinstance(seed,int) or not -1<=seed<=9007199254740991:
            raise ValueError('图像生成种子需要填写有效整数。')
        size=supplied.get('size','1080x1920')
        size=_validate_custom_size(size)
        strength=supplied.get('lora_strength',-0.2)
        if isinstance(strength,bool) or not isinstance(strength,(int,float)) or not math.isfinite(strength) or not -1<=strength<=1 or abs(strength*20-round(strength*20))>1e-6:
            raise ValueError('风格强度需在 -1 到 1 之间，每次调整 0.05。')
        return {'seed':secrets.randbelow(2**48) if seed==-1 else seed,'size':size,'lora_strength':strength}
    if w['id']=='local-card-107':
        if set(supplied)-{'seed','size','output_size'}:
            raise ValueError('含有不属于此工作流的参数，请刷新后重试。')
        seed=supplied.get('seed',-1)
        if isinstance(seed,bool) or not isinstance(seed,int) or not -1<=seed<=9007199254740991:
            raise ValueError('图像生成种子需要填写有效整数。')
        size=_validate_custom_size(supplied.get('size','1024x1536'))
        width,height=map(int,size.split('x'))
        if width%32 or height%32:raise ValueError('画面宽高需为 32 的倍数。')
        output_size=supplied.get('output_size',1536)
        if isinstance(output_size,bool) or not isinstance(output_size,int) or not 512<=output_size<=2048 or output_size%32:
            raise ValueError('增强尺寸需在 512–2048 像素之间，按 32 调整。')
        return {'seed':secrets.randbelow(2**32) if seed==-1 else seed,'size':size,'output_size':output_size,'width':width,'height':height}
    if w['id'] in ('local-card-109','local-card-128'):
        if set(supplied)-{'seed','resolution','branch','upscale'}:
            raise ValueError('含有不属于此工作流的参数，请刷新后重试。')
        seed=supplied.get('seed',-1)
        if isinstance(seed,bool) or not isinstance(seed,int) or not -1<=seed<=9007199254740991:
            raise ValueError('图像生成种子需要填写有效整数。')
        resolution=supplied.get('resolution','768x1344')
        if resolution not in ('1024x1024','1152x896','896x1152','1216x832','832x1216','1344x768','768x1344','1536x640','640x1536'):
            raise ValueError('基础画面尺寸不在原工作流支持范围内。')
        branch=supplied.get('branch','standard')
        if branch not in ('standard','lora'):
            raise ValueError('生成分支不在原工作流支持范围内。')
        upscale=supplied.get('upscale',1.5)
        if isinstance(upscale,bool) or upscale not in (1,1.5):
            raise ValueError('二次放大倍率不在支持范围内。')
        return {'seed':secrets.randbelow(2**48) if seed==-1 else seed,'resolution':resolution,'branch':branch,'upscale':upscale}
    if w['id'] in ('local-card-104','local-card-129'):
        if set(supplied)-{'seed','resolution'}:
            raise ValueError('含有不属于此工作流的参数，请刷新后重试。')
        seed=supplied.get('seed',-1)
        if isinstance(seed,bool) or not isinstance(seed,int) or not -1<=seed<=9007199254740991:
            raise ValueError('图像生成种子需要填写有效整数。')
        resolution=supplied.get('resolution','768x1344')
        if resolution not in ('1024x1024','1152x896','896x1152','1216x832','832x1216','1344x768','768x1344','1536x640','640x1536'):
            raise ValueError('画面尺寸不在原工作流支持范围内。')
        return {'seed':secrets.randbelow(2**48) if seed==-1 else seed,'resolution':resolution}
    if w['id']=='local-card-21':
        if set(supplied)-{'seed','size'}:raise ValueError('含有不属于此工作流的参数，请刷新后重试。')
        seed=supplied.get('seed',-1)
        if isinstance(seed,bool) or not isinstance(seed,int) or not -1<=seed<=9007199254740991:raise ValueError('图像生成种子需要填写有效整数。')
        size=_validate_custom_size(supplied.get('size','1024x1024'))
        width,height=map(int,size.split('x'))
        return {'seed':secrets.randbelow(2**48) if seed==-1 else seed,'size':size,'width':width,'height':height}
    if w['id']=='local-card-19':
        if set(supplied)-{'seed','size'}:
            raise ValueError('含有不属于此工作流的参数，请刷新后重试。')
        seed=supplied.get('seed',-1)
        if isinstance(seed,bool) or not isinstance(seed,int) or not -1<=seed<=9007199254740991:
            raise ValueError('图像生成种子需要填写有效整数。')
        size=supplied.get('size','1024x1024')
        if not isinstance(size,str) or not re.fullmatch(r'[0-9]{3,4}x[0-9]{3,4}',size):
            raise ValueError('画面尺寸请填写宽×高，例如 1024x1024。')
        width,height=map(int,size.split('x'))
        if any(n<512 or n>4096 or n%32 for n in (width,height)):
            raise ValueError('画面宽高需在 512–4096 像素之间，且为 32 的倍数。')
        return {'seed':secrets.randbelow(2**48) if seed==-1 else seed,'size':size,'width':width,'height':height}
    if w['id'] in ('local-card-9','local-card-10'):
        if set(supplied)-{'seed','resolution','output_pixels'}:
            raise ValueError('含有不属于此工作流的参数，请刷新后重试。')
        seed=supplied.get('seed',-1)
        if isinstance(seed,bool) or not isinstance(seed,int) or not -1<=seed<=9007199254740991:
            raise ValueError('图像生成种子需要填写有效整数。')
        resolution=supplied.get('resolution','768x1344')
        if resolution not in ('1024x1024','1152x896','896x1152','1216x832','832x1216','1344x768','768x1344','1536x640','640x1536'):
            raise ValueError('画面尺寸不在原工作流支持范围内。')
        output_pixels=supplied.get('output_pixels',1536)
        if isinstance(output_pixels,bool) or not isinstance(output_pixels,int) or not 512<=output_pixels<=4096 or output_pixels%32:
            raise ValueError('输出总像素需在 512–4096 千像素之间，按 32 调整。')
        return {'seed':secrets.randbelow(2**48) if seed==-1 else seed,'resolution':resolution,'output_pixels':output_pixels}
    if w['id']=='local-card-82':
        if set(supplied)-{'seed','prompt_seed','output_long_side'}:
            raise ValueError('含有不属于此工作流的参数，请刷新后重试。')
        seeds={}
        for key in ('seed','prompt_seed'):
            value=supplied.get(key,-1)
            if isinstance(value,bool) or not isinstance(value,int) or not -1<=value<=9007199254740991:
                raise ValueError('随机种子需要填写有效整数。')
            seeds[key]=secrets.randbelow(2**48) if value==-1 else value
        side=supplied.get('output_long_side',1536)
        if isinstance(side,bool) or not isinstance(side,int) or not 256<=side<=4096 or side%32:
            raise ValueError('输出最长边需在 256–4096 像素之间，按 32 调整。')
        return {**seeds,'output_long_side':side}
    if w['id']=='local-card-14':
        if set(supplied)-{'seed','strength','horizontal_angle','vertical_angle','zoom'}:
            raise ValueError('含有不属于此工作流的参数，请刷新后重试。')
        seed=supplied.get('seed',-1)
        if isinstance(seed,bool) or not isinstance(seed,int) or not -1<=seed<=9007199254740991:
            raise ValueError('图像生成种子需要填写有效整数。')
        horizontal=supplied.get('horizontal_angle',0)
        vertical=supplied.get('vertical_angle',30)
        zoom=supplied.get('zoom',5)
        strength=supplied.get('strength',0.4)
        if any(isinstance(v,bool) or not isinstance(v,int) for v in (horizontal,vertical)) or not 0<=horizontal<=360 or not -30<=vertical<=60:
            raise ValueError('视角超出原节点支持范围。')
        for key,value in [('zoom',zoom),('strength',strength)]:
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<=10 or abs(value*10-round(value*10))>1e-6:
                raise ValueError(('镜头拉近' if key=='zoom' else '调色强度')+'应在 0–10 之间，按 0.1 调整。')
        return {'seed':secrets.randbelow(2**48) if seed==-1 else seed,'strength':strength,'horizontal_angle':horizontal,'vertical_angle':vertical,'zoom':zoom}
    if w['id'] in ('local-card-105','local-card-106'):
        if set(supplied)-{'seed','noise_seed','aspect_ratio','megapixels'}:
            raise ValueError('含有不属于此工作流的参数，请刷新后重试。')
        seeds={}
        for key in ('seed','noise_seed'):
            value=supplied.get(key,-1)
            if isinstance(value,bool) or not isinstance(value,int) or not -1<=value<=9007199254740991:
                raise ValueError('随机种子需要填写有效整数。')
            seeds[key]=secrets.randbelow(2**48) if value==-1 else value
        ratio=supplied.get('aspect_ratio','9:16 (Portrait Widescreen)')
        ratios=['16:9 (Widescreen)','1:1 (Square)','21:9 (Ultrawide)','3:4 (Portrait Standard)',
                '4:3 (Standard)','9:16 (Portrait Widescreen)','2:3 (Portrait Photo)','3:2 (Photo)']
        if ratio not in ratios:raise ValueError('画面比例不在源节点支持范围内。')
        mp=supplied.get('megapixels',1)
        if isinstance(mp,bool) or not isinstance(mp,(int,float)) or not math.isfinite(mp) or not 0.1<=mp<=16 or abs(mp*10-round(mp*10))>1e-6:
            raise ValueError('百万像素应在 0.1–16 MP 之间，按 0.1 调整。')
        return {**seeds,'aspect_ratio':ratio,'megapixels':mp}
    if w['id'] in ('local-card-1','local-card-2','local-card-3','local-card-84'):
        if set(supplied)-{'seed','aspect_ratio','megapixels'}:
            raise ValueError('含有不属于此工作流的参数，请刷新后重试。')
        seed=supplied.get('seed',-1)
        if isinstance(seed,bool) or not isinstance(seed,int) or not -1<=seed<=9007199254740991:
            raise ValueError('图像生成种子需要填写有效整数。')
        ratios=['16:9 (Widescreen)','1:1 (Square)','21:9 (Ultrawide)',
                '3:4 (Portrait Standard)','4:3 (Standard)','9:16 (Portrait Widescreen)',
                '2:3 (Portrait Photo)','3:2 (Photo)']
        ratio=supplied.get('aspect_ratio','1:1 (Square)' if w['id'] in ('local-card-2','local-card-3','local-card-84') else '9:16 (Portrait Widescreen)')
        if ratio not in ratios:raise ValueError('画面比例不在源节点支持范围内。')
        mp=supplied.get('megapixels',1)
        if isinstance(mp,bool) or not isinstance(mp,(int,float)) or not math.isfinite(mp) or not 0.1<=mp<=16:
            raise ValueError('百万像素应在 0.1–16 MP 之间。')
        if abs(mp*10-round(mp*10))>1e-6:raise ValueError('百万像素按 0.1 MP 调整。')
        return {'seed':secrets.randbelow(2**48) if seed==-1 else seed,'aspect_ratio':ratio,'megapixels':mp}
    if w['id']=='local-card-78':
        if set(supplied)-{'seed'}:
            raise ValueError('含有不属于此工作流的参数，请刷新后重试。')
        seed=supplied.get('seed',-1)
        if isinstance(seed,bool) or not isinstance(seed,int) or not -1<=seed<=9007199254740991:
            raise ValueError('图像生成种子需要填写有效整数。')
        return {'seed':secrets.randbelow(2**48) if seed==-1 else seed}
    if w['id']=='local-card-12':
        if set(supplied)-{'seed','prompt_turn2real','prompt_semireal'}:raise ValueError('含有不属于此工作流的参数，请刷新后重试。')
        seed=supplied.get('seed',-1)
        if isinstance(seed,bool) or not isinstance(seed,int) or not -1<=seed<=9007199254740991:raise ValueError('图像生成种子需要填写有效整数。')
        prompts={k:supplied.get(k,v) for k,v in [('prompt_turn2real','reskin this into a real photo'),('prompt_semireal','转为写实摄影')]}
        if any(not isinstance(v,str) or not v.strip() or len(v)>6000 for v in prompts.values()):raise ValueError('请填写三个模型各自的真人化描述。')
        return {'seed':secrets.randbelow(2**48) if seed==-1 else seed,**prompts}
    if w['id']=='local-card-85':
        if set(supplied)-{'seed','size'}:raise ValueError('含有不属于此工作流的参数，请刷新后重试。')
        seed=supplied.get('seed',-1)
        if isinstance(seed,bool) or not isinstance(seed,int) or not -1<=seed<=9007199254740991:raise ValueError('图像生成种子需要填写有效整数。')
        size=_validate_custom_size(supplied.get('size','896x1088'))
        return {'seed':secrets.randbelow(2**48) if seed==-1 else seed,'size':size}
    if w['id']=='local-card-83':
        if set(supplied)-{'seed'}:raise ValueError('含有不属于此工作流的参数，请刷新后重试。')
        seed=supplied.get('seed',-1)
        if isinstance(seed,bool) or not isinstance(seed,int) or not -1<=seed<=9007199254740991:
            raise ValueError('图像生成种子需要填写有效整数。')
        return {'seed':secrets.randbelow(2**48) if seed==-1 else seed}
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
    if workflow_id in ('local-card-11','local-card-15','local-card-16','local-card-17','local-card-18','local-card-20'):
        g=json.loads(workflow_path(workflow_id).read_text('utf-8'))
        images=[a for a in assets if a['kind']=='image']
        # Browser bindings follow the image socket order; resolve them to the graph's natural-language image names.
        prompt=re.sub(r'@图片(\d+)',lambda m:'图'+m.group(1),prompt)
        expected={'local-card-11':2,'local-card-15':1,'local-card-16':2,
                  'local-card-17':2,'local-card-18':2,'local-card-20':1}[workflow_id]
        if len(images)!=expected:raise ValueError(f'此工作流需要 {expected} 张图片。')
        def bind_image(node,index):g[node]['inputs']['image']=images[index]['remote']
        def bind_text(node,value,key='text'):g[node]['inputs'][key]=value
        def prefix(node,branch=None):g[node]['inputs']['filename_prefix']='yingxu/'+job_id+('/'+branch if branch else '')
        if workflow_id=='local-card-11':
            bind_image('63',0);bind_image('64',1)
            bind_text('158',prompt,'value');bind_text('145',negative,'prompt')
            g['157']['inputs']['seed']=settings['seed']
            g['162']['inputs']['resolution']=settings['resolution']
            prefix('62','Flux-9B');prefix('147','Qwen-AIO')
            return prune(g,['62','147'])
        if workflow_id=='local-card-15':
            bind_image('148',0);bind_text('142',prompt)
            g['141']['inputs']['seed']=settings['seed']
            g['144']['inputs']['strength']=settings['strength']
            prefix('135');return prune(g,['135'])
        if workflow_id=='local-card-16':
            bind_image('36',0);bind_image('25',1);bind_text('37',prompt)
            # Without painted alpha, use the original image directly; no empty mask reaches DrawMaskOnImage.
            if not images[0].get('has_edit_mask',False):
                g['38']['inputs'].pop('mask',None)
                g['21']['inputs']['pixels']=['38',0]
            g['17']['inputs']['seed']=settings['seed']
            prefix('26');return prune(g,['26'])
        if workflow_id in ('local-card-17','local-card-18'):
            bind_image('76',0);bind_image('81',1)
            if workflow_id=='local-card-17':
                bind_text('109',prompt);bind_text('121',prompt)
                seeds=('101','118')
            else:
                bind_text('107',prompt);bind_text('127',prompt)
                bind_text('108',negative);bind_text('128',negative)
                seeds=('104','117')
            for node in seeds:g[node]['inputs']['noise_seed']=settings['seed']
            prefix('9','single');prefix('94','double')
            return prune(g,['9','94'])
        bind_image('43',0);bind_text('36',prompt)
        g['7']['inputs']['noise_seed']=settings['seed']
        prefix('15');return prune(g,['15'])
    if workflow_id=='local-card-134':
        g=json.loads(workflow_path('local-card-134').read_text('utf-8'))
        images=[a for a in assets if a['kind']=='image']
        if len(images)!=2:raise ValueError('此工作流需要待调色原图和色彩参考图。')
        g['11']['inputs']['image']=images[0]['remote']
        g['12']['inputs']['image']=images[1]['remote']
        g['10']['inputs']['strength']=settings['strength']
        g['14']['inputs']['filename_prefix']='yingxu/'+job_id
        return prune(g,['14'])
    if workflow_id=='local-card-13':
        g=json.loads(workflow_path('local-card-13').read_text('utf-8'))
        images=[a for a in assets if a['kind']=='image']
        if len(images)!=1:raise ValueError('此工作流需要一张待扩展原图。')
        g['63']['inputs']['image']=images[0]['remote']
        g['19']['inputs']['text']=prompt
        g['95']['inputs']['seed']=settings['seed']
        for key in ('left','top','right','bottom'):g['108']['inputs'][key]=settings[key]
        g['124']['inputs']['strength']=settings['strength']
        g['131']['inputs']['scale_to_length']=settings['output_long_side']
        g['62']['inputs']['filename_prefix']='yingxu/'+job_id
        return prune(g,['62'])
    if workflow_id=='local-card-14':
        g=json.loads(workflow_path('local-card-14').read_text('utf-8'))
        images=[a for a in assets if a['kind']=='image']
        if len(images)!=1:raise ValueError('此工作流需要一张待转换原图。')
        g['63']['inputs']['image']=images[0]['remote']
        g['114']['inputs']['prompt']=prompt
        g['95']['inputs']['seed']=settings['seed']
        for key in ('horizontal_angle','vertical_angle','zoom'):g['105']['inputs'][key]=settings[key]
        g['108']['inputs']['strength']=settings['strength']
        g['62']['inputs']['filename_prefix']='yingxu/'+job_id
        return prune(g,['62'])
    if workflow_id=='local-card-12':
        g=json.loads(workflow_path('local-card-12').read_text('utf-8'))
        images=[a for a in assets if a['kind']=='image']
        if len(images)!=1:raise ValueError('此工作流需要一张动漫原图。')
        g['63']['inputs']['image']=images[0]['remote']
        for node,text in [('19',prompt),('171',settings['prompt_turn2real']),('180',settings['prompt_semireal'])]:
            g[node]['inputs']['text']=text
        g['158']['inputs']['seed']=settings['seed']
        for node,branch in [('62','Anything-to-Real'),('170','Turn2Real'),('179','anime2real-semi')]:
            g[node]['inputs']['filename_prefix']='yingxu/'+job_id+'/'+branch
        return prune(g,['62','170','179'])
    if workflow_id=='local-card-82':
        g=json.loads(workflow_path('local-card-82').read_text('utf-8'))
        images=[a for a in assets if a['kind']=='image']
        if len(images)!=1:raise ValueError('此工作流需要一张动漫原图。')
        g['31']['inputs']['image']=images[0]['remote']
        g['43']['inputs']['text']=prompt
        g['9']['inputs']['prompt']=negative
        g['161']['inputs']['seed']=settings['prompt_seed']
        g['28']['inputs']['seed']=settings['seed']
        g['26']['inputs']['value']=settings['output_long_side']
        g['30']['inputs']['filename_prefix']='yingxu/'+job_id
        return prune(g,['30'])
    if workflow_id in ('local-card-105','local-card-106'):
        g=json.loads(workflow_path(workflow_id).read_text('utf-8'))
        if assets:raise ValueError('此工作流不接收参考素材。')
        if workflow_id=='local-card-105':text,ratio,api,noise,output='186:115','183','190','187:18','182'
        else:text,ratio,api,noise,output='134:115','37','178','98:18','158'
        g[text]['inputs']['value']=prompt
        g[ratio]['inputs'].update(aspect_ratio=settings['aspect_ratio'],megapixels=settings['megapixels'])
        g[api]['inputs']['seed']=settings['seed']
        g[noise]['inputs']['noise_seed']=settings['noise_seed']
        g[output]['inputs']['filename_prefix']='yingxu/'+job_id
        return prune(g,[output])
    if workflow_id=='local-card-83':
        g=json.loads(workflow_path('local-card-83').read_text('utf-8'))
        images=[a for a in assets if a['kind']=='image']
        if len(images)!=1:raise ValueError('此工作流需要一张动漫原图。')
        g['227']['inputs']['image']=images[0]['remote']
        g['471']['inputs']['value']=prompt
        g['221']['inputs']['seed']=settings['seed']
        g['228']['inputs']['filename_prefix']='yingxu/'+job_id
        return prune(g,['228'])
    if workflow_id in ('local-card-3','local-card-84'):
        g=json.loads(workflow_path(workflow_id).read_text('utf-8'))
        images=[a for a in assets if a['kind']=='image']
        if workflow_id=='local-card-3':
            if len(images)!=2:raise ValueError('此工作流需要原图和服装参考图。')
            g['551']['inputs']['image']=images[0]['remote']
            g['547']['inputs']['image']=images[1]['remote']
            g['560']['inputs']['value']=prompt
            g['540:491']['inputs']['negative_prompt']=negative
            ratio,seed,output='541','558','539'
        else:
            if len(images)!=1:raise ValueError('此工作流需要一张动漫原图。')
            g['506']['inputs']['image']=images[0]['remote']
            g['497:474']['inputs'].update(prompt=prompt,negative_prompt=negative)
            ratio,seed,output='496','515','494'
        g[ratio]['inputs'].update(aspect_ratio=settings['aspect_ratio'],megapixels=settings['megapixels'])
        g['540:489' if workflow_id=='local-card-3' else '497:468']['inputs']['switch']=True
        g[seed]['inputs']['seed']=settings['seed']
        g[output]['inputs']['filename_prefix']='yingxu/'+job_id
        return prune(g,[output])
    if workflow_id=='local-card-78':
        g=json.loads(workflow_path('local-card-78').read_text('utf-8'))
        images=[a for a in assets if a['kind']=='image']
        if len(images)!=1:raise ValueError('此工作流需要一张待编辑原图。')
        g['31']['inputs']['image']=images[0]['remote']
        g['11']['inputs']['prompt']=prompt
        g['3']['inputs']['prompt']=negative
        # Source preprocessing is fixed at 1.5 MP; it is not an output control.
        g['39']['inputs']['megapixels']=1.5
        g['14']['inputs']['seed']=settings['seed']
        g['80']['inputs']['filename_prefix']='yingxu/'+job_id
        return prune(g,['80'])
    if workflow_id=='local-card-108':
        g=json.loads(workflow_path('local-card-108').read_text('utf-8'))
        g['63']['inputs']['value']=prompt
        g['49']['inputs'].update(aspect_ratio=settings['aspect_ratio'],megapixels=settings['megapixels'])
        g['53']['inputs']['seed']=settings['seed']
        g['60']['inputs']['sampling_mode.seed']=settings['prompt_seed']
        g['67']['inputs']['value']=settings['lora_enabled']
        g['68']['inputs']['value']=settings['prompt_optimize']
        g['59']['inputs']['strength_model']=settings['model_strength']
        g['29']['inputs']['filename_prefix']='yingxu/'+job_id
        return prune(g,['29'])
    if workflow_id=='local-card-110':
        g=json.loads(workflow_path('local-card-110').read_text('utf-8'))
        g['90']['inputs']['text']=prompt
        g['173']['inputs']['text']=negative
        width,height=map(int,settings['size'].split('x'))
        g['29']['inputs'].update(width=width,height=height)
        g['63']['inputs']['noise_seed']=settings['seed']
        g['106']['inputs']['filename_prefix']='yingxu/'+job_id
        return prune(g,['106'])
    if workflow_id=='local-card-130':
        g=json.loads(workflow_path('local-card-130').read_text('utf-8'))
        g['13']['inputs']['prompt']=prompt
        width,height=map(int,settings['size'].split('x'))
        g['11']['inputs'].update(width=width,height=height)
        g['34']['inputs']['value']=settings['lora_strength']
        g['5']['inputs']['seed']=settings['seed']
        g['26']['inputs']['filename_prefix']='yingxu/'+job_id
        return prune(g,['26'])
    if workflow_id=='local-card-107':
        g=json.loads(workflow_path('local-card-107').read_text('utf-8'))
        g['6']['inputs']['text']=prompt
        g['7']['inputs']['text']=negative
        g['58']['inputs'].update(width=settings['width'],height=settings['height'])
        g['3']['inputs']['seed']=settings['seed']
        g['80']['inputs'].update(seed=settings['seed']%(2**32),resolution=settings['output_size'])
        g['site-output']={'class_type':'SaveImage','inputs':{'filename_prefix':'yingxu/'+job_id,'images':['80',0]}}
        return prune(g,['site-output'])
    if workflow_id in ('local-card-109','local-card-128'):
        g=json.loads(workflow_path(workflow_id).read_text('utf-8'))
        g['45']['inputs']['value']=prompt
        g['54']['inputs']['text']=negative
        g['44']['inputs']['resolution']=settings['resolution']
        g['57']['inputs']['seed']=settings['seed']
        if settings['branch']=='lora':scale,sampler,decoded='47','48','56'
        else:scale,sampler,decoded='52','51','55'
        g[scale]['inputs']['scale_by']=settings['upscale']
        g[sampler]['inputs']['seed']=settings['seed']
        g['site-output']={'class_type':'SaveImage','inputs':{'filename_prefix':'yingxu/'+job_id,'images':[decoded,0]}}
        return prune(g,['site-output'])
    if workflow_id in ('local-card-104','local-card-129'):
        g=json.loads(workflow_path(workflow_id).read_text('utf-8'))
        g['104']['inputs']['value']=prompt
        g['113']['inputs']['text']=negative
        g['116']['inputs']['seed']=settings['seed']
        g['103']['inputs']['resolution']=settings['resolution']
        g['99']['inputs']['filename_prefix']='yingxu/'+job_id
        return prune(g,['99'])
    if workflow_id in ('local-card-19','local-card-21'):
        g=json.loads(workflow_path(workflow_id).read_text('utf-8'))
        if workflow_id=='local-card-19':
            g['76']['inputs']['value']=prompt
            g['85']['inputs']['text']=negative
            width,height,seed,output='86','87','88','9'
        else:
            g['28']['inputs']['value']=prompt
            width,height,seed,output='19','20','21','14'
        g[width]['inputs']['value']=settings['width']
        g[height]['inputs']['value']=settings['height']
        g[seed]['inputs']['noise_seed']=settings['seed']
        g[output]['inputs']['filename_prefix']='yingxu/'+job_id
        return prune(g,[output])
    if workflow_id in ('local-card-9','local-card-10'):
        g=json.loads(workflow_path(workflow_id).read_text('utf-8'))
        if workflow_id=='local-card-9':
            g['108']['inputs']['value']=prompt
            g['89']['inputs']['text']=negative
            g['96']['inputs']['noise_seed']=settings['seed']
            g['105']['inputs']['resolution']=settings['resolution']
            g['107']['inputs']['scale_to_length']=settings['output_pixels']
            output='104'
        else:
            g['83']['inputs']['value']=prompt
            g['75']['inputs']['seed']=settings['seed']
            g['54']['inputs']['resolution']=settings['resolution']
            g['58']['inputs']['scale_to_length']=settings['output_pixels']
            output='31'
        g[output]['inputs']['filename_prefix']='yingxu/'+job_id
        return prune(g,[output])
    if workflow_id=='local-card-2':
        g=json.loads(workflow_path('local-card-2').read_text('utf-8'))
        images=[a for a in assets if a['kind']=='image']
        if len(images)!=2:raise ValueError('此工作流需要待编辑原图和修改参考图。')
        g['518:491']['inputs'].update(prompt=prompt,negative_prompt=negative)
        g['522']['inputs'].update(aspect_ratio=settings['aspect_ratio'],megapixels=settings['megapixels'])
        g['518:489']['inputs']['switch']=True
        g['536']['inputs']['seed']=settings['seed']
        g['530']['inputs']['image']=images[0]['remote']
        g['527']['inputs']['image']=images[1]['remote']
        g['517']['inputs']['filename_prefix']='yingxu/'+job_id
        return prune(g,['517'])
    if workflow_id=='local-card-1':
        g=json.loads(workflow_path('local-card-1').read_text('utf-8'))
        g['459:452']['inputs'].update(prompt=prompt,negative_prompt=negative)
        g['13']['inputs'].update(aspect_ratio=settings['aspect_ratio'],megapixels=settings['megapixels'])
        g['476']['inputs']['seed']=settings['seed']
        g['461']['inputs']['filename_prefix']='yingxu/'+job_id
        return prune(g,['461'])
    if workflow_id=='local-card-85':
        g=json.loads(workflow_path('local-card-85').read_text('utf-8'))
        g['67']['inputs']['value']=prompt
        if negative.strip():g['66']['inputs']['text']=negative
        width,height=map(int,settings['size'].split('x'))
        g['65']['inputs'].update(width_override=width,height_override=height)
        for key in ['58','63']:g[key]['inputs']['seed']=settings['seed']
        g['54']['inputs']['filename_prefix']='yingxu/'+job_id
        return prune(g,['54'])
    g=json.loads(workflow_path(workflow_id).read_text('utf-8'))
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
    start_frame=round(s['trim_start']*s['fps'])
    end_frame=round((s['trim_start']+s['duration'])*s['fps'])
    put('425',video=videos[0]['remote'],force_rate=s['fps'],skip_first_frames=start_frame,frame_load_cap=end_frame-start_frame+1,format='Wan')
    put('434',scale_to_length=s['long_side'])
    g['387']['inputs']={k:v for k,v in g['387']['inputs'].items() if not k.startswith('reference_images.')}
    put('387',ref_max_size=s['long_side'])
    for ix,a in enumerate(images):
        key=f'upload_{ix}';g[key]={'class_type':'LoadImage','inputs':{'image':a['remote']}}
        g['387']['inputs'][f'reference_images.reference_image_{ix}']=[key,0]
    put('443',filename_prefix=f'yingxu/{job_id}',crf=19,save_metadata=False)
    return prune(g,['443'])
