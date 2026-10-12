"""Real Scail submission geometry must reject before upload/inference."""
from copy import deepcopy
import hashlib
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

import av
import pytest
import schema_adapters as runtime
from public_fixtures import isolated_server
server = isolated_server("_test_review88_scail_server_geometry_server")
from scripts.review86_scail_controls import CONTRACTS,derive_scail_processing_geometry


@pytest.fixture(scope='module')
def media(tmp_path_factory):
    directory=tmp_path_factory.mktemp('review88_scail_server')
    uploads=directory/'uploads';uploads.mkdir()
    records={}
    for width,height in ((2000,16),(848,480)):
        id=hashlib.sha256(f'review88-scail-{width}x{height}'.encode()).hexdigest()
        with av.open(str(uploads/(id+'.mkv')),'w') as container:
            stream=container.add_stream('ffv1',rate=24)
            stream.width,stream.height,stream.pix_fmt=width,height,'yuv420p'
            frame=av.VideoFrame(width,height,'yuv420p')
            for plane in frame.planes:plane.update(bytes(plane.buffer_size))
            for packet in stream.encode(frame):container.mux(packet)
            for packet in stream.encode():container.mux(packet)
        # Deliberately false stored/client dimensions must never own the check.
        records[(width,height)]={'id':id,'kind':'video','width':512,'height':512}
    return directory,records


def spec(wid):
    return deepcopy(runtime.manifest(wid))


def seeds(spec):
    return {f['id']:314159 for f in spec['controls'] if f.get('kind')=='seed'}


@pytest.mark.parametrize('wid',sorted(CONTRACTS))
def test_actual_prepare_submission_blocks_skinny_default_before_any_remote_or_gpu_work(media,monkeypatch,wid):
    directory,records=media
    monkeypatch.setattr(server,'PRIVATE',directory)
    s=spec(wid);c=CONTRACTS[wid];record=records[(2000,16)]
    # Only remove unrelated boundary requirements; keep real controls/source/API.
    source_slot=next(slot for slot in s['media'] if slot['id']==c['loader'])
    s.update(media=[source_slot],texts=[],apiProfiles=[])
    monkeypatch.setattr(server,'asset',lambda id:record if id==record['id'] else pytest.fail('Unexpected asset'))
    calls=[]
    def forbidden(name):
        def call(*args,**kwargs):
            calls.append(name)
            pytest.fail('SCAIL geometry rejection must precede '+name)
        return call
    for name in ('source_audio_presence','schema_vhs_assets','ensure_remote','persist_new_job','dispatch'):
        monkeypatch.setattr(server,name,forbidden(name))
    values={**seeds(s),c['length']+':value':1024,c['embeds']+':width':0,c['embeds']+':height':0}
    body=server.Submission(workflow_id=wid,source_hash=s['source_hash'],catalog_values=values,
                           catalog_assets={c['loader']:record['id']},token='review88-scail-test-token')
    with pytest.raises(server.HTTPException) as caught:
        server.prepare_schema_submission(body,s,None)
    assert caught.value.status_code==400
    assert '小于64像素' in caught.value.detail
    assert calls==[]


@pytest.mark.parametrize('wid',sorted(CONTRACTS))
def test_normal_default_path_allows_native_rounding_without_changing_authored_layer(media,monkeypatch,wid):
    directory,records=media
    monkeypatch.setattr(server,'PRIVATE',directory)
    s=spec(wid);c=CONTRACTS[wid]
    values={**seeds(s),c['length']+':value':1536}
    checked=runtime.validate_values(s,values)
    assert server.points_geometry(s,checked,{c['loader']:records[(848,480)]}) is None
    facts=derive_scail_processing_geometry(s,checked,{'width':848,'height':480})
    assert facts['layerTarget']=={'width':1536,'height':880}
    assert facts['target']=={'width':1536,'height':864}
    s.update(media=[],texts=[],apiProfiles=[])
    graph,_,_=runtime.build(s,values,{}, {},{},'review88-scail-default')
    assert graph[c['scale']]['inputs']['round_to_multiple']=='16'
    assert graph[c['scale']]['inputs']['scale_to_length']==[c['length'],0]
    assert graph[c['length']]['inputs']['value']==1536
    assert graph[c['embeds']]['inputs']['width']==[c['scale'],3]
    assert graph[c['embeds']]['inputs']['height']==[c['scale'],4]


@pytest.mark.parametrize('wid',sorted(CONTRACTS))
def test_valid_512_pair_passes_even_for_skinny_source_and_reaches_model(media,monkeypatch,wid):
    directory,records=media
    monkeypatch.setattr(server,'PRIVATE',directory)
    s=spec(wid);c=CONTRACTS[wid]
    values={**seeds(s),c['embeds']+':width':512,c['embeds']+':height':512}
    checked=runtime.validate_values(s,values)
    assert server.points_geometry(s,checked,{c['loader']:records[(2000,16)]}) is None
    s.update(media=[],texts=[],apiProfiles=[])
    graph,_,_=runtime.build(s,values,{}, {},{},'review88-scail-custom')
    assert graph[c['scale']]['inputs']['round_to_multiple']=='32'
    assert graph[c['embeds']]['inputs']['width']==graph[c['reference']]['inputs']['width']==512
    assert graph[c['embeds']]['inputs']['height']==graph[c['reference']]['inputs']['height']==512


@pytest.mark.parametrize('wid',sorted(CONTRACTS))
def test_scail_precheck_requires_actual_video_instead_of_invented_dimensions(wid):
    s=spec(wid);c=CONTRACTS[wid]
    with pytest.raises(ValueError,match='原始素材'):
        server.points_geometry(s,{'width':512,'height':512},{})
    with pytest.raises(ValueError,match='参考视频'):
        server.points_geometry(s,{}, {c['loader']:{'kind':'image','width':512,'height':512}})
