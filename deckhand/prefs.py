"""Preferences dialog + autostart helpers."""
import os

from PyQt6.QtCore import Qt, QTime, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QComboBox, QDialog, QFileDialog, QFrame, QMessageBox, QTimeEdit, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QSlider, QVBoxLayout

from . import errors, keymap, mcp_install, style, trouble
from .widgets import Switch, fit_combo

AUTOSTART = os.path.expanduser("~/.config/autostart/deckhand.desktop")


def autostart_enabled():
    return os.path.exists(AUTOSTART)


def set_autostart(on):
    if on:
        os.makedirs(os.path.dirname(AUTOSTART), exist_ok=True)
        with open(AUTOSTART, "w") as f:
            f.write("[Desktop Entry]\nType=Application\nName=Deckhand\nComment=Stream Deck control\n"
                    f"Exec={mcp_install.launcher_path()} --minimized\nIcon=deckhand\nX-KDE-autostart-after=panel\n")
    elif os.path.exists(AUTOSTART):
        os.replace(AUTOSTART, AUTOSTART + ".disabled")


class PrefsDialog(QDialog):
    _fw_done = pyqtSignal(str)

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.setWindowTitle("Preferences")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 20)
        lay.setSpacing(14)
        s = engine.settings

        def row(label, widget, hint=None):
            r = QHBoxLayout()
            col = QVBoxLayout()
            col.setSpacing(1)
            col.addWidget(QLabel(label))
            if hint:
                h = QLabel(hint)
                h.setObjectName("muted")
                h.setStyleSheet(f"color:{style.MUTED};font-size:11px;")
                col.addWidget(h)
            r.addLayout(col, 1)
            r.addWidget(widget)
            lay.addLayout(r)

        def sep():
            f = QFrame()
            f.setFixedHeight(1)
            f.setStyleSheet(f"background:{style.BORDER};")
            lay.addWidget(f)

        t = QLabel("Preferences")
        t.setObjectName("h1")
        lay.addWidget(t)

        b = QSlider(Qt.Orientation.Horizontal)
        b.setRange(5, 100)
        b.setValue(s["brightness"])
        b.setFixedWidth(180)
        b.valueChanged.connect(lambda v: engine.set_setting("brightness", v))
        row("Key brightness", b)

        sl = fit_combo(QComboBox())
        for label, v in (("Never", 0), ("After 1 minute", 1), ("After 5 minutes", 5), ("After 10 minutes", 10),
                         ("After 30 minutes", 30), ("After 1 hour", 60)):
            sl.addItem(label, v)
        sl.setCurrentIndex(max(0, sl.findData(s["sleep_minutes"])))
        sl.activated.connect(lambda i: engine.set_setting("sleep_minutes", sl.itemData(i)))
        row("Turn keys off when idle", sl, "Any key press wakes the deck without triggering an action.")
        sep()

        hd = QComboBox()
        fit_combo(hd)
        for label, v in (("Short (0.3 s)", 300), ("Normal (0.5 s)", 500), ("Long (0.8 s)", 800), ("Very long (1.2 s)", 1200)):
            hd.addItem(label, v)
        hd.setCurrentIndex(max(0, hd.findData(s["hold_ms"])))
        hd.activated.connect(lambda i: engine.set_setting("hold_ms", hd.itemData(i)))
        row("Hold time", hd, "How long to press a key before its hold action runs.")

        nt = s["night"]
        nsw = Switch(nt["enabled"])
        row("Dim at night", nsw, "Lower the deck brightness between two times, then restore it.")
        nrow = QHBoxLayout()
        nrow.addWidget(QLabel("From"))
        t1 = QTimeEdit(QTime.fromString(nt["start"], "HH:mm"))
        t1.setDisplayFormat("HH:mm")
        nrow.addWidget(t1)
        nrow.addWidget(QLabel("to"))
        t2 = QTimeEdit(QTime.fromString(nt["end"], "HH:mm"))
        t2.setDisplayFormat("HH:mm")
        nrow.addWidget(t2)
        nrow.addWidget(QLabel("at"))
        nb = QSlider(Qt.Orientation.Horizontal)
        nb.setRange(5, 100)
        nb.setValue(nt["brightness"])
        nb.setFixedWidth(110)
        nrow.addWidget(nb)
        nlab = QLabel(f"{nt['brightness']}%")
        nrow.addWidget(nlab)
        nrow.addStretch(1)
        lay.addLayout(nrow)

        def save_night(*_):
            nlab.setText(f"{nb.value()}%")
            engine.set_setting("night", {"enabled": nsw.isChecked(), "start": t1.time().toString("HH:mm"),
                                         "end": t2.time().toString("HH:mm"), "brightness": nb.value()})
        nsw.toggled.connect(save_night)
        t1.timeChanged.connect(save_night)
        t2.timeChanged.connect(save_night)
        nb.valueChanged.connect(save_night)
        sep()

        pe = Switch(s["pressed_effect"])
        pe.toggled.connect(lambda v: engine.set_setting("pressed_effect", v))
        row("Press animation", pe, "Shrink the key slightly while it is held.")

        an = Switch(s["animations"])
        an.toggled.connect(lambda v: engine.set_setting("animations", v))
        row("Animations", an, "Small transitions that show what changed. Turn off for instant updates.")

        au = Switch(autostart_enabled())
        au.toggled.connect(set_autostart)
        row("Start with the desktop", au, "Launches minimized to the tray at login.")

        ct = Switch(s["close_to_tray"])
        ct.toggled.connect(lambda v: engine.set_setting("close_to_tray", v))
        row("Keep running in the tray", ct, "Closing the window keeps your keys working.")
        sep()

        ok = keymap.keyboard.available()
        st = QLabel(("Keyboard injection ready (/dev/uinput)." if ok else
                     "Deckhand can't send keystrokes yet: no access to /dev/uinput. Hotkeys and media keys need it. Run this once:"))
        st.setWordWrap(True)
        st.setStyleSheet(f"color:{style.OK if ok else style.WARN};font-size:12px;")
        lay.addWidget(st)
        if not ok:
            box = QPlainTextEdit(trouble.UINPUT_RULE_CMD)
            box.setReadOnly(True)
            box.setFixedHeight(84)
            box.setStyleSheet("font-family: monospace; font-size: 11px;")
            lay.addWidget(box)
            cp = QPushButton("Copy command")
            cp.clicked.connect(lambda: (QGuiApplication.clipboard().setText(trouble.UINPUT_RULE_CMD), cp.setText("Copied. Log out and in afterwards.")))
            lay.addWidget(cp, 0, Qt.AlignmentFlag.AlignLeft)
        dev = engine.dev
        info = QLabel(f"{dev.model.name}  ·  serial {dev.serial}  ·  firmware …" if dev else "No Stream Deck connected.")
        if dev:
            import threading
            self._fw_done.connect(lambda fw: info.setText(f"{dev.model.name}  ·  serial {dev.serial}" + (f"  ·  firmware {fw}" if fw else "")))
            threading.Thread(target=lambda: self._fw_done.emit(dev.firmware() if dev.alive else ""), daemon=True).start()
        info.setObjectName("muted")
        info.setStyleSheet(f"color:{style.MUTED};font-size:12px;")
        lay.addWidget(info)

        sep()
        bt = QLabel("Backup & support")
        bt.setObjectName("cardTitle")
        lay.addWidget(bt)
        brow = QHBoxLayout()
        for label, fn in (("Back up…", self._backup), ("Restore…", self._restore), ("Save diagnostics…", self._diag)):
            b = QPushButton(label)
            b.clicked.connect(fn)
            brow.addWidget(b)
        brow.addStretch(1)
        lay.addLayout(brow)
        self.bk_msg = QLabel("Deckhand also keeps a daily automatic backup of your profiles.")
        self.bk_msg.setObjectName("muted")
        self.bk_msg.setWordWrap(True)
        lay.addWidget(self.bk_msg)

        close = QPushButton("Done")
        close.setObjectName("primary")
        close.clicked.connect(self.accept)
        r = QHBoxLayout()
        r.addStretch(1)
        r.addWidget(close)
        lay.addLayout(r)

    def _say(self, text, ok=True):
        self.bk_msg.setStyleSheet(f"color:{style.MUTED if ok else style.DANGER};")
        self.bk_msg.setText(text)

    def _backup(self):
        import time
        from . import backup
        path, _ = QFileDialog.getSaveFileName(self, "Back up Deckhand", os.path.expanduser(f"~/deckhand-backup-{time.strftime('%Y%m%d')}.zip"), "Backup (*.zip)")
        if path:
            try:
                backup.create_backup(path)
                self._say(f"Backup saved to {path}")
            except Exception as e:
                self._say(errors.explain(e, "Backup failed"), False)

    def _restore(self):
        from . import backup
        path, _ = QFileDialog.getOpenFileName(self, "Restore a backup", os.path.expanduser("~"), "Backup (*.zip)")
        if not path:
            return
        try:
            info = backup.inspect_backup(path)
        except ValueError as e:
            self._say(f"Cannot restore: {e}.", False)
            return
        r = QMessageBox.question(self, "Restore backup", f"Replace your profiles and settings with this backup ({info['profiles']} profile(s), made {info['created']})?\n\n"
                                 "Your current setup is saved first, so this can be undone by restoring that copy.")
        if r != QMessageBox.StandardButton.Yes:
            return
        try:
            self.engine.apply_restore(path)
            self._say("Restored. Your previous setup was saved in the backups folder first.")
        except Exception as e:
            self._say(errors.explain(e, "Restore failed"), False)

    def _diag(self):
        import time
        from . import backup
        path, _ = QFileDialog.getSaveFileName(self, "Save diagnostics", os.path.expanduser(f"~/deckhand-diagnostics-{time.strftime('%Y%m%d')}.txt"), "Text (*.txt)")
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(backup.diagnostics_text(self.engine))
                self._say(f"Diagnostics saved to {path}. Attach it when reporting a problem.")
            except Exception as e:
                self._say(errors.explain(e, "Could not save diagnostics"), False)
