"""行为状态机。

桌面宠物最怕的不是画得丑，而是"看不出是活的"。让一只贴图显得活的
办法不是堆 if-else，而是把行为收敛成有限个状态——每个状态对应一套
帧动画，转移条件清晰可查。

状态转移图
----------

    ┌──────────────────────── 计时到 / 随机 ────────────────────────┐
    │                                                               │
  IDLE ──计时到且掷骰通过──> WALK ──计时到──> IDLE                  │
    │                          │                                    │
    ├──点击「逗它玩」──> POKE ──播完──┐                             │
    └──菜单「喂一口」──> FEED ──播完──┴──> IDLE                     │
                                                                   
  IDLE / WALK ──按下鼠标并拖动──> DRAG ──松开──> FALL ──落地──> IDLE

  IDLE ──精力见底（``tired``）──> SLEEP ──睡饱 / 被叫醒──> IDLE
  IDLE ──菜单「去睡一会儿」（``sleep_now()``）──> SLEEP（出口同上）
  SLEEP ──点击「逗它玩」──> POKE ──播完──> IDLE（随后进入"刚醒"缓冲）

DRAG 与 FALL 一律由外部事件驱动（鼠标事件、物理落地），计时器管不到它们；
POKE 与 FEED 是短促的一次性动作，播完自动回 IDLE。

松手那一步分两种：开了「重力下坠」才进 FALL，关掉就直接回 IDLE
（``drag_end(gravity=False)``）—— 没有重力就永远等不到那个落地事件，
进了 FALL 反而会卡在半空一直演下坠。

**POKE 和 FEED 是两个独立状态**，各自对应一套贴图：逗它玩放 `poke_*.png`、
喂一口放 `feed_*.png`。它们曾经共用同一个状态（点一下蹦一下），
换素材后两个动作长得一模一样，所以拆开了。

SLEEP 与"走近"意图
------------------

SLEEP 是**唯一的持续型自主动作**（其余循环态只有 IDLE / WALK）：它由
"精力见底"这个外部事实触发、或者由用户主动叫它睡（``sleep_now()``），
由"睡饱"或"被叫醒"结束，时长不由计时器定。

**两个入口共用一套出口**：不管是累趴下还是你叫它睡，醒来的条件都是
``rested`` 或被戳（poke / feed 会把它切走）—— 不为"主动小睡"另开一条醒来
路径，否则两条路迟早各走各的。两者的差别只有两条，都在 ``sleep_now`` 里：
① 不看 ``tired``；② 有一个最短时长，免得精力本来就快满的时候趴下几秒又起来。

判定所依据的 ``tired`` / ``rested`` **不由本模块计算** —— 饱食 / 心情 / 精力那三条值
住在 ``pet/vitals.py``，本模块只接两个布尔事实，跟 ``on_ground`` 一个路数。
好处是这一层保持纯逻辑：测试直接喂 ``tired=True`` 睡下去、``rested=True`` 醒过来，
就能验证整条睡-醒链路，不需要去构造任何养成数据。

**两个事实不能合成一个**：进睡和醒来必须是两个阈值（``TIRED_AT`` / ``RESTED_AT``）。
共用一个的话，睡着后精力回升一点点就够越过它，于是"睡一下、醒一下"地抽搐。

"走到屏幕中央找主人"同理：Brain 不认识坐标，由窗口每帧把**离目标的距离**
喂进来（``update_seek``），它只负责"朝哪边走、到了没有"。
"""

from __future__ import annotations

import random
from enum import Enum


class State(str, Enum):
    """行为状态。**成员值就是贴图前缀**（``State.POKE`` ↔ ``poke_00.png``）。

    继承 ``str`` 是为了能直接当字符串用（拼路径、写进 json），
    同时也让"状态名 = 贴图前缀"这条约定是**结构上**成立的，而不是靠一张表对齐。
    """

    IDLE = "idle"
    WALK = "walk"
    DRAG = "drag"
    FALL = "fall"
    POKE = "poke"           # 逗它玩（点一下演的那套）
    FEED = "feed"           # 喂一口
    SLEEP = "sleep"         # 精力见底后趴着睡


#: 全部贴图前缀，顺序即 ``State`` 的声明顺序。
#: ``pet.assets.STATES`` 与 ``tools/prep_sticker.py`` 的白名单都从它派生。
KEYS: tuple[str, ...] = tuple(s.value for s in State)

#: 每个状态的动画帧率。两个一次性动作按素材自带的帧间隔取
#: （爱给网那两套 GIF 分别是 80ms / 100ms 一帧），播起来和素材原速一致。
FPS = {
    State.IDLE: 7.0,
    State.WALK: 11.0,
    State.DRAG: 13.0,
    State.FALL: 7.0,
    State.POKE: 12.5,
    State.FEED: 10.0,
    # 睡觉那套素材是 22 帧的"趴着 → 翻身 → 趴回来"循环。
    # 按素材原速（约 80ms 一帧）会是 12.5fps —— 眨眼就把整套翻完，
    # 看着像抽搐。这里压到 4fps：一个循环 5.5 秒，像在慢慢呼吸翻身。
    State.SLEEP: 4.0,
}

#: 一次性动作的兜底时长（秒）。真正演出时由窗口按"这套素材有几帧 ÷ 帧率"
#: 覆盖掉，保证动作恰好播完一圈；这里只是给直接调 Brain 的测试一个默认值。
ONESHOT_FALLBACK = 1.0

#: 哪些状态是"播完自动回 IDLE"的一次性动作
ONESHOT = (State.POKE, State.FEED)

#: 漫步基础速度 px/s
WALK_SPEED = 52.0

#: 走到离目标多近算"到了"（px）。太小会来回抖，太大看着没走到。
SEEK_ARRIVE_PX = 10.0

#: 被叫醒之后多久内不许再自动睡（秒）。
#:
#: 没有这个缓冲会出洋相：精力还很低，你戳它一下、它抬头演完 poke 回 IDLE，
#: 下一帧判定"还困"又立刻趴回去 —— 于是"睡 - 醒 - 睡 - 醒"地抽搐。
#: 缓冲期内它保持清醒（哪怕精力很低），缓冲一过困意才重新说了算。
WAKE_HOLD = 25.0

#: 「去睡一会儿」这一觉的最短时长（秒），见 ``Brain.sleep_now``。
#:
#: 没有它会有个洋相：精力 80 的时候点一下，回复到 82 只要几秒，于是它
#: 趴下、翻半个身、又站起来 —— 看起来像没睡。给个下限之后，不管你点的时候
#: 精力多少，它至少躺够这么久，读起来才像"睡了一觉"（睡姿那套素材一个循环
#: 5.5 秒，一分钟够翻十来次，看得出是在睡）。
NAP_MIN_SECONDS = 60.0



class Brain:
    """决定宠物此刻"想做什么"，不直接操作窗口和物理。"""

    def __init__(self, auto_walk: bool = True, speed: float = 1.0,
                 rng: random.Random | None = None):
        self.auto_walk = auto_walk
        self.speed = max(0.2, float(speed))
        self.rng = rng or random.Random()

        self.state = State.IDLE
        self.facing = 1                 # 1 面向右，-1 面向左
        #: 是否正在"走向某处"（饿了找主人）。位置由窗口喂进来，见 update_seek。
        self.seeking = False
        self.seek_x: float | None = None
        #: 被叫醒后的清醒缓冲，见 WAKE_HOLD
        self._wake_hold = 0.0
        #: 这一觉是不是用户主动安排的（见 ``sleep_now`` / ``napping``）
        self._nap = False
        #: 主动小睡的"最短时长"倒计时（秒），见 ``NAP_MIN_SECONDS``
        self._nap_min = 0.0
        self._elapsed = 0.0
        self._duration = 0.0
        self._enter(State.IDLE)

    # ------------------------------------------------------------ 内部

    def _pick_duration(self, state: State) -> float:
        r = self.rng
        if state is State.IDLE:
            return r.uniform(2.2, 6.5) / self.speed
        if state is State.WALK:
            return r.uniform(1.2, 3.2) / self.speed
        if state in ONESHOT:
            return ONESHOT_FALLBACK
        # DRAG / FALL / SLEEP 都由外部事件结束，计时器管不到：
        # 前两个等鼠标和落地，SLEEP 等"睡饱了"或"被戳醒"。
        return float("inf")

    def _enter(self, state: State) -> None:
        self.state = state
        # 离开 SLEEP 就把"这一觉是什么性质"清掉。``_nap`` 决定窗口要不要给它
        # 加速回复，留着不清的话，**下一觉**（哪怕是累趴下的自然睡）会白捡
        # 上一觉的加速 —— 那种 bug 在界面上完全看不出来，只能靠这里收干净。
        if state is not State.SLEEP:
            self._nap = False
            self._nap_min = 0.0
        self._elapsed = 0.0
        self._duration = self._pick_duration(state)

    def _cancel_seek(self) -> None:
        """丢掉"要去某处"的意图（不碰当前状态，调用方自己接着切）。"""
        self.seeking = False
        self.seek_x = None


    # ------------------------------------------------------------ 外部事件

    def drag_start(self) -> None:
        """拎起来。顺带丢掉"要去某处"的意图 —— 人都被提走了，目标没意义了。"""
        self._cancel_seek()
        self._enter(State.DRAG)

    def drag_end(self, *, gravity: bool = True) -> None:
        """松手。

        有重力 → 转入 FALL，物理落地后 ``update`` 会自动接回 IDLE；
        没重力 → 掉不下去，直接回 IDLE，也就是松手停在哪就悬在哪。
        """
        if gravity:
            self._enter(State.FALL)
        else:
            self.stop_falling()

    def stop_falling(self) -> None:
        """结束下落、回到常态。

        关掉「重力下坠」时也要走这里：那一刻可能正掉到一半，
        不然 FALL 会一直等一个永远不来的落地事件，卡在半空演下坠。
        """
        self._enter(State.IDLE)

    def sleep_now(self, *, min_seconds: float = NAP_MIN_SECONDS) -> None:
        """「去睡一会儿」：用户主动叫它睡。

        和"累了自己趴下"共用同一个 SLEEP 状态、同一套出口（睡饱 / 被戳醒）——
        只有两条不同：

        * **不看 ``tired``** —— 你说睡它就睡，哪怕它精力还剩一大截；
        * **有最短时长**（``min_seconds``）—— 免得精力本来就快满的时候趴下
          几秒就够到 ``rested`` 又站起来，看着像没睡。

        顺手做两件必须做的事：撤掉"要去某处"的意图（都要睡了，还奔着目标走
        没道理），并把 ``_wake_hold`` 清零 —— 你刚戳醒它、又立刻说"去睡"，
        后一句该说了算，否则它会因为那段缓冲期干站着不睡。
        """
        self._cancel_seek()
        self._wake_hold = 0.0
        self._nap = True
        self._nap_min = max(0.0, float(min_seconds))
        self._enter(State.SLEEP)

    @property
    def napping(self) -> bool:
        """当前这一觉是不是用户主动安排的那一次。

        窗口拿它决定要不要按 ``vitals.NAP_BOOST`` 给回复加速。**放在这里、
        而不是让窗口自己记一个 flag**：状态在哪儿，"这一觉是什么性质"就该在哪儿 ——
        窗口另记一份的话，它在睡的时候被戳醒，窗口那份就留在原地了，
        下一觉（累趴下的自然睡）会莫名其妙地加速。
        """
        return self.state is State.SLEEP and self._nap

    def poke(self, *, seconds: float | None = None) -> None:
        """逗它玩：被点了一下的一次性反馈动作。

        ``seconds`` 由窗口按"这套素材播完一圈要多久"传进来（帧数 ÷ 帧率）。
        Brain 不做 IO、数不了帧，所以让知道的调用方补一句；
        不传就用 ``ONESHOT_FALLBACK``，动作照样能播完，只是可能被掐断或空转。

        睡着时被戳会先记一笔"刚醒"（见 ``WAKE_HOLD``）：精力还低，不记的话
        你戳一下它、它抬头演完动作，回 IDLE 的下一帧又立刻趴回去 —— 鬼畜。
        """
        if self.state is State.SLEEP:
            self._wake_hold = WAKE_HOLD
        self._cancel_seek()
        self._enter_oneshot(State.POKE, seconds)

    def feed(self, *, seconds: float | None = None) -> None:
        """喂一口：菜单里投喂的一次性反馈动作。睡着时同样算叫醒。"""
        if self.state is State.SLEEP:
            self._wake_hold = WAKE_HOLD
        self._cancel_seek()
        self._enter_oneshot(State.FEED, seconds)

    def _enter_oneshot(self, state: State, seconds: float | None) -> None:
        if self.state in (State.DRAG, State.FALL):
            return                      # 拎着 / 掉着的时候不理你（SLEEP 不挡，戳一下能醒）
        self._enter(state)
        if seconds is not None:
            self._duration = max(0.05, float(seconds))

    def turn(self) -> None:
        self.facing = -self.facing

    # ------------------------------------------------------------ 走向某处

    def start_seek(self, x: float) -> None:
        """让它走向屏幕上的某个位置（"饿了走到主人面前"用）。

        Brain 不认识坐标，这里只记住**目标**；当前位置由窗口每帧通过
        ``update_seek`` 喂进来 —— 跟 ``on_ground`` 一个路数：事实从外面进，
        决策在里面出。于是这一层照样能在测试里单跑。
        """
        self.seek_x = float(x)
        self.seeking = True
        if self.state is State.IDLE:
            self._enter(State.WALK)

    def stop_seek(self) -> None:
        """放弃当前目标，停在原地。"""
        self._cancel_seek()
        if self.state is State.WALK:
            self._enter(State.IDLE)

    def update_seek(self, x: float) -> bool:
        """窗口每帧喂当前位置，返回"是否还在前往"。

        "到了"这个判断必须在这里做（窗口只提供坐标）。顺带把 ``facing`` 掰向目标
        —— 它是一路奔着目标走的，朝向当然由目标决定，不能等撞了墙才翻面。
        """
        if not self.seeking or self.seek_x is None:
            return False
        dx = self.seek_x - x
        self.facing = 1 if dx >= 0 else -1
        if abs(dx) <= SEEK_ARRIVE_PX:
            self.stop_seek()
            return False
        if self.state is State.IDLE:
            self._enter(State.WALK)
        return True


    # ------------------------------------------------------------ 每帧决策

    def update(self, dt: float, *, on_ground: bool,
               tired: bool = False, rested: bool = False) -> None:
        """推进 dt 秒。

        ``tired`` 是"精力是否见底"这个事实，由窗口从 ``pet/vitals.py`` 取来喂进来。
        省略即"不困"，所以老调用方（和测试）不改也照跑。

        ``rested`` 是"睡饱了"，**只用来决定要不要醒**。为什么不复用 ``tired``：
        进入睡眠和醒来的阈值如果是同一个数，睡着之后精力只要回升一点点就越过它，
        于是变成"睡 5 秒 → 醒两分钟 → 再睡 5 秒"的抽搐 —— 实测 36 小时里
        会抽 1000 多次。所以两个阈值必须分开（``TIRED_AT`` 进、``RESTED_AT`` 出），
        中间那一段叫滞回，是这类状态机的必需品而不是可选项。
        """
        self._wake_hold = max(0.0, self._wake_hold - dt)

        if self.state is State.DRAG:
            return

        if self.state is State.FALL:
            if on_ground:
                self._enter(State.IDLE)
            return

        if self.state is State.SLEEP:
            # 睡饱了才醒（``rested``），或者被戳（poke/feed 会把它切走）。
            # 这两个就是全部出口 —— 没有第三个，所以 SLEEP 期间不能让它闲着。
            #
            # 主动小睡（``sleep_now``）还多一道闸：最短时长没倒数完就不许醒，
            # 免得精力本来就快满的时候趴下几秒又站起来。自然睡 ``_nap_min``
            # 恒为 0，走到这里等于没这道闸，行为与老版本一致。
            self._nap_min = max(0.0, self._nap_min - dt)
            if rested and self._nap_min <= 0.0:
                self._enter(State.IDLE)
            return

        if self.seeking:
            # 正在走向目标，由 update_seek 收尾 —— 不受漫步计时影响，
            # 否则走到一半计时到点就被切回 IDLE 了。
            return

        # 困了就趴下。脚不沾地时不睡（半空中趴下很怪），刚被叫醒也不睡。
        if tired and on_ground and self._wake_hold <= 0.0:
            self._enter(State.SLEEP)
            return

        self._elapsed += dt
        if self._elapsed < self._duration:
            return

        if self.state is State.IDLE:
            if self.auto_walk and self.rng.random() < 0.72:
                self.facing = self.rng.choice((-1, 1))
                self._enter(State.WALK)
            else:
                self._enter(State.IDLE)
        else:
            self._enter(State.IDLE)


    # ------------------------------------------------------------ 输出

    @property
    def sprite(self) -> str:
        """当前该用哪一套贴图 —— 就是状态的字符串值，不再另立一张映射表。"""
        return self.state.value

    @property
    def fps(self) -> float:
        return FPS[self.state]

    def wanted_vx(self, *, on_ground: bool) -> float:
        """本帧期望的水平速度。POKE / FEED / DRAG / FALL 期间不主动移动。"""
        if self.state is State.WALK and on_ground:
            return WALK_SPEED * self.speed * self.facing
        return 0.0

    @property
    def walking(self) -> bool:
        return self.state is State.WALK

    @property
    def busy(self) -> bool:
        """是否处于玩家互动中（拖拽 / 被点击或投喂后的动作）。

        SLEEP 不算 —— 它是一段**持续**的状态（累趴下、或你叫它睡），
        不是"这一个动作还没演完"，两者的时间尺度差着两个数量级。
        """
        return self.state in (State.DRAG, *ONESHOT)
