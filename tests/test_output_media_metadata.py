import struct
from fractions import Fraction

import av
import numpy as np
from PIL import Image

from output_media_metadata import probe_output_metadata


def _gif(path, durations):
    # Distinct solid colors prevent GIF's duplicate-frame merging.
    frames = [Image.new("RGB", (8, 6), (i * 70, 30, 220)) for i in range(len(durations))]
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=durations, loop=0)


def test_gif_reports_encoded_delay_not_requested_fps(tmp_path):
    path = tmp_path / "six-fps.gif"
    _gif(path, [round(1000 / 6), round(1000 / 6)])
    metadata = probe_output_metadata(path, "image")
    assert metadata["frame_duration_ms"] == 160
    assert metadata["duration"] == 0.32
    assert metadata["frame_count"] == 2
    assert metadata["frame_rate"] == 6.25
    assert metadata["gif_delay_unit_ms"] == 10


def test_gif_mixed_delays_use_cycle_average(tmp_path):
    path = tmp_path / "mixed.gif"
    _gif(path, [100, 200, 300])
    metadata = probe_output_metadata(path, "image")
    assert metadata["frame_rate"] == 5
    assert metadata["duration"] == 0.6
    assert metadata["frame_duration_min_ms"] == 100
    assert metadata["frame_duration_max_ms"] == 300
    assert "frame_duration_ms" not in metadata


def test_gif_zero_or_missing_delay_does_not_invent_playback_timing(tmp_path):
    path = tmp_path / "no-delay.gif"
    _gif(path, [0, 0])
    metadata = probe_output_metadata(path, "image")
    assert metadata["frame_count"] == 2
    assert "duration" not in metadata
    assert "frame_rate" not in metadata


def test_gif_pixel_data_is_skipped_without_pillow_frame_decode(tmp_path, monkeypatch):
    path = tmp_path / "headers-only.gif"
    _gif(path, [100, 100])

    def fail(*args, **kwargs):
        raise AssertionError("Metadata probe must not decode GIF frames")

    monkeypatch.setattr(Image, "open", fail)
    assert probe_output_metadata(path, "image")["frame_rate"] == 10


def test_video_reads_encoded_stream_values(tmp_path):
    path = tmp_path / "tiny.mp4"
    with av.open(str(path), "w") as container:
        stream = container.add_stream("mpeg4", rate=24)
        stream.width = 16
        stream.height = 16
        stream.pix_fmt = "yuv420p"
        for index in range(3):
            frame = av.VideoFrame.from_ndarray(np.zeros((16, 16, 3), dtype=np.uint8), format="rgb24")
            frame.pts = index
            frame.time_base = Fraction(1, 24)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    metadata = probe_output_metadata(path, "video")
    assert metadata["frame_count"] == 3
    assert metadata["frame_rate"] == 24
    assert metadata["duration"] == 0.125
    assert (metadata["width"], metadata["height"]) == (16, 16)


def test_failures_are_optional_and_cached_dict_is_not_shared(tmp_path):
    missing = tmp_path / "absent.mp4"
    assert probe_output_metadata(missing, "video") == {}
    broken = tmp_path / "broken.gif"
    broken.write_bytes(b"GIF89a" + struct.pack("<HH", 8, 6))
    assert probe_output_metadata(broken, "image") == {}
    path = tmp_path / "still.png"
    Image.new("RGB", (12, 9)).save(path)
    metadata = probe_output_metadata(path, "image")
    metadata["width"] = -1
    assert probe_output_metadata(path, "image") == {"width": 12, "height": 9}
    Image.new("RGB", (15, 9)).save(path)
    assert probe_output_metadata(path, "image")["width"] == 15
