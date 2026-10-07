"""Built-in glyph set, theme icon lookup and installed-app discovery."""
import configparser
import os
import re
from functools import lru_cache

from PyQt6.QtCore import QByteArray, QRectF, Qt
from PyQt6.QtGui import QIcon, QImage, QImageReader, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

_F = 'fill="currentColor"'
_SPK = '<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>'

GLYPHS = {
    "play": f'<polygon points="7 4 20 12 7 20" {_F}/>',
    "pause": f'<rect x="6" y="4" width="4" height="16" rx="1" {_F}/><rect x="14" y="4" width="4" height="16" rx="1" {_F}/>',
    "play-pause": f'<polygon points="2 5 10 12 2 19" {_F}/><line x1="15" y1="5" x2="15" y2="19"/><line x1="21" y1="5" x2="21" y2="19"/>',
    "next": f'<polygon points="5 4 15 12 5 20" {_F}/><line x1="19" y1="5" x2="19" y2="19"/>',
    "prev": f'<polygon points="19 4 9 12 19 20" {_F}/><line x1="5" y1="5" x2="5" y2="19"/>',
    "stop": f'<rect x="6" y="6" width="12" height="12" rx="2" {_F}/>',
    "volume-up": _SPK + '<path d="M15.5 8.5a5 5 0 0 1 0 7"/><path d="M19 5a10 10 0 0 1 0 14"/>',
    "volume-down": _SPK + '<path d="M15.5 8.5a5 5 0 0 1 0 7"/>',
    "volume-mute": _SPK + '<line x1="22" y1="9" x2="16" y2="15"/><line x1="16" y1="9" x2="22" y2="15"/>',
    "mic": '<path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="22"/>',
    "mic-off": '<line x1="2" y1="2" x2="22" y2="22"/><path d="M9 9v3a3 3 0 0 0 5.12 2.12M15 9.34V5a3 3 0 0 0-5.94-.6"/><path d="M17 16.95A7 7 0 0 1 5 12v-2m14 0v2a7 7 0 0 1-.11 1.23"/><line x1="12" y1="19" x2="12" y2="22"/>',
    "lock": '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    "moon": '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "file": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/>',
    "arrow-left": '<line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/>',
    "arrow-right": '<line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/>',
    "arrow-up": '<line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/>',
    "arrow-down": '<line x1="12" y1="5" x2="12" y2="19"/><polyline points="19 12 12 19 5 12"/>',
    "keyboard": '<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M6 9h.01M10 9h.01M14 9h.01M18 9h.01M7 15h10"/>',
    "globe": '<circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>',
    "terminal": '<polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/>',
    "text": '<polyline points="4 7 4 4 20 4 20 7"/><line x1="9" y1="20" x2="15" y2="20"/><line x1="12" y1="4" x2="12" y2="20"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    "cpu": '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 14h3M1 9h3M1 14h3"/>',
    "camera": '<path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>',
    "sun-dim": '<circle cx="12" cy="12" r="2.5"/><path d="M12 3v1.5M12 19.5V21M5.6 5.6l1 1M17.4 17.4l1 1M3 12h1.5M19.5 12H21M6.6 17.4l-1 1M18.4 5.6l-1 1"/>',
    "layers": '<polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/>',
    "grid": '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/>',
    "power": '<path d="M18.36 6.64a9 9 0 1 1-12.73 0"/><line x1="12" y1="2" x2="12" y2="12"/>',
    "home": '<path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>',
    "music": '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
    "video": '<polygon points="23 7 16 12 23 17 23 7"/><rect x="1" y="5" width="15" height="14" rx="2"/>',
    "mail": '<path d="M4 4h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z"/><polyline points="22 6 12 13 2 6"/>',
    "heart": '<path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>',
    "star": '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>',
    "zap": '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
    "bell": '<path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/>',
    "gamepad": '<line x1="6" y1="12" x2="10" y2="12"/><line x1="8" y1="10" x2="8" y2="14"/><path d="M15 13h.01M18 11h.01"/><rect x="2" y="6" width="20" height="12" rx="4"/>',
    "headphones": '<path d="M3 18v-6a9 9 0 0 1 18 0v6"/><path d="M21 19a2 2 0 0 1-2 2h-1a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2h3zM3 19a2 2 0 0 0 2 2h1a2 2 0 0 0 2-2v-3a2 2 0 0 0-2-2H3z"/>',
    "monitor": '<rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>',
    "code": '<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>',
    "link": '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
    "copy": '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    "refresh": '<polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>',
    "download": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
    "wifi": '<path d="M5 12.55a11 11 0 0 1 14.08 0M1.42 9a16 16 0 0 1 21.16 0M8.53 16.11a6 6 0 0 1 6.95 0"/><line x1="12" y1="20" x2="12.01" y2="20"/>',
    "plus": '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
    "x": '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
    "check": '<polyline points="20 6 9 17 4 12"/>',
    "search": '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33h0a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51h0a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82v0a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
    "chevron-down": '<polyline points="6 9 12 15 18 9"/>',
    "chevron-right": '<polyline points="9 18 15 12 9 6"/>',
    "trash": '<polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
    "undo": '<polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/>',
    "redo": '<polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>',
    "image": '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/>',
    "more": '<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/>',
    "usb": '<circle cx="10" cy="7" r="1"/><circle cx="4" cy="20" r="1"/><path d="M4.7 19.3 19 5"/><path d="m21 3-3 1 2 2z"/><path d="M9.26 7.68 5 12l2 5"/><path d="m10 14 5 2 3.5-3.5"/><path d="m18 12 1-1 1 1-1 1z"/>',
    "palette": '<circle cx="13.5" cy="6.5" r="1"/><circle cx="17.5" cy="10.5" r="1"/><circle cx="8.5" cy="7.5" r="1"/><circle cx="6.5" cy="12.5" r="1"/><path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.93 0 1.5-.67 1.5-1.5 0-.39-.15-.74-.39-1.04-.23-.29-.38-.63-.38-1.02 0-.83.67-1.5 1.5-1.5H16c3.31 0 6-2.69 6-6 0-4.96-4.48-9-10-9z"/>',
    "briefcase": '<rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/>',
    "rocket": '<path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09z"/><path d="m12 15-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z"/><path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5"/>',
    "slack": '<rect x="3" y="3" width="18" height="18" rx="3"/><path d="M8 9h8M8 13h5"/>',
    "alert": '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
    "refresh-cw": '<polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>',
    "bot": '<rect x="4" y="8" width="16" height="12" rx="3"/><path d="M12 8V4"/><circle cx="12" cy="3" r="1"/><circle cx="9" cy="14" r="1"/><circle cx="15" cy="14" r="1"/><path d="M2 14h2M20 14h2"/>',
    "plug": '<path d="M9 2v6M15 2v6M6 8h12v4a6 6 0 0 1-12 0z"/><path d="M12 18v4"/>',
    "discord": '<path d="M8 8c2.5-1 5.5-1 8 0l1.5 1.5c1.2 2.2 1.8 4.6 2 7-1.3 1-2.8 1.7-4.4 2l-.8-1.5M8 8 6.5 9.5c-1.2 2.2-1.8 4.6-2 7 1.3 1 2.8 1.7 4.4 2l.8-1.5M8.5 17c2 .6 5 .6 7 0"/><circle cx="9" cy="13" r="1"/><circle cx="15" cy="13" r="1"/>',
}

GLYPH_NAMES = sorted(GLYPHS)


def glyph_svg(name, color="#ffffff", stroke=2.0):
    body = GLYPHS.get(name, GLYPHS["grid"]).replace("currentColor", color)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
        f'stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
    )


@lru_cache(maxsize=512)
def _glyph_renderer(name, color, stroke):
    return QSvgRenderer(QByteArray(glyph_svg(name, color, stroke).encode()))


def paint_glyph(p: QPainter, name, rect: QRectF, color="#ffffff", stroke=2.0):
    _glyph_renderer(name, color, stroke).render(p, rect)


def glyph_pixmap(name, size=20, color="#ffffff", stroke=2.0, dpr=2.0):
    px = QPixmap(int(size * dpr), int(size * dpr))
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    paint_glyph(p, name, QRectF(0, 0, size * dpr, size * dpr), color, stroke)
    p.end()
    px.setDevicePixelRatio(dpr)
    return px


def glyph_icon(name, size=20, color="#ffffff", stroke=2.0):
    return QIcon(glyph_pixmap(name, size, color, stroke))


@lru_cache(maxsize=1024)
def theme_image(name, size):
    ic = QIcon.fromTheme(name)
    if ic.isNull():
        return None
    px = ic.pixmap(size, size)
    return px.toImage() if not px.isNull() else None


_IMG_CACHE = {}
MAX_IMG_SIDE = 1024


def file_image(path):
    """Load a key image once (cached by mtime) and never bigger than 1024px, so a huge or
    missing file cannot stall rendering. Returns None if it cannot be read."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    sig = (path, st.st_mtime_ns, st.st_size)
    if sig in _IMG_CACHE:
        return _IMG_CACHE[sig]
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    sz = reader.size()
    if sz.isValid() and (sz.width() > MAX_IMG_SIDE or sz.height() > MAX_IMG_SIDE):
        sz.scale(MAX_IMG_SIDE, MAX_IMG_SIDE, Qt.AspectRatioMode.KeepAspectRatio)
        reader.setScaledSize(sz)
    img = reader.read()
    img = None if img.isNull() else img
    if len(_IMG_CACHE) > 64:
        _IMG_CACHE.clear()
    _IMG_CACHE[sig] = img
    return img


_APP_DIRS = [
    "/usr/share/applications",
    "/usr/local/share/applications",
    os.path.expanduser("~/.local/share/applications"),
    "/var/lib/flatpak/exports/share/applications",
    os.path.expanduser("~/.local/share/flatpak/exports/share/applications"),
]
_apps_cache = None


def installed_apps(refresh=False):
    """[{id, name, icon, exec, path}] sorted by name, from .desktop files."""
    global _apps_cache
    if _apps_cache is not None and not refresh:
        return _apps_cache
    seen = {}
    for d in _APP_DIRS:
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            if not fn.endswith(".desktop"):
                continue
            path = os.path.join(d, fn)
            cp = configparser.RawConfigParser(strict=False, interpolation=None)
            cp.optionxform = str
            try:
                cp.read(path, encoding="utf-8")
                e = cp["Desktop Entry"]
            except Exception:
                continue
            if e.get("Type") != "Application" or e.get("NoDisplay", "").lower() == "true" or e.get("Hidden", "").lower() == "true":
                continue
            name = e.get("Name")
            if not name:
                continue
            seen[fn] = {
                "id": fn,
                "name": name,
                "icon": e.get("Icon", ""),
                "exec": re.sub(r"%[a-zA-Z]", "", e.get("Exec", "")).strip(),
                "path": path,
            }
    _apps_cache = sorted(seen.values(), key=lambda a: a["name"].lower())
    return _apps_cache


def find_app(app_id):
    for a in installed_apps():
        if a["id"] == app_id:
            return a
    return None


def app_icon(icon_name):
    if not icon_name:
        return QIcon()
    if os.path.isabs(icon_name):
        return QIcon(icon_name)
    return QIcon.fromTheme(icon_name)


_theme_cache = None
_theme_started = False


def theme_names_ready():
    return _theme_cache is not None


def warm_caches(theme=None):
    """Scan installed apps and the icon theme on a background thread so no dialog ever waits for them."""
    global _theme_started
    if _theme_started:
        return
    _theme_started = True
    theme = theme or QIcon.themeName() or "hicolor"
    import threading

    def work():
        global _theme_cache
        try:
            installed_apps()
        except Exception:
            pass
        try:
            _theme_cache = _scan_theme(theme)
        except Exception:
            _theme_cache = []
    threading.Thread(target=work, daemon=True).start()


def theme_icon_names():
    """All icon names in the active theme chain (+hicolor); scanned once, in the background."""
    global _theme_cache
    if _theme_cache is None:
        if not _theme_started:
            _theme_cache = _scan_theme(QIcon.themeName() or "hicolor")
        else:
            return []
    return _theme_cache


def _scan_theme(theme):
    names = set()
    roots = [p for p in QIcon.themeSearchPaths() if os.path.isdir(p)]
    visited = set()

    def inherits(t):
        for r in roots:
            f = os.path.join(r, t, "index.theme")
            if os.path.isfile(f):
                cp = configparser.RawConfigParser(strict=False, interpolation=None)
                try:
                    cp.read(f, encoding="utf-8")
                    return [x for x in cp.get("Icon Theme", "Inherits", fallback="").split(",") if x]
                except Exception:
                    return []
        return []

    queue = [theme, "hicolor"]
    while queue:
        t = queue.pop(0)
        if t in visited:
            continue
        visited.add(t)
        queue.extend(inherits(t))
        for r in roots:
            base = os.path.join(r, t)
            if not os.path.isdir(base):
                continue
            for dp, _dn, fns in os.walk(base):
                for fn in fns:
                    if fn.endswith((".svg", ".png", ".svgz")):
                        names.add(fn.rsplit(".", 1)[0])
    return sorted(n for n in names if not n.endswith("-symbolic.symbolic"))
