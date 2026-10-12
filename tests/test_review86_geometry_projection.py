"""Cross-language review of real preview, graph binding and video metadata."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import av
import pytest

import schema_adapters as runtime
from public_fixtures import historical_path, isolated_server
server = isolated_server("_test_review86_geometry_projection_server")
from scripts.review86_ltx_controls import derive_ltx_processing_geometry, ltx_duration_info


def read(path):
    return json.loads((ROOT / path).read_text('utf-8'))


@pytest.fixture(scope='module')
def node_results():
    result = subprocess.run(['node', 'scripts/test_review86_geometry.mjs', '--fixtures'], cwd=ROOT,
                            capture_output=True, text=True, encoding='utf-8', check=True)
    return json.loads(result.stdout)


def offline_spec(number):
    spec = copy.deepcopy(runtime.manifest(f'local-card-{number}'))
    # Remove external asset/API boundary requirements only; production controls,
    # template, validation and concrete target binding stay intact.
    spec.update(texts=[], media=[], apiProfiles=[])
    return spec


def build(number, supplied=None, geometry=None):
    spec = offline_spec(number)
    values = {field['id']: 314159 for field in spec['controls'] if field.get('kind') == 'seed'}
    values.update(supplied or {})
    if number == 51:
        values['1095:points'] = json.dumps({'positive': [{'x': .5, 'y': .5}, {'x': 1, 'y': 1}], 'negative': []})
    return runtime.build(spec, values, {}, {}, {}, 'review86-independent', geometry=geometry)


@pytest.mark.parametrize('name', ['default-rounded-source', 'default-wide-source', 'custom-960x640',
                                  'custom-width-only', 'custom-height-only', 'negative-width',
                                  'undersized-pair', 'rounds-to-zero-pair', 'beyond-native-max',
                                  'native-legal-long-side-too-large', 'native-legal-long-side-too-small'])
def test_actual_node_python_geometry_agreement(node_results, name):
    case = next(row for row in node_results['geometry'] if row['name'] == name)
    spec = runtime.manifest('local-card-51')
    if case.get('invalid'):
        assert case.get('error')
        with pytest.raises(ValueError):
            derive_ltx_processing_geometry(spec, case['values'], *case['source'])
    else:
        actual = derive_ltx_processing_geometry(spec, case['values'], *case['source'])
        for key in ('source', 'layerTarget', 'target', 'crop', 'framePercent'):
            assert actual[key] == pytest.approx(case['result'][key])


@pytest.fixture(scope='module')
def video_dir(tmp_path_factory):
    directory = tmp_path_factory.mktemp('review86_geometry')
    uploads = directory / 'uploads'
    uploads.mkdir()
    records = {}
    for width, height in [(638, 360), (1920, 1080)]:
        identifier = hashlib.sha256(f'review86-{width}x{height}'.encode()).hexdigest()
        path = uploads / f'{identifier}.mkv'
        with av.open(str(path), mode='w') as container:
            stream = container.add_stream('ffv1', rate=25)
            stream.width, stream.height, stream.pix_fmt = width, height, 'yuv420p'
            frame = av.VideoFrame(width, height, 'yuv420p')
            for plane in frame.planes:
                plane.update(bytes(plane.buffer_size))
            for packet in stream.encode(frame):
                container.mux(packet)
            for packet in stream.encode():
                container.mux(packet)
        records[(width, height)] = {'id': identifier, 'kind': 'video'}
        with av.open(str(path)) as container:
            stream = container.streams.video[0]
            assert (stream.width, stream.height) == (width, height)
            assert float(stream.average_rate) == 25
    return directory, records


@pytest.mark.parametrize('name', ['default-rounded-source', 'default-wide-source', 'custom-960x640',
                                  'custom-width-only', 'custom-height-only'])
def test_server_real_video_dimensions_and_graph_tracking_space(node_results, video_dir, monkeypatch, name):
    directory, records = video_dir
    monkeypatch.setattr(server, 'PRIVATE', directory)
    case = next(row for row in node_results['geometry'] if row['name'] == name)
    spec = runtime.manifest('local-card-51')
    geometry = server.points_geometry(spec, case['values'], {'1084': records[tuple(case['source'])]})
    assert {axis: geometry[axis] for axis in ('width', 'height')} == case['result']['target']
    graph, _, _ = build(51, case['values'], geometry)
    custom = bool(case['values'].get('1084:custom_width') or case['values'].get('1084:custom_height'))
    assert graph['1064']['inputs']['scale_to_side'] == ('None' if custom else 'longest')
    assert graph['1058']['inputs']['scale_by'] == .5
    assert (graph['1095']['inputs']['width'], graph['1095']['inputs']['height']) == (geometry['width'], geometry['height'])
    points = json.loads(graph['1095']['inputs']['coordinates'])
    assert points == [{'x': round(geometry['width']*.5), 'y': round(geometry['height']*.5)},
                      {'x': geometry['width']-1, 'y': geometry['height']-1}]


@pytest.mark.parametrize('name', ['negative-width', 'undersized-pair', 'rounds-to-zero-pair', 'beyond-native-max',
                                  'native-legal-long-side-too-large', 'native-legal-long-side-too-small'])
def test_actual_submission_checks_invalid_dimensions_before_tracking(node_results, video_dir, monkeypatch, name):
    directory, records = video_dir
    monkeypatch.setattr(server, 'PRIVATE', directory)
    case = next(row for row in node_results['geometry'] if row['name'] == name)
    spec = runtime.manifest('local-card-51')
    supplied = {**case['values'], '1095:points': json.dumps({'positive': [{'x': .5, 'y': .5}], 'negative': []})}
    with pytest.raises(ValueError):
        checked = runtime.validate_values(spec, supplied)
        server.points_geometry(spec, checked, {'1084': records[tuple(case['source'])]})


@pytest.mark.parametrize('width,height,scale', [(1, 1, 1), (0, 0, .01), (8192, 8192, 8)])
def test_card49_actual_server_rejects_native_legal_but_effectively_invalid_size(video_dir, monkeypatch, width, height, scale):
    directory, records = video_dir
    monkeypatch.setattr(server, 'PRIVATE', directory)
    spec = runtime.manifest('local-card-49')
    checked = runtime.validate_values(spec, {'363:custom_width': width, '363:custom_height': height, '467:value': scale})
    with pytest.raises(ValueError):
        server.points_geometry(spec, checked, {'363': records[(1920, 1080)]})


@pytest.mark.parametrize('width,height,scale', [(0, 0, 1), (960, 640, 1), (960, 0, .5), (0, 640, .5)])
def test_card49_actual_server_validates_video_without_creating_point_binding(video_dir, monkeypatch, width, height, scale):
    directory, records = video_dir
    monkeypatch.setattr(server, 'PRIVATE', directory)
    spec = runtime.manifest('local-card-49')
    checked = runtime.validate_values(spec, {'363:custom_width': width, '363:custom_height': height, '467:value': scale})
    assert server.points_geometry(spec, checked, {'363': records[(1920, 1080)]}) is None
    graph, _, _ = build(49, checked)
    assert graph['467']['inputs']['value'] == scale
    assert graph['448']['inputs']['scale_by'] == ['467', 0]


@pytest.mark.parametrize('number,width,height', [(49, 960, 640), (49, 960, 0), (49, 0, 640),
                                                (51, 960, 640), (51, 960, 0), (51, 0, 640)])
def test_real_build_disables_original_long_side_only_for_custom_pair(number, width, height):
    loader = '363' if number == 49 else '1084'
    spec = runtime.manifest(f'local-card-{number}')
    values = {f'{loader}:custom_width': width, f'{loader}:custom_height': height}
    target = derive_ltx_processing_geometry(spec, values, 1920, 1080)['target']
    graph, _, _ = build(number, values, {**target, 'node': '1095', 'bindDimensions': True})
    assert graph[loader]['inputs']['custom_width'] == width
    assert graph[loader]['inputs']['custom_height'] == height
    if number == 49:
        assert graph['453']['inputs']['resize_type'] == 'scale dimensions'
        assert graph['453']['inputs']['resize_type.width'] == graph['453']['inputs']['resize_type.height'] == 0
        assert 'resize_type.longer_size' not in graph['453']['inputs']
    else:
        assert graph['1064']['inputs']['scale_to_side'] == 'None'


@pytest.mark.parametrize('number', [49, 51])
def test_real_build_zero_pair_preserves_authored_resize_and_long_side(number):
    spec = runtime.manifest(f'local-card-{number}')
    original = json.loads(runtime.template_path(spec).read_text('utf-8'))
    loader, resize = ('363', '453') if number == 49 else ('1084', '1064')
    graph, _, _ = build(number, {f'{loader}:custom_width': 0, f'{loader}:custom_height': 0},
                        {'width': 640, 'height': 368, 'node': '1095', 'bindDimensions': True})
    expected = copy.deepcopy(original[resize])
    if number == 51:
        # The compiled public control targets scale_to_length directly; normal
        # binding replaces its authored primitive link by the same scalar.
        expected['inputs']['scale_to_length'] = original['1105']['inputs']['value']
    assert graph[resize] == expected
    assert graph[loader]['inputs']['custom_width'] == graph[loader]['inputs']['custom_height'] == 0
    long_side = '404' if number == 49 else '1105'
    if number == 49:
        assert graph[long_side]['inputs']['value'] == original[long_side]['inputs']['value']
    else:
        assert graph[resize]['inputs']['scale_to_length'] == original[long_side]['inputs']['value']


def test_actual_node_boolean_submission_binds_both_native_mode_consumers(node_results):
    for mode in node_results['modes']:
        assert isinstance(mode, bool)
        graph, values, _ = build(23, {'575:value': mode})
        assert values['575:value'] is mode
        assert graph['575']['inputs']['value'] is mode
        assert graph['527']['inputs']['replacement_mode'] == ['575', 0]
        assert graph['529']['inputs']['replacement_mode'] == ['575', 0]
    for malformed in ('true', 1, None):
        with pytest.raises(ValueError):
            build(23, {'575:value': malformed})


def test_duration_25fps_grid_matches_preview_and_published_graph(node_results):
    # Published LTX frame contract, independent of a private node-info capture.
    native = {"min": 1, "max": 16384, "step": 8}
    for row in node_results['durations']:
        info = ltx_duration_info(row['seconds'])
        assert info['gridFrames'] == row['result']['frames']
        assert info['gridDurationSeconds'] == row['result']['seconds']
        assert info['fps'] == row['result']['fps'] == 25
        assert native['min'] <= info['requestedFrames'] <= native['max']
        assert (info['gridFrames']-1) % native['step'] == 0
        graph, _, _ = build(125, {'208:value': row['seconds']})
        assert graph['233']['inputs']['values.a'] == row['seconds']
        assert graph['233']['inputs']['values.b'] == ['215', 0]
        assert graph['215']['inputs']['value'] == 25
        assert graph['211']['inputs']['length'] == ['233', 1]
    with pytest.raises(ValueError):
        build(125, {'208:value': 656})


def test_historical_source_template_bytes_match_review_start_snapshot():
    snapshot = json.loads(historical_path('workflow-video-review-2026-10-08/before-template-hashes.json').read_text('utf-8'))
    assert len(snapshot) == 230
    # The snapshot names are evidence paths, never local workspace paths.
    changed = []
    for name, digest in snapshot.items():
        original = historical_path(name)
        if not original.is_file() or hashlib.sha256(original.read_bytes()).hexdigest() != digest:
            changed.append(name)
    assert changed == []
