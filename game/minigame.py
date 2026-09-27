"""小游戏子系统：弹跳得分。

玩法：用左右方向键把宠物挪到方块下方，敲空格（或点画面）让它蹦起来，
撞到的方块会被**敲裂、敲碎**并加分。60 秒内比拼分数。

三个刻意的架构选择：

1. **独立窗口**。游戏窗口是普通窗口（带标题栏、可拖动、可关闭），
   完全脱离桌宠那一套"无边框 + 透明 + 置顶 + 不可抢焦点"的窗口标志——
   否则没法用键盘操作，也看不清方块。
2. **复用 ``pet.physics.Motion``**。游戏里的球和桌面上的宠物是同一份
   物理代码，不是两套。多一份体积感，少一份维护成本。
3. **复用 ``assets`` 里的贴图**。球就是桌宠本人，零新增美术需求。

v2.1.0：为什么"太无聊"以及怎么改的
----------------------------------
旧版每个方块**一碰就碎**，于是最优打法就是"贴着一个地方反复跳"——
位置、时机、高度全都不重要，玩家也感觉不到自己在变强。改动的核心是
**让"敲不穿"和"敲穿了"变成两种完全不同的处境**：

    球从下面顶到**没敲碎**的方块 → 被挡回来（那是一堵墙）
    球从下面顶到**敲碎**的方块   → 原样继续往上（连击就来自这里）

再加上一层：方块有耐久（越靠上越硬）。于是产生了一条真正的技巧曲线 ——
先花几下敲薄上面那排，后面一次跳跃就能**连穿三排**拿连击倍率。
这是旧版无论如何都打不出来的东西。

四样新东西，各自解决一个"无聊"：

    | 方块耐久 + 裂纹 | 敲击有层次，"还差一下"看得见            |
    | 连击倍率        | 跳得准有回报，位置和高度开始有意义        |
    | 掉落道具        | 每局不一样，中途有"要不要去接"的取舍      |
    | 轮次难度递增    | 通关不再是"同样的东西再来一遍"            |

**难度与收益是一起调的**：敲一下给 5 分（不再是"碎一块给 10 分"），
因为现在一块最多要敲 6 下。不这么改的话，同一局能拿到的分数会翻好几倍，
小卖部的金币直接通胀 —— 汇率（``game/common.py`` 的 ``COIN_PER_SCORE``）
是按"认真打一局够买一两样东西"定的，这里必须跟着它走。
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen

from game.common import (BG_BOUNCE, GROUND_H, GROUND_Y, HUD_H, W, H, GameWindow,
                         load_background, measure_zone_widest, paint_hud_bar,
                         ui_font, zone_spans)
from pet.assets import AssetBank
from pet.physics import Motion

# 版面常量（W / H / HUD_H / GROUND_Y）来自 game.common，两个游戏共用一套 ——
# 这里只留本游戏自己的：球、方块、回合规则。
PLAYER = 64                      # 球（宠物）边长
MOVE_SPEED = 350.0               # 水平移动速度 px/s
MOVE_ACCEL = 14.0                # 速度趋近系数，越大越跟手
#: 起跳初速度。它的平方除以 2g 就是最高点 —— 要够得着最上面那排方块，
#: 所以这个数不是随便定的：1060² / (2×2000) ≈ 281px，球顶能到 y≈189，
#: 而最上排方块在 y=232..258，留了 40 多像素余量。
#: 旧版 1000 只到 250px（球顶 220），正好卡在"刚够到、位置稍偏就摸不到"，
#: 那会让"上面那排敲不到"变成一件说不清是技术还是运气的事。
JUMP_V = 1060.0
GRAVITY = 2000.0

BLOCK_W, BLOCK_H = 96, 26
BLOCK_GAP_X, BLOCK_GAP_Y = 14, 16
BLOCK_TOP = 232
COLS, ROWS = 6, 3
BLOCK_LEFT = (W - (COLS * BLOCK_W + (COLS - 1) * BLOCK_GAP_X)) // 2

ROUND_TIME = 60.0                # 单局总时长（秒）
CLEAR_BONUS_SCORE = 50           # 清空一轮的奖励分
CLEAR_BONUS_TIME = 5.0           # 清空一轮的加时基准
CLEAR_BONUS_TIME_MIN = 2.0       # 加时的下限（后面的轮次加得越来越少）
#: 时间上限。加了"掉落道具"，加时这条路一旦没有天花板，
#: 手气好的一局能拖到十分钟 —— 那不是玩法，那是卡住了。
MAX_TIME = ROUND_TIME + 45.0

# ---------------------------------------------------------------- 敲击与耐久

#: 敲一下给的分。**不是"碎一块给 10 分"**：一块最多要敲 6 下，
#: 按每下 10 分算，一局的总分要翻好几倍，金币会立刻通胀。
SCORE_PER_HIT = 5
#: 第一轮方块的**基础**耐久；每一轮整体 +1，直到 MAX_HP
BASE_HP = 1
#: 耐久上限。再往上就不是"难"，而是"磨"了
MAX_HP = 6

#: 连击倍率阶梯：``(连击数下限, 倍率)``，从高往低匹配。
#: 用表而不是公式，是因为"几连开始 ×2"这种事调起来必须一眼看到。
COMBO_STEPS: tuple[tuple[int, int], ...] = ((6, 3), (3, 2))
MAX_COMBO_MULT = 3

#: 没敲碎的方块把球弹回来的力道（相对入射速度），以及最低弹回速度。
BLOCK_KNOCKBACK = 0.55
BLOCK_KNOCKBACK_MIN = 260.0
#: 从上面踩到没碎的方块 → 借力弹起。这是"踩方块顶"的手感来源。
BLOCK_BOUNCE_UP = 0.60
BLOCK_BOUNCE_UP_MIN = 340.0

# ---------------------------------------------------------------- 掉落道具

DROP_CHANCE = 0.16               # 敲碎一块时掉东西的概率
DROP_SIZE = 32
DROP_GRAVITY = 900.0             # 掉得慢一点，才有"够不够时间去接"的余地


@dataclass(frozen=True)
class PowerUp:
    """一种掉落道具。``label`` 只有一个字 —— 32px 的方块里画不下两个。"""

    key: str                     #: 内部标识，``_take_drop`` 按它分支
    label: str                   #: 方块上那个字
    title: str                   #: 完整说法（HUD 上显示）
    color: QColor
    weight: float                #: 抽到的相对权重


#: 道具清单 —— **加一种就在这里加一行**，``_take_drop`` 里加一个分支。
#:
#: 三种各管一件事：**多打一会**（时）、**打得动**（力）、**打得值**（分）。
#: 刻意不做"减速"那类改动物理手感的东西：它会让跳跃高度跟着变，
#: 于是"够不够得到上面那排"变成一个随时在变的量，玩家学不会。
DROPS: tuple[PowerUp, ...] = (
    PowerUp("time", "时", "加时", QColor(120, 200, 150), 0.30),
    PowerUp("power", "力", "一击必碎", QColor(240, 140, 120), 0.35),
    PowerUp("double", "分", "双倍得分", QColor(170, 150, 235), 0.35),
)

DROP_BY_KEY: dict[str, PowerUp] = {d.key: d for d in DROPS}

POWER_SECS = 8.0                 # 「力」持续多久
DOUBLE_SECS = 8.0                # 「分」持续多久
TIME_BONUS = 5.0                 # 「时」加几秒

ROW_COLORS = [QColor(255, 143, 143), QColor(255, 190, 118), QColor(150, 206, 180)]

# ---------------------------------------------------------------- HUD 版面
#
# HUD 上五段文字 + 一条进度条，加起来正好铺满 780。**坐标只写在下面这两张表里**，
# 绘制函数只负责"按表取位置"，不在 drawText 里现写数字。
#
# 为什么要抽出来：这些数不是随手定的，是**量出来的**（15px 中文一个字符约 15px、
# 11px 约 11px）。第一版把它们散在 drawText 的实参里，结果「最高 385」和
# 「第 2 轮 · 剩 17 块」两段正好落在同一段像素上，叠着画了一版才发现 ——
# 逻辑测试对这种事完全瞎，直到把验收图放大看才看出来。
# 抽成表之后，smoke_test 里有一条用例拿 QFontMetrics 算最宽的情况逐对比一遍。
#
#: ``段名 -> (x, 宽)``。left / right 对齐由 ``HUD_ALIGN_RIGHT`` 决定。
#
#: 括号里那个"最宽"是**实测值**（`QFontMetrics.horizontalAdvance` 量最坏情况），
#: 不是估的 —— 宽度只要小于它，两段迟早会撞上。
HUD_ZONES: dict[str, tuple[int, int]] = {
    "score": (20, 104),          # 得分（14px 粗体，最宽 102）
    "combo": (138, 92),          # 连击（11px 粗体，最宽 89）
    "best": (244, 70),           # 最高分（10px，最宽 68）
    "round": (348, 132),         # 第 N 轮 · 剩 M 块（11px 粗体，最宽 130）
    "secs": (508, 40),           # 剩余秒数（11px 粗体，最宽 35）
}
#: 倒计时进度条 ``(x, 宽)``。高度固定 12，垂直居中。
HUD_BAR = (556, 200)

#: ``段名 -> (字号, 是否粗体)``。和 ``HUD_ZONES`` 分开写，是因为"多宽"和"多大字"
#: 调的时候不是同一件事 —— 但**两边都改了才不重叠**，所以测试要同时看这两张表。
HUD_FONT: dict[str, tuple[int, bool]] = {
    "score": (14, True),
    "combo": (11, True),
    "best": (10, False),
    "round": (11, True),
    "secs": (11, True),
}

#: 右对齐的段 —— 这几个是"数字位数会变"的（剩几块、剩几秒），
#: 右对齐才让变化发生在左边、不把右边那条进度条推来推去。
HUD_ALIGN_RIGHT = ("round", "secs")

#: 每段"最宽的那种内容"。**改了 HUD 文案就要连这里一起改** ——
#: 它决定上面 ``HUD_ZONES`` 的宽度够不够，多一个字符就可能撞上隔壁那段。
HUD_WIDEST: dict[str, str] = {
    "score": "得分 99999",
    "combo": "连击 99　×3",
    "best": "最高 99999",
    "round": "第 99 轮 · 剩 18 块",
    "secs": "105s",
}

#: 上面那些"最宽内容"实测占多少像素（用真实字体量的，不是估的）。
#:
#: **为什么不现量**：``QT_QPA_PLATFORM=offscreen`` 那个平台插件在本机的 Qt 里
#: **字体库是空的**（连阿拉伯数字都画成方框），``QFontMetrics`` 量出来是方框的
#: 宽度 —— 拿它去断言会误报"叠字"。冒烟测试跑的就是 offscreen，所以那边只比
#: 这张**登记表**（纯算术，跟环境无关），真字体的复测放在
#: ``tools/verify_v21_ui.py``（跑在真实平台上，会把重量一遍的数和这里对照）。
HUD_WIDEST_PX: dict[str, int] = {
    "score": 102,
    "combo": 89,
    "best": 68,
    "round": 130,
    "secs": 35,
}


def hud_zone_rect(name: str) -> tuple[int, int]:
    """一段 HUD 文字占的横向区间 ``(左, 右)``，按登记的最宽内容算。

    **纯算术，不查字体** —— 于是它在任何平台上都给出同一个答案，可以放心
    拿去断言"两段有没有叠在一起"。绘制时用不上它（对齐交给 Qt），
    它是给测试和文档用的。

    算术本身在 ``game.common.zone_spans``（跑一跑用的是同一套）；
    这里只负责把本游戏这两张表喂进去。
    """
    return zone_spans(HUD_ZONES, HUD_WIDEST_PX, HUD_ALIGN_RIGHT)[name]


def measure_hud_widest() -> dict[str, int]:
    """用**当前字体**重量一遍 HUD 各段最宽内容的像素宽度。

    返回值和 ``HUD_WIDEST_PX`` 对不上就说明字号或文案改了、登记表要更新。
    **必须在真实平台上调**：offscreen 平台在本机没有字体库，量出来是方框的宽度。
    实现是 ``game.common.measure_zone_widest``（三个游戏共用一份）。
    """
    return measure_zone_widest(HUD_FONT, HUD_WIDEST)


def combo_mult(combo: int) -> int:
    """连击倍率。1 连 / 2 连是 ×1，3 连起 ×2，6 连起 ×3。

    抽成函数是因为**它同时被计分和 HUD 用**。HUD 里的"连击 ×2"如果自己
    再写一遍阶梯，改了阶梯就会看到"分数按 ×3 算、HUD 上写着 ×2"。
    """
    for need, mult in COMBO_STEPS:
        if combo >= need:
            return mult
    return 1


class Block:
    """一个可以被敲裂、敲碎的方块。用 Motion 只为了复用它的矩形判交。"""

    def __init__(self, x: float, y: float, row: int, hp: int):
        self.body = Motion(x=x, y=y, w=BLOCK_W, h=BLOCK_H)
        self.row = row
        self.hp = max(1, int(hp))
        self.max_hp = self.hp
        self.color = ROW_COLORS[row % len(ROW_COLORS)]
        self.alive = True
        self.flash = 0.0             # 刚被敲到时的白闪，0..1

    @property
    def rect(self) -> QRect:
        return QRect(int(self.body.x), int(self.body.y), BLOCK_W, BLOCK_H)

    @property
    def damage(self) -> float:
        """敲掉了多少（0 = 完好，1 = 快碎了）。画裂纹按它算。"""
        return 1.0 - self.hp / float(self.max_hp)


class Drop:
    """正在下落的道具。接住才生效，掉到地上就没了。"""

    def __init__(self, x: float, y: float, kind: PowerUp):
        self.body = Motion(x=x, y=y, w=DROP_SIZE, h=DROP_SIZE,
                           gravity=DROP_GRAVITY)
        self.kind = kind
        self.alive = True


class Pop:
    """敲到方块的粒子与飘字反馈。"""

    def __init__(self, x: float, y: float, text: str = "",
                 color: QColor | None = None):
        self.x, self.y = x, y
        self.text = text
        self.color = color or QColor(255, 190, 110)
        self.life = 0.0
        self.max_life = 0.5
        self.shards = [
            (random.uniform(-170, 170), random.uniform(-300, -90))
            for _ in range(9)
        ]

    def update(self, dt: float) -> bool:
        self.life += dt
        return self.life < self.max_life


class MiniGame(GameWindow):
    """弹跳得分小游戏窗口。

    窗口尺寸、计时器、结算浮层、关闭时发信号都在 ``GameWindow`` 里，
    这里只管本游戏的规则：球、方块、道具、连击、回合与倒计时。
    """

    TITLE = "桌宠小游戏 · 弹跳得分"
    OVERLAY_TITLE = "时间到"

    def __init__(self, bank: AssetBank, cfg, parent=None):
        super().__init__(bank, cfg, parent)

        # ---- 本游戏自己的场景
        # 背景图（粉色舞台）。读不到就是 None，_paint_background 会回退到代码画渐变。
        self._bg = load_background(BG_BOUNCE)

        self.ball = Motion(w=PLAYER, h=PLAYER, gravity=GRAVITY, restitution=0.18)
        self.blocks: list[Block] = []
        self.drops: list[Drop] = []
        self.round_no = 1
        self.time_left = ROUND_TIME
        self.squash = 0.0            # 撞击后的形变，0..1
        self._flash = 0.0
        #: 连续敲中几下没落地。落地清零 —— 见 _step 里那段。
        self.combo = 0
        self.best_combo = 0
        #: 两个限时状态还剩几秒（0 = 没有）
        self.power_left = 0.0
        self.double_left = 0.0
        #: 本局一共接住几个道具（结算文案里说一声）
        self.picked = 0

        self._reset_scene(first=True)
        self.start_clock()

    # ================================================================ 关卡

    def _reset_scene(self, first: bool = False) -> None:
        """新一局的起始状态。``GameWindow._restart()`` 也走这里。"""
        self.score = 0
        self.round_no = 1
        self.time_left = ROUND_TIME
        self.pops.clear()
        self.drops.clear()
        self.combo = 0
        self.best_combo = 0
        self.power_left = 0.0
        self.double_left = 0.0
        self.picked = 0
        self._reset_round(first=first)

    def hp_for(self, row: int) -> int:
        """本轮某个方块的初始耐久。

        两条规则叠在一起：

        * **越靠上越硬**（``ROWS - 1 - row``）。上面那排离手最远、要跳得更高
          才够得着，而且清台时它总是最后剩下的 —— 难度层次应该堆在那里，
          而不是堆在脚边那块一碰就碎的。
        * **轮次越高整体越硬**，但封顶在 ``MAX_HP``。不封顶的话，
          第 6 轮开始每块要敲十几下，那就不是游戏了。
        """
        base = BASE_HP + (self.round_no - 1)
        return max(1, min(MAX_HP, base + (ROWS - 1 - row)))

    def _reset_round(self, first: bool = False) -> None:
        self.blocks.clear()
        for row in range(ROWS):
            for col in range(COLS):
                if not first and self.rng.random() < 0.16:
                    continue                      # 随机留空，让每局布局不一样
                self.blocks.append(Block(
                    BLOCK_LEFT + col * (BLOCK_W + BLOCK_GAP_X),
                    BLOCK_TOP + row * (BLOCK_H + BLOCK_GAP_Y),
                    row,
                    self.hp_for(row),
                ))
        self.drops.clear()
        # 换了新场景，连击必须断：留着的话"清台那一刻刚好 6 连"会被带进
        # 下一轮的第一下，白送一个 ×3 —— 那是纯粹的白捡，不是技术
        self.combo = 0
        self.ball.teleport((W - PLAYER) / 2, GROUND_Y - PLAYER)
        self.ball.on_ground = True
        self.ball.stop()

    def clear_time_bonus(self) -> float:
        """清空一轮给多少加时。轮次越靠后给得越少（下限 ``_MIN``）。

        固定加 5 秒的话，手越熟打得越快、加时越频繁，一局会越拖越长 ——
        最后变成"比谁更能磨"而不是"比谁打得准"。
        """
        return max(CLEAR_BONUS_TIME_MIN,
                   CLEAR_BONUS_TIME - 0.5 * (self.round_no - 1))

    # ================================================================ 循环

    def _countdown(self, dt: float) -> None:
        """本游戏是计分制：60 秒一到就结算。"""
        self.time_left = max(0.0, self.time_left - dt)
        if self.time_left <= 0:
            self._finish()

    def _settle(self, dt: float) -> None:
        self.ball.stop()

    def _decay(self, dt: float) -> None:
        self.squash = max(0.0, self.squash - dt * 5.0)
        self._flash = max(0.0, self._flash - dt * 3.5)
        self.power_left = max(0.0, self.power_left - dt)
        self.double_left = max(0.0, self.double_left - dt)
        for blk in self.blocks:
            blk.flash = max(0.0, blk.flash - dt * 6.0)
        super()._decay(dt)

    def _step(self, dt: float) -> None:
        # ---- 输入 -> 水平速度
        left = Qt.Key.Key_Left in self.keys or Qt.Key.Key_A in self.keys
        right = Qt.Key.Key_Right in self.keys or Qt.Key.Key_D in self.keys
        target = 0.0
        if left and not right:
            target = -MOVE_SPEED
        elif right and not left:
            target = MOVE_SPEED

        # 空中控制稍弱，落地更跟手
        accel = MOVE_ACCEL * (0.55 if not self.ball.on_ground else 1.0)
        self.ball.vx += (target - self.ball.vx) * min(1.0, accel * dt)

        bounds = (0.0, float(HUD_H), float(W), float(GROUND_Y))
        was_air = not self.ball.on_ground
        self.ball.update(dt, bounds, use_gravity=True)

        if self.ball.on_ground and was_air:
            self.squash = 1.0                     # 落地压扁
            # 落地 = 这一趟结束，连击断。**这是连击唯一的清零条件**：
            # 于是"能连几下"完全由"这一跳打穿了多远"决定，
            # 而不是由"你落地后站了多久"决定。
            self.combo = 0

        # ---- 撞方块
        hit = False
        power = self.power_left > 0.0
        for blk in self.blocks:
            if not blk.alive:
                continue
            if self.ball.overlaps(blk.body):
                self._hit_block(blk, power=power)
                hit = True
        if hit:
            self.squash = 1.0
            self._flash = 1.0
        self.blocks = [b for b in self.blocks if b.alive]

        self._step_drops(dt)

        # ---- 通关
        if not self.blocks and not self.over:
            self.score += CLEAR_BONUS_SCORE
            self.time_left = min(MAX_TIME, self.time_left + self.clear_time_bonus())
            self.round_no += 1
            self._reset_round()

    # ------------------------------------------------------------ 敲方块

    def _hit_block(self, blk: Block, *, power: bool) -> None:
        """处理一次"球撞上方块"：扣耐久、计分、把球弹开。

        **弹开规则是本轮改动的核心**，也是它和普通打砖块最大的不同：

        球从下面顶到一块**没敲碎**的方块 → 被挡回去。那一刻它就是一堵墙。
        球敲碎了那块 → 方块没了，球原样继续往上 → 于是能连穿上面几排。

        旧版永远是后一种情况（一碰就碎），所以永远"穿过去"，
        位置和高度都不重要，贴着哪儿反复跳都一样 —— 这就是"无聊"的根源。

        从**上面**踩到没碎的方块则是借力弹起（`BLOCK_BOUNCE_UP`），
        让"落点踩在方块顶上"也有用，而不是只能从下面顶。
        """
        blk.hp -= 99 if power else 1
        blk.flash = 1.0

        self.combo += 1
        self.best_combo = max(self.best_combo, self.combo)
        gained = SCORE_PER_HIT * combo_mult(self.combo)
        if self.double_left > 0.0:
            gained *= 2
        self.score += gained
        self.pops.append(Pop(blk.body.x + BLOCK_W / 2, blk.body.y + BLOCK_H / 2,
                             text=f"+{gained}", color=blk.color.darker(115)))

        if blk.hp > 0:
            # 没敲碎：把球挡回去
            cx, cy = self.ball.center
            bx, by = blk.body.center
            if cy >= by:                       # 球在方块下方 → 顶到的是底面
                self.ball.vy = max(BLOCK_KNOCKBACK_MIN,
                                   abs(self.ball.vy) * BLOCK_KNOCKBACK)
            else:                              # 球在方块上方 → 踩到顶面，借力弹起
                self.ball.vy = -max(BLOCK_BOUNCE_UP_MIN,
                                    abs(self.ball.vy) * BLOCK_BOUNCE_UP)
            self.ball.on_ground = False
            return

        blk.alive = False
        if self.rng.random() < DROP_CHANCE:
            self.drops.append(Drop(blk.body.x + (BLOCK_W - DROP_SIZE) / 2,
                                   blk.body.y, self._pick_drop()))

    def _pick_drop(self) -> PowerUp:
        """按权重抽一种道具。用 ``self.rng``（不是全局 ``random``），
        测试才能塞固定种子把"掉什么"变成可复现的。"""
        return self.rng.choices(list(DROPS),
                                weights=[d.weight for d in DROPS])[0]

    # ------------------------------------------------------------ 道具

    def _step_drops(self, dt: float) -> None:
        """推进掉落的道具：接住就生效，掉地上了就没了。

        判定顺序和背包那边一样 —— **先把这一次的结果定下来**（接住 / 落地），
        再统一清场，不在遍历里删元素。
        """
        bounds = (0.0, float(HUD_H), float(W), float(GROUND_Y))
        for drop in self.drops:
            drop.body.update(dt, bounds, use_gravity=True)
            if not drop.alive:
                continue
            if self.ball.overlaps(drop.body):
                drop.alive = False
                self._take_drop(drop)
            elif drop.body.on_ground:
                drop.alive = False             # 掉地上了，没接住
        self.drops = [d for d in self.drops if d.alive]

    def _take_drop(self, drop: Drop) -> None:
        """接住一个道具。三种效果各一行，加新道具就在这里加一个分支。"""
        self.picked += 1
        kind = drop.kind.key
        if kind == "time":
            self.time_left = min(MAX_TIME, self.time_left + TIME_BONUS)
        elif kind == "power":
            self.power_left = POWER_SECS
        elif kind == "double":
            self.double_left = DOUBLE_SECS
        self.pops.append(Pop(drop.body.x + DROP_SIZE / 2,
                             drop.body.y + DROP_SIZE / 2,
                             text=drop.kind.title, color=drop.kind.color))

    def _finish(self) -> None:
        self.over = True
        if self.score > self.cfg.best_score:
            self.cfg.best_score = self.score
            self.cfg.save()
        earned = self._award_coins()
        self.label_title.setText(f"时间到！本局得分 {self.score}")
        self.label_sub.setText(
            f"最高分 {self.cfg.best_score}    通过 {self.round_no} 轮    "
            f"最高 {self.best_combo} 连（×{combo_mult(self.best_combo)}）    "
            f"道具 {self.picked} 个    "
            f"+{earned} 金币（共 {self.cfg.coins}）")
        self.overlay.show()
        self.overlay.raise_()
        self._center_overlay()

    # ================================================================ 输入

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_A, Qt.Key.Key_D):
            self.keys.add(key)
            return
        if key == Qt.Key.Key_Space:
            self._jump()
            return
        if key == Qt.Key.Key_R:
            self._restart()
            return
        if key == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:
        self.keys.discard(event.key())

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and not self.over:
            self._jump()

    def _jump(self) -> None:
        if self.over or not self.ball.on_ground:
            return
        self.ball.throw(0.0, -JUMP_V)
        self.squash = 1.0

    # ================================================================ 绘制

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        self._paint_background(p)
        self._paint_blocks(p)
        self._paint_drops(p)
        self._paint_pops(p)
        self._paint_player(p)
        self._paint_ground(p)
        self._paint_hud(p)

    def _paint_background(self, p: QPainter) -> None:
        if self._bg is not None:
            # 背景图自带天空与地面，连顶上的 HUD 区域一起铺满；
            # 半透明的 HUD 底板会压在上面，看着还是一条信息栏。
            p.drawPixmap(0, 0, self._bg)
            if self._flash > 0:
                c = QColor(255, 236, 190, int(70 * self._flash))
                p.fillRect(QRect(0, 0, W, H), c)
            return

        # 没有背景图时回退到原来的代码画渐变
        g = QLinearGradient(0, HUD_H, 0, H)
        g.setColorAt(0.0, QColor(233, 242, 252))
        g.setColorAt(1.0, QColor(250, 248, 244))
        p.fillRect(QRect(0, HUD_H, W, H - HUD_H), g)
        if self._flash > 0:
            c = QColor(255, 236, 190, int(70 * self._flash))
            p.fillRect(QRect(0, HUD_H, W, H - HUD_H), c)

    def _paint_blocks(self, p: QPainter) -> None:
        for blk in self.blocks:
            r = blk.rect
            path = QPainterPath()
            path.addRoundedRect(r.x(), r.y(), r.width(), r.height(), 8, 8)
            g = QLinearGradient(r.x(), r.y(), r.x(), r.y() + r.height())
            # 敲得越狠越暗：一眼看出哪块快碎了，不用去数还剩几下
            base = blk.color.darker(int(100 + 40 * blk.damage))
            g.setColorAt(0.0, base.lighter(118))
            g.setColorAt(1.0, base)
            p.fillPath(path, g)
            p.setPen(QPen(base.darker(135), 2))
            p.drawPath(path)

            if blk.flash > 0:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(255, 255, 255, int(170 * blk.flash)))
                p.drawPath(path)

            self._paint_cracks(p, blk, r)

            # 高光
            p.setPen(QPen(QColor(255, 255, 255, 150), 3))
            p.drawLine(r.x() + 10, r.y() + 7, r.x() + r.width() - 12, r.y() + 7)

            # 还剩几下：耐久 > 1 时才画，免得满屏都是数字
            if blk.hp > 1:
                p.setFont(ui_font(9, bold=True))
                p.setPen(QColor(60, 60, 60, 170))
                p.drawText(r, Qt.AlignmentFlag.AlignCenter, str(blk.hp))

    def _paint_cracks(self, p: QPainter, blk: Block, r: QRect) -> None:
        """按损伤程度画几条斜裂纹。

        纯粹是给眼睛的：耐久是能"看"出来的，玩家才愿意去敲第二下 ——
        旧版一碰就碎，根本没有"还差一下"这个中间状态。
        """
        d = blk.damage
        if d <= 0.01:
            return
        lines = 1 + int(d * (blk.max_hp - 1) * 0.8)
        lines = max(1, min(lines, 4))
        p.setPen(QPen(QColor(70, 50, 45, 120), 1.5))
        for i in range(lines):
            fx = r.x() + r.width() * (i + 1) / (lines + 1)
            p.drawLine(int(fx - 7), r.y() + 4, int(fx + 6), r.bottom() - 4)
            p.drawLine(int(fx + 6), r.y() + 6, int(fx - 5), r.bottom() - 6)

    def _paint_drops(self, p: QPainter) -> None:
        for drop in self.drops:
            b = drop.body
            r = QRect(int(b.x), int(b.y), DROP_SIZE, DROP_SIZE)
            path = QPainterPath()
            path.addRoundedRect(r.x(), r.y(), r.width(), r.height(), 9, 9)
            p.setPen(QPen(drop.kind.color.darker(140), 2))
            p.setBrush(drop.kind.color)
            p.drawPath(path)
            p.setPen(QColor(255, 255, 255, 235))
            p.setFont(ui_font(12, bold=True))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, drop.kind.label)

    def _paint_pops(self, p: QPainter) -> None:
        for pop in self.pops:
            t = pop.life / pop.max_life
            alpha = int(255 * (1 - t))
            for vx, vy in pop.shards:
                px = pop.x + vx * pop.life
                py = pop.y + vy * pop.life + 0.5 * 900 * pop.life ** 2
                p.setPen(Qt.PenStyle.NoPen)
                c = QColor(pop.color)
                c.setAlpha(alpha)
                p.setBrush(c)
                p.drawEllipse(int(px), int(py), 6, 6)
            if pop.text and t < 0.6:
                p.setFont(ui_font(12, bold=True))
                c = QColor(pop.color).darker(120)
                c.setAlpha(int(255 * (1 - t / 0.6)))
                p.setPen(c)
                p.drawText(int(pop.x - 40), int(pop.y - 12 - 26 * t), 80, 20,
                           Qt.AlignmentFlag.AlignCenter, pop.text)

    def _paint_player(self, p: QPainter) -> None:
        b = self.ball
        cx = b.x + PLAYER / 2
        # 影子：离地越高越淡越小
        air = max(0.0, (GROUND_Y - PLAYER - b.y) / 240.0)
        sw = PLAYER * (1.0 - 0.35 * min(1.0, air))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(90, 80, 70, int(70 * (1 - min(0.8, air)))))
        p.drawEllipse(int(cx - sw / 2), GROUND_Y - 8, int(sw), 14)

        pm = self.bank.frame("idle", 0, PLAYER)
        if pm is None:
            p.setBrush(QColor(247, 219, 168))
            p.drawEllipse(int(b.x), int(b.y), PLAYER, PLAYER)
            return

        # 落地压扁 / 起跳拉长
        sy = 1.0 - 0.22 * self.squash
        sx = 1.0 + 0.18 * self.squash
        if not b.on_ground and b.vy < -300:
            sy = 1.12
            sx = 0.93
        w, h = int(PLAYER * sx), int(PLAYER * sy)
        # 「力」生效时给球描一圈光边 —— 否则"现在一击必碎"只能靠记时间
        if self.power_left > 0:
            p.setPen(QPen(QColor(240, 140, 120, 170), 3))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(int(cx - PLAYER / 2), int(b.y + PLAYER - h),
                          PLAYER, h)
        p.drawPixmap(int(cx - w / 2), int(b.y + PLAYER - h), w, h, pm)

    def _paint_ground(self, p: QPainter) -> None:
        if self._bg is not None:
            return            # 背景图自带地面，再画一条会看出是两层边
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(206, 224, 240))
        p.drawRoundedRect(0, GROUND_Y, W, GROUND_H, 10, 10)
        p.setBrush(QColor(226, 239, 250))
        p.drawRoundedRect(0, GROUND_Y, W, 8, 4, 4)

    def _paint_hud(self, p: QPainter) -> None:
        paint_hud_bar(p, W)
        self._paint_hud_numbers(p)
        self._paint_buffs(p)

    def _paint_hud_numbers(self, p: QPainter) -> None:
        """HUD 第一排：得分 / 连击 / 最高 / 轮次 / 剩余秒数 / 倒计时条。

        **一个坐标都不在这里写死**，全部来自 ``HUD_ZONES`` / ``HUD_BAR`` ——
        见那两张表上面那段注释（这里曾经叠着画过一版）。
        """
        # ---- 左半：得分 / 连击 / 最高
        x, w = HUD_ZONES["score"]
        size, bold = HUD_FONT["score"]
        p.setPen(QColor(48, 56, 70))
        p.setFont(ui_font(size, bold=bold))
        p.drawText(x, 0, w, HUD_H, Qt.AlignmentFlag.AlignVCenter,
                   f"得分 {self.score}")

        # 连击：只在 2 连以上才出现（1 连就是"刚敲了一下"，没什么可说的）
        if self.combo >= 2:
            x, w = HUD_ZONES["combo"]
            size, bold = HUD_FONT["combo"]
            mult = combo_mult(self.combo)
            p.setFont(ui_font(size, bold=bold))
            p.setPen(QColor(230, 120, 40) if mult > 1 else QColor(140, 150, 170))
            p.drawText(x, 0, w, HUD_H, Qt.AlignmentFlag.AlignVCenter,
                       f"连击 {self.combo}　×{mult}")

        x, w = HUD_ZONES["best"]
        size, bold = HUD_FONT["best"]
        p.setFont(ui_font(size, bold=bold))
        p.setPen(QColor(120, 130, 148))
        p.drawText(x, 0, w, HUD_H, Qt.AlignmentFlag.AlignVCenter,
                   f"最高 {max(self.cfg.best_score, self.score)}")

        # ---- 右半：轮次与剩余块数 -> 剩余秒数 -> 倒计时进度条
        right = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight
        x, w = HUD_ZONES["round"]
        size, bold = HUD_FONT["round"]
        p.setPen(QColor(70, 80, 95))
        p.setFont(ui_font(size, bold=bold))
        p.drawText(x, 0, w, HUD_H, right,
                   f"第 {self.round_no} 轮 · 剩 {len(self.blocks)} 块")

        x, w = HUD_ZONES["secs"]
        size, bold = HUD_FONT["secs"]
        p.setFont(ui_font(size, bold=bold))
        p.drawText(x, 0, w, HUD_H, right, f"{int(math.ceil(self.time_left))}s")

        bx, bw = HUD_BAR
        bh = 12
        by = (HUD_H - bh) // 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(232, 236, 244))
        p.drawRoundedRect(bx, by, bw, bh, 6, 6)
        # 进度条按 ROUND_TIME 走，但加时能把时间顶到 ROUND_TIME 以上 ——
        # 夹在 1.0 就是"满了"，不然条会画到窗口外面去
        ratio = max(0.0, min(1.0, self.time_left / ROUND_TIME))
        p.setBrush(QColor(120, 200, 150) if ratio > 0.3 else QColor(240, 140, 120))
        p.drawRoundedRect(bx, by, int(bw * ratio), bh, 6, 6)

    def _paint_buffs(self, p: QPainter) -> None:
        """限时道具的状态 + 操作提示，画在 HUD 下面那条窄带里。

        道具必须显示**还剩几秒**：不显示的话，玩家挨了一下才发现
        "原来早就过期了" —— 那种挫败感纯粹来自界面没说清。
        """
        y = HUD_H + 8
        x = 20
        for left, drop in ((self.power_left, DROP_BY_KEY["power"]),
                           (self.double_left, DROP_BY_KEY["double"])):
            if left <= 0:
                continue
            text = f"{drop.title} {left:.0f}s"
            p.setFont(ui_font(10, bold=True))
            w = 30 + 8 * len(text)
            r = QRect(x, y, w, 22)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(drop.color.red(), drop.color.green(),
                              drop.color.blue(), 205))
            p.drawRoundedRect(r, 11, 11)
            p.setPen(QColor(255, 255, 255))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)
            x += w + 8

        p.setFont(ui_font(9))
        p.setPen(QColor(150, 158, 172))
        p.drawText(0, y, W - 20, 22, Qt.AlignmentFlag.AlignRight,
                   "← → 移动　　空格 / 点击 起跳　　R 重开　　Esc 退出")
