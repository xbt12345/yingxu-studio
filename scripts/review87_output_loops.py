"""Repeat a reviewed finished MP4, including audio, without GPU inference.

VHS's native image loop and its later audio mux can disagree on duration.
We therefore generate/mux once and stream-copy the complete local MP4.
No template files, remote workers, node types or credentials are modified.
"""
from __future__ import annotations

import copy
import importlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import uuid


MARKER = 'yingxu_output_loop_v1'
DEFAULT_MAX_BYTES = 1024 * 1024 * 1024


def _pinned_hashes():
    from scripts.review87_flash_controls import POLICIES as flash
    from scripts.review87_video_controls import SOURCE_HASHES as video
    from scripts.review87_infinite_controls import CONTRACTS as infinite
    return {**{wid: policy['hash'] for wid, policy in flash.items()},
            'local-card-5': video['local-card-5'],
            **{wid: contract['hash'] for wid, contract in infinite.items()}}


def _integer(value, label, maximum=100):
    if (isinstance(value, bool) or not isinstance(value, (int, float)) or
            not math.isfinite(value) or value != int(value) or not 0 <= value <= maximum):
        raise ValueError(label + '必须为0至' + str(maximum) + '的整数。')
    return int(value)


def _declared_records(wid):
    from scripts.review87_flash_controls import POLICIES as flash, flash_loop_metadata
    from scripts.review87_video_controls import OUTPUT_LOOP_POLICIES as video
    from scripts import review87_infinite_controls as infinite
    raw = (flash_loop_metadata(wid) if wid in flash else video.get(wid) if wid in video
           else getattr(infinite, 'OUTPUT_LOOP_POLICIES', {}).get(wid, []))
    return _records({'outputLoopPolicies': raw})


def _policy_signature(row):
    return (row['controlId'], row['node'], row['format'],
            json.dumps(row.get('audio', row.get('audioLink')), sort_keys=True),
            row.get('trimToAudio', False))


def _records(spec):
    raw = spec.get('outputLoopPolicies', [])
    if isinstance(raw, dict):
        if 'controlId' in raw:
            raw = [raw]
        else:
            if any(not isinstance(value, dict) for value in raw.values()):
                raise ValueError('输出循环规则格式不正确。')
            raw = [{**value, **({} if ('node' in value or 'sink' in value) else {'node': key})}
                   for key, value in raw.items()]
    if not isinstance(raw, list) or any(not isinstance(row, dict) for row in raw):
        raise ValueError('输出循环规则格式不正确。')
    result = []
    for row in raw:
        node = row.get('node', row.get('sink'))
        if not isinstance(node, str) or not node or not isinstance(row.get('controlId'), str):
            raise ValueError('输出循环缺少已审查的节点或控件。')
        if row.get('format') != 'video/h264-mp4':
            raise ValueError('输出循环只支持已审查的MP4输出。')
        result.append({**row, 'node': node})
    if len({row['node'] for row in result}) != len(result):
        raise ValueError('输出循环重复绑定了同一输出节点。')
    return result


def _contract_records(spec):
    records = _records(spec)
    if not records:
        return []
    wid = spec.get('id')
    expected = _pinned_hashes().get(wid)
    if not expected or spec.get('source_hash', spec.get('sourceHash')) != expected:
        raise ValueError('输出循环工作流来源已经变化，请重新审查。')
    declared = _declared_records(wid)
    if {_policy_signature(row) for row in records} != {_policy_signature(row) for row in declared}:
        raise ValueError('输出循环规则与原始工作流的已审查声明不一致。')
    by_id = {field['id']: field for field in spec.get('controls', [])}
    for row in records:
        field = by_id.get(row['controlId'], {})
        group_targets = {record['node'] for record in records if record['controlId'] == row['controlId']}
        actual = field.get('targets', [])
        if (field.get('key') != 'loop_count' or field.get('type') != 'number' or not isinstance(actual, list) or
                len(actual) != len(group_targets) or
                {(str(target.get('node')), target.get('input')) for target in actual} !=
                {(node, 'loop_count') for node in group_targets}):
            raise ValueError('输出循环的真实控件绑定已经变化。')
    return records


def _validate_contract(spec, graph):
    records = _contract_records(spec)
    expected = spec.get('source_hash', spec.get('sourceHash'))
    wid = spec.get('id')
    for row in records:
        node = graph.get(row['node'], {})
        inputs = node.get('inputs', {})
        if node.get('class_type') != 'VHS_VideoCombine' or inputs.get('format') != row['format']:
            raise ValueError('输出循环的原生MP4节点已经变化。')
        if inputs.get('pingpong', False) is not False:
            raise ValueError('输出循环不覆盖原生往返播放，请保持该工作流原配置。')
        expected_audio = row.get('audio', row.get('audioLink'))
        if ('audio' in row or 'audioLink' in row) and inputs.get('audio') != expected_audio:
            raise ValueError('输出循环的真实音轨绑定已经变化。')
        if inputs.get('trim_to_audio', False) != row.get('trimToAudio', False):
            raise ValueError('输出循环的原音轨裁切规则已经变化。')
        meta = node.get('_meta', {})
        if not isinstance(meta, dict):
            raise ValueError('输出循环执行记录格式不正确。')
        marker = meta.get(MARKER)
        if marker is not None:
            if (not isinstance(marker, dict) or marker.get('version') != 1 or
                    marker.get('control_id') != row['controlId'] or
                    marker.get('source_hash') != expected or marker.get('workflow_id') != wid or
                    marker.get('node') != row['node']):
                raise ValueError('输出循环的已保存执行记录与工作流不一致。')
            _integer(marker.get('extra_repeats'), '输出循环次数')
    return records


def output_loop_native_values(spec, values):
    """Keep requested UI values; return separate loop0 values for native helpers."""
    if not isinstance(values, dict):
        raise ValueError('输出循环参数格式不正确。')
    records = _contract_records(spec)
    result = copy.deepcopy(values)
    for control_id in {row['controlId'] for row in records}:
        _integer(values.get(control_id, 0), '输出循环次数')
        result[control_id] = 0
    return result


def prepare_output_loops(spec, graph, values):
    """After all scalar projections/repairs, before prune/queue; returns a copy.

Only declared source-pinned VHS MP4 loops become local delivery markers.
Passing the saved graph and saved values again is idempotent for reruns.
"""
    records = _validate_contract(spec, graph)
    if not records:
        return graph
    if not isinstance(values, dict):
        raise ValueError('输出循环参数格式不正确。')
    result = copy.deepcopy(graph)
    for row in records:
        node = result[row['node']]
        existing = node.get('_meta', {}).get(MARKER)
        value = values.get(row['controlId'], existing.get('extra_repeats') if existing else node['inputs'].get('loop_count', 0))
        repeats = _integer(value, '输出循环次数')
        node['inputs']['loop_count'] = 0
        if repeats:
            node.setdefault('_meta', {})[MARKER] = {
                'version': 1, 'workflow_id': spec['id'], 'node': row['node'],
                'extra_repeats': repeats, 'control_id': row['controlId'],
                'source_hash': spec.get('source_hash', spec.get('sourceHash')),
                'mode': 'repeat-finished-audio-video-stream-copy',
            }
        elif MARKER in node.get('_meta', {}):
            del node['_meta'][MARKER]
    return result


def _ffmpeg_executable(explicit=None):
    if explicit:
        path = Path(explicit)
        if path.is_file():
            return str(path)
        found = shutil.which(str(explicit))
        if found:
            return found
        raise ValueError('本机没有可用的FFmpeg，无法完成输出循环。')
    found = shutil.which('ffmpeg')
    if found:
        return found
    try:
        candidate = importlib.import_module('imageio_ffmpeg').get_ffmpeg_exe()
    except (ImportError, OSError, RuntimeError):
        candidate = None
    if candidate and Path(candidate).is_file():
        return candidate
    raise ValueError('本机没有可用的FFmpeg，无法完成输出循环。')


def _media_info(path):
    import av
    with Path(path).open('rb') as file:
        if b'ftyp' not in file.read(64):
            raise ValueError('输出循环需要有效MP4成片。')
    with av.open(str(path)) as container:
        videos = [stream for stream in container.streams if stream.type == 'video']
        if len(videos) != 1:
            raise ValueError('输出循环需要单视频轨MP4成片。')
        stream = videos[0]
        duration = float(stream.duration * stream.time_base) if stream.duration and stream.time_base else None
        if not duration or not math.isfinite(duration) or duration <= 0:
            raise ValueError('输出循环无法确认原成片时长。')
        rate = float(stream.average_rate) if stream.average_rate else None
        audio = [s for s in container.streams if s.type == 'audio']
        packet_seconds = max((s.codec_context.frame_size / s.codec_context.sample_rate
                              for s in audio if s.codec_context.sample_rate), default=0)
        return {'duration': duration, 'frames': stream.frames, 'rate': rate,
                'codec': stream.codec_context.name,
                'audioStreams': len(audio), 'audioPacketSeconds': packet_seconds}


def repeat_output_if_needed(spec, graph, node_id, path, *, max_bytes=DEFAULT_MAX_BYTES,
                            timeout=120, ffmpeg=None):
    """Repeat a fresh validated download before the caller's atomic dest replace.

The caller must invoke this only for a new download, before embed/probe, and
skip existing delivered files. No sidecar is created. A failure keeps ``path``
byte-identical; a success atomically substitutes the complete repeated MP4.
Returns False for unchanged output, or a small processing-evidence dict.
"""
    node_id = str(node_id)
    marker = graph.get(node_id, {}).get('_meta', {}).get(MARKER)
    if marker is None:
        return False
    records = _validate_contract(spec, graph)
    if not any(row['node'] == node_id for row in records):
        raise ValueError('该成片不属于已审查的输出循环节点。')
    repeats = _integer(marker.get('extra_repeats'), '输出循环次数')
    if not repeats:
        return False
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
        raise ValueError('输出循环大小限制必须为正整数。')
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('输出循环超时限制必须为正数。')
    source = Path(path)
    size = source.stat().st_size
    # Stream copy adds a small index/header margin; reject before doing work.
    estimate = size * (repeats + 1) + 64 * 1024
    if estimate > max_bytes:
        raise ValueError('循环后的作品预计超过允许大小，请减少循环次数。')
    before = _media_info(source)
    executable = _ffmpeg_executable(ffmpeg)
    temporary = source.with_name(source.name + '.repeat-' + uuid.uuid4().hex + '.mp4')
    arguments = [executable, '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
                 '-stream_loop', str(repeats), '-i', str(source), '-map', '0', '-c', 'copy',
                 '-movflags', '+faststart', '-f', 'mp4', str(temporary)]
    try:
        try:
            completed = subprocess.run(arguments, capture_output=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            raise ValueError('输出循环处理超时，原成片已保留，可重新取回。') from None
        except OSError:
            raise ValueError('FFmpeg输出循环启动失败，原成片已保留。') from None
        if completed.returncode:
            raise ValueError('输出循环处理失败，原成片已保留，可重新取回。')
        if not temporary.is_file() or temporary.stat().st_size > max_bytes:
            raise ValueError('循环后的作品超过允许大小，原成片已保留。')
        after = _media_info(temporary)
        if after['codec'] != before['codec'] or after['audioStreams'] != before['audioStreams']:
            raise ValueError('循环后音视频轨不完整，原成片已保留。')
        expected_duration = before['duration'] * (repeats + 1)
        # AAC packet priming/padding can add one packet per copied iteration.
        # Check exact frame counts below rather than rejecting valid long loops
        # because this format-level timing accumulates without re-encoding.
        tolerance = (max(.35, 2 / before['rate']) if before['rate'] else .5) + repeats * before['audioPacketSeconds']
        if abs(after['duration'] - expected_duration) > tolerance:
            raise ValueError('循环后的实际时长不符合设置，原成片已保留。')
        if before['frames'] and after['frames'] != before['frames'] * (repeats + 1):
            raise ValueError('循环后的帧数不符合设置，原成片已保留。')
        os.replace(temporary, source)
        return {'extra_repeats': repeats, 'plays': repeats + 1,
                'beforeSeconds': before['duration'], 'afterSeconds': after['duration'],
                'streamCopy': True, 'audioRepeated': bool(before['audioStreams'])}
    finally:
        temporary.unlink(missing_ok=True)
