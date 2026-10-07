"""Custom widgets: toggle switch, segmented control, color swatch, hotkey recorder, deck canvas, toast."""
import json
import math
import os
import time

from PyQt6.QtCore import QEasingCurve, QEvent, QMimeData, QPoint, QPointF, QPropertyAnimation, QRectF, QSize, Qt, QTimer, pyqtProperty, pyqtSignal
from PyQt6.QtGui import QColor, QDrag, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import (QAbstractButton, QApplication, QButtonGroup, QColorDialog, QGraphicsOpacityEffect, QHBoxLayout,
                             QLabel, QPushButton, QSizePolicy, QToolButton, QWidget)

from . import actions, icons, keymap, model, motion, style

MIME_ACTION = "application/x-deckhand-action"
MIME_KEY = "application/x-deckhand-key"
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg")


class ElidedLabel(QLabel):
    """Single-line label that shortens itself with an ellipsis instead of widening the layout."""

    def __init__(self, text=""):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setText(text)

    def setText(self, text):
        self._full = text
        self.setToolTip(text)
        super().setText("")
        self.update()

    def minimumSizeHint(self):
        return QSize(0, super().minimumSizeHint().height() or 18)

    def sizeHint(self):
        return QSize(self.fontMetrics().horizontalAdvance(self._full), self.fontMetrics().height() + 2)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setPen(self.palette().color(self.foregroundRole()))
        txt = self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideRight, self.width())
        p.drawText(self.rect(), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), txt)


def fit_combo(c):
    """Never let a long item text widen the layout (and force sideways scrolling)."""
    c.setSizeAdjustPolicy(c.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    c.setMinimumContentsLength(10)
    c.setSizePolicy(QSizePolicy.Policy.Ignored if False else QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return c


def icon_btn(glyph, tip="", size=18, color="#c9c9d2", flat=True):
    b = QToolButton()
    b.setIcon(icons.glyph_icon(glyph, size, color))
    b.setIconSize(QSize(size, size))
    b.setToolTip(tip)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setAutoRaise(True)
    return b


class Switch(QAbstractButton):
    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setFixedSize(38, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pos = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"pos_", self, duration=120)
        self.toggled.connect(self._animate)

    def _animate(self, on):
        self._anim.stop()
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def get_pos(self):
        return self._pos

    def set_pos(self, v):
        self._pos = v
        self.update()

    pos_ = pyqtProperty(float, get_pos, set_pos)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            p.setOpacity(0.35)
        off, on = QColor("#45454e"), QColor(style.ACCENT)
        t = self._pos
        c = QColor(int(off.red() + (on.red() - off.red()) * t), int(off.green() + (on.green() - off.green()) * t),
                   int(off.blue() + (on.blue() - off.blue()) * t))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.drawRoundedRect(self.rect(), 11, 11)
        p.setBrush(QColor("white"))
        p.drawEllipse(QPointF(11 + 16 * t, 11), 8, 8)


class Segmented(QWidget):
    """Pill-style choice control; the highlight glides to the chosen option."""
    changed = pyqtSignal(str)

    def __init__(self, items, parent=None):
        """items: [(value, label_or_glyph, tooltip, is_glyph)]"""
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons = {}
        self._ind = QRectF()
        self._anim = None
        for value, label, tip, is_glyph in items:
            b = QPushButton()
            b.setCheckable(True)
            b.setToolTip(tip)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            if is_glyph:
                b.setIcon(icons.glyph_icon(label, 16, "#d0d0d8"))
                b.setIconSize(QSize(16, 16))
            else:
                b.setText(label)
            b.setStyleSheet("QPushButton{background:transparent;border:none;padding:4px 10px;border-radius:6px;color:%s;}"
                            "QPushButton:hover{color:%s;}QPushButton:checked{color:white;}" % (style.MUTED, style.TEXT))
            self.group.addButton(b)
            self.buttons[value] = b
            lay.addWidget(b)
            b.clicked.connect(lambda _=False, v=value: self._clicked(v))

    def _target(self):
        for b in self.buttons.values():
            if b.isChecked():
                return QRectF(b.geometry())
        return QRectF()

    def _clicked(self, v):
        self._glide()
        self.changed.emit(v)

    def _glide(self):
        end = self._target()
        motion.stop(self._anim)
        if self._ind.isNull() or not self.isVisible():
            self._ind = end
            self.update()
            return

        def upd(r):
            self._ind = r
            self.update()
        self._anim = motion.value_anim(self, self._ind, end, 170, upd)

    def set_value(self, v):
        b = self.buttons.get(v)
        if b:
            b.setChecked(True)
            self._ind = self._target()
            self.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._ind = self._target()

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, self._snap)

    def _snap(self):
        try:
            self._ind = self._target()
            self.update()
        except RuntimeError:
            pass

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(style.BORDER), 1))
        p.setBrush(QColor(style.BG))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        if not self._ind.isNull():
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(style.ACCENT) if self.isEnabled() else QColor("#45454e"))
            p.drawRoundedRect(self._ind, 6, 6)


class ColorButton(QPushButton):
    changed = pyqtSignal(str)

    def __init__(self, color="#ffffff", tip="", parent=None, compact=False):
        super().__init__(parent)
        self._c = color
        self._compact = compact
        self.setFixedSize(30, 22) if compact else self.setFixedSize(34, 30)
        self.setToolTip(tip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(self._pick)

    def set_color(self, c):
        self._c = c
        self.update()

    def color(self):
        return self._c

    def _pick(self):
        from .colorpicker import ColorPopup
        pop = ColorPopup(self._c, self.window())
        pop.changed.connect(self._emit_str)
        pop.popup_below(self)
        self._pop = pop

    def _emit_str(self, c):
        self._c = c
        self.update()
        self.changed.emit(c)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if self._compact:
            p.setPen(QPen(QColor("#55ffffff"), 1))
            p.setBrush(QColor(self._c))
            p.drawRoundedRect(r, 5, 5)
            return
        p.setPen(QPen(QColor(style.BORDER), 1))
        p.setBrush(QColor(style.BG))
        p.drawRoundedRect(r, 7, 7)
        p.setPen(QPen(QColor("#00000066"), 1))
        p.setBrush(QColor(self._c))
        p.drawRoundedRect(r.adjusted(5, 5, -5, -5), 4, 4)


class HotkeyEdit(QWidget):
    changed = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hk = {"mods": [], "code": 0, "label": ""}
        self._capturing = False
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.mod_btns = {}
        for m in keymap.MOD_ORDER:
            b = QPushButton(keymap.MOD_LABEL[m])
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(f"QPushButton{{padding:6px 9px;}}QPushButton:checked{{background:{style.ACCENT};border-color:{style.ACCENT};color:white;}}")
            b.clicked.connect(self._mods_clicked)
            self.mod_btns[m] = b
            lay.addWidget(b)
        self.key_btn = QPushButton()
        self.key_btn.setMinimumWidth(80)
        self.key_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.key_btn.clicked.connect(self._start)
        lay.addWidget(self.key_btn, 1)
        self.set_value({})

    def set_value(self, hk):
        self._hk = {"mods": list(hk.get("mods", [])), "code": hk.get("code", 0), "label": hk.get("label", "")}
        for m, b in self.mod_btns.items():
            b.setChecked(m in self._hk["mods"])
        self._paint_key()

    def _paint_key(self):
        if self._capturing:
            self.key_btn.setText("Press a key…")
            self.key_btn.setStyleSheet(f"QPushButton{{border-color:{style.ACCENT};color:{style.ACCENT};}}")
        else:
            lab = self._hk["label"] or keymap.LABELS.get(self._hk["code"], "")
            self.key_btn.setText(lab or "Click to record")
            self.key_btn.setStyleSheet("" if lab else f"QPushButton{{color:{style.MUTED};}}")

    def _mods_clicked(self):
        self._hk["mods"] = [m for m in keymap.MOD_ORDER if self.mod_btns[m].isChecked()]
        self.changed.emit(dict(self._hk))

    def _start(self):
        self._capturing = True
        self._paint_key()
        self.grabKeyboard()

    def _stop(self):
        self._capturing = False
        self.releaseKeyboard()
        self._paint_key()

    def focusOutEvent(self, e):
        if self._capturing:
            self._stop()
        super().focusOutEvent(e)

    def event(self, e):
        if self._capturing and e.type() == QEvent.Type.KeyPress:
            self._key(e)
            return True
        if self._capturing and e.type() == QEvent.Type.ShortcutOverride:
            e.accept()
            return True
        return super().event(e)

    def _key(self, e):
        k = e.key()
        if k in (Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta, Qt.Key.Key_AltGr):
            return
        mods = e.modifiers()
        if k == Qt.Key.Key_Escape and not (mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier)):
            self._stop()
            return
        code = e.nativeScanCode() - 8
        if code < 1 or code > 255:
            code = keymap.CODES_BY_LABEL.get(e.text().upper() or "", 0)
        if not code:
            return
        ms = set(self._hk["mods"])
        for flag, name in ((Qt.KeyboardModifier.ControlModifier, "ctrl"), (Qt.KeyboardModifier.ShiftModifier, "shift"),
                           (Qt.KeyboardModifier.AltModifier, "alt"), (Qt.KeyboardModifier.MetaModifier, "meta")):
            if mods & flag:
                ms.add(name)
        self._hk = {"mods": [m for m in keymap.MOD_ORDER if m in ms], "code": code, "label": keymap.LABELS.get(code, "")}
        for m, b in self.mod_btns.items():
            b.setChecked(m in ms)
        self._stop()
        self.changed.emit(dict(self._hk))


class Toast(QLabel):
    def __init__(self, parent):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hide()
        self._fx = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._fx)
        self._anim = QPropertyAnimation(self._fx, b"opacity", self, duration=220)
        self._timer = QTimer(self, singleShot=True)
        self._timer.timeout.connect(self._fade)
        self._anim.finished.connect(lambda: self.hide() if self._fx.opacity() < 0.05 else None)

    def show_message(self, text, kind="info", ms=3200):
        col = {"error": style.DANGER, "ok": style.OK, "warn": style.WARN}.get(kind, style.ACCENT)
        self.setStyleSheet(f"background:{style.CARD};color:{style.TEXT};border:1px solid {col};border-radius:9px;padding:9px 16px;")
        self.setText(text)
        self.adjustSize()
        p = self.parentWidget()
        end = QPoint((p.width() - self.width()) // 2, p.height() - self.height() - 46)
        motion.value_anim(self, end + QPoint(0, 12), end, 200, self.move)
        self.move(end + QPoint(0, 12) if motion.enabled() else end)
        self.show()
        self.raise_()
        self._anim.stop()
        self._anim.setEndValue(1.0)
        self._anim.setStartValue(self._fx.opacity())
        self._anim.start()
        self._timer.start(ms)

    def _fade(self):
        self._anim.stop()
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.start()


class StatusDot(QWidget):
    """Connection dot: colour glides between states and a ripple confirms a new connection."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(18, 18)
        self._c = QColor(style.MUTED)
        self._ping = 0.0
        self._anim = None

    def set_color(self, c, ping=False):
        new = QColor(c)
        old = QColor(self._c)

        def upd(col):
            self._c = col
            self.update()
        motion.stop(self._anim)
        self._anim = motion.value_anim(self, old, new, 260, upd)
        if ping:
            motion.value_anim(self, 0.0, 1.0, 750, self._set_ping, QEasingCurve.Type.OutQuad)

    def _set_ping(self, v):
        self._ping = v
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        ctr = QPointF(self.width() / 2, self.height() / 2)
        if 0 < self._ping < 1:
            ring = QColor(self._c)
            ring.setAlphaF(0.55 * (1 - self._ping))
            p.setPen(QPen(ring, 1.6))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(ctr, 4.5 + 4.5 * self._ping, 4.5 + 4.5 * self._ping)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._c)
        p.drawEllipse(ctr, 4.5, 4.5)


class DeckView(QWidget):
    selected = pyqtSignal(int)
    contextRequested = pyqtSignal(int, QPoint)
    dropAction = pyqtSignal(int, str)
    dropKey = pyqtSignal(int, int, bool)
    dropFile = pyqtSignal(int, str)
    activated = pyqtSignal(int)      # double-click / Enter on a key

    PAD, GAP = 26, 14

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.sel = -1
        self.hover = -1
        self.drop_idx = -1
        self.pressed = set()
        self._cache = {}
        self._drag_start = None
        self._drag_idx = -1
        # motion state
        self._hover_tw, self._press_tw = {}, {}
        self._flash, self._fade, self._pop = {}, {}, {}
        self._invite = motion.Tween(0.0)
        self._nav = None
        self._ring_tw = {}
        self._expect = set()
        self._sigs, self._loc_sig = {}, None
        self._last = time.monotonic()
        self._timer = QTimer(self, interval=16)
        self._timer.timeout.connect(self._frame)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(440, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        engine.key_state.connect(self._phys)
        engine.wall_frame.connect(self._wall_frame)
        engine.hold_fired.connect(self._hold_pulse)
        self._loc_sig = self._loc_signature()
        self._sigs = {i: self._sig(i) for i in range(engine.n_keys)}

    # ---- motion driver -------------------------------------------------------------------
    def _kick(self):
        if not self._timer.isActive():
            self._last = time.monotonic()
            self._timer.start()

    def _tw(self, table, idx):
        tw = table.get(idx)
        if tw is None:
            tw = table[idx] = motion.Tween(0.0)
        return tw

    def _frame(self):
        now = time.monotonic()
        dt = min(0.05, now - self._last)
        self._last = now
        active = False
        for tw in self._hover_tw.values():
            active |= tw.step(dt, 0.12, 0.2)
        for tw in self._press_tw.values():
            active |= tw.step(dt, 0.06, 0.16)
        active |= self._invite.step(dt, 0.15, 0.2)
        for table, rate in ((self._flash, 0.75),):
            for i in list(table):
                table[i] -= dt / rate
                if table[i] <= 0:
                    del table[i]
            active |= bool(table)
        for i in list(self._fade):
            self._fade[i][1] -= dt / 0.17
            if self._fade[i][1] <= 0:
                del self._fade[i]
        active |= bool(self._fade)
        for i in list(self._pop):
            self._pop[i] += dt / 0.26
            if self._pop[i] >= 1:
                del self._pop[i]
        active |= bool(self._pop)
        if self._nav:
            self._nav["t"] += dt / 0.2
            if self._nav["t"] >= 1:
                self._nav = None
            active |= bool(self._nav)
        for i, tw in list(self._ring_tw.items()):
            tw.set(1.0 if i == self.sel else 0.0)
            active |= tw.step(dt, 0.12, 0.1)
            if tw.v == 0.0 and i != self.sel:
                del self._ring_tw[i]
        self.update()
        if not active:
            self._timer.stop()

    def _hold_pulse(self, idx):
        """The key was held long enough: a small pop confirms the hold action fired."""
        if motion.enabled():
            self._pop[idx] = 0.0
            self._flash[idx] = 0.6
            self._kick()

    def _wall_frame(self):
        e = self.engine
        for i in range(e.n_keys):
            if e.key_uses_wallpaper(i):
                self._cache = {k: v for k, v in self._cache.items() if k[0] != i}
        self.update()

    def _phys(self, idx, down):
        (self.pressed.add if down else self.pressed.discard)(idx)
        self._tw(self._press_tw, idx).set(1.0 if down else 0.0)
        self._kick()
        self.update()

    # ---- change detection -----------------------------------------------------------------
    def _loc_signature(self):
        e = self.engine
        return (e.profile["id"], e.loc["page"], tuple(e.loc["folders"]))

    def _sig(self, i):
        e = self.engine
        return json.dumps(e.get_key(i), sort_keys=True) + str(e.look_state(i))

    def _old_face(self, i, ks):
        return self._cache.get((i, int(ks * self.devicePixelRatioF())))

    def refresh(self, idx=None):
        e = self.engine
        ks, _ = self._metrics()
        if idx is not None:
            old = self._old_face(idx, ks)
            self._cache = {k: v for k, v in self._cache.items() if k[0] != idx}
            k = e.get_key(idx)
            a = k.get("action") if k else None
            dyn = bool(a and actions.ACTIONS.get(a["type"], {}).get("dynamic"))
            if old is not None and not dyn and motion.enabled():
                self._fade[idx] = [old, 1.0]
                self._kick()
            self.update()
            return
        old = {i: self._old_face(i, ks) for i in range(e.n_keys)}
        self._cache.clear()
        loc = self._loc_signature()
        new_sigs = {i: self._sig(i) for i in range(e.n_keys)}
        if motion.enabled() and self._loc_sig is not None:
            if loc != self._loc_sig:
                prev = self._loc_sig
                if loc[0] != prev[0]:
                    kind, d = "fade", 0
                elif len(loc[2]) > len(prev[2]):
                    kind, d = "open", 1
                elif len(loc[2]) < len(prev[2]):
                    kind, d = "back", -1
                else:
                    kind, d = "slide", (1 if loc[1] > prev[1] else -1)
                self._nav = {"kind": kind, "dir": d, "t": 0.0}
                self._flash.clear()
                self._fade.clear()
            else:
                quiet = getattr(e, "quiet_flash", False)
                for i, sg in new_sigs.items():
                    if self._sigs.get(i) != sg:
                        if i in self._expect:
                            self._pop[i] = 0.0
                        elif not quiet:
                            self._flash[i] = 1.0
                        if not quiet and old.get(i) is not None:
                            self._fade[i] = [old[i], 1.0]
            self._kick()
        self._expect.clear()
        self._sigs, self._loc_sig = new_sigs, loc
        self.update()

    def set_selected(self, idx):
        self.sel = idx
        self._sync_ring()
        self._kick()
        self.update()

    # ---- geometry ----------------------------------------------------------------------
    def _metrics(self):
        e = self.engine
        w, h = self.width(), self.height()
        ks = min((w - 2 * self.PAD - 40 - (e.cols - 1) * self.GAP) / e.cols, (h - 2 * self.PAD - 20 - (e.rows - 1) * self.GAP) / e.rows, 110)
        ks = max(40, ks)
        bw = e.cols * ks + (e.cols - 1) * self.GAP + 2 * self.PAD
        bh = e.rows * ks + (e.rows - 1) * self.GAP + 2 * self.PAD
        return ks, QRectF((w - bw) / 2, (h - bh) / 2, bw, bh)

    def key_rect(self, idx):
        ks, body = self._metrics()
        c, r = idx % self.engine.cols, idx // self.engine.cols
        return QRectF(body.x() + self.PAD + c * (ks + self.GAP), body.y() + self.PAD + r * (ks + self.GAP), ks, ks)

    def key_at(self, pos):
        for i in range(self.engine.n_keys):
            if self.key_rect(i).adjusted(-self.GAP / 2, -self.GAP / 2, self.GAP / 2, self.GAP / 2).contains(QPointF(pos)):
                return i
        return -1

    def _sync_ring(self):
        """The selection ring fades out on the old key and fades in on the new one (it never travels)."""
        if self.sel >= 0 and self.sel not in self._ring_tw:
            self._ring_tw[self.sel] = motion.Tween(0.0)
        for i, tw in self._ring_tw.items():
            tw.set(1.0 if i == self.sel else 0.0)
        self._kick()

    def _ring_target(self):
        if self.sel < 0 or self.sel >= self.engine.n_keys:
            return None
        return self.key_rect(self.sel).adjusted(-5, -5, 5, 5)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)

    def _face(self, idx, ks):
        dpr = self.devicePixelRatioF()
        key = (idx, int(ks * dpr))
        px = self._cache.get(key)
        if px is None:
            img = self.engine.render(idx, int(ks * dpr))
            px = QPixmap.fromImage(img)
            px.setDevicePixelRatio(dpr)
            self._cache[key] = px
        return px

    # ---- paint ----------------------------------------------------------------------------
    def paintEvent(self, _):
        e = self.engine
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        ks, body = self._metrics()
        g = QLinearGradient(body.topLeft(), body.bottomLeft())
        g.setColorAt(0, QColor("#2b2b30"))
        g.setColorAt(1, QColor("#1a1a1d"))
        p.setPen(QPen(QColor("#3a3a41"), 1))
        p.setBrush(g)
        p.drawRoundedRect(body, 24, 24)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 60))
        p.drawRoundedRect(body.adjusted(0, body.height() - 3, 0, 6), 3, 3)

        # navigation transition applies to the whole key group
        p.save()
        base_op = 1.0
        if self._nav:
            t = motion.ease_out(self._nav["t"])
            base_op = t
            c = body.center()
            kind = self._nav["kind"]
            if kind in ("open", "back"):
                sc = (0.9 + 0.1 * t) if kind == "open" else (1.08 - 0.08 * t)
                p.translate(c)
                p.scale(sc, sc)
                p.translate(-c)
            elif kind == "slide":
                p.translate(self._nav["dir"] * 30 * (1 - t), 0)
        rad = ks * 0.13
        inv = self._invite.eased
        for i in range(e.n_keys):
            r = self.key_rect(i)
            k = e.get_key(i)
            empty = model.key_is_empty(k)
            hov = self._hover_tw[i].eased if i in self._hover_tw else 0.0
            prs = self._press_tw[i].eased if i in self._press_tw else 0.0
            sc = 1.0 - 0.07 * prs
            if i in self._pop:
                sc *= 0.88 + 0.12 * motion.ease_out_back(self._pop[i])
            p.save()
            if sc != 1.0:
                p.translate(r.center())
                p.scale(sc, sc)
                p.translate(-r.center())
            path = QPainterPath()
            path.addRoundedRect(r, rad, rad)
            p.setOpacity(base_op)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#08080a"))
            p.drawRoundedRect(r.adjusted(-1.5, -1.5, 1.5, 1.5), rad + 1, rad + 1)
            p.save()
            p.setClipPath(path)
            face = self._face(i, ks)
            if i in self._fade:
                old, fv = self._fade[i]
                p.drawPixmap(r.topLeft(), old)
                p.setOpacity(base_op * (1 - motion.ease_out(fv)))
                p.drawPixmap(r.topLeft(), face)
                p.setOpacity(base_op)
            else:
                p.drawPixmap(r.topLeft(), face)
            if prs:
                p.fillRect(r, QColor(255, 255, 255, int(70 * prs)))
            if hov and not empty:
                p.fillRect(r, QColor(255, 255, 255, int(18 * hov)))
            if self.drop_idx == i:
                p.fillRect(r, QColor(61, 139, 253, 95))
            fl = self._flash.get(i, 0.0)
            if fl:
                f = motion.ease_out(fl)
                p.fillRect(r, QColor(61, 139, 253, int(80 * f)))
            p.restore()
            if empty and not e.is_locked(i):
                mix = max(hov, 1.0 if self.drop_idx == i else 0.0, 0.55 * inv)
                col = QColor(60, 60, 68)
                acc = QColor(style.ACCENT)
                col = QColor(int(col.red() + (acc.red() - col.red()) * mix), int(col.green() + (acc.green() - col.green()) * mix),
                             int(col.blue() + (acc.blue() - col.blue()) * mix))
                p.setPen(QPen(col, 1.4, Qt.PenStyle.DashLine))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(r.adjusted(5, 5, -5, -5), rad * 0.7, rad * 0.7)
                if hov:
                    p.setOpacity(base_op * hov)
                    icons.paint_glyph(p, "plus", QRectF(r.center().x() - 9, r.center().y() - 9, 18, 18), style.ACCENT, 2.2)
                    p.setOpacity(base_op)
            if fl:
                ring = QColor(61, 139, 253, int(230 * motion.ease_out(fl)))
                p.setPen(QPen(ring, 2.2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                grow = 3 + 5 * (1 - motion.ease_out(fl))
                p.drawRoundedRect(r.adjusted(-grow, -grow, grow, grow), rad + grow, rad + grow)
            if hov and i != self.sel:
                p.setPen(QPen(QColor(255, 255, 255, int(50 * hov)), 1.5))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(r.adjusted(-4, -4, 4, 4), rad + 3, rad + 3)
            p.restore()

        # selection ring: fades per key
        p.setBrush(Qt.BrushStyle.NoBrush)
        for i, tw in self._ring_tw.items():
            if i >= e.n_keys:
                continue
            p.setOpacity(base_op * (tw.v if motion.enabled() else 1.0))
            p.setPen(QPen(QColor(style.ACCENT), 2.6))
            p.drawRoundedRect(self.key_rect(i).adjusted(-5, -5, 5, 5), rad + 4, rad + 4)
        p.restore()

    # ---- interaction --------------------------------------------------------------------------
    def mousePressEvent(self, ev):
        self.setFocus()
        i = self.key_at(ev.position().toPoint())
        if ev.button() == Qt.MouseButton.LeftButton:
            self._drag_start = ev.position().toPoint()
            self._drag_idx = i
            if i >= 0:
                self.sel = i
                self._sync_ring()
                self.selected.emit(i)
                self.update()
        elif ev.button() == Qt.MouseButton.RightButton and i >= 0:
            self.sel = i
            self._sync_ring()
            self.selected.emit(i)
            self.update()
            self.contextRequested.emit(i, ev.globalPosition().toPoint())

    def _set_hover(self, h):
        if h == self.hover:
            return
        if self.hover >= 0:
            self._tw(self._hover_tw, self.hover).set(0.0)
        if h >= 0:
            self._tw(self._hover_tw, h).set(1.0)
        self.hover = h
        k = self.engine.get_key(h) if h >= 0 else None
        a = k.get("action") if k else None
        self.setToolTip(f"{actions.ACTIONS[a['type']]['name']}\n{actions.describe(a)}" if a and a["type"] in actions.ACTIONS else "")
        self._kick()
        self.update()

    def mouseMoveEvent(self, ev):
        pos = ev.position().toPoint()
        h = self.key_at(pos)
        self._set_hover(h)
        self.setCursor(Qt.CursorShape.PointingHandCursor if h >= 0 else Qt.CursorShape.ArrowCursor)
        if (ev.buttons() & Qt.MouseButton.LeftButton) and self._drag_start is not None and self._drag_idx >= 0:
            if (pos - self._drag_start).manhattanLength() > 8:
                k = self.engine.get_key(self._drag_idx)
                if not model.key_is_empty(k) and not self.engine.is_locked(self._drag_idx):
                    self._start_drag(self._drag_idx)
                self._drag_start = None

    def _start_drag(self, idx):
        d = QDrag(self)
        m = QMimeData()
        e = self.engine
        m.setData(MIME_KEY, json.dumps({"idx": idx, "page": e.loc["page"], "folders": list(e.loc["folders"]), "profile": e.profile["id"]}).encode())
        d.setMimeData(m)
        px = QPixmap.fromImage(self.engine.render(idx, 72 * 2))
        px.setDevicePixelRatio(2)
        d.setPixmap(px)
        d.setHotSpot(QPoint(36, 36))
        self._invite.set(1.0)
        self._kick()
        d.exec(Qt.DropAction.MoveAction | Qt.DropAction.CopyAction, Qt.DropAction.MoveAction)
        self.drop_idx = -1
        self._invite.set(0.0)
        self._kick()
        self.update()

    def mouseDoubleClickEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            i = self.key_at(ev.position().toPoint())
            self._drag_start = None
            if i >= 0:
                self.activated.emit(i)

    def mouseReleaseEvent(self, ev):
        self._drag_start = None

    def leaveEvent(self, _):
        self._set_hover(-1)

    def keyPressEvent(self, ev):
        e = self.engine
        k = ev.key()
        if self.sel < 0:
            self.sel = 0
        d = {Qt.Key.Key_Left: -1, Qt.Key.Key_Right: 1, Qt.Key.Key_Up: -e.cols, Qt.Key.Key_Down: e.cols}.get(k)
        if d is not None:
            n = self.sel + d
            if 0 <= n < e.n_keys and not (d in (-1, 1) and n // e.cols != self.sel // e.cols):
                self.sel = n
                self._sync_ring()
                self.selected.emit(n)
                self.update()
            return
        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.sel >= 0:
            self.activated.emit(self.sel)
            return
        super().keyPressEvent(ev)

    # ---- drag & drop ----------------------------------------------------------------------------
    def _accepts(self, m):
        return m.hasFormat(MIME_ACTION) or m.hasFormat(MIME_KEY) or any(
            u.isLocalFile() and u.toLocalFile().lower().endswith(IMAGE_EXT) for u in m.urls())

    def dragEnterEvent(self, ev):
        if self._accepts(ev.mimeData()):
            ev.acceptProposedAction()
            self._invite.set(1.0)
            self._kick()

    def dragMoveEvent(self, ev):
        i = self.key_at(ev.position().toPoint())
        if i >= 0 and self.engine.is_locked(i):
            i = -1
        if i != self.drop_idx:
            self.drop_idx = i
            self.update()
        if i >= 0:
            ev.acceptProposedAction()
        else:
            ev.ignore()

    def dragLeaveEvent(self, _):
        self.drop_idx = -1
        self._invite.set(0.0)
        self._kick()
        self.update()

    def dropEvent(self, ev):
        i = self.key_at(ev.position().toPoint())
        self.drop_idx = -1
        self._invite.set(0.0)
        self._kick()
        self.update()
        m = ev.mimeData()
        if i < 0 or self.engine.is_locked(i):
            return
        ev.acceptProposedAction()
        self._expect = {i}
        if m.hasFormat(MIME_ACTION):
            self.dropAction.emit(i, bytes(m.data(MIME_ACTION)).decode())
        elif m.hasFormat(MIME_KEY):
            raw = bytes(m.data(MIME_KEY)).decode()
            try:
                info = json.loads(raw) if not raw.isdigit() else {"idx": int(raw)}
                src = int(info["idx"])
            except (ValueError, KeyError, TypeError):
                return
            copy_it = bool(ev.modifiers() & Qt.KeyboardModifier.ControlModifier) or ev.proposedAction() == Qt.DropAction.CopyAction
            e = self.engine
            same = ("page" not in info) or (info.get("profile") == e.profile["id"] and info["page"] == e.loc["page"]
                                            and list(info.get("folders", [])) == list(e.loc["folders"]))
            self._expect = {i} if copy_it or not same else {i, src}
            if same:
                self.dropKey.emit(src, i, copy_it)
            elif info.get("profile") == e.profile["id"]:
                e.move_key_from({"page": info["page"], "folders": info.get("folders", [])}, src, i, copy_it)
        else:
            for u in m.urls():
                if u.isLocalFile() and u.toLocalFile().lower().endswith(IMAGE_EXT):
                    self.dropFile.emit(i, u.toLocalFile())
                    break
        self._expect = set()
