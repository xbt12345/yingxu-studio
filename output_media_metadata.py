"""Read saved output timing without decoding every media frame.

GIF timing describes one encoded animation cycle. Its delays are stored in
centiseconds, so requested generation FPS and encoded average FPS can differ.
An absent or zero GIF delay has no portable playback duration; omit timing in
that case instead of inventing a browser-specific minimum delay.
"""

from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path
from typing import Any

import av
from PIL import Image


_MAX_GIF_BYTES = 64 * 1024 * 1024
_MAX_GIF_BLOCKS = 262144
_MAX_GIF_FRAMES = 16384


def _positive_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number > 0 else None


class _GifReader:
    def __init__(self, stream, size: int):
        self.stream = stream
        self.size = size
        self.blocks = 0

    def read(self, count: int) -> bytes:
        if self.stream.tell() + count > self.size:
            raise ValueError("Truncated GIF")
        data = self.stream.read(count)
        if len(data) != count:
            raise ValueError("Truncated GIF")
        return data

    def skip(self, count: int) -> None:
        if self.stream.tell() + count > self.size:
            raise ValueError("Truncated GIF")
        self.stream.seek(count, 1)

    def subblocks(self) -> None:
        while True:
            self.blocks += 1
            if self.blocks > _MAX_GIF_BLOCKS:
                raise OverflowError("GIF metadata scan budget")
            length = self.read(1)[0]
            if length == 0:
                return
            self.skip(length)


def _gif_metadata(path: Path, size: int) -> dict[str, Any]:
    # Scan GIF block headers and skip compressed pixels. Pillow.seek() can
    # decode/composite earlier frames; avoid using it for a metadata probe.
    with path.open("rb") as stream:
        reader = _GifReader(stream, size)
        if reader.read(6) not in (b"GIF87a", b"GIF89a"):
            return {}
        screen = reader.read(7)
        width = int.from_bytes(screen[:2], "little")
        height = int.from_bytes(screen[2:4], "little")
        if width <= 0 or height <= 0:
            return {}
        geometry = {"width": width, "height": height}
        if screen[4] & 0x80:
            reader.skip(3 * (2 ** ((screen[4] & 7) + 1)))
        pending_delay: int | None = None
        delays: list[int | None] = []
        try:
            while stream.tell() <= _MAX_GIF_BYTES:
                marker = reader.read(1)[0]
                if marker == 0x3B:
                    break
                if marker == 0x21:
                    label = reader.read(1)[0]
                    if label == 0xF9:
                        if reader.read(1)[0] != 4:
                            return {}
                        control = reader.read(4)
                        if reader.read(1)[0] != 0:
                            return {}
                        pending_delay = int.from_bytes(control[1:3], "little") * 10
                    else:
                        # Plain-text rendering is another timed graphic. Its
                        # playback cannot be described as image-frame FPS.
                        if label == 0x01:
                            return geometry
                        reader.subblocks()
                    continue
                if marker != 0x2C:
                    return {}
                descriptor = reader.read(9)
                if descriptor[8] & 0x80:
                    reader.skip(3 * (2 ** ((descriptor[8] & 7) + 1)))
                reader.read(1)  # LZW minimum code size, not pixel decoding.
                reader.subblocks()
                delays.append(pending_delay)
                pending_delay = None
                if len(delays) > _MAX_GIF_FRAMES:
                    return geometry
            else:
                return geometry
        except OverflowError:
            return geometry
        if not delays:
            return geometry
        result = {**geometry, "frame_count": len(delays)}
        if all(delay is not None and delay > 0 for delay in delays):
            total_ms = sum(delays)
            result.update(
                duration=total_ms / 1000,
                frame_rate=len(delays) * 1000 / total_ms,
                gif_delay_unit_ms=10,
                frame_duration_min_ms=min(delays),
                frame_duration_max_ms=max(delays),
            )
            if len(set(delays)) == 1:
                result["frame_duration_ms"] = delays[0]
        return result


def _container_metadata(path: Path, kind: str) -> dict[str, Any]:
    # Header/stream probing only. No decode(), demux loop, or GPU work.
    with av.open(
        str(path), options={"analyzeduration": "1000000", "probesize": "1000000"}
    ) as container:
        streams = container.streams.audio if kind == "audio" else container.streams.video
        if not streams:
            return {}
        stream = streams[0]
        result: dict[str, Any] = {}
        if kind != "audio":
            width = getattr(stream.codec_context, "width", 0)
            height = getattr(stream.codec_context, "height", 0)
            if width > 0 and height > 0:
                result.update(width=width, height=height)
            count = getattr(stream, "frames", 0)
            if isinstance(count, int) and count > 0:
                result["frame_count"] = count
            fps = _positive_number(getattr(stream, "average_rate", None))
            if fps is not None:
                result["frame_rate"] = fps
        duration = None
        if stream.duration is not None and stream.time_base is not None:
            duration = _positive_number(stream.duration * stream.time_base)
        if duration is None and container.duration is not None:
            duration = _positive_number(container.duration / av.time_base)
        if duration is not None:
            result["duration"] = duration
        return result


@lru_cache(maxsize=128)
def _cached_metadata(path: str, kind: str, mtime_ns: int, size: int) -> dict[str, Any]:
    del mtime_ns  # Part of the cache key; a rewritten file must be probed again.
    file = Path(path)
    try:
        with file.open("rb") as stream:
            signature = stream.read(6)
        if signature in (b"GIF87a", b"GIF89a"):
            return _gif_metadata(file, size)
        if kind == "image":
            with Image.open(file) as image:
                return {"width": image.width, "height": image.height}
        if kind in ("video", "audio"):
            return _container_metadata(file, kind)
    except Exception:
        # Metadata is optional; probing errors must not fail a saved output.
        return {}
    return {}


def probe_output_metadata(path: str | Path, kind: str) -> dict[str, Any]:
    """Return optional saved-file metadata; always fail softly.

    Call once after an output file is finalized. For older outputs call only
    when the selected work is opened, not for every item on every list poll.
    Returned dicts are copies so callers cannot mutate cached values.
    """
    try:
        file = Path(path).resolve()
        stat = file.stat()
        if not file.is_file() or kind not in ("image", "video", "audio"):
            return {}
        return dict(_cached_metadata(str(file), kind, stat.st_mtime_ns, stat.st_size))
    except Exception:
        return {}
