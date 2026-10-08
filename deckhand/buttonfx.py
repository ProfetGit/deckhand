"""App-wide button polish: every push/tool button gets a pointer cursor, a smooth hover glow and a press dip.

One event filter handles all buttons, so new buttons get it automatically and keep their own styling:
the glow is a click-through overlay, not a colour change, so it works on primary, danger, flat and
round buttons alike. Everything goes through motion.value_anim, so the Animations preference applies.
"""
from PyQt6.QtCore import QEvent, QEasingCurve, QObject, QRectF, Qt, QVariantAnimation
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QAbstractButton, QComboBox, QPushButton, QToolButton, QWidget

from . import motion

HOVER_ALPHA = 0.11      # white overlay at full hover
PRESS_ALPHA = 0.16      # dark overlay while pressed
RADIUS = 7


class _Glow(QWidget):
    def __init__(self, button):
        super().__init__(button)
        self.setObjectName("hoverGlow")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.hover, self.press = 0.0, 0.0
        self._anim = {}
        self.setGeometry(button.rect())

    def radius(self):
        r = self.parentWidget().property("glowRadius")
        return float(r) if r is not None else min(RADIUS, self.height() / 2)

    def go(self, which, target, ms):
        a = self._anim.get(which)
        motion.stop(a)

        def upd(v):
            setattr(self, which, float(v))
            self.update()
        self._anim[which] = motion.value_anim(self, getattr(self, which), target, ms, upd, QEasingCurve.Type.OutCubic)

    def paintEvent(self, _):
        if self.hover <= 0.001 and self.press <= 0.001:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self.hover > 0.001:
            p.setBrush(QColor(255, 255, 255, int(255 * HOVER_ALPHA * self.hover)))
            p.drawRoundedRect(r, self.radius(), self.radius())
        if self.press > 0.001:
            p.setBrush(QColor(0, 0, 0, int(255 * PRESS_ALPHA * self.press)))
            p.drawRoundedRect(r, self.radius(), self.radius())


def _is_button(o):
    return isinstance(o, (QPushButton, QToolButton)) and not o.objectName() == "hoverGlow"


class ButtonFx(QObject):
    WATCH = {QEvent.Type.Show, QEvent.Type.Enter, QEvent.Type.Leave, QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease,
             QEvent.Type.Resize, QEvent.Type.EnabledChange, QEvent.Type.Hide}

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t not in self.WATCH:
            return False
        if isinstance(obj, QComboBox):
            if t == QEvent.Type.Show:
                obj.setCursor(Qt.CursorShape.PointingHandCursor)
            return False
        if not _is_button(obj):
            return False
        glow = obj.findChild(_Glow, "hoverGlow")
        if t == QEvent.Type.Show:
            if glow is None:
                glow = _Glow(obj)
            glow.setGeometry(obj.rect())
            glow.raise_()
            glow.show()
            obj.setCursor(Qt.CursorShape.PointingHandCursor if obj.isEnabled() else Qt.CursorShape.ArrowCursor)
            return False
        if glow is None:
            return False
        if t == QEvent.Type.Resize:
            glow.setGeometry(obj.rect())
        elif t == QEvent.Type.EnabledChange:
            obj.setCursor(Qt.CursorShape.PointingHandCursor if obj.isEnabled() else Qt.CursorShape.ArrowCursor)
            if not obj.isEnabled():
                glow.go("hover", 0.0, 80)
                glow.go("press", 0.0, 80)
        elif obj.isEnabled():
            if t == QEvent.Type.Enter:
                glow.raise_()
                glow.go("hover", 1.0, 130)
            elif t == QEvent.Type.Leave:
                glow.go("hover", 0.0, 180)
                glow.go("press", 0.0, 120)
            elif t == QEvent.Type.MouseButtonPress:
                glow.go("press", 1.0, 60)
            elif t == QEvent.Type.MouseButtonRelease:
                glow.go("press", 0.0, 140)
        elif t == QEvent.Type.Hide:
            glow.hover = glow.press = 0.0
        return False


_fx = None


def install(app):
    """Install the filter once for the whole application."""
    global _fx
    if _fx is None:
        _fx = ButtonFx(app)
        app.installEventFilter(_fx)
    return _fx
