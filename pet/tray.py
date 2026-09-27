"""系统托盘。

无边框窗口没有关闭按钮，托盘是用户唯一的"正规出口"——所以这个模块
必须在第一版就有，否则调试期间只能靠任务管理器杀进程。

托盘菜单同时承担"找回宠物"的职责：宠物被藏起来之后，只能从这里叫出来。

菜单里和右键菜单重复的那几块（状态行 / 互动动作 / 小卖部 / 番茄钟 /
游戏子菜单 / 三个开关）走 ``pet/menu.py``，**不在这里重写一遍**。
这个文件只留"只有托盘才有"的东西：「显示 / 隐藏」和「大小」。

菜单为什么要每次重建
--------------------
``setContextMenu()`` 只给一次机会，所以这个 ``QMenu`` 是**一次构建、反复复用**的。
可它现在要显示三样每刻都在变的东西：它饿没饿、手上有多少金币、番茄钟还剩多久。
一次构建的话，用户右键看到的是"上一次建菜单那一刻"的金币数 —— 而金币
要玩完一局游戏才涨，涨的时机跟建菜单的时机毫无关系。

所以接 ``aboutToShow``：**每次弹出前清空重灌**。这是 QMenu 上做动态菜单的
标准做法（``clear()`` 在 ``aboutToShow`` 里调是安全的，那时菜单还没显示出来）。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from . import menu as menulib
from .config import Config
from .window import PetWindow


class PetTray(QSystemTrayIcon):
    """托盘图标 + 菜单。"""

    def __init__(self, icon_path: Path, pet: PetWindow, cfg: Config,
                 *, on_quit, on_game, games=(), parent=None):
        icon = QIcon(str(icon_path)) if Path(icon_path).exists() else QIcon()
        super().__init__(icon, parent)
        self.pet = pet
        self.cfg = cfg
        self._on_quit = on_quit
        self._on_game = on_game
        self._games = tuple(games)

        #: 开关项 —— 每次重建菜单都会换一批新的，这里跟着更新
        self._toggles: list[tuple[QAction, menulib.Toggle]] = []

        self.setToolTip("桌宠 —— 右键查看菜单，双击叫出来")
        self._menu = QMenu()
        self._menu.aboutToShow.connect(self.refresh)
        self.refresh()
        self.setContextMenu(self._menu)
        self.activated.connect(self._on_activated)

    # ------------------------------------------------------------ 菜单

    def refresh(self) -> None:
        """把菜单清空重灌一遍。

        平时由 ``aboutToShow`` 在弹出前自动调；外部改了设置（比如小游戏结算
        发了金币）之后也可以主动调一次，让菜单立刻跟上。
        """
        m = self._menu
        # 正在显示的时候不要重建 —— 那会把用户正看着的菜单清空。
        # 跳过也没关系，下一次弹出前一定会重建。
        if m.isVisible():
            return

        m.clear()

        self.act_toggle = QAction("显示 / 隐藏", m)
        self.act_toggle.triggered.connect(self.toggle_pet)
        m.addAction(self.act_toggle)

        menulib.add_vitals(m, self.pet.vitals, self.cfg)
        m.addSeparator()
        menulib.add_interactions(m, self.pet)
        menulib.add_shop(m, self.pet, self.cfg)
        menulib.add_bag(m, self.pet, self.cfg)
        menulib.add_pomodoro(m, self.pet)
        # 没传游戏清单时退化成单个菜单项：点一下由主程序决定开哪个
        menulib.add_game_menu(m, self._games, self._on_game,
                              fallback=lambda: self._on_game())
        m.addSeparator()

        self._toggles = menulib.add_toggles(m, self.cfg, self.pet)

        m.addSeparator()
        size_menu = m.addMenu("大小")
        for label, scale in (("小", 0.75), ("中", 1.0), ("大", 1.35), ("很大", 1.7)):
            act = QAction(label, size_menu)
            act.triggered.connect(lambda _=False, s=scale: self._set_scale(s))
            size_menu.addAction(act)

        m.addAction("背包面板", self.pet.open_panel)
        m.addAction("回到默认位置", self.pet.reset_position)
        m.addSeparator()
        m.addAction("退出", self._on_quit)

        # 顺手把托盘的悬停提示也刷成"它现在怎么样" —— 不点开任何菜单、
        # 鼠标往托盘图标上一停就能看到。v2.2.0 删掉"划过桌宠弹出的状态卡片"
        # 之后，状态值就剩两个出口：这里，和右键菜单顶上那两行
        # （见 ``pet/panel.py`` 开头的"状态显示的三次收缩"）。
        self.setToolTip(f"桌宠　{self.pet.vitals.summary()}\n"
                        f"{self.pet.vitals.detail()}　金币 {self.cfg.coins}")

    def sync_toggles(self) -> None:
        """只把勾选状态拉回 ``cfg`` 的真实值（菜单结构不动）。"""
        menulib.sync_toggles(self._toggles, self.cfg)

    # ------------------------------------------------------------ 交互

    def _on_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self.toggle_pet()

    def toggle_pet(self) -> None:
        if self.pet.isVisible():
            self.pet.hide()
        else:
            self.pet.show()
            self.pet.raise_()

    def show_pet(self) -> None:
        if not self.pet.isVisible():
            self.pet.show()
        self.pet.raise_()

    # ------------------------------------------------------------ 槽

    def _set_scale(self, scale: float) -> None:
        self.pet.apply_scale(scale)
        self.show_pet()
