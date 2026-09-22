"""Lossless MP4 remux: ComfyUI imports the exact executed API graph from prompt metadata."""
import json
import os
from pathlib import Path

import av


def embed_workflow(path, graph):
    path = Path(path)
    with av.open(str(path)) as source:
        try:
            if json.loads(source.metadata.get('prompt', 'null')) == graph:
                return
        except (ValueError, TypeError):
            pass
    temporary = path.with_name(path.stem + '.metadata.mp4')
    try:
        with av.open(str(path)) as source, av.open(
            str(temporary), 'w', options={'movflags': 'use_metadata_tags+faststart'}
        ) as destination:
            # Do not copy an upstream workflow tag: it can describe a stale template.
            destination.metadata['prompt'] = json.dumps(graph, ensure_ascii=False, separators=(',', ':'))
            destination.metadata['description'] = 'Yingxu executed ComfyUI graph. Drop the original MP4 onto the ComfyUI canvas.'
            streams = {stream.index: destination.add_stream_from_template(stream) for stream in source.streams}
            for packet in source.demux():
                if packet.dts is None:
                    continue
                packet.stream = streams[packet.stream.index]
                destination.mux(packet)
        with av.open(str(temporary)) as check:
            if json.loads(check.metadata.get('prompt', 'null')) != graph:
                raise ValueError('视频工作流元数据校验失败')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
