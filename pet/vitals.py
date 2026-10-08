"""养成状态：饱食 / 心情 / 精力。

三条都是 0..100 的数，只做三件事：**随时间掉、被互动补、跌破阈值就"有事"**。

本模块刻意不依赖 Qt、不读盘、不认识窗口 —— 跟 ``physics.Motion`` 与
``behavior.Brain`` 同一种做法：把"会变的数"收在一处，界面层只负责显示和喂事件。
于是它能被单独跑测试，也能被将来的别的界面（托盘气泡、通知）复用。

为什么要有这一层
----------------
在这之前，桌宠只有 ``Config.feed_count`` / ``play_count`` 两个累计计数器：
喂了 11 次、逗了 52 次，**狗本身没有任何变化**。互动不留后果，就没有回来的理由。
这一层让那两次点击第一次有了意义 —— 喂一口它真的会饱，逗它玩它真的会开心，
而"久不理它"也真的会饿、会蔫、会困。

时间用真实秒数
--------------
衰减按**真实经过的秒数**算，不是按帧数：程序挂在那儿不动、系统卡顿掉帧，
都不该影响"过了多久"。窗口那边会传真实 dt 进来（它本来就有）。

离线衰减
--------
关掉程序期间也要掉，否则"关了就没人管"成了最优解。但两条保护：

* **掉得比在线慢**（它在家睡觉），见 ``OFFLINE_PER_HOUR``；
* **掉不到 0**（``OFFLINE_FLOOR``）—— 回来看到一只饿到濒死的狗只会让人内疚，
  不会让人想喂它。留一口气，"它饿了，去喂一下"这个念头才成立。

超过 ``OFFLINE_CAP_HOURS`` 的部分不再累加：出差一周回来和出差一天回来，
看到的应该是同一只"有点饿"的狗。
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------- 取值范围

MIN = 0.0
MAX = 100.0

#: 初始值。第一天打开时不该是"满分"—— 留一点空间，喂它一口立刻有反馈。
START = 78.0

# ---------------------------------------------------------------- 在线衰减（每分钟）

#: 清醒时各值每分钟掉多少。按"从满到空"折算：
#: 饱食约 8 小时、心情约 10 小时、精力约 6 小时。
#:
#: 第一版定的是 0.55 / 0.35 / 0.45（3 小时见底），实测太凶 —— 挂着工作一小时
#: 就掉掉三分之一，桌宠从"陪伴"变成了"催命"。养成节奏要按**半天**这个尺度来：
#: 一小时无感、一下午有点饿、一整天不管才会见底。
SATIETY_PER_MIN = 0.21
MOOD_PER_MIN = 0.16
ENERGY_PER_MIN = 0.28

#: 睡觉时精力回升速度：约 14 分钟从空回到满。
#: 精力掉到 ``TIRED_AT`` 就会自己去睡，所以一天会睡上几次、每次十几分钟。
ENERGY_REST_PER_MIN = 6.0

#: 睡觉时其它两项的变化（饿得慢一点、心情回一点）
SATIETY_PER_MIN_ASLEEP = 0.20
MOOD_PER_MIN_ASLEEP = 0.18

# ---------------------------------------------------------------- 离线衰减

#: 离线每小时掉多少（三项同速，简单可预期）
OFFLINE_PER_HOUR = 6.0
#: 离线最多掉到这个值，**不会更低**
OFFLINE_FLOOR = 30.0
#: 超过这么多小时的部分不再计入
OFFLINE_CAP_HOURS = 12.0

# ---------------------------------------------------------------- 互动提升

#: 投喂一次补多少饱食。**这是"每天一次免费"那份的量** ——
#: 免费额度用完之后，「喂一口」吃的是背包里的东西，加的是那样东西自己的效果。
FEED_GAIN = 26.0
#: 逗它玩一次补多少心情。
#:
#: 从 22 降到 8。逗它玩是**纯陪伴**、不该收费（玩具球是"更好的玩具"，
#: 不是"能玩的许可证"），但 22 和玩具球的 35 只差 13 点，而一个不要钱、
#: 一个要 18 个金币，买球就显得很不值。拉开到 8 之后两条路的分工才立住：
#: 免费的费力而收益小，花钱的省力而收益大。
PLAY_GAIN = 8.0
#: 逗它玩花掉多少精力。**独立常量，不跟着 ``PLAY_GAIN`` 一起缩** ——
#: 玩一次的体力消耗是"玩"这个动作的属性，不是收益的属性；而且精力只有
#: 睡觉能回（商店不卖），留着它才让"逗它玩"仍然有成本、不能无限刷。
PLAY_ENERGY_COST = 3.3

# ---------------------------------------------------------------- 阈值

#: 饱食低于这个值算"饿"
HUNGRY_AT = 30.0
#: 心情低于这个值算"蔫"
SAD_AT = 30.0
#: 精力低于这个值算"困"（会去趴着睡）
TIRED_AT = 25.0
#: 精力回到这个值以上算"睡饱了"（自然醒）
RESTED_AT = 82.0

#: 三项的字段名与中文名 —— 商店、菜单、描述都从这里取，别各写一份
FIELDS: tuple[tuple[str, str], ...] = (
    ("satiety", "饱食"),
    ("mood", "心情"),
    ("energy", "精力"),
)

LABEL: dict[str, str] = dict(FIELDS)

#: 每一项"该管了"时的说法。键与 ``FIELDS`` 的字段名一一对应 ——
#: 菜单那行提醒、状态面板的红字、悬停气泡都用它，说法只有这一份。
ALERT_LABEL: dict[str, str] = {
    "satiety": "饿了",
    "mood": "有点蔫",
    "energy": "困了",
}


def _clamp(value: float) -> float:
    return max(MIN, min(MAX, float(value)))


@dataclass
class Vitals:
    """一只狗此刻的三条状态值。"""

    satiety: float = START
    mood: float = START
    energy: float = START

    # ------------------------------------------------------------ 取值

    def get(self, field: str) -> float:
        return _clamp(getattr(self, field, MIN))

    def clamp(self) -> None:
        self.satiety = _clamp(self.satiety)
        self.mood = _clamp(self.mood)
        self.energy = _clamp(self.energy)

    # ------------------------------------------------------------ 变化

    def awake(self, dt: float) -> None:
        """清醒时推进 dt 秒（衰减三项）。"""
        k = max(0.0, float(dt)) / 60.0
        self.satiety -= SATIETY_PER_MIN * k
        self.mood -= MOOD_PER_MIN * k
        self.energy -= ENERGY_PER_MIN * k
        self.clamp()

    def rest(self, dt: float) -> None:
        """睡觉时推进 dt 秒：精力回升，饿得慢，心情也回一点。"""
        k = max(0.0, float(dt)) / 60.0
        self.energy += ENERGY_REST_PER_MIN * k
        self.satiety -= SATIETY_PER_MIN_ASLEEP * k
        self.mood += MOOD_PER_MIN_ASLEEP * k
        self.clamp()

    def feed(self, amount: float = FEED_GAIN) -> None:
        """喂一口。"""
        self.satiety = _clamp(self.satiety + amount)

    def play(self, amount: float = PLAY_GAIN) -> None:
        """逗它玩。玩是要花精力的 —— 但只花一点点，不能让它玩两下就困。"""
        self.mood = _clamp(self.mood + amount)
        self.energy = _clamp(self.energy - PLAY_ENERGY_COST)

    def boost(self, field: str, amount: float) -> None:
        """直接抬某一项（小卖部买来的东西走这里）。"""
        if field in LABEL:
            setattr(self, field, _clamp(self.get(field) + float(amount)))

    def offline(self, hours: float) -> None:
        """按离线时长补一次衰减。见模块开头的两条保护。"""
        if hours <= 0:
            return
        drop = OFFLINE_PER_HOUR * min(float(hours), OFFLINE_CAP_HOURS)
        for name, _label in FIELDS:
            cur = self.get(name)
            # min(cur, FLOOR) 保证"本来就比下限还低"时不会反被抬上来
            setattr(self, name, max(min(cur, OFFLINE_FLOOR), cur - drop))
        self.clamp()

    # ------------------------------------------------------------ 判定

    @property
    def hungry(self) -> bool:
        return self.satiety < HUNGRY_AT

    @property
    def sad(self) -> bool:
        return self.mood < SAD_AT

    @property
    def tired(self) -> bool:
        return self.energy < TIRED_AT

    @property
    def rested(self) -> bool:
        """睡饱了没有 —— 到这条线就自然醒。"""
        return self.energy >= RESTED_AT

    def alert_for(self, field: str) -> bool:
        """某一项现在是不是"该管了"。状态面板要给哪一条标红，问它。

        判断本身还是那三个属性（``hungry`` / ``sad`` / ``tired``）——
        这里只做"字段名 → 属性"的查表，不另写一遍阈值比较。
        另写一遍的后果是：改了 ``TIRED_AT`` 而漏改这里，面板就永远不标红。
        """
        return {"satiety": self.hungry, "mood": self.sad,
                "energy": self.tired}.get(field, False)

    def alerts(self) -> list[str]:
        """当前该管一管的那几件事，按 ``FIELDS`` 的顺序列出。

        **判断和措辞收在同一处**：``needs_attention``、``summary()``、
        状态面板的红字标记都从这里取。将来加第四项（比如"口渴"）只改
        ``FIELDS`` 和 ``ALERT_LABEL`` 两张表，三个地方一起跟上；
        散着写的话漏改的地方不会报错，只会少提醒一次 —— 那种错最难发现。
        """
        return [ALERT_LABEL[name] for name, _label in FIELDS
                if self.alert_for(name)]

    @property
    def needs_attention(self) -> bool:
        """三项里有没有哪一项掉到该管一管的程度。"""
        return bool(self.alerts())

    # ------------------------------------------------------------ 描述

    def summary(self) -> str:
        """一句话说它现在怎么样 —— 右键菜单顶上那一行。

        只说**不好的**那几件事：状态正常时反而要短（"状态不错"），
        不能让一行提示常年占着菜单的宽度。
        """
        bits = self.alerts()
        return "、".join(bits) if bits else "状态不错"

    def detail(self) -> str:
        """一行紧凑的三项数值，给小卖部当标题用。"""
        return "   ".join(f"{label} {self.get(name):.0f}" for name, label in FIELDS)

