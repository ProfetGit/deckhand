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


def _pcolor(params, key, default):
    """Colour option: '' / missing / invalid means 'auto' and gives the default."""
    v = params.get(key)
    c = QColor(v) if isinstance(v, str) and v else QColor()
    return c if c.isValid() else QColor(default)


def _pint(params, key, default, lo, hi):
    try:
        v = int(params.get(key, default))
    except (TypeError, ValueError):
        v = default
    return max(lo, min(hi, v))


def _pscale(params):
    return _pint(params, "scale", 100, 50, 140) / 100


def _gauge_color(v, params=None):
    params = params or {}
    if params.get("color_mode") == "fixed":
        return _pcolor(params, "bar_color", "#3ddc84")
    crit = _pint(params, "crit", 85, 1, 100)
    warn = min(_pint(params, "warn", 60, 1, 99), crit)
    if v < warn:
        return QColor("#3ddc84")
    if v < crit:
        return QColor("#ffb020")
    return QColor("#ff5a5f")


DATE_FORMATS = actions.DATE_STRFTIME


def _draw_clock(p, s, params, color):
    now = time.localtime()
    fmt = params.get("fmt", "24h")
    sec = params.get("seconds")
    sc = _pscale(params)
    tcol = _pcolor(params, "color", color)
    if fmt == "12h":
        t = time.strftime("%I:%M" + (":%S" if sec else ""), now).lstrip("0")
        suffix = ("AM" if now.tm_hour < 12 else "PM") if params.get("ampm", True) else ""
    else:
        t = time.strftime("%H:%M" + (":%S" if sec else ""), now)
        suffix = ""
    date = params.get("date", True)
    size = 72 * s
    big = ((25 if sec else 28) * s if not date else (23 if sec else 26) * s) * sc
    box = QRectF(0, size * (0.16 if date else 0.28), size, size * 0.42)
    if not date and not suffix:
        box = QRectF(0, size * 0.25, size, size * 0.5)
    _text(p, box, t, big, tcol, True, shadow=False)
    if suffix:
        _text(p, QRectF(0, (3 if date else box.bottom() / s - 2) * s, size, 12 * s), suffix, 10 * s, _pcolor(params, "date_color", "#9aa0aa"), True, shadow=False)
    if date:
        fmt_d = DATE_FORMATS.get(params.get("date_fmt"), DATE_FORMATS["short"])
        _text(p, QRectF(0, size * 0.66, size, size * 0.2), time.strftime(fmt_d, now), 11 * s, _pcolor(params, "date_color", "#9aa0aa"), False, shadow=False)


def _draw_bar(p, r, label, value, s, params):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(255, 255, 255, 28))
    p.drawRoundedRect(r, 3 * s, 3 * s)
    p.setBrush(_gauge_color(value, params))
    p.drawRoundedRect(QRectF(r.x(), r.y(), max(r.height(), r.width() * value / 100), r.height()), 3 * s, 3 * s)
    p.setFont(_font(9.5 * s, True))
    inner = QRectF(r.x() + 4 * s, r.y(), r.width() - 8 * s, r.height())
    if params.get("show_label", True):
        p.setPen(_pcolor(params, "label_color", "#e6e8ec"))
        p.drawText(inner, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), label)
    if params.get("show_value", True):
        p.setPen(_pcolor(params, "value_color", "#e6e8ec"))
        p.drawText(inner, int(Qt.AlignmentFlag.AlignVCenter | (Qt.AlignmentFlag.AlignRight if params.get("show_label", True) else Qt.AlignmentFlag.AlignHCenter)), f"{value:.0f}%")


def _draw_gauge(p, size, value, label, sub, s, params):
    show_label, show_value = params.get("show_label", True), params.get("show_value", True)
    r = QRectF(size * 0.15, size * 0.1, size * 0.7, size * 0.7)
    if not show_label:
        r = QRectF(size * 0.13, size * 0.13, size * 0.74, size * 0.74)
    pen = QPen(QColor(255, 255, 255, 30), 5.5 * s)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(r, 225 * 16, -270 * 16)
    pen.setColor(_gauge_color(value, params))
    p.setPen(pen)
    p.drawArc(r, 225 * 16, int(-270 * 16 * max(0.02, value / 100)))
    if show_value:
        _text(p, r, f"{value:.0f}", 19 * s, _pcolor(params, "value_color", "#ffffff"), True, shadow=False)
    if show_label and (label or sub):
        _text(p, QRectF(0, size * 0.77, size, size * 0.2), label + (f" {sub}" if sub else ""), 10 * s,
              _pcolor(params, "label_color", "#9aa0aa"), True, shadow=False)
    elif sub:
        _text(p, QRectF(0, size * 0.77, size, size * 0.2), sub, 10 * s, _pcolor(params, "label_color", "#9aa0aa"), True, shadow=False)


def _draw_sysmon(p, s, params):
    size = 72 * s
    metric = params.get("metric", "both")
    if metric == "both":
        _draw_bar(p, QRectF(6 * s, 12 * s, size - 12 * s, 21 * s), "CPU", sysinfo.cpu_percent(), s, params)
        _draw_bar(p, QRectF(6 * s, 40 * s, size - 12 * s, 21 * s), "RAM", sysinfo.ram_percent(), s, params)
    elif metric == "cpu":
        _draw_gauge(p, size, sysinfo.cpu_percent(), "CPU", "", s, params)
    elif metric == "ram":
        _draw_gauge(p, size, sysinfo.ram_percent(), "RAM", "", s, params)
    else:
        u, _m, t = sysinfo.gpu_percent()
        if u is None:
            _text(p, QRectF(0, size * 0.28, size, size * 0.3), "N/A", 20 * s, "#9aa0aa", True, shadow=False)
            _text(p, QRectF(0, size * 0.62, size, size * 0.2), "GPU not found", 9.5 * s, "#6c717c", False, shadow=False)
        else:
            sub = f"{t:.0f}°" if t is not None and params.get("show_temp", True) else ""
            _draw_gauge(p, size, u, "GPU", sub, s, params)


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
        if params.get("dim_paused", True):
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
        p.setPen(_pcolor(params, "text_color", "#ffffff"))
        p.drawText(QRectF(m, size * 0.57, avail, fm_t.height()), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), ttxt)
        if artist and title and params.get("show_artist", True):
            apx, atxt = fit(artist, (9, 8.5, 7.5), False)
            fm_a = QFontMetricsF(_font(apx * s, False))
            p.setFont(_font(apx * s, False))
            p.setPen(_pcolor(params, "artist_color", "#c4c9d4"))
            p.drawText(QRectF(m, size * 0.57 + fm_t.height() + 1 * s, avail, fm_a.height()), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), atxt)


def _clock_text(secs):
    secs = max(0, int(secs))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _draw_counter(p, s, params, color):
    size = 72 * s
    try:
        value = int(params.get("value", 0))
    except (TypeError, ValueError):
        value = 0
    txt = str(value)
    px = (30 if len(txt) <= 3 else 23 if len(txt) <= 5 else 16) * s * _pscale(params)
    label = str(params.get("label") or "")
    col = _pcolor(params, "negative_color", color) if value < 0 and params.get("negative_color") else _pcolor(params, "color", color)
    _text(p, QRectF(0, size * (0.12 if label else 0.2), size, size * 0.5), txt, px, col, True, shadow=False)
    if label:
        _text(p, QRectF(4 * s, size * 0.66, size - 8 * s, size * 0.22), label[:14], 10.5 * s, _pcolor(params, "label_color", "#9aa0aa"), False, shadow=False)


def _draw_timer(p, s, params, color):
    size = 72 * s
    run = params.get("_run") or {}
    secs = run.get("seconds", 0)
    txt = _clock_text(secs)
    idle = run.get("idle", not secs)
    if run.get("done"):
        col, label = _pcolor(params, "done_color", "#ff6b6b"), "Done!"
    elif run.get("running"):
        col, label = _pcolor(params, "run_color", "#3ddc84"), "Running"
    elif idle:
        col, label = _pcolor(params, "color", color), "Countdown" if params.get("mode") == "countdown" else "Stopwatch"
    else:
        col, label = _pcolor(params, "paused_color", _pcolor(params, "color", color).name()), "Paused"
    px = (24 if len(txt) <= 5 else 17) * s * _pscale(params)
    caption = params.get("show_caption", True)
    _text(p, QRectF(0, size * (0.16 if caption else 0.25), size, size * (0.42 if caption else 0.5)), txt, px, col, True, shadow=False)
    if caption:
        ccol = _pcolor(params, "caption_color", "#ff9a9a" if run.get("done") else "#9aa0aa")
        _text(p, QRectF(0, size * 0.64, size, size * 0.22), label, 10.5 * s, ccol, bool(run.get("done")), shadow=False)


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
