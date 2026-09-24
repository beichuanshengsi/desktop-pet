"""番茄钟：帮用户掐一段专注时间，到点了让狗来叫他。

一个纯粹的计时器 —— ``start(minutes)`` 开始、``tick(dt)`` 推进、**到点那一次**
``tick`` 返回 ``True``。不依赖 Qt、不认识窗口，所以测试喂固定步长就能验证
（跟 ``behavior.Brain`` / ``physics.Motion`` 一个路数）。

为什么不塞进窗口
----------------
窗口已经管着状态机、物理、菜单、计时器，再混一个"到点了没有"的判定进去，
想单独验证"25 分钟真的会到点"就得把整个窗口跑起来。分开之后这条逻辑
用几毫秒就能跑完。

关于精度
--------
累加窗口喂进来的 ``dt``，而不是记一个"结束时刻"去和系统时钟比：
窗口的 ``dt`` 本来就是 ``perf_counter`` 之差、而且夹住过卡顿，
累加它和拿时间戳相减等价，但不依赖系统时钟有没有被改过。

**"到点"只在那一帧返回一次**（返回后自己停下），所以调用方不需要再去重 ——
如果写成"剩余 <= 0 就返回 True"，那它会每帧都喊一次，提醒会连成一片。
"""

from __future__ import annotations

import math

#: 允许的时长范围（分钟）。下限只是防呆，实际的档位由菜单定。
MIN_MINUTES = 0.05
MAX_MINUTES = 180.0


class Pomodoro:
    """一轮倒计时。"""

    def __init__(self) -> None:
        self._total = 0.0               # 本轮总时长（秒）
        self._left = 0.0                # 剩余（秒）
        self.running = False
        #: 累计完成过几轮 —— 只有长期开着的程序才用得上，但留着比将来补强。
        self.finished_rounds = 0

    # ------------------------------------------------------------ 控制

    def start(self, minutes: float) -> float:
        """开始一轮。返回**实际采用**的分钟数（越界会被夹住）。"""
        m = max(MIN_MINUTES, min(MAX_MINUTES, float(minutes)))
        self._total = m * 60.0
        self._left = self._total
        self.running = True
        return m

    def stop(self) -> None:
        """取消。剩余与进度一并归零。"""
        self.running = False
        self._total = 0.0
        self._left = 0.0

    def tick(self, dt: float) -> bool:
        """推进 dt 秒；**刚好到点**返回 True（同一轮只返回一次）。"""
        if not self.running:
            return False
        self._left -= max(0.0, float(dt))
        if self._left > 0.0:
            return False
        self._left = 0.0
        self.running = False
        self.finished_rounds += 1
        return True

    # ------------------------------------------------------------ 读取

    @property
    def remaining(self) -> float:
        """剩余秒数。"""
        return max(0.0, self._left)

    @property
    def remaining_minutes(self) -> float:
        return self.remaining / 60.0

    @property
    def total_minutes(self) -> float:
        """本轮设定的总时长（分钟）。停下来之后仍然保留 ——
        提醒文案要说"25 分钟到了"，那时倒计时已经归零、只剩这一份记录。"""
        return self._total / 60.0

    @property
    def progress(self) -> float:
        """已走过的比例 0..1。没在跑就是 0。"""
        if self._total <= 0.0:
            return 0.0
        return max(0.0, min(1.0, 1.0 - self._left / self._total))

    def label(self) -> str:
        """菜单上显示的剩余时间，形如 ``24:31``。"""
        total = int(math.ceil(self.remaining))
        return f"{total // 60:02d}:{total % 60:02d}"
