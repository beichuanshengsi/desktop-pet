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
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

#: 字体回退链与自绘字体是**全程序共用**的，实现搬到了 ``pet/uitheme.py``
#: （桌宠自己也要开对话框和面板，放在 game 里会逼出 pet → game 的循环依赖）。
#: 这里转出来是为了两个游戏的 import 一行都不用改。
from pet.uitheme import FONT_STACK, ui_font            # noqa: F401
#: 装备加成。**四个游戏都从这一个函数取** —— 加成规则只写在 ``pet/cards.py``
#: 一份，各游戏自己算一份的话，迟早出现"打弹跳得分能吃到加成、打 2048 吃不到"，
#: 而玩家一定会挑那个更划算的玩。
from pet.cards import coins_with_bonus

# ---------------------------------------------------------------- 版面

W, H = 780, 580                  # 游戏窗口尺寸（两个游戏一致，切换时不跳）
HUD_H = 56                       # 顶部信息条高度
GROUND_H = 46                    # 地面厚度
GROUND_Y = H - GROUND_H          # 地面上表面

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

    ⚠️ **有一处刻意的例外**：``game/g2048.py`` 的 ``coins_for_tile``。
    那一款按**最大格子**折算而不是按分数 —— 因为它的分数会到几千，
    套这里的 ``// 10`` 就是一局几百金币，小卖部当场失去意义。
    改这个常数的时候记得那是**两处**（这里和那边），
    只改一边的后果是"打 2048 比打另外三款划算得多"，
    而玩家一定会发现最划算的那一款。
    """
    try:
        return max(0, int(score)) // COIN_PER_SCORE
    except (TypeError, ValueError):
        return 0


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


def build_confirm_overlay(host: QWidget, on_cancel, on_pause, on_settle):
    """造「这一局还没打完」的确认浮层，返回 ``(浮层, 标题标签, 副标题标签)``。

    三个出口：**按当前分数结算** / **暂停，回头再玩** / **取消，继续玩**。
    顺序是有意的 —— 结算排最前（主按钮，蓝底），"取消"垫底，跟系统对话框
    把"安全出口"放在最后的习惯一致；把"取消"放第一位会让人误点。

    为什么用自定义浮层而不是 ``QMessageBox``：
    1. 样式要和结算浮层一致（同一套 ``OVERLAY_QSS``），弹个系统灰框很出戏；
    2. ``QMessageBox`` 是模态对话框，``exec()`` 会阻塞事件循环 —— 冒烟测试
       没法断言"点了取消之后这一局还在不在"。
    """
    overlay = QWidget(host)
    overlay.setObjectName("overlay")
    overlay.setStyleSheet(OVERLAY_QSS)
    overlay.setFixedWidth(352)

    lay = QVBoxLayout(overlay)
    lay.setContentsMargins(28, 24, 28, 24)
    lay.setSpacing(10)

    title = QLabel("这一局还没打完", overlay)
    title.setFont(ui_font(14, bold=True))
    title.setAlignment(Qt.AlignmentFlag.AlignCenter)

    sub = QLabel("", overlay)
    sub.setFont(ui_font(11))
    sub.setStyleSheet("color:#6b7688;")
    sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
    sub.setWordWrap(True)

    def _button(text: str, slot, *, secondary: bool) -> QPushButton:
        btn = QPushButton(text, overlay)
        # NoFocus：游戏靠键盘玩，按钮抢走焦点会让"取消继续玩"之后按键失灵
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if secondary:
            btn.setStyleSheet(OVERLAY_SECONDARY_QSS)
        btn.clicked.connect(slot)
        return btn

    lay.addWidget(title)
    lay.addWidget(sub)
    lay.addSpacing(4)
    lay.addWidget(_button("按当前分数结算", on_settle, secondary=False))
    lay.addWidget(_button("暂停，回头再玩", on_pause, secondary=True))
    lay.addWidget(_button("取消，继续玩", on_cancel, secondary=True))
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


# ---------------------------------------------------------------- HUD 排版
#
# 自绘 HUD（``QPainter.drawText``）没有布局管理器兜底 —— **坐标写错就是直接叠着印**。
# 真事：弹跳得分的第一版把「最高 385」和「第 2 轮 · 剩 17 块」两段画进了同一段像素
# （360~436 完全重合），当时所有逻辑断言全绿，是把验收图放大到 1:1 才看出来的。
#
# 修法是每个游戏各写两张表（``段名 -> (槽位起点, 槽位宽)`` 与 ``段名 -> 最宽内容占多少像素``），
# 绘制函数一行坐标都不许写死；而**算区间**这件事两个游戏是同一套算术，
# 所以放这里一份，各自只提供自己的表（``minigame.hud_zone_rect`` 就是这么用的）。


def zone_spans(zones: dict[str, tuple[int, int]],
               widest_px: dict[str, int],
               right_aligned: tuple[str, ...] = ()) -> dict[str, tuple[int, int]]:
    """把 ``段名 -> (槽位起点, 槽位宽)`` 算成 ``段名 -> (墨迹左, 墨迹右)``。

    ``right_aligned`` 里的段按右对齐算：槽位右边缘就是墨迹右边缘，
    墨迹从 ``起点 + 宽 - 实际宽`` 开始。之所以要区分，是因为数字位数会变
    （"剩 18 块" → "剩 9 块"），右对齐能让变化发生在左边，不把隔壁元素推来推去。

    **纯算术，不查字体** —— 于是在任何平台上都给出同一个答案，可以放心拿去
    断言"两段有没有叠在一起"。它也是 ``offline`` 安全的：offscreen 平台插件
    在本机字体库为空，``QFontMetrics`` 量出来是方框的宽度（约真值两倍），
    拿它断言会**误报**叠字（实测误报 4 组）。
    """
    out: dict[str, tuple[int, int]] = {}
    for name, (x, w) in zones.items():
        tw = int(widest_px.get(name, w))
        out[name] = (x + w - tw, x + w) if name in right_aligned else (x, x + tw)
    return out


def overlapping_zones(spans: dict[str, tuple[int, int]]) -> list[tuple[str, str]]:
    """两两**相交**的段名对；返回空列表就是排版没重叠。

    首尾刚好相接（``a1 == b0``）不算重叠：中间还留着 0 像素，肉眼看是分开的。
    """
    names = sorted(spans)
    out: list[tuple[str, str]] = []
    for i, a in enumerate(names):
        a0, a1 = spans[a]
        for b in names[i + 1:]:
            b0, b1 = spans[b]
            if a0 < b1 and b0 < a1:
                out.append((a, b))
    return out


def measure_zone_widest(fonts: dict[str, tuple[int, bool]],
                        widest: dict[str, str]) -> dict[str, int]:
    """用**当前字体**量一组 HUD 段"最宽内容"占多少像素。

    三个游戏各写一遍之后抽到这里 —— 它们做的是同一件事（遍历"最宽内容"、
    按登记的字号造字体、量宽度），差别只有传进来哪两张表。

    ⚠️ **必须在真实平台上调**：offscreen 平台插件在本机**字体库是空的**
    （``QFontDatabase.families()`` 返回空列表），``QFontMetrics`` 量出来是
    方框的宽度、约等于真值的两倍。冒烟测试跑的就是 offscreen，所以那边
    只比 ``HUD_WIDEST_PX`` 这张登记表（纯算术）；真字体的复测放在验收脚本里
    （``tools/verify_v21_ui.py`` / ``verify_v22_ui.py``），两者对照打印。
    """
    from PySide6.QtGui import QFontMetrics

    out: dict[str, int] = {}
    for name, text in widest.items():
        size, bold = fonts[name]
        out[name] = QFontMetrics(ui_font(size, bold=bold)).horizontalAdvance(text)
    return out


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
    * **中途退出的确认框**（结算 / 暂停 / 取消）与**暂停-恢复**（``suspend`` /
      ``resume``），见 ``ask_exit``
    * 松键清键位、关闭时把本局得分 ``closed.emit()`` 出去

    子类只需要做四件事：

    1. 设 ``TITLE`` / ``OVERLAY_TITLE`` 两个类属性；
    2. ``__init__`` 里先 ``super().__init__(bank, cfg, parent)`` 再建自己的场景
       （别忘 ``self.over = False`` 与 ``self.score = 0`` 底座已经给过了），
       最后调 ``self.start_clock()``；
    3. 实现 ``_step(dt)`` / ``_reset_scene()`` / ``_finish(early)`` 三个必填钩子，
       需要时再覆盖 ``_countdown`` / ``_settle`` / ``_decay`` / ``_record_best``
       / ``_round_coins``；
    4. 把 ``Esc`` 与「重开」都接到 ``self.ask_exit()``（别直接 ``close()``）。

    **"记最高分"与"算金币"抽成 ``_record_best`` / ``_round_coins`` 两个钩子**，
    是因为它们各有两个调用方：打完结算（``_finish``）和中途退出结算
    （``_settle_early``）。各写一份的话，"中途退出不记最高分"这种漏改一定会出现。
    """

    #: 一局结束时发出，参数是本局得分。``main.py`` 靠它恢复桌宠的桌面漫步。
    closed = Signal(int)

    #: 这一局被「暂停，回头再玩」收起来了（窗口已隐藏但状态还在）。
    #: ``main.py`` 收到后恢复桌宠走动，并在右键菜单里挂「继续上一局」。
    #: **和 ``closed`` 是两回事**：那个是"这局没了"，这个是"这局先放一放"。
    suspended = Signal()

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
        #: 本局结算时用到的装备加成比例（0.13 = +13%）。给结算浮层那句
        #: "（含装备 +13%）"用 —— 不加这一行，用户根本看不出装备起没起作用。
        self._bonus_rate = 0.0
        #: 这一局被「暂停，回头再玩」收着（见 ``suspend``）。
        self._suspended = False
        #: 程序自己拆窗口用的开关：置上之后 ``closeEvent`` 不再拦（见 ``close_now``）。
        self._force_close = False
        #: 这一局是"玩家中途收工、按当时分数结算"的（不是时间到/撞死）。
        self._settled_early = False
        #: 本局实发金币（含装备加成）。``_award_coins`` 写它，``close_settling``
        #: 读它 —— 外面（``main.py``）要靠这个数决定要不要弹一句"帮你结算了"。
        self._last_earned = 0

        self._build_overlay()
        self._build_confirm()

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

    def _record_best(self) -> None:
        """把本局成绩并进存档里的最高分。**默认什么都不记**，四个游戏各覆盖。

        各游戏记的字段不同（``best_score`` / ``best_catch`` / ``best_runner`` /
        ``best_2048``），但"只有超过才写、写就立刻 ``save()``"这条规矩一样。
        抽成钩子是为了让 ``_finish()``（打完）与 ``_settle_early()``（中途退出）
        **共用同一份记录逻辑** —— 这个功能要修的正是"中途退出什么都不记"，
        所以这两条路必须走同一个实现，不能各写一份。
        """

    def _round_coins(self) -> int:
        """本局该给的**基础**金币（还没乘装备加成）。默认按分数折算。

        ``g2048`` 覆盖它：那一款按**最大格子**折算（``coins_for_tile``），
        不跟 ``coins_for`` 这把尺子（理由写在 ``g2048.py`` 模块开头）。
        抽成钩子之后，"中途退出结算"也会自动走对同一个算法 ——
        否则会出现"打完按格子算、中途退按分数算"这种两把尺子的事故。
        """
        return coins_for(self.score)

    def _finish(self, early: bool = False) -> None:
        """结算这一局。**子类必须实现**（四个游戏的结算文案各不相同）。

        ``early=True`` 表示"玩家中途按当前分数收工"，不是时间到 / 撞死 ——
        文案要跟着变（"提前收工"而不是"时间到"），否则玩家会以为是自己输了。

        ⚠️ **参数名必须与这里一致**：子类改叫 ``stop`` 之类类型检查器会判为
        "不兼容的覆盖"（Python 允许按关键字传参，改名字就是改签名）。
        底座只调 ``_finish(early=True)`` 这一种，所以参数要给默认值。
        """
        raise NotImplementedError

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

    def _build_confirm(self) -> None:
        self.confirm, self.confirm_title, self.confirm_sub = build_confirm_overlay(
            self, self._cancel_exit, self._suspend_round, self._settle_early)
        self.confirm_sub.setText(
            "直接退出的话，这一局打的分数就白打了。\n"
            "可以按现在的分数结算拿金币，也可以先暂停、回头再从右键菜单接着玩。")

    def _award_coins(self) -> int:
        """把本局该得的金币记进存档，返回这一局挣了多少（**含装备加成**）。

        放底座里、由 ``_finish()`` 与 ``_settle_early()`` 调，而不是各游戏各写
        一遍：汇率只有一个（``coins_for``），四个游戏必须用同一把尺子。

        **基础金币走 ``_round_coins()`` 这个钩子**（默认按分数折算，2048 覆盖成
        按最大格子折算）—— 这样"打完结算"和"中途退出结算"自动用同一个算法。

        装备加成在这里乘上去（``coins_with_bonus``），而不是去改 ``coins_for``：
        汇率是"分 → 金币"的换算，加成是"玩家资产带来的额外收益"。两件事混在
        一起的话，"卸下装备之后汇率是多少"就说不清了，而且
        ``coins_for`` 是个纯函数，被测试和 HUD 到处引用。
        """
        base = self._round_coins()
        earned, self._bonus_rate = coins_with_bonus(self.cfg, base)
        self._last_earned = earned
        if earned:
            self.cfg.coins += earned
            self.cfg.save()
        return earned

    def coins_note(self) -> str:
        """结算文案里那句"（含装备 +13%）"。没吃到加成时返回空串。

        单独抽出来，是因为四个游戏的结算文案长得都不一样（2048 那款还要报
        最大格子），但**加成的说法必须一致** —— 各写一遍迟早有一处忘了改，
        而症状是"某个游戏看起来没吃加成"。
        """
        rate = float(getattr(self, "_bonus_rate", 0.0))
        return f"（含装备 +{rate * 100:.0f}%）" if rate > 0 else ""

    def _center_overlay(self) -> None:
        center_overlay(self.overlay, W, H)

    def _restart(self) -> None:
        """「再来一局」。先藏浮层再重置，避免重置过程中浮层闪一下。"""
        self.overlay.hide()
        self.over = False
        # 「这一局是中途收工的」和「这一局发了多少金币」都是**属于一局**的标记，
        # 重开就是新的一局 —— 不清的话，新一局会顶着"上一局是中途收工的"这个
        # 身份继续跑（``settled_early`` 就再也回不到 False 了）。
        self._settled_early = False
        self._last_earned = 0
        self._reset_scene(first=True)
        self.setFocus()

    # ------------------------------------------------------------ 中途退出
    #
    # 这一节修的是一个具体的坑：以前按 Esc / 点关闭按钮 / 按 R 重开，只要这一局
    # 还没打完，分数和金币就**全部丢掉**（``_finish()`` 只在时间到 / 撞死时才跑）。
    # 玩家玩了半局、临时有急事，回来一看白玩 —— 这不合理。
    #
    # 现在的规矩：**中途要走，先问一句**，三个出口 ——
    #   按当前分数结算（``_settle_early``）/ 暂停回头再玩（``suspend``）/ 取消继续玩。
    #
    # 为什么不担心"看要输了就中途结算更划算"：四个游戏的分数**只增不减**，
    # 金币又只跟当前分数（2048 跟最大格子）挂钩 —— 中途结算拿到的**只会比打完少**。
    # 弹跳得分 / 跑一跑越到后面单位时间收益越高，2048 提前退更是纯亏。

    @property
    def is_suspended(self) -> bool:
        """这一局是不是被「暂停，回头再玩」收起来了。"""
        return self._suspended

    @property
    def settled_early(self) -> bool:
        """这一局是不是"中途收工、按当时分数结算"的。"""
        return self._settled_early

    @property
    def last_earned(self) -> int:
        """本局实发金币（含装备加成）。没结算过就是 0。"""
        return self._last_earned

    def request_close(self) -> None:
        """``Esc`` / 点关闭按钮时的统一入口。

        打完了就直接关（这时正看着结算浮层，关掉是玩家本意）；
        没打完就先弹确认框，别让这一局白丢。

        四个游戏都从这里走，**不要在自己文件里直接 ``self.close()``** ——
        那样会把确认框整个绕过去。
        """
        if self.over:
            self.close()
        else:
            self.ask_exit()

    def request_restart(self) -> None:
        """``R`` 重开的统一入口。

        打完时直接重开；**没打完时要先问一句** —— 这条最容易漏：
        ``R`` 按下去没有任何提示，玩家不会意识到这一局的分数已经没了。
        """
        if self.over:
            self._restart()
        else:
            self.ask_exit()

    def ask_exit(self) -> None:
        """要退出 / 重开，但这一局还没打完 —— 先弹确认框问一句。

        ``Esc`` 和「重开」都接到这里，**不要再直接调 ``close()``**：
        直接关就是玩家白丢一局，而重开更隐蔽（按下去什么都没提示、分数就没了）。

        三种情况直接放行、不弹框：

        * 这一局已经结算过（``self.over``，正看着结算浮层）—— 关掉就完了；
        * 已经在暂停态（窗口本来就藏着，也点不到）；
        * 确认框已经开着（连按两下 ``Esc`` 不该叠出两层浮层）。
        """
        if self.over or self._suspended or self.confirm.isVisible():
            return
        self.confirm.show()
        self.confirm.raise_()
        center_overlay(self.confirm, W, H)

    def _cancel_exit(self) -> None:
        """「取消，继续玩」：收起确认框，这一局一个字节都没动。"""
        self.confirm.hide()
        self.setFocus()

    def _settle_early(self) -> None:
        """「按当前分数结算」：把这一局按现在的进度结掉。

        走的是和打完完全一样的 ``_finish()``，只是带 ``early=True`` 换个文案 ——
        于是"记最高分 / 给金币 / 弹结算浮层"三件事自动和正常结算一模一样。

        浮层照样弹（玩家能从上面看到拿了多少金币，也能直接「再来一局」），
        这跟"点 Esc 就直接消失"是两件事：**退出的是这一局，不是这个窗口**。
        """
        if self.over:
            return
        self.confirm.hide()
        self._settled_early = True
        self._finish(early=True)

    def _suspend_round(self) -> None:
        """「暂停，回头再玩」：收起确认框，然后冻结这一局。"""
        self.suspend()

    def suspend(self) -> None:
        """冻结这一局但不结束：停表 + 藏窗口，**状态一个都不丢**。

        ⚠️ 这里**绝不能走 ``close()``**：那会触发 ``closed``，``main.py`` 收到
        就把窗口 ``deleteLater()`` 掉了 —— 那就真没了，跟直接退出没区别。
        所以只 ``hide()``，窗口对象留着，``resume()`` 一叫就接着打。

        发 ``suspended`` 而不是 ``closed``：外面要做的事也不一样 ——
        ``closed`` 是"解除暂停 + 拆窗口"，``suspended`` 是"恢复桌宠走动 +
        在菜单里挂一个继续入口"，窗口得留着。

        **已经是暂停态就直接返回**：``main.py`` 收到信号会去 ``pet`` 上挂菜单、
        ``tray.refresh()``，重复发一遍是白干；而"关掉桌宠再打开"这类操作也可能
        让同一条路径走到两次。
        """
        if self._suspended:
            return
        self.confirm.hide()
        self._timer.stop()
        self._suspended = True
        self.hide()
        self.suspended.emit()

    def resume(self) -> None:
        """从暂停态接着打。不是暂停态则什么都不做（重复点菜单入口不该有副作用）。"""
        if not self._suspended:
            return
        self._suspended = False
        # 暂停期间可能过了十几分钟，_last 还停在那一刻 —— 不重置的话
        # 恢复的第一帧会算出巨大 dt，物体直接瞬移出界（``_tick`` 虽然夹到
        # 0.05 秒，但那是给掉帧用的，不该拿来兜这种"暂停了几分钟"的情况）。
        self._last = perf_counter()
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()
        self._timer.start(16)

    def close_now(self) -> None:
        """不管打没打完，立刻关掉（程序自己拆窗口时用）。

        正常关窗会被 ``closeEvent`` 拦下来弹确认框；换游戏、退出程序时弹那个框
        是纯打扰 —— 所以给外面一条"我确定要关"的路。
        """
        self._force_close = True
        self.close()

    def close_settling(self) -> int:
        """收窗口之前，把还没打完的这一局按当前进度结掉。返回这一局挣的金币。

        给"换一个游戏"和"退出程序"用：那一局是玩家**明确要求要留着**的
        （他选的是暂停，不是结算），直接 ``deleteLater()`` 会把进度抹掉 ——
        那正是这个功能要修的毛病。既然他改主意去玩别的了，就把这一局按现在的
        分数结掉（金币会进存档，``main.py`` 顺手弹个托盘气泡告诉他），
        而不是悄悄扔掉。

        结算浮层虽然会 ``show()``，但窗口本身是藏着的（暂停态），玩家看不见 ——
        所以这里不需要为"闪一下"做什么特殊处理。
        """
        if not self.over:
            self._settled_early = True
            self._finish(early=True)
        self.close_now()
        return self.last_earned

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._center_overlay()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.setFocus()
        # 窗口可能在后台等了一阵才被显示，用旧的 _last 会算出好几秒的一大步
        self._last = perf_counter()

    def closeEvent(self, event) -> None:
        # 还没打完就来关窗 —— 先问一句，别让玩家白丢一局。
        # 三种情况不拦：已经结算过（over）、程序自己在拆窗口（_force_close）、
        # 暂停态（窗口本来就藏着，走到这儿多半是 main.py 在换游戏）。
        if not self.over and not self._force_close and not self._suspended:
            event.ignore()
            self.ask_exit()
            return
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
BG_RUNNER = "bg_runner"       # 跑一跑（黄昏跑道）
BG_2048 = "bg_2048"           # 狗粮 2048（暖色桌面）


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
