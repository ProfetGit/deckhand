"""Colour popover: saturation/brightness square, hue strip, hex field, palette and recent colours.

Applies live while you drag. Click outside to keep the colour, Esc to put the old one back.
"""
import colorsys
import os

from PyQt6.QtCore import QPoint, QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRegularExpressionValidator
from PyQt6.QtWidgets import QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from . import model, motion, style

RECENT_FILE = os.path.join(model.CONFIG_DIR, "recent_colors.json")
PALETTE = [
    "#000000", "#1a1a1d", "#3a3a41", "#8c8c97", "#d0d0d8", "#ffffff",
    "#ff5a5f", "#ff8a3d", "#ffb020", "#f2e14c", "#3ddc84", "#2ec4b6",
    "#3d8bfd", "#6c63ff", "#a259ff", "#ff6bd6",
    "#3a1010", "#3a2410", "#352d0c", "#10301d", "#0f2f33", "#102340", "#241c47", "#3a1236",
]


def load_recent():
    data = model.read_json(RECENT_FILE, [])
    return [c for c in data if isinstance(c, str) and QColor(c).isValid()][:10] if isinstance(data, list) else []


def remember(color):
    c = QColor(color).name()
    rec = [x for x in load_recent() if x != c]
    rec.insert(0, c)
    try:
        model.write_json(RECENT_FILE, rec[:10])
    except OSError:
        pass


class _Drag(QWidget):
    moved = pyqtSignal(float, float)

    def _emit(self, ev):
        r = self.rect()
        x = min(max(ev.position().x(), 0), r.width())
        y = min(max(ev.position().y(), 0), r.height())
        self.moved.emit(x / max(1, r.width()), y / max(1, r.height()))

    def mousePressEvent(self, ev):
        self._emit(ev)

    def mouseMoveEvent(self, ev):
        if ev.buttons() & Qt.MouseButton.LeftButton:
            self._emit(ev)


class SVSquare(_Drag):
    def __init__(self):
        super().__init__()
        self.setFixedSize(236, 150)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.h, self.s, self.v = 0.0, 0.0, 0.0

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        r = QRectF(self.rect())
        path.addRoundedRect(r, 8, 8)
        p.setClipPath(path)
        p.fillRect(self.rect(), QColor.fromHsvF(self.h, 1, 1))
        g = QLinearGradient(0, 0, r.width(), 0)
        g.setColorAt(0, QColor(255, 255, 255, 255))
        g.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillRect(self.rect(), g)
        g2 = QLinearGradient(0, 0, 0, r.height())
        g2.setColorAt(0, QColor(0, 0, 0, 0))
        g2.setColorAt(1, QColor(0, 0, 0, 255))
        p.fillRect(self.rect(), g2)
        p.setClipping(False)
        pos = QPointF(self.s * r.width(), (1 - self.v) * r.height())
        p.setPen(QPen(QColor(0, 0, 0, 160), 3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(pos, 7, 7)
        p.setPen(QPen(QColor("white"), 2))
        p.drawEllipse(pos, 7, 7)


class HueStrip(_Drag):
    def __init__(self):
        super().__init__()
        self.setFixedSize(236, 14)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.h = 0.0

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        g = QLinearGradient(0, 0, r.width(), 0)
        for i in range(0, 7):
            g.setColorAt(i / 6, QColor.fromHsvF(min(i / 6, 0.999), 1, 1))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(r, 7, 7)
        x = self.h * r.width()
        p.setPen(QPen(QColor(0, 0, 0, 120), 3))
        p.setBrush(QColor.fromHsvF(self.h, 1, 1))
        p.drawEllipse(QPointF(min(max(x, 7), r.width() - 7), r.height() / 2), 7.5, 7.5)
        p.setPen(QPen(QColor("white"), 2))
        p.drawEllipse(QPointF(min(max(x, 7), r.width() - 7), r.height() / 2), 7.5, 7.5)


class _Chip(QPushButton):
    def __init__(self, color, size=20):
        super().__init__()
        self.color = color
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(color)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(QColor(255, 255, 255, 60 if not self.underMouse() else 190), 1.4))
        p.setBrush(QColor(self.color))
        p.drawRoundedRect(r, 6, 6)


class ColorPopup(QFrame):
    changed = pyqtSignal(str)

    def __init__(self, color, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setObjectName("colorpop")
        self.setStyleSheet(f"#colorpop{{background:{style.PANEL2};border:1px solid {style.BORDER};border-radius:12px;}}"
                           f"#colorpop QLabel{{background:transparent;color:{style.MUTED};font-size:11px;}}")
        self.original = QColor(color).name() if QColor(color).isValid() else "#000000"
        self._reverted = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)
        self.sv = SVSquare()
        self.hue = HueStrip()
        self.sv.moved.connect(self._sv)
        self.hue.moved.connect(lambda x, _y: self._hue(x))
        lay.addWidget(self.sv)
        lay.addWidget(self.hue)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.prev = _Prev(self.original)
        row.addWidget(self.prev)
        self.hex = QLineEdit()
        self.hex.setMaxLength(7)
        self.hex.setValidator(QRegularExpressionValidator(__import__("PyQt6.QtCore", fromlist=["QRegularExpression"]).QRegularExpression(r"#?[0-9a-fA-F]{0,6}")))
        self.hex.setStyleSheet("font-family: monospace;")
        self.hex.textEdited.connect(self._hex)
        row.addWidget(self.hex, 1)
        reset = QPushButton("Reset")
        reset.setToolTip("Back to the colour it had when you opened this")
        reset.clicked.connect(lambda: self.set_color(self.original))
        row.addWidget(reset)
        lay.addLayout(row)

        lay.addWidget(QLabel("PALETTE"))
        lay.addLayout(self._grid(PALETTE, 8))
        rec = load_recent()
        if rec:
            lay.addWidget(QLabel("RECENT"))
            lay.addLayout(self._grid(rec, 10))
        self.set_color(self.original, emit=False)

    def _grid(self, colors, per_row):
        g = QGridLayout()
        g.setSpacing(6)
        for n, c in enumerate(colors):
            chip = _Chip(c, 24 if per_row <= 8 else 20)
            chip.clicked.connect(lambda _=False, c=c: self.set_color(c))
            g.addWidget(chip, n // per_row, n % per_row)
        g.setColumnStretch(per_row, 1)
        return g

    # ---- colour model -------------------------------------------------------------------
    def set_color(self, c, emit=True):
        q = QColor(c)
        if not q.isValid():
            return
        h, s, v, _ = q.getHsvF()
        # hue is undefined for greys: keep the current hue so the strip does not jump
        if h < 0:
            h = self.hue.h
        self._apply(h, s, v, emit, from_hex=False)

    def _apply(self, h, s, v, emit=True, from_hex=False):
        self.sv.h, self.sv.s, self.sv.v = h, s, v
        self.hue.h = h
        col = QColor.fromHsvF(min(max(h, 0), 0.9999), min(max(s, 0), 1), min(max(v, 0), 1)).name()
        if not from_hex:
            self.hex.setText(col)
        self.prev.set_new(col)
        self.sv.update()
        self.hue.update()
        self._color = col
        if emit:
            self.changed.emit(col)

    def _sv(self, x, y):
        self._apply(self.hue.h, x, 1 - y)

    def _hue(self, x):
        self._apply(x, self.sv.s, self.sv.v)

    def _hex(self, text):
        t = text if text.startswith("#") else "#" + text
        if len(t) == 7 and QColor(t).isValid():
            q = QColor(t)
            h, s, v, _ = q.getHsvF()
            self._apply(self.hue.h if h < 0 else h, s, v, from_hex=True)

    # ---- show / close --------------------------------------------------------------------
    def popup_below(self, widget):
        self.adjustSize()
        g = widget.mapToGlobal(QPoint(0, widget.height() + 6))
        scr = QApplication.screenAt(g) or QApplication.primaryScreen()
        a = scr.availableGeometry()
        x = min(max(g.x() - self.width() + widget.width(), a.left() + 6), a.right() - self.width() - 6)
        y = g.y() if g.y() + self.height() < a.bottom() else widget.mapToGlobal(QPoint(0, 0)).y() - self.height() - 6
        self.move(x, y)
        self.show()
        motion.fade_in(self, 110)

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Escape:
            self._reverted = True
            self.changed.emit(self.original)
            self.close()
            return
        super().keyPressEvent(ev)

    def closeEvent(self, ev):
        if not self._reverted and getattr(self, "_color", self.original) != self.original:
            remember(self._color)
        super().closeEvent(ev)


class _Prev(QWidget):
    """Old colour (left) vs new colour (right)."""

    def __init__(self, old):
        super().__init__()
        self.old, self.new = QColor(old), QColor(old)
        self.setFixedSize(52, 30)
        self.setToolTip("Left: original  ·  Right: new")

    def set_new(self, c):
        self.new = QColor(c)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 7, 7)
        p.setClipPath(path)
        p.fillRect(QRectF(0, 0, r.width() / 2, r.height()), self.old)
        p.fillRect(QRectF(r.width() / 2, 0, r.width() / 2, r.height()), self.new)
        p.setClipping(False)
        p.setPen(QPen(QColor(255, 255, 255, 70), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, 7, 7)
