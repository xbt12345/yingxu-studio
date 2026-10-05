"""Original-track inspection and silent117 routing; no card/model requests."""
from pathlib import Path
from fractions import Fraction
import tempfile
import unittest
from unittest.mock import patch

import av
from PIL import Image
import server
import schema_adapters


class OriginalAudioRouting(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.spec = schema_adapters.manifest('local-card-117')
        self.records = {'269': {'id': 'a' * 64, 'kind': 'video', 'remote': 'owned.mp4'}}

    def clip(self, sound):
        path = Path(self.temp.name) / ('sound.mp4' if sound else 'silent.mp4')
        with av.open(str(path), 'w') as output:
            video = output.add_stream('libx264', rate=24)
            video.width = video.height = 64
            video.pix_fmt = 'yuv420p'
            audio = output.add_stream('aac', rate=48000) if sound else None
            if audio is not None:
                audio.layout = 'mono'
            for _ in range(4):
                for packet in video.encode(av.VideoFrame.from_image(Image.new('RGB', (64, 64), 'blue'))):
                    output.mux(packet)
            for packet in video.encode():
                output.mux(packet)
            if sound:
                frame = av.AudioFrame('fltp', 'mono', 8000)
                frame.sample_rate = 48000
                frame.pts = 0
                frame.time_base = Fraction(1, 48000)
                for plane in frame.planes:
                    plane.update(bytes(plane.buffer_size))
                for packet in audio.encode(frame):
                    output.mux(packet)
                for packet in audio.encode():
                    output.mux(packet)
        return path

    def test_real_no_audio_video_is_kept_without_dummy_remux(self):
        path = self.clip(False)
        with patch.object(server, 'asset_file', return_value=path), patch.object(server, 'vhs_audio_asset') as derive:
            self.assertIs(server.source_audio_presence(self.spec, self.records), False)
            routed = server.schema_vhs_assets(self.spec, self.records)
        derive.assert_not_called()
        self.assertEqual(routed, self.records)
        with av.open(str(path)) as source:
            self.assertEqual(len(source.streams.audio), 0)

    def test_real_audio_track_retains_existing_sound_compatibility(self):
        path = self.clip(True)
        with patch.object(server, 'asset_file', return_value=path), patch.object(server, 'vhs_audio_asset', side_effect=lambda a: a) as derive:
            self.assertIs(server.source_audio_presence(self.spec, self.records), True)
            routed = server.schema_vhs_assets(self.spec, self.records)
        derive.assert_called_once_with(self.records['269'])
        self.assertEqual(routed, self.records)

    def test_unknown_or_corrupt_original_is_rejected_before_upload(self):
        path = Path(self.temp.name) / 'corrupt.mp4'
        path.write_bytes(b'not a video')
        with patch.object(server, 'asset_file', return_value=path), patch.object(server, 'ensure_remote') as upload:
            with self.assertRaises(ValueError):
                server.source_audio_presence(self.spec, self.records)
            with self.assertRaises(ValueError):
                server.source_audio_presence(self.spec, {})
        upload.assert_not_called()

    def test_other_workflows_keep_the_existing_compatibility_contract(self):
        other = {'id': 'local-card-121', 'outputs': ['save'],
                 'media': [{'id': '269', 'targets': [{'node': '269', 'input': 'video'}]}]}
        graph = {'269': {'class_type': 'VHS_LoadVideo'}, 'save': {'class_type': 'VHS_VideoCombine'}}
        with patch.object(server, 'vhs_audio_asset', side_effect=lambda a: a) as derive:
            self.assertIsNone(server.source_audio_presence(other, self.records))
            self.assertEqual(server.schema_vhs_assets(other, self.records, graph), self.records)
        derive.assert_called_once()


if __name__ == '__main__':
    unittest.main()
