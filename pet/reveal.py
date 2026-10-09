"""抽卡翻牌浮层：抽到了什么，单独弹出来给你看。

为什么是**卡册的子控件**，而不是另开一个窗口
--------------------------------------------
1. 卡册本身已经是一个独立顶层窗口。再开一个窗口就得自己管"跟着卡册移动 /
   卡册关掉它也关掉 / 幼儿模式里还要抬到遮罩之上"这一串事，一处漏了就变成
   "浮层留在屏幕上关不掉"；
2. 作为子控件铺满整册，它天然盖住卡册里所有按钮 —— 翻牌期间点不到「抽一次」，
   不会出现"动画还没放完又抽了一张"的错位；
3. 离屏截图时直接 ``panel.grab()`` 就能把浮层一起拍下来，验收脚本不用额外起窗口。

特效按稀有度分档
----------------
普通 → 传说：粒子数、光环层数、光晕亮度都递增（见 ``SPARK``）。
**这是整套收集系统里唯一"当场看得出稀有度"的反馈** —— 图鉴里的格子配色是
静态的、一眼扫过去分不出刚抽到的是哪一档，翻牌那一下的心跳才是抽卡的意义。

动画只跑 0.55 秒，而且**随时可以跳过**：抽卡是会连着做很多次的动作，
被迫看完每一次动画很快就会从"期待"变成"负担"。
"""

from __future__ import annotations

import math
import random

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QWidget

from . import uitheme
from .cards import Card

#: 每档的特效强度：``档位 -> (粒子数, 光环层数)``。
#: 键与 ``pet/cards.py`` 的 ``TIERS`` 一致；写成表而不是几个 if，
#: 是为了调参时四条档位能一屏看全、一眼比出梯度。
SPARK: dict[str, tuple[int, int]] = {
    "普通": (14, 1),
    "稀有": (24, 2),
    "史诗": (36, 3),
    "传说": (52, 4),
}


def ease_out_back(x: float, k: float = 1.9) -> float:
    """回弹缓动：冲过头一点点再收回来。

    "弹出来"的手感全靠这一点过冲 —— 线性放大出来的效果是"变大"，
    不是"弹出来"。``k`` 越大冲得越猛。
    """
    x = min(1.0, max(0.0, x))
    return 1.0 + (k + 1.0) * (x - 1.0) ** 3 + k * (x - 1.0) ** 2


class CardReveal(QWidget):
    """铺满卡册的翻牌浮层。整个界面都是画出来的，没有子控件。"""

    #: 动画总时长（秒）。0.55 是"看得见但不等人"的位置。
    DURATION = 0.55
    TICK_MS = 16

    #: 卡片本体的边长（像素）与内部留白。
    ART = 168
    PAD = 14

    #: 固定随机种子：粒子每次从同一串数出发，于是翻牌图能逐张比对
    #: （``tools/verify_reveal_ui.py`` 拿它当验收证据，见该脚本开头）。
    SEED = 20261009

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("reveal")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self.rng = random.Random(self.SEED)
        #: 这一次翻的是哪张卡。``None`` = 还没翻过（此时 paintEvent 直接返回）。
        self.card: Card | None = None
        self.label = ""
        self.thumb = QPixmap()
        self.is_new = False
        self.dup_count = 0

        self._t = 1.0                 # 动画进度 0..1
        self._done = True             # 已经停在终态（点击 = 收起，而不是跳过）
        self._sparks: list[tuple[float, float, float, float]] = []

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(self.TICK_MS)
        self._timer.timeout.connect(self._tick)
        self.hide()

    # ------------------------------------------------------------ 状态

    @property
    def tier(self) -> str:
        return self.card.tier if self.card is not None else "普通"

    @property
    def colour(self) -> QColor:
        return QColor(uitheme.TIER_COLOR.get(self.tier, uitheme.ACCENT))

    @property
    def progress(self) -> float:
        """动画进度 0..1（1 = 已经停在终态）。"""
        return self._t

    @property
    def done(self) -> bool:
        """动画放完了没有。跳过与收起的区别就看它。"""
        return self._done

    @property
    def sparks(self) -> int:
        """这一档放了多少颗粒子（测试与验收脚本用）。"""
        return len(self._sparks)

    # ------------------------------------------------------------ 开关

    def show_card(self, card: Card, label: str, thumb: QPixmap, *,
                  is_new: bool, dup_count: int = 0) -> None:
        """开始一次翻牌。``thumb`` 是卡面缩略图（卡册那边已经有缓存）。"""
        self.card = card
        self.label = label
        self.thumb = thumb
        self.is_new = is_new
        self.dup_count = dup_count
        self.rng.seed(self.SEED)              # 每次翻牌都从同一串粒子出发
        self._sparks = self._make_sparks()
        self._t = 0.0
        self._done = False

        parent = self.parentWidget()
        if parent is not None:                # 铺满整册（卡册是固定尺寸的）
            self.setGeometry(parent.rect())
        self.show()
        self.raise_()
        self.setFocus()
        self._timer.start()

    def advance(self) -> None:
        """点一下 / 按一下：动画没放完就跳到终态，放完了就收起来。

        **跳过是必须的**：抽卡是连着做很多次的动作，强迫看完每一次动画
        很快就会变成负担。所以任何一次点击都先把"等待"清掉。
        """
        if self._done:
            self.dismiss()
            return
        self._t = 1.0
        self._done = True
        self._timer.stop()
        self.update()

    def dismiss(self) -> None:
        """收起浮层。停表是必须的 —— 留着它在后台空转，下次翻牌会两个一起走。"""
        self._timer.stop()
        self.hide()

    def _tick(self) -> None:
        self._t = min(1.0, self._t + self.TICK_MS / 1000.0)
        if self._t >= 1.0:
            self._timer.stop()
            self._done = True
        self.update()

    def _make_sparks(self) -> list[tuple[float, float, float, float]]:
        """生成粒子：``(方向角, 飞多远, 起飞时刻, 半径)``。

        起飞时刻是错开的 —— 同时起飞看起来像爆炸，错开一点才像"飘"出来。
        """
        count, _ = SPARK.get(self.tier, SPARK["普通"])
        return [
            (self.rng.uniform(0.0, 360.0),
             self.rng.uniform(90.0, 300.0),
             self.rng.uniform(0.08, 0.30),
             self.rng.uniform(2.0, 5.0))
            for _ in range(count)
        ]

    # ------------------------------------------------------------ 事件

    def mousePressEvent(self, event) -> None:
        self.advance()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return,
                           Qt.Key.Key_Enter, Qt.Key.Key_Escape):
            self.advance()
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------ 绘制

    def paintEvent(self, event) -> None:
        if self.card is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        box = self.rect()
        colour = self.colour
        centre = QPointF(box.center().x(), box.center().y() - 34.0)

        self._paint_veil(p, box)
        self._paint_rings(p, centre, colour)
        self._paint_sparks(p, centre, colour)
        self._paint_card(p, centre, colour)
        self._paint_text(p, box, centre, colour)
        p.end()

    # ---- 下面几个 _paint_* 都从 self._t 里读进度，不各自记状态：
    #      这样"跳过"只要把 _t 设成 1 就会同时生效，不会有一半动画还停在半路。

    def _paint_veil(self, p: QPainter, box) -> None:
        """把整册压暗。**这一层必须有**：不压暗的话翻出来的卡和卡册里的格子
        挤在一起，看不出"这一张是单独弹出来的"。"""
        alpha = int(206 * min(1.0, self._t / 0.22))
        if alpha <= 0:
            return
        veil = QColor(13, 17, 27)
        veil.setAlpha(alpha)
        p.fillRect(box, veil)

    def _paint_rings(self, p: QPainter, centre: QPointF, colour: QColor) -> None:
        """从卡后面往外扩的光环，层数按档位递增。"""
        _, layers = SPARK.get(self.tier, SPARK["普通"])
        p.setPen(Qt.PenStyle.NoPen)

        # 终态也留一圈柔和的光：扩出去的光环会淡到没有，要是没有这层，
        # 动画一停画面就"什么都不剩"，停在「点一下继续」时像一张普通贴图。
        # 半径要比卡片的**对角线一半**还大，不然整圈光都被卡片自己盖住，
        # 只在四个角上漏出一点，看着像渲染脏了。
        glow_alpha = int((30 + 15 * layers) * min(1.0, self._t / 0.35))
        if glow_alpha > 0:
            radius = self.ART * 0.95
            inner = QColor(colour)
            inner.setAlpha(glow_alpha)
            outer = QColor(colour)
            outer.setAlpha(0)
            grad = QRadialGradient(centre, radius)
            grad.setColorAt(0.0, inner)
            grad.setColorAt(0.55, inner)
            grad.setColorAt(1.0, outer)
            p.setBrush(grad)
            p.drawEllipse(centre, radius, radius)

        for i in range(layers):
            phase = min(1.0, max(0.0, (self._t - i * 0.06) / 0.42))
            if phase <= 0.0:
                continue
            radius = self.ART * (0.52 + 0.42 * phase)
            inner = QColor(colour)
            inner.setAlpha(int(120 * (1.0 - phase)))
            outer = QColor(colour)
            outer.setAlpha(0)
            grad = QRadialGradient(centre, radius)
            grad.setColorAt(0.0, inner)
            grad.setColorAt(0.72, inner)
            grad.setColorAt(1.0, outer)
            p.setBrush(grad)
            p.drawEllipse(centre, radius, radius)

    def _paint_sparks(self, p: QPainter, centre: QPointF, colour: QColor) -> None:
        p.setPen(Qt.PenStyle.NoPen)
        for angle, speed, delay, size in self._sparks:
            phase = min(1.0, max(0.0, (self._t - delay) / 0.55))
            if phase <= 0.0 or phase >= 1.0:
                continue
            rad = math.radians(angle)
            dist = self.ART * 0.5 + speed * phase
            pos = QPointF(centre.x() + math.cos(rad) * dist,
                          centre.y() + math.sin(rad) * dist * 0.78)
            dot = QColor(colour).lighter(135)
            dot.setAlpha(int(220 * (1.0 - phase)))
            p.setBrush(dot)
            p.drawEllipse(pos, size, size)

    def _paint_card(self, p: QPainter, centre: QPointF, colour: QColor) -> None:
        """卡片本体：前半段横向"翻"出来，后半段整体"弹"一下。"""
        flip = min(1.0, self._t / 0.30)                 # 翻：0 → 1
        grow = ease_out_back(min(1.0, self._t / 0.42))  # 弹：可以过冲
        side = self.ART * (0.72 + 0.28 * grow)
        sx = max(0.02, flip)                            # 不能真给 0，0 宽画不出来

        p.save()
        p.translate(centre)
        p.scale(sx, 1.0)
        frame = QRectF(-side / 2.0, -side / 2.0, side, side)

        glow = QColor(colour)
        glow.setAlpha(int(90 * self._t))
        p.setPen(QPen(glow, 10.0))
        p.setBrush(QColor("#ffffff"))
        p.drawRoundedRect(frame, 18.0, 18.0)

        p.setPen(QPen(colour, 3.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(frame, 18.0, 18.0)

        if not self.thumb.isNull():
            room = max(8, int(side) - 2 * self.PAD)
            art = self.thumb.scaled(room, room,
                                    Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(int(-art.width() / 2), int(-art.height() / 2), art)
        p.restore()

    def _paint_text(self, p: QPainter, box, centre: QPointF,
                    colour: QColor) -> None:
        """卡名 + 结果 + 提示。字比卡晚出现一点，不然像一张贴纸。"""
        if self._t < 0.40:
            return
        fade = min(1.0, (self._t - 0.40) / 0.30)

        top = centre.y() + self.ART * 0.60
        p.setFont(uitheme.ui_font(13, bold=True))
        p.setPen(self._tinted(QColor("#ffffff"), fade))
        p.drawText(QRectF(box.left(), top, box.width(), 26.0),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                   self.label)

        tag = "新收集！" if self.is_new else f"重复（已有 {self.dup_count} 张）"
        tag_colour = QColor(colour).lighter(125) if self.is_new \
            else QColor("#b9c2d0")
        p.setFont(uitheme.ui_font(10, bold=self.is_new))
        p.setPen(self._tinted(tag_colour, fade))
        p.drawText(QRectF(box.left(), top + 26.0, box.width(), 22.0),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, tag)

        p.setFont(uitheme.ui_font(9))
        p.setPen(self._tinted(QColor("#8d97a8"), fade))
        p.drawText(QRectF(box.left(), box.bottom() - 36.0, box.width(), 20.0),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                   "点一下继续" if self._done else "点一下跳过")

    @staticmethod
    def _tinted(colour: QColor, fade: float) -> QColor:
        out = QColor(colour)
        out.setAlpha(int(255 * min(1.0, max(0.0, fade))))
        return out
