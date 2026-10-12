"""Baidu video jobs share the studio's durable history, ownership and billing."""
import base64
import io
import logging
import time
import uuid
from typing import Literal
from urllib.parse import urlsplit

import requests
from fastapi import HTTPException
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

import baidu_video


TERMINAL = {'done', 'failed', 'cancelled', 'abandoned'}


class CreationSubmission(BaseModel):
    model_config = ConfigDict(extra='forbid')
    model: Literal['baidu-sd2', 'baidu-sd2.5']
    kind: Literal['video'] = 'video'
    quality: Literal['480p', '720p', '1080p']
    count: int = Field(default=1, ge=1, le=1, strict=True)
    duration: int = Field(ge=4, le=30, strict=True)
    ratio: Literal['16:9', '9:16', 'adaptive']
    prompt: str = Field(min_length=1, max_length=6000)
    negative: str = Field(default='', max_length=0)
    mode: Literal['text', 'first_frame', 'reference_image'] = 'text'
    asset_ids: list[str] = Field(default_factory=list, max_length=9)
    reference_slots: list[int | None] = Field(default_factory=list, max_length=9)
    token: str = Field(min_length=8, max_length=100)


class CreationJobs:
    def __init__(self, backend):
        self.backend = backend

    def _references(self, body):
        b = self.backend
        if not body.prompt.strip() or '\x00' in body.prompt:
            raise HTTPException(400, '请填写有效的画面描述。')
        expected = {'text': [], 'first_frame': [0]}
        slots = body.reference_slots
        if len(slots) != len(body.asset_ids) or any(type(slot) is not int and slot is not None for slot in slots):
            raise HTTPException(400, '参考图片位置与素材不匹配，请重新选择。')
        if body.mode in expected and slots != expected[body.mode]:
            raise HTTPException(400, '纯文本无需参考图；首帧模式需要一张对应图片。')
        if body.mode == 'reference_image' and (not slots or any(slot is not None for slot in slots)):
            raise HTTPException(400, '参考图模式需要图片，请重新选择素材。')
        references = []
        for identifier, slot in zip(body.asset_ids, slots):
            source = b.asset(identifier)
            if source.get('kind') != 'image':
                raise HTTPException(400, '这两个模型当前接入的是图片参考，请选择图片素材。')
            path = b.asset_file(source)
            # Send the actual uploaded image, never an authenticated localhost URL.
            with Image.open(path) as image:
                data = io.BytesIO()
                image.convert('RGB').save(data, format='JPEG', quality=95)
            references.append({'slot': slot, 'data_url': 'data:image/jpeg;base64,' +
                               base64.b64encode(data.getvalue()).decode('ascii')})
        return references

    def submit(self, body, original_id=None):
        b = self.backend
        b.platform_bridge.prepare_creation_submission(body, original_id)
        with b.database() as db:
            old = db.execute('SELECT data FROM jobs WHERE token=?', (body.token,)).fetchone()
        if old:
            return b.public(b.platform_bridge.checked_replay(old[0]))
        try:
            payload = baidu_video.build_payload(body.model_dump(mode='json'), self._references(body))
        except (ValueError, OSError, Image.DecompressionBombError) as error:
            raise HTTPException(400, str(error) or '参考图片无法读取，请重新导入。') from None
        settings = {key: getattr(body, key) for key in ('kind', 'quality', 'count', 'duration', 'ratio', 'mode')}
        record = dict(id=uuid.uuid4().hex, token=body.token, backend='baidu-video', creation=True,
                      workflow_id=body.model, model=body.model, mode=body.mode,
                      prompt=body.prompt, negative='', settings=settings, asset_ids=list(body.asset_ids),
                      reference_slots=list(body.reference_slots), status='submitting',
                      stage='正在提交视频任务', started=time.time()*1000, ended=None,
                      outputs=[], graph={}, prompt_id=None, error=None)
        if original_id:
            record['rerun_of'] = original_id
        record = b.persist_new_job(record)
        if record.pop('_platform_replay', False):
            return b.public(record)
        return self._dispatch(record, payload)

    def _dispatch(self, record, payload):
        b = self.backend
        identifier = record['id']
        try:
            task_id = baidu_video.submit(payload)
            return b.public(b.update(identifier, prompt_id=task_id, status='queued',
                                     stage='等待视频生成', error=None, connection_error=None))
        except ValueError as error:
            return b.public(b.update(identifier, status='failed', stage='视频接口拒绝任务',
                                     error=str(error), failure_phase='submission', ended=time.time()*1000))
        except (requests.RequestException, KeyError, TypeError):
            # A timeout may follow a successful upstream charge. Never POST twice.
            return b.public(b.update(identifier, status='unknown', stage='提交状态待确认',
                                     error='未能确认是否提交成功，请先在供应商任务记录中核对；本站不会自动重复提交。'))

    def _collect(self, record, result):
        b = self.backend
        identifier = record['id']
        with b.output_collection(identifier) as acquired:
            if not acquired:
                return
            b.update(identifier, status='downloading', stage='正在取回作品', error=None,
                     connection_error=None, failure_phase=None, output_failure_code=None)
            folder = b.PRIVATE/'outputs'/identifier
            target = folder/'0.mp4'
            temporary = folder/'0.part'
            try:
                folder.mkdir(parents=True, exist_ok=True)
                if not target.is_file():
                    url = result.get('video_url')
                    parsed = urlsplit(url or '')
                    if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password:
                        raise ValueError('视频接口没有返回有效的作品地址。')
                    with requests.get(url, stream=True, timeout=(15, 120)) as response:
                        response.raise_for_status()
                        size = 0
                        with temporary.open('wb') as output:
                            for chunk in response.iter_content(1024*1024):
                                size += len(chunk)
                                if size > 1024*1024*1024:
                                    raise ValueError('返回的作品超过允许大小。')
                                output.write(chunk)
                    with temporary.open('rb') as output:
                        if b'ftyp' not in output.read(64):
                            raise ValueError('视频接口返回的作品不是有效 MP4。')
                    facts = b.probe_output_metadata(temporary, 'video')
                    if not facts.get('width') or not facts.get('height'):
                        raise ValueError('视频作品无法读取，请重新取回。')
                    temporary.replace(target)
                facts = b.probe_output_metadata(target, 'video')
                output = {'id': identifier+'o0', 'type': 'video', 'src': f'/api/media/{identifier}/0.mp4',
                          'poster': '', 'bytes': target.stat().st_size, 'duration': None, **facts,
                          'metadata_source': 'saved-file', 'workflow_embedded': False}
                b.update(identifier, status='done', stage='已保存作品', outputs=[output],
                         error=None, failure_phase=None, output_failure_code=None,
                         connection_error=None, ended=time.time()*1000)
            except requests.RequestException:
                b.update(identifier, status='downloading', stage='作品等待取回',
                         connection_error='作品已生成，连接恢复后自动取回；不会重新生成。')
            except (ValueError, OSError, b.av.error.FFmpegError) as error:
                b.output_failure(record, error)
            finally:
                try:temporary.unlink(missing_ok=True)
                except OSError:pass

    def monitor(self):
        b = self.backend
        while not b.stopping.is_set():
            try:self.poll_once()
            except Exception as error:
                logging.getLogger('yingxu.creation').warning('Video task monitoring paused (%s)', type(error).__name__)
            b.stopping.wait(3)

    def poll_once(self):
        b = self.backend
        records = [record for record in b.jobs() if record.get('creation') and
                   record.get('prompt_id') and record['status'] not in TERMINAL]
        for record in records:
            try:
                result = baidu_video.query(record['prompt_id'])
                status = result['status']
                if status == 'done':
                    self._collect(record, result)
                elif status == 'failed':
                    b.update(record['id'], status='failed', stage='视频生成失败',
                             error=result.get('error') or '视频服务未能完成本次生成。',
                             failure_phase='generation', connection_error=None, ended=time.time()*1000)
                elif status == 'cancelled':
                    b.update(record['id'], status='cancelled', stage='视频任务已取消', error=None,
                             connection_error=None, ended=time.time()*1000)
                else:
                    b.update(record['id'], status=status, stage='等待视频生成' if status == 'queued' else '视频生成中',
                             connection_error=None)
            except (requests.RequestException, ValueError, KeyError, TypeError):
                b.update(record['id'], connection_error='视频服务暂时无法查询，连接恢复后自动重试；不会重复提交。')

    def rerun(self, identifier, body):
        b = self.backend
        record = b.job(identifier)
        if record.get('failure_phase') == 'output':
            raise HTTPException(409, '视频已生成，请重新取回作品。')
        if record['status'] not in TERMINAL:
            raise HTTPException(409, '原任务尚未结束，请等待或核对原任务后再生成。')
        settings = record['settings']
        request = CreationSubmission(model=record['model'], quality=settings['quality'],
                                     duration=settings['duration'], ratio=settings['ratio'],
                                     prompt=record['prompt'], mode=settings['mode'],
                                     asset_ids=record['asset_ids'], reference_slots=record['reference_slots'],
                                     token=body.token)
        return self.submit(request, identifier)

    def retrieve(self, identifier):
        b = self.backend
        record = b.job(identifier)
        if record['status'] != 'failed' or record.get('failure_phase') != 'output' or not record.get('prompt_id'):
            raise HTTPException(409, '只有原视频的取回或保存失败可以重新取回。')
        try:
            result = baidu_video.query(record['prompt_id'])
            if result['status'] != 'done':
                raise HTTPException(409, '供应商尚未返回原任务的已完成作品，请稍后再取回。')
            self._collect(record, result)
        except (requests.RequestException, ValueError, KeyError, TypeError):
            raise HTTPException(503, '暂时无法查询原视频，请稍后重新取回；不会重新生成。') from None
        return b.public(b.job(identifier))

    def cancel(self, identifier):
        record = self.backend.job(identifier)
        if record['status'] in TERMINAL:
            return self.backend.public(record)
        # No upstream cancellation contract was supplied for these two models.
        raise HTTPException(409, '该视频接口尚未提供已确认的取消方式，任务会继续查询；如需停止等待请先在供应商处核对任务。')


def install_creation(app, backend):
    integration = CreationJobs(backend)

    @app.post('/api/creation/jobs')
    def create(body: CreationSubmission):
        return integration.submit(body)

    return integration
