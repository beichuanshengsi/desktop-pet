"""番茄钟：帮用户掐一段专注时间，到点了让狗来叫他。

一个纯粹的计时器 —— ``start(seconds)`` 开始、``tick(dt)`` 推进、**到点那一次**
``tick`` 返回 ``True``。不依赖 Qt、不认识窗口，所以测试喂固定步长就能验证
（跟 ``behavior.Brain`` / ``physics.Motion`` 一个路数）。

为什么不塞进窗口
----------------
窗口已经管着状态机、物理、菜单、计时器，再混一个"到点了没有"的判定进去，
想单独验证"25 分钟真的会到点"就得把整个窗口跑起来。分开之后这条逻辑
用几毫秒就能跑完。

为什么单位是**秒**而不是分钟
---------------------------
原来只有 25 / 50 两个菜单档位，用分钟当单位最省事。现在时长由用户在滚轮上
**自己滚**出来，范围是 1 秒 ~ 2 小时 —— 到这一档，分钟已经不够用了：
"45 秒"在分钟制下是 0.75，四舍五入就变成 1 分钟。所以内部统一存秒，
和界面的"时 / 分 / 秒"三列一一对应，中间不再有换算损耗。

分钟只是**显示层的说法**（``describe()`` 把秒说成人话），不是存储单位。

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

#: 允许的时长范围（秒）。滚轮只能滚出这个区间内的值，
#: ``start()`` 也会再夹一次 —— 界面是界面的防呆，这里是数据的防呆。
MIN_SECONDS = 1.0
MAX_SECONDS = 7200.0             # 2 小时

#: 滚轮"时"那一列的上限，由 ``MAX_SECONDS`` 推出来（2 小时 → 0/1/2）。
MAX_HOURS = int(MAX_SECONDS // 3600)


def clamp_seconds(value: float) -> float:
    """把任意时长夹进 ``[MIN_SECONDS, MAX_SECONDS]``。

    非数字给下限（1 秒）而不是崩：滚轮、存档、测试都可能喂进脏数据，
    这条路径上抛异常只会让桌宠整个起不来。
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return MIN_SECONDS
    if math.isnan(v):
        return MIN_SECONDS
    return max(MIN_SECONDS, min(MAX_SECONDS, v))


def hms(seconds: float) -> tuple[int, int, int]:
    """秒数 → ``(时, 分, 秒)``。滚轮三列、提醒文案都从这里取，避免各拆各的。

    **这里不做 1 秒下限夹紧**，只保证不是负数。原因是有两个"合法的 0"：
    ``剩余 0 秒``要显示成 ``00:00``（倒计时归零了），而 ``设定 0 秒``是个
    非法时长、要夹成 1 秒。夹紧的职责在 ``clamp_seconds`` / ``seconds_of`` 那边显式做，
    放在这里就会让"时间到"的读数是 ``00:01`` —— 一个只在到点那一瞬间出现、
    极难复现的显示 bug。
    """
    try:
        total = int(round(float(seconds)))
    except (TypeError, ValueError):          # 非数字、NaN、None 一律当 0
        total = 0
    total = max(0, total)
    h, rest = divmod(total, 3600)
    m, s = divmod(rest, 60)
    return h, m, s


def seconds_of(hours: int, minutes: int, seconds: int) -> float:
    """``(时, 分, 秒)`` → 秒数（已夹紧）。滚轮滚完就调它汇总。"""
    return clamp_seconds(int(hours) * 3600 + int(minutes) * 60 + int(seconds))


def format_clock(seconds: float) -> str:
    """倒计时读数：不到 1 小时是 ``24:31``，超过就是 ``1:05:03``。

    不做成永远 ``00:24:31``：25 分钟一轮是绝大多数场景，多出来的 ``00:``
    只是白占菜单宽度。
    """
    h, m, s = hms(seconds)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def describe(seconds: float) -> str:
    """把时长说成人话，用在提醒文案里：``25 分钟`` / ``45 秒`` / ``1 小时 5 分``。

    刻意**不写秒**在超过 1 小时后：``1 小时 5 分 3 秒到了`` 读起来像机器报时，
    用户要的是"起来动一动"，不是审计时长。
    """
    total = int(round(clamp_seconds(seconds)))
    if total >= 3600:
        h, m, _s = hms(total)
        return f"{h} 小时 {m} 分" if m else f"{h} 小时"
    if total >= 60:
        m, s = divmod(total, 60)
        return f"{m} 分 {s} 秒" if s else f"{m} 分钟"
    return f"{total} 秒"


class Pomodoro:
    """一轮倒计时。"""

    def __init__(self) -> None:
        self._total = 0.0               # 本轮总时长（秒）
        self._left = 0.0                # 剩余（秒）
        self.running = False
        #: 累计完成过几轮 —— 只有长期开着的程序才用得上，但留着比将来补强。
        self.finished_rounds = 0

    # ------------------------------------------------------------ 控制

    def start(self, seconds: float) -> float:
        """开始一轮。返回**实际采用**的秒数（越界会被夹住）。"""
        secs = clamp_seconds(seconds)
        self._total = secs
        self._left = secs
        self.running = True
        return secs

    def start_hms(self, hours: int, minutes: int, seconds: int) -> float:
        """按滚轮三列的值开始一轮。滚轮对话框直接调这个。"""
        return self.start(seconds_of(hours, minutes, seconds))

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
    def total_seconds(self) -> float:
        """本轮设定的总时长（秒）。停下来之后仍然保留 ——
        提醒文案要说"25 分钟到了"，那时倒计时已经归零、只剩这一份记录。"""
        return self._total

    @property
    def progress(self) -> float:
        """已走过的比例 0..1。没在跑就是 0。"""
        if self._total <= 0.0:
            return 0.0
        return max(0.0, min(1.0, 1.0 - self._left / self._total))

    def label(self) -> str:
        """菜单上显示的剩余时间，形如 ``24:31``（超过 1 小时是 ``1:05:03``）。"""
        return format_clock(math.ceil(self.remaining))

    def describe_total(self) -> str:
        """本轮总时长的说法，形如 ``25 分钟``。到点提醒的文案用它。"""
        return describe(self._total)
