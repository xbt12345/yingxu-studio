"""Personal studio: persistent jobs, real ComfyUI execution and retained videos."""
import asyncio
import copy
import secrets
import mimetypes
import math
import hashlib
import io
import json
import os
import re
import sqlite3
import threading
import time
import uuid
import sys
from urllib.parse import urlsplit, urlunsplit
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from fractions import Fraction

# Isolate the Starlette version required by the machine's FastAPI installation.
sys.path.insert(0,str(Path(__file__).resolve().parent/'private/runtime'))

import requests
import websocket
import av
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageChops, ImageOps
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from adapters import ROOT, WORKFLOWS, CATALOG_WORKFLOWS, manifest, settings_for, build_graph, prune
from local_directory import choose_directory
from portable import embed_workflow
from configuration import DATA_DIR, workflow_path
from deployment_access import access_denied, railway_origin
import schema_adapters
from region_preservation import preserve_region_output
from reviewed_repairs import preserve_117_source_audio
from png_delivery import strip_png_text

try:
    local_config=json.loads((ROOT/'private/backend.json').read_text('utf-8'))
except (OSError,ValueError):local_config={}
BASE = os.environ.get('CHENYU_CARD_URL',local_config.get('card_url','')).rstrip('/')
CLIENT = 'yingxu-local-mvp-v07'
PRIVATE = DATA_DIR
for folder in ['uploads','outputs','receipts']:(PRIVATE/folder).mkdir(parents=True,exist_ok=True)
DB = PRIVATE/'workspace.sqlite3'
lock=threading.RLock()
stopping=threading.Event()
@contextmanager
def database():
    connection=sqlite3.connect(DB)
    try:
        with connection:yield connection
    finally:connection.close()

with database() as db:
    db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, token TEXT UNIQUE, data TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS assets (id TEXT PRIMARY KEY, data TEXT NOT NULL)')

def jobs():
    with lock,database() as db:return [json.loads(r[0]) for r in db.execute('SELECT data FROM jobs ORDER BY rowid')]
def job(id):
    with lock,database() as db:
        r=db.execute('SELECT data FROM jobs WHERE id=?',(id,)).fetchone()
    if not r:raise HTTPException(404,'找不到任务。')
    return json.loads(r[0])
def save(j):
    with lock,database() as db:db.execute('INSERT INTO jobs VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET token=excluded.token,data=excluded.data',(j['id'],j['token'],json.dumps(j,ensure_ascii=False)))
def update(id,**values):
    with lock:
        j=job(id)
        if j.get('status')=='abandoned':return j
        j.update(values);save(j)
    return j
def asset(id):
    with lock,database() as db:r=db.execute('SELECT data FROM assets WHERE id=?',(id,)).fetchone()
    if not r:raise HTTPException(400,'参考素材未上传成功，请重新选择素材后提交。')
    return json.loads(r[0])
def asset_file(a):
    # The hash, rather than a caller-supplied filename, owns the disk path.
    if len(a['id']) != 64 or any(c not in '0123456789abcdef' for c in a['id']):
        raise HTTPException(404, '找不到素材。')
    path=next((p for p in (PRIVATE/'uploads').glob(a['id']+'.*') if p.is_file()),None)
    if not path:raise HTTPException(409, '原素材文件已被移除，请重新导入同一份素材后重试。')
    return path

def has_edit_mask(a):
    with Image.open(asset_file(a)) as image:
        alpha=image.getchannel('A') if 'A' in image.getbands() else None
        return alpha is not None and alpha.getextrema()[0]<255

def require_edit_mask(a):
    """Required-mask graphs must reject an empty mask before dispatch."""
    if not has_edit_mask(a):
        raise HTTPException(400,'原图还没有编辑区域。请在原图上使用「画笔标注区域」后再生成。')

def require_schema_edit_inputs(spec,records,values):
    """Check only reviewed inpaint consumers fed by an uploaded alpha mask.

    A segmentation model's IMAGE input and a visual annotation are not edit-mask
    contracts. Follow the actual active template links, never workflow names.
    """
    graph=prune(json.loads(schema_adapters.template_path(spec).read_text('utf-8')),spec['outputs'])
    for control in spec.get('controls',[]):
        if values.get(control['id'])!=1:continue
        for target in control.get('targets',[]):
            switch=graph.get(str(target.get('node')), {})
            if target.get('input')!='index' or switch.get('class_type')!='easy anythingIndexSwitch':continue
            manual=switch.get('inputs',{}).get('value1')
            if isinstance(manual,list) and len(manual)==2 and manual[1]==1 and graph.get(str(manual[0]),{}).get('class_type')=='PreviewBridge':
                raise HTTPException(400,'网站尚不支持手工掩膜桥接，请使用自动分割；手工分支需要在算力卡 MaskEditor 中保存掩膜。')
    consumers={'AnimaLLLiteApply','ZImageFunControlnet'}
    mask_outputs={('MaskPreview',0):'mask',
                  ('LayerUtility: ImageScaleByAspectRatio V2',1):'mask',
                  ('GrowMaskWithBlur',0):'mask'}
    def from_loader(link,loader,seen=None):
        if not isinstance(link,list) or len(link)!=2:return False
        node_id,output=str(link[0]),link[1]
        if node_id==loader:return output==1
        seen=set()if seen is None else seen
        if node_id in seen:return False
        seen.add(node_id)
        node=graph.get(node_id,{})
        field=mask_outputs.get((node.get('class_type'),output))
        return bool(field)and from_loader(node.get('inputs',{}).get(field),loader,seen)
    for slot in spec.get('media',[]):
        if slot.get('kind')!='image' or not slot.get('required',not slot.get('optional',False)) or slot['id']not in records:continue
        for target in slot.get('targets',[]):
            loader=str(target.get('node'))
            if target.get('input')!='image' or graph.get(loader,{}).get('class_type')!='LoadImage':continue
            if any(node.get('class_type')in consumers and from_loader(node.get('inputs',{}).get('mask'),loader)for node in graph.values()):
                require_edit_mask(records[slot['id']])
                break

def video_length(a):
    try:
        with av.open(str(asset_file(a))) as container:
            if container.duration is not None:return container.duration/av.time_base
            stream=next((s for s in container.streams if s.type=='video'),None)
            if stream and stream.duration is not None:return float(stream.duration*stream.time_base)
    except (av.error.FFmpegError, OSError, ValueError):
        pass
    raise HTTPException(400,'无法读取原视频时长，请重新导出 MP4 后再试。')

def video_packet_signature(path):
    """Verify lossless remuxing, including presentation/decode timing."""
    with av.open(str(path)) as container:
        stream=container.streams.video[0]
        digest=hashlib.sha256();count=0
        for packet in container.demux(stream):
            if packet.dts is None:continue
            data=bytes(packet)
            timing=(packet.pts*packet.time_base if packet.pts is not None else None,
                    packet.dts*packet.time_base,packet.duration*packet.time_base)
            digest.update(str((len(data),timing)).encode('ascii'));digest.update(data);count+=1
        return (stream.codec_context.name,stream.width,stream.height,
                stream.duration*stream.time_base if stream.duration is not None else None,
                stream.start_time*stream.time_base if stream.start_time is not None else None,
                count,digest.hexdigest())


def vhs_audio_asset(source):
    """VHS currently materializes AUDIO even for an unused audio output.

    Keep sound-bearing originals unchanged. For a video without any audio track,
    derive a packet-copy MP4 with silence; never re-encode the video or mutate the
    user's original. Reject formats whose packets/timing cannot be preserved.
    PyAV's pinned wheels provide AAC/MP4, with no system ffmpeg requirement.
    """
    path=asset_file(source)
    try:
        with av.open(str(path)) as container:
            if len(container.streams.video)!=1:raise ValueError('需要单一视频轨道。')
            if container.streams.audio:
                if next(container.decode(container.streams.audio[0]),None) is None:raise ValueError('音轨没有有效音频帧。')
                return source
            duration=container.duration
            if duration is None or duration<=0:raise ValueError('无法确定视频时长。')
    except (av.error.FFmpegError,ValueError,OSError):
        raise HTTPException(400,'此工作流需要有效的视频和音轨；无法读取原视频，请重新导出 MP4 后导入。')from None
    cached_id=source.get('vhs_silent_asset')
    if cached_id:
        try:
            cached=asset(cached_id);asset_file(cached)
            if cached.get('original_asset_id')==source['id'] and cached.get('adaptation')=='vhs-silent-aac-v1':return cached
        except HTTPException:pass
    temporary=PRIVATE/'uploads'/('.vhs-silent-'+uuid.uuid4().hex+'.mp4')
    try:
        signature=video_packet_signature(path)
        if not signature[-2]:raise ValueError('视频没有有效压缩帧。')
        with av.open(str(path)) as original,av.open(str(temporary),'w',format='mp4',options={'avoid_negative_ts':'disabled'}) as output:
            video=original.streams.video[0]
            copied=output.add_stream_from_template(video);copied.time_base=video.time_base
            copied.metadata.update(video.metadata);output.metadata.update(original.metadata)
            audio=output.add_stream('aac',rate=48000);audio.layout='stereo';audio.bit_rate=32000
            total=(duration*48000+av.time_base-1)//av.time_base;written=0
            def silence_until(end):
                nonlocal written
                while written<end:
                    samples=min(1024,end-written)
                    frame=av.AudioFrame('fltp','stereo',samples);frame.sample_rate=48000
                    frame.pts=written;frame.time_base=Fraction(1,48000)
                    for plane in frame.planes:plane.update(bytes(plane.buffer_size))
                    for packet in audio.encode(frame):output.mux(packet)
                    written+=samples
            for packet in original.demux(video):
                if packet.dts is None:continue
                silence_until(min(total,max(0,int(packet.dts*packet.time_base*48000))))
                packet.stream=copied;output.mux(packet)
            silence_until(total)
            for packet in audio.encode():output.mux(packet)
        if video_packet_signature(temporary)!=signature:raise ValueError('视频压缩包或时间轴发生变化。')
        with av.open(str(temporary)) as derived:
            if derived.duration is None or abs(derived.duration-duration)>math.ceil(av.time_base/48000):
                raise ValueError('视频时长发生变化。')
            if not derived.streams.audio or next(derived.decode(derived.streams.audio[0]),None) is None:
                raise ValueError('静音轨无法解码。')
        data=temporary.read_bytes()
        if len(data)>200*1024*1024:raise ValueError('静音副本超过单素材大小限制。')
        key=hashlib.sha256(data).hexdigest();destination=PRIVATE/'uploads'/(key+'.mp4')
        temporary.replace(destination)
        record=dict(id=key,kind='video',name=Path(source['name']).stem+'（静音兼容）.mp4',bytes=len(data),
                    original_asset_id=source['id'],adaptation='vhs-silent-aac-v1')
        with lock,database() as db:
            existing=db.execute('SELECT data FROM assets WHERE id=?',(key,)).fetchone()
            if existing:record=json.loads(existing[0])
            else:db.execute('INSERT INTO assets VALUES (?,?)',(key,json.dumps(record,ensure_ascii=False)))
            original_record=json.loads(db.execute('SELECT data FROM assets WHERE id=?',(source['id'],)).fetchone()[0])
            original_record['vhs_silent_asset']=key
            db.execute('UPDATE assets SET data=? WHERE id=?',(json.dumps(original_record,ensure_ascii=False),source['id']))
        return record
    except (av.error.FFmpegError,ValueError,TypeError,IndexError,OSError):
        raise HTTPException(400,'此视频没有音轨，当前格式无法无损添加静音轨。请重新导出带音轨的 MP4（静音音轨也可），再导入此工作流。')from None
    finally:
        temporary.unlink(missing_ok=True)


def source_audio_presence(spec,records):
    """Inspect the owned original, before any compatibility remux or upload."""
    if spec.get('id')!='local-card-117':return None
    source=records.get('269')
    if not source or source.get('kind')!='video':
        raise ValueError('请先导入原视频，无法确认其音轨。')
    try:
        with av.open(str(asset_file(source))) as container:
            if len(container.streams.video)!=1:raise ValueError('需要单一视频轨道。')
            return bool(container.streams.audio)
    except (av.error.FFmpegError,ValueError,OSError):
        raise ValueError('无法读取原视频的音轨，请重新导入有效视频。')from None


def schema_vhs_assets(spec,records,graph=None,*,source_has_audio=None):
    graph=graph if graph is not None else prune(json.loads(schema_adapters.template_path(spec).read_text('utf-8')),spec['outputs'])
    if spec.get('id')=='local-card-117' and source_has_audio is None:
        source_has_audio=source_audio_presence(spec,records)
    result=dict(records)
    for slot in spec.get('media',[]):
        if slot['id']not in records or records[slot['id']].get('kind')!='video':continue
        if spec.get('id')=='local-card-117' and slot['id']=='269' and source_has_audio is False:
            # This source has optional audio conditioning/save inputs. Omit
            # those consumers instead of materializing a synthetic soundtrack.
            continue
        if any(target.get('input')=='video' and graph.get(str(target.get('node')),{}).get('class_type')=='VHS_LoadVideo'
               for target in slot.get('targets',[])):
            result[slot['id']]=vhs_audio_asset(records[slot['id']])
    return result


def bind_vhs_audio(graph,records):
    """Compatibility path for existing named adapters, based on actual links."""
    for node in graph.values():
        if node.get('class_type')!='VHS_LoadVideo':continue
        source=next((record for record in records if record.get('kind')=='video' and record.get('remote')==node.get('inputs',{}).get('video')),None)
        if source:node['inputs']['video']=ensure_remote(vhs_audio_asset(source))['remote']


def points_geometry(spec,values,records):
    recipe=spec.get('pointsRecipe')
    if not recipe:return None
    source=records.get(recipe.get('slotId'))
    if not source or source.get('kind')!='video':raise ValueError('主体点选需要绑定原视频。')
    try:
        with av.open(str(asset_file(source))) as container:
            stream=next((s for s in container.streams if s.type=='video'),None)
            width,height=(stream.width,stream.height) if stream else (0,0)
    except (av.error.FFmpegError,OSError,ValueError):raise ValueError('无法读取原视频尺寸，请重新导入。') from None
    long_side=values.get(recipe.get('longSideControlId'),recipe.get('longSide'))
    multiple=recipe.get('multiple')
    if not width or not height or not isinstance(long_side,(int,float)) or isinstance(long_side,bool) or not math.isfinite(long_side) or long_side<=0 or not isinstance(multiple,int) or multiple<=0:
        raise ValueError('主体点选的缩放尺寸未完成审查。')
    source_multiple=recipe.get('sourceMultiple',1)
    if not isinstance(source_multiple,int) or isinstance(source_multiple,bool) or source_multiple<=0:
        raise ValueError('主体点选的原视频尺寸转换未完成审查。')
    # VHS AnimateDiff first center-crops to its format's nearest dimension
    # multiple, before LayerStyle receives the frame. Match its int(x+.5)
    # rounding instead of Python's ties-to-even round().
    width=int(width/source_multiple+0.5)*source_multiple
    height=int(height/source_multiple+0.5)*source_multiple
    if not width or not height:raise ValueError('原视频尺寸过小，无法进行主体点选。')
    # LayerUtility original/longest: truncate proportional short side, then
    # round both dimensions upward before its fit-crop resize.
    if width>=height:target_width,target_height=int(long_side),int(long_side*height/width)
    else:target_width,target_height=int(long_side*width/height),int(long_side)
    target_width=int(math.ceil(target_width/multiple)*multiple)
    target_height=int(math.ceil(target_height/multiple)*multiple)
    if 'postScale' in recipe:
        scale=recipe['postScale']
        if not isinstance(scale,(int,float)) or isinstance(scale,bool) or not math.isfinite(scale) or scale<=0:
            raise ValueError('主体点选的下游缩放尺寸未完成审查。')
        # ImageScaleBy uses Python round(), then LTXVPreprocess crops odd
        # dimensions only when compression is enabled. The reviewed 0.5 scale
        # after a 32px-multiple resize always produces even dimensions.
        target_width=round(target_width*scale);target_height=round(target_height*scale)
        if min(target_width,target_height)<8 or target_width%2 or target_height%2:
            raise ValueError('主体点选的下游预处理尺寸未完成审查。')
    return {'width':target_width,'height':target_height,'node':recipe['node'],
            **({'bindDimensions':True} if 'postScale' in recipe else {}),
            **({'negativeTarget':recipe['negativeTarget']} if recipe.get('negativeTarget') else {})}

def public_asset(a):
    try:asset_file(a);available=True
    except HTTPException:available=False
    result=dict(id=a['id'],kind=a['kind'],name=a['name'],bytes=a['bytes'],src=f"/api/assets/{a['id']}/file",available=available)
    original_id=a.get('original_asset_id')
    if a.get('annotation_mode')=='mask' and isinstance(original_id,str) and re.fullmatch('[0-9a-f]{64}',original_id):
        try:
            original=asset(original_id);asset_file(original)
            original_available=original.get('kind')=='image'
        except HTTPException:original_available=False
        result.update(original_asset_id=original_id,annotation_mode='mask',original_available=original_available,
                      original_src=f'/api/assets/{original_id}/file' if original_available else '')
    return result

def public(j):
    from history_parameters import history_seed_values
    references=[]
    catalog_slots=[slot['id'] for slot in j.get('schema_spec',{}).get('media',[]) if slot['id'] in j.get('catalog_assets',{})]
    for index,id in enumerate(j.get('asset_ids',[])):
        try:reference=public_asset(asset(id))
        except HTTPException:reference=dict(id=id,available=False,kind='unknown',name='原素材缺失',src='')
        if index<len(catalog_slots):reference['catalogSlot']=catalog_slots[index]
        references.append(reference)
    recovered=history_seed_values(j)
    return {**{k:v for k,v in j.items() if k not in ['token','graph','download_items','schema_spec']},'outputs':historical_output_presentation(j),'request_token':j['token'],'references':references,**({'catalog_seed_values':recovered}if recovered else{})}

def public_graph(graph):
    """Keep execution credentials out of workflow downloads and video metadata."""
    graph=copy.deepcopy(graph)
    protected=set()
    def credential_source(node):
        if node in protected or node not in graph:return
        protected.add(node)
        for value in graph[node].get('inputs',{}).values():
            if isinstance(value,list) and len(value)==2 and isinstance(value[0],str):credential_source(value[0])
    for node in graph.values():
        for key,value in node.get('inputs',{}).items():
            if any(part in key.lower() for part in ('api_key','apikey','access_token','authorization','password','secret')) and isinstance(value,list) and len(value)==2:
                credential_source(str(value[0]))
    for node in protected:
        for key,value in graph[node].get('inputs',{}).items():
            if isinstance(value,str):graph[node]['inputs'][key]='[请填写自己的密钥]'
    def clean(value,key=''):
        name=key.lower()
        if any(part in name for part in ('api_key','apikey','access_token','authorization','password','secret')):
            return '[请填写自己的密钥]' if not isinstance(value,list) else value
        if isinstance(value,str) and re.fullmatch(r'sk-[A-Za-z0-9_-]{16,}',value):
            return '[请填写自己的密钥]'
        if isinstance(value,dict):return {k:clean(v,k) for k,v in value.items()}
        if isinstance(value,list):return [clean(v,key) for v in value]
        return value
    return clean(graph)

def ensure_remote(a):
    local=asset_file(a)
    try:
        if a.get('remote'):
            remote=Path(a['remote'])
            with requests.get(BASE+'/view',params={'filename':remote.name,'subfolder':remote.parent.as_posix() if str(remote.parent)!='.' else '', 'type':'input'},headers={'Range':'bytes=0-63'},stream=True,timeout=15) as response:
                if response.status_code in (200,206):return a
        with local.open('rb') as stream:
            response=requests.post(BASE+'/upload/image',files={'image':('yingxu-'+a['id'][:24]+local.suffix,stream,mimetypes.guess_type(str(local))[0])},data={'overwrite':'false'},timeout=(15,180))
        response.raise_for_status();out=response.json()
        a={**a,'remote':(out.get('subfolder','')+'/'+out['name']).lstrip('/')}
        with lock,database() as db:db.execute('UPDATE assets SET data=? WHERE id=?',(json.dumps(a,ensure_ascii=False),a['id']))
        return a
    except (requests.RequestException,ValueError,KeyError):
        raise HTTPException(502, '参考素材已保留，但无法送达算力卡。请确认卡在线后重试。')
def friendly(message):
    low=message.lower()
    if 'out of memory' in low or 'cuda error' in low:return '显存不足。请降低画面像素或时长、减少参考图，再重试。'
    if 'not in list' in low or 'not found' in low:return '算力卡缺少此任务依赖的模型或素材。请检查卡上的模型与上传文件后重试。'
    if 'connection' in low or 'timeout' in low:return '暂时无法连接算力卡。请确认卡已开机，恢复连接后本页会继续查询。'
    return '工作流执行失败：'+message[:500]+'。提示词和素材已保留，可修改参数后重试。'

MEDIA_KINDS={'.png':'image','.jpg':'image','.jpeg':'image','.webp':'image','.gif':'image',
             '.mp4':'video','.webm':'video','.mov':'video',
             '.wav':'audio','.mp3':'audio','.flac':'audio','.ogg':'audio','.m4a':'audio',
             '.txt':'text'}
def output_items(h,kind='video',output_nodes=None):
    found=[]
    seen=set()
    def retain(item,node_id):
        identity=tuple(item.get(key)for key in ('kind','filename','subfolder','type','text'))
        if identity in seen:return
        seen.add(identity);found.append({**item,'output_node':str(node_id)})
    nodes=h.get('outputs',{})
    if output_nodes is not None:nodes={str(k):nodes[str(k)] for k in output_nodes if str(k) in nodes}
    for node_id,node in nodes.items():
        for key in ('images','gifs','videos','audio','audios','files'):
            entries=node.get(key,[])
            if isinstance(entries,dict):entries=[entries]
            if not isinstance(entries,list):continue
            for value in entries:
                suffix=Path(value.get('filename','')).suffix.lower() if isinstance(value,dict) else ''
                accepted_types=('output','temp') if output_nodes is not None else ('output',)
                if isinstance(value,dict) and suffix in MEDIA_KINDS and value.get('type') in accepted_types:
                    item={**value,'kind':MEDIA_KINDS[suffix]}
                    retain(item,node_id)
        if kind=='text' or output_nodes is not None:
            for key in ('text','string','strings'):
                entries=node.get(key,[])
                if isinstance(entries,str):entries=[entries]
                if not isinstance(entries,list):continue
                texts=[v for v in entries if isinstance(v,str)]
                if texts:
                    text='\n'.join(texts)
                    if len(text.encode('utf-8'))>1024*1024:raise ValueError('返回的文字超过允许大小。')
                    item={'kind':'text','text':text,'filename':str(node_id)+'.txt','type':'output'}
                    retain(item,node_id)
    return found


def reviewed_output_metadata(spec,graph):
    """Labels describe reviewed execution chains, never filenames or order."""
    def matches(node_id,class_type,**links):
        node=graph.get(node_id,{})
        return node.get('class_type')==class_type and all(node.get('inputs',{}).get(key)==value for key,value in links.items())
    workflow_id=spec.get('id')
    if workflow_id=='local-card-90':
        original=matches('11','LoadImage')
        seedvr_models=matches('14','SeedVR2LoadDiTModel')and matches('15','SeedVR2LoadVAEModel')
        tiled=(original and matches('86','TTP_Image_Assy',tiles=['59',0],positions=['87',1],
                                    original_size=['87',2],grid_size=['87',3]) and
               matches('59','easy cleanGpuUsed',anything=['70',0]) and
               matches('70','ImageListToImageBatch',images=['68',0]) and
               matches('68','VAEDecode',samples=['91',0],vae=['63',0]) and
               matches('91','KSampler',model=['109',0],latent_image=['67',0]) and
               matches('67','VAEEncode',pixels=['65',0],vae=['63',0]) and
               matches('65','easy imageBatchToImageList',image=['87',0]) and
               matches('87','TTP_Image_Tile_Batch',image=['88',0]) and
               matches('88','ImageScaleToTotalPixels',image=['83',0]) and
               matches('83','ImageUpscaleWithModel',image=['75',0]) and
               matches('75','LayerUtility: ImageScaleByAspectRatio V2',image=['11',0]) and
               matches('109','ModelPatchTorchSettings',model=['61',0]) and
               matches('61','ModelSamplingSD3',model=['80',0]) and
               matches('80','PathchSageAttentionKJ',model=['78',0]) and
               matches('78','LoraLoaderModelOnly',model=['77',0]) and
               matches('77','UNETLoader')and
               graph['77'].get('inputs',{}).get('unet_name')=='smooth/Smooth Mix Wan t2v 2.2 low v2.safetensors')
        rules={
            '16':(original and seedvr_models and matches('16','PreviewImage',images=['13',0]) and
                  matches('13','SeedVR2VideoUpscaler',image=['11',0],dit=['14',0],vae=['15',0]),
                  '放大结果 A · SeedVR','result',0),
            '128':(tiled and seedvr_models and matches('128','PreviewImage',images=['126',0]) and
                   matches('126','SeedVR2VideoUpscaler',image=['86',0],dit=['14',0],vae=['15',0]),
                   '放大结果 B · 重绘后 SeedVR','result',1),
            '92':(tiled and matches('92','PreviewImage',images=['86',0]),'Wan 重绘放大结果','result',2),
            '115':(original and matches('115','PreviewImage',images=['11',0]),'原图','control',3),
        }
    elif workflow_id=='local-card-95':
        decoded=(matches('11','VAEDecode',samples=['8',0]) and matches('8','KSampler',latent_image=['9',0]) and
                 matches('9','EmptySD3LatentImage'))
        original=matches('4','ImageStitch',image1=['23',0]) and matches('23','LoadImage')
        rules={
            '24':(decoded and matches('24','SaveImage',images=['11',0]),'编辑结果','result',0),
            '13':(decoded and original and matches('13','SaveImage',images=['5',0]) and
                  matches('5','ImageStitch',image1=['4',0],image2=['11',0]),
                  '对比拼图 · 原图 / 编辑结果','comparison',1),
        }
    elif workflow_id=='local-card-96':
        decoded=(matches('19','VAEDecode',samples=['10',0]) and matches('10','KSampler',latent_image=['11',0]) and
                 matches('11','EmptySD3LatentImage'))
        references=(matches('5','ImageStitch',image1=['8',0],image2=['1',0]) and
                    matches('8','LoadImage') and matches('1','LoadImage'))
        rules={
            '18':(decoded and matches('18','SaveImage',images=['19',0]),'编辑结果','result',0),
            '22':(decoded and references and matches('22','SaveImage',images=['6',0]) and
                  matches('6','ImageStitch',image1=['5',0],image2=['19',0]),
                  '对比拼图 · 两张参考图 / 编辑结果','comparison',1),
        }
    elif workflow_id=='local-card-133':
        subject=matches('11','LayerMask: BiRefNetUltraV2',image=['12',0]) and matches('12','LoadImage')
        rules={
            '18':(subject and matches('18','PreviewImage',images=['11',0]),'透明主体','result',0),
            '17':(subject and matches('17','PreviewImage',images=['16',0]) and
                  matches('16','LayerUtility: ImageRemoveAlpha',RGBA_image=['11',0],mask=['11',1],
                          fill_background=True,background_color=['19',0]) and
                  matches('19','LayerUtility: ColorPicker',color='#ffffff',mode='HEX'),
                  '白底图','result',1),
        }
    elif workflow_id=='local-card-30':
        if spec.get('source_hash')!='1d4bb89d8e5531a50b800e5d1228ac9a230091b4df1ab7bf49e9e4062fc115c0':return {}
        source=(matches('128','VHS_LoadVideoFFmpeg') and matches('62','VHS_VideoInfo',video_info=['128',3]) and
                matches('10','ImageFromBatch',image=['128',0]) and
                matches('20','RepeatImageBatch',image=['10',0],amount=['24',0]) and
                matches('19','ImageBatch',image1=['20',0],image2=['128',0]))
        poses=(source and matches('74','DrawViTPose') and matches('75','SDPoseOODProcessor',images=['19',0]) and
               matches('106','RenderNLFPoses') and
               matches('142','easy anythingIndexSwitch',value0=['74',0],value1=['75',0],value2=['106',0]))
        decoded=(poses and matches('39','WanVideoAnimateEmbeds',pose_images=['142',0]) and
                 matches('173','LayerUtility: PurgeVRAM V2',anything=['39',0]) and
                 matches('35','WanVideoSampler',image_embeds=['173',0]) and
                 matches('48','WanVideoDecode',samples=['35',0]) and
                 matches('12','ImageFromBatch',image=['48',0],batch_index=['24',0],length=['62',6]))
        roles={
            '36':(decoded and matches('36','VHS_VideoCombine',images=['12',0],audio=['128',2]),'生成视频','result'),
            '147':(poses and matches('147','VHS_VideoCombine',images=['142',0]),'姿态控制预览','control'),
        }
        return {node:dict(label=label,role=role)for node,(valid,label,role)in roles.items()if valid}
    elif workflow_id=='local-card-124':
        if spec.get('source_hash')!='539ebf8eb167f3571a11bb9cddfc08a819b6f906aa4f80907cbe320b61dd436e':return {}
        references=(matches('78','LoadImage') and matches('79','LoadImage') and
                    matches('15','ImageResizeKJv2',image=['78',0]) and matches('48','ImageResizeKJv2',image=['79',0]))
        first_last=(references and matches('60','WanFirstLastFrameToVideo',start_image=['15',0],end_image=['48',0]) and
                    matches('64','KSamplerAdvanced',positive=['60',0],negative=['60',1],latent_image=['60',2]) and
                    matches('61','KSamplerAdvanced',positive=['60',0],negative=['60',1],latent_image=['64',0]) and
                    matches('62','VAEDecode',samples=['61',0]))
        inbetween=(references and matches('44','WanFirstMiddleLastFrameToVideo',start_image=['15',0],end_image=['48',0]) and
                   matches('18','KSamplerAdvanced',positive=['44',0],negative=['44',2],latent_image=['44',3]) and
                   matches('19','KSamplerAdvanced',positive=['44',1],negative=['44',2],latent_image=['18',0]) and
                   matches('16','VAEDecode',samples=['19',0]))
        roles={
            '65':(first_last and matches('65','VHS_VideoCombine',images=['62',0]),'首尾帧生成结果','result'),
            '34':(inbetween and matches('34','VHS_VideoCombine',images=['16',0]),'补间生成结果','result'),
        }
        return {node:dict(label=label,role=role)for node,(valid,label,role)in roles.items()if valid}
    elif workflow_id in ('local-card-22','local-card-23','local-card-24','local-card-25',
                          'local-card-26','local-card-27','local-card-28','local-card-116'):
        return _reviewed_character_video_output_metadata(workflow_id,matches)
    elif workflow_id in ('local-card-40','local-card-43','local-card-44','local-card-45','local-card-46',
                         'local-card-48','local-card-49','local-card-50','local-card-60','local-card-126'):
        return _reviewed_video_edit_output_metadata(workflow_id,matches)
    elif workflow_id!='local-card-51':
        return {}
    else:
        return _reviewed_ltx_output_metadata(graph,matches,spec)
    return {node:dict(label=label,role=role,display_order=order)for node,(valid,label,role,order)in rules.items()if valid}


def _reviewed_character_video_output_metadata(workflow_id,matches):
    """Describe inspected video chains without changing registered file order."""
    rules={}
    if workflow_id in ('local-card-22','local-card-23'):
        nodes={
            'local-card-22':dict(source='112',scaled='602',info='101',mask='197',drive='79',ref_track='81',
                                 reference='108',reference_scale='89',decode='43',sampler='41',settings='40',
                                 embeds='347',pure='119',original='86',mask_output='200'),
            'local-card-23':dict(source='552',scaled='560',info='555',mask='527',drive='503',ref_track='504',
                                 reference='574',reference_scale='519',decode='465',sampler='489',settings='480',
                                 embeds='529',pure='508',original='491',mask_output='475'),
        }[workflow_id]
        source=(matches(nodes['source'],'VHS_LoadVideo') and
                matches(nodes['scaled'],'LayerUtility: ImageScaleByAspectRatio V2',image=[nodes['source'],0]) and
                matches(nodes['info'],'VHS_VideoInfoLoaded',video_info=[nodes['source'],3]))
        decoded=(source and matches(nodes['decode'],'WanAnimatePlus Decode',samples=[nodes['sampler'],0]) and
                 matches(nodes['sampler'],'WanAnimatePlus SamplerFromSettings',sampler_inputs=[nodes['settings'],0]) and
                 matches(nodes['settings'],'WanAnimatePlus SamplerSettings',image_embeds=[nodes['embeds'],0]) and
                 matches(nodes['embeds'],'WanAnimatePlus SCAIL_2 Embeds'))
        segmented=(source and matches(nodes['mask'],'SCAIL2ColoredMaskV2',
                                      driving_track_data=[nodes['drive'],0],ref_track_data=[nodes['ref_track'],0]) and
                   matches(nodes['drive'],'SAM3_VideoTrack',images=[nodes['scaled'],0]) and
                   matches(nodes['ref_track'],'SAM3_VideoTrack',images=[nodes['reference_scale'],0]) and
                   matches(nodes['reference_scale'],'ImageResizeKJv2',image=[nodes['reference'],0]) and
                   matches(nodes['reference'],'LoadImage'))
        rules={
            nodes['pure']:(decoded and matches(nodes['pure'],'VHS_VideoCombine',images=[nodes['decode'],0]),
                           '生成视频','result'),
            nodes['original']:(source and matches(nodes['original'],'VHS_VideoCombine',images=[nodes['scaled'],0]),
                               '原片预览','control'),
            nodes['mask_output']:(segmented and matches(nodes['mask_output'],'VHS_VideoCombine',images=[nodes['mask'],0]),
                                  '主体分割预览','mask'),
        }
    elif workflow_id in ('local-card-24','local-card-25','local-card-26','local-card-27','local-card-116'):
        nodes={
            'local-card-24':dict(source='3751',scaled='3727',size='3705',pose='3706',detector='3704',
                                pure='3736',pure_input='3763',trim='3763',decoded_size='3659',decode='3657',sampler='3739',
                                face='3667',comparison='3701',concat='3647',ref_concat='3648',ref_scale='3697',reference='3737',
                                control='3683',draw_mask='3673',switch='3686',mask='3634',grow='3643'),
            'local-card-25':dict(source='653',scaled='626',size='604',pose='605',detector='603',
                                pure='635',pure_input='558',trim='664',decode='556',sampler='638',
                                face='566',comparison='600',concat='546',ref_concat='547',ref_scale='596',reference='636',
                                control='582',draw_mask='572',switch='585',mask='533',grow='542'),
            'local-card-26':dict(source='483',scaled='456',size='434',pose='435',detector='433',
                                pure='465',pure_input='388',trim='552',decode='386',sampler='468',
                                face='396',comparison='430',concat='376',ref_concat='377',ref_scale='426',reference='466',
                                pose_output='493',draw_pose='438'),
            'local-card-27':dict(source='783',scaled='756',size='734',pose='735',detector='733',
                                pure='765',pure_input='688',trim='788',decode='686',sampler='768',
                                face='696',comparison='730',concat='676',ref_concat='677',ref_scale='726',reference='766',
                                control='712',draw_mask='702',switch='715',mask='663',grow='672'),
            'local-card-116':dict(source='783',scaled='756',size='734',pose='735',detector='733',
                                 pure='765',pure_input='688',trim='785',decode='686',sampler='768',
                                 face='696',comparison='730',concat='676',ref_concat='677',ref_scale='726',reference='766',
                                 control='712',draw_mask='702',switch='715',mask='663',grow='672'),
        }[workflow_id]
        source=(matches(nodes['source'],'VHS_LoadVideo') and
                matches(nodes['scaled'],'LayerUtility: ImageScaleByAspectRatio V2',image=[nodes['source'],0]))
        pose=(source and matches(nodes['size'],'GetImageSizeAndCount',image=[nodes['scaled'],0]) and
              matches(nodes['pose'],'PoseAndFaceDetection',images=[nodes['size'],0],model=[nodes['detector'],0]) and
              matches(nodes['detector'],'OnnxDetectionModelLoader'))
        decoded=(source and matches(nodes['decode'],'WanVideoDecode',samples=[nodes['sampler'],0]) and
                 matches(nodes['sampler'],'WanVideoSampler'))
        if nodes.get('decoded_size'):
            trimmed=(decoded and matches(nodes['decoded_size'],'GetImageSizeAndCount',image=[nodes['decode'],0]) and
                     matches(nodes['trim'],'ImageFromBatch',image=[nodes['decoded_size'],0],length=[nodes['source'],1]))
        else:
            trimmed=(decoded and matches(nodes['trim'],'ImageFromBatch',image=[nodes['decode'],0],length=[nodes['source'],1]) and
                     matches(nodes['pure_input'],'GetImageSizeAndCount',image=[nodes['trim'],0]))
        references=(pose and matches(nodes['ref_concat'],'ImageConcatMulti',
                                    image_1=[nodes['ref_scale'],0],image_2=[nodes['pose'],1]) and
                    matches(nodes['ref_scale'],'ImageResizeKJv2',image=[nodes['reference'],0]) and
                    matches(nodes['reference'],'LoadImage'))
        rules={
            nodes['pure']:(trimmed and matches(nodes['pure'],'VHS_VideoCombine',images=[nodes['pure_input'],0]),
                           '生成视频','result'),
            nodes['face']:(pose and matches(nodes['face'],'VHS_VideoCombine',images=[nodes['pose'],1]),
                           '面部控制预览','control'),
            nodes['comparison']:(trimmed and references and matches(nodes['comparison'],'VHS_VideoCombine',images=[nodes['concat'],0]) and
                                  matches(nodes['concat'],'ImageConcatMulti',image_1=[nodes['pure_input'],0],image_2=[nodes['ref_concat'],0]),
                                  '对比预览 · 参考图 / 面部控制 / 生成结果','comparison'),
        }
        if nodes.get('control'):
            control=(source and matches(nodes['draw_mask'],'DrawMaskOnImage',image=[nodes['switch'],0],mask=[nodes['mask'],0]) and
                     matches(nodes['switch'],'Any Switch (rgthree)',any_02=[nodes['scaled'],0]) and
                     matches(nodes['mask'],'BlockifyMask',masks=[nodes['grow'],0]) and matches(nodes['grow'],'GrowMask'))
            rules[nodes['control']]=(control and matches(nodes['control'],'VHS_VideoCombine',images=[nodes['draw_mask'],0]),
                                     '服装控制预览' if workflow_id in ('local-card-27','local-card-116') else '主体控制预览','control')
        if nodes.get('pose_output'):
            rules[nodes['pose_output']]=(pose and matches(nodes['pose_output'],'VHS_VideoCombine',images=[nodes['draw_pose'],0]) and
                                         matches(nodes['draw_pose'],'DrawViTPose',pose_data=[nodes['pose'],0]),'姿态骨架预览','control')
    elif workflow_id=='local-card-28':
        source=(matches('427','VHS_LoadVideo') and matches('440','LayerUtility: ImageScaleByAspectRatio V2',image=['427',0]))
        decoded=(source and matches('539','ImageFromBatch',image=['535',0],length=['427',1]) and
                 matches('535','ImpactConditionalBranch',cond=['518',0],tt_value=['529',0],ff_value=['520',0]) and
                 matches('529','ImageListToImageBatch',images=['506',0]) and
                 matches('506','easy forLoopEnd',flow=['505',0],initial_value1=['295',0]) and
                 matches('505','easy forLoopStart',initial_value1=['510',0]) and
                 matches('295','ImageBatch',image1=['505',2],image2=['292',0]) and
                 matches('292','ImageFromBatch',image=['290',0]) and matches('290','VAEDecode',samples=['291',0]) and
                 matches('291','TrimVideoLatent',samples=['294',0]) and matches('294','KSampler') and
                 matches('520','ImageFromBatch',image=['510',1],length=['427',1]) and
                 matches('510','easy ab',**{'A or B':['518',0],'in':['285',0]}) and
                 matches('285','VAEDecode',samples=['284',0]) and
                 matches('284','TrimVideoLatent',samples=['288',0]) and matches('288','KSampler'))
        upscaled=(decoded and matches('354','ImageUpscaleWithModelBatched',images=['548',0],upscale_model=['311',0]) and
                  matches('548','easy cleanGpuUsed',anything=['546',0]) and matches('546','easy clearCacheAll',anything=['539',0]) and
                  matches('311','Upscale Model Loader'))
        pose=(source and matches('399','PoseAndFaceDetection',images=['395',0],model=['394',0]) and
              matches('395','GetImageSizeAndCount',image=['440',0]) and matches('394','OnnxDetectionModelLoader'))
        control=(source and matches('368','DrawMaskOnImage',image=['380',0],mask=['332',0]) and
                 matches('380','Any Switch (rgthree)',any_02=['440',0]) and
                 matches('332','BlockifyMask',masks=['339',0]) and matches('339','GrowMask'))
        rules={
            '508':(decoded and matches('508','VHS_VideoCombine',images=['539',0]),'生成视频 · 首次结果','result'),
            '358':(upscaled and matches('358','VHS_VideoCombine',images=['354',0]),'生成视频 · 放大','result'),
            '345':(upscaled and matches('317','RIFE VFI',frames=['354',0]) and
                   matches('345','VHS_VideoCombine',images=['317',0]),'生成视频 · 插帧','result'),
            '377':(control and matches('377','VHS_VideoCombine',images=['368',0]),'主体控制预览','control'),
            '398':(pose and matches('398','VHS_VideoCombine',images=['399',1]),'面部控制预览','control'),
        }
    return {node:dict(label=label,role=role)for node,(valid,label,role)in rules.items()if valid}


def _reviewed_video_edit_output_metadata(workflow_id,matches):
    """Only inspected pure/comparison chains receive roles; keep file order."""
    if workflow_id=='local-card-40':
        source=(matches('27','VHS_LoadVideo') and matches('17','ImageFromBatch',image=['27',0]) and
                matches('38','LayerUtility: ImageScaleByAspectRatio V2',image=['17',0]))
        decoded=(source and matches('36','LoadImage') and
                 matches('33','BerniniStudio',source_video=['38',0],image0=['36',0]) and
                 matches('26','SamplerCustom',positive=['33',0],negative=['33',1],latent_image=['33',2]) and
                 matches('31','SamplerCustom',positive=['33',0],negative=['33',1],latent_image=['26',0]) and
                 matches('18','VAEDecode',samples=['31',0]))
        rules={
            '40':(decoded and matches('40','VHS_VideoCombine',images=['18',0],audio=['27',2]),
                  '生成视频','result'),
            '42':(decoded and matches('42','VHS_VideoCombine',images=['41',0],audio=['27',2]) and
                  matches('41','ImageConcanate',image1=['20',0],image2=['36',0],direction='down') and
                  matches('20','ImageConcanate',image1=['38',0],image2=['18',0],direction='right'),
                  '对比预览 · 原片 / 生成结果 / 参考图','comparison'),
        }
    elif workflow_id in ('local-card-43','local-card-48'):
        source=(matches('365','VHS_LoadVideo') and matches('496','ResizeImageMaskNode',input=['365',0]) and
                matches('478','ImageScaleBy',image=['496',0]) and matches('479','LTXVPreprocess',image=['478',0]))
        decoded=(source and matches('455','LTXVAddGuideMulti',**{'num_guides.image_1':['479',0]}) and
                 matches('500','SamplerCustomAdvanced') and matches('413','LTXVSeparateAVLatent',av_latent=['500',0]) and
                 matches('405','LTXVCropGuides',positive=['455',0],negative=['455',1],latent=['413',0]) and
                 matches('467','VAEDecode',samples=['405',2]))
        rules={
            '363':(decoded and matches('491','GetImageSizeAndCount',image=['467',0]) and
                   matches('363','VHS_VideoCombine',images=['491',0],audio=['365',2]),'编辑结果','result'),
            '362':(decoded and matches('436','ImageConcanate',image1=['479',0],image2=['467',0],direction='right') and
                   matches('362','VHS_VideoCombine',images=['436',0]),'对比预览 · 原片 / 编辑结果','comparison'),
        }
    elif workflow_id=='local-card-44':
        source=(matches('5099','VHS_LoadVideo') and
                matches('5158:5120','LayerUtility: ImageScaleByAspectRatio V2',image=['5099',0]) and
                matches('5158:5026','ResizeImageMaskNode',input=['5158:5120',0]) and
                matches('5158:5085','ResizeImageMaskNode',input=['5158:5026',0]))
        decoded=(source and matches('5158:5012','LTXAddVideoICLoRAGuide',image=['5158:5085',0]) and
                 matches('5102','SamplerCustomAdvanced') and
                 matches('5158:5112','LTXVSeparateAVLatent',av_latent=['5102',0]) and
                 matches('5158:5111','LTXVCropGuides',positive=['5158:5012',0],negative=['5158:5012',1],latent=['5158:5112',0]) and
                 matches('5158:5113','VAEDecodeTiled',samples=['5158:5111',2]))
        rules={
            '5069':(decoded and matches('5069','VHS_VideoCombine',images=['5158:5113',0],audio=['5099',2]),
                    '修复结果','result'),
            '5135':(decoded and matches('5158:5134','ImageConcanate',image1=['5099',0],image2=['5158:5113',0],direction='right') and
                    matches('5135','VHS_VideoCombine',images=['5158:5134',0],audio=['5099',2]),
                    '对比预览 · 原片 / 修复结果','comparison'),
        }
    elif workflow_id=='local-card-45':
        source=(matches('34','VHS_LoadVideo') and
                matches('50:26','LayerUtility: ImageScaleByAspectRatio V2',image=['34',0]) and
                matches('50:38','ResizeImageMaskNode',input=['50:26',0]) and
                matches('50:40','ResizeImageMaskNode',input=['50:38',0]))
        decoded=(source and matches('50:10','LTXAddVideoICLoRAGuide',image=['50:40',0]) and
                 matches('50:35','SamplerCustomAdvanced') and
                 matches('50:13','LTXVSeparateAVLatent',av_latent=['50:35',0]) and
                 matches('50:8','LTXVCropGuides',positive=['50:10',0],negative=['50:10',1],latent=['50:13',0]) and
                 matches('50:44','VAEDecodeTiled',samples=['50:8',2]))
        rules={
            '24':(decoded and matches('24','VHS_VideoCombine',images=['50:44',0],audio=['34',2]),
                  '编辑结果','result'),
            '37':(decoded and matches('50:28','ImageConcanate',image1=['34',0],image2=['50:44',0],direction='right') and
                  matches('37','VHS_VideoCombine',images=['50:28',0],audio=['34',2]),
                  '对比预览 · 原片 / 编辑结果','comparison'),
        }
    elif workflow_id=='local-card-46':
        source=(matches('5141','VHS_LoadVideo') and matches('5149','ImagePadKJ',image=['5141',0]) and
                matches('5167:5146','ResizeImageMaskNode',input=['5149',0]) and
                matches('5167:5147','ResizeImageMaskNode',input=['5167:5146',0]))
        decoded=(source and matches('5126','SamplerCustomAdvanced') and
                 matches('5167:5124','LTXVSeparateAVLatent',av_latent=['5126',0]) and
                 matches('5167:5123','LTXVCropGuides',positive=['5167:5118',0],negative=['5167:5118',1],latent=['5167:5124',0]) and
                 matches('5167:5132','VAEDecodeTiled',samples=['5167:5123',2]) and
                 matches('5167:5129','Color Correct (mtb)',image=['5167:5132',0]) and
                 matches('5167:5130','Switch image [Crystools]',on_true=['5167:5129',0],on_false=['5167:5132',0]))
        rules={
            '5104':(decoded and matches('5104','VHS_VideoCombine',images=['5167:5130',0],audio=['5141',2]),
                    '扩图结果','result'),
            '5131':(decoded and matches('5167:5133','ImageConcanate',image1=['5167:5130',0],image2=['5167:5147',0],direction='left') and
                    matches('5131','VHS_VideoCombine',images=['5167:5133',0],audio=['5141',2]),
                    '对比预览 · 原片 / 扩图结果','comparison'),
        }
    elif workflow_id=='local-card-49':
        source=(matches('363','VHS_LoadVideo') and matches('453','ResizeImageMaskNode',input=['363',0]) and
                matches('448','ImageScaleBy',image=['453',0]) and matches('449','LTXVPreprocess',image=['448',0]))
        decoded=(source and matches('440','LTXVAddGuideMulti',**{'num_guides.image_1':['449',0]}) and
                 matches('455','SamplerCustomAdvanced') and matches('415','LTXVSeparateAVLatent',av_latent=['455',0]) and
                 matches('456','LTXVCropGuides',positive=['440',0],negative=['440',1],latent=['415',0]) and
                 matches('394','VAEDecode',samples=['456',2]))
        rules={
            '358':(decoded and matches('472','GetImageSizeAndCount',image=['394',0]) and
                   matches('358','VHS_VideoCombine',images=['472',0],audio=['363',2]),'换衣结果','result'),
            '357':(decoded and matches('431','ImageConcanate',image1=['449',0],image2=['394',0],direction='right') and
                   matches('357','VHS_VideoCombine',images=['431',0]),'对比预览 · 原片 / 换衣结果','comparison'),
        }
    elif workflow_id=='local-card-50':
        source=(matches('460','VHS_LoadVideo') and matches('462','ImageResizeKJv2',image=['460',0]))
        first=(source and matches('680','LTXMultipleControls',guide_video=['462',0]) and
               matches('470','SamplerCustomAdvanced',latent_image=['680',3]) and
               matches('475','VAEDecodeTiled',samples=['470',0]))
        refined=(first and matches('465','LTXVLatentUpsampler',samples=['470',0]) and
                 matches('472','LTXVCropGuides',positive=['680',1],negative=['680',2],latent=['465',0]) and
                 matches('474','LTXMultipleControls',positive=['472',0],negative=['472',1],latent=['472',2],guide_video=['475',0]) and
                 matches('437','SamplerCustomAdvanced',latent_image=['474',3]) and
                 matches('439','VAEDecodeTiled',samples=['437',0]))
        rules={
            '477':(first and matches('476','CreateVideo',images=['475',0],audio=['460',2]) and
                   matches('477','SaveVideo',video=['476',0]),'编辑结果 · 首次','result'),
            '75':(refined and matches('441','CreateVideo',images=['439',0],audio=['460',2]) and
                  matches('75','SaveVideo',video=['441',0]),'编辑结果 · 放大精修','result'),
            '491':(first and matches('481','AddLabel',image=['462',0]) and matches('482','AddLabel',image=['475',0]) and
                   matches('480','ImageConcatMulti',image_1=['481',0],image_2=['482',0],direction='right') and
                   matches('600','AddLabel',image=['480',0]) and
                   matches('491','VHS_VideoCombine',images=['600',0],audio=['460',2]),
                   '对比预览 · 原片 / 首次结果','comparison'),
        }
    elif workflow_id=='local-card-60':
        source=(matches('359','VHS_LoadVideo') and matches('360','GetImageSizeAndCount',image=['359',0]) and
                matches('362','LayerUtility: ImageScaleByAspectRatio V2',image=['360',0]) and
                matches('361','GetImageSizeAndCount',image=['362',0]))
        decoded=(source and matches('14','SamplerCustomAdvanced') and
                 matches('22','LTXVSeparateAVLatent',av_latent=['14',0]) and matches('45','VAEDecode',samples=['22',0]))
        rules={
            '347':(decoded and matches('347','VHS_VideoCombine',images=['45',0],audio=['359',2]),'修复结果','result'),
            '330':(decoded and matches('332','ImageConcatMulti',inputcount=2,image_1=['361',0],image_2=['45',0],direction='right') and
                   matches('330','VHS_VideoCombine',images=['332',0],audio=['359',2]),'对比预览 · 原片 / 修复结果','comparison'),
        }
    elif workflow_id=='local-card-126':
        decoded=(matches('28','WanVaceToVideo',control_video=['34',0],control_masks=['34',1]) and
                 matches('34','WanVideoVACEStartToEndFrame',start_image=['52',0],end_image=['54',0]) and
                 matches('8','KSampler',positive=['28',0],negative=['28',1],latent_image=['28',2]) and
                 matches('11','VAEDecode',samples=['8',0]))
        upscaled=(decoded and matches('71','ImageUpscaleWithModelBatched',images=['11',0]))
        rules={
            '39':(decoded and matches('39','VHS_VideoCombine',images=['11',0]),'生成视频 · 原始结果','result'),
            '72':(upscaled and matches('72','VHS_VideoCombine',images=['71',0]),'生成视频 · 放大','result'),
            '63':(upscaled and matches('62','RIFE VFI',frames=['71',0]) and
                  matches('63','VHS_VideoCombine',images=['62',0]),'生成视频 · 放大插帧','result'),
        }
    else:return {}
    return {node:dict(label=label,role=role)for node,(valid,label,role)in rules.items()if valid}


def _reviewed_ltx_output_metadata(graph,matches,spec=None):
    """Keep the separately reviewed local-card-51 output-chain checks intact."""
    first_images,refined_images=['989',0],['968',0]
    # Retain historical labels, while recognizing only the complete, exact
    # source-pinned tracked-region adaptation. A partial or changed mask chain
    # must not inherit the reviewed output roles.
    from region_preservation import (preserve_region_output,VIDEO_REGION_FIRST,
                                     VIDEO_REGION_REFINED)
    if spec and any(n in graph for n in (VIDEO_REGION_FIRST,VIDEO_REGION_REFINED)):
        verified=copy.deepcopy(graph)
        try:
            preservation=preserve_region_output(spec,verified)
        except ValueError:
            preservation=None
        if preservation and verified==graph:
            first_images,refined_images=[VIDEO_REGION_FIRST,0],[VIDEO_REGION_REFINED,0]
    first=(matches('989','VAEDecode',samples=['1004',2]) and
           matches('1004','LTXVCropGuides',latent=['1003',0]) and
           matches('1003','LTXVSeparateAVLatent',av_latent=['1009',0]) and
           matches('1009','SamplerCustomAdvanced'))
    refined=(first and matches('968','VAEDecodeTiled',samples=['966',2]) and
             matches('966','LTXVCropGuides',latent=['965',0]) and
             matches('965','LTXVSeparateAVLatent',av_latent=['972',0]) and
             matches('972','SamplerCustomAdvanced',latent_image=['974',0]) and
             matches('974','LTXVConcatAVLatent',video_latent=['988',2]) and
             matches('988','LTXVAddGuideMulti',latent=['980',0]) and
             matches('980','LTXVLatentUpsampler',samples=['1004',2]))
    rules={
        '948':(refined and matches('948','SaveVideo',video=['944',0]) and matches('944','CreateVideo',images=refined_images),
               '生成视频 · 放大精修','result',0),
        '949':(first and matches('949','SaveVideo',video=['953',0]) and matches('953','CreateVideo',images=first_images),
               '生成视频 · 首次结果','result',1),
        '939':(refined and matches('939','VHS_VideoCombine',images=['945',0]) and
               matches('945','ImageConcanate',image1=['942',0],image2=refined_images) and
               matches('942','ImageConcanate',image1=['1057',0],image2=['1063',0]),
               '对比预览 · 原片 / 控制图 / 放大精修','comparison',2),
        '955':(first and matches('955','VHS_VideoCombine',images=['962',0]) and
               matches('962','ImageConcanate',image1=['961',0],image2=first_images) and
               matches('961','ImageConcanate',image1=['1057',0],image2=['1063',0]),
               '对比预览 · 原片 / 控制图 / 首次结果','comparison',3),
        '1049':(matches('1049','VHS_VideoCombine',images=['1063',0]) and
                matches('1063','ImageCompositeFromMaskBatch+',image_from=['1057',0],mask=['1069',0]) and
                matches('1069','BlockifyMask',masks=['1080',0]) and matches('1080','GrowMaskWithBlur',mask=['1062',0]) and
                matches('1062','SeCVideoSegmentation'),
                '控制视频预览','control',4),
        '1048':(matches('1048','VHS_VideoCombine',images=['1033',0]) and
                matches('1033','MaskToImage',mask=['1062',0]) and matches('1062','SeCVideoSegmentation'),
                '主体掩膜预览','mask',5),
    }
    return {node:dict(label=label,role=role,display_order=order)for node,(valid,label,role,order)in rules.items()if valid}


def present_outputs(j,items,outputs):
    """Pure metadata migration: retain output IDs, URLs and on-disk numbering."""
    spec=j.get('schema_spec') or manifest(j['workflow_id']) or schema_adapters.manifest(j['workflow_id']) or {}
    metadata=reviewed_output_metadata(spec,j.get('graph',{}))
    by_id={j['id']+'o'+str(index):item for index,item in enumerate(items)}
    result=[]
    for output in outputs:
        item=by_id.get(output['id']);copy_output=copy.deepcopy(output)
        if item:
            copy_output['output_node']=item['output_node']
            copy_output.update(metadata.get(item['output_node'],{}))
        result.append(copy_output)
    if metadata and spec.get('id')not in ('local-card-30','local-card-124'):
        result.sort(key=lambda output:output.get('display_order',99))
    return result


def historical_output_presentation(j):
    """Read-only labels from saved graph/node identity, with receipt fallback."""
    outputs=j.get('outputs',[])
    if not outputs or j.get('workflow_id')not in ('local-card-22','local-card-23','local-card-24','local-card-25',
                                                'local-card-26','local-card-27','local-card-28','local-card-30','local-card-116','local-card-124',
                                                'local-card-40','local-card-43','local-card-44','local-card-45','local-card-46',
                                                'local-card-48','local-card-49','local-card-50','local-card-60','local-card-126',
                                                'local-card-51','local-card-90','local-card-95','local-card-96','local-card-133'):return outputs
    spec=j.get('schema_spec')or manifest(j['workflow_id'])or schema_adapters.manifest(j['workflow_id'])or{}
    metadata=reviewed_output_metadata(spec,j.get('graph',{}))
    if not metadata:return outputs
    if all(isinstance(output.get('output_node'),str)for output in outputs):
        result=copy.deepcopy(outputs)
        for output in result:output.update(metadata.get(output['output_node'],{}))
        if spec.get('id')in ('local-card-30','local-card-124'):return result
        return sorted(result,key=lambda output:output.get('display_order',99))
    try:
        receipt=json.loads((PRIVATE/'receipts'/f'{j["id"]}.json').read_text('utf-8'))
        items=output_items(receipt,spec.get('output','video'),spec.get('outputs')if j.get('schema_spec')else None)
    except (OSError,ValueError,TypeError,AttributeError):
        return outputs
    return present_outputs(j,items,outputs)


def reviewed_translation_failure(j,h):
    """Recognize a known empty translator receipt, not a missing/unknown receipt."""
    spec=j.get('schema_spec') or {}
    if (j.get('workflow_id')!='local-card-93' or
        spec.get('source_hash')!='45c4103740959e1e7890af7a8a25e2292c67720682020f5387aa637697c89970'):
        return None
    graph=j.get('graph') or {}
    def matches(node,kind,**inputs):
        value=graph.get(node,{})
        return value.get('class_type')==kind and all(value.get('inputs',{}).get(k)==v for k,v in inputs.items())
    prompt=graph.get('71',{}).get('inputs',{}).get('prompt')
    encoding=graph.get('10',{})
    known_encoder=(matches('10','TextEncodeQwenImageEdit',prompt=['82',0]) or
        (matches('10','TextEncodeQwenImageEditPlus',prompt=['82',0],image1=['103',0]) and
         any(record.get('id')=='review73-qwen2511-reference-encoding' for record in
             encoding.get('_meta',{}).get('yingxu_execution_repairs',[]))))
    if not (isinstance(prompt,str) and prompt.strip() and
            matches('71','CR Prompt Text') and
            matches('76','DeepTranslatorTextNode',text=['71',0],to_translate='english') and
            matches('82','ShowText|pysssss',text=['76',0]) and
            known_encoder):
        return None
    receipt_outputs=h.get('outputs')
    if not isinstance(receipt_outputs,dict):return None
    receipt_text=receipt_outputs.get('82')
    if not isinstance(receipt_text,dict):return None
    texts=receipt_text.get('text')
    if isinstance(texts,list) and texts and all(isinstance(text,str) and not text.strip() for text in texts):
        return '描述翻译失败，未得到有效提示词。请将描述语言设为“英文直接使用”，填写英文描述后重试。素材与返回文件已保留。'
    return None


def reviewed_compiler_failure(j,h):
    """A source compiler's explicit error is not a successful creative result."""
    spec=j.get('schema_spec') or {}
    reviewed={'local-card-68':'87aeca2157dafa9dddc059b0bb3658f90c302332e32dca509b133caa3e8e04b9',
              'local-card-117':'c167d210db8f5270d0b760f5e0bb330f89217d34ba48b7e4d4b737ddfc18b6bf'}
    wid=j.get('workflow_id')
    if wid not in reviewed or spec.get('source_hash')!=reviewed[wid]:
        return None
    graph=j.get('graph') or {}
    chain={'273':('VisionAPIDirect',{'prompt':['270',0],'system_prompt':['274',0]}),
           '276':('ShowText|pysssss',{'text':['273',0]}),
           '265':('Any Switch (rgthree)',{'any_01':['276',0],'any_02':['270',0]}),
           '253':('ShowText|pysssss',{'text':['265',0]})}
    if wid=='local-card-117':
        chain['273'][1].update(image=['264',0],video_frames=['272',0])
        chain['219']=('MiniMaxH3ReferenceToVideo',{'ref_videos.ref_video_0':['272',0],
                         'ref_images.ref_image_0':['229:91',0],'ref_video_audios.ref_video_audio_0':['269',2]})
    for nid,(kind,inputs) in chain.items():
        value=graph.get(nid,{})
        if value.get('class_type')!=kind or any(value.get('inputs',{}).get(k)!=v for k,v in inputs.items()):return None
    outputs=h.get('outputs')
    if not isinstance(outputs,dict):return None
    for nid in ('273','276','253'):
        result=outputs.get(nid)
        if not isinstance(result,dict):continue
        text=result.get('text')
        if wid=='local-card-117' and isinstance(text,list):
            if any(isinstance(t,str) and 'COMPILATION_ERROR:' in t.upper() for t in text):
                return '视频编辑描述未通过编译。请按接口返回说明补充目标或参考素材；提示词、素材及返回文件已保留。'
            if text and all(isinstance(t,str) for t in text) and not any(t.strip() for t in text):
                return '视频编辑 API 返回了空描述，无法生成。提示词、素材及返回文件已保留。'
        elif isinstance(text,list) and any(isinstance(t,str) and t.lstrip().upper().startswith('COMPILATION_ERROR:') for t in text):
            return '姿势编辑描述未通过编译。请用文字说明手臂、手掌和身体的目标姿势；参考图仅提供外观。提示词、素材及返回文件已保留。'
    return None


def collect(j,h):
    spec=j.get('schema_spec') or manifest(j['workflow_id']) or schema_adapters.manifest(j['workflow_id']) or {}
    kind=spec.get('output','video')
    items=output_items(h,kind,spec.get('outputs') if j.get('schema_spec') else None)
    if not items:
        compiler_error=reviewed_compiler_failure(j,h)
        if compiler_error:
            receipt={k:h.get(k) for k in ['outputs','status']}
            (PRIVATE/'receipts'/f'{j["id"]}.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),'utf-8')
        update(j['id'],status='failed',stage=('视频编辑描述编译失败' if j['workflow_id']=='local-card-117' else '姿势描述编译失败') if compiler_error else '没有作品输出',error=compiler_error or '工作流已结束，但没有返回可保存的作品。请检查输出节点。',ended=time.time()*1000)
        return
    update(j['id'],status='downloading',stage='正在取回作品',error=None)
    folder=PRIVATE/'outputs'/j['id'];folder.mkdir(exist_ok=True)
    outputs=[]
    for i,item in enumerate(items):
        kind=item['kind']
        suffix=Path(item['filename']).suffix.lower();dest=folder/f'{i}{suffix}';tmp=dest.with_suffix('.part')
        if not dest.exists():
            if 'text' in item:tmp.write_bytes(item['text'].encode('utf-8'))
            else:
                with requests.get(BASE+'/view',params={k:item.get(k,'') for k in ['filename','subfolder','type']},stream=True,timeout=(15,120)) as r:
                    r.raise_for_status()
                    size=0
                    with tmp.open('wb') as f:
                        for chunk in r.iter_content(1024*1024):
                            size+=len(chunk)
                            limit=1 if kind=='text' else 100 if kind=='image' else 1024
                            if size>limit*1024*1024:raise ValueError('返回的作品超过允许大小。')
                            f.write(chunk)
            try:
                if kind=='image':
                    with Image.open(tmp) as preview:preview.verify()
                elif kind=='text':tmp.read_text('utf-8')
                elif kind=='video' and suffix=='.mp4':
                    with tmp.open('rb') as f:head=f.read(64)
                    if b'ftyp' not in head:raise ValueError('算力卡返回的文件不是有效 MP4，请检查视频保存节点。')
                else:
                    with av.open(str(tmp)) as container:
                        if not any(stream.type==kind for stream in container.streams):raise ValueError('算力卡返回的媒体格式不正确。')
            except (OSError,UnicodeError,av.error.FFmpegError) as error:raise ValueError('无法读取算力卡返回的作品。') from error
            tmp.replace(dest)
        embedded=kind=='video' and suffix=='.mp4'
        if embedded:embed_workflow(dest,public_graph(j['graph']))
        branch_labels={'local-card-12':['Anything-to-Real','Turn2Real','anime2real-semi']}
        label=branch_labels.get(j['workflow_id'],[])
        branch_name=None
        if j['workflow_id'] in ('local-card-11','local-card-17','local-card-18'):
            for name,display in [('Flux-9B','Flux 9B 结果'),('Qwen-AIO','Qwen 结果'),('single','单图结果'),('double','双图结果')]:
                if name in item.get('subfolder','').split('/') or item.get('filename','').startswith(name+'_'):
                    branch_name=display;break
        outputs.append(dict(workflow_embedded=embedded,id=j['id']+'o'+str(i),type=kind,src=f'/api/media/{j["id"]}/{i}{suffix}',poster='',duration=j.get('settings',{}).get('duration') if kind in ('video','audio') else None,bytes=dest.stat().st_size,label=branch_name or (label[i] if i<len(label) else None),**({'text':dest.read_text('utf-8')} if kind=='text' else {})))
    receipt={k:h.get(k) for k in ['outputs','status']}
    (PRIVATE/'receipts'/f'{j["id"]}.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),'utf-8')
    translation_error=reviewed_translation_failure(j,h)
    compiler_error=reviewed_compiler_failure(j,h)
    update(j['id'],status='failed' if translation_error or compiler_error else 'done',
           stage='描述翻译失败' if translation_error else ('视频编辑描述编译失败' if j['workflow_id']=='local-card-117' else '姿势描述编译失败') if compiler_error else '已保存作品',
           outputs=present_outputs(j,items,outputs),ended=time.time()*1000,error=translation_error or compiler_error)

def reconcile_unknown(j,q):
    candidates=[x for values in q.values() for x in values]
    for x in candidates:
        if len(x)>3 and x[3].get('yingxu_job_id')==j['id']:
            return update(j['id'],prompt_id=x[1],status='queued',stage='已找回任务',error=None)
    response=requests.get(BASE+'/history',params={'max_items':100},timeout=30);response.raise_for_status();h=response.json()
    for pid,v in h.items():
        p=v.get('prompt',[])
        if len(p)>3 and p[3].get('yingxu_job_id')==j['id']:
            return update(j['id'],prompt_id=pid,status='queued',stage='已找回任务',error=None)
    return j

def poll_once():
    active=[j for j in jobs() if j['status'] not in ['done','failed','cancelled','abandoned']]
    if not active:return
    q=requests.get(BASE+'/queue',timeout=15);q.raise_for_status();q=q.json()
    running={x[1] for x in q.get('queue_running',[])}
    pending=[x[1] for x in q.get('queue_pending',[])]
    for j in active:
        try:
            if not j.get('prompt_id'):
                if time.time()*1000-j['started']<90000 and not j.get('cancel_requested'):continue
                j=reconcile_unknown(j,q)
                if not j.get('prompt_id'):
                    update(j['id'],status='cancelling' if j.get('cancel_requested') else 'unknown',stage='取消请求已保存 · 等待找回任务编号' if j.get('cancel_requested') else '提交状态待确认',error='远端任务未确认，不会重复提交。可停止本地等待；这不代表远端已经停止。')
                    continue
            pid=j['prompt_id']
            h=requests.get(BASE+'/history/'+pid,timeout=20);h.raise_for_status();h=h.json().get(pid)
            if h:
                status=h.get('status',{})
                if status.get('status_str')=='error':
                    events=status.get('messages',[])
                    e=next((d for t,d in reversed(events) if t in ['execution_error','execution_interrupted']),{})
                    msg=e.get('exception_message','任务在算力卡上被中断')
                    (PRIVATE/'receipts'/f'{j["id"]}-error.json').write_text(json.dumps({'status':status},ensure_ascii=False,indent=2),'utf-8')
                    cancelled=job(j['id']).get('cancel_requested') and any(t=='execution_interrupted' for t,d in events)
                    update(j['id'],status='cancelled' if cancelled else 'failed',stage='已取消任务' if cancelled else '生成失败',error=None if cancelled else friendly(msg),ended=time.time()*1000)
                elif status.get('completed'):collect(j,h)
            elif pid in running:
                cancelling=job(j['id']).get('cancel_requested')
                update(j['id'],status='cancelling' if cancelling else 'running',stage='正在取消任务' if cancelling else '生成中',connection_error=None)
            elif pid in pending:update(j['id'],status='cancelling' if job(j['id']).get('cancel_requested') else 'queued',stage='等待取消确认' if job(j['id']).get('cancel_requested') else f'排队中 · 前面还有 {pending.index(pid)} 个任务',connection_error=None)
            elif j['status'] not in ['submitting','unknown']:
                update(j['id'],stage='正在核对算力卡任务记录',connection_error='任务暂未出现在队列或历史中，请保留此页；不会重复提交。')
            current=job(j['id'])
            if current.get('cancel_requested') and current['status'] not in ['done','failed','cancelled','abandoned'] and pid in running|set(pending):
                try:attempt_cancel(current,q)
                except HTTPException as e:update(j['id'],cancel_error=str(e.detail),stage='取消待确认',status='cancelling')
        except (requests.RequestException,ValueError) as e:
            update(j['id'],connection_error='视频尚未取回，连接恢复后自动重试。' if j['status']=='downloading' else '连接暂时中断，正在重连；任务不会重复提交。')

def monitor():
    while not stopping.is_set():
        try:poll_once()
        except Exception:
            for j in jobs():
                if j['status'] not in ['done','failed','cancelled','abandoned']:update(j['id'],connection_error='算力卡暂时不可达，正在重连；已完成文件保留在本地。')
        stopping.wait(3)

def listen():
    while not stopping.is_set():
        ws=None
        try:
            ws=websocket.create_connection(BASE.replace('https:','wss:').replace('http:','ws:')+'/ws?clientId='+CLIENT,timeout=15)
            while not stopping.is_set():
                try:raw=ws.recv()
                except websocket.WebSocketTimeoutException:continue
                if not isinstance(raw,str):continue
                event=json.loads(raw);kind=event.get('type');d=event.get('data',{})
                if kind not in ['executing','progress','execution_start']:continue
                pid=d.get('prompt_id')
                j=next((j for j in jobs() if j.get('prompt_id')==pid and j['status'] not in ['done','failed','cancelled','abandoned']),None)
                if not j or j.get('cancel_requested'):continue
                if kind=='progress':update(j['id'],status='running',stage='生成中',progress=None,connection_error=None)
                elif kind=='executing' and d.get('node'):
                    stage='生成中'
                    update(j['id'],status='running',stage=stage,progress=None,connection_error=None)
        except Exception:stopping.wait(3)
        finally:
            if ws:ws.close()

@asynccontextmanager
async def lifespan(app):
    stopping.clear()
    if BASE:
        threading.Thread(target=monitor,daemon=True).start()
        threading.Thread(target=listen,daemon=True).start()
    yield
    stopping.set()

app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None)

class DirectorySelection(BaseModel):
    initial: str = Field(default='', max_length=4096)

@app.post('/api/local-directory')
def local_directory(request:Request,body:DirectorySelection):
    # A remote/tunnel caller must not launch UI on the owner's desktop.
    if not request.client or request.client.host not in ('127.0.0.1','::1') or request.url.hostname not in ('127.0.0.1','localhost','::1'):
        raise HTTPException(403,'请在运行网站的这台电脑上选择文件夹，或直接填写运行端目录。')
    origin=request.headers.get('origin')
    if not origin or origin.rstrip('/')!=str(request.base_url).rstrip('/'):
        raise HTTPException(403,'目录选择只允许当前本地页面调用。')
    try:return {'path':choose_directory(body.initial)}
    except (RuntimeError,OSError,ValueError) as error:
        raise HTTPException(503,str(error)) from None

@app.middleware('http')
async def local_origin(request:Request,call_next):
    denied=access_denied(request.url.path,request.headers.get('authorization'))
    if denied is not None:return denied
    # Authentication and the origin guard serve different purposes.
    origin=request.headers.get('origin')
    allowed={f'http://127.0.0.1:{request.url.port}',f'http://localhost:{request.url.port}'}
    allowed.update(x.strip().rstrip('/') for x in os.environ.get('YINGXU_ALLOWED_ORIGINS','').split(',') if x.strip())
    public_origin=railway_origin()
    if public_origin:allowed.add(public_origin)
    try:
        private_origin=json.loads((PRIVATE/'access.json').read_text('utf-8-sig')).get('origin','')
        from urllib.parse import urlparse
        parsed=urlparse(private_origin)
        if parsed.scheme=='https' and (parsed.hostname or '').endswith('.ts.net') and parsed.path in ('','/') and not parsed.query and not parsed.fragment and not parsed.username:
            allowed.add(private_origin.rstrip('/'))
    except (OSError,ValueError,AttributeError):pass
    if request.url.path.startswith('/api') and origin and origin not in allowed:
        from fastapi.responses import JSONResponse
        return JSONResponse({'detail':'不允许跨站调用。'},403)
    response=await call_next(request)
    if request.url.path.startswith('/api') and not request.url.path.startswith('/api/media'):response.headers['Cache-Control']='no-store'
    return response

@app.get('/healthz')
def liveness():
    return JSONResponse({'status':'ok'},headers={'Cache-Control':'no-store'})

@app.get('/api/workflows')
def list_workflows():return [w for w in WORKFLOWS if workflow_path(w['id']).is_file()] if BASE else []

@app.get('/api/catalog-connections')
def catalog_connections():
    if not BASE:return []
    legacy=[{**{k:w[k] for k in ['id','name','source','source_hash','output']},'adapter':'legacy','available':True,
             'validation':'api-pending' if w['id'] in ('local-card-105','local-card-106') else 'live-verified'} for w in CATALOG_WORKFLOWS if BASE and workflow_path(w['id']).is_file()]
    legacy_ids={w['id'] for w in CATALOG_WORKFLOWS}
    generic=[]
    for id,spec in schema_adapters.registry().items():
        if id in legacy_ids:continue
        ready=spec.get('validation')=='structural-verified'
        available=bool(BASE) and ready and schema_adapters.template_path(spec).is_file()
        generic.append({**{k:spec.get(k) for k in ('id','name','source','source_hash','output')},
                        'adapter':'generic','available':available,'validation':spec.get('validation','blocked'),
                        'blocking_reason':spec.get('blocking_reason') or ('' if available or not ready else '尚未配置算力服务或缺少执行模板。'),
                        **public_schema(spec)})
    return legacy+generic

def public_schema(spec):
    def control(field):
        visible={key:copy.deepcopy(field[key]) for key in ('id','kind','key','value','type','label','nodeId','min','max','step','integer','options','customRange','derived','help','uiGroup','unit','guidanceRange','mediaSlotId') if key in field}
        if field.get('previewRecipe'):
            visible['previewRecipe']={key:copy.deepcopy(field['previewRecipe'][key]) for key in ('longSideControlId','longSide','multiple','sourceMultiple','postScale','fit','frameRate','skipControlId','skipFrames') if key in field['previewRecipe']}
        if field.get('members'):visible['members']=[{key:member[key] for key in ('id','key','nodeId') if key in member} for member in field['members']]
        return visible
    def api_profile(profile):
        visible={key:copy.deepcopy(profile[key]) for key in ('id','label','model','modelOptions','keyOnly','help','branchId') if key in profile}
        try:
            parsed=urlsplit(profile.get('baseUrl',''))
            host=parsed.hostname or ''
            if ':' in host:host='['+host+']'
            if parsed.port:host+=':'+str(parsed.port)
            visible['baseUrl']=urlunsplit((parsed.scheme,host,parsed.path,'','')) if parsed.scheme in ('http','https') else ''
        except ValueError:visible['baseUrl']=''
        return visible
    media=[{**{key:copy.deepcopy(slot[key]) for key in ('id','kind','label','branchId') if key in slot},
            'required':slot.get('required',not slot.get('optional',False)),
            'optional':not slot.get('required',not slot.get('optional',False))} for slot in spec.get('media',[])]
    constraints=[{key:item[key]for key in ('type','width','height')if key in item}
                 for item in spec.get('constraints',[])if item.get('type')=='nonzero-size']
    return {'supportedControlIds':[field['id'] for field in spec.get('controls',[])],
            'supportedTextIds':[field['id'] for field in spec.get('texts',[])],
            'constraints':constraints,
            'supportedMediaIds':[slot['id'] for slot in spec.get('media',[])],
            'controls':[control(field) for field in spec.get('controls',[])],
            'texts':[{key:copy.deepcopy(field[key]) for key in ('id','key','role','label','help','branchId','default','value','required','preserveWhenEmpty') if key in field} for field in spec.get('texts',[])],
            'media':media,'apiProfiles':[api_profile(profile) for profile in spec.get('apiProfiles',[])],
            'external_api_account':spec.get('external_api_account',False)}

@app.get('/api/health')
def health():
    if not BASE:return dict(online=False,configured=False,message='演示模式：在 .env 中设置 CHENYU_CARD_URL 后可接入真实生成。')
    try:
        r=requests.get(BASE+'/queue',timeout=8);r.raise_for_status()
        return dict(online=True,queue=len(r.json().get('queue_pending',[])),running=len(r.json().get('queue_running',[])))
    except requests.RequestException:return dict(online=False,message='请确认算力卡正在运行且地址未变化。')

def image_with_edit_mask(data,mask_data):
    """Keep source RGB under transparent edit pixels; canvas exports lose it."""
    try:
        with Image.open(io.BytesIO(data))as image:
            if image.width*image.height>20_000_000:raise HTTPException(413,'标注图片超过 2000 万像素，请缩小后再上传。')
            original=ImageOps.exif_transpose(image).convert('RGBA')
        with Image.open(io.BytesIO(mask_data))as image:
            if image.width*image.height>20_000_000:raise HTTPException(413,'编辑掩膜超过 2000 万像素，请缩小后再上传。')
            mask_image=ImageOps.exif_transpose(image).convert('RGBA')
        if mask_image.size!=original.size:raise HTTPException(400,'编辑掩膜尺寸与原图不一致，请重新标注。')
        # New masks are white on transparent; older masks are opaque gray.
        # Multiplication retains antialiased strengths in both encodings.
        selected=ImageChops.multiply(mask_image.convert('L'),mask_image.getchannel('A'))
        original.putalpha(ImageChops.multiply(original.getchannel('A'),ImageOps.invert(selected)))
        result=io.BytesIO();original.save(result,format='PNG');return result.getvalue()
    except (OSError,ValueError,Image.DecompressionBombError):
        raise HTTPException(400,'原图或编辑掩膜损坏，请重新导出 PNG 后上传。')from None

def retain_unmasked_image(data,ext,name):
    """Keep the exact independent source bytes for later original comparison."""
    key=hashlib.sha256(data).hexdigest()
    path=PRIVATE/'uploads'/(key+ext)
    if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest()!=key:path.write_bytes(data)
    original=dict(id=key,kind='image',name=name,bytes=len(data))
    with lock,database() as db:
        db.execute('INSERT OR IGNORE INTO assets VALUES (?,?)',(key,json.dumps(original,ensure_ascii=False)))
    return key


@app.post('/api/assets')
async def upload(file:UploadFile=File(...),mask:UploadFile|None=File(None)):
    ext=Path(file.filename or '').suffix.lower()
    if ext not in MEDIA_KINDS or MEDIA_KINDS[ext]=='text':raise HTTPException(400,'支持 PNG、JPG、WebP、GIF 图片，MP4 / WebM 视频，以及 WAV、MP3、FLAC、OGG、M4A 音频。')
    chunks=[];size=0
    while chunk:=await file.read(1024*1024):
        size+=len(chunk)
        if size>200*1024*1024:raise HTTPException(413,'单个素材上限 200 MB，请压缩或截短后重试。')
        chunks.append(chunk)
    data=b''.join(chunks)
    kind=MEDIA_KINDS[ext]
    content_type=file.content_type
    name=(file.filename or '')[:150]
    provenance={}
    if kind=='image':
        try:
            with Image.open(io.BytesIO(data)) as im:im.verify()
        except Exception:raise HTTPException(400,'图片文件损坏或格式不符，请重新导出 PNG / JPG。')
    elif kind=='video' and ext in ('.mp4','.mov'):
        if b'ftyp' not in data[:64]:raise HTTPException(400,'请使用有效的 MP4 视频。')
    else:
        try:
            with av.open(io.BytesIO(data)) as container:
                stream=next((s for s in container.streams if s.type==kind),None)
                if stream is None or next(container.decode(stream),None) is None:raise ValueError('没有有效媒体帧。')
        except (av.error.FFmpegError,ValueError,OSError):raise HTTPException(400,'无法读取'+('音频' if kind=='audio' else '视频')+'，请重新导出后再上传。')
    if mask is not None:
        if kind!='image' or MEDIA_KINDS.get(Path(mask.filename or '').suffix.lower())!='image':
            raise HTTPException(400,'编辑掩膜只能与图片原图一起上传，请使用 PNG、JPG 或 WebP 图片。')
        mask_chunks=[];mask_size=0
        while chunk:=await mask.read(1024*1024):
            mask_size+=len(chunk)
            if mask_size>200*1024*1024:raise HTTPException(413,'单个编辑掩膜上限 200 MB，请缩小后重试。')
            mask_chunks.append(chunk)
        original_data=data;original_ext=ext;original_name=name
        data=image_with_edit_mask(data,b''.join(mask_chunks))
        original_id=retain_unmasked_image(original_data,original_ext,original_name)
        provenance={'original_asset_id':original_id,'annotation_mode':'mask'}
        size=len(data);ext='.png';content_type='image/png'
        name=(Path(name).stem or '标注原图')+'.png'
    id=hashlib.sha256(data).hexdigest()
    local=PRIVATE/'uploads'/(id+ext);local.write_bytes(data)
    try:cached=asset(id)
    except HTTPException:cached=None
    if cached:
        if provenance:
            cached={**cached,**provenance}
            with lock,database() as db:
                db.execute('UPDATE assets SET data=? WHERE id=?',(json.dumps(cached,ensure_ascii=False),id))
        def still_available():
            if not cached.get('remote'):return False
            remote=Path(cached['remote'])
            try:
                with requests.get(BASE+'/view',params={'filename':remote.name,'subfolder':str(remote.parent).replace('\\','/') if str(remote.parent)!='.' else '', 'type':'input'},headers={'Range':'bytes=0-63'},stream=True,timeout=15) as r:
                    return r.status_code in [200,206]
            except requests.RequestException:return False
        if await asyncio.to_thread(still_available):return public_asset(cached)
    def transfer():
        try:
            with local.open('rb') as stream:
                r=requests.post(BASE+'/upload/image',files={'image':('yingxu-'+id[:24]+ext,stream,content_type)},data={'overwrite':'false'},timeout=(15,180))
            r.raise_for_status();out=r.json()
        except (requests.RequestException,ValueError):raise HTTPException(502,'素材未能上传到算力卡，请检查卡是否在线后重试。')
        a=dict(id=id,kind=kind,name=name,bytes=size,remote=(out.get('subfolder','')+'/'+out['name']).lstrip('/'),**provenance)
        with lock,database() as db:db.execute('INSERT OR REPLACE INTO assets VALUES (?,?)',(id,json.dumps(a,ensure_ascii=False)))
        return public_asset(a)
    return await asyncio.to_thread(transfer)

class Submission(BaseModel):
    model_config=ConfigDict(extra='forbid')
    workflow_id:str
    source_hash:str|None=None
    prompt:str=Field(default='',max_length=6000)
    negative:str=Field(default='',max_length=6000)
    settings:dict=Field(default_factory=dict)
    asset_ids:list[str]=Field(default_factory=list,max_length=64)
    catalog_values:dict=Field(default_factory=dict,max_length=256)
    catalog_texts:dict=Field(default_factory=dict,max_length=128)
    catalog_assets:dict[str,str]=Field(default_factory=dict,max_length=64)
    api_profiles:dict=Field(default_factory=dict)
    token:str=Field(min_length=8,max_length=100)

    @field_validator('prompt','negative')
    @classmethod
    def valid_text(cls,value):
        if '\x00' in value:raise ValueError('描述不能包含空字符。')
        return value

    @model_validator(mode='after')
    def named_negative_limit(self):
        # Catalog text controls share the reviewed 6000-character contract.
        # The two original named video forms retain their 2000-character limit.
        if self.workflow_id in ('h3-reference','bernini-edit') and len(self.negative)>2000:
            raise ValueError('此视频工作流的反向提示词最多 2000 字。')
        return self

API_PROFILE_NODES={'local-card-82':('161','30'),'local-card-105':('190','182'),'local-card-106':('178','158')}
def bind_api_profiles(workflow_id,graph,profiles):
    allowed=API_PROFILE_NODES.get(workflow_id)
    if not isinstance(profiles,dict) or (profiles and not allowed):
        raise HTTPException(400,'此工作流没有可替换的 API 入口。')
    if not profiles:return graph
    node,output=allowed
    if set(profiles)!={node}:raise HTTPException(400,'API 配置与原工作流节点不匹配。')
    choice=profiles[node]
    if not isinstance(choice,dict) or set(choice)!={'mode','base_url','model','api_key'} or choice.get('mode')!='custom':
        raise HTTPException(400,'请检查自有 API 配置。')
    base_url,model,api_key=(choice[k].strip() if isinstance(choice[k],str) else '' for k in ('base_url','model','api_key'))
    parsed=urlsplit(base_url)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or len(base_url)>400:
        raise HTTPException(400,'Base URL 需要是有效的 HTTP 或 HTTPS 地址。')
    if not model or len(model)>120:raise HTTPException(400,'请填写有效的 Model 名称。')
    if not api_key or len(api_key)>500:raise HTTPException(400,'请填写 API key。')
    graph[node]['inputs'].update(api_baseurl=base_url,model=model,api_key=api_key)
    return prune(graph,[output])

@app.post('/api/jobs')
def submit(body:Submission):
    if not BASE:raise HTTPException(503,'尚未配置算力服务，请在 .env 中设置 CHENYU_CARD_URL；演示生成仍可使用。')
    if manifest(body.workflow_id) is None:
        spec=schema_adapters.manifest(body.workflow_id)
        if spec:
            with lock,database() as db:
                old=db.execute('SELECT data FROM jobs WHERE token=?',(body.token,)).fetchone()
                if old:return public(json.loads(old[0]))
                j=prepare_schema_submission(body,spec,db)
            return dispatch(j)
    with lock,database() as db:
        old=db.execute('SELECT data FROM jobs WHERE token=?',(body.token,)).fetchone()
        if old:return public(json.loads(old[0]))
        w=manifest(body.workflow_id)
        if not w:raise HTTPException(400,'此工作流尚未接入。')
        if body.catalog_values or body.catalog_texts or body.catalog_assets:raise HTTPException(400,'此工作流仍使用原有参数接口，请刷新页面后重试。')
        if w.get('source_hash') and body.source_hash!=w['source_hash']:
            raise HTTPException(409,'工作流原文件已经变化，请刷新页面后重试。')
        try:s=settings_for(w,body.settings)
        except ValueError as e:raise HTTPException(400,str(e))
        if not body.prompt.strip():raise HTTPException(400,'请填写希望生成或修改的画面。')
        if body.negative.strip() and not w['negative']:raise HTTPException(400,'此工作流没有反向提示词输入，请把要求写入镜头描述。')
        aa=[asset(i) for i in body.asset_ids]
        if any(a['kind'] not in ('image','video') for a in aa):raise HTTPException(400,'此工作流不支持音频素材。')
        for kind,lo,hi in [('image','minImages','maxImages'),('video','minVideos','maxVideos')]:
            n=sum(a['kind']==kind for a in aa)
            if not w[lo]<=n<=w[hi]:raise HTTPException(400,f'{w["name"]}需要 {w[lo]}–{w[hi]} 份'+('图片' if kind=='image' else '视频')+'素材。')
        if w['id']=='local-card-15':
            require_edit_mask(aa[0])
        if w['id']=='bernini-edit':
            source=next(a for a in aa if a['kind']=='video')
            if s['trim_start']+s['duration']>video_length(source)+0.05:
                raise HTTPException(400,'选择的片段超出原视频时长，请缩短片段或调整起点。')
        aa=[ensure_remote(a) for a in aa]
        if w['id']=='local-card-16':
            aa[0]={**aa[0],'has_edit_mask':has_edit_mask(aa[0])}
        id=uuid.uuid4().hex
        try:
            graph=bind_api_profiles(w['id'],build_graph(w['id'],body.prompt,body.negative,s,aa,id),body.api_profiles)
            bind_vhs_audio(graph,aa)
        except FileNotFoundError:raise HTTPException(503,'缺少此工作流的 API 模板，请核对 workflows/api 及部署说明。') from None
        for node in graph.values():
            inputs=node.get('inputs',{})
            key=inputs.get('api_key')
            if isinstance(key,list) and len(key)==2:
                key_node=graph.get(str(key[0]),{}).get('inputs',{})
                key=next((key_node[k] for k in ('prompt','text','value') if k in key_node),key)
            if isinstance(key,str) and not key.strip():
                raise HTTPException(400,'此工作流需要自己的 API key，请在自有 API 配置中填写，或配置私有工作流模板。')
        j=dict(id=id,token=body.token,workflow_id=w['id'],prompt=body.prompt,negative=body.negative,settings=s,asset_ids=body.asset_ids,status='submitting',stage='正在提交到算力卡',started=time.time()*1000,ended=None,outputs=[],graph=graph,prompt_id=None,error=None)
        db.execute('INSERT INTO jobs VALUES (?,?,?)',(id,body.token,json.dumps(j,ensure_ascii=False)))
    return dispatch(j)

def require_api_keys(graph,spec=None):
    def resolved(value):
        seen=set()
        while isinstance(value,list) and len(value)==2:
            node_id=str(value[0])
            if node_id in seen:return None
            seen.add(node_id)
            source=graph.get(node_id,{}).get('inputs',{})
            literal=next((source[key] for key in ('prompt','text','value','string') if key in source),value)
            if literal is value:return value
            value=literal
        return value
    # Registry profiles may bind to a primitive named "value", rather than
    # an input named api_key. Check the actual reviewed targets after overrides
    # and graph pruning, without requiring credentials during offline builds.
    for profile in (spec or {}).get('apiProfiles',[]):
        binding=profile.get('bindings',{}).get('apiKey')
        targets=binding if isinstance(binding,list) else [binding]
        for target in targets:
            if not isinstance(target,dict) or str(target.get('node')) not in graph:continue
            value=resolved(graph[str(target['node'])].get('inputs',{}).get(target.get('input')))
            if value is None or isinstance(value,str) and not value.strip():
                label=profile.get('label') or '此工作流的 API 配置'
                raise HTTPException(400,f'{label}缺少 API key，请填写自己的 API key，或配置带密钥的私有工作流模板。')
    for node in graph.values():
        inputs=node.get('inputs',{})
        for name,value in inputs.items():
            if name.lower() not in ('api_key','apikey','access_token'):continue
            value=resolved(value)
            if isinstance(value,str) and not value.strip():raise HTTPException(400,'此工作流需要自己的 API key，请在自有 API 配置中填写，或配置私有工作流模板。')

def prepare_schema_submission(body,spec,db):
    if body.source_hash!=spec.get('source_hash'):raise HTTPException(409,'工作流原文件已经变化，请刷新页面后重试。')
    if body.settings or body.asset_ids:raise HTTPException(400,'此工作流需要按控件与素材槽提交，请刷新页面后重试。')
    try:
        schema_adapters.require_ready(spec)
        # Validate all inexpensive inputs before any remote upload or submission.
        checked_values=schema_adapters.validate_values(spec,body.catalog_values)
        schema_adapters.validate_texts(spec,body.catalog_texts,body.prompt,body.negative)
        slots=spec.get('media',[])
        if set(body.catalog_assets)-{slot['id'] for slot in slots}:raise ValueError('参考素材包含不属于此工作流的项目。')
        records={slot['id']:asset(body.catalog_assets[slot['id']]) for slot in slots if slot['id'] in body.catalog_assets}
        schema_adapters.validate_assets(spec,records)
        require_schema_edit_inputs(spec,records,checked_values)
        geometry=points_geometry(spec,checked_values,records)
        source_has_audio=source_audio_presence(spec,records)
        records=schema_vhs_assets(spec,records,source_has_audio=source_has_audio)
        records={slot:ensure_remote(record) for slot,record in records.items()}
        id=uuid.uuid4().hex
        graph,values,texts=schema_adapters.build(spec,checked_values,body.catalog_texts,records,body.api_profiles,id,body.prompt,body.negative,geometry=geometry)
        region_adaptation=preserve_region_output(spec,graph)
        audio_adaptation=preserve_117_source_audio(spec,graph,source_has_audio=source_has_audio)
        if audio_adaptation:graph=prune(graph,spec['outputs'])
    except FileNotFoundError:raise HTTPException(503,'缺少此工作流的执行模板，请核对部署文件。') from None
    except (ValueError,KeyError,TypeError) as error:raise HTTPException(400,str(error)) from None
    require_api_keys(graph,spec)
    j=dict(id=id,token=body.token,workflow_id=spec['id'],prompt=body.prompt,negative=body.negative,settings={},
           catalog_values=values,catalog_texts=texts,catalog_assets=dict(body.catalog_assets),schema_spec=copy.deepcopy(spec),
           asset_ids=[body.catalog_assets[slot['id']] for slot in slots if slot['id'] in body.catalog_assets],
           status='submitting',stage='正在提交到算力卡',started=time.time()*1000,ended=None,outputs=[],graph=graph,prompt_id=None,error=None)
    if region_adaptation:j['execution_adaptations']=[region_adaptation]
    if audio_adaptation:j.setdefault('execution_adaptations',[]).append(audio_adaptation)
    db.execute('INSERT INTO jobs VALUES (?,?,?)',(id,body.token,json.dumps(j,ensure_ascii=False)))
    return j

def dispatch(j):
    id=j['id'];graph=j['graph']
    try:
        r=requests.post(BASE+'/prompt',json={'prompt':graph,'client_id':CLIENT,'extra_data':{'yingxu_job_id':id}},timeout=(15,60))
        if r.status_code>=400:
            try:detail=r.json()
            except ValueError:detail={'http_status':r.status_code,'message':r.text[:1000]}
            (PRIVATE/'receipts'/f'{id}-validation.json').write_text(json.dumps(detail,ensure_ascii=False,indent=2),'utf-8')
            return public(update(id,status='failed',stage='工作流校验失败',error=friendly(json.dumps(detail.get('node_errors',detail),ensure_ascii=False)[:500]),ended=time.time()*1000))
        out=r.json()
        return public(update(id,prompt_id=out['prompt_id'],status='queued',stage='等待算力卡执行',error=None,connection_error=None))
    except (requests.RequestException,ValueError,KeyError) as error:
        (PRIVATE/'receipts'/f'{id}-transport.json').write_text(json.dumps({'type':type(error).__name__,'message':str(error)[:1000]},ensure_ascii=False,indent=2),'utf-8')
        return public(update(id,status='unknown',stage='正在确认提交状态',error='连接中断，正在核对任务，暂不重复提交。'))

def redraw_legacy_refinement_seed(workflow_id,graph,settings):
    """Record the independently redrawn refinement seed in the saved settings.

    Old tickets can lack the newer form key. Their saved execution graph is the
    authoritative previous seed, including tickets affected by the old coupled
    redraw. No creative, model, size or material input is touched.
    """
    contracts={'local-card-85':('63','KSampler','refine_seed',9007199254740991),
               'local-card-107':('80','SeedVR2VideoUpscaler','upscale_seed',4294967295)}
    if workflow_id not in contracts:raise ValueError('未审查此工作流的独立精修种子。')
    node,typ,key,maximum=contracts[workflow_id]
    current=graph.get(node,{})
    old=current.get('inputs',{}).get('seed')
    if current.get('class_type')!=typ or isinstance(old,bool) or not isinstance(old,int) or not 0<=old<=maximum:
        raise ValueError('独立精修种子的执行合同已经变化，请重新审查。')
    new=(old+1+secrets.randbelow(maximum))%(maximum+1)
    settings[key]=new
    current['inputs']['seed']=new


class Rerun(BaseModel):
    model_config=ConfigDict(extra='forbid')
    token:str=Field(min_length=8,max_length=100)
    randomize_seed:bool=Field(default=True,strict=True)

@app.post('/api/jobs/{id}/rerun')
def rerun(id:str,body:Rerun):
    original=job(id)
    if original.get('schema_spec'):
        return rerun_schema(id,body)
    with lock,database() as db:
        previous=db.execute('SELECT data FROM jobs WHERE token=?',(body.token,)).fetchone()
        if previous:return public(json.loads(previous[0]))
        original=job(id)
        if original['status'] not in ['done','failed','cancelled','abandoned']:
            raise HTTPException(409,'原任务尚未结束，请等待结果后再试。')
        aa=[ensure_remote(asset(key)) for key in original['asset_ids']]
        new_id=uuid.uuid4().hex
        settings=copy.deepcopy(original['settings'])
        graph=copy.deepcopy(original['graph'])
        if body.randomize_seed:
            if 'seed' in settings:
                old_seed=settings['seed']
                settings['seed']=(old_seed+1+secrets.randbelow(2**48-1))%(2**48)
            if original['workflow_id']=='local-card-2':
                graph['536']['inputs']['seed']=settings['seed']
                graph['518:489']['inputs']['switch']=True
            elif original['workflow_id']=='local-card-1':
                graph['476']['inputs']['seed']=settings['seed']
            elif original['workflow_id']=='local-card-85':
                graph['58']['inputs']['seed']=settings['seed']
                redraw_legacy_refinement_seed(original['workflow_id'],graph,settings)
            elif original['workflow_id']=='local-card-9':
                graph['96']['inputs']['noise_seed']=settings['seed']
            elif original['workflow_id']=='local-card-10':
                graph['75']['inputs']['seed']=settings['seed']
            elif original['workflow_id']=='local-card-12':
                graph['158']['inputs']['seed']=settings['seed']
            elif original['workflow_id']=='local-card-13':
                graph['95']['inputs']['seed']=settings['seed']
            elif original['workflow_id']=='local-card-14':
                graph['95']['inputs']['seed']=settings['seed']
            elif original['workflow_id']=='local-card-19':
                graph['88']['inputs']['noise_seed']=settings['seed']
            elif original['workflow_id']=='local-card-21':
                graph['21']['inputs']['noise_seed']=settings['seed']
            elif original['workflow_id'] in ('local-card-104','local-card-129'):
                graph['116']['inputs']['seed']=settings['seed']
            elif original['workflow_id']=='local-card-107':
                graph['3']['inputs']['seed']=settings['seed']
                redraw_legacy_refinement_seed(original['workflow_id'],graph,settings)
            elif original['workflow_id'] in ('local-card-109','local-card-128'):
                graph['57']['inputs']['seed']=settings['seed']
                graph['48' if settings['branch']=='lora' else '51']['inputs']['seed']=settings['seed']
            elif original['workflow_id']=='local-card-130':
                graph['5']['inputs']['seed']=settings['seed']
            elif original['workflow_id']=='local-card-108':
                settings['prompt_seed']=(settings['prompt_seed']+1+secrets.randbelow(2**32-1))%(2**32)
                graph['53']['inputs']['seed']=settings['seed']
                graph['60']['inputs']['sampling_mode.seed']=settings['prompt_seed']
            elif original['workflow_id']=='local-card-110':
                graph['63']['inputs']['noise_seed']=settings['seed']
            elif original['workflow_id']=='local-card-3':
                graph['558']['inputs']['seed']=settings['seed']
                graph['540:489']['inputs']['switch']=True
            elif original['workflow_id']=='local-card-84':
                graph['515']['inputs']['seed']=settings['seed']
                graph['497:468']['inputs']['switch']=True
            elif original['workflow_id']=='local-card-78':
                graph['14']['inputs']['seed']=settings['seed']
            elif original['workflow_id']=='local-card-83':
                graph['221']['inputs']['seed']=settings['seed']
            elif original['workflow_id']=='local-card-134':
                pass  # Deterministic color match; a retry keeps the same inputs.
            elif original['workflow_id'] in ('local-card-11','local-card-15','local-card-16','local-card-17','local-card-18','local-card-20'):
                for node,key in {'local-card-11':[('157','seed')],
                                 'local-card-15':[('141','seed')],
                                 'local-card-16':[('17','seed')],
                                 'local-card-17':[('101','noise_seed'),('118','noise_seed')],
                                 'local-card-18':[('104','noise_seed'),('117','noise_seed')],
                                 'local-card-20':[('7','noise_seed')]}[original['workflow_id']]:
                    graph[node]['inputs'][key]=settings['seed']
            elif original['workflow_id']=='local-card-82':
                settings['prompt_seed']=(settings['prompt_seed']+1+secrets.randbelow(2**48-1))%(2**48)
                graph['161']['inputs']['seed']=settings['prompt_seed']
                graph['28']['inputs']['seed']=settings['seed']
            elif original['workflow_id'] in ('local-card-105','local-card-106'):
                settings['noise_seed']=(settings['noise_seed']+1+secrets.randbelow(2**48-1))%(2**48)
                graph['190' if original['workflow_id']=='local-card-105' else '178']['inputs']['seed']=settings['seed']
                graph['187:18' if original['workflow_id']=='local-card-105' else '98:18']['inputs']['noise_seed']=settings['noise_seed']
            else:
                seed_nodes=['55'] if original['workflow_id']=='h3-reference' else ['384','386']
                for key in seed_nodes:graph[key]['inputs']['noise_seed']=settings['seed']
        output={'local-card-2':'517','local-card-1':'461','local-card-3':'539','local-card-9':'104','local-card-10':'31','local-card-11':'62','local-card-15':'135','local-card-16':'26','local-card-17':'9','local-card-18':'9','local-card-20':'15','local-card-12':'62','local-card-13':'62','local-card-14':'62','local-card-19':'9','local-card-21':'14','local-card-78':'80','local-card-82':'30','local-card-83':'228','local-card-84':'494','local-card-85':'54','local-card-104':'99','local-card-105':'182','local-card-106':'158','local-card-107':'site-output','local-card-108':'29','local-card-109':'site-output','local-card-110':'106','local-card-128':'site-output','local-card-129':'99','local-card-130':'26','local-card-134':'14','h3-reference':'54'}.get(original['workflow_id'],'443')
        graph[output]['inputs']['filename_prefix']='yingxu/'+new_id
        for node,branch in {'local-card-11':[('62','Flux-9B'),('147','Qwen-AIO')],
                            'local-card-17':[('9','single'),('94','double')],
                            'local-card-18':[('9','single'),('94','double')]}.get(original['workflow_id'],[]):
            graph[node]['inputs']['filename_prefix']='yingxu/'+new_id+'/'+branch
        if original['workflow_id']=='local-card-12':
            for node,branch in [('62','Anything-to-Real'),('170','Turn2Real'),('179','anime2real-semi')]:graph[node]['inputs']['filename_prefix']='yingxu/'+new_id+'/'+branch
        # Restore upstream files if the card was restarted; all other graph inputs stay intact.
        for ix,a in enumerate(a for a in aa if a['kind']=='image'):
            if original['workflow_id']=='local-card-2':graph[['530','527'][ix]]['inputs']['image']=a['remote']
            elif original['workflow_id']=='local-card-3':graph[['551','547'][ix]]['inputs']['image']=a['remote']
            elif original['workflow_id']=='local-card-84':graph['506']['inputs']['image']=a['remote']
            elif original['workflow_id']=='local-card-78':graph['31']['inputs']['image']=a['remote']
            elif original['workflow_id']=='local-card-82':graph['31']['inputs']['image']=a['remote']
            elif original['workflow_id']=='local-card-12':graph['63']['inputs']['image']=a['remote']
            elif original['workflow_id']=='local-card-13':graph['63']['inputs']['image']=a['remote']
            elif original['workflow_id']=='local-card-14':graph['63']['inputs']['image']=a['remote']
            elif original['workflow_id']=='local-card-83':graph['227']['inputs']['image']=a['remote']
            elif original['workflow_id']=='local-card-134':graph[['11','12'][ix]]['inputs']['image']=a['remote']
            elif original['workflow_id'] in ('local-card-11','local-card-15','local-card-16','local-card-17','local-card-18','local-card-20'):
                node={'local-card-11':['63','64'],'local-card-15':['148'],'local-card-16':['36','25'],
                      'local-card-17':['76','81'],'local-card-18':['76','81'],'local-card-20':['43']}[original['workflow_id']][ix]
                graph[node]['inputs']['image']=a['remote']
            else:graph[f'upload_{ix}']['inputs']['image']=a['remote']
        if original['workflow_id']=='bernini-edit':
            graph['425']['inputs']['video']=next(a['remote'] for a in aa if a['kind']=='video')
        bind_vhs_audio(graph,aa)
        j=dict(id=new_id,token=body.token,workflow_id=original['workflow_id'],prompt=original['prompt'],negative=original['negative'],settings=settings,asset_ids=list(original['asset_ids']),status='submitting',stage='正在提交到算力卡',started=time.time()*1000,ended=None,outputs=[],graph=graph,prompt_id=None,error=None,rerun_of=id)
        db.execute('INSERT INTO jobs VALUES (?,?,?)',(new_id,body.token,json.dumps(j,ensure_ascii=False)))
    return dispatch(j)

def rerun_schema(id,body):
    if not BASE:raise HTTPException(503,'尚未配置算力服务。')
    with lock,database() as db:
        previous=db.execute('SELECT data FROM jobs WHERE token=?',(body.token,)).fetchone()
        if previous:return public(json.loads(previous[0]))
        original=job(id)
        if original['status'] not in ['done','failed','cancelled','abandoned']:raise HTTPException(409,'原任务尚未结束，请等待结果后再试。')
        records={slot:asset(key) for slot,key in original.get('catalog_assets',{}).items()}
        try:source_has_audio=source_audio_presence(original['schema_spec'],records)
        except ValueError as error:raise HTTPException(409,str(error))from None
        records=schema_vhs_assets(original['schema_spec'],records,original['graph'],source_has_audio=source_has_audio)
        records={slot:ensure_remote(record) for slot,record in records.items()}
        new_id=uuid.uuid4().hex
        try:
            graph,values=schema_adapters.rerun(original,records,new_id,randomize_seed=body.randomize_seed)
            region_adaptation=preserve_region_output(original['schema_spec'],graph)
            audio_adaptation=preserve_117_source_audio(original['schema_spec'],graph,source_has_audio=source_has_audio)
            if audio_adaptation:graph=prune(graph,original['schema_spec']['outputs'])
        except (ValueError,KeyError,TypeError) as error:raise HTTPException(409,'原工作流的执行绑定无法恢复：'+str(error)) from None
        j={**copy.deepcopy(original),'id':new_id,'token':body.token,'catalog_values':values,'graph':graph,
           'status':'submitting','stage':'正在提交到算力卡','started':time.time()*1000,'ended':None,'outputs':[],
           'prompt_id':None,'error':None,'rerun_of':id}
        if region_adaptation:j['execution_adaptations']=[region_adaptation]
        if audio_adaptation:
            j['execution_adaptations']=[a for a in j.get('execution_adaptations',[]) if a.get('id')!=audio_adaptation['id']]+[audio_adaptation]
        for key in ('cancel_requested','cancel_sent','cancel_error','connection_error','progress'):j.pop(key,None)
        db.execute('INSERT INTO jobs VALUES (?,?,?)',(new_id,body.token,json.dumps(j,ensure_ascii=False)))
    return dispatch(j)

@app.get('/api/assets/{id}/file')
def asset_content(id:str):
    a=asset(id);path=asset_file(a)
    path=public_media_path(path)
    return FileResponse(path,media_type=mimetypes.guess_type(str(path))[0],filename=a['name'],content_disposition_type='inline')

def public_media_path(path):
    """Serve PNG pixels without upstream execution metadata; retain originals."""
    path=Path(path)
    if path.suffix.lower()!='.png':return path
    with lock:
        try:
            if path.stat().st_size>100*1024*1024:raise ValueError('PNG delivery size limit')
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            safe=PRIVATE/'delivery-images'/f'{digest}.png'
            if not safe.is_file():strip_png_text(path,safe)
            return safe
        except (OSError,ValueError):
            raise HTTPException(500,'作品元数据处理失败，原件已保留。请重新打开作品。') from None

@app.get('/api/jobs/{id}/workflow')
def workflow_download(id:str):
    j=job(id)
    return JSONResponse(public_graph(j['graph']),headers={'Content-Disposition':f'attachment; filename="yingxu-{id[:8]}-workflow-api.json"'})

@app.get('/api/jobs')
def get_jobs():return [public(j) for j in jobs()]
@app.get('/api/jobs/{id}')
def get_job(id:str):return public(job(id))
def attempt_cancel(j,q=None):
    """Retry a persisted intent using only the task-scoped remote API."""
    id=j['id'];pid=j.get('prompt_id')
    if not pid or j.get('cancel_sent'):return public(j)
    try:
        if q is None:
            response=requests.get(BASE+'/queue',timeout=15);response.raise_for_status();q=response.json()
        pending={x[1] for x in q.get('queue_pending',[])}
        running={x[1] for x in q.get('queue_running',[])}
        if pid not in pending|running:
            return public(update(id,status='cancelling',stage='正在核对取消结果'))
        response=requests.post(BASE+'/api/jobs/'+pid+'/cancel',timeout=15)
        if response.status_code in (404,405):
            if pid in running:raise HTTPException(409,'算力卡不支持按任务取消运行；请在算力卡端处理，或停止本地等待。')
            requests.post(BASE+'/queue',json={'delete':[pid]},timeout=15).raise_for_status()
        else:
            response.raise_for_status()
            if response.json().get('cancelled') is not True:raise HTTPException(409,'远端尚未确认取消，将继续核对。')
        if pid in pending:
            response=requests.get(BASE+'/queue',timeout=15);response.raise_for_status();q=response.json()
            if pid not in {x[1] for x in q.get('queue_running',[])+q.get('queue_pending',[])}:
                return public(update(id,status='cancelled',stage='已取消任务',cancel_requested=True,ended=time.time()*1000,cancel_error=None,connection_error=None,error=None))
        return public(update(id,status='cancelling',stage='正在取消任务',cancel_requested=True,cancel_sent=True,cancel_error=None,connection_error=None))
    except (requests.RequestException,ValueError):
        return public(update(id,status='cancelling',stage='取消请求已保存 · 等待连接',cancel_error='远端未确认停止；恢复连接后自动重试。'))

@app.post('/api/jobs/{id}/cancel')
def cancel(id:str):
    with lock:
        j=job(id)
        if j['status'] in ['done','failed','cancelled','abandoned'] or j.get('cancel_requested'):return public(j)
        j=update(id,cancel_requested=True,status='cancelling',stage='取消请求已保存',cancel_error=None)
    if not j.get('prompt_id'):
        return public(update(id,stage='取消请求已保存 · 等待找回任务编号',cancel_error='尚未取得远端编号；连接恢复后自动取消，不会重复提交。'))
    try:
        response=requests.get(BASE+'/queue',timeout=15);response.raise_for_status();q=response.json()
        pid=j['prompt_id'];present={x[1] for x in q.get('queue_running',[])+q.get('queue_pending',[])}
        if pid not in present:
            raise HTTPException(409,'任务已离开队列，正在核对结果。请稍后查看状态。')
        return attempt_cancel(j,q)
    except (requests.RequestException,ValueError):
        return public(update(id,status='cancelling',stage='取消请求已保存 · 等待连接',cancel_error='远端未确认停止；恢复连接后自动重试。'))
    except HTTPException as e:
        update(id,cancel_error=str(e.detail));raise

@app.post('/api/jobs/{id}/abandon')
def abandon(id:str):
    # Explicitly stop local tracking; never claim the remote execution was stopped.
    with lock:
        j=job(id)
        if j['status'] in ['done','failed','cancelled','abandoned']:return public(j)
        if not j.get('cancel_requested'):raise HTTPException(409,'请先请求取消任务。')
        return public(update(id,status='abandoned',stage='已停止本地等待 · 远端状态未确认',ended=time.time()*1000,connection_error=None,error='远端任务可能仍运行并产生费用，请在算力卡端确认。'))

@app.get('/api/media/{id}/{filename}')
def media(id:str,filename:str):
    j=job(id)
    if filename not in [Path(o['src']).name for o in j.get('outputs',[])]:raise HTTPException(404,'找不到作品。')
    p=PRIVATE/'outputs'/j['id']/filename
    if not p.is_file():raise HTTPException(404,'本地作品文件已被移除。')
    if p.suffix.lower()!='.mp4':
        p=public_media_path(p)
        return FileResponse(p,media_type=mimetypes.guess_type(str(p))[0],filename=f'映序-{id[:8]}-{filename}',content_disposition_type='inline')
    with lock:
        embed_workflow(p,public_graph(j['graph']))
        current=job(id)
        index=int(filename.split('.')[0])
        out=current['outputs'][index]
        if not out.get('workflow_embedded') or out.get('bytes')!=p.stat().st_size:
            out.update(workflow_embedded=True,bytes=p.stat().st_size)
            update(id,outputs=current['outputs'])
    return FileResponse(p,media_type='video/mp4',filename=f'映序-{id[:8]}-{filename}',content_disposition_type='inline')

@app.post('/api/image/cutout')
async def image_cutout(file:UploadFile=File(...),bounds:str=Form('{}')):
    # Compute in memory; original files, jobs and the remote card are untouched.
    from local_cutout import cutout_png
    data=await file.read(40*1024*1024+1)
    if len(data)>40*1024*1024:raise HTTPException(413,'图片超过 40 MB，请缩小后再试。')
    try:
        region=json.loads(bounds)
        if not isinstance(region,dict):raise ValueError('主体范围格式不正确。')
        png=await asyncio.to_thread(cutout_png,data,region or None)
    except ImportError:raise HTTPException(503,'本地抠图组件未安装，可先使用框选或圈选。')
    except (ValueError,OSError,Image.DecompressionBombError) as error:raise HTTPException(400,str(error) or '无法读取图片。')
    return Response(png,media_type='image/png',headers={'Cache-Control':'no-store'})

app.mount('/',StaticFiles(directory=ROOT/'public',html=True),name='site')

if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host=os.environ.get('HOST','127.0.0.1'),port=int(os.environ.get('PORT','8770')))
