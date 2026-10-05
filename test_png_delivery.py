"""Synthetic PNG delivery checks; no real key, database or remote execution."""
import hashlib
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib

from png_delivery import PNGDeliveryError, PNG_SIGNATURE, TEXT_CHUNKS, strip_png_text


def chunk(kind, payload=b''):
    return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload) & 0xffffffff)


def chunks(data):
    position, result = 8, []
    while position < len(data):
        length = struct.unpack_from('>I', data, position)[0]
        end = position + length + 12
        result.append((data[position + 4:position + 8], data[position + 8:end - 4], data[position:end]))
        position = end
    return result


FAKE_SECRET = b'sk-fake-test-only-abcdefghijklmnopqrstuvwxyz'
RGBA = bytes([10, 20, 30, 0, 70, 80, 90, 64, 110, 120, 130, 128, 210, 220, 230, 255])
SCANLINES = b'\0' + RGBA[:8] + b'\0' + RGBA[8:]


def rgba_png(text=True, extras=()):
    compressed = zlib.compress(SCANLINES)
    parts = [PNG_SIGNATURE, chunk(b'IHDR', struct.pack('>IIBBBBB', 2, 2, 8, 6, 0, 0, 0))]
    parts += list(extras)
    if text:
        parts += [chunk(b'tEXt', b'prompt\0' + FAKE_SECRET),
                  chunk(b'iTXt', b'workflow\0\0\0\0\0' + FAKE_SECRET),
                  chunk(b'zTXt', b'compressed\0\0' + zlib.compress(FAKE_SECRET))]
    parts += [chunk(b'IDAT', compressed[:4]), chunk(b'IDAT', compressed[4:]), chunk(b'IEND')]
    return b''.join(parts)


class PNGDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.source = self.directory / 'original.png'
        self.destination = self.directory / 'delivery.png'

    def tearDown(self):
        self.temp.cleanup()

    def reject(self, raw):
        self.source.write_bytes(raw)
        self.destination.write_bytes(b'previous-cache')
        before = self.source.read_bytes()
        with self.assertRaises(PNGDeliveryError):
            strip_png_text(self.source, self.destination)
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(self.destination.read_bytes(), b'previous-cache')
        self.assertFalse(list(self.directory.glob('.png-delivery-*.tmp')))

    def test_all_text_removed_without_changing_pixels_alpha_or_idat(self):
        original = rgba_png()
        self.source.write_bytes(original)
        result = strip_png_text(self.source, self.destination)
        delivered = self.destination.read_bytes()
        original_idat = [raw for kind, _, raw in chunks(original) if kind == b'IDAT']
        delivered_idat = [raw for kind, _, raw in chunks(delivered) if kind == b'IDAT']
        self.assertEqual(original_idat, delivered_idat)
        scanlines = zlib.decompress(b''.join(payload for kind, payload, _ in chunks(delivered) if kind == b'IDAT'))
        pixels = scanlines[1:9] + scanlines[10:18]
        self.assertEqual(pixels, RGBA)
        self.assertEqual(list(pixels[3::4]), [0, 64, 128, 255])
        self.assertEqual(scanlines, SCANLINES)
        self.assertFalse(any(kind in TEXT_CHUNKS for kind, _, _ in chunks(delivered)))
        self.assertNotIn(FAKE_SECRET, delivered)
        self.assertEqual(result['removed_text_chunks'], 3)
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(result['source_sha256'], hashlib.sha256(original).hexdigest())
        self.assertEqual(result['delivery_sha256'], hashlib.sha256(delivered).hexdigest())

    def test_icc_gamma_unknown_ancillary_and_original_crcs_are_preserved(self):
        extras = [chunk(b'iCCP', b'owned-profile\0\0' + zlib.compress(b'owned-profile-bytes')),
                  chunk(b'gAMA', struct.pack('>I', 45455)), chunk(b'vpAg', b'opaque-ancillary')]
        original = rgba_png(extras=extras)
        self.source.write_bytes(original)
        strip_png_text(self.source, self.destination)
        self.assertEqual([raw for kind, _, raw in chunks(original) if kind not in TEXT_CHUNKS],
                         [raw for _, _, raw in chunks(self.destination.read_bytes())])

    def test_palette_and_transparency_are_retained_exactly(self):
        original = (PNG_SIGNATURE + chunk(b'IHDR', struct.pack('>IIBBBBB', 2, 1, 8, 3, 0, 0, 0))
                    + chunk(b'PLTE', b'\xff\0\0\0\xff\0') + chunk(b'tRNS', b'\0\x80')
                    + chunk(b'tEXt', b'prompt\0' + FAKE_SECRET)
                    + chunk(b'IDAT', zlib.compress(b'\0\0\1')) + chunk(b'IEND'))
        self.source.write_bytes(original)
        strip_png_text(self.source, self.destination)
        self.assertEqual([raw for kind, _, raw in chunks(original) if kind not in TEXT_CHUNKS],
                         [raw for _, _, raw in chunks(self.destination.read_bytes())])

    def test_apng_controls_and_frame_data_are_retained_exactly(self):
        first_control = struct.pack('>IIIIIHHBB', 0, 2, 2, 0, 0, 1, 16, 0, 0)
        second_control = struct.pack('>IIIIIHHBB', 1, 2, 2, 0, 0, 1, 16, 0, 0)
        parts = chunks(rgba_png(extras=[chunk(b'acTL', struct.pack('>II', 2, 0)), chunk(b'fcTL', first_control)]))
        original = PNG_SIGNATURE + b''.join(raw for kind, _, raw in parts if kind != b'IEND')
        original += chunk(b'fcTL', second_control) + chunk(b'fdAT', struct.pack('>I', 2) + zlib.compress(SCANLINES)) + chunk(b'IEND')
        self.source.write_bytes(original)
        strip_png_text(self.source, self.destination)
        self.assertEqual([raw for kind, _, raw in chunks(original) if kind not in TEXT_CHUNKS],
                         [raw for _, _, raw in chunks(self.destination.read_bytes())])

    def test_png_without_text_is_an_identical_delivery_copy(self):
        self.source.write_bytes(rgba_png(text=False))
        result = strip_png_text(self.source, self.destination)
        self.assertEqual(self.source.read_bytes(), self.destination.read_bytes())
        self.assertEqual(result['removed_text_chunks'], 0)
        self.assertEqual(result['source_sha256'], result['delivery_sha256'])

    def test_same_path_and_hard_link_alias_are_refused(self):
        original = rgba_png()
        self.source.write_bytes(original)
        with self.assertRaises(PNGDeliveryError):
            strip_png_text(self.source, self.source)
        os.link(self.source, self.destination)
        with self.assertRaises(PNGDeliveryError):
            strip_png_text(self.source, self.destination)
        self.assertEqual(self.source.read_bytes(), original)

    def test_symlink_alias_is_refused_without_rewriting_original(self):
        original = rgba_png()
        self.source.write_bytes(original)
        try:
            self.destination.symlink_to(self.source)
        except (OSError, NotImplementedError):
            self.skipTest('This filesystem does not permit symlinks')
        with self.assertRaises(PNGDeliveryError):
            strip_png_text(self.source, self.destination)
        self.assertEqual(self.source.read_bytes(), original)
        self.assertTrue(self.destination.is_symlink())

    def test_incomplete_indexed_palette_and_duplicate_transparency_are_refused(self):
        header = chunk(b'IHDR', struct.pack('>IIBBBBB', 2, 1, 8, 3, 0, 0, 0))
        palette = chunk(b'PLTE', b'\xff\0\0\0\xff\0')
        transparency = chunk(b'tRNS', b'\0\x80')
        image = chunk(b'IDAT', zlib.compress(b'\0\0\1'))
        for raw in [PNG_SIGNATURE + header + image + chunk(b'IEND'),
                    PNG_SIGNATURE + header + palette + transparency + transparency + image + chunk(b'IEND')]:
            self.reject(raw)

    def test_bad_signature_truncation_and_chunk_bounds_are_refused(self):
        original = rgba_png()
        for raw in [b'not-png', original[:-1], original[:14], original[:8],
                    original[:8] + struct.pack('>I', 0x80000000) + original[12:]]:
            with self.subTest(size=len(raw)):
                self.reject(raw)

    def test_invalid_crcs_in_text_or_image_are_refused(self):
        original = rgba_png()
        for target in [b'tEXt', b'IDAT']:
            parts = chunks(original)
            for index, (kind, _, raw) in enumerate(parts):
                if kind == target:
                    damaged = raw[:-1] + bytes([raw[-1] ^ 1])
                    self.reject(PNG_SIGNATURE + b''.join(damaged if i == index else p[2] for i, p in enumerate(parts)))
                    break

    def test_missing_duplicate_or_nonfinal_iend_are_refused(self):
        original = rgba_png()
        for raw in [original[:-12], original + chunk(b'IEND'), original + b'trailing',
                    original[:-12] + chunk(b'IEND', b'x')]:
            with self.subTest(size=len(raw)):
                self.reject(raw)

    def test_header_and_critical_chunk_structure_are_refused(self):
        header = chunk(b'IHDR', struct.pack('>IIBBBBB', 2, 2, 8, 6, 0, 0, 0))
        image = chunk(b'IDAT', zlib.compress(SCANLINES))
        for raw in [PNG_SIGNATURE + image + header + chunk(b'IEND'),
                    PNG_SIGNATURE + header + header + image + chunk(b'IEND'),
                    PNG_SIGNATURE + chunk(b'IHDR', struct.pack('>IIBBBBB', 0, 2, 8, 6, 0, 0, 0)) + image + chunk(b'IEND'),
                    PNG_SIGNATURE + header + chunk(b'ABCD', b'unknown-critical') + image + chunk(b'IEND'),
                    PNG_SIGNATURE + header + chunk(b'abcd') + image + chunk(b'IEND'),
                    PNG_SIGNATURE + header + image + chunk(b'tEXt', b'between\0x') + image + chunk(b'IEND')]:
            with self.subTest(size=len(raw)):
                self.reject(raw)

    def test_atomic_replace_failure_keeps_source_cache_and_cleans_temp(self):
        original = rgba_png()
        self.source.write_bytes(original)
        self.destination.write_bytes(b'previous-cache')
        with patch('png_delivery.os.replace', side_effect=OSError('simulated-write-failure')):
            with self.assertRaises(OSError):
                strip_png_text(self.source, self.destination)
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(self.destination.read_bytes(), b'previous-cache')
        self.assertFalse(list(self.directory.glob('.png-delivery-*.tmp')))


if __name__ == '__main__':
    unittest.main()
