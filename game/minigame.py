"""小游戏子系统：弹跳得分。

玩法：用左右方向键把宠物挪到方块下方，敲空格（或点画面）让它蹦起来，
撞到的方块会被撞碎并加分。60 秒内比拼分数。

三个刻意的架构选择：

1. **独立窗口**。游戏窗口是普通窗口（带标题栏、可拖动、可关闭），
   完全脱离桌宠那一套"无边框 + 透明 + 置顶 + 不可抢焦点"的窗口标志——
   否则没法用键盘操作，也看不清方块。
2. **复用 ``pet.physics.Motion``**。游戏里的球和桌面上的宠物是同一份
   物理代码，不是两套。多一份体积感，少一份维护成本。
3. **复用 ``assets`` 里的贴图**。球就是桌宠本人，零新增美术需求。
"""

from __future__ import annotations

import math
import random

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen

from game.common import (BG_BOUNCE, GROUND_H, GROUND_Y, HUD_H, W, H, GameWindow,
                         load_background, paint_hud_bar, ui_font)
from pet.assets import AssetBank
from pet.physics import Motion

# 版面常量（W / H / HUD_H / GROUND_Y）来自 game.common，两个游戏共用一套 ——
# 这里只留本游戏自己的：球、方块、回合规则。
PLAYER = 64                      # 球（宠物）边长
MOVE_SPEED = 350.0               # 水平移动速度 px/s
MOVE_ACCEL = 14.0                # 速度趋近系数，越大越跟手
JUMP_V = 1000.0                  # 起跳初速度
GRAVITY = 2000.0

BLOCK_W, BLOCK_H = 96, 26
BLOCK_GAP_X, BLOCK_GAP_Y = 14, 16
BLOCK_TOP = 232
COLS, ROWS = 6, 3
BLOCK_LEFT = (W - (COLS * BLOCK_W + (COLS - 1) * BLOCK_GAP_X)) // 2

ROUND_TIME = 60.0                # 单局总时长（秒）
CLEAR_BONUS_SCORE = 50
CLEAR_BONUS_TIME = 5.0
SCORE_PER_BLOCK = 10

ROW_COLORS = [QColor(255, 143, 143), QColor(255, 190, 118), QColor(150, 206, 180)]


class Block:
    """一个可被撞碎的方块。用 Motion 只为了复用它的矩形判交。"""

    def __init__(self, x: float, y: float, row: int):
        self.body = Motion(x=x, y=y, w=BLOCK_W, h=BLOCK_H)
        self.row = row
        self.color = ROW_COLORS[row % len(ROW_COLORS)]
        self.alive = True

    @property
    def rect(self) -> QRect:
        return QRect(int(self.body.x), int(self.body.y), BLOCK_W, BLOCK_H)


class Pop:
    """撞碎方块的粒子反馈。"""

    def __init__(self, x: float, y: float):
        self.x, self.y = x, y
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
    这里只管本游戏的规则：球、方块、回合与倒计时。
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
        self.pops: list[Pop] = []
        self.round_no = 1
        self.time_left = ROUND_TIME
        self.squash = 0.0            # 撞击后的形变，0..1
        self._flash = 0.0

        self._reset_scene(first=True)
        self.start_clock()

    # ================================================================ 关卡

    def _reset_scene(self, first: bool = False) -> None:
        """新一局的起始状态。``GameWindow._restart()`` 也走这里。"""
        self.score = 0
        self.round_no = 1
        self.time_left = ROUND_TIME
        self.pops.clear()
        self._reset_round(first=first)

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
                ))
        self.ball.teleport((W - PLAYER) / 2, GROUND_Y - PLAYER)
        self.ball.on_ground = True
        self.ball.stop()

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

        # ---- 撞方块
        hit = False
        for blk in self.blocks:
            if not blk.alive:
                continue
            if self.ball.overlaps(blk.body):
                blk.alive = False
                self.score += SCORE_PER_BLOCK
                hit = True
                self.pops.append(Pop(blk.body.x + BLOCK_W / 2,
                                     blk.body.y + BLOCK_H / 2))
        if hit:
            self.squash = 1.0
            self._flash = 1.0

        self.blocks = [b for b in self.blocks if b.alive]

        # ---- 通关
        if not self.blocks and not self.over:
            self.score += CLEAR_BONUS_SCORE
            self.time_left = min(ROUND_TIME, self.time_left + CLEAR_BONUS_TIME)
            self.round_no += 1
            self._reset_round()

    def _finish(self) -> None:
        self.over = True
        if self.score > self.cfg.best_score:
            self.cfg.best_score = self.score
            self.cfg.save()
        earned = self._award_coins()
        self.label_title.setText(f"时间到！本局得分 {self.score}")
        self.label_sub.setText(
            f"最高分 {self.cfg.best_score}    通过 {self.round_no} 轮    "
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
            g.setColorAt(0.0, blk.color.lighter(118))
            g.setColorAt(1.0, blk.color)
            p.fillPath(path, g)
            p.setPen(QPen(blk.color.darker(135), 2))
            p.drawPath(path)
            # 高光
            p.setPen(QPen(QColor(255, 255, 255, 150), 3))
            p.drawLine(r.x() + 10, r.y() + 7, r.x() + r.width() - 12, r.y() + 7)

    def _paint_pops(self, p: QPainter) -> None:
        for pop in self.pops:
            t = pop.life / pop.max_life
            alpha = int(255 * (1 - t))
            for vx, vy in pop.shards:
                px = pop.x + vx * pop.life
                py = pop.y + vy * pop.life + 0.5 * 900 * pop.life ** 2
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(255, 190, 110, alpha))
                p.drawEllipse(int(px), int(py), 6, 6)
            if t < 0.6:
                f = ui_font(12, bold=True)
                p.setFont(f)
                p.setPen(QColor(240, 130, 60, int(255 * (1 - t / 0.6))))
                p.drawText(int(pop.x - 20), int(pop.y - 12 - 26 * t), 60, 20,
                           Qt.AlignmentFlag.AlignCenter, f"+{SCORE_PER_BLOCK}")

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

        p.setPen(QColor(48, 56, 70))
        p.setFont(ui_font(15, bold=True))
        p.drawText(20, 0, 200, HUD_H, Qt.AlignmentFlag.AlignVCenter,
                   f"得分 {self.score}")

        p.setFont(ui_font(11))
        p.setPen(QColor(120, 130, 148))
        p.drawText(210, 0, 180, HUD_H, Qt.AlignmentFlag.AlignVCenter,
                   f"最高 {max(self.cfg.best_score, self.score)}")

        # 右侧从左到右：轮次 -> 剩余秒数 -> 倒计时进度条，三段互不重叠
        bw, bh = 240, 12
        bx = W - bw - 24
        by = (HUD_H - bh) // 2

        p.setFont(ui_font(11, bold=True))
        p.setPen(QColor(70, 80, 95))
        p.drawText(bx - 190, 0, 100, HUD_H,
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                   f"第 {self.round_no} 轮")
        p.drawText(bx - 82, 0, 74, HUD_H,
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                   f"{int(math.ceil(self.time_left))}s")

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(232, 236, 244))
        p.drawRoundedRect(bx, by, bw, bh, 6, 6)
        ratio = max(0.0, min(1.0, self.time_left / ROUND_TIME))
        p.setBrush(QColor(120, 200, 150) if ratio > 0.3 else QColor(240, 140, 120))
        p.drawRoundedRect(bx, by, int(bw * ratio), bh, 6, 6)

        p.setFont(ui_font(9))
        p.setPen(QColor(150, 158, 172))
        p.drawText(20, HUD_H + 8, W - 40, 24, Qt.AlignmentFlag.AlignLeft,
                   "← → 移动     空格 / 点击 起跳     R 重开     Esc 退出")
