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

# Isolate the Starlette version required by the machine's FastAPI installation.
sys.path.insert(0,str(Path(__file__).resolve().parent/'private/runtime'))

import requests
import websocket
import av
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field
from adapters import ROOT, WORKFLOWS, CATALOG_WORKFLOWS, manifest, settings_for, build_graph, prune
from local_directory import choose_directory
from portable import embed_workflow
from configuration import DATA_DIR, workflow_path
from deployment_access import access_denied, railway_origin
import schema_adapters

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

def video_length(a):
    try:
        with av.open(str(asset_file(a))) as container:
            if container.duration is not None:return container.duration/av.time_base
            stream=next((s for s in container.streams if s.type=='video'),None)
            if stream and stream.duration is not None:return float(stream.duration*stream.time_base)
    except (av.error.FFmpegError, OSError, ValueError):
        pass
    raise HTTPException(400,'无法读取原视频时长，请重新导出 MP4 后再试。')

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
    return {'width':target_width,'height':target_height,'node':recipe['node'],
            **({'negativeTarget':recipe['negativeTarget']} if recipe.get('negativeTarget') else {})}

def public_asset(a):
    try:asset_file(a);available=True
    except HTTPException:available=False
    return dict(id=a['id'],kind=a['kind'],name=a['name'],bytes=a['bytes'],src=f"/api/assets/{a['id']}/file",available=available)

def public(j):
    references=[]
    catalog_slots=[slot['id'] for slot in j.get('schema_spec',{}).get('media',[]) if slot['id'] in j.get('catalog_assets',{})]
    for index,id in enumerate(j.get('asset_ids',[])):
        try:reference=public_asset(asset(id))
        except HTTPException:reference=dict(id=id,available=False,kind='unknown',name='原素材缺失',src='')
        if index<len(catalog_slots):reference['catalogSlot']=catalog_slots[index]
        references.append(reference)
    return {**{k:v for k,v in j.items() if k not in ['token','graph','download_items','schema_spec']},'request_token':j['token'],'references':references}

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
    remote=Path(a['remote'])
    try:
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
                    if item not in found:found.append(item)
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
                    if item not in found:found.append(item)
    return found

def collect(j,h):
    spec=j.get('schema_spec') or manifest(j['workflow_id']) or schema_adapters.manifest(j['workflow_id']) or {}
    kind=spec.get('output','video')
    items=output_items(h,kind,spec.get('outputs') if j.get('schema_spec') else None)
    if not items:
        update(j['id'],status='failed',stage='没有作品输出',error='工作流已结束，但没有返回可保存的作品。请检查输出节点。',ended=time.time()*1000)
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
    update(j['id'],status='done',stage='已保存作品',outputs=outputs,ended=time.time()*1000,error=None)

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
            visible['previewRecipe']={key:copy.deepcopy(field['previewRecipe'][key]) for key in ('longSideControlId','longSide','multiple','sourceMultiple','fit','frameRate','skipControlId','skipFrames') if key in field['previewRecipe']}
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

@app.post('/api/assets')
async def upload(file:UploadFile=File(...)):
    ext=Path(file.filename or '').suffix.lower()
    if ext not in MEDIA_KINDS or MEDIA_KINDS[ext]=='text':raise HTTPException(400,'支持 PNG、JPG、WebP、GIF 图片，MP4 / WebM 视频，以及 WAV、MP3、FLAC、OGG、M4A 音频。')
    chunks=[];size=0
    while chunk:=await file.read(1024*1024):
        size+=len(chunk)
        if size>200*1024*1024:raise HTTPException(413,'单个素材上限 200 MB，请压缩或截短后重试。')
        chunks.append(chunk)
    data=b''.join(chunks)
    kind=MEDIA_KINDS[ext]
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
    id=hashlib.sha256(data).hexdigest()
    try:cached=asset(id)
    except HTTPException:cached=None
    if cached:
        def still_available():
            remote=Path(cached['remote'])
            try:
                with requests.get(BASE+'/view',params={'filename':remote.name,'subfolder':str(remote.parent).replace('\\','/') if str(remote.parent)!='.' else '', 'type':'input'},headers={'Range':'bytes=0-63'},stream=True,timeout=15) as r:
                    return r.status_code in [200,206]
            except requests.RequestException:return False
        if await asyncio.to_thread(still_available):return {k:v for k,v in cached.items() if k!='remote'}
    local=PRIVATE/'uploads'/(id+ext);local.write_bytes(data)
    def transfer():
        try:
            with local.open('rb') as stream:
                r=requests.post(BASE+'/upload/image',files={'image':('yingxu-'+id[:24]+ext,stream,file.content_type)},data={'overwrite':'false'},timeout=(15,180))
            r.raise_for_status();out=r.json()
        except (requests.RequestException,ValueError):raise HTTPException(502,'素材未能上传到算力卡，请检查卡是否在线后重试。')
        a=dict(id=id,kind=kind,name=(file.filename or '')[:150],bytes=size,remote=(out.get('subfolder','')+'/'+out['name']).lstrip('/'))
        with lock,database() as db:db.execute('INSERT OR REPLACE INTO assets VALUES (?,?)',(id,json.dumps(a,ensure_ascii=False)))
        return {k:v for k,v in a.items() if k!='remote'}
    return await asyncio.to_thread(transfer)

class Submission(BaseModel):
    model_config=ConfigDict(extra='forbid')
    workflow_id:str
    source_hash:str|None=None
    prompt:str=Field(default='',max_length=6000)
    negative:str=Field(default='',max_length=2000)
    settings:dict=Field(default_factory=dict)
    asset_ids:list[str]=Field(default_factory=list,max_length=64)
    catalog_values:dict=Field(default_factory=dict,max_length=256)
    catalog_texts:dict=Field(default_factory=dict,max_length=128)
    catalog_assets:dict[str,str]=Field(default_factory=dict,max_length=64)
    api_profiles:dict=Field(default_factory=dict)
    token:str=Field(min_length=8,max_length=100)

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
        try:graph=bind_api_profiles(w['id'],build_graph(w['id'],body.prompt,body.negative,s,aa,id),body.api_profiles)
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
        geometry=points_geometry(spec,checked_values,records)
        records={slot:ensure_remote(record) for slot,record in records.items()}
        id=uuid.uuid4().hex
        graph,values,texts=schema_adapters.build(spec,checked_values,body.catalog_texts,records,body.api_profiles,id,body.prompt,body.negative,geometry=geometry)
    except FileNotFoundError:raise HTTPException(503,'缺少此工作流的执行模板，请核对部署文件。') from None
    except (ValueError,KeyError,TypeError) as error:raise HTTPException(400,str(error)) from None
    require_api_keys(graph,spec)
    j=dict(id=id,token=body.token,workflow_id=spec['id'],prompt=body.prompt,negative=body.negative,settings={},
           catalog_values=values,catalog_texts=texts,catalog_assets=dict(body.catalog_assets),schema_spec=copy.deepcopy(spec),
           asset_ids=[body.catalog_assets[slot['id']] for slot in slots if slot['id'] in body.catalog_assets],
           status='submitting',stage='正在提交到算力卡',started=time.time()*1000,ended=None,outputs=[],graph=graph,prompt_id=None,error=None)
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

class Rerun(BaseModel):
    model_config=ConfigDict(extra='forbid')
    token:str=Field(min_length=8,max_length=100)

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
        if 'seed' in settings:
            old_seed=settings['seed']
            settings['seed']=(old_seed+1+secrets.randbelow(2**48-1))%(2**48)
        graph=copy.deepcopy(original['graph'])
        if original['workflow_id']=='local-card-2':
            graph['536']['inputs']['seed']=settings['seed']
            graph['518:489']['inputs']['switch']=True
        elif original['workflow_id']=='local-card-1':
            graph['476']['inputs']['seed']=settings['seed']
        elif original['workflow_id']=='local-card-85':
            for key in ['58','63']:graph[key]['inputs']['seed']=settings['seed']
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
            graph['80']['inputs']['seed']=settings['seed']%(2**32)
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
        records={slot:ensure_remote(asset(key)) for slot,key in original.get('catalog_assets',{}).items()}
        new_id=uuid.uuid4().hex
        try:graph,values=schema_adapters.rerun(original,records,new_id)
        except (ValueError,KeyError,TypeError) as error:raise HTTPException(409,'原工作流的执行绑定无法恢复：'+str(error)) from None
        j={**copy.deepcopy(original),'id':new_id,'token':body.token,'catalog_values':values,'graph':graph,
           'status':'submitting','stage':'正在提交到算力卡','started':time.time()*1000,'ended':None,'outputs':[],
           'prompt_id':None,'error':None,'rerun_of':id}
        for key in ('cancel_requested','cancel_sent','cancel_error','connection_error','progress'):j.pop(key,None)
        db.execute('INSERT INTO jobs VALUES (?,?,?)',(new_id,body.token,json.dumps(j,ensure_ascii=False)))
    return dispatch(j)

@app.get('/api/assets/{id}/file')
def asset_content(id:str):
    a=asset(id);path=asset_file(a)
    return FileResponse(path,media_type=mimetypes.guess_type(str(path))[0],filename=a['name'],content_disposition_type='inline')

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
