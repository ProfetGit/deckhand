"""Shared motion primitives. Every animation in the app goes through `enabled()` so the
Preferences > Animations switch turns all of it off at once.

Rule of thumb used throughout: motion must explain something (where focus moved, what changed,
which way we navigated, that an action landed). Durations stay under ~250 ms.
"""
import math

from PyQt6.QtCore import QEasingCurve, QObject, QPropertyAnimation, QVariantAnimation
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QWidget

_on = True


def set_enabled(v):
    global _on
    _on = bool(v)


def enabled():
    return _on


def ease_out(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def ease_in_out(t):
    t = max(0.0, min(1.0, t))
    return 3 * t * t - 2 * t * t * t


def ease_out_back(t, s=1.7):
    t = max(0.0, min(1.0, t)) - 1
    return 1 + t * t * ((s + 1) * t + s)


class Tween:
    """A 0..1 value that glides toward a target; rates differ for rising and falling."""

    def __init__(self, value=0.0):
        self.v = value
        self.target = value

    def set(self, target):
        self.target = target
        if not _on:
            self.v = target

    def step(self, dt, rise_s, fall_s):
        if self.v == self.target:
            return False
        rate = dt / (rise_s if self.target > self.v else fall_s)
        self.v = min(self.target, self.v + rate) if self.target > self.v else max(self.target, self.v - rate)
        return self.v != self.target

    @property
    def eased(self):
        return ease_out(self.v)


def fade_in(widget: QWidget, ms=150):
    """Fade a freshly built panel in. The effect is removed afterwards so text stays crisp."""
    if not _on or widget is None:
        return
    fx = QGraphicsOpacityEffect(widget)
    fx.setOpacity(0.0)
    widget.setGraphicsEffect(fx)
    anim = QPropertyAnimation(fx, b"opacity", widget)
    anim.setDuration(ms)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def done():
        try:
            widget.setGraphicsEffect(None)
        except RuntimeError:
            pass
    anim.finished.connect(done)
    anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)


def stop(anim):
    """Stop an animation handle that Qt may already have deleted (DeleteWhenStopped)."""
    if anim is None:
        return
    try:
        anim.stop()
    except RuntimeError:
        pass


def value_anim(parent: QObject, start, end, ms, on_value, easing=QEasingCurve.Type.OutCubic, on_done=None):
    """Run a one-shot QVariantAnimation, or jump straight to the end when animations are off."""
    if not _on:
        on_value(end)
        if on_done:
            on_done()
        return None
    a = QVariantAnimation(parent)
    a.setStartValue(start)
    a.setEndValue(end)
    a.setDuration(ms)
    a.setEasingCurve(easing)
    a.valueChanged.connect(on_value)
    if on_done:
        a.finished.connect(on_done)
    a.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)
    return a
