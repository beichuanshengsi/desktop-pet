"""桌宠程序入口。

启动顺序有讲究：
    QApplication 之前  -> 设置高 DPI 取整策略
    QApplication 之后  -> 才能创建 QPixmap（AssetBank 依赖它）
    建窗口之前         -> 检查贴图目录，否则首启可能是一片空白
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt, QTimer                          # noqa: E402
from PySide6.QtGui import QGuiApplication, QIcon                # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox        # noqa: E402

from pet import __version__                                      # noqa: E402
from pet import backup                                           # noqa: E402
from pet import icon as iconlib                                 # noqa: E402
from pet import kids as kidslib                                  # noqa: E402
from pet import uitheme                                          # noqa: E402
from pet.assets import AssetBank                                 # noqa: E402
from pet.config import Config, now_stamp                        # noqa: E402
from pet.paths import asset_dir, pet_asset_dir, user_asset_dir  # noqa: E402
from pet.pomodoro import describe as describe_span              # noqa: E402
from pet.tray import PetTray                                     # noqa: E402
from pet.window import PetWindow                                 # noqa: E402
from game import DEFAULT_GAME, GAMES, GameWindow, create_game    # noqa: E402


def check_pet_assets() -> None:
    """贴图目录空了就说一声人话。

    这里**不再自动生成内置贴图**了：那两套代码画的形象（``pet/assetgen*.py``）
    已在 2026-09-22 全部删除，贴图现在完全来自素材目录。

    目录空着程序也不会崩（窗口就是一片透明），但不说一声很容易被当成"启动失败"
    —— 所以把该往哪儿放说清楚。
    """
    d = pet_asset_dir()
    if any(d.glob("*.png")):
        return
    print(f"[assets] 警告：{d} 下没有任何贴图，桌面上会看不到东西。")
    print(f"[assets]        把 128×128 透明 PNG 按 <状态>_<序号>.png 放进去，"
          f"例如 {d / 'idle_00.png'}")
    print(f"[assets]        或者把素材丢进 {asset_dir('raw') / 'inbox'} 再跑 "
          f"python tools/intake.py --apply")
    print(f"[assets]        用户素材目录（优先级更高）：{user_asset_dir('pet')}")


def ensure_icon() -> None:
    """图标缺失时补一个。

    只补不覆盖 —— 图标是用户可能特意换过的资产，程序没有资格替它决定。
    """
    if (asset_dir() / "icon.png").exists():
        return
    try:
        rep = iconlib.refresh()
        print(f"[icon] 图标缺失，已按 {rep['source'].name} 生成 -> {rep['png']}")
    except Exception as exc:                       # noqa: BLE001
        print(f"[icon] 生成图标失败：{exc}（将没有托盘图标）")


def apply_ui_font(qapp: QApplication) -> str | None:
    """给整个程序装一条中文字体回退链。

    不同 Windows 上装的中文字体不一样，写死一个字体名迟早会在某台机器上
    变成一排方框。这里按优先级挑第一个系统里真的存在的。

    回退链本身住在 ``pet/uitheme.py`` —— 游戏 HUD、滚轮对话框、状态面板
    都从那儿取同一份，**别在这里另抄一张表**（抄了就会漂）。
    """
    from PySide6.QtGui import QFont, QFontDatabase
    available = set(QFontDatabase.families())
    for name in uitheme.FONT_STACK:
        if name in available:
            qapp.setFont(QFont(name, 9))
            return name
    return None


class DesktopPetApp:
    """把窗口、托盘、小游戏串起来的中枢。"""

    def __init__(self, qapp: QApplication, cfg: Config | None = None):
        self.qapp = qapp
        # 先留一份今天的快照再动任何东西 —— 存档只有一份，出事时那份旧的就是
        # 全部线索（见 pet/backup.py）。失败也只是少一份快照，不影响启动。
        backup.snapshot_daily()

        self.cfg = cfg if cfg is not None else Config.load()
        if not self.cfg.launched_at:
            self.cfg.launched_at = now_stamp()
            self.cfg.save()

        self.bank = AssetBank(pet_asset_dir()).load()
        if not self.bank.ok():
            print(f"[assets] 警告：{pet_asset_dir()} 下找不到任何贴图")

        self.pet = PetWindow(self.cfg, self.bank, GAMES)
        self.pet.request_game.connect(self.open_game)
        self.pet.request_quit.connect(self.quit)
        self.pet.pomodoro_done.connect(self._on_pomodoro_done)
        self.pet.notify.connect(self._on_notify)

        # 图标走 pet.icon：.ico 里带了 16/24/32/48/64/128/256 各尺寸，
        # Windows 按场景自己挑（托盘 16、任务栏 32、Alt-Tab 64），比自己缩 .png 清晰
        icon_path = iconlib.app_icon_path()
        self.icon = QIcon(str(icon_path)) if icon_path.exists() else QIcon()
        # 应用级也设一份：没单独设图标的窗口（含以后新加的对话框）都继承它，
        # 否则 Windows 会拿 python.exe 的图标顶上去
        self.qapp.setWindowIcon(self.icon)
        self.tray = PetTray(icon_path, self.pet, self.cfg,
                            on_quit=self.quit, on_game=self.open_game, games=GAMES)
        self.tray.show()

        # 幼儿模式（见 pet/kids.py）。它只认识 cfg / 桌宠 / 托盘这三样，
        # 窗口那一侧的接线全在这儿 —— 控制器自己不去管"谁来开游戏"。
        self.kids = kidslib.KidsMode(self.cfg, self.pet, self.tray)
        self.pet.request_kids.connect(self.on_kids)
        self.kids.entered.connect(self._on_kids_entered)
        self.kids.left.connect(self._on_kids_left)

        # 同一时刻只开一个游戏窗口（两个都开着的话，两边计时器都在跑，
        # 而且托盘菜单里没法看出哪个是"当前这个"）
        #
        # 类型写 GameWindow 而不是 QWidget：下面要连 closed 信号，
        # 那是 game.common.GameWindow 给两个游戏统一提供的契约
        self.game: GameWindow | None = None
        self.game_kind: str | None = None
        if self.cfg.show_on_start:
            self.pet.show()

    # ------------------------------------------------------------ 小游戏

    def open_game(self, kind: str = DEFAULT_GAME) -> None:
        if self.game is not None and self.game.isVisible():
            if self.game_kind == kind:
                self.game.raise_()
                self.game.activateWindow()
                self.game.setFocus()
                return
            self._close_game()             # 换一个游戏：先收掉旧的，暂停状态保持

        self.tray.show_pet()
        self.pet.set_paused(True)          # 游戏期间冻结桌面漫步，避免两边打架

        self.game = create_game(kind, self.bank, self.cfg)
        self.game_kind = kind
        self.game.setWindowIcon(self.icon)
        self.game.closed.connect(self._on_game_closed)
        self.game.show()
        # 幼儿模式开着的话，游戏窗口也得抬到遮罩之上 —— 不然它是"开出来了
        # 但被玻璃压在下面"，用户看到的是"点了没反应"。放在 show() 之后调，
        # 是因为它内部要用 setWindowFlag 加置顶（那会让窗口隐藏再重新显示）。
        self.kids.adopt(self.game)
        self.game.raise_()
        self.game.activateWindow()
        self.game.setFocus()

    def _close_game(self) -> None:
        """拆掉当前游戏窗口，但**不动**暂停状态（换游戏时接管方还要用）。"""
        if self.game is None:
            return
        game, self.game = self.game, None
        self.game_kind = None
        # 先断开，免得 close 触发的 closed 又把 _on_game_closed 跑一遍、解除暂停
        try:
            game.closed.disconnect(self._on_game_closed)
        except (RuntimeError, TypeError):
            pass
        game.close()
        game.deleteLater()

    def _on_game_closed(self, score: int) -> None:
        self.pet.set_paused(False)
        self.tray.refresh()
        if self.game is not None:
            self.game.deleteLater()
            self.game = None
        self.game_kind = None

    # ------------------------------------------------------------ 番茄钟

    def _on_pomodoro_done(self, seconds: int) -> None:
        """番茄钟到点：弹一个托盘气泡。

        为什么用气泡而不是自己弹个窗口：用户设番茄钟就是为了专心做事，那一刻他
        多半正在别的窗口里。气泡会自己消失、不抢焦点，是**唯一不打断他的提醒方式**
        —— 跟桌宠自己"绝不抢焦点"那条硬约束是一路的。

        参数是**秒**（时长现在由用户在滚轮上自己滚，1 秒 ~ 2 小时都可能），
        说法交给 ``pomodoro.describe`` 统一翻 —— 别在这儿拼字符串，
        否则"50 分钟"和"45 秒"迟早被写成同一句别扭的话。
        """
        self.tray.showMessage("番茄钟", f"{describe_span(seconds)}到了，起来动一动吧",
                              self.icon, 12000)

    # ------------------------------------------------------------ 托盘气泡

    def _on_notify(self, title: str, text: str) -> None:
        """桌宠想跟用户说句话（买了东西、道具用掉、状态告急）。

        走和番茄钟同一条路：托盘气泡，不抢焦点、不弹窗。窗口那边拿不到托盘，
        所以它只负责 ``notify.emit()``，由这里出口 —— 跟 ``pomodoro_done`` 一个道理。
        """
        self.tray.showMessage(title, text, self.icon, 6000)

    # ------------------------------------------------------------ 幼儿模式

    def on_kids(self, command: str) -> None:
        """右键菜单里「幼儿模式」那几项。命令的含义见 ``PetWindow.request_kids``。

        密码/遮罩/钩子的细节都在 ``pet/kids.py``，这里只做三件窗口管不了的事：
        **问密码**、**把"严格档其实没生效"说出来**、**同步桌宠的菜单锁定态**。
        """
        if command == "passcode":
            kidslib.ask_new_passcode(self.pet, self.cfg)
            return

        strict = command == "strict"
        if not kidslib.ensure_passcode(self.pet, self.cfg):
            return              # 用户在设密码那一步取消了：那就什么也不做

        got = self.kids.enter(strict)
        if got == "fail":
            self.tray.showMessage("幼儿模式没开成",
                                  "退出密码不是 4 位半角数字，先设一个再开。",
                                  self.icon, 8000)
            return
        if strict and got == "safe":
            # 钩子没装上（多半被安全软件拦了）。**这件事必须说出来** ——
            # 不说的后果是用户以为锁死了，其实 Win 键还能按，而他不会去验。
            # 用 singleShot 推一拍，让遮罩先铺好再弹，看起来更顺。
            QTimer.singleShot(0, lambda: QMessageBox.warning(
                self.pet, "严格档没生效",
                kidslib.mode_note(True, got) + "\n\n"
                "键盘钩子没装成功，通常是被安全软件拦下了（它和键盘记录器用同一个"
                "系统接口）。遮罩已经铺好，桌宠照常能玩。"))

    def _on_kids_entered(self, _mode: str) -> None:
        # 锁着的时候右键菜单必须砍掉「退出」「藏进托盘」和那几个开关，
        # 否则小朋友右键一下就能自己解开（见 PetWindow._build_menu）
        self.pet.kids_locked = True

    def _on_kids_left(self) -> None:
        self.pet.kids_locked = False

    # ------------------------------------------------------------ 退出

    def quit(self) -> None:
        # 钩子是**系统级**的：程序退了它还挂着，Win 键会莫名其妙失效，
        # 而用户完全联想不到是桌宠。所以这里必须先卸干净。
        self.kids.shutdown()
        self.cfg.save()
        self.tray.hide()
        self.pet.close()
        self.qapp.quit()


def main() -> int:
    # 必须在 QApplication 构造前设置，否则多显示器 + 125%/150% 缩放下坐标会跳变
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    qapp = QApplication(sys.argv)
    qapp.setApplicationName("DesktopPet")
    qapp.setApplicationDisplayName("桌宠")
    qapp.setApplicationVersion(__version__)
    qapp.setQuitOnLastWindowClosed(False)      # 藏进托盘不算退出

    check_pet_assets()
    ensure_icon()
    apply_ui_font(qapp)
    DesktopPetApp(qapp)
    return qapp.exec()


if __name__ == "__main__":
    raise SystemExit(main())
