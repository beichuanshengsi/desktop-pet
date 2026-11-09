"""小游戏：狗粮 2048。

玩法就是 2048：方向键朝一个方向推，相同的两块**合成一倍**，
每推一次冒出一块新的。目标是凑出一碗 **512**（达成即结算），
推不动了也结算。**限 3 次撤销**，给手滑留后路。

四款游戏里它是最特别的一个，所以单独说明
----------------------------------------
另外三款都是"手"的游戏（挪位置、卡时机），这一款是**脑子**的：
没有手感、没有反应速度、没有运气以外的意外，**每一次失败都是自己想错了**。
它也因此是四款里唯一能"随时切走再回来"的 —— 状态是离散的，
不看屏幕的十分钟不会让它死掉（``GameWindow`` 的计时器停了也无所谓）。

三个刻意的取舍
--------------

1. **规则层不依赖 Qt**（``slide_line`` / ``move`` / ``can_move`` 都是纯函数）。
   这不是洁癖：2048 的规则**特别容易写错**，而错误的形态是"看起来能玩、
   某个方向偶尔不对"，靠眼睛很难发现。纯函数能直接喂固定棋盘断言 ——
   比如 ``[2,2,2,2]`` 滑一次必须是 ``[4,4,0,0]`` 而不是 ``[8,0,0,0]``
   （**一次滑动里新合成的格子不能再参与合成**，这是 2048 最容易踩的一条）。
2. **结算口径和另外三款不一样，是故意的**。另外三款统一用
   ``game.common.coins_for``（``score // 10``），因为它们的分数都在
   "一局 200~800 分"这个量级。2048 的分数会到几千 —— 硬套那把尺子，
   一局就是几百金币，小卖部立刻失去意义（最贵的东西才 30）。
   所以这一款按**最大格子**折算（``coins_for_tile``）：达成 512 = 56 金币，
   和另外三款"认真打一局"基本持平。**两把尺子并存是有代价的**（改汇率时要
   记得有两处），所以这条规则写在 ``game/common.py`` 的汇率注释旁边，
   免得以后有人只改了一边。
3. **目标定在 512 而不是 2048**。2048 一局要十几分钟，而这是个**桌宠的
   小游戏**（旁边还挂着一只狗要喂）。512 大约 3~6 分钟，够体会"越挤越紧"
   又不至于让人中途放弃。达成即结算 —— 想接着挑战 1024 就再来一局。
"""

from __future__ import annotations

import random
from typing import Iterable

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFontMetricsF, QPainter, QPen

from game.common import (BG_2048, HUD_H, W, H, GameWindow, load_background,
                         measure_zone_widest, paint_hud_bar, ui_font, zone_spans)
from pet.assets import AssetBank
from pet import sfx as sfxlib
# 装备加成的乘法与"金币进存档"现在都在底座 ``_award_coins`` 里一份
# （本款只覆盖 ``_round_coins`` 提供自己那把尺子），所以这里不再直接 import
# ``coins_with_bonus`` —— 留着会让"加成只写一处"这个约定变得看不出来。

# ================================================================ 规则（纯函数）
#
# 这一节**不 import Qt 的任何东西**，测试可以直接喂棋盘。
# 界面上要用到的尺寸常量在下一节。

SIZE = 4                     #: 4x4
TARGET = 512                 #: 凑出这个数就结算
START_TILES = 2              #: 开局先摆几块
UNDO_LIMIT = 3               #: 一局能撤销几次
SPAWN_FOUR_CHANCE = 0.10     #: 新冒出来的块有多大概率是 4（其余是 2）

Grid = tuple[tuple[int, ...], ...]


def empty_grid() -> Grid:
    return tuple(tuple(0 for _ in range(SIZE)) for _ in range(SIZE))


def slide_line(cells: Iterable[int]) -> tuple[list[int], int]:
    """把一行朝**左**滑到底，返回 ``(新行, 这行得了多少分)``。

    三条规则，顺序不能换：

    1. 先去零（空位在哪儿都不影响结果）；
    2. 相邻且相等就合并成两倍，**合并出来的新块在这一次滑动里不再合并**
       —— 所以 ``[2,2,2,2]`` 是 ``[4,4,0,0]`` 而不是 ``[8,0,0,0]``。
       ``i += 2`` 那一步就是这个意思（跳过刚合成的那块）。
    3. 右边补零回 4 格。

    得分按 2048 的老规矩：**合并出多少就加多少**（合出 8 加 8）。
    """
    nums = [int(c) for c in cells if c]
    out: list[int] = []
    gained = 0
    i = 0
    while i < len(nums):
        if i + 1 < len(nums) and nums[i] == nums[i + 1]:
            merged = nums[i] * 2
            out.append(merged)
            gained += merged
            i += 2                  # 关键：跳过刚合成的那块，它不能再合
        else:
            out.append(nums[i])
            i += 1
    out += [0] * (SIZE - len(out))
    return out, gained


def _rows_for(grid: Grid, direction: str) -> list[list[int]]:
    """把棋盘按方向拆成"四条各自朝左滑的行"。

    这样 ``slide_line`` 就只用写一份 —— 四个方向的差别全在这里被吸收掉。
    """
    if direction == "left":
        return [list(row) for row in grid]
    if direction == "right":
        return [list(reversed(row)) for row in grid]
    if direction == "up":
        return [[grid[r][c] for r in range(SIZE)] for c in range(SIZE)]
    if direction == "down":
        return [[grid[r][c] for r in range(SIZE - 1, -1, -1)]
                for c in range(SIZE)]
    raise ValueError(f"未知方向：{direction!r}")


def _grid_from_rows(rows: list[list[int]], direction: str) -> Grid:
    """``_rows_for`` 的逆运算。"""
    if direction == "left":
        return tuple(tuple(r) for r in rows)
    if direction == "right":
        return tuple(tuple(reversed(r)) for r in rows)
    if direction == "up":
        return tuple(tuple(rows[c][r] for c in range(SIZE)) for r in range(SIZE))
    return tuple(tuple(rows[c][SIZE - 1 - r] for c in range(SIZE))
                 for r in range(SIZE))


def move(grid: Grid, direction: str) -> tuple[Grid, int, bool]:
    """朝一个方向推一次，返回 ``(新棋盘, 得分, 有没有真的动)``。

    第三个数很要紧：**没动的那一次不该冒新块**，否则玩家按一下无效方向
    就等于白送对方一块 —— 这是 2048 里最容易被忽略的体验细节。
    """
    rows = _rows_for(grid, direction)
    new_rows: list[list[int]] = []
    gained = 0
    for row in rows:
        slid, got = slide_line(row)
        new_rows.append(slid)
        gained += got
    out = _grid_from_rows(new_rows, direction)
    return out, gained, out != grid


def can_move(grid: Grid) -> bool:
    """还有路可走吗（有空格，或者相邻有相等的）。"""
    for row in grid:
        if any(c == 0 for c in row):
            return True
    for r in range(SIZE):
        for c in range(SIZE):
            v = grid[r][c]
            if c + 1 < SIZE and grid[r][c + 1] == v:
                return True
            if r + 1 < SIZE and grid[r + 1][c] == v:
                return True
    return False


def max_tile(grid: Grid) -> int:
    return max((c for row in grid for c in row), default=0)


def is_finished(grid: Grid) -> bool:
    """这一盘该收了没有：**凑到目标**，或者**推不动了**。

    抽成纯函数是为了能被直接断言 —— 尤其是"死局"这一支：
    在窗口层很难测（要先推一步、再让随机冒块恰好把最后一个空位填掉），
    而它又是个不该出错的判定：判错的后果是"明明死局了还能继续按"。
    """
    return max_tile(grid) >= TARGET or not can_move(grid)


def spawn(grid: Grid, rng: random.Random) -> Grid:
    """在随机空位放一块新的（2 或 4）。没有空位就原样返回。"""
    holes = [(r, c) for r in range(SIZE) for c in range(SIZE) if grid[r][c] == 0]
    if not holes:
        return grid
    r, c = rng.choice(holes)
    value = 4 if rng.random() < SPAWN_FOUR_CHANCE else 2
    cells = [list(row) for row in grid]
    cells[r][c] = value
    return tuple(tuple(row) for row in cells)


def new_grid(rng: random.Random) -> Grid:
    grid = empty_grid()
    for _ in range(START_TILES):
        grid = spawn(grid, rng)
    return grid


def coins_for_tile(tile: int) -> int:
    """按最大格子折算金币 —— **这一款不跟 ``coins_for`` 那把尺子**。

    理由见模块开头第 2 条。折法是"每超过 8（2 的 3 次方）一格给 8 金币"：

        16 → 8      64 → 24     256 → 40
        32 → 16     128 → 32    512 → 56（达成目标）

    为什么定在 8 起步：一局下来即使没凑到目标，只要别乱推也至少能到 8，
    空空手而归对养成游戏是负反馈。为什么每格给 8 而不是更多：
    **达成目标那一局 = 56 金币**，和另外三款"认真打一局"（20~80）对得上。
    """
    if tile < 8:
        return 0
    exp = int(tile).bit_length() - 1
    return max(0, exp - 2) * 8


# ================================================================ 版面与配色

BOARD = 420                                    #: 棋盘边长
GAP = 14                                       #: 格子间距
CELL = (BOARD - GAP * (SIZE + 1)) // SIZE      #: 单格边长
BOARD_X = (W - BOARD) // 2
BOARD_Y = HUD_H + (H - HUD_H - BOARD) // 2

#: ``数值 -> (底色, 字色)``。狗粮主题：越大的块越像"烤得越焦"。
#: 表里没有的（1024 以上）按 ``FALLBACK`` 取色，不会崩。
TILE_COLORS: dict[int, tuple[str, str]] = {
    2: ("#f6efe2", "#7a6a52"),
    4: ("#f3e3c6", "#7a6242"),
    8: ("#f7c873", "#7a5410"),
    16: ("#f5a94e", "#5f3c06"),
    32: ("#f08a4b", "#5a2f05"),
    64: ("#e96a3c", "#fff6ee"),
    128: ("#dd4f38", "#fff6ee"),
    256: ("#c93b34", "#fff6ee"),
    512: ("#a92d2d", "#fff6ee"),
}
TILE_FALLBACK = ("#7d2222", "#fff6ee")

#: 数字字号按位数递减 —— 88px 的格子里，"1024" 用 30px 会溢出。
TILE_FONT = {1: 32, 2: 30, 3: 24, 4: 19}

#: HUD 版面登记表。规矩同另外两款（见 ``game/common.zone_spans``）：
#: **坐标只写在这里**，绘制函数不许写死数字。
#:
#: ``tile`` 和 ``undo`` 之间那段距离是**量出来之后重排的**：第一版把 undo 放在
#: x=284，而「最大 2048」实量 71px 宽（我估的是 62）—— 于是两段真的差 1px 就
#: 叠上了。冒烟测试用的登记值偏小，反而**没能报出来**；是靠验收脚本量真字宽
#: 才发现的。这也是那条"估计宽度没有意义"的教训的第二次复现。
HUD_ZONES: dict[str, tuple[int, int]] = {
    "score": (20, 104),      # 得分（14px 粗体）
    "best": (132, 74),       # 最高（10px）
    "tile": (214, 76),       # 当前最大块（11px 粗体）
    "undo": (296, 64),       # 还剩几次撤销（10px）
}

#: 最大块到目标的对数进度条 —— 没有文字，不参与叠字断言（同另外两款的处理）
HUD_BAR = (380, 360)

HUD_FONT: dict[str, tuple[int, bool]] = {
    "score": (14, True),
    "best": (10, False),
    "tile": (11, True),
    "undo": (10, False),
}

HUD_ALIGN_RIGHT: tuple[str, ...] = ()

HUD_WIDEST: dict[str, str] = {
    "score": "得分 99999",
    "best": "最高 99999",
    "tile": "最大 2048",
    "undo": "撤销 ×3",
}

#: 实测像素宽度，由 ``tools/verify_v22_ui.py`` 在真实平台上量出来对照（不是估的）。
#: 是"精确值"而不是宽松预算：字号或文案一改，验收脚本立刻报超。
HUD_WIDEST_PX: dict[str, int] = {
    "score": 102,
    "best": 68,
    "tile": 71,
    "undo": 47,
}


def hud_zone_rect(name: str) -> tuple[int, int]:
    """一段 HUD 文字占的横向区间 ``(左, 右)``，按登记的最宽内容算（纯算术）。"""
    return zone_spans(HUD_ZONES, HUD_WIDEST_PX, HUD_ALIGN_RIGHT)[name]


def measure_hud_widest() -> dict[str, int]:
    """用**当前字体**重量一遍各段最宽内容的像素宽度（只能在真实平台上调）。"""
    return measure_zone_widest(HUD_FONT, HUD_WIDEST)


def target_ratio(grid: Grid) -> float:
    """最大块离目标的**对数**进度（0..1）。

    用对数而不是线性：2048 的成长是翻倍的，线性的进度条会在最后一格
    "永远卡在 90%"—— 512 之前的每一步看起来都毫无进展。
    """
    t = max_tile(grid)
    if t < 16:
        return 0.0
    exp = t.bit_length() - 1
    span = TARGET.bit_length() - 1 - 4          # 16(2^4) → 512(2^9)：共 5 档
    return max(0.0, min(1.0, (exp - 4) / float(span)))


# ================================================================ 小游戏窗口


class Game2048(GameWindow):
    """狗粮 2048。

    ``GameWindow`` 的计时器这里只用来做"按着的方向键连发"，规则推进是
    **离散**的 —— 一次按键一步，所以 ``_step`` 里不按 dt 算任何东西。
    """

    TITLE = "桌宠小游戏 · 狗粮 2048"
    OVERLAY_TITLE = "结束"

    #: 按住方向键多长时间自动再推一次（秒）。太快会"一滑一大片"，
    #: 太慢手指会累；0.16 约等于连点的手速。
    REPEAT_DELAY = 0.16

    def __init__(self, bank: AssetBank, cfg, parent=None):
        super().__init__(bank, cfg, parent)

        self._bg = load_background(BG_2048)
        self.grid: Grid = empty_grid()
        self.undo_left = UNDO_LIMIT
        self._history: list[tuple[Grid, int, int]] = []
        self._held: str | None = None
        self._repeat = 0.0
        self.won = False
        self._flash = 0.0

        self._reset_scene(first=True)
        self.start_clock()

    # ================================================================ 关卡

    def _reset_scene(self, first: bool = False) -> None:
        self.score = 0
        self.grid = new_grid(self.rng)
        self.undo_left = UNDO_LIMIT
        self._history.clear()
        self._held = None
        self._repeat = 0.0
        self.won = False
        self._flash = 0.0

    # ------------------------------------------------------------ 一步

    def can_undo(self) -> bool:
        return self.undo_left > 0 and bool(self._history)

    def push(self, direction: str) -> bool:
        """朝一个方向推一次。返回**有没有真的动**。

        走这条路（而不是直接改 ``grid``）才有撤销和自动冒块。键盘、测试
        都从这儿进 —— 一次按键走完整的一步，测试就能直接断言"推完长什么样"。
        """
        if self.over:
            return False
        nxt, gained, moved = move(self.grid, direction)
        if not moved:
            return False
        self._history.append((self.grid, self.score, self.undo_left))
        self.grid = spawn(nxt, self.rng)
        self.score += gained
        # 合并出东西响"得分"，只是挪了个位置响轻轻的"滑一下"。
        # 这一款一局要推几十上百步，每步都给一点声音才不至于闷；
        # 但两种要分开 —— 每步都按得分音的话，"这一步真的合上了"就没感觉了。
        sfxlib.play("score" if gained else "flip")

        # 只在这一步**真的推动了之后**才判"该不该收"：死局必然是
        # "某次成功的推送 + 冒新块"之后的产物，中途去判是白费。
        if is_finished(self.grid):
            self.won = max_tile(self.grid) >= TARGET
            self._finish()
        return True

    def undo(self) -> bool:
        """撤销一步（消耗一次）。没得撤就返回 False。"""
        if self.over or not self.can_undo():
            return False
        self.grid, self.score, self.undo_left = self._history.pop()
        self.undo_left -= 1
        return True

    # ================================================================ 输入

    def keyPressEvent(self, event) -> None:
        key = event.key()
        direction = _DIRECTION_KEYS.get(key)
        if direction is not None:
            if not event.isAutoRepeat():
                self.push(direction)
                self._held = direction
                self._repeat = self.REPEAT_DELAY
            return
        if key == Qt.Key.Key_Z:
            self.undo()
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
        if _DIRECTION_KEYS.get(event.key()) is not None:
            if not event.isAutoRepeat():
                self._held = None
            return
        super().keyReleaseEvent(event)

    # ================================================================ 每帧

    def _step(self, dt: float) -> None:
        """只有"按住不放自动连推"这一件事是按时间的，规则本身不按 dt。"""
        if self._held is None:
            return
        self._repeat -= dt
        if self._repeat <= 0:
            self.push(self._held)
            self._repeat = self.REPEAT_DELAY

    def _settle(self, dt: float) -> None:
        self._held = None

    def _decay(self, dt: float) -> None:
        super()._decay(dt)
        if self._flash > 0:
            self._flash = max(0.0, self._flash - dt * 1.6)

    def _record_best(self) -> None:
        if self.score > self.cfg.best_2048:
            self.cfg.best_2048 = self.score
            self.cfg.save()

    def _round_coins(self) -> int:
        """2048 的金币**按最大格子**折算，不跟 ``coins_for`` 那把尺子。

        覆盖这一个钩子就够了：``_award_coins``（以及它背后的"打完结算"和
        "中途退出结算"两条路）都会自动走这里，不用各写一遍。
        理由见模块开头第 2 条与 ``coins_for_tile``。
        """
        return coins_for_tile(max_tile(self.grid))

    def _finish(self, early: bool = False) -> None:
        self.over = True
        best = max(self.cfg.best_2048, self.score)
        self._record_best()
        earned = self._award_coins(announce=not early)
        self._flash = 1.0

        if early:
            # 玩家中途收工。**不能沿用"推不动了"** —— 那会让他以为是自己把
            # 局面走死了，其实是主动结束的。
            outcome = f"提前收工　得分 {self.score}"
        elif self.won:
            outcome = f"凑出 {TARGET} 了！得分 {self.score}"
        else:
            outcome = f"推不动了　得分 {self.score}"
        self.label_title.setText(outcome)
        self.label_sub.setText(
            f"最大块 {max_tile(self.grid)}    最高分 {best}    "
            f"+{earned} 金币{self.coins_note()}（共 {self.cfg.coins}）")
        self.overlay.show()
        self.overlay.raise_()
        self._center_overlay()

    # ================================================================ 绘制

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        self._paint_background(p)
        self._paint_board(p)
        self._paint_hud(p)

    def _paint_background(self, p: QPainter) -> None:
        if self._bg is not None:
            p.drawPixmap(0, 0, self._bg)
        else:
            p.fillRect(QRect(0, HUD_H, W, H - HUD_H), QColor(250, 246, 238))
        if self._flash > 0:
            p.fillRect(QRect(0, HUD_H, W, H - HUD_H),
                       QColor(255, 236, 190, int(80 * self._flash)))

    def _cell_rect(self, r: int, c: int) -> QRect:
        x = BOARD_X + GAP + c * (CELL + GAP)
        y = BOARD_Y + GAP + r * (CELL + GAP)
        return QRect(x, y, CELL, CELL)

    def _paint_board(self, p: QPainter) -> None:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(226, 214, 196))
        p.drawRoundedRect(QRect(BOARD_X, BOARD_Y, BOARD, BOARD), 14, 14)

        for r in range(SIZE):
            for c in range(SIZE):
                rect = self._cell_rect(r, c)
                value = self.grid[r][c]
                p.setPen(Qt.PenStyle.NoPen)
                if value == 0:
                    p.setBrush(QColor(240, 232, 220))
                    p.drawRoundedRect(rect, 10, 10)
                    continue

                bg, ink = TILE_COLORS.get(value, TILE_FALLBACK)
                p.setBrush(QColor(bg))
                p.drawRoundedRect(rect, 10, 10)

                text = str(value)
                size = TILE_FONT.get(len(text), 17)
                font = ui_font(size, bold=True)
                # 字号是"按位数"定的，万一某个字体把它撑爆了就再缩一档 ——
                # 溢出会压到隔壁格子，只有真画出来才看得见（和 HUD 叠字一个教训）
                if QFontMetricsF(font).horizontalAdvance(text) > CELL - 12:
                    font = ui_font(max(11, size - 6), bold=True)
                p.setFont(font)
                p.setPen(QColor(ink))
                p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

        if max_tile(self.grid) >= TARGET:
            p.setPen(QPen(QColor(234, 179, 8), 3))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRect(BOARD_X - 3, BOARD_Y - 3,
                                    BOARD + 6, BOARD + 6), 16, 16)

        self._paint_hint(p)

    def _paint_hint(self, p: QPainter) -> None:
        """棋盘下面那行操作提示。撤销还剩几次也在这儿说一声。"""
        p.setFont(ui_font(10))
        p.setPen(QColor(150, 138, 122))
        p.drawText(QRect(0, BOARD_Y + BOARD + 12, W, 22),
                   Qt.AlignmentFlag.AlignCenter,
                   f"方向键（或 WASD）推一下　Z 撤销（剩 {self.undo_left}）　R 重开")

    def _paint_hud(self, p: QPainter) -> None:
        paint_hud_bar(p, W)
        self._paint_hud_numbers(p)

    def _paint_hud_numbers(self, p: QPainter) -> None:
        texts = {
            "score": f"得分 {self.score}",
            "best": f"最高 {max(self.cfg.best_2048, self.score)}",
            "tile": f"最大 {max_tile(self.grid)}",
            "undo": f"撤销 ×{self.undo_left}",
        }
        for name, (x, w) in HUD_ZONES.items():
            size, bold = HUD_FONT[name]
            p.setFont(ui_font(size, bold=bold))
            p.setPen(QColor(43, 51, 64))
            align = (Qt.AlignmentFlag.AlignVCenter
                     | (Qt.AlignmentFlag.AlignRight if name in HUD_ALIGN_RIGHT
                        else Qt.AlignmentFlag.AlignLeft))
            p.drawText(QRect(x, 0, w, HUD_H), align, texts[name])

        bx, bw = HUD_BAR
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(232, 236, 243))
        p.drawRoundedRect(QRect(bx, HUD_H // 2 - 5, bw, 10), 5, 5)
        ratio = target_ratio(self.grid)
        if ratio > 0.02:
            p.setBrush(QColor(240, 150, 90) if ratio < 1.0
                       else QColor(120, 196, 152))
            p.drawRoundedRect(QRect(bx, HUD_H // 2 - 5, int(bw * ratio), 10), 5, 5)


#: 方向键（含 WASD）到方向的映射。写在类外，是因为类体里引用 ``Qt``
#: 那些常量在导入期求值，一旦名字拼错要到运行时才炸。
_DIRECTION_KEYS: dict[int, str] = {
    Qt.Key.Key_Left: "left", Qt.Key.Key_A: "left",
    Qt.Key.Key_Right: "right", Qt.Key.Key_D: "right",
    Qt.Key.Key_Up: "up", Qt.Key.Key_W: "up",
    Qt.Key.Key_Down: "down", Qt.Key.Key_S: "down",
}
