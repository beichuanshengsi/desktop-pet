"""宠物的屏幕运动。

刻意不依赖 Qt：只要给一个矩形边界就能跑，所以小游戏里的球体、
桌面上的重力下坠，用的是同一份代码。

坐标一律用屏幕像素，原点在屏幕左上角。

本模块管两件事：

* ``Motion`` —— 一个受重力、会撞墙的方形物体（``update`` 推进、``throw`` 给初速）。
* ``VelocitySampler`` / ``clamp_fling`` —— 从一串鼠标位置里估手速，把"甩出去"
  这件事收拾成两个数。它是物理问题，不该散在窗口的鼠标回调里。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from time import perf_counter


@dataclass
class Motion:
    """一个受重力、可被拖拽、会撞墙的方形物体。"""

    x: float = 0.0
    y: float = 0.0
    w: float = 128.0
    h: float = 128.0

    vx: float = 0.0
    vy: float = 0.0

    gravity: float = 2200.0          # px/s^2
    restitution: float = 0.30        # 落地反弹系数
    edge_bounce: bool = False        # 撞左右边界是否反弹（桌宠刹住，球类反弹）
    ground_friction: float = 2400.0  # 落地后水平减速度 px/s^2
    max_fall_speed: float = 2600.0

    on_ground: bool = False
    events: dict = field(default_factory=dict)

    # ------------------------------------------------------------ 操作

    def teleport(self, x: float, y: float) -> None:
        self.x, self.y = float(x), float(y)
        self.vx = self.vy = 0.0

    def throw(self, vx: float, vy: float) -> None:
        self.vx, self.vy = float(vx), float(vy)
        if vy < 0:
            self.on_ground = False

    def stop(self) -> None:
        self.vx = self.vy = 0.0

    # ------------------------------------------------------------ 步进

    def update(self, dt: float, bounds: tuple[float, float, float, float],
               use_gravity: bool = True) -> dict:
        """步进 dt 秒。

        bounds = (left, top, right, bottom)，right/bottom 是边界本身（含）。

        返回事件字典，键可能包含：
            landed   本步落地
            bounced  本步发生过弹起
            edge     -1 撞左边界 / 1 撞右边界 / 0 未撞
            ceiling  撞到顶
        """
        dt = max(0.0, min(dt, 0.05))          # 卡顿时夹住 dt，防止穿模
        left, top, right, bottom = bounds
        ev = {"landed": False, "bounced": False, "edge": 0, "ceiling": False}

        if use_gravity:
            self.vy = min(self.max_fall_speed, self.vy + self.gravity * dt)

        # ---- 水平
        self.x += self.vx * dt
        if self.x < left:
            self.x = left
            if self.edge_bounce:
                self.vx = abs(self.vx) * self.restitution
            else:
                self.vx = 0.0
            ev["edge"] = -1
        elif self.x + self.w > right:
            self.x = right - self.w
            if self.edge_bounce:
                self.vx = -abs(self.vx) * self.restitution
            else:
                self.vx = 0.0
            ev["edge"] = 1

        # ---- 垂直
        self.y += self.vy * dt
        if self.y < top:
            self.y = top
            self.vy = abs(self.vy) * self.restitution
            ev["ceiling"] = True

        floor = bottom - self.h
        if self.y >= floor:
            self.y = floor
            if self.vy > 90.0:                # 还有速度就弹一下
                self.vy = -self.vy * self.restitution
                ev["bounced"] = True
                self.on_ground = False
            else:                             # 速度足够小就判定站住
                self.vy = 0.0
                if not self.on_ground:
                    ev["landed"] = True
                self.on_ground = True
        else:
            self.on_ground = False

        # ---- 落地摩擦
        if self.on_ground and self.vx:
            if abs(self.vx) <= self.ground_friction * dt:
                self.vx = 0.0
            else:
                self.vx -= self.ground_friction * dt * (1 if self.vx > 0 else -1)

        self.events = ev
        return ev

    # ------------------------------------------------------------ 便捷属性

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.w / 2.0, self.y + self.h / 2.0)

    def rect(self) -> tuple[float, float, float, float]:
        return (self.x, self.y, self.x + self.w, self.y + self.h)

    def overlaps(self, other: "Motion") -> bool:
        ax0, ay0, ax1, ay1 = self.rect()
        bx0, by0, bx1, by1 = other.rect()
        return not (ax1 <= bx0 or bx1 <= ax0 or ay1 <= by0 or by1 <= ay0)


# ---------------------------------------------------------------- 甩出去
#
# 拖动本来只是"搬位置"：松手时窗口会走 ``_sync_from_window()`` 把物理状态
# 对齐到窗口坐标，顺手把速度清零。于是 ``Motion.throw()`` 和 ``edge_bounce``
# 这一整套（写小游戏时就有了）在桌宠身上一直没人用 —— 狗永远甩不出去。
#
# 要接上它，缺的只有"手速"这一个输入。鼠标事件本身不带速度，只能自己估。

#: 采样窗口（秒）。只取最近这么久的位置点算速度。
#:
#: 不能用"最后两次事件"求差：鼠标事件间隔是抖的（跟回报率、系统负载都有关），
#: 相邻两次可能只隔 1ms，一除就是几千 px/s 的鬼数。取一小段时间的**首尾两点**
#: 就没有这个问题，而且这个时长恰好等于"人感觉自己甩了一下"的时长。
FLING_WINDOW = 0.14

#: 低于这个速度（px/s）不算甩，按平常放下处理。
#: 没有它，手抖一下狗就飞了 —— 拖到目的地再松手是最常见的动作。
FLING_MIN = 130.0

#: 甩出去的速度上限（px/s）。不夹住的话一次快速拖动就是几千 px/s，
#: 狗会直接瞬移到屏幕外再"掉"回来，看着像 bug。
FLING_MAX = 2200.0

#: 被甩出去时的落地反弹系数。比默认的 0.30 小一点：
#: 0.30 会让狗在地上蹦好几下才停，桌宠不该那么活跃。
FLING_RESTITUTION = 0.18


class VelocitySampler:
    """从最近一小段时间的位置采样里估手速。

    纯逻辑、不依赖 Qt，``t`` 可以注入 —— 测试能直接喂一串假的 ``(x, y, t)``
    验证"甩得快 / 甩得慢 / 没动"三种情况，不需要真的去拖窗口。
    """

    def __init__(self, window: float = FLING_WINDOW, max_samples: int = 24):
        self.window = max(0.02, float(window))
        self.max_samples = max(2, int(max_samples))
        self._pts: list[tuple[float, float, float]] = []

    def clear(self) -> None:
        self._pts.clear()

    def add(self, x: float, y: float, t: float | None = None) -> None:
        """记一个采样点。``t`` 省略就用当前时刻（窗口那边就是这么调的）。"""
        now = perf_counter() if t is None else float(t)
        self._pts.append((now, float(x), float(y)))

        cutoff = now - self.window
        # 至少留两个点 —— 只剩一个就算不出速度了，那样等于每次松手都没甩
        while len(self._pts) > 2 and self._pts[0][0] < cutoff:
            self._pts.pop(0)
        if len(self._pts) > self.max_samples:
            del self._pts[:-self.max_samples]

    def velocity(self) -> tuple[float, float]:
        """``(vx, vy)``，单位 px/s。样本不足或时间差太小就返回 ``(0, 0)``。"""
        if len(self._pts) < 2:
            return (0.0, 0.0)
        t0, x0, y0 = self._pts[0]
        t1, x1, y1 = self._pts[-1]
        dt = t1 - t0
        if dt <= 1e-3:
            return (0.0, 0.0)
        return ((x1 - x0) / dt, (y1 - y0) / dt)

    @property
    def samples(self) -> int:
        """当前攒了几个点（测试与调试用）。"""
        return len(self._pts)


def clamp_fling(vx: float, vy: float) -> tuple[float, float]:
    """把估出来的手速收拾成能直接喂给 ``Motion.throw`` 的两个数。

    太轻（低于 ``FLING_MIN``）当作没甩，猛过头就按比例缩到 ``FLING_MAX`` ——
    缩的是**速度大小**、方向原样保留，所以"往左上使劲甩"还是往左上飞。
    """
    speed = math.hypot(float(vx), float(vy))
    if speed < FLING_MIN:
        return (0.0, 0.0)
    if speed > FLING_MAX:
        k = FLING_MAX / speed
        return (float(vx) * k, float(vy) * k)
    return (float(vx), float(vy))
