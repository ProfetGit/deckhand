"""Key face renderer. One code path feeds both the device JPEGs and the editor preview."""
import time

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QGuiApplication, QImage, QLinearGradient, QPainter, QPen

from . import actions, icons, sysinfo

BASE = 72.0


def _font(px, bold=False, mono=False):
    f = QFont("monospace" if mono else QGuiApplication.font().family())
    f.setPixelSize(max(1, int(round(px))))
    f.setBold(bold)
    return f


def _text(p, rect, text, px, color, bold=True, align=Qt.AlignmentFlag.AlignCenter, shadow=True):
    p.setFont(_font(px, bold))
    flags = int(align) | int(Qt.TextFlag.TextWordWrap)
    if shadow:
        p.setPen(QColor(0, 0, 0, 190))
        d = max(1.0, px / 14)
        for dx, dy in ((-d, 0), (d, 0), (0, -d), (0, d), (d, d), (-d, d)):
            p.drawText(rect.translated(dx, dy), flags, text)
    p.setPen(QColor(color))
    p.drawText(rect, flags, text)


def _load_color(v, default):
    c = QColor(v or default)
    return c if c.isValid() else QColor(default)


def _gauge_color(v):
    if v < 60:
        return QColor("#3ddc84")
    if v < 85:
        return QColor("#ffb020")
    return QColor("#ff5a5f")


def _draw_clock(p, s, params, color):
    now = time.localtime()
    fmt = params.get("fmt", "24h")
    sec = params.get("seconds")
    if fmt == "12h":
        t = time.strftime("%I:%M" + (":%S" if sec else ""), now).lstrip("0")
        suffix = time.strftime("%p", now)
    else:
        t = time.strftime("%H:%M" + (":%S" if sec else ""), now)
        suffix = ""
    date = params.get("date", True)
    size = 72 * s
    big = (25 if sec else 28) * s if not date else (23 if sec else 26) * s
    box = QRectF(0, size * (0.16 if date else 0.28), size, size * 0.42)
    _text(p, box, t, big, color, True, shadow=False)
    if suffix:
        _text(p, QRectF(0, box.bottom() - 2 * s, size, 12 * s), suffix, 10 * s, "#9aa0aa", True, shadow=False)
    if date:
        _text(p, QRectF(0, size * 0.66, size, size * 0.2), time.strftime("%a %-d %b", now), 11 * s, "#9aa0aa", False, shadow=False)


def _draw_bar(p, r, label, value, s):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(255, 255, 255, 28))
    p.drawRoundedRect(r, 3 * s, 3 * s)
    p.setBrush(_gauge_color(value))
    p.drawRoundedRect(QRectF(r.x(), r.y(), max(r.height(), r.width() * value / 100), r.height()), 3 * s, 3 * s)
    p.setFont(_font(9.5 * s, True))
    p.setPen(QColor("#e6e8ec"))
    p.drawText(QRectF(r.x() + 4 * s, r.y(), r.width() - 8 * s, r.height()), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), label)
    p.drawText(QRectF(r.x() + 4 * s, r.y(), r.width() - 8 * s, r.height()), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight), f"{value:.0f}%")


def _draw_gauge(p, size, value, label, sub, s):
    r = QRectF(size * 0.15, size * 0.1, size * 0.7, size * 0.7)
    pen = QPen(QColor(255, 255, 255, 30), 5.5 * s)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(r, 225 * 16, -270 * 16)
    pen.setColor(_gauge_color(value))
    p.setPen(pen)
    p.drawArc(r, 225 * 16, int(-270 * 16 * max(0.02, value / 100)))
    _text(p, r, f"{value:.0f}", 19 * s, "#ffffff", True, shadow=False)
    _text(p, QRectF(0, size * 0.77, size, size * 0.2), label + (f" {sub}" if sub else ""), 10 * s, "#9aa0aa", True, shadow=False)


def _draw_sysmon(p, s, params):
    size = 72 * s
    metric = params.get("metric", "both")
    if metric == "both":
        _draw_bar(p, QRectF(6 * s, 12 * s, size - 12 * s, 21 * s), "CPU", sysinfo.cpu_percent(), s)
        _draw_bar(p, QRectF(6 * s, 40 * s, size - 12 * s, 21 * s), "RAM", sysinfo.ram_percent(), s)
    elif metric == "cpu":
        _draw_gauge(p, size, sysinfo.cpu_percent(), "CPU", "", s)
    elif metric == "ram":
        _draw_gauge(p, size, sysinfo.ram_percent(), "RAM", "", s)
    else:
        u, _m, t = sysinfo.gpu_percent()
        if u is None:
            _text(p, QRectF(0, size * 0.28, size, size * 0.3), "N/A", 20 * s, "#9aa0aa", True, shadow=False)
            _text(p, QRectF(0, size * 0.62, size, size * 0.2), "GPU not found", 9.5 * s, "#6c717c", False, shadow=False)
        else:
            _draw_gauge(p, size, u, "GPU", f"{t:.0f}°" if t is not None else "", s)


def _cover(p, img, size):
    """Draw img filling the square (centre-cropped)."""
    s = max(size / img.width(), size / img.height())
    w, h = img.width() * s, img.height() * s
    p.drawImage(QRectF((size - w) / 2, (size - h) / 2, w, h), img)


def _draw_nowplaying(p, s, params):
    size = 72 * s
    np_ = params.get("_np") or {}
    title, artist, status = np_.get("title", ""), np_.get("artist", ""), np_.get("status", "None")
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    if status == "None" or not (title or artist):
        g = QLinearGradient(0, 0, 0, size)
        g.setColorAt(0, QColor("#1b1f29"))
        g.setColorAt(1, QColor("#0f1218"))
        p.fillRect(QRectF(0, 0, size, size), g)
        icons.paint_glyph(p, "music", QRectF(size * 0.3, size * 0.16, size * 0.4, size * 0.4), "#59606e", 1.8)
        _text(p, QRectF(4 * s, size * 0.62, size - 8 * s, size * 0.3), "Nothing\nplaying", 10 * s, "#7b8292", False, shadow=False)
        return
    art = icons.file_image(np_["art"]) if params.get("show_art", True) and np_.get("art") else None
    if art is not None:
        _cover(p, art, size)
    else:
        g = QLinearGradient(0, 0, size, size)
        g.setColorAt(0, QColor("#2a3550"))
        g.setColorAt(1, QColor("#161a26"))
        p.fillRect(QRectF(0, 0, size, size), g)
        icons.paint_glyph(p, "music", QRectF(size * 0.25, size * 0.12, size * 0.5, size * 0.5), "#8fa3d6", 1.8)
    if status != "Playing":
        p.fillRect(QRectF(0, 0, size, size), QColor(0, 0, 0, 120))
        icons.paint_glyph(p, "pause", QRectF(size * 0.74, size * 0.06, size * 0.2, size * 0.2), "#ffffff", 2.4)
    if params.get("show_text", True) and (title or artist):
        g = QLinearGradient(0, size * 0.38, 0, size)
        g.setColorAt(0, QColor(0, 0, 0, 0))
        g.setColorAt(1, QColor(0, 0, 0, 215))
        p.fillRect(QRectF(0, size * 0.38, size, size * 0.62), g)
        m = 4 * s
        avail = size - 2 * m

        def fit(text, sizes, bold):
            """Largest font that fits the width; if none does, the smallest one with an ellipsis."""
            for px in sizes:
                fm = QFontMetricsF(_font(px * s, bold))
                if fm.horizontalAdvance(text) <= avail:
                    return px, text
            px = sizes[-1]
            return px, QFontMetricsF(_font(px * s, bold)).elidedText(text, Qt.TextElideMode.ElideRight, avail)
        tpx, ttxt = fit(title or artist, (11, 10, 9, 8.5), True)
        fm_t = QFontMetricsF(_font(tpx * s, True))
        p.setFont(_font(tpx * s, True))
        p.setPen(QColor("white"))
        p.drawText(QRectF(m, size * 0.57, avail, fm_t.height()), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), ttxt)
        if artist and title:
            apx, atxt = fit(artist, (9, 8.5, 7.5), False)
            fm_a = QFontMetricsF(_font(apx * s, False))
            p.setFont(_font(apx * s, False))
            p.setPen(QColor("#c4c9d4"))
            p.drawText(QRectF(m, size * 0.57 + fm_t.height() + 1 * s, avail, fm_a.height()), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), atxt)


def _clock_text(secs):
    secs = max(0, int(secs))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _draw_counter(p, s, params, color):
    size = 72 * s
    txt = str(params.get("value", 0))
    px = (30 if len(txt) <= 3 else 23 if len(txt) <= 5 else 16) * s
    has_label = bool(params.get("label"))
    _text(p, QRectF(0, size * (0.12 if has_label else 0.2), size, size * 0.5), txt, px, color, True, shadow=False)
    if has_label:
        _text(p, QRectF(4 * s, size * 0.66, size - 8 * s, size * 0.22), params["label"][:14], 10.5 * s, "#9aa0aa", False, shadow=False)


def _draw_timer(p, s, params, color):
    size = 72 * s
    run = params.get("_run") or {}
    secs = run.get("seconds", 0)
    txt = _clock_text(secs)
    col = "#ff6b6b" if run.get("done") else "#3ddc84" if run.get("running") else color
    px = (24 if len(txt) <= 5 else 17) * s
    _text(p, QRectF(0, size * 0.16, size, size * 0.42), txt, px, col, True, shadow=False)
    label = "Done" if run.get("done") else ("Running" if run.get("running") else "Paused" if secs else
                                            ("Countdown" if params.get("mode") == "countdown" else "Stopwatch"))
    _text(p, QRectF(0, size * 0.64, size, size * 0.22), label, 10.5 * s, "#9aa0aa", False, shadow=False)


def _icon_spec(key):
    ic = key.get("icon")
    if ic and ic.get("value"):
        return ic
    a = key.get("action")
    if a and a["type"] in actions.ACTIONS:
        meta = actions.ACTIONS[a["type"]]
        if meta.get("state") and not key.get("alt"):
            return {"kind": "glyph", "value": meta["state"]["off"]["glyph"]}
        return {"kind": "glyph", "value": meta["glyph"]}
    return None


ALT_FIELDS = ("icon", "title", "title_color", "icon_color", "bg")


def has_states(key):
    """Does this key have a second look (own alt, or a built-in live one)?"""
    if not key:
        return False
    if key.get("alt"):
        return True
    a = key.get("action")
    return bool(a and actions.ACTIONS.get(a["type"], {}).get("state") and not (key.get("icon") and key["icon"].get("value")))


def effective(key, state):
    """The key as it should look in the given state (True = active look)."""
    if not state or not key:
        return key
    out = dict(key)
    alt = key.get("alt")
    if alt:
        for f in ALT_FIELDS:
            if f in alt:
                out[f] = alt[f]
        return out
    a = key.get("action")
    meta = actions.ACTIONS.get(a["type"]) if a else None
    if meta and meta.get("state") and not (key.get("icon") and key["icon"].get("value")):
        on = meta["state"]["on"]
        out["icon"] = {"kind": "glyph", "value": on["glyph"]}
        for f in ("bg", "icon_color", "title_color"):
            if f in on:
                out[f] = on[f]
    return out


def _draw_icon(p, ic, rect, color, key):
    kind, val = ic["kind"], ic["value"]
    if kind == "glyph":
        side = min(rect.width(), rect.height())
        r = QRectF(0, 0, side, side)
        r.moveCenter(rect.center())
        icons.paint_glyph(p, val, r, color, 2.0 if side > 30 else 2.4)
        return
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    if kind == "theme":
        img = icons.theme_image(val, 128)
        if img is None:
            side = min(rect.width(), rect.height()) * 0.6
            box = QRectF(0, 0, side, side)
            box.moveCenter(rect.center())
            icons.paint_glyph(p, "alert", box, "#ff6b6b", 2.2)
            return
        side = min(rect.width(), rect.height())
        r = QRectF(0, 0, side, side)
        r.moveCenter(rect.center())
        p.drawImage(r, img)
    else:
        img = icons.file_image(val)
        if img is None:
            side = min(rect.width(), rect.height()) * 0.6
            box = QRectF(0, 0, side, side)
            box.moveCenter(rect.center())
            icons.paint_glyph(p, "alert", box, "#ff6b6b", 2.2)
            return
        w, h = img.width(), img.height()
        f = min(rect.width() / w, rect.height() / h)
        r = QRectF(0, 0, w * f, h * f)
        r.moveCenter(rect.center())
        p.drawImage(r, img)


def render_key(key, size=72, pressed=False, state=False, backdrop=None, overlay=False):
    key = effective(key, state)
    s = size / BASE
    key = key or {}
    bg = _load_color(key.get("bg"), "#000000")
    if overlay:
        # foreground only, on transparency: composited over each animated wallpaper frame
        img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
    else:
        img = QImage(size, size, QImage.Format.Format_RGB32)
        img.fill(bg)
    p = QPainter(img)
    if backdrop is not None and bg == QColor("#000000") and not overlay:
        p.drawImage(0, 0, backdrop)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    if pressed:
        p.translate(size / 2, size / 2)
        p.scale(0.9, 0.9)
        p.translate(-size / 2, -size / 2)
        p.setClipRect(QRectF(0, 0, size, size))
    action = key.get("action")
    atype = action["type"] if action else None
    custom = key.get("icon") and key["icon"].get("value")
    title = key.get("title", "")
    show_title = key.get("show_title", True) and bool(title)
    tsize = key.get("title_size", 14) * s
    tcolor = key.get("title_color", "#ffffff")
    icolor = key.get("icon_color", "#ffffff")
    pos = key.get("title_pos", "bottom")

    dyn = atype and actions.ACTIONS.get(atype, {}).get("dynamic") and not custom
    if dyn:
        if atype == "clock":
            _draw_clock(p, s, action["params"], tcolor)
        elif atype == "nowplaying":
            _draw_nowplaying(p, s, action["params"])
        elif atype == "counter":
            _draw_counter(p, s, action["params"], tcolor)
        elif atype == "timer":
            _draw_timer(p, s, action["params"], tcolor)
        else:
            _draw_sysmon(p, s, action["params"])
    else:
        ic = _icon_spec(key)
        if ic:
            pad = 7 * s
            area = QRectF(pad, pad, size - 2 * pad, size - 2 * pad)
            if ic["kind"] == "file":
                area = QRectF(0, 0, size, size)
            elif show_title and pos != "middle":
                th = QFontMetricsF(_font(tsize, key.get("bold", True))).height() * min(2, title.count("\n") + 1)
                if pos == "bottom":
                    area = QRectF(pad, pad - 1 * s, size - 2 * pad, size - th - 2 * pad + 4 * s)
                else:
                    area = QRectF(pad, th + 2 * s, size - 2 * pad, size - th - 2 * pad)
            elif ic["kind"] == "glyph":
                area = QRectF(size * 0.2, size * 0.2, size * 0.6, size * 0.6)
            _draw_icon(p, ic, area, icolor, key)

    if show_title:
        m = 3 * s
        box = QRectF(m, m, size - 2 * m, size - 2 * m)
        al = {"bottom": Qt.AlignmentFlag.AlignBottom, "top": Qt.AlignmentFlag.AlignTop,
              "middle": Qt.AlignmentFlag.AlignVCenter}.get(pos, Qt.AlignmentFlag.AlignBottom)
        _text(p, box, title, tsize, tcolor, key.get("bold", True), Qt.AlignmentFlag.AlignHCenter | al)
    p.end()
    if pressed:
        q = QPainter(img)
        q.fillRect(img.rect(), QColor(0, 0, 0, 70))
        q.end()
    return img


def to_jpeg(img, quality=92):
    flipped = img.mirrored(True, True)
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    flipped.save(buf, "JPEG", quality)
    return bytes(ba)


def error_tile(size=72):
    """What a key shows if rendering it failed: visible, harmless, never a crash."""
    img = QImage(size, size, QImage.Format.Format_RGB32)
    img.fill(QColor("#2a1214"))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    side = size * 0.46
    icons.paint_glyph(p, "alert", QRectF((size - side) / 2, (size - side) / 2, side, side), "#ff6b6b", 2.0)
    p.end()
    return img
