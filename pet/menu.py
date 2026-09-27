"""菜单构建 —— 桌宠右键菜单与托盘菜单共用的那部分。

两个菜单长得像但**不一样**：托盘有「显示 / 隐藏」和「大小」，桌宠有「左右翻向」
和「藏进托盘」，所以不能直接共用同一个 ``QMenu``。

但重复的那部分必须**只有一份实现**：逗它玩 / 喂一口、游戏子菜单、三个开关、
小卖部、番茄钟、状态那一行。以前是各写一遍，代价是加一个开关要改两个文件 ——
漏掉一个就会出现"右键菜单里有、托盘里没有"，而没人会天天去比对这两个菜单。

判断标准跟 ``game/common.py`` 一样：**两个调用方都要用的**才放进来，
只有一边有的留在自己那个文件里。

所以：

* 加一个**开关** → 在下面 ``TOGGLES`` 里加一行（两个菜单同时生效）
* 加一样**商品** → 在下面 ``SHOP`` 里加一行（两个菜单同时生效）
* 加一档**番茄钟快捷档** → 在下面 ``POMODORO_CHOICES`` 里加一个秒数
* 加一个**游戏** → 什么都不用改（``game.GAMES`` 是清单的唯一来源）
* 加一个只在一边有的条目 → 留在 ``window.py`` / ``tray.py`` 里

买与不买由谁决定
----------------
菜单层只做两件事：**按 ``cfg.coins`` 决定商品项灰不灰**、**把 key 发出去**。
钱够不够扣、加了哪一样、演什么动作，全在 ``PetWindow.buy()`` 里 ——
那边的判定是权威的，菜单上的灰只是提示（菜单构建到用户点下去之间，
金币是可能变的，比如后台刚结算完一局游戏）。

**买了不等于用掉**：``PetWindow.buy()`` 只扣钱 + 把东西放进背包，
真正生效要点「背包」里那一下（``PetWindow.use_item()``）。所以这一层里
「小卖部」和「背包」是两个子菜单：一个管进货，一个管花掉。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Protocol

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu

from .config import Config
from .pomodoro import describe
from .vitals import LABEL as VITALS_LABEL


@dataclass(frozen=True)
class Toggle:
    """一个勾选开关牵动的三个地方。"""

    field: str      #: ``Config`` 上的字段名（也决定初始勾选状态）
    label: str      #: 菜单里显示的文字
    setter: str     #: ``PetWindow`` 上负责应用这个开关的方法名


#: 开关登记表 —— **加一个开关就在这里加一行**。
TOGGLES: tuple[Toggle, ...] = (
    Toggle("auto_walk", "自动漫步", "set_auto_walk"),
    Toggle("gravity", "重力下坠", "set_gravity"),
    Toggle("topmost", "始终置顶", "set_topmost"),
)


@dataclass(frozen=True)
class ShopItem:
    """小卖部里的一样东西。"""

    key: str        #: 标识，``PetWindow.buy()`` 按它查表
    label: str      #: 菜单里显示的名字
    price: int      #: 售价（金币）
    action: str     #: 买下之后让它演哪个动作（``State`` 的成员值）
    #: 提升哪些值：``((vitals 字段名, 加多少), ...)``
    gains: tuple[tuple[str, float], ...]


#: 商品登记表 —— **加一样东西就在这里加一行**。
#:
#: 只卖"吃的"和"玩的"，**精力不卖**：精力只有睡才能回来。
#: 这不是漏了，是刻意留的唯一解 —— 三条值里总得有一条是钱买不到的，
#: 否则"看它困了、不吵它"这件事就永远没有意义。
SHOP: tuple[ShopItem, ...] = (
    ShopItem("treat", "肉干", 12, "feed", (("satiety", 35.0),)),
    ShopItem("ball", "玩具球", 18, "poke", (("mood", 35.0),)),
    ShopItem("feast", "豪华大餐", 30, "feed",
             (("satiety", 50.0), ("mood", 20.0))),
)

#: 番茄钟的**快捷档位**（秒）—— 加一档就在这里加一个数。
#:
#: 时长本身由用户滚轮自己定（1 秒 ~ 2 小时，见 ``pet/wheel_dialog.py``），
#: 这几个只是"懒得多滚"的常用值。**单位是秒**，别再写分钟：
#: 滚轮能滚出 45 秒这种值，清单里混着分钟和秒，迟早有人把 45 当分钟用。
POMODORO_CHOICES: tuple[int, ...] = (60, 300, 1500, 3000)      # 1/5/25/50 分钟


def shop_item(key: str) -> ShopItem | None:
    """按标识找商品。找不到返回 ``None``（菜单传进来的 key 永远来自 SHOP，
    但购买入口是公开方法，测试和脚本也可能直接调）。"""
    for item in SHOP:
        if item.key == key:
            return item
    return None


def gains_text(item: ShopItem) -> str:
    """商品/道具的效果说法，形如 ``饱食+35``。菜单和小卖部共用一份。"""
    return "/".join(f"{VITALS_LABEL.get(f, f)}+{v:.0f}" for f, v in item.gains)


def item_text(item: ShopItem) -> str:
    """小卖部里那一行的完整文字：名字、效果、价钱。"""
    return f"{item.label}（{gains_text(item)}）  {item.price} 金币"


def bag_item_text(item: ShopItem, count: int) -> str:
    """背包里那一行：名字、效果、**数量**（价钱不用写，已经买下来了）。"""
    return f"{item.label}（{gains_text(item)}）  ×{count}"



class _ToggleTarget(Protocol):
    """开关要调的三个方法。

    ``PetWindow`` 天然满足这个形状，所以不用 import 它（``window`` 已经
    import 了本模块，反向 import 会成环）。
    """

    def set_auto_walk(self, on: bool) -> None: ...
    def set_gravity(self, on: bool) -> None: ...
    def set_topmost(self, on: bool) -> None: ...


def add_interactions(menu: QMenu, pet) -> None:
    """逗它玩 / 喂一口 —— 两个菜单都指到同一对方法上，别各接各的。"""
    menu.addAction("逗它玩", pet.poke)
    menu.addAction("喂一口", pet.feed)


def add_vitals(menu: QMenu, vitals, cfg: Config) -> list[QAction]:
    """顶上那两行"它现在怎么样 + 手上有多少钱"。

    做成不可点的 action 而不是往 QMenu 里塞 ``QLabel``：自定义 widget 在不同
    Windows 主题下的内边距不一样，而这两行只是给自己看的，不值得为它调样式。

    **为什么从一行变成三行**：原来这里只写一句 ``summary()``，状态不错的时候
    就是"状态不错"四个字 —— 用户根本看不出它饱食多少、还能撑多久，
    得再点进小卖部才知道。现在第一行直接摆三个数（复用 ``Vitals.detail()``）、
    第二行报金币；第三行**只在真有事情时出现**（饿了 / 困了 / 有点蔫），
    正常时那一行不存在，不会常年占着菜单宽度。
    """
    made: list[QAction] = []

    line = menu.addAction(f"{vitals.detail()}　·　金币 {cfg.coins}")
    line.setEnabled(False)
    made.append(line)

    if vitals.needs_attention:
        alert = menu.addAction(f"要注意：{vitals.summary()}")
        alert.setEnabled(False)
        made.append(alert)

    return made


def add_shop(menu: QMenu, pet, cfg: Config) -> QMenu:
    """小卖部子菜单：**进货**（买下的东西会进背包，不立刻生效）。

    买不起的那几样**灰掉但留着**：直接不显示的话，用户根本不知道还有别的东西
    可买，也就不知道攒钱有什么用。

    这个子菜单里**只有商品项是可点的**（标题行、提示行都 disabled）——
    这条不成文的规矩值得守住：一眼扫过去能点的就是能买的。要花掉道具请去
    「背包」，要盘点存货请去「背包面板」。
    """
    sub = menu.addMenu("小卖部")

    money = sub.addAction(f"金币 {cfg.coins}")
    money.setEnabled(False)
    tip = sub.addAction("买下会放进背包，到「背包」里才用掉")
    tip.setEnabled(False)
    sub.addSeparator()

    for item in SHOP:
        act = sub.addAction(item_text(item))
        act.setEnabled(cfg.coins >= item.price)
        # 绑成默认参数：不这样写闭包捕获的是循环变量本身，
        # 所有菜单项最后都会发出同一个 key（Qt 里最容易踩的一类坑）
        act.triggered.connect(lambda _=False, k=item.key: pet.buy(k))
    return sub


def add_bag(menu: QMenu, pet, cfg: Config) -> QMenu:
    """背包子菜单：**花掉**（点一下就消耗一个、当场生效）。

    和「小卖部」分工明确：那边进货、这边使用。之所以还留一个子菜单而不是
    只给一个"打开面板"的入口 —— 用道具是高频操作，为了喂一口去开一个窗口
    再点一下，比直接点两下菜单慢得多。

    空背包时给一行灰字提示，而不是显示一个空菜单：空菜单看起来像坏了。

    「打开背包面板」**不放在这里** —— 它是个一层就能点到的入口
    （在右键菜单和托盘菜单的下半区），塞进背包子菜单就成了"想看一眼存货
    得先点开背包"，正好和这个面板存在的理由相反。
    """
    sub = menu.addMenu("背包")

    head = sub.addAction(f"金币 {cfg.coins}　·　共 {pet.bag.total()} 件")
    head.setEnabled(False)
    sub.addSeparator()

    entries = pet.bag.entries()
    if not entries:
        empty = sub.addAction("（空的）去小卖部买点东西吧")
        empty.setEnabled(False)
    for item, count in entries:
        act = sub.addAction(bag_item_text(item, count))
        # 同样把 k 绑成默认参数，否则十个道具点哪个都是最后那个
        act.triggered.connect(lambda _=False, k=item.key: pet.use_item(k))
    return sub


def add_pomodoro(menu: QMenu, pet) -> QMenu:
    """番茄钟子菜单。

    没在跑时：**「自定义时长…」排在最前**（滚轮能滚出 1 秒 ~ 2 小时，
    是主入口），底下跟一排常用档位给懒得多滚的人。

    跑着的时候只给「还剩 mm:ss」和「停止」—— 再列一遍档位没有意义，
    还会让人以为点一下是"再加一轮"。剩余时间旁边带上本轮总时长，
    因为时长现在是用户自己定的，"还剩 12:30"到底是快到头了还是刚开始，
    光看剩余数字判断不了。
    """
    sub = menu.addMenu("番茄钟")
    pomo = pet.pomodoro
    if pomo.running:
        head = sub.addAction(f"还剩 {pomo.label()}　（共 {pomo.describe_total()}）")
        head.setEnabled(False)
        sub.addSeparator()
        sub.addAction("停止", pet.stop_pomodoro)
        return sub

    sub.addAction("自定义时长…", pet.pick_pomodoro)
    sub.addSeparator()
    for secs in POMODORO_CHOICES:
        sub.addAction(describe(secs),
                      lambda _=False, s=secs: pet.start_pomodoro(s))
    return sub



def add_game_menu(menu: QMenu, games: Iterable[tuple[str, str, str]],
                  emit: Callable[[str], None], *,
                  fallback: Callable[[], None] | None = None) -> QMenu | None:
    """加「一起玩游戏」子菜单，返回它（没加则返回 ``None``）。

    ``games`` 就是 ``game.GAMES``：``(标识, 菜单名, 窗口标题)``。空的时候
    桌宠这一层**不认识 game 包**，没清单就干脆不显示这个入口；
    托盘那边给了 ``fallback`` 就退化成单个菜单项（它自己会再问一次用什么游戏）。
    """
    items = tuple(games)
    if not items:
        if fallback is not None:
            menu.addAction("一起玩游戏", fallback)
        return None

    sub = menu.addMenu("一起玩游戏")
    for game_id, label, _title in items:
        # 把 k 绑成默认参数：不这样写的话闭包捕获的是循环变量本身，
        # 所有菜单项最后都会发出同一个标识（Qt 里最容易踩的一类坑）
        sub.addAction(label, lambda _=False, k=game_id: emit(k))
    return sub


def add_toggles(menu: QMenu, cfg: Config,
                target: _ToggleTarget) -> list[tuple[QAction, Toggle]]:
    """加一排勾选开关，返回 ``[(action, 登记项)]`` 给调用方留着同步勾选状态。

    返回值必须拿着：``cfg`` 也会被别处改（小游戏结束后主程序会刷新托盘），
    菜单上显示的勾选状态得跟着走，否则"菜单说开着、其实已经关了"。
    """
    made: list[tuple[QAction, Toggle]] = []
    for item in TOGGLES:
        act = QAction(item.label, menu)
        act.setCheckable(True)
        act.setChecked(bool(getattr(cfg, item.field)))
        act.toggled.connect(getattr(target, item.setter))
        menu.addAction(act)
        made.append((act, item))
    return made


def sync_toggles(made: Iterable[tuple[QAction, Toggle]], cfg: Config) -> None:
    """把菜单上的勾选状态拉回 ``cfg`` 的真实值。

    ``blockSignals`` 不能省：``setChecked`` 会发 ``toggled``，
    不挡住就会"同步一下反而把设置改了"。
    """
    for act, item in made:
        act.blockSignals(True)
        act.setChecked(bool(getattr(cfg, item.field)))
        act.blockSignals(False)
