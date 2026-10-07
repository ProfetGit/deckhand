"""Auto-switch dialog: map apps and window titles to profiles."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton, QScrollArea, QVBoxLayout,
                             QWidget)

from . import autoswitch, icons, style
from .widgets import Switch, fit_combo, icon_btn


class AutoSwitchDialog(QDialog):
    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.cfg = autoswitch.clean_config(engine.settings.get("auto_switch"))
        self.setWindowTitle("Auto-switch profiles")
        self.resize(720, 640)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(12)
        t = QLabel("Auto-switch profiles")
        t.setObjectName("h1")
        t.setStyleSheet("font-size:17px;font-weight:700;")
        lay.addWidget(t)
        sub = QLabel("Switch the deck to a profile when you focus a certain app or window. The first matching rule wins. "
                     "Deckhand's own window never triggers a switch.")
        sub.setWordWrap(True)
        sub.setObjectName("muted")
        lay.addWidget(sub)

        top = QHBoxLayout()
        top.addWidget(QLabel("Switch profiles automatically"), 1)
        self.enable = Switch(self.cfg["enabled"])
        self.enable.toggled.connect(self._toggle)
        top.addWidget(self.enable)
        lay.addLayout(top)
        self.now = QLabel()
        self.now.setObjectName("muted")
        self.now.setWordWrap(True)
        lay.addWidget(self.now)

        head = QHBoxLayout()
        cap = QLabel("RULES")
        cap.setObjectName("cardTitle")
        head.addWidget(cap, 1)
        self.add_btn = QPushButton("  Add rule")
        self.add_btn.setIcon(icons.glyph_icon("plus", 14, "#d0d0d8"))
        self.add_btn.clicked.connect(self._add_menu)
        head.addWidget(self.add_btn)
        lay.addLayout(head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body = QWidget()
        self.rows = QVBoxLayout(self.body)
        self.rows.setContentsMargins(0, 0, 0, 0)
        self.rows.setSpacing(8)
        self.rows.addStretch(1)
        scroll.setWidget(self.body)
        lay.addWidget(scroll, 1)

        drow = QHBoxLayout()
        drow.addWidget(QLabel("When nothing matches"), 1)
        self.default = fit_combo(QComboBox())
        self.default.setMinimumWidth(220)
        self._fill_profiles(self.default, include_keep=True, current=self.cfg["default"])
        self.default.activated.connect(lambda i: self._set_default(self.default.itemData(i)))
        drow.addWidget(self.default)
        lay.addLayout(drow)

        done = QPushButton("Done")
        done.setObjectName("primary")
        done.clicked.connect(self.accept)
        br = QHBoxLayout()
        br.addStretch(1)
        br.addWidget(done)
        lay.addLayout(br)

        engine.windows.stateChanged.connect(self._status)
        self._build_rows()
        self._status()

    # ---- helpers ------------------------------------------------------------------------
    def _fill_profiles(self, combo, include_keep=False, current=""):
        combo.clear()
        if include_keep:
            combo.addItem("Keep the current profile", "")
        for p in self.engine.profiles():
            combo.addItem(p["name"], p["id"])
        i = combo.findData(current)
        if current and i < 0:
            combo.addItem("(deleted profile)", current)
            i = combo.count() - 1
        combo.setCurrentIndex(max(0, i))

    def _save(self):
        self.engine.set_auto_switch(self.cfg)

    def _toggle(self, on):
        self.cfg["enabled"] = on
        self._save()
        self._status()

    def _set_default(self, pid):
        self.cfg["default"] = pid or ""
        self._save()

    def _status(self):
        w = self.engine.windows
        if self.cfg["enabled"] and not w.supported:
            self.now.setStyleSheet(f"color:{style.WARN};")
            self.now.setText(w.problem or "Window tracking is not available.")
        elif self.cfg["enabled"]:
            self.now.setStyleSheet("")
            act = w.active
            self.now.setText("Focused now: " + autoswitch.window_label(act) if act else "Waiting for the first window change…")
        else:
            self.now.setStyleSheet("")
            self.now.setText("Off. Turn it on to start watching which window has focus (nothing leaves your computer).")

    # ---- rule rows ------------------------------------------------------------------------
    def _build_rows(self):
        while self.rows.count() > 1:
            wd = self.rows.takeAt(0).widget()
            if wd:
                wd.hide()
                wd.setParent(None)
                wd.deleteLater()
        if not self.cfg["rules"]:
            hint = QLabel("No rules yet. Add one, ideally from a recent window so the name is exact.")
            hint.setObjectName("muted")
            hint.setWordWrap(True)
            self.rows.insertWidget(0, hint)
        for n, r in enumerate(self.cfg["rules"]):
            self.rows.insertWidget(n if self.cfg["rules"] else 0, self._row(n, r))

    def _row(self, n, r):
        card = QFrame()
        card.setObjectName("card")
        h = QHBoxLayout(card)
        h.setContentsMargins(10, 8, 8, 8)
        h.setSpacing(8)
        kind = fit_combo(QComboBox())
        kind.addItem("App", "app")
        kind.addItem("Title", "title")
        kind.setCurrentIndex(0 if r["kind"] == "app" else 1)
        kind.setFixedWidth(84)
        kind.setToolTip("App: matches the program (e.g. firefox). Title: matches the window title (e.g. YouTube).")
        kind.activated.connect(lambda i, n=n: self._edit(n, kind=kind.itemData(i)))
        h.addWidget(kind)
        pat = QLineEdit(r["pattern"])
        pat.setPlaceholderText("e.g. firefox   (start with re: for a regular expression)")
        pat.textEdited.connect(lambda v, n=n: self._edit(n, pattern=v, rebuild=False))
        h.addWidget(pat, 1)
        h.addWidget(QLabel("→"))
        prof = fit_combo(QComboBox())
        prof.setMinimumWidth(150)
        self._fill_profiles(prof, current=r["profile"])
        prof.activated.connect(lambda i, n=n: self._edit(n, profile=prof.itemData(i), rebuild=False))
        h.addWidget(prof)
        for glyph, tip, fn in (("arrow-up", "Move up (earlier rules win)", lambda _=False, n=n: self._move(n, -1)),
                               ("arrow-down", "Move down", lambda _=False, n=n: self._move(n, 1)),
                               ("x", "Delete rule", lambda _=False, n=n: self._delete(n))):
            b = icon_btn(glyph, tip, 14)
            b.clicked.connect(fn)
            h.addWidget(b)
        return card

    def _edit(self, n, rebuild=True, **fields):
        if 0 <= n < len(self.cfg["rules"]):
            self.cfg["rules"][n].update(fields)
            if fields.get("pattern") == "":
                return  # an empty pattern is dropped by sanitizing; wait until the user types something
            self._save()

    def _move(self, n, d):
        j = n + d
        if 0 <= j < len(self.cfg["rules"]):
            rules = self.cfg["rules"]
            rules[n], rules[j] = rules[j], rules[n]
            self._save()
            self._build_rows()

    def _delete(self, n):
        if 0 <= n < len(self.cfg["rules"]):
            del self.cfg["rules"][n]
            self._save()
            self._build_rows()

    def _add_menu(self):
        m = QMenu(self)
        recent = self.engine.windows.recent
        if recent:
            for w in recent[:10]:
                app = w["cls"] or w["name"] or w["desktop"]
                act = m.addAction(f"{app}   -   {w['title'][:50]}" if w["title"] else app)
                act.triggered.connect(lambda _=False, app=app: self._add("app", app))
            m.addSeparator()
        m.addAction("Blank app rule", lambda: self._add("app", ""))
        m.addAction("Blank title rule", lambda: self._add("title", ""))
        m.exec(self.add_btn.mapToGlobal(self.add_btn.rect().bottomLeft()))

    def _add(self, kind, pattern):
        profs = self.engine.profiles()
        pid = profs[0]["id"] if profs else ""
        self.cfg["rules"].append({"kind": kind, "pattern": pattern or "new-rule", "profile": pid})
        self._save()
        self._build_rows()
