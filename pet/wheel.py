"""滚轮选择器的**取值规则**（纯逻辑，不依赖 Qt）。

界面长什么样是 ``pet/wheel_dialog.py`` 的事；这个模块只回答一个问题：
**三列滚轮各自能滚出哪些数、互相怎么牵制、合起来是几秒。**

为什么要单独拆出来
------------------
"2 小时 30 分"这种组合**不存在**（上限就是 2 小时），"0 时 0 分 0 秒"
也不存在（下限是 1 秒）。这类边界如果写在绘制代码里，就只能靠"跑起来滚一下
看看对不对"来验证；放在这里，测试可以直接喂 ``scroll(列, 方向)`` 断言结果。

三列的联动规则（上限 2 小时 = 7200 秒，下限 1 秒）
--------------------------------------------------

    | 时 = 0 且 分 = 0 | 秒 只能 1..59   （不许出现 0，不然总时长是 0）  |
    | 时 = 0          | 分 0..59，秒 0..59                                |
    | 时 = 1          | 分 0..59，秒 0..59（最大 1:59:59，仍在 2 小时内） |
    | 时 = 2          | 分、秒 都只能是 0（2:00:00 就是天花板）           |

**往"高"位滚会牵连低位**：从 1:30:50 把"时"滚到 2，分和秒会被清零，
不然就成了 2:30:50 —— 超出上限。反过来把"时"滚回 1 时，分秒停在 0
（不会"恢复"原来的 30:50）—— 这和日期选择器里"把月份改小、日期跟着夹"
是同一种行为，可预期比"记住上次"重要。

滚轮是**循环**的：在 1..59 这一列上往下滚一格，1 会绕到 59。
"滚轮下滑"的手感就来自这个循环，不循环就滚不到头也滚不到底。
"""

from __future__ import annotations

from dataclasses import dataclass

from .pomodoro import MAX_HOURS, MAX_SECONDS, MIN_SECONDS, hms, seconds_of

#: 三列的键与中文名。顺序即界面从左到右的顺序，也是"高位在前"的顺序。
COLUMNS: tuple[tuple[str, str], ...] = (
    ("h", "时"),
    ("m", "分"),
    ("s", "秒"),
)

#: 分 / 秒两列的满格值（滚出来的原始集合，再由联动规则裁）
FULL_CYCLE = 60

HOUR, MINUTE, SECOND = 0, 1, 2


@dataclass(frozen=True)
class Column:
    """某一列**此刻**的样子，绘制层照着它画就行。"""

    key: str
    label: str
    values: tuple[int, ...]     #: 这一列现在能滚出来的所有值（升序）
    index: int                  #: 当前停在第几格

    @property
    def value(self) -> int:
        return self.values[self.index]


class WheelModel:
    """时长滚轮的三列取值。所有边界规则都收在这里。"""

    def __init__(self, seconds: float | None = None):
        self._v: list[int] = [0, 0, 1]          # 时 / 分 / 秒
        if seconds is not None:
            self.set_value(seconds)

    # ------------------------------------------------------------ 取值

    def values(self, col: int) -> tuple[int, ...]:
        """该列此刻能滚出来的值。由**高位**决定，所以低位会随高位伸缩。"""
        h, m, _s = self._v
        if col == HOUR:
            return tuple(range(0, MAX_HOURS + 1))
        if col == MINUTE:
            return (0,) if h >= MAX_HOURS else tuple(range(0, FULL_CYCLE))
        if h >= MAX_HOURS:
            return (0,)
        if h == 0 and m == 0:
            return tuple(range(1, FULL_CYCLE))      # 不许 0：那样总时长是 0
        return tuple(range(0, FULL_CYCLE))

    def index(self, col: int) -> int:
        """当前值在 ``values(col)`` 里的下标。取不到时退到第一个 ——
        高位刚变窄时可能发生，``_settle()`` 会把它夹回来，但这中间不能抛异常。"""
        vals = self.values(col)
        try:
            return vals.index(self._v[col])
        except ValueError:
            return 0

    def current(self, col: int) -> int:
        return self.values(col)[self.index(col)]

    def columns(self) -> list[Column]:
        """三列的完整快照。绘制层每帧拿它，不自己算规则。"""
        return [Column(key, label, self.values(i), self.index(i))
                for i, (key, label) in enumerate(COLUMNS)]

    @property
    def value(self) -> float:
        """三列合起来是多少秒（已夹进合法区间）。"""
        return seconds_of(*self._v)

    # ------------------------------------------------------------ 改动

    def set_value(self, seconds: float) -> float:
        """把滚轮摆到某个时长上（打开对话框时用上次的选择）。"""
        self._v = list(hms(seconds))
        self._settle()
        return self.value

    def scroll(self, col: int, delta: int) -> None:
        """把某一列往上（``delta < 0``）或往下（``delta > 0``）滚若干格。

        循环：撞到头就从另一端绕回来（1..59 那列往下滚，1 → 59）。
        一次能滚多格，鼠标滚轮的加速度、拖动甩出去都靠这个 ``delta``。
        """
        vals = self.values(col)
        idx = (self.index(col) + int(delta)) % len(vals)
        # 先把这一列摆到目标格，再让联动规则去裁低位
        self._v[col] = vals[idx]
        self._settle()

    def choose(self, col: int, value: int) -> None:
        """直接跳到某个值（快捷档位按钮用）。值不在本列范围里就忽略。"""
        vals = self.values(col)
        if int(value) in vals:
            self._v[col] = int(value)
        else:
            # 不在范围里（比如点了"2 小时"而当下的分列只能是 0）：
            # 先把它能取的最接近值拿来用，保证按钮永远有反应
            self._v[col] = min(vals, key=lambda v: abs(v - int(value)))
        self._settle()

    # ------------------------------------------------------------ 收束

    def _settle(self) -> None:
        """把三列夹成一个**真实存在**的组合。见模块开头那张表。"""
        h, m, s = self._v
        h = max(0, min(MAX_HOURS, h))
        if h >= MAX_HOURS:
            m = s = 0                       # 2:00:00 就是天花板
        m = max(0, min(FULL_CYCLE - 1, m))
        s = max(0, min(FULL_CYCLE - 1, s))
        if h == 0 and m == 0 and s < MIN_SECONDS:
            s = int(MIN_SECONDS)            # 下限 1 秒
        self._v = [h, m, s]
        # 兜底：无论怎么组合都不该越过上限
        if seconds_of(h, m, s) > MAX_SECONDS:
            self._v = list(hms(MAX_SECONDS))
