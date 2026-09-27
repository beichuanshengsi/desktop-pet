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


def now_stamp() -> str:
    """当前时间的存档字符串形式。"""
    return datetime.now().strftime(STAMP_FMT)


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
    #: 上次在滚轮里选的番茄钟时长（**秒**）。下次打开对话框就从这儿接着滚，
    #: 不用每次重新滚一遍 25 分钟。默认值来自 ``pet/pomodoro.py`` 的常用档位。
    pomodoro_seconds: float = 1500.0

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
