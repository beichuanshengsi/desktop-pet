"""小游戏子系统。

这里的 ``GAMES`` 是游戏清单的**唯一来源** —— 托盘菜单、桌宠右键菜单、
``main.py`` 的窗口管理都从它取。加第五个游戏时只需要：

1. 写一个新的 ``game/xxx.py``，继承 ``GameWindow``（``game/common.py``），
   它是所有游戏窗口的共同底座，``closed = Signal(int)`` 就在那里；
2. 往 ``GAMES`` 加一行；
3. 在 ``create_game()`` 里加一个分支。

不需要去改两个菜单，它们遍历 ``GAMES`` 自动就有了。

四款游戏的分工（选型时就按"玩家控制什么"来区分，避免同质化）：

    | bounce 弹跳得分 | 控制**位置** —— 挪到方块底下，跳 |
    | catch  接狗狗   | 控制**位置** —— 左右跑去接掉落物 |
    | runner 跑一跑   | 控制**时机** —— 位置固定，只有跳和低头 |
    | 2048   狗粮 2048| 控制**方向** —— 离散回合，纯决策     |

``COIN_PER_SCORE`` / ``coins_for`` 是从 ``common`` 转出来的：汇率属于
"各个游戏共用的东西"，实现放在 ``common.py``，但 ``pet/config.py`` 那边
引的是本模块的名字，所以这里必须能取到（别删这两行）。
**例外**：``game/g2048.py`` 按最大格子折算，不走 ``coins_for`` —— 理由写在那边。
"""

from __future__ import annotations

from game.common import COIN_PER_SCORE, GameWindow, coins_for

__all__ = ["COIN_PER_SCORE", "DEFAULT_GAME", "GAMES", "GameWindow",
           "coins_for", "create_game", "game_kinds", "game_title"]

#: (标识, 菜单里显示的名字, 窗口标题)
GAMES: tuple[tuple[str, str, str], ...] = (
    ("bounce", "弹跳得分", "桌宠小游戏 · 弹跳得分"),
    ("catch", "接狗狗", "桌宠小游戏 · 接狗狗"),
    ("runner", "跑一跑", "桌宠小游戏 · 跑一跑"),
    ("2048", "狗粮 2048", "桌宠小游戏 · 狗粮 2048"),
)

DEFAULT_GAME = GAMES[0][0]


def game_kinds() -> tuple[str, ...]:
    return tuple(kind for kind, _label, _title in GAMES)


def game_title(kind: str) -> str:
    for k, _label, title in GAMES:
        if k == kind:
            return title
    return GAMES[0][2]


def create_game(kind: str, bank, cfg) -> GameWindow:
    """按标识造一个游戏窗口。

    返回类型写成 ``GameWindow`` 而不是 ``QWidget``：调用方（``main.py``）
    要连 ``closed`` 信号 —— 那是底座给的，标成 ``QWidget`` 类型检查器就报错。

    游戏模块在这里**延迟导入**：四个游戏都依赖 Qt，但托盘起来的时候
    未必会玩游戏；更重要的是避免 ``game`` 与 ``pet`` 之间出现双向导入。
    """
    if kind == "catch":
        from game.catcher import CatchGame
        return CatchGame(bank, cfg)

    if kind == "runner":
        from game.runner import Runner
        return Runner(bank, cfg)

    if kind == "2048":
        from game.g2048 import Game2048
        return Game2048(bank, cfg)

    from game.minigame import MiniGame
    return MiniGame(bank, cfg)
