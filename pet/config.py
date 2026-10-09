"""配置与存档。

只管一件事：**用户选了什么**。路径与素材目录在 ``pet/paths.py``，
那两个根目录（只读资源 / 可写数据）的区别在那里讲。

读存档的原则是"坏档不能让程序起不来"：字段全部有默认值，缺字段、
多字段、类型不对，都尽量就地校正而不是抛异常 —— 用户手改过存档是很常见的事。
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime

from .paths import config_path
from .vitals import START as VITALS_START

#: 存档里时间戳的统一格式。``launched_at`` 与 ``last_seen`` 都用它 ——
#: 这两处要是各写一种格式，"离线多久"就会算出鬼来。
STAMP_FMT = "%Y-%m-%d %H:%M:%S"

#: 只到"天"的存档格式。「喂一口」那份每日免费额度用它 ——
#: 记到秒没有意义，而且**同一天里两次调用必须相等**，否则额度永远重置不了。
DAY_FMT = "%Y-%m-%d"


def now_stamp() -> str:
    """当前时间的存档字符串形式。"""
    return datetime.now().strftime(STAMP_FMT)


def today_stamp() -> str:
    """今天的日期字符串。判断"是不是同一天"只认它的输出。"""
    return datetime.now().strftime(DAY_FMT)


def hours_since(stamp: str) -> float:
    """``stamp`` 到现在过了几小时。空值 / 格式不对一律返回 0（当作刚离开）。

    离线衰减就靠这个数。**解析失败必须返回 0 而不是抛异常**：存档是用户
    可以手改的文件，一个手打错的日期不该让程序起不来。
    """
    if not stamp:
        return 0.0
    try:
        was = datetime.strptime(str(stamp), STAMP_FMT)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, (datetime.now() - was).total_seconds() / 3600.0)


@dataclass
class Config:
    """用户配置与进度。字段全部给默认值，缺字段的老存档也能正常读入。"""

    # 位置（-1 表示尚未确定，需要按屏幕算一个默认值）
    pos_x: int = -1
    pos_y: int = -1
    scale: float = 1.0              # 显示缩放
    speed: float = 1.0              # 行为节奏倍率
    auto_walk: bool = True          # 允许自主漫步
    gravity: bool = True            # 松手后下坠
    topmost: bool = True            # 始终置顶
    show_on_start: bool = True      # 启动时显示

    # 养成与统计
    feed_count: int = 0             # 累计投喂次数
    play_count: int = 0             # 累计互动次数
    best_score: int = 0             # 小游戏「弹跳得分」最高分
    best_catch: int = 0             # 小游戏「接狗狗」最高分（和上面分开存，互不覆盖）
    best_runner: int = 0            # 小游戏「跑一跑」最远分数（同上，各存各的）
    best_2048: int = 0              # 小游戏「狗粮 2048」最高分（同上）
    launched_at: str = ""           # 首次运行时间

    # 养成状态的三条值。**默认值来自 pet/vitals.py**，别在这里另写一个数 ——
    # 衰减曲线、阈值也都在那边，这里只负责存。
    satiety: float = VITALS_START   # 饱食
    mood: float = VITALS_START      # 心情
    energy: float = VITALS_START    # 精力

    #: 小卖部的钱。两个小游戏结算时按得分折算，见 game/__init__.py 的 COIN_PER_SCORE。
    coins: int = 0
    #: 上次退出时间（ISO 字符串）。启动时拿它算离线衰减；空 = 第一次运行。
    last_seen: str = ""

    #: 背包：商品 key -> 个数。**只存数量**，名字/价格/效果一律回
    #: ``menu.SHOP`` 查 —— 商品改了价或改了描述，不用动存档，也不会出现
    #: "存档里写的是旧名字"。解析规则见 ``pet/bag.py`` 的 ``normalize``。
    inventory: dict[str, int] = field(default_factory=dict)
    #: 上次用掉「喂一口」那份免费额度的**日期**（``DAY_FMT`` 的格式）。
    #: 空 = 从没用过（老存档就是这个值，于是升级后还能白喂一次）。
    #: 当天再点「喂一口」，吃的就是背包里的东西了。
    free_feed_day: str = ""
    #: 上次在滚轮里选的番茄钟时长（**秒**）。下次打开对话框就从这儿接着滚，
    #: 不用每次重新滚一遍 25 分钟。默认值来自 ``pet/pomodoro.py`` 的常用档位。
    pomodoro_seconds: float = 1500.0

    # ---------------- 卡册与抽卡（见 pet/cards.py）
    #
    # 这一组字段的读写规则都在 ``pet/cards.py`` 的 ``Album`` 里，本类只负责存。
    # 之所以不另做一个独立的 ``album.json``：桌宠是"被任务管理器结束掉也不奇怪"
    # 的常驻程序，多一份存档就多一处"最后几秒的改动白丢"的机会。

    #: 卡册：卡 id -> 拥有张数。**重复的卡留在册里不自动变碎片** ——
    #: 分不分解、分解哪张，由用户在卡册里自己决定。
    cards: dict[str, int] = field(default_factory=dict)
    #: 低级碎片（普通/稀有重复卡分解来的）。
    frag_low: int = 0
    #: 高级碎片（史诗/传说重复卡分解来的，以及低级碎片 5:1 换来的）。
    #: 两条货币分开，是为了让"换一张传说"必须真的攒够高级碎片。
    frag_high: int = 0
    #: 装备栏：装着的卡 id 列表。槽位数按"第几周"解锁，见 ``cards.Album.slots``。
    equipped: list[str] = field(default_factory=list)
    #: 当前的周标识（``cards.week_stamp()`` 的输出，形如 ``2026-W41``）。
    #: 和它不相等就说明跨周了，周额度要清零。
    week_stamp: str = ""
    #: 本周各档已兑换次数：档位 -> 次数。
    weekly_used: dict[str, int] = field(default_factory=dict)
    #: 本周"低换高"已经吃掉的低级碎片数（上限见 ``cards.LOW_TO_HIGH_CAP``）。
    low_convert_used: int = 0
    #: 兑换保底计数：档位 -> 连续撞重复了几次，见 ``cards.GUARD``。
    dup_streak: dict[str, int] = field(default_factory=dict)

    # ---------------- 幼儿模式（见 pet/kids.py）
    #
    # **这里只有密码，没有"正在锁定"**。桌宠是会被任务管理器结束掉的常驻程序，
    # 一旦把"已锁定"持久化，异常退出后重启就会自己锁上 —— 用户会以为电脑坏了。
    # 所以幼儿模式**重启即解除**，这条是刻意的，别加字段"记住上次状态"。
    #
    #: 退出幼儿模式的 4 位数字密码。**明文存**：家长忘了密码时打开 config.json
    #: 就能看见，把它改成空字符串则会重新让他设一个 —— 存哈希等于把唯一的
    #: 后路堵死，而这份存档本来就是用户自己可以手改的文件。
    kids_passcode: str = ""

    # ---------------- 读写

    @classmethod
    def load(cls) -> "Config":
        path = config_path()
        cfg = cls()
        if not path.exists():
            return cfg
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cfg                      # 存档损坏就静默用默认值，不能让程序起不来

        known = {f.name for f in fields(cls)}
        for k, v in raw.items():
            if k not in known:
                continue                    # 老版本留下的废弃字段：忽略，不报错
            cur = getattr(cfg, k)
            # 做一次宽松的类型校正，避免手工编辑存档后炸掉
            try:
                if isinstance(cur, bool):
                    v = bool(v)
                elif isinstance(cur, int) and not isinstance(cur, bool):
                    v = int(v)
                elif isinstance(cur, float):
                    v = float(v)
                elif isinstance(cur, str):
                    v = str(v)
                elif isinstance(cur, dict):
                    # 背包这类"键值对"字段：原样收下就行。**细活留给各自的模块**
                    # （``bag.normalize`` 会剔掉下架商品、负数、非整数），
                    # 这里只挡掉类型完全不对的情况（被手改成了一串数字）。
                    v = v if isinstance(v, dict) else {}
                elif isinstance(cur, list):
                    # 列表字段（目前只有 ``equipped``）。元素只收字符串 ——
                    # 一个手打错的数字混进去，"装备了 c001 和 3"这种状态
                    # 在卡册里没法画出来，也没法卸掉。
                    v = [x for x in v if isinstance(x, str)] if isinstance(v, list) else []
            except (TypeError, ValueError):
                continue
            setattr(cfg, k, v)
        return cfg

    def save(self) -> None:
        path = config_path()
        tmp = path.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2),
                           encoding="utf-8")
            os.replace(tmp, path)           # 原子替换，避免写一半断电留下坏档
        except OSError:
            pass
