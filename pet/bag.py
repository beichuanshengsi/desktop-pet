"""背包：小卖部买来的东西先存在这里，什么时候用由用户决定。

在它之前，买和用是同一件事 —— ``buy()`` 一扣钱就立刻把饱食抬上去。
那样有三个问题：

1. **没得选**。饱食已经 90 了还想买肉干？买下去就浪费了，只能等它饿。
2. **攒不住**。想"打三局游戏、一次买齐三种道具"，做不到 —— 买一样用一样。
3. **没有"东西"这个概念**。菜单上只有三行价格，用户看不到自己拥有什么，
   金币也就只是个数字，攒钱的动机比现在弱得多。

所以把"买"和"用"拆成两步：``buy()`` 只管扣钱和入库，
``use_item()`` 才真正生效。这个模块就是中间那个仓库。

为什么不认识 Qt
--------------
和 ``physics.Motion`` / ``behavior.Brain`` / ``pomodoro.Pomodoro`` 一样：
它是一份会变的数据加上几条规则（加、减、有没有、够不够），
跟窗口一点关系都没有。于是"买了两个、用掉一个、还剩一个"这种事
能在测试里几毫秒验完，不用把桌宠跑起来。

商品的**清单**不在这里 —— 它在 ``menu.SHOP``（那是全程序唯一的商品登记表）。
本模块只认识 key，需要名字和价格时回 ``menu.shop_item()`` 查，
免得"商品改名了但背包里还留着旧名字"。
"""

from __future__ import annotations

from .menu import SHOP, ShopItem, is_food, shop_item


def normalize(raw) -> dict[str, int]:
    """把任意来源的"key -> 数量"收拾成干净的 ``dict``。

    存档是用户能手改的文件，也可能是老版本写下的（那时候还没有背包）。
    所以这里必须容错：非字典、key 不是字符串、数量是小数或负数、
    甚至 key 指向一个已经下架的商品 —— 一律就地纠正，绝不抛异常。
    一个手打错的存档不该让桌宠起不来。
    """
    if not isinstance(raw, dict):
        return {}
    out: dict[str, int] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        try:
            n = int(value)
        except (TypeError, ValueError):
            continue
        if n > 0 and shop_item(key) is not None:
            out[key] = n
    return out


class Bag:
    """一只狗的背包。同一样东西可以叠着放。"""

    def __init__(self, counts: dict[str, int] | None = None):
        self._counts: dict[str, int] = normalize(counts or {})

    # ------------------------------------------------------------ 改动

    def add(self, key: str, amount: int = 1) -> int:
        """放进去几个，返回放完之后有多少（不认识的 key 原样返回 0）。"""
        if shop_item(key) is None or amount <= 0:
            return self.count(key)
        self._counts[key] = self.count(key) + int(amount)
        return self._counts[key]

    def take(self, key: str, amount: int = 1) -> bool:
        """拿走几个。不够就**整笔失败**、什么都不扣 —— 返回成功与否。

        不做"扣到 0 为止"：那样调用方拿到 False 之后还得自己判断
        "到底扣了没扣"，用起来必然出错。要多少就得有多少。
        """
        amount = int(amount)
        if amount <= 0 or self.count(key) < amount:
            return False
        left = self._counts[key] - amount
        if left:
            self._counts[key] = left
        else:
            self._counts.pop(key, None)
        return True

    def clear(self) -> None:
        self._counts.clear()

    # ------------------------------------------------------------ 查询

    def count(self, key: str) -> int:
        return self._counts.get(key, 0)

    def total(self) -> int:
        """一共有几件（所有种类加起来）—— 菜单和面板上的"共 N 件"。"""
        return sum(self._counts.values())

    def is_empty(self) -> bool:
        return not self._counts

    def entries(self) -> list[tuple[ShopItem, int]]:
        """按**商品清单的顺序**列出持有的东西：``[(ShopItem, 数量), ...]``。

        顺序跟着 ``SHOP`` 走而不是跟着字典走 —— 字典的顺序取决于"先买的哪样"，
        同一只狗在两个菜单里会排成两种样子。菜单的顺序必须稳定，
        否则用户每次都得多看两眼才找得到肉干。
        """
        out: list[tuple[ShopItem, int]] = []
        for item in SHOP:
            n = self.count(item.key)
            if n > 0:
                out.append((item, n))
        return out

    def first_food(self) -> tuple[ShopItem, int] | None:
        """背包里第一样"吃的"，没有就返回 ``None``。

        「喂一口」用它：免费额度用完之后，吃掉的正是这里查出来的那一样。
        按 ``SHOP`` 顺序而不是"先买的先吃" —— 同 ``entries()`` 的理由，
        同一只狗每次喂到的必须是同一样东西。

        **只认加饱食的商品**：背包里全是玩具球时它返回 ``None`` ——
        饿的时候啃球没有意义，那时候该灰掉的是「喂一口」那一行。
        """
        for item, n in self.entries():
            if is_food(item):
                return item, n
        return None

    # ------------------------------------------------------------ 存档

    def to_dict(self) -> dict[str, int]:
        """给存档用的纯数据（``Config`` 负责真正落盘）。"""
        return dict(self._counts)

    @classmethod
    def from_dict(cls, raw) -> "Bag":
        return cls(normalize(raw))

    def __repr__(self) -> str:                       # 调试与测试里看得懂
        inside = ", ".join(f"{k}×{v}" for k, v in self._counts.items())
        return f"Bag({inside or '空'})"
