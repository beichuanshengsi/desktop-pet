"""存档的每日快照 —— 一份存档不值得赌。

问题
----

桌宠的进度全在 ``config.json`` 一个文件里，而且**只此一份**。``Config.save()``
已经是"先写临时文件、再原子替换"，所以"写一半断电留下坏档"基本防住了；
但有一类事故它防不住 —— **文件本身是完整的，内容却不是玩家想要的样子**：

* 测试脚本忘了隔离存档，把测试数据写了进去（v2.3.0 真发生过：跑一次验证，
  卡册里凭空多了 40 张卡）
* 玩家自己手改存档改错了
* 程序被任务管理器结束在"改了一半"的中间态

这类事故靠代码是防不完的，只能靠**留一份旧的**：出了事能翻回去看昨天是什么样。

做法
----

每次启动时看一眼：今天还没快照过，就把当前存档复制一份到
``<存档目录>/backups/config-YYYY-MM-DD.json``，只保留最近 ``KEEP_DAYS`` 天。

为什么按天、而不是"每次保存都备份"：存档每 3 秒落一次盘，每次备份等于把
3 秒前的状态存一遍，纯属浪费。按天留才回答得了"我昨天还是好的，今天怎么了"。

为什么不放在 ``Config.save()`` 里：那是每 3 秒走一次的路径，
一旦出错就是主循环出错。启动时做一次，失败也只是少一份快照，不影响运行。

备份目录跟着**存档文件所在目录**走（``config_path().parent``），不跟 ``data_dir()``
—— 这样子目录里跑测试（把 ``config_path`` 指到临时文件）时，快照也会落到临时
目录里，不会在项目根留下 ``backups/``。
"""

from __future__ import annotations

import shutil
from datetime import datetime, timedelta
from pathlib import Path

from . import paths

#: 快照目录名（就在存档旁边）。
BACKUP_DIR_NAME = "backups"

#: 保留多少天。14 天足够覆盖"我上周还是好的"这种回头看的场景，
#: 又不会攒出几百个小文件。
KEEP_DAYS = 14


def backup_dir() -> Path:
    """快照目录（跟着存档文件走，不跟 data_dir）。"""
    # 走 ``paths.config_path()`` 而不是 ``from .paths import config_path``：
    # 后者在导入时就把函数绑死了，谁要是给 ``paths`` 打个补丁（测试常干的事），
    # 这里不会跟着走 —— 快照就会落到真存档旁边。少一次"隔离失效"，值。
    return paths.config_path().parent / BACKUP_DIR_NAME


def _prune(keep: int = KEEP_DAYS) -> int:
    """删掉太旧的快照，返回删了几个。认不出日期的文件一律不动。"""
    removed = 0
    cutoff = datetime.now().date() - timedelta(days=keep)
    for path in backup_dir().glob("config-*.json"):
        stamp = path.stem.removeprefix("config-")
        try:
            day = datetime.strptime(stamp, "%Y-%m-%d").date()
        except ValueError:
            continue                    # 不是我起的名字，别乱删
        if day >= cutoff:
            continue
        try:
            path.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def snapshot_daily(day: datetime | None = None) -> Path | None:
    """今天还没快照过就存一份当前存档，返回快照路径。

    返回 ``None`` 表示"今天已经有了"或"还没有存档可备份" —— 两种情况都正常，
    调用方不需要区分（启动路径上不该为这个报错）。
    """
    src = paths.config_path()
    if not src.exists():
        return None

    today = (day or datetime.now()).strftime("%Y-%m-%d")
    dst = backup_dir() / f"config-{today}.json"
    if dst.exists():
        return None

    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    except OSError:
        return None
    _prune()
    return dst
