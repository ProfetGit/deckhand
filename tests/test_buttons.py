"""Button polish: pointer cursor everywhere, animated hover glow, press dip, disabled buttons, animations off."""
import os, sys, tempfile, time
tmp = tempfile.mkdtemp()
os.environ.update(HOME=tmp, XDG_CONFIG_HOME=tmp + "/cfg", QT_QPA_PLATFORM="offscreen", DECKHAND_SOCKET=tmp + "/s.sock")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QEnterEvent, QMouseEvent
from PyQt6.QtWidgets import QApplication, QComboBox, QPushButton, QToolButton, QLabel, QWidget, QVBoxLayout
app = QApplication(sys.argv)
from deckhand import style, motion, buttonfx
app.setStyleSheet(style.QSS)
buttonfx.install(app)
from deckhand.engine import Engine
from deckhand.mainwindow import MainWindow

fails = []
def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  {extra}"))
    if not cond: fails.append(name)
def spin(sec):
    end = time.monotonic() + sec
    while time.monotonic() < end:
        app.processEvents(); time.sleep(0.004)
def enter(b): app.sendEvent(b, QEnterEvent(QPointF(5, 5), QPointF(5, 5), QPointF(5, 5)))
def leave(b): app.sendEvent(b, QEvent(QEvent.Type.Leave))
def mouse(b, kind):
    app.sendEvent(b, QMouseEvent(kind, QPointF(5, 5), QPointF(5, 5), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
glow = lambda b: b.findChild(buttonfx._Glow, "hoverGlow")

w = QWidget(); lay = QVBoxLayout(w)
b1, b2, tb, cb, lbl = QPushButton("Test"), QPushButton("Disabled"), QToolButton(), QComboBox(), QLabel("not a button")
b2.setEnabled(False); b3 = QPushButton("Primary"); b3.setObjectName("primary"); b4 = QPushButton("Danger"); b4.setObjectName("danger")
for x in (b1, b2, b3, b4, tb, cb, lbl): lay.addWidget(x)
w.show(); spin(0.1)
check("every enabled button gets the pointer cursor", all(x.cursor().shape() == Qt.CursorShape.PointingHandCursor for x in (b1, b3, b4, tb)))
check("dropdowns get the pointer cursor too", cb.cursor().shape() == Qt.CursorShape.PointingHandCursor)
check("disabled buttons keep the normal arrow", b2.cursor().shape() != Qt.CursorShape.PointingHandCursor)
b2.setEnabled(True); spin(0.05); check("enabling a button gives it the pointer", b2.cursor().shape() == Qt.CursorShape.PointingHandCursor)
b2.setEnabled(False); spin(0.05); check("disabling it takes the pointer away", b2.cursor().shape() != Qt.CursorShape.PointingHandCursor)
check("plain labels are untouched", glow(lbl) is None and lbl.cursor().shape() != Qt.CursorShape.PointingHandCursor)
check("each button has one click-through glow overlay", all(glow(x) is not None for x in (b1, b3, b4, tb)) and len(b1.findChildren(buttonfx._Glow)) == 1
      and glow(b1).testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
check("glow covers the whole button and follows resizes", glow(b1).geometry() == b1.rect() and (b1.resize(200, 50) or True) and (spin(0.05) or True) and glow(b1).geometry() == b1.rect())

g = glow(b1); idle = b1.grab().toImage()
enter(b1); spin(0.02)
check("hover glow animates in (not instant)", 0.0 <= g.hover < 1.0)
spin(0.25); check("and reaches full strength", g.hover > 0.99, g.hover)
hov = b1.grab().toImage()
check("a hovered button actually looks different", hov != idle)
c = hov.pixelColor(100, 25); c0 = idle.pixelColor(100, 25)
check("hover lightens the button", c.red() > c0.red() or c.green() > c0.green(), (c.getRgb(), c0.getRgb()))
mouse(b1, QEvent.Type.MouseButtonPress); spin(0.2)
check("pressing dims it", g.press > 0.95 and b1.grab().toImage() != hov)
mouse(b1, QEvent.Type.MouseButtonRelease); spin(0.3); check("releasing restores the hover look", g.press < 0.02)
leave(b1); spin(0.35); check("leaving fades the glow back out", g.hover < 0.02 and b1.grab().toImage() == idle)
enter(b2); spin(0.2); check("disabled buttons never glow", glow(b2).hover == 0.0)
for x in (b3, b4, tb): enter(x); spin(0.2); check(f"{x.objectName() or 'tool'} button glows too", glow(x).hover > 0.9); leave(x)
enter(b1); spin(0.05); leave(b1); spin(0.01); check("quick in-and-out never leaves a stuck glow", (spin(0.4) or True) and g.hover < 0.02)

motion.set_enabled(False)
enter(b3); check("with animations off the glow is instant", glow(b3).hover == 1.0); leave(b3); check("and leaves instantly", glow(b3).hover == 0.0)
motion.set_enabled(True)

# the real app: every button in the main window and its dialogs
e = Engine(); e.windows.install_script = False
mw = MainWindow(e); mw.resize(1280, 900); mw.show(); spin(0.3)
from PyQt6.QtWidgets import QLineEdit
btns = [x for x in mw.findChildren((QPushButton, QToolButton)) if x.objectName() != "hoverGlow" and x.isVisibleTo(mw) and not isinstance(x.parent(), QLineEdit)]
check("main window has many buttons", len(btns) > 10, len(btns))
bad = [x.text() or x.toolTip() for x in btns if x.isEnabled() and x.cursor().shape() != Qt.CursorShape.PointingHandCursor]
check("every enabled button in the main window shows a pointer", not bad, bad)
nog = [x.text() or x.toolTip() for x in btns if glow(x) is None]
check("every button in the main window has a glow", not nog, nog)
mw._select(0); spin(0.3)
ins = [x for x in mw.inspector.findChildren((QPushButton, QToolButton)) if x.objectName() != "hoverGlow" and x.isVisibleTo(mw)]
check("inspector buttons (Test, Clear, icon pickers...) all have it", ins and all(glow(x) is not None and (not x.isEnabled() or x.cursor().shape() == Qt.CursorShape.PointingHandCursor) for x in ins), len(ins))
pages = [x for x in mw.findChildren(QPushButton) if x.property("glowRadius") == 13]
check("round page tabs get a matching round glow", pages and glow(pages[0]).radius() == 13.0)
from deckhand.prefs import PrefsDialog
from deckhand.agents_dialog import AgentsDialog
from deckhand.mcp_server import McpServer
for d in (PrefsDialog(e, mw), AgentsDialog(e, McpServer(e), mw)):
    d.show(); spin(0.2)
    db = [x for x in d.findChildren(QPushButton) if x.objectName() != "hoverGlow"]
    check(f"{type(d).__name__}: buttons have pointer + glow", db and all(glow(x) is not None and x.cursor().shape() == Qt.CursorShape.PointingHandCursor for x in db if x.isEnabled()))
    d.close()
e.shutdown()
print("FAILED:", fails if fails else "none"); sys.exit(1 if fails else 0)
