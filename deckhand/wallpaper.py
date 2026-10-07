"""Deck wallpaper: one image spread across every key of the deck.

The image is laid out on a canvas that includes the physical gaps between keys, then cut into one
slice per key. That way the picture lines up across the gaps like it would on a printed overlay.
Keys with the default black background show their slice; keys with a custom background colour keep it.
"""
import os

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QImageReader, QPainter

from . import icons

GAP_RATIO = 0.28          # gap between keys as a fraction of key size
FITS = ("fill", "fit", "stretch")
DEFAULTS = {"file": "", "fit": "fill", "zoom": 100, "fx": 50, "fy": 50, "dim": 35, "animate": True, "fps": 12}

_cache = {}


def normalize(wp):
    """Return a clean wallpaper dict, or None if there is no usable one."""
    if not isinstance(wp, dict) or not isinstance(wp.get("file"), str) or not wp["file"]:
        return None
    out = dict(DEFAULTS)
    out["file"] = wp["file"][:500]
    if wp.get("fit") in FITS:
        out["fit"] = wp["fit"]
    out["animate"] = bool(wp.get("animate", True))
    for k, lo, hi in (("zoom", 100, 400), ("fx", 0, 100), ("fy", 0, 100), ("dim", 0, 90), ("fps", 5, 20)):
        try:
            out[k] = max(lo, min(hi, int(wp.get(k, DEFAULTS[k]))))
        except (TypeError, ValueError):
            pass
    return out


def canvas_size(cols, rows, px):
    gap = round(px * GAP_RATIO)
    return cols * px + (cols - 1) * gap, rows * px + (rows - 1) * gap, gap


def _compose_image(img, wp, cols, rows, px):
    W, H, _gap = canvas_size(cols, rows, px)
    out = QImage(W, H, QImage.Format.Format_RGB32)
    out.fill(QColor("#000000"))
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    iw, ih = img.width(), img.height()
    z = wp["zoom"] / 100.0
    if wp["fit"] == "stretch":
        p.drawImage(QRectF(0, 0, W, H), img)
    else:
        s = (max(W / iw, H / ih) if wp["fit"] == "fill" else min(W / iw, H / ih)) * z
        w, h = iw * s, ih * s
        x = (W - w) * (wp["fx"] / 100.0) if w > W else (W - w) / 2
        y = (H - h) * (wp["fy"] / 100.0) if h > H else (H - h) / 2
        p.drawImage(QRectF(x, y, w, h), img)
    if wp["dim"]:
        p.fillRect(out.rect(), QColor(0, 0, 0, int(255 * wp["dim"] / 100)))
    p.end()
    return out


def compose(wp, cols, rows, px):
    """The whole-deck canvas (with gaps) for this wallpaper, or None if the image cannot be read.
    Animated images use their first frame here."""
    wp = normalize(wp)
    if not wp:
        return None
    img = icons.file_image(wp["file"])
    if img is None:
        return None
    key = (wp["file"], img.cacheKey(), wp["fit"], wp["zoom"], wp["fx"], wp["fy"], wp["dim"], cols, rows, px)
    hit = _cache.get(key)
    if hit is not None:
        return hit
    out = _compose_image(img, wp, cols, rows, px)
    if len(_cache) > 8:
        _cache.clear()
    _cache[key] = out
    return out


# ---- animation ------------------------------------------------------------------------------
MAX_SOURCE_SIDE = 640            # decode frames no larger than this
MEMORY_BUDGET = 160 * 1024 * 1024
MAX_LOOP_S = 30.0
_anim_info_cache = {}


def animation_info(path):
    """(is_animated, source_frame_count) for a file; cheap, cached by mtime."""
    try:
        st = os.stat(path)
    except OSError:
        return False, 0
    key = (path, st.st_mtime_ns)
    if key not in _anim_info_cache:
        r = QImageReader(path)
        n = r.imageCount()
        _anim_info_cache[key] = (n > 1, n)
        if len(_anim_info_cache) > 64:
            _anim_info_cache.clear()
    return _anim_info_cache[key]


class Animation:
    def __init__(self, frames, fps, source_frames, source_s, truncated):
        self.frames, self.fps = frames, fps
        self.source_frames, self.source_s, self.truncated = source_frames, source_s, truncated

    @property
    def loop_s(self):
        return len(self.frames) / self.fps


def load_animation(wp, cols, rows, px, cancelled=lambda: False):
    """Decode an animated GIF/WebP into deck-sized wallpaper canvases, resampled to wp['fps'].
    Heavy: call from a worker thread. Returns None if the file is not animated or unreadable."""
    wp = normalize(wp)
    if not wp or not animation_info(wp["file"])[0]:
        return None
    reader = QImageReader(wp["file"])
    reader.setAutoTransform(True)
    sz = reader.size()
    if sz.isValid() and (sz.width() > MAX_SOURCE_SIDE or sz.height() > MAX_SOURCE_SIDE):
        sz.scale(MAX_SOURCE_SIDE, MAX_SOURCE_SIDE, Qt.AspectRatioMode.KeepAspectRatio)
        reader.setScaledSize(sz)
    W, H, _gap = canvas_size(cols, rows, px)
    frame_bytes = W * H * 4
    fps = wp["fps"]
    max_steps = int(MAX_LOOP_S * fps)
    max_distinct = max(2, int(MEMORY_BUDGET // frame_bytes))
    frames, distinct, source_n, t = [], 0, 0, 0.0
    # Stream through the file: a source frame is only composed if the resampled timeline (one tick per
    # 1/fps) lands inside its display time. Repeated ticks share one canvas, so memory stays bounded.
    import math
    while reader.canRead() and len(frames) < max_steps and distinct < max_distinct:
        if cancelled():
            return None
        img = reader.read()
        if img.isNull():
            break
        d = reader.nextImageDelay()
        d = 100 if d <= 0 else max(20, d)            # browsers treat 0/very small delays as 100ms
        source_n += 1
        lo, hi = math.ceil(t * fps - 1e-9), math.ceil((t + d / 1000.0) * fps - 1e-9) - 1
        if hi >= lo and lo >= len(frames):
            canvas = _compose_image(img, wp, cols, rows, px)
            distinct += 1
            while len(frames) <= min(hi, max_steps - 1):
                frames.append(canvas)
        t += d / 1000.0
    if len(frames) < 2:
        return None
    total = t
    truncated = reader.canRead()
    src = frames
    return Animation(frames, fps, source_n, total, truncated)


def slice_for(wp, idx, cols, rows, px):
    """The px x px part of the wallpaper behind key idx (None if there is no wallpaper)."""
    canvas = compose(wp, cols, rows, px)
    if canvas is None:
        return None
    gap = round(px * GAP_RATIO)
    c, r = idx % cols, idx // cols
    return canvas.copy(c * (px + gap), r * (px + gap), px, px)
