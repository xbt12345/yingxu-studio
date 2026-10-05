"""Remove PNG text chunks from a delivery copy without decoding any pixels.

The original stays untouched. IDAT and every retained chunk, including its CRC,
are copied byte for byte. This validates PNG container structure and CRCs, not
the contents of compressed pixels or opaque ancillary payloads.
"""
import hashlib
import os
from pathlib import Path
import struct
import tempfile
import zlib


PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'
TEXT_CHUNKS = {b'tEXt', b'iTXt', b'zTXt'}
CRITICAL_CHUNKS = {b'IHDR', b'PLTE', b'IDAT', b'IEND'}
BIT_DEPTHS = {0: {1, 2, 4, 8, 16}, 2: {8, 16}, 3: {1, 2, 4, 8},
              4: {8, 16}, 6: {8, 16}}


class PNGDeliveryError(ValueError):
    """A fixed error code; never includes embedded metadata."""


def _strip_text_chunks(data):
    if not data.startswith(PNG_SIGNATURE):
        raise PNGDeliveryError('invalid-png-signature')
    output = bytearray(PNG_SIGNATURE)
    view = memoryview(data)
    position = len(PNG_SIGNATURE)
    removed = 0
    seen_header = False
    seen_palette = False
    seen_transparency = False
    seen_image = False
    image_closed = False
    image_bytes = 0
    color_type = bit_depth = palette_size = None
    while position < len(data):
        if len(data) - position < 12:
            raise PNGDeliveryError('truncated-png-chunk')
        length = struct.unpack_from('>I', data, position)[0]
        kind = bytes(view[position + 4:position + 8])
        if length > 0x7fffffff or length > len(data) - position - 12:
            raise PNGDeliveryError('invalid-png-chunk-bounds')
        if (len(kind) != 4 or any(not (65 <= c <= 90 or 97 <= c <= 122) for c in kind)
                or not 65 <= kind[2] <= 90):
            raise PNGDeliveryError('invalid-png-chunk-type')
        end = position + length + 12
        expected_crc = struct.unpack_from('>I', data, end - 4)[0]
        if zlib.crc32(view[position + 4:end - 4]) & 0xffffffff != expected_crc:
            raise PNGDeliveryError('invalid-png-crc')
        if kind[0] & 32 == 0 and kind not in CRITICAL_CHUNKS:
            raise PNGDeliveryError('unknown-png-critical-chunk')
        if not seen_header and kind != b'IHDR':
            raise PNGDeliveryError('png-header-must-be-first')
        payload = view[position + 8:end - 4]
        if kind == b'IHDR':
            if seen_header or length != 13:
                raise PNGDeliveryError('invalid-png-header')
            width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack('>IIBBBBB', payload)
            if (not 0 < width <= 0x7fffffff or not 0 < height <= 0x7fffffff
                    or bit_depth not in BIT_DEPTHS.get(color_type, set())
                    or compression != 0 or filtering != 0 or interlace not in (0, 1)):
                raise PNGDeliveryError('invalid-png-header-fields')
            seen_header = True
        elif kind == b'PLTE':
            if (seen_palette or seen_image or color_type in (0, 4)
                    or not length or length % 3 or length > 768):
                raise PNGDeliveryError('invalid-png-palette')
            palette_size = length // 3
            if color_type == 3 and palette_size > 1 << bit_depth:
                raise PNGDeliveryError('invalid-png-palette')
            seen_palette = True
        elif kind == b'IDAT':
            if image_closed or color_type == 3 and not seen_palette:
                raise PNGDeliveryError('invalid-png-image-order')
            seen_image = True
            image_bytes += length
        elif kind == b'IEND':
            if length or not seen_image or not image_bytes or end != len(data):
                raise PNGDeliveryError('invalid-png-end')
            output.extend(view[position:end])
            return bytes(output), removed
        elif kind == b'tRNS':
            expected = {0: 2, 2: 6}.get(color_type)
            if (seen_transparency or seen_image or color_type in (4, 6)
                    or color_type == 3 and (not seen_palette or not 0 < length <= palette_size)
                    or expected is not None and length != expected):
                raise PNGDeliveryError('invalid-png-transparency')
            seen_transparency = True
        if seen_image and kind != b'IDAT':
            image_closed = True
        if kind in TEXT_CHUNKS:
            removed += 1
        else:
            output.extend(view[position:end])
        position = end
    raise PNGDeliveryError('missing-png-end')


def strip_png_text(source: Path, destination: Path) -> dict:
    """Atomically write a separate text-free PNG copy and safe hashes/counts.

    Existing destination bytes are replaced only after full structural/CRC
    validation. Same paths, symlink aliases and hard-link aliases are refused.
    Malformed input leaves the original and any existing destination unchanged.
    """
    source = Path(source)
    destination = Path(destination)
    if (source.resolve() == destination.resolve()
            or destination.exists() and os.path.samefile(source, destination)):
        raise PNGDeliveryError('source-and-destination-must-differ')
    original = source.read_bytes()
    delivered, removed = _strip_text_chunks(original)
    result = {'source_sha256': hashlib.sha256(original).hexdigest(),
              'delivery_sha256': hashlib.sha256(delivered).hexdigest(),
              'removed_text_chunks': removed,
              'source_bytes': len(original), 'delivery_bytes': len(delivered)}
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='wb', prefix='.png-delivery-', suffix='.tmp',
                                         dir=destination.parent, delete=False) as output:
            temporary = Path(output.name)
            output.write(delivered)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return result
