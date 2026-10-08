"""The mouse wheel only ever scrolls the page: it never changes a number box, dropdown or slider under the pointer.

One app-wide event filter. A wheel turn over such a control is turned into a scroll of the nearest scroll area
(or dropped when there is none), so sliding the pointer across the inspector can't silently edit settings.
"""
from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtWidgets import QAbstractScrollArea, QAbstractSlider, QAbstractSpinBox, QApplication, QComboBox

_guard = None
GUARDED = (QAbstractSpinBox, QComboBox, QAbstractSlider)


def scroll_parent(w):
    p = w.parentWidget()
    while p is not None and not isinstance(p, QAbstractScrollArea):
        p = p.parentWidget()
    return p


class WheelGuard(QObject):
    def eventFilter(self, obj, ev):
        if ev.type() != QEvent.Type.Wheel or not isinstance(obj, GUARDED):
            return False
        area = scroll_parent(obj)
        if area is not None:
            bar = area.verticalScrollBar()
            dy = ev.angleDelta().y()
            if bar is not None and dy:
                bar.setValue(bar.value() - round(dy / 120 * bar.singleStep() * 3))
        ev.accept()
        return True


def install(app):
    global _guard
    if _guard is None:
        _guard = WheelGuard(app)
        app.installEventFilter(_guard)
        app.aboutToQuit.connect(uninstall)
    return _guard


def uninstall():
    global _guard
    if _guard is not None:
        QApplication.instance().removeEventFilter(_guard)
        _guard = None
