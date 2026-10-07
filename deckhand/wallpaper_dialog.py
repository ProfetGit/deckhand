"""Wallpaper dialog: pick one image for the whole deck and tune how it is cut across the keys."""
import os

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPixmap
from PyQt6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QSizePolicy, QSlider, QVBoxLayout,
                             QWidget)

from . import errors, icons, style, wallpaper
from .iconpicker import import_image
from .widgets import IMAGE_EXT, Segmented, Switch


class DeckPreview(QWidget):
    """The deck exactly as it will look: the real key renderer, wallpaper included."""

    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self.setMinimumSize(420, 250)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def paintEvent(self, _):
        e = self.engine
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        px = 96
        W, H, gap = wallpaper.canvas_size(e.cols, e.rows, px)
        pad = 18
        s = min((self.width() - 2 * pad) / W, (self.height() - 2 * pad) / H)
        ox, oy = (self.width() - W * s) / 2, (self.height() - H * s) / 2
        body = QRectF(ox - pad * 0.6, oy - pad * 0.6, W * s + pad * 1.2, H * s + pad * 1.2)
        p.setPen(QColor("#3a3a41"))
        p.setBrush(QColor("#1d1d21"))
        p.drawRoundedRect(body, 16, 16)
        p.setPen(Qt.PenStyle.NoPen)
        rad = px * s * 0.13
        for i in range(e.n_keys):
            c, r = i % e.cols, i // e.cols
            rect = QRectF(ox + c * (px + gap) * s, oy + r * (px + gap) * s, px * s, px * s)
            img = e.render(i, int(px * s * self.devicePixelRatioF()))
            pm = QPixmap.fromImage(img)
            pm.setDevicePixelRatio(self.devicePixelRatioF())
            p.save()
            from PyQt6.QtGui import QPainterPath
            path = QPainterPath()
            path.addRoundedRect(rect, rad, rad)
            p.setClipPath(path)
            p.drawPixmap(rect.topLeft(), pm)
            p.restore()
        if not e.profile.get("wallpaper"):
            p.setPen(QColor(style.MUTED))
            p.drawText(self.rect(), int(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter), "No wallpaper set")


class WallpaperDialog(QDialog):
    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.setWindowTitle("Deck wallpaper")
        self.setAcceptDrops(True)
        self.resize(640, 640)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(12)
        t = QLabel("Deck wallpaper")
        t.setObjectName("h1")
        t.setStyleSheet("font-size:17px;font-weight:700;")
        lay.addWidget(t)
        sub = QLabel("One image spread across every key of this profile. Keys with a black background show it; keys with their own colour keep theirs.")
        sub.setWordWrap(True)
        sub.setObjectName("muted")
        lay.addWidget(sub)
        self.preview = DeckPreview(engine)
        lay.addWidget(self.preview, 1)

        row = QHBoxLayout()
        self.choose = QPushButton("  Choose image…")
        self.choose.setIcon(icons.glyph_icon("image", 16, "#d0d0d8"))
        self.choose.clicked.connect(self._pick)
        self.remove = QPushButton("Remove wallpaper")
        self.remove.setObjectName("danger")
        self.remove.clicked.connect(self._remove)
        row.addWidget(self.choose)
        row.addWidget(self.remove)
        row.addStretch(1)
        self.fit = Segmented([("fill", "Fill", "Cover the whole deck, cropping the edges", False),
                              ("fit", "Fit", "Show the whole image, with black bars if needed", False),
                              ("stretch", "Stretch", "Stretch to the deck's shape", False)])
        self.fit.changed.connect(lambda v: self._set(fit=v))
        row.addWidget(self.fit)
        lay.addLayout(row)

        self.anim_row = QWidget()
        ar = QHBoxLayout(self.anim_row)
        ar.setContentsMargins(0, 0, 0, 0)
        self.anim_lbl = QLabel()
        self.anim_lbl.setObjectName("muted")
        self.anim_lbl.setWordWrap(True)
        ar.addWidget(self.anim_lbl, 1)
        ar.addWidget(QLabel("Play animation"))
        self.anim_sw = Switch(True)
        self.anim_sw.toggled.connect(lambda v: self._set(animate=v))
        ar.addWidget(self.anim_sw)
        lay.addWidget(self.anim_row)
        self.sliders = {}
        for key, label, lo, hi, suffix in (("fps", "Frame rate", 5, 20, " fps"), ("zoom", "Zoom", 100, 400, "%"), ("fx", "Position left–right", 0, 100, ""),
                                           ("fy", "Position up–down", 0, 100, ""), ("dim", "Darken", 0, 90, "%")):
            r = QHBoxLayout()
            name = QLabel(label)
            name.setFixedWidth(140)
            r.addWidget(name)
            sl = QSlider(Qt.Orientation.Horizontal)
            sl.setRange(lo, hi)
            val = QLabel()
            val.setFixedWidth(46)
            val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            sl.valueChanged.connect(lambda v, k=key, val=val, suf=suffix: (val.setText(f"{v}{suf}"), self._set(**{k: v})))
            r.addWidget(sl, 1)
            r.addWidget(val)
            lay.addLayout(r)
            self.sliders[key] = (sl, val, suffix)
        hint = QLabel("Darken keeps icons readable. Tip: a wide image works best on the XL; use Position to choose which part shows.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{style.MUTED};font-size:11px;")
        lay.addWidget(hint)
        done = QPushButton("Done")
        done.setObjectName("primary")
        done.clicked.connect(self.accept)
        br = QHBoxLayout()
        br.addStretch(1)
        br.addWidget(done)
        lay.addLayout(br)
        engine.changed.connect(self._sync)
        engine.anim_changed.connect(self._sync)
        engine.wall_frame.connect(self.preview.update)
        self._sync()

    # ---- state ------------------------------------------------------------------------
    def _cfg(self):
        return wallpaper.normalize(self.engine.profile.get("wallpaper"))

    def _sync(self):
        cfg = self._cfg()
        for key, (sl, val, suf) in self.sliders.items():
            sl.blockSignals(True)
            sl.setValue(cfg[key] if cfg else wallpaper.DEFAULTS[key])
            sl.setEnabled(bool(cfg) and not (cfg["fit"] == "stretch" and key in ("zoom", "fx", "fy")))
            if key == "fps":
                sl.setEnabled(bool(cfg) and cfg["animate"])
            val.setText(f"{sl.value()}{suf}")
            sl.blockSignals(False)
        animated = bool(cfg) and wallpaper.animation_info(cfg["file"])[0]
        self.anim_row.setVisible(animated)
        self.sliders["fps"][0].setVisible(animated)
        self.sliders["fps"][1].setVisible(animated)
        for w in self.findChildren(QLabel):
            if w.text() == "Frame rate":
                w.setVisible(animated)
        if animated:
            self.anim_sw.blockSignals(True)
            self.anim_sw.setChecked(cfg["animate"])
            self.anim_sw.blockSignals(False)
            st = self.engine.anim_state
            if st["state"] == "loading":
                txt = "Preparing the animation…"
            elif st["state"] == "ready":
                txt = (f"Animated  ·  {st['frames']} frames  ·  {st['seconds']} s loop at {st['fps']} fps"
                       + ("  ·  long animations are cut to fit memory" if st.get("truncated") else ""))
            elif st["state"] == "error":
                txt = "This animation could not be decoded; showing its first frame."
            else:
                txt = "Animation paused: showing the first frame."
            self.anim_lbl.setText(txt)
        self.fit.set_value(cfg["fit"] if cfg else "fill")
        self.fit.setEnabled(bool(cfg))
        self.remove.setEnabled(bool(cfg))
        self.choose.setText("  Change image…" if cfg else "  Choose image…")
        self.preview.update()

    def _set(self, **changes):
        cfg = self._cfg()
        if not cfg:
            return
        cfg.update(changes)
        self.engine.set_wallpaper(cfg, coalesce="wallpaper")

    def _use_file(self, path):
        try:
            if icons.file_image(path) is None:
                raise ValueError("that file is not an image Deckhand can read")
            spec = import_image(path)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Could not use that image", errors.explain(e))
            return
        cfg = self._cfg() or dict(wallpaper.DEFAULTS)
        cfg["file"] = spec["value"]
        self.engine.set_wallpaper(cfg)

    def _pick(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose a wallpaper", os.path.expanduser("~/Pictures"),
                                              "Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif)")
        if path:
            self._use_file(path)

    def _remove(self):
        self.engine.set_wallpaper(None)

    def dragEnterEvent(self, ev):
        if any(u.isLocalFile() and u.toLocalFile().lower().endswith(IMAGE_EXT) for u in ev.mimeData().urls()):
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        for u in ev.mimeData().urls():
            if u.isLocalFile() and u.toLocalFile().lower().endswith(IMAGE_EXT):
                self._use_file(u.toLocalFile())
                break
