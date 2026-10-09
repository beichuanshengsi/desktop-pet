"""桌宠主窗口。

这里有桌面宠物的全部"窗口层"技巧，也是整份代码里唯一需要和操作系统
窗口管理器打交道的地方：

* ``FramelessWindowHint`` 去掉标题栏
* ``WA_TranslucentBackground`` 让 PNG 的 alpha 通道真正生效
* ``WindowStaysOnTopHint`` 常驻最上层
* ``Tool`` 让窗口不出现在任务栏和 Alt+Tab 列表里
* ``WindowDoesNotAcceptFocus`` + ``WA_ShowWithoutActivating`` 保证不抢焦点
  —— 这是唯一的硬约束：宠物绝不能打断用户正在做的事。

注意第 2 条必须配合 paintEvent 里的自绘；只设属性而不用带 alpha 的贴图，
窗口会是一块不透明的黑/白方块。

这一层还负责把四样**每帧都要推一把**的东西串起来：

* 行为状态机（``behavior.Brain``）—— 决定它想做什么
* 物理（``physics.Motion``）—— 决定它真的去了哪
* 养成状态（``vitals.Vitals``）—— 三条随时间变的数，窗口喂它、也读它
* 番茄钟（``pomodoro.Pomodoro``）—— 到点由它喊一声

这四样彼此都不认识：Brain 不认识坐标，Motion 不认识行为，Vitals 不认识窗口，
Pomodoro 不认识 Qt。**唯一的连接点就是这里**。所以这一层只做"喂事实、读结果"，
不往里塞业务判定 —— 一旦判定散进去，那几样就都没法单独测了。

背包（``bag.Bag``）也挂在这里，但它的角色不一样：它不是"每帧推一把"的东西，
而是**用户操作的账本**。`buy()` 扣钱入库、`use_item()` 出库生效 ——
这两个动作是改数值的唯一入口，和 Vitals 一样属于"数据"，不属于界面。

**"要跟用户说句话"这件事也必须从这里出去**：窗口拿不到托盘，
所以它只 ``notify.emit()``，由 ``main.py`` 决定是用气泡还是别的什么。
跟 ``pomodoro_done`` / ``request_quit`` 一个路子 —— 谁有出口谁负责喊。
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QWidget

from . import facing as facinglib
from . import menu as menulib
from . import uitheme
from .album_panel import AlbumPanel
from .anim import Animator
from .assets import AssetBank
from .bag import Bag
from .behavior import NAP_MIN_SECONDS, Brain, FPS, State
from .cards import Album, Pull, Trade
from .config import Config, hours_since, now_stamp, today_stamp
from .panel import BagPanel
from .paths import pet_asset_dir
from .physics import (FLING_RESTITUTION, Motion, VelocitySampler, clamp_fling)
from .pomodoro import Pomodoro, describe as describe_span
from .vitals import ENERGY_REST_PER_MIN, NAP_BOOST, RESTED_AT, Vitals
from .wheel_dialog import DurationDialog

BASE_SIZE = 128          # 贴图逻辑边长
TICK_MS = 33             # 约 30 FPS：足够平滑，又不会为一只挂件烧 CPU
HOP_SPEED = 430.0        # 点击时向上弹的初速度
ACTION_COOLDOWN = 0.35   # 同一个互动动作的连点保护，避免动画被反复打断

#: 番茄钟到点时额外往上蹦这一下（比点击那下高，隔着屏幕也能看见）
RING_HOP_SPEED = 520.0

# 这里曾经有个 ``BUBBLE_LINGER_MS``（划过气泡消失前停留的毫秒数）。
# v2.2.0 把"鼠标划过就弹状态卡片"整个删掉了，理由写在 ``pet/panel.py``
# 开头的"状态显示的三次收缩"里 —— 一句话：桌宠常驻桌面，鼠标划过它
# 是最高频的意外动作，每次都弹一个窗口就不是"看得见"而是打扰了。
# 要恢复的话别只把类加回来，先想清楚"多久弹一次算打扰"。


@dataclass(frozen=True)
class FeedPlan:
    """点一下「喂一口」会发生什么。

    ``PetWindow.feed()`` 和菜单那一行（``menu.feed_text``）读的都是它 ——
    不共用一份计划的话，就会出现"菜单上写着今天免费、点下去却扣了肉干"
    这类各说各话，而这两处恰好是用户唯一能看见"要不要花钱"的地方。
    """

    free: bool                              #: 走今天那份免费额度（不消耗东西）
    item: menulib.ShopItem | None = None    #: 要消耗的商品（免费时为 ``None``）
    left: int = 0                           #: 那样东西吃掉之后还剩几个


@dataclass(frozen=True)
class NapPlan:
    """点一下「去睡一会儿」会发生什么 —— 和 ``FeedPlan`` 同一个路数。

    ``PetWindow.nap()`` 和菜单那一行（``menu.nap_text``）读的是同一份计划。
    分两处各判一遍的话，会出现"菜单写着它已经睡着、点下去又把它叫起来"
    这种自相矛盾，而这一行字正是用户唯一能看见"点下去会怎样"的地方。
    """

    ready: bool                             #: 现在能不能叫它睡
    why: str = ""                           #: ``ready=False`` 时的一句原因
    minutes: float = 0.0                    #: 能睡时：大约几分钟睡饱


class PetWindow(QWidget):
    """一只住在桌面上的宠物。"""

    request_game = Signal(str)         # 参数是游戏标识，见 game.GAMES
    request_quit = Signal()
    #: 番茄钟到点。参数是**这一轮的总秒数**（时长由用户滚轮自己定，
    #: 1 秒 ~ 2 小时都有可能）—— ``main.py`` 收下它翻成人话再弹托盘气泡。
    #: 提醒本身不由本模块做：窗口连托盘都拿不到，谁有出口谁来喊。
    pomodoro_done = Signal(int)
    #: 想跟用户说一句话：``(标题, 正文)``。
    #:
    #: 用在"买了东西放进背包""道具用掉了""状态告急"这类**不需要他立刻处理、
    #: 但应该知道一声**的事上。出口在 ``main.py``（托盘气泡）。
    #: 为什么不直接弹窗：桌宠的硬约束是绝不打断用户，见模块开头。
    notify = Signal(str, str)

    def __init__(self, cfg: Config, bank: AssetBank, games=(), parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.bank = bank
        # 游戏清单由 main.py 传进来。pet 这一层不认识 game 包，
        # 菜单只管把标识发出去，谁来开窗口是主程序的事。
        self._games = tuple(games)

        self.setWindowTitle("桌宠")
        self._apply_window_flags()

        self._size = self._scaled_size()
        self.setFixedSize(self._size, self._size)

        # 行为与运动
        self.brain = Brain(auto_walk=cfg.auto_walk, speed=cfg.speed)
        self.body = Motion(w=self._size, h=self._size)
        self.anim = Animator(fps=self.brain.fps, loop=True)

        # 养成状态：从存档读回来，再按"上次退出到现在"补一次离线衰减。
        # 存档里没有 last_seen（第一次跑，或者老版本升上来的档）就是 0 小时。
        self.vitals = self._load_vitals()

        # 背包：小卖部买来的东西先存这儿。和养成状态一样，读存档、定期写回。
        self.bag = Bag(self.cfg.inventory)

        # 卡册：抽卡 / 碎片 / 装备栏。和背包一样属于"用户操作的账本"，
        # 状态直接挂在 ``cfg`` 上（理由见 ``pet/cards.py`` 开头）——
        # 于是它天然被 ``_persist`` 每 3 秒写一次，不用另铺一条同步的路。
        self.album = Album(self.cfg)

        # 番茄钟。纯计时，到点发信号。
        self.pomodoro = Pomodoro()

        # 素材原图朝哪边（-1 左 / 1 右）。读一次缓存住，绘制循环里不能读盘。
        # 同一个动作有好几套素材时，个别套的原图方向可能相反 —— 那份
        # "按套覆盖"表也在这里一次读完（见 facing.base_for）。
        self.face_base = facinglib.current()
        self.face_sets = facinglib.current_sets()

        # 一个动作可能有好几套素材，每次触发随机挑一套播（见 _pick_set）。
        # 记的是"当前正在播的套名"，随状态走：poke 播完回 idle 也不清，
        # 下次再点会被重新随机覆盖。
        # walk 也会写进来 —— 起步那一刻挑一次，整段行走不再换（见 _track_state）。
        self._sprite_set: dict[str, str] = {}
        self.rng = random.Random()
        # 上一帧的行为状态，用来捕捉"刚切进 walk"这个瞬间。
        self._last_state: State = State.IDLE

        # 交互状态
        self._dragging = False
        self._press_global = QPoint()
        self._drag_offset = QPoint()
        self._last_action: dict[str, float] = {}   # 每个互动动作各自的连点冷却
        self._paused = False

        # 甩出去：拖动时采样手速，松手时交给物理
        self._fling = VelocitySampler()
        self._flung = False                        # 当前是不是"正在被甩出去"
        #: 平时的落地反弹系数。``_end_fling`` 要把它还回去 ——
        #: 记下来而不是抄一个 0.30，以后改 Motion 的默认值这里跟着走。
        self._base_restitution = self.body.restitution

        self._restore_position()
        self._sync_anim(force=True)
        self._last_tick = time.perf_counter()
        self._dirty = True

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._timer.start(TICK_MS)

        self._save_timer = QTimer(self)
        self._save_timer.timeout.connect(self._persist)
        self._save_timer.start(3000)

        # 背包面板是**用到才建**（``_panel`` 初值为 None）。理由有两个：
        # 一是没开过面板的用户不该白付一个窗口的开销；二是它要
        # ``QApplication`` 已经在跑 —— 而这个窗口在测试里是能被造出来的，
        # 构造期去 new 一个顶层窗口会让无界面测试变脆。
        self._panel: BagPanel | None = None
        #: 卡册窗口，同 ``_panel`` 的懒建规则。
        self._album_panel: AlbumPanel | None = None

        self.setCursor(Qt.CursorShape.OpenHandCursor)

    # ================================================================ 窗口

    def _apply_window_flags(self) -> None:
        """套上"桌面挂件"那一套窗口标志。

        具体那几条（无边框 / Tool / 不抢焦点 / 透明 / 置顶）写在
        ``uitheme.apply_overlay_flags`` —— 状态气泡要的是一模一样的一套，
        与其抄第二遍，不如共用一份。这里只负责把 ``cfg.topmost`` 这个**开关**
        传下去：那是本窗口自己的设置，气泡不该跟着走。
        """
        uitheme.apply_overlay_flags(self, topmost=bool(self.cfg.topmost))

    def _scaled_size(self) -> int:
        return max(48, int(round(BASE_SIZE * float(self.cfg.scale))))

    # ================================================================ 位置

    def _screen_available(self) -> QRect:
        """取宠物当前所在显示器的工作区（已排除任务栏）。"""
        center = self.frameGeometry().center()
        scr = QGuiApplication.screenAt(center) or QGuiApplication.primaryScreen()
        return scr.availableGeometry() if scr else QRect(0, 0, 1280, 720)

    def _bounds(self) -> tuple[float, float, float, float]:
        g = self._screen_available()
        return (float(g.left()), float(g.top()),
                float(g.right() + 1), float(g.bottom() + 1))

    def _restore_position(self) -> None:
        g = self._screen_available()
        x, y = self.cfg.pos_x, self.cfg.pos_y
        if x < 0 or y < 0 or not g.contains(QPoint(x + self._size // 2, y + self._size // 2)):
            x = g.right() - self._size - 60
            y = g.bottom() - self._size
        self.body.w = self.body.h = float(self._size)
        self.body.teleport(x, y)
        self.move(int(self.body.x), int(self.body.y))

    def reset_position(self) -> None:
        self.cfg.pos_x = self.cfg.pos_y = -1
        self._restore_position()
        self._dirty = True

    # ================================================================ 养成状态

    def _load_vitals(self) -> Vitals:
        """从存档读三条值，再按"上次退出到现在"补一次离线衰减。"""
        v = Vitals(self.cfg.satiety, self.cfg.mood, self.cfg.energy)
        v.clamp()
        v.offline(hours_since(self.cfg.last_seen))
        return v

    def _save_vitals(self) -> None:
        """把三条值写回存档对象（真正落盘由 ``_persist`` 统一管）。"""
        self.cfg.satiety = self.vitals.satiety
        self.cfg.mood = self.vitals.mood
        self.cfg.energy = self.vitals.energy

    def _tick_vitals(self, dt: float) -> None:
        """推进养成状态：睡着走 ``rest``（回精力），醒着走 ``awake``（掉三项）。

        **和暂停无关**：玩游戏那段时间也是真实流逝的时间，当然也要饿。

        「去睡一会儿」那一觉按 ``NAP_BOOST`` 加速，而且加速的是**整段时间**、
        不是单独把精力那一项调快 —— 于是这一觉对饱食 / 心情的总账和自然睡
        完全一样，只是压缩进 1/3 的真实时间（理由写在 ``vitals.NAP_BOOST``）。
        "这一觉是不是用户安排的"由状态机说了算（``brain.napping``），
        窗口不另记一个 flag。
        """
        if self.brain.state is State.SLEEP:
            self.vitals.rest(dt * (NAP_BOOST if self.brain.napping else 1.0))
        else:
            self.vitals.awake(dt)

    def _steer_if_hungry(self) -> None:
        """饿了就走到屏幕中间、面向用户。

        只在**闲着的两个状态**（IDLE / WALK）才动身：它正被拎着、正掉着、
        正演动作或者正在睡觉，都不该被这个打断 —— 尤其睡着的时候，
        半夜饿醒爬起来走两步太出戏了。

        目标喂给 Brain 的是**宠物中心要到的位置**，不是左上角坐标：
        Brain 那边比的是 ``seek_x - 当前位置``，两边得用同一把尺子。
        """
        if not self.vitals.hungry:
            if self.brain.seeking:
                self.brain.stop_seek()
            return

        if self.brain.state not in (State.IDLE, State.WALK):
            return

        g = self._screen_available()
        if not self.brain.seeking:
            self.brain.start_seek(float(g.center().x()))
        self.brain.update_seek(self.body.x + self._size / 2.0)

    # ================================================================ 番茄钟

    def start_pomodoro(self, seconds: int) -> None:
        """开始一轮专注（**参数是秒**）。到点会发 ``pomodoro_done``。

        时长由用户在滚轮上自己滚，所以这里收的是秒不是分钟 —— 滚轮能滚出
        "45 秒"，用分钟当单位的话它会被四舍五入成 1 分钟。
        """
        self.pomodoro.start(seconds)

    def pick_pomodoro(self) -> None:
        """弹滚轮对话框选时长，选完直接开始。

        **选中的值要记回存档**（``cfg.pomodoro_seconds``）：下次再点开对话框
        就停在上次那个位置，不用从 25 分钟重新滚一遍。这是滚轮选择器比
        固定档位好用的前提 —— 常用时长各不相同，"记住我上次选的"比
        "给我一排预设"更贴近真实用法。

        取消（reject）时什么都不做：用户点了取消就是想反悔，这时候
        顺手开一轮倒计时是最讨厌的一种"自作聪明"。
        """
        dlg = DurationDialog(self.cfg.pomodoro_seconds)
        dlg.center_on(self._screen_available())
        if dlg.exec() != DurationDialog.DialogCode.Accepted:
            return
        secs = dlg.selected_seconds()
        self.cfg.pomodoro_seconds = float(secs)
        self.cfg.save()
        self.start_pomodoro(secs)
        self.notify.emit("番茄钟", f"开始专注 {describe_span(secs)}")

    def stop_pomodoro(self) -> None:
        self.pomodoro.stop()

    def _tick_pomodoro(self, dt: float) -> None:
        if self.pomodoro.tick(dt):
            self._ring()

    def _ring(self) -> None:
        """到点了：发信号 + 现场蹦一下。

        **信号先发**：托盘气泡是主要提醒（用户可能正在别的窗口里，
        根本看不见桌面右下角）。蹦这一下是给"正好看得到"的情况补的。

        信号带的是**本轮总秒数**，翻成人话（"25 分钟" / "45 秒"）由
        ``main.py`` 调 ``pomodoro.describe`` 做 —— 说法只有那一份实现。
        """
        self.pomodoro_done.emit(int(round(self.pomodoro.total_seconds)))
        if self.brain.state in (State.DRAG, State.FALL):
            return
        self._begin_action(State.POKE)
        self.brain.poke(seconds=self._oneshot_seconds(State.POKE))
        self._sync_anim(True)
        if self.body.on_ground and self.cfg.gravity:
            self.body.throw(0.0, -RING_HOP_SPEED)
        # 它可能是被藏在托盘里的，得先叫出来
        self.show()
        self.raise_()

    # ================================================================ 背包

    def buy(self, key: str) -> None:
        """买一样东西：扣金币、**放进背包**。

        **这里是"钱够不够"的唯一权威判定**。菜单上那个灰只是提示 ——
        菜单搭好到用户点下去之间，后台可能刚结算完一局游戏把金币变了，
        所以不足时要静默返回，而不是信任菜单的判断。

        从"买下立刻生效"改成"买下入库"，是为了让用户能**挑时候用**：
        饱食已经 90 还想买肉干、或者想打三局游戏一次买齐三种 ——
        旧做法下这两件事都做不到（买了就浪费）。真正生效的入口是 ``use_item()``。
        """
        item = menulib.shop_item(key)
        if item is None or self.cfg.coins < item.price:
            return

        self.cfg.coins -= item.price
        n = self.bag.add(key)
        self._save_bag()
        self.cfg.save()
        # 告诉一声：菜单一收起就看不见了，不提示的话用户不确定买没买上
        self.notify.emit("已放进背包", f"{item.label} ×{n}（共 {self.bag.total()} 件）")

    def use_item(self, key: str) -> bool:
        """用掉一个道具：出库、抬数值、演对应动作。返回有没有用成。

        **顺序很讲究**：先 ``bag.take()``（东西不够它会整笔失败），成功了才动
        数值。反过来的话，"点一下空背包里的道具"就成了一条白拿数值的漏洞 ——
        而这种漏洞只在用户手快连点两下的时候才暴露，最难发现。
        """
        item = menulib.shop_item(key)
        if item is None or not self.bag.take(key):
            return False

        for field, amount in item.gains:
            self.vitals.boost(field, amount)
        self._save_vitals()
        self._save_bag()
        self.cfg.save()
        self._play_gift(item.action)
        self.notify.emit("用掉一个", f"{item.label}（还剩 {self.bag.count(key)}）")
        return True

    def _save_bag(self) -> None:
        """把背包写回存档对象（真正落盘由 ``_persist`` 统一管）。"""
        self.cfg.inventory = self.bag.to_dict()

    def _play_gift(self, action: str) -> None:
        """**用掉东西**当场的反应 —— 演它对应的那个动作（吃的演 feed、玩的演 poke）。

        动作名来自 ``menu.SHOP`` 表，认不出来就当没这回事（不崩）。

        注意它现在挂在"用"而不是"买"上：买下来的那一刻狗不该有反应
        （东西还在背包里，还没吃到嘴里）。这一点比看起来重要 ——
        否则用户会以为买下就等于喂过了。
        """
        try:
            state = State(action)
        except ValueError:
            return
        if state not in (State.POKE, State.FEED):
            return
        if self.brain.state in (State.DRAG, State.FALL):
            return

        self._begin_action(state)
        if state is State.FEED:
            self.brain.feed(seconds=self._oneshot_seconds(state))
        else:
            self.brain.poke(seconds=self._oneshot_seconds(state))
        self._sync_anim(True)

    # ================================================================ 背包面板

    def open_panel(self) -> None:
        """打开（或叫回）背包面板。

        **懒建**：没点过这个菜单项的用户不该多一个窗口。建好之后留着复用 ——
        每次点都重建的话，用户挪过位置的面板会跳回屏幕中间。
        """
        if self._panel is None:
            self._panel = BagPanel(self, self.cfg)
        self._panel.center_on(self._screen_available())
        self._panel.show()
        self._panel.raise_()
        self._panel.activateWindow()

    def leaveEvent(self, event) -> None:
        """鼠标离开时顺手把面板上的数字刷一遍。

        面板可能正开着，而用户刚喂过它。面板自己有 1 秒的定时器兜底，
        这一下只是为了让他看到"喂完立刻就变"。

        **这里以前还要管那个"划过就弹的状态卡片"**（进要停表、出要起表）。
        v2.2.0 把卡片删了，理由见 ``pet/panel.py`` 开头的"状态显示的三次收缩"。
        于是 ``enterEvent`` 整个不再需要覆盖 —— 鼠标划过桌宠现在什么都不发生，
        状态值只在右键菜单（和托盘 tooltip）里看。
        """
        if self._panel is not None and self._panel.isVisible():
            self._panel.refresh()
        if self._album_panel is not None and self._album_panel.isVisible():
            self._album_panel.refresh()
        super().leaveEvent(event)

    # ================================================================ 卡册

    def open_album(self) -> None:
        """打开（或叫回）卡册窗口。懒建、复用 —— 理由同 ``open_panel``。"""
        self.album.refresh_week()
        if self._album_panel is None:
            self._album_panel = AlbumPanel(self, self.cfg)
        self._album_panel.center_on(self._screen_available())
        self._album_panel.show()
        self._album_panel.raise_()
        self._album_panel.activateWindow()
        self._album_panel.refresh()

    def pull_card(self) -> Pull | None:
        """抽一次卡。金币够不够、发哪张卡全在 ``Album.pull`` 里判定，
        面板只转发 —— 和 ``buy`` / ``use_item`` 是同一条规矩。

        抽完**立刻落盘**：桌宠是被任务管理器结束掉也不奇怪的常驻程序，
        抽到的卡要是等 3 秒的定时器才写，中间被关掉就白抽了。
        """
        self.album.refresh_week()
        pull = self.album.pull()
        if pull is not None:
            self.cfg.save()
        return pull

    def dissolve_card(self, cid: str) -> tuple[bool, int, str]:
        ok, amount, kind = self.album.dissolve(cid)
        if ok:
            self.cfg.save()
        return ok, amount, kind

    def exchange_card(self, tier: str) -> Trade:
        self.album.refresh_week()
        trade = self.album.exchange(tier)
        if trade.ok:
            self.cfg.save()
        return trade

    def convert_low(self, times: int = 1) -> int:
        self.album.refresh_week()
        got = self.album.convert_low(times)
        if got:
            self.cfg.save()
        return got

    def equip_card(self, cid: str) -> bool:
        ok = self.album.equip(cid)
        if ok:
            self.cfg.save()
        return ok

    def unequip_card(self, cid: str) -> bool:
        ok = self.album.unequip(cid)
        if ok:
            self.cfg.save()
        return ok

    def _persist(self) -> None:
        """定期落盘：位置 + 养成状态 + 背包。

        以前只在"位置变了"时写，图个少写盘。但养成状态是**每帧都在变**的
        （一直在衰减），继续按"变了才写"等于每 3 秒必写一次 —— 索性就每 3 秒
        写一次，不再比来比去。一个几百字节的 JSON，这点代价可以忽略。

        背包也一起写：它变化频率低（用户点一下才变），但**不能只在退出时写** ——
        桌宠是被任务管理器结束掉也不奇怪的常驻程序，那种退出走不到
        ``closeEvent``，最后买的几样东西就没了。
        """
        self.cfg.pos_x, self.cfg.pos_y = int(self.body.x), int(self.body.y)
        self._save_vitals()
        self._save_bag()
        self.cfg.save()

    # ================================================================ 主循环

    def _tick(self) -> None:
        now = time.perf_counter()
        dt = now - self._last_tick
        self._last_tick = now
        if dt <= 0:
            return
        self._advance(min(dt, 0.1))

    def _advance(self, dt: float) -> None:
        """推进 dt 秒的逻辑。与计时分离，方便测试直接喂固定步长。

        **养成状态和番茄钟放在最前面，且不受暂停影响**：拖拽中、小游戏暂停中、
        甚至窗口被藏进托盘，时间一样在走 —— 那些都只是"它没动"，不是"时间停了"。
        只有一件事会冻结它们，就是程序关掉（那时走的是离线衰减）。
        """
        self._tick_vitals(dt)
        self._tick_pomodoro(dt)

        if self._dragging:
            # 拖拽期间由鼠标事件直接决定位置，物理让位
            self._sync_from_window()
            moved = self.anim.update(dt)
            if moved:
                self.update()
            return

        if self._paused:
            self.body.stop()
            return

        # 先决定"要不要动身去找主人"，再让状态机推进 ——
        # 反过来写的话，这一帧切进来的 seek 要等下一帧才生效，会顿一下。
        self._steer_if_hungry()

        self.brain.update(dt, on_ground=self.body.on_ground,
                          tired=self.vitals.tired, rested=self.vitals.rested)
        self._track_state()

        want_vx = self.brain.wanted_vx(on_ground=self.body.on_ground)
        if want_vx:
            self.body.vx = want_vx
        elif self.body.on_ground:
            self.body.vx = 0.0

        # 只认设置本身。以前这里写的是 ``bool(cfg.gravity) or not on_ground``，
        # 于是"脚不沾地"就再补一次重力 —— 悬浮状态恰好永远脚不沾地，
        # 那个 or 把开关整个架空了（勾不勾都往下掉）。
        ev = self.body.update(dt, self._bounds(),
                              use_gravity=bool(self.cfg.gravity))

        # 被甩出去的那一程落地了，把参数还回去。不还的话，它接下来自己走路
        # 撞到屏幕边会弹一下 —— 弹跳是小球的行为，狗走路应该走到边就停。
        if self._flung and ev["landed"]:
            self._end_fling()

        if ev["edge"] and self.brain.walking:
            self.brain.turn()

        moved = self.anim.update(dt)
        self._sync_anim()

        new_pos = (round(self.body.x), round(self.body.y))
        if moved or new_pos != (self.x(), self.y()):
            self.move(*new_pos)
            self.update()

    def _sync_from_window(self) -> None:
        self.body.x = float(self.x())
        self.body.y = float(self.y())
        self.body.stop()

    # ================================================================ 甩出去

    def _start_fling(self, vx: float, vy: float) -> None:
        """松手那一刻把手速交给物理。

        这是 ``Motion.throw()`` / ``edge_bounce`` / ``restitution`` 第一次真正被
        桌宠用上 —— 它们从写小游戏那天就在，只是桌宠这边一直没有"速度"可给。

        **只在开了「重力下坠」时真甩**：没有重力就没有落地事件，它飞出去会永远
        悬在半空 —— 而 FALL 只认"落地"这一个出口，结果是卡在屏幕外演下坠，
        只能靠拖回来救。所以宁可"没重力时甩不动"，也不要留一个能把自己弄丢的操作。
        """
        if not self.cfg.gravity:
            return
        self.body.edge_bounce = True          # 撞左右墙反弹，而不是贴住不动
        self.body.restitution = FLING_RESTITUTION
        self._flung = True
        self.body.throw(vx, vy)

    def _end_fling(self) -> None:
        """落地了，把"被甩出去"专用的参数还回平时的样子。

        ``edge_bounce`` 必须还回去：它开着的时候，狗自己走路撞到屏幕边会反弹，
        那是小球的行为。桌宠走路应该是走到边上就停下转身。
        """
        self._flung = False
        self.body.edge_bounce = False
        self.body.restitution = self._base_restitution

    def _current_set(self) -> str | None:
        """当前状态正在播的是哪一套素材。``None`` = 用默认套。

        idle 永远不在 ``_sprite_set`` 里，于是返回 None、走默认套 ——
        它要在状态里停好几秒，中途换套会让画面突然跳一下。
        walk 则是**只在起步那一刻**被写进去（见 ``_track_state``），
        整段行走保持同一套，所以同样不会中途跳。
        """
        return self._sprite_set.get(self.brain.sprite)

    def _pick_set(self, state: State) -> str | None:
        """给这次动作随机挑一套素材。

        只有一套（或压根没分套）时返回 None，即"就这一套，别挑"。
        ``self.rng`` 做成实例属性是为了让测试能塞固定种子，把随机变成可复现。

        挑的时候**排除上一次刚用过的那套**：纯随机的三套里有 1/3 的概率
        连着两次一模一样，玩家会觉得"怎么没变"。排除之后两套素材就是
        完美轮换、三套也不会连着重复。
        """
        names = self.bank.set_names(state.value)
        if not names:
            return None
        last = self._sprite_set.get(state.value)
        pool = [n for n in names if n != last] or names
        return self.rng.choice(pool)

    def _begin_action(self, state: State) -> None:
        """进入动作前先定下这次用哪套素材（一次性动作 / 拖拽 / walk 起步）。"""
        self._sprite_set[state.value] = self._pick_set(state) or ""

    def _track_state(self) -> None:
        """捕捉"状态刚切换"那一帧，给需要挑套的循环状态定下素材。

        一次性动作和拖拽都有自己的入口可以挂钩（``poke`` / ``feed`` /
        ``mouseMoveEvent``），唯独 walk 是行为状态机自己溜达进去的 ——
        没有任何外部事件能告诉窗口"要开始走了"，只能在这里看状态变没变。

        挑套只发生在**进入 walk 的那一帧**，整段行走都用同一套：
        两套素材帧数不同，中途换会接不上。而每次重新起步都会重新挑，
        于是两套就是完美轮换 —— 走这一趟和下一趟长得不一样。
        """
        state = self.brain.state
        if state is self._last_state:
            return
        self._last_state = state
        if state is State.WALK:
            self._begin_action(State.WALK)

    def _sync_anim(self, force: bool = False) -> None:
        """按当前状态切换帧序列。状态没变时不会打断播放进度。

        ``force`` 表示"刚刚换了个动作"，这时必须立刻要求重绘：主循环只在
        "这一帧动了 / 窗口挪了"的时候才 update()，而一次性动作是 10~12.5 fps，
        等它自己动到下一帧要 80~100ms —— 点一下等半拍才看见狗有反应，手感很差。
        """
        sprite = self.brain.sprite
        count = max(1, self.bank.count(sprite, self._current_set()))
        self.anim.play(count, fps=self.brain.fps, loop=True, restart=force)
        if force:
            self.update()

    # ================================================================ 绘制

    def paintEvent(self, _event) -> None:
        cur_set = self._current_set()
        pm = self.bank.frame(self.brain.sprite, self.anim.index, self._size,
                             cur_set)
        if pm is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        # 走的方向和素材画的方向不一致才翻——素材本身朝哪边，看一眼
        # custom_pet/facing.json（可以按套分别声明），不靠猜（猜错就是倒着走）。
        base = facinglib.base_for(self.face_base, self.face_sets,
                                  self.brain.sprite, cur_set)
        if facinglib.should_mirror(self.brain.facing, base):
            painter.translate(self._size, 0)
            painter.scale(-1, 1)
        painter.drawPixmap(0, 0, pm)

    # ================================================================ 鼠标

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_global = event.globalPosition().toPoint()
            self._drag_offset = self._press_global - self.frameGeometry().topLeft()
            self._dragging = False
            # 上一次拖拽留下的轨迹必须清掉，否则"按住不动三秒再松手"
            # 会拿三秒前的点去算速度，算出个莫名其妙的值
            self._fling.clear()

        elif event.button() == Qt.MouseButton.RightButton:
            self._show_menu(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event) -> None:
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        gp = event.globalPosition().toPoint()
        if not self._dragging:
            if (gp - self._press_global).manhattanLength() <= 6:
                return
            self._dragging = True
            self._begin_action(State.DRAG)      # 每次拎起来随机换一种挣扎
            self.brain.drag_start()
            self._sync_anim(True)
            self.grabMouse()                    # 必须抓鼠标，否则拖出窗口就断连
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

        self.move(gp - self._drag_offset)
        # 顺手记一笔手速，松手时用来决定"这一下甩多快"（见 velocity_sampler）
        self._fling.add(gp.x(), gp.y())

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self.setCursor(Qt.CursorShape.OpenHandCursor)

        if self._dragging:
            self._dragging = False
            self.releaseMouse()

            # 手速先算出来：它来自采样器记的鼠标全局坐标，跟窗口位置无关，
            # 但摆在这里读起来最顺（下一步就把窗口位置和物理对齐了）
            vx, vy = clamp_fling(*self._fling.velocity())
            self._fling.clear()

            self._sync_from_window()
            self.body.on_ground = False
            # 关掉重力时不要进 FALL：那状态要靠"落地"结束，而它永远落不了地
            self.brain.drag_end(gravity=bool(self.cfg.gravity))
            if vx or vy:
                self._start_fling(vx, vy)       # 这两个数非 0 = 这一下是"甩"
            self._sync_anim(True)
        else:
            self.poke()

    # ================================================================ 互动

    def poke(self) -> None:
        """逗它玩：做个动作，顺便真的蹦起来。每次随机挑一套演法。

        顺带补一点心情 —— 在这之前 ``play_count`` 加一就完事了，
        狗一点变化都没有。现在它是真的开心了。
        """
        if not self._action_ready("poke"):
            return
        self._begin_action(State.POKE)
        self.brain.poke(seconds=self._oneshot_seconds(State.POKE))
        self._sync_anim(True)
        # 起跳那一下只在有重力时给：没重力就没有回落，它会一路飘到天花板挂着
        if self.body.on_ground and self.cfg.gravity:
            self.body.throw(0.0, -HOP_SPEED)
        self.cfg.play_count += 1
        self.vitals.play()

    def feed_plan(self) -> FeedPlan | None:
        """这次「喂一口」会发生什么。返回 ``None`` = 喂不了。

        两条路按"今天那份免费额度还在不在"分：

        * **今天还没喂过** → 免费，不看背包（``free=True``）。
          这一份是给"一个金币都没有"的时候兜底的，一天一次。
        * **今天已经喂过** → 吃背包里第一样吃的（``free=False`` + ``item``）。
          没有吃的就返回 ``None``，菜单那一行会跟着灰掉。

        时间只认 ``config.today_stamp()``（本地日期）—— 跨天自动恢复，
        不需要任何定时器：这个方法每次开菜单都现算一遍。
        """
        if self.cfg.free_feed_day != today_stamp():
            return FeedPlan(free=True)

        food = self.bag.first_food()
        if food is None:
            return None
        item, n = food
        return FeedPlan(free=False, item=item, left=n - 1)

    def feed(self) -> None:
        """喂一口：优先用今天那份免费额度，用完了就吃背包里的东西。

        这里**不**像逗它玩那样把窗口弹起来 —— 素材里狗是坐着低头吃饭的，
        整个窗口跟着蹦一下反而出戏，动作本身就够表达了。

        **为什么要认识背包**：在这之前这里是白送的 —— 饱食 +26、冷却 0.35 秒，
        从饿到饱只要一秒半、一个金币不花，于是小卖部就成了摆设。而饱食偏偏是
        三条值里**唯一没有免费回补渠道的**（心情睡觉会回、精力只有睡觉能给），
        这条后门一开，"买"这件事整个失去意义。

        现在留了**每天一次**的免费额度：开局一个金币都没有时也能喂它一口，
        想喂第二口就得先有吃的。
        """
        plan = self.feed_plan()
        if plan is None:
            # 菜单上那一行是灰的，正常点不到这儿。但和 buy() 同一个道理：
            # 菜单的判断只是提示，真正的判定必须在动作里，否则"菜单搭好到
            # 点下去之间状态变了"就成了一条白拿数值的缝。
            self.notify.emit("喂不了", "今天的免费用完了，背包里也没吃的")
            return
        if not self._action_ready("feed"):
            return

        if not plan.free and plan.item is not None:
            # 有吃的就吃 —— 走和「背包」子菜单**完全相同**的那条路
            # （扣一个、加那样东西自己的效果、演对应动作、发通知），
            # 别在这里再写一遍那套顺序
            self.use_item(plan.item.key)
            return

        self.cfg.free_feed_day = today_stamp()
        self.cfg.feed_count += 1
        self.vitals.feed()
        self._save_vitals()
        self.cfg.save()
        self._begin_action(State.FEED)
        self.brain.feed(seconds=self._oneshot_seconds(State.FEED))
        self._sync_anim(True)
        self.notify.emit("喂饱了", "今天这份免费，下次得从背包里拿")

    def nap_plan(self) -> NapPlan:
        """现在叫它睡，会发生什么。菜单那一行和 ``nap()`` 读的是同一份。

        **三种"点不了"各给一句人话** —— 菜单上灰掉并写明原因，比点下去没反应
        强，跟「喂一口」那一行同一个道理：

        * 已经在睡 → "它已经睡着了"；
        * 正被拎着 / 正在掉 → "先把它放到地上"，半空趴下很怪
          （自动睡也不在这两个状态里发生）；
        * 精力还足（``rested``）→ "它不困"，硬睡的话趴下几秒就够到醒来那条线。

        能睡时算一个"睡饱大约几分钟"：按 ``NAP_BOOST`` 加速后的速率折算，
        不必等它睡完才知道。**最短时长也要算进去** —— 精力快满的时候，真正
        决定它躺多久的是 ``NAP_MIN_SECONDS``（回复早已顶到上限），不是速率。
        """
        if self.brain.state is State.SLEEP:
            return NapPlan(False, "它已经睡着了")
        if self.brain.state in (State.DRAG, State.FALL):
            return NapPlan(False, "先把它放到地上")
        if self.vitals.rested:
            return NapPlan(False, f"它不困（精力 {self.vitals.energy:.0f}）")

        per_min = ENERGY_REST_PER_MIN * NAP_BOOST
        to_rested = max(0.0, RESTED_AT - self.vitals.energy) / per_min
        return NapPlan(True, "", max(to_rested, NAP_MIN_SECONDS / 60.0))

    def nap(self) -> None:
        """「去睡一会儿」：用户主动安排它睡一觉。

        判定走 ``nap_plan()`` —— 和菜单那一行**同一份**。真正让它睡下去的是
        ``Brain.sleep_now()``；三条值在睡的过程中由 ``_tick_vitals`` 推进、
        由 ``_persist`` 统一落盘，所以这里不碰存档，也不用等它睡醒才存。
        """
        plan = self.nap_plan()
        if not plan.ready:
            # 菜单那一行是灰的，正常点不到这儿。但判定必须在动作里再做一次
            # （和 feed / buy 同一个道理）：菜单搭好到点下去之间状态是会变的。
            self.notify.emit("先别叫它睡", plan.why)
            return
        if not self._action_ready("nap"):
            return
        self.brain.sleep_now()
        self._sync_anim(True)
        self.notify.emit("睡着了", f"睡饱大约 {plan.minutes:.0f} 分钟，到点它自己会醒")

    def _action_ready(self, key: str) -> bool:
        """连点保护：太密就丢掉这次，免得动作被反复打断。

        冷却按动作**分开**记：刚逗完立刻想喂一口是合理操作，不该被
        逗它玩的冷却一并吞掉；真正要挡的是"同一个动作被连点打断"。
        """
        now = time.perf_counter()
        if now - self._last_action.get(key, 0.0) < ACTION_COOLDOWN:
            return False
        self._last_action[key] = now
        return True

    def _oneshot_seconds(self, state: State) -> float:
        """这套素材把一个一次性动作播完要多久：帧数 ÷ 帧率。

        不写死秒数，是为了"换了素材动作长度自动跟上" —— 素材从 20 帧换成
        40 帧，动作就该演两倍时长，而不是演一半被掐断。
        这里必须按**本次随机选中的那一套**数帧：几套素材帧数不一样长，
        用别套的帧数算时长，短的那套会被掐断、长的那套会空转。
        """
        sprite = state.value
        frames = max(1, self.bank.count(sprite, self._sprite_set.get(sprite)))
        return frames / FPS[state]

    # ================================================================ 菜单

    def _show_menu(self, global_pos: QPoint) -> None:
        self._build_menu().exec(global_pos)

    def _build_menu(self) -> QMenu:
        """搭出右键菜单。

        拆成独立方法是为了能测：``exec()`` 会阻塞，测试里没法调 ``_show_menu``，
        但可以直接拿这个 QMenu 检查结构、触发 action。

        和托盘菜单共用的那几块（状态行 / 互动动作 / 小卖部 / 番茄钟 / 游戏子菜单 /
        三个开关）都走 ``pet/menu.py``，**不在这里重写一遍** —— 加一样商品
        只改那份登记表。这里只放"只有右键菜单才有"的条目。

        第一行是状态行而且不可点：菜单一拉出来就先看见"它饿没饿、手上有多少钱"，
        不用再点进二级菜单。
        """
        menu = QMenu(self)

        menulib.add_vitals(menu, self.vitals, self.cfg)
        menu.addSeparator()
        # 顶部一排装备徽章 + 卡册入口。卡池缺失时这一块整个不显示
        # （见 ``menu.add_album``）—— 留一个点了没反应的入口只会让人困惑。
        menulib.add_album(menu, self, self.cfg)
        menulib.add_interactions(menu, self)
        menulib.add_shop(menu, self, self.cfg)
        menulib.add_bag(menu, self, self.cfg)
        menulib.add_pomodoro(menu, self)
        menulib.add_game_menu(menu, self._games, self.request_game.emit)
        menu.addSeparator()
        menulib.add_toggles(menu, self.cfg, self)

        menu.addSeparator()
        # 一层就能点到。名字里不再带"状态"：状态值现在只在菜单顶上那两行看
        # （v2.2.0 把划过弹出的卡片删了，见 pet/panel.py 开头），
        # 这里就是背包 —— 名字和它实际管的东西对上，省得点进去找状态条。
        menu.addAction("背包面板", self.open_panel)
        menu.addAction("左右翻向（走反了改这个）", self.flip_facing)
        menu.addAction("回到默认位置", self.reset_position)
        menu.addAction("藏进托盘", self.hide)
        menu.addSeparator()
        menu.addAction("退出", self.request_quit.emit)
        return menu

    # ================================================================ 设置

    def set_auto_walk(self, on: bool) -> None:
        self.cfg.auto_walk = bool(on)
        self.brain.auto_walk = bool(on)
        self.cfg.save()

    def set_gravity(self, on: bool) -> None:
        """开关「重力下坠」。

        关掉的意思是"不下坠"：松手停在哪就悬在哪，所以顺手把竖直速度清掉；
        如果那一刻正掉到一半，也要把状态从 FALL 里拉出来，否则它会停在
        半空继续演下坠动画（FALL 只认"落地"这一个出口）。
        """
        self.cfg.gravity = bool(on)
        if not on:
            self.body.vy = 0.0
            if self.brain.state is State.FALL:
                self.brain.stop_falling()
        self.cfg.save()

    def set_topmost(self, on: bool) -> None:
        self.cfg.topmost = bool(on)
        self.cfg.save()
        visible = self.isVisible()
        self._apply_window_flags()
        if visible:
            self.show()                          # 改 flags 后必须重 show 才生效

    def set_paused(self, paused: bool) -> None:
        """小游戏进行时冻结桌面宠物的自主行为，避免两边互相打断。"""
        self._paused = bool(paused)
        if paused:
            self.body.stop()

    def apply_scale(self, scale: float) -> None:
        self.cfg.scale = max(0.5, min(2.0, float(scale)))
        self._size = self._scaled_size()
        self.setFixedSize(self._size, self._size)
        self.body.w = self.body.h = float(self._size)
        self.body.stop()
        self.cfg.save()
        self._dirty = True
        self.update()

    def flip_facing(self) -> None:
        """贴图左右翻向。

        "素材画的是哪一边"没法从代码推出来，只能靠眼睛看——所以留个
        手动开关，顺便写回 ``facing.json``，下次启动还是这个朝向。

        按套覆盖的表也要一起翻：单独声明过的那几套相对默认套是反的，
        只翻默认值会把它们翻回来，等于白改。
        """
        self.face_base = -self.face_base
        self.face_sets = {name: -value for name, value in self.face_sets.items()}
        try:
            facinglib.write(pet_asset_dir(), self.face_base,
                            sets=self.face_sets)
        except (OSError, ValueError):
            pass                    # 写不进去也不影响本次运行
        self.update()

    # ================================================================ 收尾

    def closeEvent(self, event) -> None:
        self._timer.stop()
        self._save_timer.stop()
        # 面板是没有父窗口的顶层窗口，留着会变成"桌宠退出了，
        # 屏幕上还浮着一块背包面板"。
        if self._panel is not None:
            self._panel.close()
        if self._album_panel is not None:
            self._album_panel.close()
        self.cfg.pos_x, self.cfg.pos_y = int(self.body.x), int(self.body.y)
        # 记下"我是什么时候走的" —— 下次启动靠它算离线衰减（见 _load_vitals）。
        # 位置、养成状态、背包也要顺手存一次，否则最后 3 秒的变动会白丢。
        self.cfg.last_seen = now_stamp()
        self._save_vitals()
        self._save_bag()
        self.cfg.save()
        super().closeEvent(event)
