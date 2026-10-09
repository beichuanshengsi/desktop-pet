"""幼儿模式：把桌面锁起来，只让小朋友跟桌宠玩。

**为什么要这个**：小朋友想玩电脑，家长要的是"能玩桌宠、碰不到别的东西"。
桌宠本身是个挂在桌面上的小窗口，既不占屏也没法挡住图标 —— 它需要一个"壳"。

**核心是一条窗口层次**（``KidsMode._keep_above`` 每 600 毫秒重新维持一次）::

    最上层   桌宠 · 小游戏 · 卡册 · 背包 · 对话框      ← 这些照常可点
    中间层   全屏遮罩（KidsOverlay）                  ← 其余所有鼠标点击落在这儿，吞掉
    最下层   桌面图标 · 任务栏 · 别的程序              ← 够不着

窗口顺序不能反。``raise_()`` 的含义是"抬到同一层里最上"，而**任务栏也是置顶窗口**：
先抬遮罩才能盖住任务栏，后抬桌宠才能盖住遮罩。反过来的话就是"遮罩盖住了桌面，
但任务栏还浮在它上面"。

**两档的差别只在键盘**：

* **安全档** —— 只有上面那套窗口层次。鼠标完全锁死，但 ``Win`` / ``Alt+Tab``
  这类**系统级键盘手势**拦不住（它们不走窗口，走的是系统），小朋友按一下能切走。
* **严格档** —— 再加一个低级键盘钩子（``pet/keyblock.py``）。杀软可能对打包后的
  exe 报启发式警告，钩子本身出问题还会让全系统键盘顿一下 —— 所以它是**可选档**，
  默认不开。

**退出**：按住屏幕右上角约 1.5 秒弹出小键盘，输 4 位密码。密码**明文**存在
``config.json`` 的 ``kids_passcode`` 里 —— 这是刻意的：家长忘了密码时打开那个文件
就能看见，或者把它改成空字符串就会重新让他设一个。存成哈希反而会把唯一的后路堵死。

**绝不写进存档**：本模块的任何"正在锁定"状态都不落盘（``cfg`` 里只有密码）。
桌宠是"被任务管理器结束掉也不奇怪"的常驻程序，一旦把"已锁定"持久化，
异常退出后重启就会自己锁上，那才是真的把用户的电脑弄坏了。**重启即解除。**

**兜底**：``Ctrl+Alt+Del`` 是 Windows 的安全注意序列，任何钩子都拦不住 ——
万一卡在里面，用它开任务管理器结束程序。代码里也因此**不需要**再留"紧急自救热键"。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QObject, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QFrame, QGridLayout, QInputDialog,
                               QLabel, QLineEdit, QMessageBox, QPushButton,
                               QVBoxLayout, QWidget)

from . import uitheme
from .config import Config
from .keyblock import KeyBlocker

#: 退出密码的长度。写死 4 位：小键盘一屏放得下，家长也记得住。
PASSCODE_LEN = 4


def valid_passcode(value: object) -> bool:
    """是不是一个能用的密码：**恰好 4 位、半角数字**。

    只收 ASCII 数字：中文输入法下打出来的全角"１２３４"``str.isdigit()`` 也是真，
    但它在小键盘上永远敲不出来 —— 让这种值存进存档，等于给家长埋一个
    "明明设过密码却退不出去"的坑。
    """
    text = str(value or "")
    return len(text) == PASSCODE_LEN and text.isascii() and text.isdigit()


@dataclass
class PasscodeEntry:
    """小键盘正在输入的那 4 位。**纯数据**，不碰 Qt，所以能脱机测。"""

    length: int = PASSCODE_LEN
    typed: str = field(default="")

    def push(self, ch: str) -> bool:
        """吃进一个字符，返回**这次是否刚好输满**（调用方据此决定要不要校验）。"""
        if len(ch) != 1 or not (ch.isascii() and ch.isdigit()):
            return False
        if len(self.typed) >= self.length:
            return False
        self.typed += ch
        return len(self.typed) >= self.length

    def pop(self) -> None:
        self.typed = self.typed[:-1]

    def clear(self) -> None:
        self.typed = ""

    @property
    def full(self) -> bool:
        return len(self.typed) >= self.length

    def matches(self, code: object) -> bool:
        return bool(code) and self.typed == str(code)

    def dots(self, filled: str = "●", empty: str = "○") -> str:
        """给小键盘显示用的一行圆点。"""
        n = len(self.typed)
        return " ".join(filled if i < n else empty for i in range(self.length))


def screen_union() -> QRect:
    """所有显示器合起来的那块矩形。

    多屏时 ``showFullScreen()`` 只盖得住其中一块 —— 遮罩漏掉的那块屏幕上，
    桌面还是活的。所以自己算并集、用 ``setGeometry`` + ``show()``。
    """
    rect = QRect()
    for screen in QGuiApplication.screens():
        rect = rect.united(screen.geometry())
    return rect


# ================================================================ 遮罩


class KidsOverlay(QWidget):
    """盖住整块桌面的那层"玻璃"。

    它只做三件事：**画一层暗底**、**吞掉所有鼠标事件**、**在右上角藏一个
    长按出密码的入口**。桌宠并不画在里面 —— 桌宠是**独立窗口**，被抬到了
    这层玻璃之上，所以点桌宠的鼠标事件由系统直接送给桌宠，压根不经过这里。
    这比自己转发事件可靠得多（转发要处理拖动、右键、滚轮、双击……一样漏了就一样怪）。
    """

    #: 右上角"家长热区"要按住多久才弹小键盘。
    HOLD_MS = 1500
    #: 热区边长（正方形，贴右上角）。
    ZONE = 96

    #: 暗底。alpha 必须 > 0：置顶的透明窗口是**按像素 alpha 判定命中**的，
    #: 全透明的地方鼠标会直接穿过去（那就等于没锁）。
    BACKDROP = QColor(12, 16, 26, 150)

    _PAD_QSS = (
        f"QFrame#kidspad {{ background: {uitheme.SURFACE}; border-radius: 16px; }}"
        f"QLabel#kidstitle {{ color: {uitheme.INK}; }}"
        f"QLabel#kidsdots {{ color: {uitheme.ACCENT}; }}"
        f"QLabel#kidsnote {{ color: #d9480f; }}"
        "QPushButton { border: none; border-radius: 10px; font-size: 17px;"
        f" min-width: 62px; min-height: 46px; background: {uitheme.TRACK};"
        f" color: {uitheme.INK}; font-family: {uitheme.qss_family()}; }}"
        "QPushButton:hover { background: #e2e7f0; }"
        "QPushButton#kidsfn { font-size: 13px; background: #eef2ff;"
        f" color: {uitheme.ACCENT_DARK}; }}"
    )

    unlocked = Signal()

    def __init__(self, passcode: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._passcode = str(passcode)
        self._entry = PasscodeEntry()

        # 无边框 + Tool + 置顶。用 Tool 是为了**不进任务栏、不进 Alt+Tab**：
        # 遮罩要是出现在 Alt+Tab 列表里，安全档就多了一个明摆着的缺口。
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.Tool
                            | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        # 和桌宠窗口相反：遮罩**必须**能拿到键盘焦点，否则小键盘收不到实体键盘输入
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.ArrowCursor)

        self._pad: QFrame | None = None
        self._dots: QLabel | None = None
        self._note: QLabel | None = None
        self._hold = QTimer(self)
        self._hold.setSingleShot(True)
        self._hold.setInterval(self.HOLD_MS)
        self._hold.timeout.connect(self._show_pad)

    # ------------------------------------------------------------ 画

    def _zone_rect(self) -> QRect:
        return QRect(self.width() - self.ZONE - 8, 8, self.ZONE, self.ZONE)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect()
        p.fillRect(rect, self.BACKDROP)

        # 右上角热区画得极淡：家长被告知过就知道在哪，小朋友看不出这是个按钮
        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(self._zone_rect().adjusted(12, 12, -12, -12), 12, 12)

        p.setPen(QColor(255, 255, 255, 215))
        p.setFont(uitheme.ui_font(20, True))
        p.drawText(QRect(0, int(rect.height() * 0.15), rect.width(), 40),
                   Qt.AlignmentFlag.AlignHCenter, "幼儿模式已开启")
        p.setPen(QColor(255, 255, 255, 140))
        p.setFont(uitheme.ui_font(12))
        p.drawText(QRect(0, int(rect.height() * 0.15) + 44, rect.width(), 30),
                   Qt.AlignmentFlag.AlignHCenter,
                   "现在只有桌宠可以点，桌面上的其他东西都锁住了")

        # 小键盘弹出来的时候就不再画这行提示，免得和它叠在一起。
        # 写在屏幕上不怕被小朋友看到：这个年纪看不懂字，而家长一眼就明白。
        if self._pad is None or not self._pad.isVisible():
            p.setPen(QColor(255, 255, 255, 100))
            p.setFont(uitheme.ui_font(11))
            p.drawText(QRect(0, rect.height() - 46, rect.width(), 26),
                       Qt.AlignmentFlag.AlignHCenter,
                       f"家长：按住右上角 {self.HOLD_MS / 1000:.1f} 秒，"
                       f"输入 {PASSCODE_LEN} 位密码退出")
        p.end()

    # ------------------------------------------------------------ 鼠标

    def mousePressEvent(self, event) -> None:
        if self._pad is not None and self._pad.isVisible():
            event.accept()          # 小键盘开着一律不关：不给小朋友"乱点把它点没"的路
            return
        if self._zone_rect().contains(event.position().toPoint()):
            self._hold.start()
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self._hold.stop()
        event.accept()

    # 遮罩上滚轮、右键、双击一律吃掉：默认实现本来就不传播到桌面，
    # 这里显式接住是为了**别让它们冒泡回 QWidget 的默认处理**（右键会弹菜单）。
    def wheelEvent(self, event) -> None:
        event.accept()

    def contextMenuEvent(self, event) -> None:
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        event.accept()

    # ------------------------------------------------------------ 键盘

    def keyPressEvent(self, event) -> None:
        text = event.text()
        if len(text) == 1 and text.isascii() and text.isdigit():
            self._push(text)
            event.accept()
            return
        key = event.key()
        if key == Qt.Key.Key_Backspace:
            self._entry.pop()
            self._sync_dots()
            event.accept()
            return
        if key == Qt.Key.Key_Escape:
            self._hide_pad()
            event.accept()
            return
        event.ignore()

    # ------------------------------------------------------------ 小键盘

    def _build_pad(self) -> QFrame:
        pad = QFrame(self)
        pad.setObjectName("kidspad")
        pad.setStyleSheet(self._PAD_QSS)
        outer = QVBoxLayout(pad)
        outer.setContentsMargins(22, 18, 22, 18)
        outer.setSpacing(10)

        title = QLabel(f"输入 {PASSCODE_LEN} 位退出密码", pad)
        title.setObjectName("kidstitle")
        title.setFont(uitheme.ui_font(13, True))
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        outer.addWidget(title)

        self._dots = QLabel(pad)
        self._dots.setObjectName("kidsdots")
        self._dots.setFont(uitheme.ui_font(16, True))
        self._dots.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        outer.addWidget(self._dots)

        self._note = QLabel(" ", pad)
        self._note.setObjectName("kidsnote")
        self._note.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        outer.addWidget(self._note)

        grid = QGridLayout()
        grid.setSpacing(8)
        keys = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "清除", "0", "退格"]
        for index, key in enumerate(keys):
            btn = QPushButton(key, pad)
            # NoFocus：焦点留在遮罩上，实体键盘敲的数字才会走到遮罩的 keyPressEvent
            # （否则点过一个按钮，之后敲键盘就全喂给那个按钮了）
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            if key == "清除":
                btn.setObjectName("kidsfn")
                btn.clicked.connect(self._clear)
            elif key == "退格":
                btn.setObjectName("kidsfn")
                btn.clicked.connect(self._backspace)
            else:
                btn.clicked.connect(lambda _=False, k=key: self._push(k))
            grid.addWidget(btn, index // 3, index % 3)
        outer.addLayout(grid)

        self._sync_dots()
        return pad

    def _show_pad(self) -> None:
        if self._pad is None:
            self._pad = self._build_pad()
        self._entry.clear()
        self._sync_dots()
        self._set_note(" ")
        pad = self._pad
        pad.adjustSize()
        pad.move(max(0, (self.width() - pad.width()) // 2),
                 max(0, (self.height() - pad.height()) // 2))
        pad.show()
        pad.raise_()
        self.setFocus()

    def _hide_pad(self) -> None:
        if self._pad is not None:
            self._pad.hide()
        self._hold.stop()

    def _sync_dots(self) -> None:
        if self._dots is not None:
            self._dots.setText(self._entry.dots())

    def _set_note(self, text: str) -> None:
        if self._note is not None:
            self._note.setText(text or " ")

    def _clear(self) -> None:
        self._entry.clear()
        self._sync_dots()
        self._set_note(" ")

    def _backspace(self) -> None:
        self._entry.pop()
        self._sync_dots()

    def _push(self, digit: str) -> None:
        """收到一位数字。**先显示、后校验**，输满那一刻才去比密码。

        "先显示"这一条不能省：前三位敲下去界面必须立刻亮一颗圆点，
        否则用户（尤其是不确定自己按了几下的人）看不出自己输到哪儿了。
        ``entry.push`` 的返回值只回答"是不是刚好输满"，**不回答"吃进去没有"** ——
        非数字和"已经满 4 位"都会返回 ``False``，所以这里比对前后长度来区分。
        """
        if self._pad is None:
            # 家长可能直接敲实体键盘：那就顺手把小键盘也调出来，
            # 否则他敲了 4 位却什么也看不见（不知道输了几位）。
            self._show_pad()
        before = len(self._entry.typed)
        full = self._entry.push(digit)
        if len(self._entry.typed) == before:
            return                      # 没吃进去（非数字、或已经满了）：圆点不动
        self._sync_dots()
        if not full:
            return
        if self._entry.matches(self._passcode):
            self.unlocked.emit()
            return
        self._entry.clear()
        self._sync_dots()
        self._set_note("密码不对，再试一次")
        QTimer.singleShot(1800, lambda: self._set_note(" "))


# ================================================================ 控制器


class KidsMode(QObject):
    """幼儿模式的开关与生命周期。``cfg`` / ``pet`` / ``tray`` 由 ``main.py`` 传进来。

    **它不记得自己开着**：没有"恢复上次状态"这回事，进程一起来就是关闭的
    （理由见模块开头"绝不写进存档"）。
    """

    #: 参数是实际生效的档位：``"safe"`` / ``"strict"``。
    entered = Signal(str)
    left = Signal()

    #: 维持窗口层次的节拍。600 毫秒是权衡出来的：任务栏会时不时把自己重新
    #: 抬到最上（点它、或者收到 shell 通知的时候），节拍太慢就会露出可点的空档；
    #: 太快则白费 CPU，而一次 ``raise_()`` 虽然便宜，一秒十几次也没必要。
    TICK_MS = 600

    def __init__(self, cfg: Config, pet: QWidget, tray: object | None = None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self._pet = pet
        self._tray = tray
        self._overlay: KidsOverlay | None = None
        self._blocker = KeyBlocker()
        self._was_topmost = True
        #: 被我们加上"置顶"的那些窗口。退出时要还回去 —— 否则小朋友玩过之后，
        #: 游戏窗口和卡册会一直浮在所有窗口上面，用户找不到原因。
        self._flipped: list[QWidget] = []
        self._timer = QTimer(self)
        self._timer.setInterval(self.TICK_MS)
        self._timer.timeout.connect(self.keep_above)

    # ------------------------------------------------------------ 状态

    @property
    def active(self) -> bool:
        return self._overlay is not None

    @property
    def strict(self) -> bool:
        """严格档此刻是不是真的生效（装过钩子并且没卸）。"""
        return self._blocker.active

    @property
    def blocked_keys(self) -> int:
        """严格档累计吃掉的按键数。只用于自检与日志。"""
        return self._blocker.blocked

    # ------------------------------------------------------------ 进 / 出

    def enter(self, strict: bool = False) -> str:
        """进入幼儿模式，返回实际生效的档位：``"safe"`` / ``"strict"`` / ``"fail"``。

        ``strict=True`` 而钩子没装上时**降级成安全档继续开**，而不是拒绝进入：
        遮罩本身已经挡住了鼠标那一路，比"什么也开不了"有用得多。返回值把这件事
        告诉调用方，由它去说明 —— 这里不弹窗，保持"控制器不做界面"的分工。
        """
        if self.active:
            return "strict" if self.strict else "safe"
        if not valid_passcode(self.cfg.kids_passcode):
            return "fail"       # 没密码不许进：退出路径不能没有，否则真锁死

        # 先装钩子再铺遮罩：万一装失败，降级已经体现在返回值里，
        # 不会出现"遮罩都铺好了才发现严格档没生效"的半截状态。
        if strict:
            self._blocker.install()
            strict = self.strict

        overlay = KidsOverlay(str(self.cfg.kids_passcode))
        overlay.unlocked.connect(self.leave)
        overlay.setGeometry(screen_union())
        self._overlay = overlay

        # 桌宠必须在遮罩之上，否则整个模式就是"什么也点不了" ——
        # 用户可能本来就关着置顶，这里临时打开，退出时还回去。
        self._was_topmost = bool(self.cfg.topmost)
        self._set_topmost(True)

        overlay.show()
        overlay.raise_()
        overlay.activateWindow()
        overlay.setFocus()

        # 托盘图标也要收起来：它藏在任务栏的溢出区里，孩子够不到，
        # 但**家长自己点开它就能看到"退出"** —— 那正是这个模式要挡的东西。
        if self._tray is not None:
            try:
                self._tray.hide()               # type: ignore[attr-defined]
            except (AttributeError, RuntimeError):
                pass

        self._timer.start()
        self.keep_above()
        self.entered.emit("strict" if strict else "safe")
        return "strict" if strict else "safe"

    def leave(self) -> None:
        """退出幼儿模式。没开的时候调用它也是安全的（退出路径上不该再挑条件）。"""
        overlay = self._overlay
        if overlay is None:
            return
        self._timer.stop()
        self._blocker.uninstall()
        self._overlay = None
        self._restore_flipped()
        overlay.hide()
        overlay.deleteLater()
        self._set_topmost(self._was_topmost)
        if self._tray is not None:
            try:
                self._tray.show()               # type: ignore[attr-defined]
            except (AttributeError, RuntimeError):
                pass
        self._pet.raise_()
        self.left.emit()

    def _set_topmost(self, on: bool) -> None:
        """给桌宠设置顶。

        **这是全模块唯一碰 ``set_topmost`` 的地方**，而且走 ``getattr``：
        ``KidsMode`` 对外只声明依赖一个 ``QWidget``（这样测试里塞个假桌宠
        只用实现一两个方法就够），而 ``set_topmost`` 是 ``PetWindow`` 才有的。
        属性不存在就跳过 —— 真桌宠上它一定存在。
        """
        setter = getattr(self._pet, "set_topmost", None)
        if callable(setter):
            setter(on)

    # ------------------------------------------------------------ 维持层次

    def keep_above(self) -> None:
        """把遮罩抬到顶、再把"自己的窗口"抬到遮罩之上。**每 TICK_MS 跑一次。**

        顺序不能反，理由见模块开头。这里每轮都重抬一次，是为了兜住两类事：
        任务栏把自己重新抬高，以及用户中途新开了窗口（卡册 / 背包 / 游戏）。
        """
        overlay = self._overlay
        if overlay is None:
            return
        overlay.raise_()
        for window in self._windows_above():
            self._make_top(window)

    def adopt(self, window: QWidget) -> None:
        """让一个**新开的**窗口一出生就压在遮罩之上。没开幼儿模式时什么也不做。

        给"创建 → 立刻 show"的路径用（游戏窗口），免得它先闪一下在遮罩底下。
        等下一拍 ``keep_above`` 才抬起来的做法也成立，但用户会看见它先被盖住再跳上来。
        """
        if self.active:
            self._make_top(window)

    def _windows_above(self) -> list[QWidget]:
        """要压在遮罩之上的窗口：桌宠 + 我们自己开出来的窗口。

        用"扫一遍顶层窗口"而不是挨个登记：卡册、背包、番茄钟时长对话框都是
        用户点出来的，入口有好几条，**漏登记一个的症状是"点了没反应"**
        （其实窗口开出来了，只是压在遮罩底下）。扫一遍就不会漏。

        只收 ``Window`` / ``Dialog``：``Popup``（右键菜单、下拉）本来就浮在
        一切之上，``ToolTip`` 同理，都不需要、也不该被我们加置顶。
        """
        found: list[QWidget] = [self._pet]
        for widget in QApplication.topLevelWidgets():
            if widget is self._overlay or not widget.isVisible():
                continue
            kind = widget.windowType() & Qt.WindowType.WindowType_Mask
            if kind in (Qt.WindowType.Window, Qt.WindowType.Dialog):
                found.append(widget)
        return found

    def _make_top(self, window: QWidget) -> None:
        """确保 ``window`` 是置顶的，然后抬到最上。"""
        try:
            if not (window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint):
                window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
                window.show()       # setWindowFlag 会让窗口隐藏，必须再 show 回来
                if window not in self._flipped:
                    self._flipped.append(window)
            window.raise_()
        except RuntimeError:
            pass            # 窗口已经被销毁（Qt 的 C++ 对象没了就是这个异常）

    def _restore_flipped(self) -> None:
        """把被我们改成置顶的窗口还原。"""
        for window in self._flipped:
            try:
                if window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint:
                    window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
                    if window.isVisible():
                        window.show()
            except RuntimeError:
                pass
        self._flipped.clear()

    # ------------------------------------------------------------ 收尾

    def shutdown(self) -> None:
        """程序退出时调一次：**保证钩子一定被卸掉**。

        这台机器上的键盘是全局的，程序没了钩子还挂着，症状是"Win 键莫名其妙
        失效"，而用户完全联想不到是那个桌宠。所以退出路径上这里是硬要求，
        不能只靠"反正进程要结束了系统会回收"。
        """
        self._blocker.uninstall()
        if self._overlay is not None:
            self.leave()


# ================================================================ 密码


def _ask_twice(parent: QWidget | None, cfg: Config, *, first_time: bool) -> bool:
    """让用户输两遍 4 位密码，一致才写进存档。取消返回 ``False``。"""
    title = "设置退出密码" if first_time else "换一个退出密码"
    if first_time:
        prompt = ("幼儿模式要用一个 4 位数字密码才能退出。\n"
                  "设一个你记得住的（例如 1234）：")
    else:
        prompt = "输入新的 4 位数字密码："

    while True:
        text, ok = QInputDialog.getText(parent, title, prompt,
                                        QLineEdit.EchoMode.Password)
        if not ok:
            return False
        text = text.strip()
        if not valid_passcode(text):
            QMessageBox.warning(parent, "这个密码不能用",
                                f"要**恰好 {PASSCODE_LEN} 位半角数字**，例如 1234。\n"
                                "（中文输入法下的全角数字不行 —— 小键盘上敲不出来。）")
            continue
        again, ok2 = QInputDialog.getText(parent, "再输一遍",
                                          "再输一遍确认：", QLineEdit.EchoMode.Password)
        if not ok2:
            return False
        if again.strip() != text:
            QMessageBox.warning(parent, "两次不一样", "两次输的不一样，重新来一遍。")
            continue
        cfg.kids_passcode = text
        cfg.save()
        return True


def ensure_passcode(parent: QWidget | None, cfg: Config) -> bool:
    """确认存档里有一个能用的退出密码；没有就当场要一个。取消返回 ``False``。"""
    if valid_passcode(cfg.kids_passcode):
        return True
    if not _ask_twice(parent, cfg, first_time=True):
        return False
    QMessageBox.information(
        parent, "记牢这个密码",
        f"退出幼儿模式：按住屏幕**右上角**约 1.5 秒，弹出小键盘后输入这 {PASSCODE_LEN} 位密码。\n\n"
        "密码以明文存在 config.json 的 kids_passcode 字段里 —— 忘了就打开那个文件看一眼；\n"
        "或者把它改成空字符串，下次会重新让你设一个。\n\n"
        "万一真的卡住了：按 Ctrl+Alt+Del 打开任务管理器结束程序即可。\n"
        "这个组合键是 Windows 的安全注意序列，任何锁定都拦不住。")
    return True


def ask_new_passcode(parent: QWidget | None, cfg: Config) -> bool:
    """换一个退出密码（菜单里的「换退出密码」）。"""
    return _ask_twice(parent, cfg, first_time=False)


def mode_note(strict: bool, got: str) -> str:
    """给调用方拼一句"实际开成了什么"，用于严格档降级时的说明。"""
    if got == "strict":
        return "严格档已生效：Win / Alt+Tab / Alt+F4 都按不动了。"
    if got == "fail":
        return "没能进入幼儿模式。"
    if strict:
        return "安全档已生效：鼠标锁住了，但 Win / Alt+Tab 这类系统级键盘手势拦不住。"
    return "安全档已生效：鼠标锁住了。"
