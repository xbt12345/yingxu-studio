"""Independent real-media checks of Review87's pre-upload geometry boundary."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import av
from PIL import Image
import pytest

import schema_adapters as runtime
from public_fixtures import isolated_server
server = isolated_server("_test_review87_server_geometry_server")
from scripts.review87_video_controls import POLICIES as VIDEO_POLICIES, reviewed_video_controls, finalize_video_schema
from scripts.review87_flash_controls import POLICIES as FLASH_POLICIES, reviewed_flash_controls, finalize_flash_schema
from scripts.review87_infinite_controls import (
    REFERENCE_GEOMETRY_POLICIES, finalize_infinite_schema, map_speaker_regions,
)

BOXES = [dict(x=.08, y=.15, width=.3, height=.7), dict(x=.6, y=.18, width=.33, height=.65)]


def independent_spec(wid):
    """Before/after builder both exercise the actual finalizer and real template."""
    spec = deepcopy(runtime.manifest(wid))
    template = json.loads(runtime.template_path(spec).read_text("utf-8"))
    if wid in VIDEO_POLICIES:
        new = reviewed_video_controls(wid)
        spec["controls"] = spec["controls"] + [f for f in new if f["id"] not in {old["id"] for old in spec["controls"]}]
        spec = finalize_video_schema(spec, template=template)
    elif wid in FLASH_POLICIES:
        new = reviewed_flash_controls(wid)
        spec["controls"] = spec["controls"] + [f for f in new if f["id"] not in {old["id"] for old in spec["controls"]}]
        spec = finalize_flash_schema(spec, template=template)
    elif wid in REFERENCE_GEOMETRY_POLICIES:
        spec = finalize_infinite_schema(spec, template)
    return spec


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    directory = tmp_path_factory.mktemp("review87_server_geometry")
    uploads = directory/"uploads"
    uploads.mkdir()
    records = {}
    for width, height in ((638,360), (1920,1080), (64,64)):
        id = hashlib.sha256(f"review87-video-{width}x{height}".encode()).hexdigest()
        path = uploads/(id+".mkv")
        with av.open(str(path), "w") as container:
            stream = container.add_stream("ffv1", rate=16)
            stream.width, stream.height, stream.pix_fmt = width, height, "yuv420p"
            frame = av.VideoFrame(width,height,"yuv420p")
            for plane in frame.planes:
                plane.update(bytes(plane.buffer_size))
            for packet in stream.encode(frame):
                container.mux(packet)
            for packet in stream.encode():
                container.mux(packet)
        records[("video",width,height)] = dict(id=id,kind="video",width=999999,height=999999)
    for width,height in ((1920,1080), (1000,2000), (2000,16), (832,480)):
        id = hashlib.sha256(f"review87-image-{width}x{height}".encode()).hexdigest()
        Image.new("RGB",(width,height),(38,41,59)).save(uploads/(id+".png"))
        records[("image",width,height)] = dict(id=id,kind="image",width=1,height=1)
    id = hashlib.sha256(b"review87-exif-rotation6").hexdigest()
    exif = Image.Exif();exif[274]=6
    Image.new("RGB",(64,128),(38,41,59)).save(uploads/(id+".jpg"),exif=exif)
    records["exif"] = dict(id=id,kind="image")
    id = hashlib.sha256(b"review87-corrupt-image").hexdigest()
    (uploads/(id+".png")).write_bytes(b"not an image")
    records["corrupt-image"] = dict(id=id,kind="image")
    id = hashlib.sha256(b"review87-corrupt-video").hexdigest()
    (uploads/(id+".mkv")).write_bytes(b"not a video")
    records["corrupt-video"] = dict(id=id,kind="video")
    return directory,records


@pytest.mark.parametrize("wid",sorted(VIDEO_POLICIES))
@pytest.mark.parametrize("width,height",[(0,0),(640,480),(640,0),(0,480)])
def test_real_video_precheck_preserves_native_binding_and_returns_no_point_editor(media,monkeypatch,wid,width,height):
    directory,records=media
    monkeypatch.setattr(server,"PRIVATE",directory)
    spec,p=independent_spec(wid),VIDEO_POLICIES[wid]
    values={p["widthId"]:width,p["heightId"]:height}
    assert server.points_geometry(spec,values,{p["loader"]:records[("video",1920,1080)]}) is None
    # Reuse the real generic build; only external media/API boundaries are absent.
    spec.update(texts=[],media=[],apiProfiles=[])
    values.update({f["id"]:314159 for f in spec["controls"] if f.get("kind")=="seed"})
    graph,_,_=runtime.build(spec,values,{}, {},{},"review87-independent")
    assert graph[p["loader"]]["inputs"]["custom_width"] == width
    assert graph[p["loader"]]["inputs"]["custom_height"] == height
    assert graph[p["layer"]]["inputs"]["scale_to_side"] == ("None" if width or height else "longest")
    assert not any(n.get("class_type")=="PointsEditor" for n in graph.values())


@pytest.mark.parametrize("wid",sorted(VIDEO_POLICIES))
def test_each_model_effective_overflow_is_blocked_using_decoded_dimensions(media,monkeypatch,wid):
    directory,records=media
    monkeypatch.setattr(server,"PRIVATE",directory)
    p=VIDEO_POLICIES[wid]
    with pytest.raises(ValueError,match="模型处理宽高"):
        server.points_geometry(independent_spec(wid),{p["widthId"]:0,p["heightId"]:p["modelMaximum"]},
                               {p["loader"]:records[("video",1920,1080)]})


@pytest.mark.parametrize("wid",sorted(FLASH_POLICIES))
def test_flash_real_video_loader_dimensions_and_small_size_rejection(media,monkeypatch,wid):
    directory,records=media
    monkeypatch.setattr(server,"PRIVATE",directory)
    spec,p=independent_spec(wid),FLASH_POLICIES[wid]
    source={p["loader"]:records[("video",1920,1080)]}
    assert server.points_geometry(spec,{},source) is None
    assert server.points_geometry(spec,{p["loader"]+":custom_width":640,p["loader"]+":custom_height":480},source) is None
    with pytest.raises(ValueError,match="过小|至少"):
        server.points_geometry(spec,{p["loader"]+":custom_width":1,p["loader"]+":custom_height":1},source)


@pytest.mark.parametrize("wid",("local-card-99","local-card-100","local-card-101"))
def test_infinite_uses_real_image_or_video_metadata_instead_of_record_width_height(media,monkeypatch,wid):
    directory,records=media
    monkeypatch.setattr(server,"PRIVATE",directory)
    spec=independent_spec(wid);p=REFERENCE_GEOMETRY_POLICIES[wid]
    original=records[(p["mediaKind"],1920,1080)]
    geometry=server.points_geometry(spec,{"321:value":640},{p["slotId"]:original})
    assert geometry["original"]==dict(width=1920,height=1080)
    assert geometry["target"]==dict(width=640,height=368)
    assert geometry["workflowId"]==wid
    assert geometry["crop"]["width"]<1
    assert geometry["crop"]["height"]==pytest.approx(1)


def test_infinite_picture_geometry_matches_native_loadimage_exif_transpose(media,monkeypatch):
    directory,records=media
    monkeypatch.setattr(server,"PRIVATE",directory)
    result=server.points_geometry(independent_spec("local-card-101"),{"321:value":640},{"284":records["exif"]})
    assert result["original"]==dict(width=128,height=64)
    assert result["target"]==dict(width=640,height=320)


def test_source_regions_map_through_the_real_processing_crop_once(media,monkeypatch):
    directory,records=media
    monkeypatch.setattr(server,"PRIVATE",directory)
    geometry=server.points_geometry(independent_spec("local-card-101"),{"321:value":640},{"284":records[("image",1920,1080)]})
    mapped=map_speaker_regions(BOXES,geometry)
    crop=geometry["crop"]
    assert mapped[0]["x"]!=BOXES[0]["x"]
    for original,result in zip(BOXES,mapped):
        assert result["x"]==pytest.approx((original["x"]-crop["x"])/crop["width"])
        assert result["width"]==pytest.approx(original["width"]/crop["width"])
        assert result["y"]==pytest.approx(original["y"])
        assert result["height"]==pytest.approx(original["height"])
    tampered=deepcopy(geometry);tampered["sourceHash"]="0"*64
    with pytest.raises(ValueError,match="无法确认"):
        map_speaker_regions(BOXES,tampered)


@pytest.mark.parametrize("wid",("local-card-99","local-card-101"))
def test_invalid_skinny_source_is_rejected_even_when_client_size_metadata_claims_normal_shape(media,monkeypatch,wid):
    directory,records=media
    monkeypatch.setattr(server,"PRIVATE",directory)
    source={**records[("image",2000,16)],"width":832,"height":480}
    with pytest.raises(ValueError,match="超出模型范围"):
        server.points_geometry(independent_spec(wid),{}, {"284":source})


@pytest.mark.parametrize("wid,key",[("local-card-24","corrupt-video"),("local-card-118","corrupt-video"),("local-card-101","corrupt-image")])
def test_unreadable_actual_source_gets_actionable_error(media,monkeypatch,wid,key):
    directory,records=media
    monkeypatch.setattr(server,"PRIVATE",directory)
    spec=independent_spec(wid)
    p=spec.get("videoGeometryPolicy") or spec.get("videoSizePolicy") or spec["infiniteReferenceGeometry"]
    slot=p.get("loader") or p.get("slotId")
    with pytest.raises(ValueError,match="重新导入"):
        server.points_geometry(spec,{}, {slot:records[key]})


@pytest.mark.parametrize("wid",("local-card-24","local-card-118","local-card-101"))
def test_absent_geometry_source_never_uses_client_dimensions(wid):
    with pytest.raises(ValueError,match="原始素材"):
        server.points_geometry(independent_spec(wid),{"width":640,"height":480},{})


@pytest.mark.parametrize("wid,source_key,values,expected",[
    ("local-card-24",("video",1920,1080),{"3751:custom_width":0,"3751:custom_height":8096},"模型处理宽高"),
    ("local-card-118",("video",1920,1080),{"13:custom_width":1,"13:custom_height":1},"过小"),
    ("local-card-101",("image",2000,16),{"194:speaker_regions":json.dumps(BOXES)},"超出模型范围"),
])
def test_real_submission_rejects_geometry_before_remote_upload_audio_remux_persistence_or_gpu(media,monkeypatch,wid,source_key,values,expected):
    directory,records=media
    monkeypatch.setattr(server,"PRIVATE",directory)
    spec=independent_spec(wid)
    p=spec.get("videoGeometryPolicy") or spec.get("videoSizePolicy") or spec["infiniteReferenceGeometry"]
    slot=p.get("loader") or p.get("slotId")
    # Narrow only unrelated boundary inputs; preserve all real controls/templates.
    original_slot=next(s for s in spec["media"] if s["id"]==slot)
    spec.update(media=[original_slot],texts=[],apiProfiles=[])
    source=records[source_key]
    monkeypatch.setattr(server,"asset",lambda id:source if id==source["id"] else pytest.fail("Wrong source ID"))
    calls=[]
    def forbidden(name):
        def method(*args,**kwargs):
            calls.append(name)
            pytest.fail("Geometry rejection must precede "+name)
        return method
    for name in ("ensure_remote","schema_vhs_assets","source_audio_presence","persist_new_job","dispatch"):
        monkeypatch.setattr(server,name,forbidden(name))
    supplied={f["id"]:314159 for f in spec["controls"] if f.get("kind")=="seed"}
    supplied.update(values)
    body=server.Submission(workflow_id=wid,source_hash=spec["source_hash"],catalog_values=supplied,catalog_assets={slot:source["id"]},token="review87-independent-token")
    with pytest.raises(server.HTTPException) as caught:
        server.prepare_schema_submission(body,spec,None)
    assert caught.value.status_code==400
    assert expected in caught.value.detail
    assert calls==[]
