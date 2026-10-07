"""Loading screen, device-status banner and troubleshooting dialog."""
import math
import os
import time

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QGuiApplication, QPainter
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (QDialog, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
                             QVBoxLayout, QWidget)

from . import icons, motion, style, trouble

ASSET_DIR = os.path.join(os.path.dirname(__file__), "assets")
MIN_SHOWN_S = 0.6        # never flash the loading screen for a blink
NONE_GRACE_S = 3.5       # a deck re-enumerating after a restart can take a few seconds to appear
HARD_TIMEOUT_S = 9.0


class LoadingOverlay(QWidget):
    """Covers the window while Deckhand starts and looks for the deck, then fades away."""
    finished = pyqtSignal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._svg = QSvgRenderer(os.path.join(ASSET_DIR, "deckhand.svg"))
        self._text = "Starting Deckhand…"
        self._t0 = time.monotonic()
        self._phase = 0.0
        self._done = False
        self._timer = QTimer(self, interval=16)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._fx = QGraphicsOpacityEffect(self)
        self._fx.setOpacity(1.0)
        self.setGraphicsEffect(self._fx)
        self.raise_()
        self.show()

    def set_text(self, t):
        if t != self._text:
            self._text = t
            self.update()

    @property
    def elapsed(self):
        return time.monotonic() - self._t0

    def _tick(self):
        self._phase = (self._phase + 0.018) % 1.0
        self.update()

    def finish(self):
        """Fade out (after the minimum display time) and remove."""
        if self._done:
            return
        self._done = True
        wait = max(0.0, MIN_SHOWN_S - self.elapsed)
        QTimer.singleShot(int(wait * 1000), self._fade)

    def _fade(self):
        def upd(v):
            self._fx.setOpacity(v)

        def done():
            self._timer.stop()
            self.hide()
            self.finished.emit()
            self.deleteLater()
        motion.value_anim(self, 1.0, 0.0, 260, upd, on_done=done)

    def resizeEvent(self, e):
        super().resizeEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(style.BG))
        cx, cy = self.width() / 2, self.height() / 2 - 24
        pulse = 1.0 + (0.025 * math.sin(self._phase * 2 * math.pi) if motion.enabled() else 0.0)
        s = 88 * pulse
        self._svg.render(p, QRectF(cx - s / 2, cy - s / 2, s, s))
        p.setPen(QColor(style.TEXT))
        f = p.font()
        f.setPixelSize(20)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(0, cy + 58, self.width(), 30), int(Qt.AlignmentFlag.AlignCenter), "Deckhand")
        f.setPixelSize(13)
        f.setBold(False)
        p.setFont(f)
        p.setPen(QColor(style.MUTED))
        p.drawText(QRectF(0, cy + 92, self.width(), 24), int(Qt.AlignmentFlag.AlignCenter), self._text)
        # indeterminate bar: a pill that sweeps across a track
        w, h = 180, 3
        x0, y0 = cx - w / 2, cy + 128
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(style.BORDER))
        p.drawRoundedRect(QRectF(x0, y0, w, h), 1.5, 1.5)
        seg = 56
        t = motion.ease_in_out(self._phase) if motion.enabled() else 0.5
        p.setBrush(QColor(style.ACCENT))
        p.setClipRect(QRectF(x0, y0 - 1, w, h + 2))
        p.drawRoundedRect(QRectF(x0 - seg + (w + seg) * t, y0, seg, h), 1.5, 1.5)


class TroubleDialog(QDialog):
    """Plain steps (and a copyable command) for the current deck problem."""

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        info = engine.conn_info
        g = trouble.guide(info)
        self.setWindowTitle("Stream Deck troubleshooting")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 20)
        lay.setSpacing(12)
        t = QLabel(info.get("title") or "Stream Deck")
        t.setObjectName("h1")
        t.setStyleSheet("font-size:17px;font-weight:700;")
        lay.addWidget(t)
        s = QLabel(g["summary"])
        s.setWordWrap(True)
        s.setObjectName("muted")
        lay.addWidget(s)
        for n, step in enumerate(g["steps"], 1):
            row = QHBoxLayout()
            row.setSpacing(10)
            num = QLabel(str(n))
            num.setFixedSize(22, 22)
            num.setAlignment(Qt.AlignmentFlag.AlignCenter)
            num.setStyleSheet(f"background:{style.CARD};border-radius:11px;color:{style.MUTED};font-weight:700;")
            row.addWidget(num, 0, Qt.AlignmentFlag.AlignTop)
            lab = QLabel(step)
            lab.setWordWrap(True)
            row.addWidget(lab, 1)
            lay.addLayout(row)
        if g["command"]:
            box = QPlainTextEdit(g["command"])
            box.setReadOnly(True)
            box.setStyleSheet("font-family: monospace; font-size: 12px;")
            box.setFixedHeight(84 if len(g["command"]) > 70 else 44)
            lay.addWidget(box)
            cp = QPushButton("Copy command")
            cp.clicked.connect(lambda: (QGuiApplication.clipboard().setText(g["command"]), cp.setText("Copied")))
            lay.addWidget(cp, 0, Qt.AlignmentFlag.AlignLeft)
        row = QHBoxLayout()
        row.addStretch(1)
        retry = QPushButton("Retry now")
        retry.clicked.connect(engine.retry_device)
        done = QPushButton("Close")
        done.setObjectName("primary")
        done.clicked.connect(self.accept)
        row.addWidget(retry)
        row.addWidget(done)
        lay.addLayout(row)


class StatusBanner(QFrame):
    """Shown above the editor whenever the deck is not connected; always says what, why and what to do."""

    def __init__(self, engine, open_help):
        super().__init__()
        self.engine = engine
        self.open_help = open_help
        self.hide()
        h = QHBoxLayout(self)
        h.setContentsMargins(18, 10, 14, 10)
        h.setSpacing(10)
        self.icon = QLabel()
        h.addWidget(self.icon)
        self.text = QLabel()
        self.text.setWordWrap(True)
        h.addWidget(self.text, 1)
        self.close_btn = QPushButton()
        self.close_btn.hide()
        h.addWidget(self.close_btn)
        self.retry = QPushButton("Retry")
        self.retry.clicked.connect(engine.retry_device)
        h.addWidget(self.retry)
        self.how = QPushButton("How to fix")
        self.how.clicked.connect(self.open_help)
        h.addWidget(self.how)

    def update_for(self, info):
        st = info.get("state")
        if st in ("ok", "scanning", None):
            self.hide()
            return
        g = trouble.guide(info)
        col = {"error": style.DANGER, "warn": style.WARN}.get(g["level"], style.MUTED)
        bg = {"error": "#3a1416", "warn": "#3a2d12"}.get(g["level"], style.PANEL2)
        self.setStyleSheet(f"StatusBanner{{background:{bg};}}QLabel{{background:transparent;color:{col};}}")
        self.icon.setPixmap(icons.glyph_pixmap("alert" if g["level"] != "info" else "usb", 18, col))
        self.text.setText(g["summary"])
        culprits = info.get("culprits") or []
        if culprits:
            c = culprits[0]
            self.close_btn.setText(f"Close {c['name']}")
            try:
                self.close_btn.clicked.disconnect()
            except TypeError:
                pass
            self.close_btn.clicked.connect(lambda _=False, pid=c["pid"]: self.engine.close_rival(pid))
            self.close_btn.show()
        else:
            self.close_btn.hide()
        self.how.setVisible(bool(g["steps"]))
        self.show()
