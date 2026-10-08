"""Auto-built settings forms for actions (shared by the inspector and the multi-action step editor)."""
import copy
import os

from PyQt6.QtCore import QPoint, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (QComboBox, QCompleter, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox, QPlainTextEdit,
                             QLayout, QPushButton, QSizePolicy, QSpinBox, QVBoxLayout, QWidget)

from . import actions, errors, icons, keymap, sounds, style, sysinfo
from .widgets import ColorButton, HotkeyEdit, Switch, compact_combo, fit_combo, icon_btn


def muted(text):
    l = QLabel(text)
    l.setStyleSheet(f"color:{style.MUTED};font-size:11px;font-weight:600;")
    return l


class AppCombo(QComboBox):
    appChosen = pyqtSignal(str)

    def __init__(self, current):
        super().__init__()
        fit_combo(self)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.setIconSize(QSize(20, 20))
        self.setMaxVisibleItems(14)
        apps = icons.installed_apps()
        self.addItem("")
        for a in apps:
            self.addItem(icons.app_icon(a["icon"]), a["name"], a["id"])
        comp = QCompleter(self.model(), self)
        comp.setFilterMode(Qt.MatchFlag.MatchContains)
        comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setCompleter(comp)
        self.lineEdit().setPlaceholderText("Search installed apps…")
        i = self.findData(current)
        if current and i < 0:
            self.addItem(f"{current} (not installed)", current)
            i = self.count() - 1
        self.setCurrentIndex(max(i, 0))
        self.activated.connect(self._act)
        comp.activated[str].connect(self._comp)

    def _act(self, i):
        self.appChosen.emit(self.itemData(i) or "")

    def _comp(self, text):
        i = self.findText(text, Qt.MatchFlag.MatchExactly)
        if i >= 0:
            self.setCurrentIndex(i)
            self.appChosen.emit(self.itemData(i) or "")


class FlowLayout(QLayout):
    """Lays small items out left to right and wraps them onto new rows (hidden items are skipped)."""

    def __init__(self, parent=None, hspace=22, vspace=18):
        super().__init__(parent)
        self.items, self.hs, self.vs = [], hspace, vspace
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self.items.append(item)

    def count(self):
        return len(self.items)

    def itemAt(self, i):
        return self.items[i] if 0 <= i < len(self.items) else None

    def takeAt(self, i):
        return self.items.pop(i) if 0 <= i < len(self.items) else None

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._lay(QRect(0, 0, w, 0), False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._lay(rect, True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        sz = QSize()
        for it in self.items:
            if not it.isEmpty():
                sz = sz.expandedTo(it.minimumSize())
        return sz

    def _lay(self, rect, apply):
        x, y, row_h = rect.x(), rect.y(), 0
        for it in self.items:
            if it.isEmpty():
                continue
            sz = it.sizeHint()
            if x > rect.x() and x + sz.width() > rect.right() + 1:
                x, y, row_h = rect.x(), y + row_h + self.vs, 0
            if apply:
                it.setGeometry(QRect(QPoint(x, y), sz))
            x += sz.width() + self.hs
            row_h = max(row_h, sz.height())
        return y + row_h - rect.y()


COMPACT = ("int", "choice", "color", "profile")


def make_field(f, value, commit, engine, ctx=None):
    t, key = f["type"], f["key"]
    if t == "string":
        w = QLineEdit(value or "")
        w.setPlaceholderText(f.get("placeholder", ""))
        w.textEdited.connect(commit)
        return w
    if t == "multiline":
        w = QPlainTextEdit(value or "")
        w.setMinimumHeight(86)
        w.setMaximumHeight(130)
        if f.get("mono"):
            w.setStyleSheet("font-family: monospace;")
        w.textChanged.connect(lambda: commit(w.toPlainText()))
        return w
    if t == "bool":
        w = Switch(bool(value))
        w.toggled.connect(commit)
        return w
    if t == "choice":
        w = compact_combo(QComboBox())
        for v, label in f["options"]:
            w.addItem(label, v)
        w.setCurrentIndex(max(0, w.findData(value)))
        w.activated.connect(lambda i: commit(w.itemData(i)))
        return w
    if t == "int":
        return SpinField(f.get("min", 0), f.get("max", 100), int(value or 0), commit)
    if t == "hotkey":
        w = HotkeyEdit()
        w.set_value(value or {})
        w.changed.connect(commit)
        return w
    if t == "app":
        w = AppCombo(value)
        w.appChosen.connect(commit)
        return w
    if t == "path":
        box = QWidget()
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        le = QLineEdit(value or "")
        le.setPlaceholderText("/path/to/file-or-folder")
        le.textEdited.connect(commit)
        h.addWidget(le, 1)
        for label, fn in (("File…", QFileDialog.getOpenFileName), ("Folder…", None)):
            b = QPushButton(label)

            def pick(_=False, fn=fn, le=le):
                if fn:
                    p, _f = fn(box.window(), "Choose a file", os.path.expanduser("~"))
                else:
                    p = QFileDialog.getExistingDirectory(box.window(), "Choose a folder", os.path.expanduser("~"))
                if p:
                    le.setText(p)
                    commit(p)
            b.clicked.connect(pick)
            h.addWidget(b)
        return box
    if t == "color":
        return ColorField(value or "", commit)
    if t == "profile":
        w = fit_combo(QComboBox())
        for p in engine.profiles():
            w.addItem(p["name"], p["id"])
        w.setCurrentIndex(max(0, w.findData(value)))
        w.activated.connect(lambda i: commit(w.itemData(i)))
        return w
    if t in ("audio_in", "audio_out"):
        devs = sysinfo.audio_devices("source" if t == "audio_in" else "sink")
        w = fit_combo(QComboBox())
        cur = next((d for d in devs if d["default"]), None)
        w.addItem(f"System default ({cur['description']})" if cur else "System default", "")
        for d in devs:
            w.addItem(d["description"], d["name"])
        if value and w.findData(value) < 0:
            w.addItem(f"{value} (not connected)", value)
        w.setCurrentIndex(max(0, w.findData(value or "")))
        w.activated.connect(lambda i: commit(w.itemData(i)))
        return w
    if t == "sound":
        return SoundField(value or "default", commit, lambda: (ctx or {}).get("volume", 80))
    if t == "steps":
        return StepsEditor(value or [], commit, engine)
    return QLabel("?")


def build_form(action, on_param, engine, skip=()):
    """Vertical form for an action's fields. on_param(key, value) is called on every edit.
    A field with when={param: value} is only shown while that param has that value."""
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(16)
    meta = actions.ACTIONS.get(action["type"], {})
    params = dict(action.get("params", {}))
    conds = []

    def refresh():
        for cont, when in conds:
            cont.setVisible(all(params.get(k, meta.get("defaults", {}).get(k)) == v for k, v in when.items()))

    def commit(k, v):
        params[k] = v
        on_param(k, v)
        refresh()

    flow = None
    for f in meta.get("fields", []):
        if f["key"] in skip:
            continue
        cont = QWidget()
        cl = QVBoxLayout(cont)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(7)
        val = params.get(f["key"], meta.get("defaults", {}).get(f["key"]))
        w = make_field(f, val, lambda v, k=f["key"]: commit(k, v), engine, ctx=params)
        small = f["type"] in COMPACT
        if f["type"] == "bool":
            row = QHBoxLayout()
            row.setSpacing(12)
            row.setContentsMargins(0, 2, 0, 2)
            row.addWidget(w)
            row.addWidget(QLabel(f["label"]))
            row.addStretch(1)
            cl.addLayout(row)
        else:
            lab = muted(f["label"].upper())
            cl.addWidget(lab)
            cl.addWidget(w, 0, Qt.AlignmentFlag.AlignLeft if small else Qt.AlignmentFlag(0))
            if f.get("hint"):
                if small:
                    lab.setToolTip(f["hint"])
                    w.setToolTip(f["hint"])
                else:
                    h = QLabel(f["hint"])
                    h.setWordWrap(True)
                    h.setStyleSheet(f"color:{style.MUTED};font-size:11px;")
                    cl.addWidget(h)
        if small:
            if flow is None:
                holder = QWidget()
                flow = FlowLayout(holder)
                lay.addWidget(holder)
            flow.addWidget(cont)
        else:
            flow = None
            lay.addWidget(cont)
        if f.get("when"):
            conds.append((cont, f["when"]))
    refresh()
    return box


class SpinField(QWidget):
    """Compact number box with minus / plus buttons (the wheel and arrow keys work too)."""

    def __init__(self, lo, hi, value, commit):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        self.spin = QSpinBox()
        self.spin.setRange(lo, hi)
        self.spin.setValue(value)
        self.spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.spin.setFixedWidth(max(64, 28 + 9 * len(str(max(abs(lo), abs(hi))))))
        self.spin.valueChanged.connect(commit)
        minus, plus = icon_btn("minus", "Decrease", 14), icon_btn("plus", "Increase", 14)
        for b in (minus, plus):
            b.setFixedSize(30, 30)
            b.setAutoRepeat(True)
            b.setAutoRepeatInterval(60)
        minus.clicked.connect(lambda: self.spin.stepDown())
        plus.clicked.connect(lambda: self.spin.stepUp())
        h.addWidget(minus)
        h.addWidget(self.spin)
        h.addWidget(plus)

    def value(self):
        return self.spin.value()


class ColorField(QWidget):
    """A colour swatch with an Auto button; an empty value means 'use the built-in colour'."""

    def __init__(self, value, commit):
        super().__init__()
        self.commit = commit
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        self.btn = ColorButton(value or "#808080", "Choose a colour")
        self.btn.changed.connect(self._picked)
        h.addWidget(self.btn)
        self.state = QLabel()
        self.state.setStyleSheet(f"color:{style.MUTED};font-size:11px;")
        h.addWidget(self.state)
        self.auto = QPushButton("Reset")
        self.auto.setFixedWidth(60)
        self.auto.setToolTip("Go back to the automatic colour")
        self.auto.clicked.connect(self._reset)
        h.addWidget(self.auto)
        h.addStretch(1)
        self._show(value)

    def _show(self, value):
        self.auto.setEnabled(bool(value))
        self.btn.setEnabled(True)
        self.state.setText(value if value else "Auto")
        self.state.setMinimumWidth(52)

    def _picked(self, c):
        self._show(c)
        self.commit(c)

    def _reset(self):
        self._show("")
        self.commit("")


class SoundField(QWidget):
    """Pick the default chime, a custom audio file, or silence; with a play button to hear it."""

    def __init__(self, value, commit, get_volume):
        super().__init__()
        self.value, self.commit, self.get_volume = value, commit, get_volume
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        self.combo = fit_combo(QComboBox())
        self.combo.activated.connect(self._chosen)
        h.addWidget(self.combo, 1)
        self.play_btn = icon_btn("play", "Play this sound", 16)
        self.play_btn.clicked.connect(self._play)
        h.addWidget(self.play_btn)
        self._fill()

    def _fill(self):
        c = self.combo
        c.clear()
        c.addItem("Default chime", "default")
        if self.value not in ("default", "none", "", None):
            c.addItem(("" if os.path.isfile(self.value) else "(missing) ") + sounds.label(self.value), self.value)
        c.addItem("Choose a file…", "__choose__")
        c.addItem("No sound", "none")
        c.setCurrentIndex(max(0, c.findData(self.value if self.value not in ("", None) else "default")))

    def _chosen(self, i):
        data = self.combo.itemData(i)
        if data == "__choose__":
            path, _ = QFileDialog.getOpenFileName(self.window(), "Choose a sound", os.path.expanduser("~"),
                                                  "Sounds (" + " ".join("*" + e for e in sounds.EXTS) + ")")
            if path:
                try:
                    data = sounds.import_sound(path)
                except (ValueError, OSError) as e:
                    QMessageBox.warning(self.window(), "Could not use that sound", errors.explain(e))
                    data = self.value
            else:
                data = self.value
        self.value = data
        self._fill()
        if data != "__choose__":
            self.commit(data)

    def _play(self):
        if not sounds.play(self.value, self.get_volume()):
            errors.report("No audio output was found to play the sound.", "warn", once_key="sound-test", cooldown=10)


class StepsEditor(QWidget):
    def __init__(self, steps, commit, engine):
        super().__init__()
        self.steps = copy.deepcopy(steps)
        self.commit = commit
        self.engine = engine
        self.open = -1
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(6)
        self._build()

    def _emit(self):
        self.commit(copy.deepcopy(self.steps))

    def _clear(self):
        while self.lay.count():
            it = self.lay.takeAt(0)
            if it.widget():
                it.widget().hide()
                it.widget().setParent(None)
                it.widget().deleteLater()
            elif it.layout():
                while it.layout().count():
                    w = it.layout().takeAt(0).widget()
                    if w:
                        w.deleteLater()

    def _build(self):
        self._clear()
        for i, s in enumerate(self.steps):
            meta = actions.ACTIONS.get(s["type"], {"name": s["type"], "glyph": "grid"})
            card = QFrame()
            card.setObjectName("step")
            card.setStyleSheet(f"#step{{background:{style.BG};border:1px solid {style.BORDER};border-radius:8px;}}"
                               f"#step QWidget{{background:transparent;}}")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(8, 6, 8, 8)
            head = QHBoxLayout()
            ic = QLabel()
            ic.setPixmap(icons.glyph_pixmap(meta["glyph"], 18, "#cfcfd8"))
            head.addWidget(ic)
            title = QPushButton(f"{i + 1}.  {meta['name']}   " + (actions.describe(s) if s["type"] != "delay" else f"{s['params'].get('ms', 0)} ms"))
            title.setObjectName("flat")
            title.setStyleSheet("text-align:left;")
            title.setCursor(Qt.CursorShape.PointingHandCursor)
            title.clicked.connect(lambda _=False, i=i: self._toggle(i))
            head.addWidget(title, 1)
            for glyph, tip, fn in (("arrow-up", "Move up", lambda _=False, i=i: self._move(i, -1)),
                                   ("arrow-down", "Move down", lambda _=False, i=i: self._move(i, 1)),
                                   ("x", "Remove step", lambda _=False, i=i: self._remove(i))):
                b = icon_btn(glyph, tip, 14)
                b.clicked.connect(fn)
                head.addWidget(b)
            cl.addLayout(head)
            if i == self.open:
                form = build_form(s, lambda k, v, i=i: self._param(i, k, v), self.engine)
                cl.addWidget(form)
            self.lay.addWidget(card)
        add = QPushButton("  Add step")
        add.setIcon(icons.glyph_icon("plus", 16, "#d0d0d8"))
        menu = QMenu(add)
        for aid, a in actions.ACTIONS.items():
            if a["multi"] and aid != "back":
                menu.addAction(icons.glyph_icon(a["glyph"], 16, "#d0d0d8"), a["name"]).triggered.connect(lambda _=False, aid=aid: self._add(aid))
        add.setMenu(menu)
        self.lay.addWidget(add)

    def _toggle(self, i):
        self.open = -1 if self.open == i else i
        self._build()

    def _add(self, aid):
        self.steps.append(actions.default_action(aid))
        self.open = len(self.steps) - 1
        self._emit()
        self._build()

    def _remove(self, i):
        del self.steps[i]
        self.open = -1
        self._emit()
        self._build()

    def _move(self, i, d):
        j = i + d
        if 0 <= j < len(self.steps):
            self.steps[i], self.steps[j] = self.steps[j], self.steps[i]
            self.open = j if self.open == i else self.open
            self._emit()
            self._build()

    def _param(self, i, k, v):
        self.steps[i]["params"][k] = v
        self._emit()
