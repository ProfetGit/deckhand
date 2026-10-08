"""Entry point: single instance, theme, tray-resident main window."""
import os
import sys
import time

from PyQt6.QtCore import QLockFile, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication

from . import style

SOCKET = "deckhand-ipc"


def _already_running():
    s = QLocalSocket()
    s.connectToServer(SOCKET)
    if s.waitForConnected(300):
        s.write(b"show")
        s.flush()
        s.waitForBytesWritten(300)
        s.disconnectFromServer()
        return True
    return False


def _install_crash_guard():
    """PyQt aborts the whole process on an unhandled exception inside a slot. Log it and carry on instead."""
    import time
    import traceback
    from .model import CONFIG_DIR

    def hook(t, v, tb):
        txt = "".join(traceback.format_exception(t, v, tb))
        sys.stderr.write(txt)
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(os.path.join(CONFIG_DIR, "errors.log"), "a") as f:
                f.write(f"--- {time.strftime('%F %T')}\n{txt}")
        except OSError:
            pass
    sys.excepthook = hook


def main():
    _install_crash_guard()
    argv = sys.argv[:]
    minimized = "--minimized" in argv
    if "--minimized" in argv:
        argv.remove("--minimized")
    app = QApplication(argv)
    app.setApplicationName("Deckhand")
    app.setDesktopFileName("deckhand")
    app.setQuitOnLastWindowClosed(False)
    lock_dir = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    lock = QLockFile(os.path.join(lock_dir, "deckhand.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        # Another instance owns the app (maybe still starting up): ask it to show its window, then leave.
        for _ in range(20):
            if _already_running():
                break
            time.sleep(0.15)
        return 0
    app._instance_lock = lock
    QLocalServer.removeServer(SOCKET)
    server = QLocalServer()
    server.listen(SOCKET)

    app.setStyle("Fusion")
    from . import buttonfx
    buttonfx.install(app)
    app.setStyleSheet(style.QSS)
    f = app.font()
    f.setPixelSize(13)
    app.setFont(f)

    from . import icons
    icons.warm_caches()
    from .engine import Engine
    from .mainwindow import MainWindow
    from . import backup
    backup.auto_backup()
    engine = Engine()
    win = MainWindow(engine)
    server.newConnection.connect(lambda: (server.nextPendingConnection(), win.show_front()))
    from .mcp_server import McpServer
    mcp = McpServer(engine)
    mcp.start()
    win.attach_agents(mcp)
    app.aboutToQuit.connect(mcp.stop)
    app.aboutToQuit.connect(engine.shutdown)
    engine.start()
    if not (minimized and win.tray):
        win.show()
    return app.exec()
