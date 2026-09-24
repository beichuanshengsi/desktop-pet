"""小游戏子系统。

这里的 ``GAMES`` 是游戏清单的**唯一来源** —— 托盘菜单、桌宠右键菜单、
``main.py`` 的窗口管理都从它取。加第三个游戏时只需要：

1. 写一个新的 ``game/xxx.py``，继承 ``GameWindow``（``game/common.py``），
   它是两个游戏窗口的共同底座，``closed = Signal(int)`` 就在那里；
2. 往 ``GAMES`` 加一行；
3. 在 ``create_game()`` 里加一个分支。

不需要去改两个菜单，它们遍历 ``GAMES`` 自动就有了。

``COIN_PER_SCORE`` / ``coins_for`` 是从 ``common`` 转出来的：汇率属于
"两个游戏共用的东西"，实现放在 ``common.py``，但 ``pet/config.py`` 那边
引的是本模块的名字，所以这里必须能取到（别删这两行）。
"""

from __future__ import annotations

from game.common import COIN_PER_SCORE, GameWindow, coins_for

__all__ = ["COIN_PER_SCORE", "DEFAULT_GAME", "GAMES", "GameWindow",
           "coins_for", "create_game", "game_kinds", "game_title"]

#: (标识, 菜单里显示的名字, 窗口标题)
GAMES: tuple[tuple[str, str, str], ...] = (
    ("bounce", "弹跳得分", "桌宠小游戏 · 弹跳得分"),
    ("catch", "接狗狗", "桌宠小游戏 · 接狗狗"),
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

    游戏模块在这里**延迟导入**：两个游戏都依赖 Qt，但托盘起来的时候
    未必会玩游戏；更重要的是避免 ``game`` 与 ``pet`` 之间出现双向导入。
    """
    if kind == "catch":
        from game.catcher import CatchGame
        return CatchGame(bank, cfg)

    from game.minigame import MiniGame
    return MiniGame(bank, cfg)
