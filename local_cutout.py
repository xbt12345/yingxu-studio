"""Local foreground segmentation. No model service, network or source-file writes."""
import io
from PIL import Image, ImageOps


def cutout_png(data: bytes, bounds=None) -> bytes:
    import cv2
    import numpy as np

    with Image.open(io.BytesIO(data)) as image:
        if image.width * image.height > 20_000_000:
            raise ValueError('图片超过 2000 万像素，请缩小后再抠图。')
        original = ImageOps.exif_transpose(image).convert('RGBA')
    if min(original.size) < 16:
        raise ValueError('图片尺寸过小，无法分离主体。')
    small = original.copy()
    small.thumbnail((960, 960), Image.Resampling.LANCZOS)
    width, height = small.size
    values = bounds or {'x': .03, 'y': .03, 'width': .94, 'height': .94}
    try:
        x, y, w, h = [float(values[k]) for k in ('x', 'y', 'width', 'height')]
    except (KeyError, TypeError, ValueError):
        raise ValueError('主体范围格式不正确。')
    if not all(np.isfinite([x, y, w, h])) or min(x, y) < 0 or min(w, h) <= 0 or x+w > 1 or y+h > 1:
        raise ValueError('主体范围必须位于图片内。')
    # GrabCut requires at least a thin band of known background outside the box.
    left, top = max(1, round(x*width)), max(1, round(y*height))
    right, bottom = min(width-1, round((x+w)*width)), min(height-1, round((y+h)*height))
    if right-left < 4 or bottom-top < 4:
        raise ValueError('主体范围过小，请重新框选。')
    rgb = np.array(small.convert('RGB'))
    mask = np.zeros((height, width), np.uint8)
    cv2.grabCut(rgb, mask, (left, top, right-left, bottom-top), np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64), 5, cv2.GC_INIT_WITH_RECT)
    alpha = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype('uint8')
    if np.count_nonzero(alpha) < max(8, width*height*.001):
        raise ValueError('没有分离出清晰主体，请框选主体后重试，或使用圈选。')
    matte = Image.fromarray(alpha).resize(original.size, Image.Resampling.LANCZOS)
    original_alpha = np.asarray(original.getchannel('A'), dtype=np.uint16)
    merged = (original_alpha*np.asarray(matte, dtype=np.uint16)//255).astype('uint8')
    original.putalpha(Image.fromarray(merged))
    result = io.BytesIO()
    original.save(result, format='PNG')
    return result.getvalue()
