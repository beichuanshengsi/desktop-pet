"""小游戏：跑一跑。

玩法：小狗在跑道上往前跑，障碍从右边过来 —— **空格/↑ 跳过地上长出来的墩子，
↓ 低头钻过从上垂下来的横杆**。撞上任何一样就地结束，得分是跑过的距离
（每 ``PIXELS_PER_POINT`` 像素 1 分），所以"活多久"和"跑多远"是同一件事。

和另外三款的分工
----------------
玩家在每一款里控制的东西是不一样的，这也是当初把它们摆在一起让用户选的原因：

    | 弹跳得分 | 控制**位置**     | 挪到方块底下，跳 |
    | 接狗狗   | 控制**位置**     | 左右接掉落物     |
    | 跑一跑   | 控制**时机**     | 位置固定，只有跳/低头两个动作 |
    | 2048     | 控制**方向**     | 离散回合，纯决策 |

**只听时机**意味着这款没有"练级"空间 —— 没法靠"站位更准"混过去，
只有"看准了再动"。这就是它和另外两款最本质的区别。

三条让它不无聊的设计（都是拿旧版"太无聊"的教训换的）
----------------------------------------------------
1. **跳跃缓冲 + 可变跳跃高度 + 快速下落**（下面三个常量）。
   跑酷好不好玩**全在手感**上：缓冲让"落地前那一瞬按跳"也算数，可变高度
   让"轻点一下"和"按住不放"跳出两种高度，快速下落让空中按 ↓ 立刻砸下来。
   三个都不加的话，操作就成了"到点了按一下"，和打字没区别。
2. **障碍成组出现（``PATTERNS``）而不是纯随机**。随机撒障碍的后果是
   每次都一样的心跳，玩家会发现"反正躲不掉"。成组出现才有**节奏**：
   一个高墙接一根垂下的横杆，逼你完成"跳 → 落地 → 低头"这串动作。
3. **无时限**。弹跳得分是 60 秒拼分数，这一款是"跑到撞为止"。速度在
   ``SPEED_STEP_DIST`` 像素提一档（封顶 ``MAX_SPEED``），而障碍的**时间间隔**
   从 1.55 秒一直缩到 0.55 秒且不封顶 —— 于是难度没有天花板，
   高手也迟早会在某一次 0.55 秒里手滑。**这比"设个时限到点收工"更耐玩**，
   也顺便把"挂机刷分"这条路堵上了。

为什么没做土狼时间（coyote time）
---------------------------------
当初列方案时写过它。真写的时候发现它**在这个玩法里不会有任何作用**：
土狼时间的意义是"走出平台边缘后还允许跳一下"，而这条路是**平的**，
没有边缘可走空。留着就是一段永远走过的分支、还得为它写用例。
真正起作用的是上面那三样，再加上下面这个：

* **判定盒比贴图收窄**（``HIT_PAD_X`` / ``HIT_PAD_Y``）。跑酷最劝退的体验是
  "我明明擦过去了却算撞"，所以对玩家宽容一点：视觉上狗的身体比判定盒大一圈。
  障碍那边**不收** —— 障碍要"看到什么就是什么"，收了会变成
  "我明明撞上了却没死"，那是另一种不讲理。

顺手也说明：竖直运动**没走 ``pet.physics.Motion``**。``Motion`` 是为"会撞墙、
有摩擦、会弹跳的方块"写的（球和桌宠共用），而跑酷里的竖直运动是单向的
（只受重力、只落到一条地平线），十行算术就能写完，比削 ``Motion`` 的
参数去适配它更清楚。这是本项目里第一次"该复用却不复用"，
理由写在上一句里；后面那款"弹弓打塔"才是 ``Motion`` 真正能派上用场的地方。
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import (QColor, QLinearGradient, QPainter, QPen, QPixmap)

from game.common import (BG_RUNNER, GROUND_H, GROUND_Y, HUD_H, W, H, GameWindow,
                         load_background, measure_zone_widest, paint_hud_bar,
                         ui_font, zone_spans)
from pet.assets import AssetBank

# ================================================================ 玩法数值

#: 狗的 x 固定不动（画面滚动 = 它在前进）。放在偏左：右边要留出反应空间，
#: 障碍必须"看得见一会儿"才谈得上躲。
PLAYER_X = 128
PLAYER_W = 56
PLAYER_H = 60                    # 站立高度
CROUCH_H = 34                    # 低头后的高度（要能钻过离地 40 的横杆）

#: 判定盒在视觉基础上往里收这么多（对玩家有利，见模块开头第 3 条）
HIT_PAD_X = 9
HIT_PAD_Y = 6

GRAVITY = 3000.0
JUMP_V = 1010.0                  # 顶点约 170px、滞空约 0.67s
FAST_FALL = 2600.0               # 空中按 ↓ 时额外加的下坠加速度
JUMP_BUFFER = 0.13               # 跳跃缓冲：落地前这么久按跳，落地瞬间自动起跳
JUMP_CUT = 0.42                  # 松键后保留的上升速度比例（轻点 = 小跳）

BASE_SPEED = 340.0               # 起跑速度 px/s
SPEED_STEP = 46.0                # 每提一档加多少
SPEED_STEP_DIST = 3000.0         # 每跑这么多像素提一档
MAX_SPEED = 780.0                # 速度上限

#: 两个障碍之间的**时间**间隔：起手 1.55 秒，每提一档缩短 0.13 秒，最快 0.55 秒。
#:
#: 为什么不按固定像素留间隔：那样速度一提，间隔时间就自动缩短，难度是"看不见"
#: 地陡增的。按时间给，难度曲线的每一格都是自己算好的。
GAP_SEC_START = 1.55
GAP_SEC_DECAY = 0.13
GAP_SEC_MIN = 0.55

#: 得分 = 跑过的像素 / 这个数。定它的依据是 ``COIN_PER_SCORE`` 那把尺子：
#: 认真跑一局约 3 万像素 → 600 分 → 60 金币，和另外两款"一局 20~80 金币"同量级。
PIXELS_PER_POINT = 50.0

#: 从开局到第一个障碍出现，先跑这么多像素（约两秒的热身）
FIRST_SPAWN_DIST = 760.0


# ================================================================ 障碍登记表
#
# 加一种障碍 = 在 ``KINDS`` 里加一行 + 在 ``PATTERNS`` 里排进图案。
# 绘制那边按 ``kind.key`` 取配色表，新种类不配色也有兜底色（不会崩）。


@dataclass(frozen=True)
class Kind:
    """一种障碍。"""

    key: str
    label: str          #: 给人看的名字（结算文案 / 测试打印用）
    w: int
    h: int
    #: 底边离地多高。地面障碍是 0；从上垂下来的横杆给一个正值，
    #: 表示"下方留多高的缝"—— 那个缝比站姿矮、比低头高，"只能低头过"就是靠它。
    lift: float
    #: 从屏幕顶垂下来（而不是从地面长上来）。只影响绘制，判定一律用矩形。
    hang: bool
    #: 玩家要不要低头。只是给文档和测试用的说明，判定完全由几何决定。
    crawl: bool


#: 场景高度：从 HUD 下沿到地面。垂下来的障碍要占满这一整段 ——
#: **不能只是"挂在半空的一根杆"**，否则玩家跳得够高就能从上面越过去，
#: "必须低头"这条规则就废了（跳跃顶点约 170px，一根 26px 高的横杆拦不住它）。
SCENE_TOP = HUD_H

KINDS: dict[str, Kind] = {
    "low": Kind("low", "矮墩", 32, 42, 0.0, False, False),
    # 「高墙」比矮墩**宽**（48 vs 32）而不只是高：跳跃的滞空足够越过两者，
    # 真正拉开差距的是"要在障碍到达前多久起跳"——墙越宽，容错窗口越窄。
    "tall": Kind("tall", "高墙", 48, 68, 0.0, False, False),
    "bird": Kind("bird", "垂杆", 52, GROUND_Y - SCENE_TOP - 40, 40.0, True, True),
}


@dataclass(frozen=True)
class Pattern:
    """一组一起出现的障碍。

    ``parts`` 是 ``((障碍标识, 相对第一个的横向偏移), ...)``；``dx=0`` 就是
    第一个。偏移量按像素给 —— 因为玩家感知的是"两个障碍隔多远"，
    而这个距离除以当前速度就是留给他的时间，两者是一一对应的。
    """

    parts: tuple[tuple[str, float], ...]
    min_tier: int       #: 从第几档开始出现（0 起算）
    label: str


PATTERNS: tuple[Pattern, ...] = (
    Pattern((("low", 0.0),), 0, "单个矮墩"),
    Pattern((("tall", 0.0),), 1, "高墙"),
    Pattern((("bird", 0.0),), 2, "垂下的横杆（低头）"),
    # 两个矮墩隔 150px：一次跳跃（速度 500 时水平能过 335px）能跨过两个，
    # 所以它考验的不是"跳两次"而是"别慌 —— 一次就够"。
    Pattern((("low", 0.0), ("low", 150.0)), 4, "两个矮墩，一跳过俩"),
    # 高墙 + 480px 之后一根垂杆：480px 在最高档速度下约 0.78 秒，
    # 而一次跳跃的滞空是 0.67 秒 —— **刚好够落地再低头，不宽裕**。
    # 这串"跳 → 落地 → 低头"就是这款游戏最想教会玩家的节奏。
    Pattern((("tall", 0.0), ("bird", 480.0)), 6, "先跳高墙，再低头"),
)


def pattern_width(pat: Pattern) -> float:
    """一组障碍横跨多宽（第一个的左边缘到最后一个的右边缘）。"""
    last_dx = max(dx for _k, dx in pat.parts)
    last_w = max(KINDS[k].w for k, dx in pat.parts if dx == last_dx)
    return last_dx + last_w


def pick_pattern(tier: int, rng: random.Random, avoid: Pattern | None = None) -> Pattern:
    """按档位挑一组障碍。

    **尽量不连着出同一组**：连着两次"高墙"玩家会以为游戏卡住了。
    候选只剩一个时（起手那几档）就照出，不为难自己。
    """
    pool = [p for p in PATTERNS if p.min_tier <= tier]
    if not pool:
        pool = [PATTERNS[0]]
    if avoid is not None and len(pool) > 1:
        narrowed = [p for p in pool if p is not avoid]
        if narrowed:
            pool = narrowed
    return rng.choice(pool)


def tier_for(distance: float) -> int:
    """跑到这个距离是第几档（0 起算）。不封顶 —— 封顶的是速度和间隔。"""
    return max(0, int(distance // SPEED_STEP_DIST))


def speed_for(tier: int) -> float:
    return min(MAX_SPEED, BASE_SPEED + tier * SPEED_STEP)


def gap_seconds_for(tier: int) -> float:
    return max(GAP_SEC_MIN, GAP_SEC_START - tier * GAP_SEC_DECAY)


# ================================================================ HUD 版面
#
# 规矩和弹跳得分那边一样（见 ``game/common.zone_spans`` 的说明）：
# **坐标只写在这两张表里**，绘制函数一行都不许写死。上一款就是因为坐标散在
# drawText 的实参里，两段文字叠着画了一版，逻辑测试全绿也没发现。


#: ``段名 -> (槽位起点, 槽位宽)``
HUD_ZONES: dict[str, tuple[int, int]] = {
    "score": (20, 104),          # 得分（14px 粗体）
    "best": (132, 74),           # 最高（10px）
    "tier": (216, 72),           # 第 N 档（11px 粗体）
    "speed": (606, 128),         # 当前速度（11px 粗体，右对齐）
}

#: 下一档还差多少 —— 一根进度条。**不放进 ``HUD_ZONES``**：
#: 它没有文字，不参与"两段文字会不会叠"那套断言（和弹跳得分的进度条同一处理）。
HUD_BAR = (300, 280)

HUD_FONT: dict[str, tuple[int, bool]] = {
    "score": (14, True),
    "best": (10, False),
    "tier": (11, True),
    "speed": (11, True),
}

#: 右对齐的段：速度是会变位数的那一个（340 → 780），右对齐才不会左右抖。
HUD_ALIGN_RIGHT = ("speed",)

#: 每段"最宽的那种内容"。**改了 HUD 文案就要连这里一起改。**
HUD_WIDEST: dict[str, str] = {
    "score": "得分 99999",
    "best": "最高 99999",
    "tier": "第 99 档",
    "speed": "780 px/s",
}

#: 上面那些"最宽内容"实测占多少像素。**用真实字体量的，不是估的** ——
#: 量的脚本是 ``tools/verify_v22_ui.py``（它跑在默认 windows 平台上，
#: 会把这两张表逐段对照打印）。第一版是照着弹跳得分的经验估的，
#: 结果 ``tier`` 估 52、实量 57，``speed`` 估 62、实量 65 —— 都超了。
#: 估出来的数没有意义，这张表只能是量出来的。
#:
#: 为什么不在这儿现量：冒烟测试跑的是 offscreen 平台，本机那个插件的字体库是空的，
#: ``QFontMetrics`` 量出来是方框的宽度（约真值两倍），拿它断言会误报叠字。
#: 所以这里的值是"精确值"而不是"宽松预算"：字号或文案一改，验收脚本立刻报超。
HUD_WIDEST_PX: dict[str, int] = {
    "score": 102,
    "best": 68,
    "tier": 57,
    "speed": 65,
}


def hud_zone_rect(name: str) -> tuple[int, int]:
    """一段 HUD 文字占的横向区间 ``(左, 右)``，按登记的最宽内容算。

    **纯算术，不查字体** —— 任何平台上都是同一个答案，可以直接拿去断言
    "两段有没有叠在一起"。算术在 ``game.common.zone_spans``（各游戏共用一份）。
    """
    return zone_spans(HUD_ZONES, HUD_WIDEST_PX, HUD_ALIGN_RIGHT)[name]


def measure_hud_widest() -> dict[str, int]:
    """用**当前字体**重量一遍各段最宽内容的像素宽度，和 ``HUD_WIDEST_PX`` 对照。

    **必须在真实平台上调** —— offscreen 平台在本机没有字体库，量出来是方框宽度。
    调用它的是 ``tools/verify_v22_ui.py``。
    """
    return measure_zone_widest(HUD_FONT, HUD_WIDEST)


# ================================================================ 场景对象


@dataclass
class Rock:
    """场上的一个障碍。``x`` 是左边缘，``y`` 是上边缘。"""

    kind: Kind
    x: float

    @property
    def w(self) -> int:
        return self.kind.w

    @property
    def h(self) -> int:
        return self.kind.h

    @property
    def y(self) -> float:
        """垂下来的从场景顶开始算；地上长出来的底边贴地。"""
        if self.kind.hang:
            return float(SCENE_TOP)
        return GROUND_Y - self.h

    def rect(self) -> tuple[float, float, float, float]:
        return (self.x, self.y, self.x + self.w, self.y + self.h)


# ================================================================ 小游戏窗口


class Runner(GameWindow):
    """跑一跑。

    窗口尺寸、计时器、结算浮层、关闭时发信号都在 ``GameWindow`` 里，
    这里只管本游戏的规则：速度、障碍生成、跳跃与低头。
    """

    TITLE = "桌宠小游戏 · 跑一跑"
    OVERLAY_TITLE = "撞上了"

    def __init__(self, bank: AssetBank, cfg, parent=None):
        super().__init__(bank, cfg, parent)

        self._bg = load_background(BG_RUNNER)

        # ---- 玩家
        self.feet = float(GROUND_Y)     # 脚底所在高度（竖直方向的唯一状态量）
        self.vy = 0.0
        self.on_ground = True
        self.crouching = False
        #: 跳跃缓冲还剩多少秒（> 0 表示"玩家想跳"）
        self._jump_wanted = 0.0

        # ---- 世界
        self.rocks: list[Rock] = []
        self.distance = 0.0
        self.tier = 0
        self.speed = BASE_SPEED
        self._next_spawn = FIRST_SPAWN_DIST
        self._last_pattern: Pattern | None = None
        self._flash = 0.0

        self._reset_scene(first=True)
        self.start_clock()

    # ================================================================ 关卡

    def _reset_scene(self, first: bool = False) -> None:
        """新一局的起始状态。``GameWindow._restart()`` 也走这里。

        每局**必须重掷随机源**的只有障碍图案；但 ``rng`` 是实例属性，
        测试能塞固定种子进去把随机变可复现 —— 所以这里不重设它。
        """
        self.score = 0
        self.distance = 0.0
        self.tier = 0
        self.speed = BASE_SPEED
        self.rocks.clear()
        self._next_spawn = FIRST_SPAWN_DIST
        self._last_pattern = None
        self.feet = float(GROUND_Y)
        self.vy = 0.0
        self.on_ground = True
        self.crouching = False
        self._jump_wanted = 0.0
        self._flash = 0.0

    # ------------------------------------------------------------ 速度与难度

    def _refresh_tier(self) -> None:
        """按跑过的距离更新档位与速度。每帧调一次。"""
        self.tier = tier_for(self.distance)
        self.speed = speed_for(self.tier)

    def gap_px(self) -> float:
        """当前档位下，两组障碍之间该留多少像素。"""
        return self.speed * gap_seconds_for(self.tier)

    def next_tier_ratio(self) -> float:
        """离下一档还差多少（0..1）。速度封顶之后就恒为 1。"""
        if self.speed >= MAX_SPEED:
            return 1.0
        return (self.distance % SPEED_STEP_DIST) / SPEED_STEP_DIST

    # ------------------------------------------------------------ 生成

    def _spawn_if_due(self) -> None:
        if self.distance < self._next_spawn:
            return
        pat = pick_pattern(self.tier, self.rng, self._last_pattern)
        self._last_pattern = pat

        base_x = float(W) + 24.0
        for key, dx in pat.parts:
            self.rocks.append(Rock(KINDS[key], base_x + dx))

        # 下一组的"到期距离"：从**这一组跑过去**之后，再留一段间隔。
        # 用距离而不是时间记，是因为移动本身就按距离算（x -= speed*dt），
        # 混着用会得到一个随速度漂移的间隔。
        self._next_spawn = (self.distance + pattern_width(pat)
                            + self.gap_px())

    # ================================================================ 输入

    def press_jump(self) -> None:
        """按下跳（键盘、鼠标、测试都走这里）。

        不直接起跳 —— 只记下"想跳"，由 ``_step`` 在合适的时刻兑现。
        这样"落地前一点点按"也能跳出去（跳跃缓冲），
        指令序列化成一个数之后，测试里也不用构造 Qt 事件。
        """
        if not self.over:
            self._jump_wanted = JUMP_BUFFER

    def release_jump(self) -> None:
        """松开跳：如果还在上升，把速度砍掉一截（轻点 = 小跳）。"""
        if self.vy < 0:
            self.vy *= JUMP_CUT
        self._jump_wanted = 0.0

    def press_crouch(self, on: bool = True) -> None:
        self.crouching = on

    def height(self) -> int:
        """当前姿态的高度（判定盒按它算）。"""
        return CROUCH_H if (self.crouching and self.on_ground) else PLAYER_H

    def hitbox(self) -> tuple[float, float, float, float]:
        """玩家判定盒 ``(左, 上, 右, 下)``，比视觉收窄一圈。"""
        h = self.height()
        return (PLAYER_X + HIT_PAD_X,
                self.feet - h + HIT_PAD_Y,
                PLAYER_X + PLAYER_W - HIT_PAD_X,
                self.feet - HIT_PAD_Y)

    def collides(self) -> bool:
        """判定盒有没有碰到任何障碍。**纯几何，可单独测。**"""
        p0, p1, p2, p3 = self.hitbox()
        for rock in self.rocks:
            r0, r1, r2, r3 = rock.rect()
            if p0 < r2 and r0 < p2 and p1 < r3 and r1 < p3:
                return True
        return False

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Space, Qt.Key.Key_Up, Qt.Key.Key_W):
            self.press_jump()
            return
        if key in (Qt.Key.Key_Down, Qt.Key.Key_S):
            self.press_crouch(True)
            return
        if key == Qt.Key.Key_R:
            # 走 request_restart 而不是直接 _restart：这一局没打完的话
            # 要先弹确认框，否则按一下 R 分数就没了、连个提示都没有
            self.request_restart()
            return
        if key == Qt.Key.Key_Escape:
            self.request_close()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Space, Qt.Key.Key_Up, Qt.Key.Key_W):
            self.release_jump()
        elif key in (Qt.Key.Key_Down, Qt.Key.Key_S):
            self.press_crouch(False)
        super().keyReleaseEvent(event)

    def mousePressEvent(self, event) -> None:
        """点一下也跳 —— 和人玩弹跳得分时的手感保持一致。"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.press_jump()

    # ================================================================ 每帧

    def _step(self, dt: float) -> None:
        self._refresh_tier()

        # ---- 世界往前跑
        self.distance += self.speed * dt
        self.score = int(self.distance / PIXELS_PER_POINT)
        for rock in self.rocks:
            rock.x -= self.speed * dt
        self.rocks = [r for r in self.rocks if r.x + r.w > -40.0]
        self._spawn_if_due()

        # ---- 跳跃：缓冲到期的"想跳"在这里兑现
        self._jump_wanted = max(0.0, self._jump_wanted - dt)
        if self._jump_wanted > 0.0 and self.on_ground:
            self.vy = -JUMP_V
            self.on_ground = False
            self._jump_wanted = 0.0

        # ---- 竖直积分
        self.vy += GRAVITY * dt
        if self.crouching and not self.on_ground:
            self.vy += FAST_FALL * dt           # 空中按 ↓ 立刻砸下来
        self.feet += self.vy * dt

        if self.feet >= GROUND_Y:
            self.feet = float(GROUND_Y)
            self.vy = 0.0
            self.on_ground = True
        else:
            self.on_ground = False

        # ---- 撞了就结束
        if self.collides():
            self._flash = 1.0
            self._finish()

    def _settle(self, dt: float) -> None:
        """结束后：让它停在地上，别继续往下掉。"""
        self.feet = float(GROUND_Y)
        self.vy = 0.0
        self.on_ground = True

    def _decay(self, dt: float) -> None:
        super()._decay(dt)
        if self._flash > 0:
            self._flash = max(0.0, self._flash - dt * 1.6)

    def _record_best(self) -> None:
        if self.score > self.cfg.best_runner:
            self.cfg.best_runner = self.score
            self.cfg.save()

    def _finish(self, early: bool = False) -> None:
        self.over = True
        self._record_best()
        earned = self._award_coins()
        headline = "提前收工" if early else "撞上了！"
        self.label_title.setText(f"{headline}跑了 {self.score} 分")
        self.label_sub.setText(
            f"最远 {self.cfg.best_runner}    速度档位 {self.tier + 1}    "
            f"撞上时 {self.speed:.0f} px/s    "
            f"+{earned} 金币{self.coins_note()}（共 {self.cfg.coins}）")
        self.overlay.show()
        self.overlay.raise_()
        self._center_overlay()

    # ================================================================ 绘制

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        self._paint_background(p)
        self._paint_rocks(p)
        self._paint_player(p)
        self._paint_ground(p)
        self._paint_hud(p)

    def _paint_background(self, p: QPainter) -> None:
        if self._bg is not None:
            p.drawPixmap(0, 0, self._bg)
        else:
            # 黄昏跑道：上暖下淡，和另外两款（粉色舞台 / 蓝天草地）一眼分得开
            g = QLinearGradient(0, HUD_H, 0, GROUND_Y)
            g.setColorAt(0.0, QColor(255, 214, 170))
            g.setColorAt(0.55, QColor(255, 236, 214))
            g.setColorAt(1.0, QColor(252, 246, 238))
            p.fillRect(QRect(0, HUD_H, W, GROUND_Y - HUD_H), g)

        if self._flash > 0:
            p.fillRect(QRect(0, HUD_H, W, H - HUD_H),
                       QColor(226, 74, 84, int(90 * self._flash)))

    def _paint_ground(self, p: QPainter) -> None:
        if self._bg is not None:
            return                  # 背景图自带地面
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(214, 188, 162))
        p.drawRect(0, GROUND_Y, W, GROUND_H)
        p.setBrush(QColor(196, 168, 142))
        p.drawRect(0, GROUND_Y, W, 7)

        # 会滚动的短横线 —— 静止的一帧里也要能看出"它在跑"
        off = int(self.distance) % 96
        p.setPen(QPen(QColor(232, 212, 190), 4, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        x = -off
        while x < W:
            p.drawLine(int(x), GROUND_Y + 22, int(x + 40), GROUND_Y + 22)
            x += 96

    def _paint_rocks(self, p: QPainter) -> None:
        for rock in self.rocks:
            k = rock.kind
            r = QRect(int(rock.x), int(rock.y), k.w, k.h)
            if k.key == "bird":
                body, edge = QColor(150, 132, 196), QColor(112, 94, 158)
            elif k.key == "tall":
                body, edge = QColor(122, 106, 96), QColor(92, 78, 70)
            else:
                body, edge = QColor(158, 138, 122), QColor(122, 104, 92)

            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(body)
            p.drawRoundedRect(r, 8, 8)
            p.setBrush(edge)
            # 上沿压一道深色，形状一眼看得出是"从上面垂下来"还是"从地上长出来"
            if k.hang:
                p.drawRoundedRect(QRect(r.x(), r.y(), r.width(), 10), 5, 5)
            else:
                p.drawRoundedRect(QRect(r.x(), r.bottom() - 8, r.width(), 8), 4, 4)

    def _paint_player(self, p: QPainter) -> None:
        h = self.height()
        w = PLAYER_W
        # 缩身时把贴图压扁（而不是换一张）—— 现役素材里没有"低头"这个状态，
        # 而压扁是"占位美术"里最省的一种，等真有素材了换掉 _frame 就行。
        top = self.feet - h

        # 影子：离地越高越淡
        air = max(0.0, (GROUND_Y - self.feet) / 200.0)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(90, 80, 70, int(60 * (1 - min(0.85, air)))))
        p.drawEllipse(int(PLAYER_X), GROUND_Y - 6, PLAYER_W, 11)

        pm = self._frame()
        if pm is None:
            p.setBrush(QColor(247, 219, 168))
            p.drawRoundedRect(QRect(int(PLAYER_X), int(top), w, h), 10, 10)
            return
        p.drawPixmap(int(PLAYER_X), int(top), w, h, pm)

    def _frame(self) -> QPixmap | None:
        """当前该画哪一帧。

        走路帧按**跑过的距离**推进，不是按时间 —— 于是速度一提，四只爪子
        自己就倒得更快，不用为"跑得快"单独做一套动画。
        """
        state = "walk" if self.on_ground else "idle"
        if self.over:
            state = "idle"
        frames = self.bank.raw(state)
        if not frames:
            return None
        if state == "walk":
            idx = int(self.distance / 52.0) % len(frames)
        else:
            idx = 0
        return self.bank.frame(state, idx, max(PLAYER_W, PLAYER_H))

    def _paint_hud(self, p: QPainter) -> None:
        paint_hud_bar(p, W)
        self._paint_hud_numbers(p)

    def _paint_hud_numbers(self, p: QPainter) -> None:
        texts = {
            "score": f"得分 {self.score}",
            "best": f"最高 {self.cfg.best_runner}",
            "tier": f"第 {self.tier + 1} 档",
            "speed": f"{self.speed:.0f} px/s",
        }
        for name, (x, w) in HUD_ZONES.items():
            size, bold = HUD_FONT[name]
            p.setFont(ui_font(size, bold=bold))
            p.setPen(QColor(43, 51, 64))
            align = (Qt.AlignmentFlag.AlignVCenter
                     | (Qt.AlignmentFlag.AlignRight if name in HUD_ALIGN_RIGHT
                        else Qt.AlignmentFlag.AlignLeft))
            p.drawText(QRect(x, 0, w, HUD_H), align, texts[name])

        # 下一档进度条（在它自己的槽位里，和上面那几段文字互不干扰）
        bx, bw = HUD_BAR
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(232, 236, 243))
        p.drawRoundedRect(QRect(bx, HUD_H // 2 - 5, bw, 10), 5, 5)
        ratio = self.next_tier_ratio()
        if ratio > 0.02:
            p.setBrush(QColor(240, 150, 90) if self.speed < MAX_SPEED
                       else QColor(120, 196, 152))
            p.drawRoundedRect(QRect(bx, HUD_H // 2 - 5, int(bw * ratio), 10), 5, 5)
