"""帧动画播放器。

和 Qt 解耦：它只管"当前该播第几帧"，不关心谁来绘制。这样小游戏里
也能直接复用它来播宠物的动作帧。
"""

from __future__ import annotations


class Animator:
    """按固定帧率推进帧索引。

    loop=True  循环播放，返回当前帧
    loop=False 播到最后一帧就停住，finished 置 True
    """

    def __init__(self, fps: float = 10.0, loop: bool = True):
        self.fps = max(0.5, float(fps))
        self.loop = loop
        self._count = 0
        self.index = 0
        self.finished = False
        self._acc = 0.0              # 已累积时间，单位秒

    # ------------------------------------------------------------ 控制

    def play(self, frame_count: int, fps: float | None = None,
             loop: bool | None = None, restart: bool = False) -> None:
        """切换动画。参数不变时不会打断当前播放进度。"""
        fps = self.fps if fps is None else max(0.5, float(fps))
        loop = self.loop if loop is None else loop
        changed = (frame_count != self._count or fps != self.fps or loop != self.loop)

        self._count = max(1, int(frame_count))
        self.fps = fps
        self.loop = loop

        if changed or restart:
            self.index = 0
            self._acc = 0.0
            self.finished = False

    def reset(self) -> None:
        self.index = 0
        self._acc = 0.0
        self.finished = False

    # ------------------------------------------------------------ 推进

    def update(self, dt: float) -> bool:
        """推进 dt 秒，返回"当前帧索引是否发生变化"。"""
        if self.finished or self._count <= 1:
            return False

        self._acc += dt
        step = 1.0 / self.fps
        moved = False
        while self._acc >= step:
            self._acc -= step
            nxt = self.index + 1
            if nxt >= self._count:
                if self.loop:
                    self.index = 0
                else:
                    self.index = self._count - 1
                    self.finished = True
            else:
                self.index = nxt
            moved = True
            if self.finished:
                break
        return moved

    # ------------------------------------------------------------ 状态

    @property
    def count(self) -> int:
        return self._count

    @property
    def progress(self) -> float:
        """单次播放的进度 0..1，用于需要按动画时间联动物理的地方。"""
        if self._count <= 1:
            return 1.0
        return min(1.0, self.index / (self._count - 1))
