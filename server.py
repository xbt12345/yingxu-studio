"""Local-only MVP: persistent jobs, real ComfyUI execution and locally retained videos."""
import asyncio
import copy
import secrets
import mimetypes
import hashlib
import io
import json
import os
import sqlite3
import threading
import time
import uuid
import sys
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

# Isolate the Starlette version required by the machine's FastAPI installation.
sys.path.insert(0,str(Path(__file__).resolve().parent/'private/runtime'))

import requests
import websocket
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field
from adapters import ROOT, WORKFLOWS, manifest, settings_for, build_graph
from portable import embed_workflow

try:
    local_config=json.loads((ROOT/'private/backend.json').read_text('utf-8'))
except (OSError,ValueError):local_config={}
BASE = os.environ.get('CHENYU_CARD_URL',local_config.get('card_url','')).rstrip('/')
CLIENT = 'yingxu-local-mvp-v07'
PRIVATE = ROOT/'private'
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
        j=job(id);j.update(values);save(j)
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

def public_asset(a):
    try:asset_file(a);available=True
    except HTTPException:available=False
    return dict(id=a['id'],kind=a['kind'],name=a['name'],bytes=a['bytes'],src=f"/api/assets/{a['id']}/file",available=available)

def public(j):
    references=[]
    for id in j.get('asset_ids',[]):
        try:references.append(public_asset(asset(id)))
        except HTTPException:references.append(dict(id=id,available=False,kind='unknown',name='原素材缺失',src=''))
    return {**{k:v for k,v in j.items() if k not in ['token','graph','download_items']},'request_token':j['token'],'references':references}

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

def output_items(h):
    found=[]
    for node in h.get('outputs',{}).values():
        for key in ['images','gifs','videos']:
            for v in node.get(key,[]):
                if isinstance(v,dict) and v.get('filename','').lower().endswith('.mp4') and v.get('type')=='output':
                    if v not in found:found.append(v)
    return found

def collect(j,h):
    items=output_items(h)
    if not items:
        update(j['id'],status='failed',stage='没有视频输出',error='工作流已结束，但没有返回 MP4。请检查输出节点是否连接到保存视频。',ended=time.time()*1000)
        return
    update(j['id'],status='downloading',stage='正在取回视频',error=None)
    folder=PRIVATE/'outputs'/j['id'];folder.mkdir(exist_ok=True)
    outputs=[]
    for i,item in enumerate(items):
        dest=folder/f'{i}.mp4';tmp=dest.with_suffix('.part')
        if not dest.exists():
            with requests.get(BASE+'/view',params={k:item.get(k,'') for k in ['filename','subfolder','type']},stream=True,timeout=(15,120)) as r:
                r.raise_for_status()
                size=0
                with tmp.open('wb') as f:
                    for chunk in r.iter_content(1024*1024):
                        size+=len(chunk)
                        if size>1024*1024*1024:raise ValueError('返回的视频超过 1 GB，请缩短时长后重新生成。')
                        f.write(chunk)
                with tmp.open('rb') as f:head=f.read(64)
                if b'ftyp' not in head:raise ValueError('算力卡返回的文件不是有效 MP4，请检查视频保存节点。')
                tmp.replace(dest)
        embed_workflow(dest,j['graph'])
        outputs.append(dict(workflow_embedded=True,id=j['id']+'o'+str(i),type='video',src=f'/api/media/{j["id"]}/{i}.mp4',poster='',duration=j['settings'].get('duration'),bytes=dest.stat().st_size))
    receipt={k:h.get(k) for k in ['outputs','status']}
    (PRIVATE/'receipts'/f'{j["id"]}.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),'utf-8')
    update(j['id'],status='done',stage='已保存视频',outputs=outputs,ended=time.time()*1000,error=None)

def reconcile_unknown(j,q):
    candidates=[x for values in q.values() for x in values]
    for x in candidates:
        if len(x)>3 and x[3].get('yingxu_job_id')==j['id']:
            return update(j['id'],prompt_id=x[1],status='queued',stage='已找回任务',error=None)
    h=requests.get(BASE+'/history',params={'max_items':100},timeout=30).json()
    for pid,v in h.items():
        p=v.get('prompt',[])
        if len(p)>3 and p[3].get('yingxu_job_id')==j['id']:
            return update(j['id'],prompt_id=pid,status='queued',stage='已找回任务',error=None)
    return j

def poll_once():
    active=[j for j in jobs() if j['status'] not in ['done','failed','cancelled']]
    if not active:return
    q=requests.get(BASE+'/queue',timeout=15);q.raise_for_status();q=q.json()
    running={x[1] for x in q.get('queue_running',[])}
    pending=[x[1] for x in q.get('queue_pending',[])]
    for j in active:
        try:
            if not j.get('prompt_id'):
                if time.time()*1000-j['started']<90000:continue
                j=reconcile_unknown(j,q)
                if not j.get('prompt_id'):
                    update(j['id'],status='unknown',stage='提交状态待确认',error='连接中断，尚不能确认任务是否已提交。为防重复消耗，暂不重新提交；请检查算力卡队列。')
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
            elif pid in pending:update(j['id'],status='queued',stage=f'排队中 · 前面还有 {pending.index(pid)} 个任务',connection_error=None)
            elif j['status'] not in ['submitting','unknown']:
                update(j['id'],stage='正在核对算力卡任务记录',connection_error='任务暂未出现在队列或历史中，请保留此页；不会重复提交。')
        except (requests.RequestException,ValueError) as e:
            update(j['id'],connection_error='视频尚未取回，连接恢复后自动重试。' if j['status']=='downloading' else '连接暂时中断，正在重连；任务不会重复提交。')

def monitor():
    while not stopping.is_set():
        try:poll_once()
        except Exception:
            for j in jobs():
                if j['status'] not in ['done','failed','cancelled']:update(j['id'],connection_error='算力卡暂时不可达，正在重连；已完成文件保留在本地。')
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
                j=next((j for j in jobs() if j.get('prompt_id')==pid and j['status'] not in ['done','failed','cancelled']),None)
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
    threading.Thread(target=monitor,daemon=True).start()
    threading.Thread(target=listen,daemon=True).start()
    yield
    stopping.set()

app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None)

@app.middleware('http')
async def local_origin(request:Request,call_next):
    # This personal MVP binds loopback. Do not let another website submit GPU jobs.
    origin=request.headers.get('origin')
    allowed={f'http://127.0.0.1:{request.url.port}',f'http://localhost:{request.url.port}'}
    allowed.update(x.strip().rstrip('/') for x in os.environ.get('YINGXU_ALLOWED_ORIGINS','').split(',') if x.strip())
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

@app.get('/api/workflows')
def list_workflows():return WORKFLOWS

@app.get('/api/health')
def health():
    try:
        r=requests.get(BASE+'/queue',timeout=8);r.raise_for_status()
        return dict(online=True,queue=len(r.json().get('queue_pending',[])),running=len(r.json().get('queue_running',[])))
    except requests.RequestException:return dict(online=False,message='请确认算力卡正在运行且地址未变化。')

@app.post('/api/assets')
async def upload(file:UploadFile=File(...)):
    ext=Path(file.filename or '').suffix.lower()
    if ext not in ['.png','.jpg','.jpeg','.webp','.mp4']:raise HTTPException(400,'支持 PNG、JPG、WebP 图片和 MP4 视频。')
    chunks=[];size=0
    while chunk:=await file.read(1024*1024):
        size+=len(chunk)
        if size>200*1024*1024:raise HTTPException(413,'单个素材上限 200 MB，请压缩或截短后重试。')
        chunks.append(chunk)
    data=b''.join(chunks)
    kind='video' if ext=='.mp4' else 'image'
    if kind=='image':
        try:
            with Image.open(io.BytesIO(data)) as im:im.verify()
        except Exception:raise HTTPException(400,'图片文件损坏或格式不符，请重新导出 PNG / JPG。')
    elif b'ftyp' not in data[:64]:raise HTTPException(400,'请使用有效的 MP4 视频。')
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
    prompt:str=Field(min_length=1,max_length=6000)
    negative:str=Field(default='',max_length=2000)
    settings:dict=Field(default_factory=dict)
    asset_ids:list[str]=Field(default_factory=list,max_length=9)
    token:str=Field(min_length=8,max_length=100)

@app.post('/api/jobs')
def submit(body:Submission):
    with lock,database() as db:
        old=db.execute('SELECT data FROM jobs WHERE token=?',(body.token,)).fetchone()
        if old:return public(json.loads(old[0]))
        w=manifest(body.workflow_id)
        if not w:raise HTTPException(400,'此工作流尚未接入。')
        try:s=settings_for(w,body.settings)
        except ValueError as e:raise HTTPException(400,str(e))
        if not body.prompt.strip():raise HTTPException(400,'请填写希望生成或修改的画面。')
        if body.negative.strip() and not w['negative']:raise HTTPException(400,'此工作流没有反向提示词输入，请把要求写入镜头描述。')
        aa=[asset(i) for i in body.asset_ids]
        for kind,lo,hi in [('image','minImages','maxImages'),('video','minVideos','maxVideos')]:
            n=sum(a['kind']==kind for a in aa)
            if not w[lo]<=n<=w[hi]:raise HTTPException(400,f'{w["name"]}需要 {w[lo]}–{w[hi]} 份'+('图片' if kind=='image' else '视频')+'素材。')
        aa=[ensure_remote(a) for a in aa]
        id=uuid.uuid4().hex
        graph=build_graph(w['id'],body.prompt,body.negative,s,aa,id)
        j=dict(id=id,token=body.token,workflow_id=w['id'],prompt=body.prompt,negative=body.negative,settings=s,asset_ids=body.asset_ids,status='submitting',stage='正在提交到算力卡',started=time.time()*1000,ended=None,outputs=[],graph=graph,prompt_id=None,error=None)
        db.execute('INSERT INTO jobs VALUES (?,?,?)',(id,body.token,json.dumps(j,ensure_ascii=False)))
    return dispatch(j)

def dispatch(j):
    id=j['id'];graph=j['graph']
    try:
        r=requests.post(BASE+'/prompt',json={'prompt':graph,'client_id':CLIENT,'extra_data':{'yingxu_job_id':id}},timeout=(15,60))
        if r.status_code>=400:
            detail=r.json();(PRIVATE/'receipts'/f'{id}-validation.json').write_text(json.dumps(detail,ensure_ascii=False,indent=2),'utf-8')
            return public(update(id,status='failed',stage='工作流校验失败',error=friendly(json.dumps(detail.get('node_errors',detail),ensure_ascii=False)[:500]),ended=time.time()*1000))
        out=r.json()
        return public(update(id,prompt_id=out['prompt_id'],status='queued',stage='等待算力卡执行'))
    except (requests.RequestException,ValueError,KeyError):
        return public(update(id,status='unknown',stage='正在确认提交状态',error='连接中断，正在核对任务，暂不重复提交。'))

class Rerun(BaseModel):
    model_config=ConfigDict(extra='forbid')
    token:str=Field(min_length=8,max_length=100)

@app.post('/api/jobs/{id}/rerun')
def rerun(id:str,body:Rerun):
    with lock,database() as db:
        previous=db.execute('SELECT data FROM jobs WHERE token=?',(body.token,)).fetchone()
        if previous:return public(json.loads(previous[0]))
        original=job(id)
        if original['status'] not in ['done','failed','cancelled']:
            raise HTTPException(409,'原任务尚未结束，请等待结果后再试。')
        aa=[ensure_remote(asset(key)) for key in original['asset_ids']]
        new_id=uuid.uuid4().hex
        settings=copy.deepcopy(original['settings'])
        old_seed=settings['seed']
        settings['seed']=(old_seed+1+secrets.randbelow(2**48-1))%(2**48)
        graph=copy.deepcopy(original['graph'])
        seed_nodes=['55'] if original['workflow_id']=='h3-reference' else ['384','386']
        for key in seed_nodes:graph[key]['inputs']['noise_seed']=settings['seed']
        output='54' if original['workflow_id']=='h3-reference' else '443'
        graph[output]['inputs']['filename_prefix']='yingxu/'+new_id
        # Restore upstream files if the card was restarted; all other graph inputs stay intact.
        for ix,a in enumerate(a for a in aa if a['kind']=='image'):
            graph[f'upload_{ix}']['inputs']['image']=a['remote']
        if original['workflow_id']=='bernini-edit':
            graph['425']['inputs']['video']=next(a['remote'] for a in aa if a['kind']=='video')
        j=dict(id=new_id,token=body.token,workflow_id=original['workflow_id'],prompt=original['prompt'],negative=original['negative'],settings=settings,asset_ids=list(original['asset_ids']),status='submitting',stage='正在提交到算力卡',started=time.time()*1000,ended=None,outputs=[],graph=graph,prompt_id=None,error=None,rerun_of=id)
        db.execute('INSERT INTO jobs VALUES (?,?,?)',(new_id,body.token,json.dumps(j,ensure_ascii=False)))
    return dispatch(j)

@app.get('/api/assets/{id}/file')
def asset_content(id:str):
    a=asset(id);path=asset_file(a)
    return FileResponse(path,media_type=mimetypes.guess_type(str(path))[0],filename=a['name'],content_disposition_type='inline')

@app.get('/api/jobs/{id}/workflow')
def workflow_download(id:str):
    j=job(id)
    return JSONResponse(j['graph'],headers={'Content-Disposition':f'attachment; filename="yingxu-{id[:8]}-workflow-api.json"'})

@app.get('/api/jobs')
def get_jobs():return [public(j) for j in jobs()]
@app.get('/api/jobs/{id}')
def get_job(id:str):return public(job(id))
@app.post('/api/jobs/{id}/cancel')
def cancel(id:str):
    j=job(id)
    if j['status'] in ['done','failed','cancelled']:return public(j)
    if j.get('cancel_requested'):return public(j)
    pid=j.get('prompt_id')
    if not pid:raise HTTPException(409,'正在确认提交记录，取得任务编号后可取消。')
    try:
        response=requests.get(BASE+'/queue',timeout=15);response.raise_for_status();q=response.json()
        pending={x[1] for x in q.get('queue_pending',[])}
        running={x[1] for x in q.get('queue_running',[])}
        if pid not in pending|running:raise HTTPException(409,'任务已离开队列，正在核对结果。请稍后查看状态。')
        # The task-scoped API checks identity atomically. Never use global /interrupt.
        response=requests.post(BASE+'/api/jobs/'+pid+'/cancel',timeout=15)
        if response.status_code in (404,405):
            if pid in running:raise HTTPException(409,'当前算力卡不支持按任务取消运行，请升级 ComfyUI 后重试。')
            requests.post(BASE+'/queue',json={'delete':[pid]},timeout=15).raise_for_status()
        else:
            response.raise_for_status()
            if response.json().get('cancelled') is not True:
                raise HTTPException(409,'任务可能已完成，正在核对结果；尚未确认取消。')
        if pid in pending:
            response=requests.get(BASE+'/queue',timeout=15);response.raise_for_status();q=response.json()
            if pid not in {x[1] for x in q.get('queue_running',[])+q.get('queue_pending',[])}:
                return public(update(id,status='cancelled',stage='已取消任务',cancel_requested=True,ended=time.time()*1000))
        return public(update(id,status='cancelling',stage='正在取消任务',cancel_requested=True,connection_error=None))
    except (requests.RequestException,ValueError):raise HTTPException(502,'连接中断，尚未确认取消成功。请检查任务状态后重试；可能已经产生费用。')

@app.get('/api/media/{id}/{filename}')
def media(id:str,filename:str):
    j=job(id)
    if filename not in [f'{i}.mp4' for i in range(len(j.get('outputs',[])))]:raise HTTPException(404,'找不到视频。')
    p=PRIVATE/'outputs'/j['id']/filename
    if not p.is_file():raise HTTPException(404,'本地视频文件已被移除。')
    with lock:
        embed_workflow(p,j['graph'])
        current=job(id)
        index=int(filename.split('.')[0])
        out=current['outputs'][index]
        if not out.get('workflow_embedded') or out.get('bytes')!=p.stat().st_size:
            out.update(workflow_embedded=True,bytes=p.stat().st_size)
            update(id,outputs=current['outputs'])
    return FileResponse(p,media_type='video/mp4',filename=f'映序-{id[:8]}-{filename}',content_disposition_type='inline')

app.mount('/',StaticFiles(directory=ROOT/'public',html=True),name='site')

if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=int(os.environ.get('PORT','8770')))
