"""两个小游戏共用的版面、界面零件、结算汇率与窗口底座。

窗口尺寸、HUD 高度、地面厚度、中文字体回退链、结算浮层的样式、
**分数换金币的汇率** —— 这些东西两个游戏必须完全一致，否则在托盘里换个
游戏，窗口尺寸会跳、按钮颜色会变、字体也可能不一样，一眼就看出是两个人写的。

所以集中放这里，谁也别在自己文件里再抄一份。

判断标准很简单：**两个游戏都要用的**才搬进来；只有一个游戏用的
（比如血条、方块配色）留在各自的文件里。
"""

from __future__ import annotations

import random
from pathlib import Path
from time import perf_counter

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

# ---------------------------------------------------------------- 版面

W, H = 780, 580                  # 游戏窗口尺寸（两个游戏一致，切换时不跳）
HUD_H = 56                       # 顶部信息条高度
GROUND_H = 46                    # 地面厚度
GROUND_Y = H - GROUND_H          # 地面上表面

#: 中文字体回退链。不同 Windows 上装的中文字体不一样，写死一个名字很容易翻车。
FONT_STACK = ["Microsoft YaHei UI", "Microsoft YaHei", "SimHei",
              "Noto Sans CJK SC", "Source Han Sans SC", "sans-serif"]

OVERLAY_QSS = (
    "#overlay { background: rgba(255,255,255,238);"
    " border: 1px solid #e2e8f0; border-radius: 14px; }"
    "QLabel { color: #2b3340; }"
    "QPushButton { background: #4a6cf7; color: white; border: none;"
    " padding: 8px 22px; border-radius: 8px; font-size: 13px; }"
    "QPushButton:hover { background: #3b5bdb; }"
)

OVERLAY_SECONDARY_QSS = (
    "QPushButton { background:#e8ecf3; color:#4a5568; }"
    "QPushButton:hover { background:#dbe1ea; }"
)


# ---------------------------------------------------------------- 结算汇率

#: 小卖部的汇率：多少分换 1 金币。
#:
#: 定这个数要看三件事：**一局能买几样**、**打几局能买齐**、**挂机划不划算**。
#: 两个游戏认真打一局通常在 200~800 分，按这里折算就是 20~80 金币；
#: 小卖部最贵的一样 30 金币 —— 也就是"认真打一局，够买一两样"。
#: 改成 1 就是通货膨胀（一局买空货架，金币立刻失去意义），
#: 改成 50 就是永远攒不够（那不如干脆不卖）。
COIN_PER_SCORE = 10


def coins_for(score: int) -> int:
    """一局得 ``score`` 分该给几个金币。

    **两个游戏必须用同一把尺子**，所以折算只写在这里一份。各写一份迟早会
    出现"打弹跳得分更划算"，而玩家一定会发现，然后只玩那个 —— 那另一个
    游戏就白做了。负数与脏数据按 0 处理，结算路径不该因为一个分数崩掉。
    """
    try:
        return max(0, int(score)) // COIN_PER_SCORE
    except (TypeError, ValueError):
        return 0


def ui_font(size: int, bold: bool = False) -> QFont:
    """按回退链挑字体的 QFont。给字号就行，别管系统里装的哪一款。"""
    f = QFont()
    f.setFamilies(FONT_STACK)
    f.setPointSize(size)
    if bold:
        f.setWeight(QFont.Weight.Bold)
    return f


def build_result_overlay(host: QWidget, on_again, on_close):
    """造一个结算浮层，返回 (浮层, 标题标签, 副标题标签)。

    调用方只关心标题和副标题写什么，按钮和样式不用管。
    浮层创建后是隐藏的，需要时自己 ``show()`` + ``center_overlay()``。
    """
    overlay = QWidget(host)
    overlay.setObjectName("overlay")
    overlay.setStyleSheet(OVERLAY_QSS)

    lay = QVBoxLayout(overlay)
    lay.setContentsMargins(28, 24, 28, 24)
    lay.setSpacing(12)

    title = QLabel("", overlay)
    title.setFont(ui_font(15, bold=True))
    title.setAlignment(Qt.AlignmentFlag.AlignCenter)

    sub = QLabel("", overlay)
    sub.setFont(ui_font(11))
    sub.setStyleSheet("color:#6b7688;")
    sub.setAlignment(Qt.AlignmentFlag.AlignCenter)

    btn_again = QPushButton("再来一局", overlay)
    btn_again.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    btn_again.clicked.connect(on_again)

    btn_close = QPushButton("关掉", overlay)
    btn_close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    btn_close.setStyleSheet(OVERLAY_SECONDARY_QSS)
    btn_close.clicked.connect(on_close)

    lay.addWidget(title)
    lay.addWidget(sub)
    lay.addSpacing(4)
    lay.addWidget(btn_again)
    lay.addWidget(btn_close)
    overlay.hide()
    return overlay, title, sub


def center_overlay(overlay: QWidget, w: int = W, h: int = H) -> None:
    """把浮层摆在 HUD 以下那块区域的中间。"""
    overlay.adjustSize()
    overlay.move((w - overlay.width()) // 2,
                 HUD_H + (h - HUD_H - overlay.height()) // 2)


def paint_hud_bar(p, w: int = W) -> None:
    """HUD 底板：白底 + 一条分隔线。两个游戏的顶部条长得一样。"""
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QColor, QPen

    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(255, 255, 255, 235))
    p.drawRect(0, 0, w, HUD_H)
    p.setPen(QPen(QColor(226, 232, 240), 1))
    p.drawLine(0, HUD_H - 1, w, HUD_H - 1)


# ---------------------------------------------------------------- 窗口底座


class GameWindow(QWidget):
    """两个游戏窗口的共同底座。

    **为什么要有这个基类**：``main.py`` 手里只有一个窗口变量，它得能确定地
    调 ``.closed.connect()`` / ``.close()`` / ``.setWindowIcon()``。以前那里
    把类型标成 ``QWidget``，类型检查器就报「QWidget 没有 ``closed`` 属性」——
    因为信号确实是两个子类各自加的。**这份契约本来就该有个地方写下来**，
    而不是靠两个文件里各抄一行 ``closed = Signal(int)``，再附一句注释说
    "记得保持签名一致"。

    底座负责"两个游戏必须一模一样"的部分：

    * 窗口尺寸 / 标题 / 强焦点策略（换游戏时窗口不跳、键盘能直接用）
    * 16ms 精确计时器（一局的真实时长按 wall-clock 算，掉帧只让动作粗一点）
    * 结算浮层的创建、居中、显示
    * 松键清键位、关闭时把本局得分 ``closed.emit()`` 出去

    子类只需要做三件事：

    1. 设 ``TITLE`` / ``OVERLAY_TITLE`` 两个类属性；
    2. ``__init__`` 里先 ``super().__init__(bank, cfg, parent)`` 再建自己的场景
       （别忘 ``self.over = False`` 与 ``self.score = 0`` 底座已经给过了），
       最后调 ``self.start_clock()``；
    3. 实现 ``_step(dt)`` 与 ``_reset_scene()``，需要时再覆盖
       ``_countdown`` / ``_settle`` / ``_decay`` 这几个钩子。
    """

    #: 一局结束时发出，参数是本局得分。``main.py`` 靠它恢复桌宠的桌面漫步。
    closed = Signal(int)

    TITLE = "桌宠小游戏"
    OVERLAY_TITLE = "游戏结束"

    def __init__(self, bank, cfg, parent=None):
        super().__init__(parent)
        self.bank = bank
        self.cfg = cfg
        self.setWindowTitle(self.TITLE)
        self.setFixedSize(W, H)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.rng = random.Random()     # 实例属性：测试能塞固定种子，把随机变可复现
        self.keys: set[int] = set()
        self.pops: list = []           # 粒子反馈，两个游戏各是一种，都只有 update(dt)->bool
        self.score = 0
        self.over = False

        self._build_overlay()

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._last = perf_counter()

    # ------------------------------------------------------------ 时钟

    def start_clock(self) -> None:
        """建完场景后调一次，让计时器开始跑。

        **故意不在 ``__init__`` 里直接 start**：子类的 ``_reset_scene()``
        还没跑完，这时来一帧物理会读到半成品状态（空方块列表、还没摆位的
        接板）。让子类在自己场景建好之后显式踩这一脚。
        """
        self._last = perf_counter()
        self._timer.start(16)

    def _tick(self) -> None:
        now = perf_counter()
        # 夹住 dt：拖动窗口或系统卡顿时 now-_last 可能是秒级，
        # 一步算下去物体会瞬移穿墙。宁可动作粗一点也不能穿。
        dt = min(0.05, max(0.0, now - self._last))
        self._last = now
        if dt <= 0:
            return
        self._advance(dt)

    def _advance(self, dt: float) -> None:
        """推进 dt 秒。与计时分离，测试可以直接喂固定步长。

        两个游戏的差别只有三处，所以抽成钩子而不是各写一份：

        * ``_countdown()`` —— 各自的回合规则（弹跳得分在这里扣时间；
          接狗狗是血量制，不覆盖就是空实现）
        * ``_step()`` —— 一局还在进行时怎么动
        * ``_settle()`` —— 已经结束时让角色停住

        都走完再统一 ``_decay()`` + ``update()``。``_countdown`` 里可能直接
        判负（时间到 / 血扣光），所以第二步要**重新看一次** ``self.over``，
        否则会在结束的那一帧还按"进行中"算一次物理。
        """
        if not self.over:
            self._countdown(dt)
        if self.over:
            self._settle(dt)
        else:
            self._step(dt)
        self._decay(dt)
        self.update()

    # ------------------------------------------------------------ 给子类的钩子

    def _countdown(self, dt: float) -> None:
        """回合规则。默认没有时限。"""

    def _step(self, dt: float) -> None:
        """一局进行中的推进。子类必须实现。"""
        raise NotImplementedError

    def _settle(self, dt: float) -> None:
        """一局结束后的每帧收尾（一般是让角色停住）。默认什么都不做。

        **参数名必须与这里一致**：子类改叫 ``_dt`` 类型检查器会判为
        "不兼容的覆盖"（Python 允许按关键字传参，改名字就是改签名）。
        """

    def _decay(self, dt: float) -> None:
        """每帧都要走的衰减与粒子清理。子类加自己的，记得调 ``super()``。"""
        self.pops = [p for p in self.pops if p.update(dt)]

    def _reset_scene(self, first: bool = False) -> None:
        """把一局重置回开局。子类必须实现，``_restart()`` 会调它。

        ``first`` 区分首局和"再来一局"：首局可以缓一点（少放点怪、
        给一点准备时间），重开则直接进入状态。
        """
        raise NotImplementedError

    # ------------------------------------------------------------ 结算与收尾

    def _build_overlay(self) -> None:
        self.overlay, self.label_title, self.label_sub = build_result_overlay(
            self, self._restart, self.close)
        self.label_title.setText(self.OVERLAY_TITLE)

    def _award_coins(self) -> int:
        """把本局得分折成金币记进存档，返回这一局挣了多少。

        放底座里、由 ``_finish()`` 调，而不是各游戏各写一遍：汇率只有一个
        （``coins_for``），两个游戏必须用同一把尺子。

        **只在结算时给**，中途关掉窗口不给 —— 否则"打到一半看要输了就关窗"
        会变成一种比认真打完更划算的操作。
        """
        earned = coins_for(self.score)
        if earned:
            self.cfg.coins += earned
            self.cfg.save()
        return earned

    def _center_overlay(self) -> None:
        center_overlay(self.overlay, W, H)

    def _restart(self) -> None:
        """「再来一局」。先藏浮层再重置，避免重置过程中浮层闪一下。"""
        self.overlay.hide()
        self.over = False
        self._reset_scene(first=True)
        self.setFocus()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._center_overlay()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.setFocus()
        # 窗口可能在后台等了一阵才被显示，用旧的 _last 会算出好几秒的一大步
        self._last = perf_counter()

    def closeEvent(self, event) -> None:
        self._timer.stop()
        self.closed.emit(self.score)       # main.py 收到后解除桌宠的暂停
        super().closeEvent(event)

    def keyReleaseEvent(self, event) -> None:
        # 两个游戏的按键都是"按住持续生效"，松键就从集合里去掉
        self.keys.discard(event.key())


# ---------------------------------------------------------------- 背景图

#: ``背景名 -> QPixmap 或 None``。paintEvent 每帧都调 load_background，
#: 没有缓存的话每帧都要读一次盘（780x580 的 PNG 约 400KB），帧率会被拖垮。
#: None 表示"这张确实没有"，也要缓存 —— 不然缺图时每帧都去 stat 一次。
_BG_CACHE: dict[str, QPixmap | None] = {}

#: 没有背景图时，两个游戏各自回退到原来的代码画渐变。
#: 这里只登记名字，具体渐变留在各自文件 —— 那是各游戏自己的美术。
BG_BOUNCE = "bg_bounce"       # 弹跳得分（粉色舞台）
BG_CATCH = "bg_catch"         # 接狗狗（蓝天草地）


def load_background(name: str) -> QPixmap | None:
    """读 ``assets/game/<name>.png`` 当游戏背景，拉伸铺满窗口。

    图不存在或读不出来就返回 ``None``，调用方自己回退到代码画的渐变。
    背景图的尺寸不必等于窗口：这里统一缩放到 ``W x H``。
    """
    if name in _BG_CACHE:
        return _BG_CACHE[name]

    from pet.paths import game_asset_dir        # 延迟导入，避免模块级循环依赖

    pm = QPixmap()
    path = Path(game_asset_dir()) / f"{name}.png"
    if path.exists():
        pm = QPixmap(str(path))

    out = None if pm.isNull() else pm.scaled(
        W, H, Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation)
    _BG_CACHE[name] = out
    return out


def clear_background_cache() -> None:
    """换过背景图之后调一次，免得还拿旧的 QPixmap（测试里也用得上）。"""
    _BG_CACHE.clear()
