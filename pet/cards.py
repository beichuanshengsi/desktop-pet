"""卡册与抽卡：把 104 张线条小狗变成一套能收集、能兑换、能装备的经济系统。

这是 v2.3.0 的新东西。它要解决的是一句很朴素的话：**攒金币得有地方花**。

在这之前，金币只有小卖部一个出口（肉干 12 / 玩具球 18 / 大餐 30），而三样
都是消耗品 —— 买完就没有"值得攒"的理由了。用户的原话是"没有值得攒钱的东西"。
于是有了这一层：一套 102 张的卡册，抽卡消耗金币、重复卡分解成碎片、
碎片攒够了换想要的档位，抽到的卡还能装到 5 个槽位上加速金币获取。

为什么是一个独立模块、且完全不认识 Qt
--------------------------------------
和 ``bag.Bag`` / ``vitals.Vitals`` / ``physics.Motion`` 一样：它是一份会变的
数据加上几条规则。抽卡概率、碎片折算、每周额度、保底计数、装备加成上限 ——
这些全都该在"没有窗口"的条件下几毫秒验完一遍。界面层（``album_panel`` /
``badge_bar``）只负责显示和转发点击。

状态存在哪儿
------------
**不另开一份内存副本，直接读写 ``Config`` 上那几个字段**（``cards`` /
``frag_low`` / ``frag_high`` / ``equipped`` / ``weekly_used`` …）。
理由：存档同步是一件极易出错的事 —— 副本和 ``cfg`` 只要有一处漏同步，
症状就是"抽到了卡，重启之后没了"。既然 ```PetWindow._persist`` 本来每 3 秒
就把 ``cfg`` 整个写一遍，让这里直接改 ``cfg`` 就自动被持久化了，一条多余的路都不用铺。

参数为什么集中写在文件头上
--------------------------
这套数字是**模拟出来的**（见 ``抽卡参数方案.md``：102 张池、
单抽 60 金币、26 周集齐），不是拍脑袋定的。调其中任何一个都要重跑模拟，
所以把它们摆在最显眼的地方、每个都写清楚它牵动什么 —— 散落在各处的话，
改了单抽价而没改兑换价，整条时间线就悄悄变了。
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import STAMP_FMT
from .paths import card_asset_dir

# ================================================================ 参数（定稿）
#
# 出处：``抽卡参数方案.md`` v1.1。改这里任何一个数之前先回去读那一节，
# 尤其是"只改单抽价 = 把整条时间线拉长"和"梯度靠差异化兑换价掰"两条。

#: 四个档位，从低到高。**顺序有语义**：卡册按它倒序陈列、加成的封顶
#: 按它算，别随手调。
TIERS: tuple[str, ...] = ("普通", "稀有", "史诗", "传说")

#: 每抽的出货概率（方案 A）。和必须为 1.0 —— 有测试盯着。
RATE: dict[str, float] = {"普通": 0.62, "稀有": 0.26, "史诗": 0.10, "传说": 0.02}

#: 单抽价。为什么是 60 而不是 25/50：装备系统会带来 16~19% 的恒定收入加成，
#: 把价格从 50 抬到 60 **正好抵消它**，集齐时间回到 25~26 周（半年）。
#: 换句话说，装备不是加速器，而是"回到原点"的机制 —— 没装备是 31 周，
#: 装满 5 槽才回到半年。这是刻意的，不是定价失误。
COIN_PER_PULL = 60

#: 重复卡分解出多少碎片：``档位 -> (碎片类型, 数量)``。
#: 普通/稀有给**低级**碎片，史诗/传说给**高级**碎片 —— 两条货币通道
#: 分开，是为了让"低换高"成为一个有代价的动作（5:1 且每周有限额）。
DISSOLVE: dict[str, tuple[str, int]] = {
    "普通": ("low", 2),
    "稀有": ("low", 6),
    "史诗": ("high", 4),
    "传说": ("high", 10),
}

#: 兑换价：``档位 -> (碎片类型, 数量)``。
#: **普 4 / 稀 24 这个 6 倍差就是整条难度梯度的支点** —— 只靠出率掰不过来
#: （普通 51 张、出率 62%，纯抽卡比稀有还慢），必须让"换一张稀有"显得贵。
COST: dict[str, tuple[str, int]] = {
    "普通": ("low", 4),
    "稀有": ("low", 24),
    "史诗": ("high", 16),
    "传说": ("high", 30),
}

#: 每周兑换额度（次）。跨周**不累积**：攒着额度的玩法会让"每周都来"失去意义。
WEEKLY_QUOTA: dict[str, int] = {"普通": 16, "稀有": 5, "史诗": 2, "传说": 1}

#: 低级碎片 → 高级碎片的汇率与**每周上限**（上限按消耗的低级碎片数计）。
#: 34 这个数是个刹车：它把高级碎片的产出卡住，从而把传说档停在第 25 周左右。
#: 改成 40 会让梯度更整齐（间距 4/4/4），但总时长缩到 24 周。
LOW_TO_HIGH_RATE = 5
LOW_TO_HIGH_CAP = 34

#: 兑换保底：同一档**连续 N 次兑到重复**，下一次必定给未拥有的。
#: 传说档只有 7 张，随机兑换的撞重复率高达 88%，这是纯长尾 ——
#: 只能靠保底打断，调价格无效。
GUARD = 3

#: 装备加成（金币获取）与硬顶。硬顶必须存在：5 张传说叠起来是 25%，
#: 那就超过了模拟时假设的 20%，整条时间线会跟着松掉。
EQUIP_BONUS: dict[str, float] = {"普通": 0.01, "稀有": 0.02, "史诗": 0.03, "传说": 0.05}
EQUIP_CAP = 0.20

#: 装备槽总数与解锁节奏：第 1~3 周 1 槽，之后每 3 周 +1，第 13 周满 5 槽。
#: 这是纯体验改进 —— 实测总时长与"一上来就 5 槽"**完全一样**，
#: 但第 2 周的加成从 13.1% 降到 3.7%，爬坡好看得多，每周都有"开新槽"的期待。
EQUIP_SLOTS = 5
SLOT_EVERY_WEEKS = 3


# ================================================================ 卡

@dataclass(frozen=True)
class Card:
    """一张卡。``id`` 是稳定标识（``c003``），存档里存的就是它。

    **不存文件名**：素材重命名、换一套卡池时，存档不该跟着失效。
    """

    id: str
    file: str
    tier: str


class CardPool:
    """全部卡 + 按档位分好的索引。只读。"""

    def __init__(self, cards=()):
        self._cards: tuple[Card, ...] = tuple(cards)
        self._by_id: dict[str, Card] = {c.id: c for c in self._cards}
        by_tier: dict[str, list[Card]] = {t: [] for t in TIERS}
        for c in self._cards:
            by_tier.setdefault(c.tier, []).append(c)
        self._by_tier: dict[str, tuple[Card, ...]] = {
            t: tuple(v) for t, v in by_tier.items()}

    # ------------------------------------------------------------ 查询

    def __len__(self) -> int:
        return len(self._cards)

    def __bool__(self) -> bool:
        return bool(self._cards)

    def all(self) -> tuple[Card, ...]:
        return self._cards

    def get(self, cid: str) -> Card | None:
        return self._by_id.get(cid)

    def by_tier(self, tier: str) -> tuple[Card, ...]:
        return self._by_tier.get(tier, ())

    def count_tier(self, tier: str) -> int:
        return len(self.by_tier(tier))

    def thumb_path(self, cid: str) -> Path:
        """缩略图的路径。文件未必存在（用户换素材时可能少放几张），
        调用方负责兜底 —— 这里只管按约定拼路径，不做 IO。"""
        return card_asset_dir() / "thumb" / f"{cid}.png"


_pool_cache: CardPool | None = None


def load_pool(path: Path | None = None, *, fresh: bool = False) -> CardPool:
    """读卡池清单（``assets/cards/cards.json``）。结果**缓存**，只在进程里读一次。

    读盘失败一律返回空池而不是抛异常：素材缺失是"卡册打不开"，
    不该是"桌宠起不来"。空池时界面会给出"没找到卡册素材"的说明。
    """
    global _pool_cache
    if _pool_cache is not None and not fresh:
        return _pool_cache

    target = path or (card_asset_dir() / "cards.json")
    cards: list[Card] = []
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
        for item in raw.get("cards", []):
            cid, tier = str(item.get("id", "")), str(item.get("tier", ""))
            if cid and tier in TIERS:
                cards.append(Card(cid, str(item.get("file", "")), tier))
    except (OSError, ValueError, AttributeError, TypeError):
        cards = []

    _pool_cache = CardPool(cards)
    return _pool_cache


def pool() -> CardPool:
    """全局卡池（懒加载）。给"只想算个加成"的调用方用。"""
    return load_pool()


# ================================================================ 结果对象

@dataclass(frozen=True)
class Pull:
    """一次抽卡的结果。"""

    card: Card
    is_new: bool                #: 是不是第一次拿到（图鉴 +1）
    dup_count: int              #: 这张现在一共有几张（含这一张）


@dataclass(frozen=True)
class Trade:
    """一次兑换的结果。**失败也要能说清为什么** —— 界面就靠 ``reason`` 那行字。"""

    ok: bool
    tier: str
    card: Card | None = None
    is_new: bool = False
    refund: int = 0             #: 撞重复时返还的碎片数
    reason: str = ""            #: 失败原因（人话，直接显示给用户）


# ================================================================ 周与槽位

def week_stamp(now: datetime | None = None) -> str:
    """当前这一周的标识，形如 ``2026-W41``（ISO 周）。

    额度按周重置，认的就是它。用 ISO 周而不是"距首次运行 7 天"——
    周额度是个日历概念，跨周那一下必须所有人都同时重置。
    """
    iso = (now or datetime.now()).isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


# ================================================================ 卡册

class Album:
    """一只狗的卡册 + 碎片 + 装备栏。

    所有状态都直接写在传进来的 ``cfg`` 上（见模块开头"状态存在哪儿"）。
    """

    def __init__(self, cfg, rng: random.Random | None = None, cards: CardPool | None = None):
        self.cfg = cfg
        self.pool = cards if cards is not None else pool()
        #: 抽卡的随机源。做成可注入的，测试里塞固定种子就能复现。
        self.rng = rng or random.Random()

    # ------------------------------------------------------------ 基础查询

    def count(self, cid: str) -> int:
        return int(self.cfg.cards.get(cid, 0))

    def is_owned(self, cid: str) -> bool:
        return self.count(cid) > 0

    def owned_kinds(self) -> int:
        """已收集的种类数（不是总张数）—— 图鉴进度看的是它。"""
        return sum(1 for c in self.pool.all() if self.is_owned(c.id))

    def total_kinds(self) -> int:
        return len(self.pool)

    def owned_kinds_of(self, tier: str) -> int:
        return sum(1 for c in self.pool.by_tier(tier) if self.is_owned(c.id))

    def cards_of(self, tier: str) -> tuple[Card, ...]:
        return self.pool.by_tier(tier)

    def all_cards(self) -> tuple[Card, ...]:
        return self.pool.all()

    def duplicates(self) -> int:
        """一共有多少张"多余的"（可以分解的）。"""
        return sum(max(0, n - 1) for n in self.cfg.cards.values())

    # ------------------------------------------------------------ 抽卡

    def pull_cost(self) -> int:
        return COIN_PER_PULL

    def can_pull(self) -> bool:
        return bool(self.pool) and self.cfg.coins >= COIN_PER_PULL

    def roll_tier(self) -> str:
        """按出率掷一个档位。"""
        r = self.rng.random()
        acc = 0.0
        for tier in TIERS:
            acc += RATE[tier]
            if r < acc:
                return tier
        return TIERS[-1]                       # 浮点累加的兜底

    def pull(self) -> Pull | None:
        """抽一次：扣金币、掷档位、从该档随机拿一张（可能重复）。

        金币不够或卡池是空的返回 ``None``。**判定在这里而不是界面上** ——
        按钮的灰只是提示，菜单搭好到点下去之间金币可能刚被结算改过。
        """
        if not self.can_pull():
            return None
        tier = self.roll_tier()
        choices = self.pool.by_tier(tier)
        if not choices:
            return None
        card = self.rng.choice(choices)
        self.cfg.coins -= COIN_PER_PULL
        n = self._grant(card.id)
        return Pull(card=card, is_new=(n == 1), dup_count=n)

    # ------------------------------------------------------------ 分解

    def can_dissolve(self, cid: str) -> bool:
        """能不能分解。**必须留一张** —— 分解掉最后一张等于把图鉴挖个洞，
        而"图鉴全亮"是这套系统唯一的长期目标。"""
        return self.count(cid) > 1

    def dissolve(self, cid: str) -> tuple[bool, int, str]:
        """分解一张**重复**的卡，返回 ``(成功, 得几个碎片, 碎片类型)``。"""
        card = self.pool.get(cid)
        if card is None or not self.can_dissolve(cid):
            return False, 0, ""
        kind, amount = DISSOLVE[card.tier]
        self._set_count(cid, self.count(cid) - 1)
        self._add_frag(kind, amount)
        return True, amount, kind

    # ------------------------------------------------------------ 兑换

    def week_used(self, tier: str) -> int:
        self.refresh_week()
        return int(self.cfg.weekly_used.get(tier, 0))

    def week_left(self, tier: str) -> int:
        return max(0, WEEKLY_QUOTA.get(tier, 0) - self.week_used(tier))

    def frag_of(self, kind: str) -> int:
        return int(self.cfg.frag_low if kind == "low" else self.cfg.frag_high)

    def exchange_block_reason(self, tier: str) -> str:
        """现在能不能兑换这一档。空字符串 = 可以；否则是给人看的原因。

        **界面灰不灰就用这一处判定**，别在按钮那边另写一遍（两处口径迟早分叉，
        而症状是"按钮能点、点下去什么都没发生"）。
        """
        if not self.pool.by_tier(tier):
            return "没有这一档的卡"
        if self.week_left(tier) <= 0:
            return f"本周 {tier} 额度已用完"
        kind, cost = COST[tier]
        if self.frag_of(kind) < cost:
            name = "低级碎片" if kind == "low" else "高级碎片"
            return f"还差 {cost - self.frag_of(kind)} 个{name}"
        return ""

    def can_exchange(self, tier: str) -> bool:
        return not self.exchange_block_reason(tier)

    def exchange(self, tier: str) -> Trade:
        """用碎片换一张卡（随机，撞重复则部分返还，并计入保底）。

        **保底比降价更能打断长尾**：同一档连续 ``GUARD`` 次撞重复之后，
        下一次直接给未拥有的 —— 传说只有 7 张，没有这条规则的话
        光靠随机要磨很久。
        """
        reason = self.exchange_block_reason(tier)
        if reason:
            return Trade(ok=False, tier=tier, reason=reason)

        kind, cost = COST[tier]
        self._add_frag(kind, -cost)
        self._use_week(tier)

        pool_tier = self.pool.by_tier(tier)
        missing = [c for c in pool_tier if not self.is_owned(c.id)]
        streak = int(self.cfg.dup_streak.get(tier, 0))

        if missing and streak >= GUARD:
            # 保底：直接给一张没有的，别再掷了
            card = self.rng.choice(missing)
            forced = True
        else:
            card = self.rng.choice(pool_tier)
            forced = False

        n = self._grant(card.id)
        if n > 1:
            # 撞重复：按分解价**部分返还**（净亏 = 兑换价 − 返还 > 0）。
            # 返还得正好等于兑换价就是"免费重摇"，那是最早那版被否掉的原因。
            back_kind, back = DISSOLVE[tier]
            self._add_frag(back_kind, back)
            if not forced:
                self.cfg.dup_streak[tier] = streak + 1
            return Trade(ok=True, tier=tier, card=card, is_new=False, refund=back)

        # 出了新卡：**不管是保底给的还是运气好**，连击都要归零 ——
        # 保底那一次也算"这次没撞重复"，计数留着的话下一轮又会立刻触发保底。
        self.cfg.dup_streak[tier] = 0
        return Trade(ok=True, tier=tier, card=card, is_new=True)

    def dup_streak(self, tier: str) -> int:
        return int(self.cfg.dup_streak.get(tier, 0))

    # ------------------------------------------------------------ 低换高

    def low_convert_capacity(self) -> int:
        """这一周还能换几个高级碎片（受碎片存量与周上限双重限制）。"""
        self.refresh_week()
        by_cap = max(0, LOW_TO_HIGH_CAP - int(self.cfg.low_convert_used)) // LOW_TO_HIGH_RATE
        by_have = self.cfg.frag_low // LOW_TO_HIGH_RATE
        return max(0, min(by_cap, by_have))

    def convert_low(self, times: int = 1) -> int:
        """低级碎片换高级碎片，返回实际换成了几个（0 = 换不了）。"""
        can = min(int(times), self.low_convert_capacity())
        if can <= 0:
            return 0
        self.cfg.frag_low -= can * LOW_TO_HIGH_RATE
        self.cfg.low_convert_used = int(self.cfg.low_convert_used) + can * LOW_TO_HIGH_RATE
        self.cfg.frag_high += can
        return can

    # ------------------------------------------------------------ 装备

    def slots(self) -> int:
        """已经解锁了几个装备槽。"""
        weeks = self.weeks_played()
        return min(EQUIP_SLOTS, 1 + (weeks - 1) // SLOT_EVERY_WEEKS)

    def weeks_played(self) -> int:
        """从首次运行算起是第几周（第 1 周 = 头 7 天）。"""
        started = str(self.cfg.launched_at or "")
        if not started:
            return 1
        try:
            t0 = datetime.strptime(started, STAMP_FMT)
        except ValueError:
            return 1
        days = max(0.0, (datetime.now() - t0).total_seconds() / 86400.0)
        return int(days // 7) + 1

    def equipped(self) -> list[str]:
        """在装备栏里的卡 id（已按槽位数截断，存档被手改超了也不会越界）。"""
        return list(self.cfg.equipped)[:self.slots()]

    def is_equipped(self, cid: str) -> bool:
        return cid in self.cfg.equipped

    def can_equip(self, cid: str) -> str:
        """能不能装上这张卡。空字符串 = 可以，否则是原因。"""
        if not self.is_owned(cid):
            return "还没抽到这张"
        if self.is_equipped(cid):
            return "已经装上了"
        if len(self.cfg.equipped) >= self.slots():
            return f"装备栏满了（{self.slots()} 格）"
        return ""

    def equip(self, cid: str) -> bool:
        if self.can_equip(cid):
            return False
        self.cfg.equipped.append(cid)
        return True

    def unequip(self, cid: str) -> bool:
        if cid not in self.cfg.equipped:
            return False
        self.cfg.equipped.remove(cid)
        return True

    def toggle_equip(self, cid: str) -> bool:
        """点一下在"装上/卸下"之间切换。返回切换之后**是不是装着的**。"""
        if self.is_equipped(cid):
            self.unequip(cid)
            return False
        self.equip(cid)
        return self.is_equipped(cid)

    def bonus(self) -> float:
        """当前装备提供的金币加成比例（0.13 = +13%），已按硬顶截断。"""
        total = 0.0
        for cid in self.equipped():
            card = self.pool.get(cid)
            if card is not None:
                total += EQUIP_BONUS.get(card.tier, 0.0)
        return min(EQUIP_CAP, total)

    def bonus_text(self) -> str:
        rate = self.bonus()
        return "金币 +0%" if rate <= 0 else f"金币 +{rate * 100:.0f}%"

    # ------------------------------------------------------------ 周重置

    def refresh_week(self) -> bool:
        """跨周了就清空周额度。返回有没有真的重置。

        **不需要定时器**：每次要读额度时现算一遍 —— 桌宠可能被挂在后台
        一整周都没人点它，定时器上的"周一零点"反而更不可靠。
        """
        stamp = week_stamp()
        if str(self.cfg.week_stamp) == stamp:
            return False
        self.cfg.week_stamp = stamp
        self.cfg.weekly_used = {}
        self.cfg.low_convert_used = 0
        return True

    # ------------------------------------------------------------ 内部

    def _grant(self, cid: str) -> int:
        """发一张卡，返回这张现在一共有几张。"""
        n = self.count(cid) + 1
        self._set_count(cid, n)
        return n

    def _set_count(self, cid: str, n: int) -> None:
        if n > 0:
            self.cfg.cards[cid] = int(n)
        else:
            self.cfg.cards.pop(cid, None)

    def _add_frag(self, kind: str, amount: int) -> None:
        if kind == "low":
            self.cfg.frag_low = max(0, int(self.cfg.frag_low) + int(amount))
        else:
            self.cfg.frag_high = max(0, int(self.cfg.frag_high) + int(amount))

    def _use_week(self, tier: str) -> None:
        self.cfg.weekly_used[tier] = int(self.cfg.weekly_used.get(tier, 0)) + 1


# ================================================================ 给游戏层的口子

def coin_bonus(cfg) -> float:
    """这一局的金币该加成多少（比例）。装备为空或卡池缺失时返回 0。

    小游戏那边**只认这一个函数** —— 加成规则只写在这里一份，
    免得"改了个数值，某个游戏忘了跟上"。
    """
    if not getattr(cfg, "equipped", None):
        return 0.0
    try:
        return Album(cfg).bonus()
    except (OSError, ValueError, TypeError, KeyError):
        return 0.0


def coins_with_bonus(cfg, earned: int) -> tuple[int, float]:
    """把一局挣到的金币按装备加成放大，返回 ``(最终值, 用到的比例)``。

    加成**只在结算时**算一次（和金币本身同一处）—— 所以不管这一局是打完的、
    还是玩家中途按「按当前分数结算」收工的，加成都走这一个函数，
    不会出现"某一款吃不到加成"。
    """
    try:
        base = max(0, int(earned))
    except (TypeError, ValueError):
        return 0, 0.0
    rate = coin_bonus(cfg)
    if base <= 0 or rate <= 0:
        return base, rate
    return int(round(base * (1.0 + rate))), rate
