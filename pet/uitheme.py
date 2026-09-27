"""界面外观的公共零件：中文字体回退链、对话框与面板的样式表。

**为什么这个模块在 pet 而不是 game 里**：字体回退链本来就是全程序共用的东西，
只是最早写小游戏时才第一次需要它（``game/common.py``）。现在桌宠自己也要开
对话框和面板，如果 pet 反过来去 import game，就成了 pet → game → pet 的循环。
所以把它放在最底层的 pet 包里，``game.common`` 从这儿取 —— 谁都能往下依赖，
谁也不许往上依赖。

全程序只留**一份**回退链：``main.apply_ui_font``（应用级默认字体）、
游戏 HUD、滚轮对话框、状态面板都从这里取。各写一份的代价是"某台机器上新加的
那个面板里中文全是方框"，而写它的人手上恰好装了那个字体，永远复现不了。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

#: 中文字体回退链。不同 Windows 上装的中文字体不一样，写死一个名字很容易翻车。
#: 末尾的 ``sans-serif`` 是给自绘与 QSS 用的兜底（``QFontDatabase`` 里查不到它，
#: 所以 ``apply_ui_font`` 只遍历它前面的部分）。
FONT_STACK: list[str] = [
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "SimHei",
    "Noto Sans CJK SC",
    "Source Han Sans SC",
    "DengXian",
    "sans-serif",
]

#: 自绘用的字体。给字号就行，别管系统里装的哪一款。
def ui_font(size: int, bold: bool = False) -> QFont:
    f = QFont()
    f.setFamilies(FONT_STACK)
    f.setPointSize(size)
    if bold:
        f.setWeight(QFont.Weight.Bold)
    return f


def qss_family() -> str:
    """把回退链写成 QSS 的 ``font-family`` 值（带引号、逗号分隔）。"""
    return ", ".join(f'"{name}"' for name in FONT_STACK)


# ---------------------------------------------------------------- 配色

#: 面板 / 对话框共用的颜色。改一处，两个窗口一起变。
INK = "#2b3340"          # 主文字
INK_SOFT = "#6b7688"     # 次要文字
INK_FAINT = "#98a2b3"    # 提示文字
LINE = "#e2e8f0"         # 分隔线 / 描边
SURFACE = "#ffffff"      # 卡片底
ACCENT = "#4a6cf7"       # 主色（按钮、进度条）
ACCENT_DARK = "#3b5bdb"  # 主色按下
TRACK = "#eef1f6"        # 进度条底槽


def dialog_qss(family: str | None = None) -> str:
    """对话框/面板的通用样式。``family`` 省略就用回退链。"""
    fam = family or qss_family()
    return (
        f"QDialog, QWidget#panel {{ background: {SURFACE}; font-family: {fam}; }}"
        f"QLabel {{ color: {INK}; font-family: {fam}; }}"
        f"QLabel#hint {{ color: {INK_SOFT}; }}"
        f"QLabel#big {{ color: {ACCENT}; }}"
        f"QPushButton {{ background: {TRACK}; color: {INK}; border: none;"
        f" padding: 7px 18px; border-radius: 8px; font-size: 13px;"
        f" font-family: {fam}; }}"
        f"QPushButton:hover {{ background: #e2e7f0; }}"
        f"QPushButton#primary {{ background: {ACCENT}; color: white; }}"
        f"QPushButton#primary:hover {{ background: {ACCENT_DARK}; }}"
        f"QPushButton#chip {{ padding: 5px 12px; font-size: 12px;"
        f" border-radius: 14px; background: #eef2ff; color: {ACCENT_DARK}; }}"
        f"QPushButton#chip:hover {{ background: #e0e7ff; }}"
        f"QFrame#card {{ background: #fbfcfe; border: 1px solid {LINE};"
        f" border-radius: 10px; }}"
        f"QFrame#rule {{ background: {LINE}; border: none; max-height: 1px; }}"
    )


def apply_overlay_flags(widget, *, topmost: bool = True) -> None:
    """把窗口调成"桌面挂件"那套标志：无边框、透明、置顶、**绝不抢焦点**。

    这套配方原本只写在 ``PetWindow._apply_window_flags`` 里，现在状态气泡
    也要一模一样的一套 —— 与其抄第二遍再写一句"记得和 window.py 保持一致"，
    不如就这一份。抄第二遍的代价是：改了窗体的某一条，气泡那边不会跟着改，
    而症状是"鼠标一划过，正在打的字就断了"，且只在某些机器上出现。

    注意第 2 条属性必须配合带 alpha 的贴图/自绘；只设属性而画一块不透明的底，
    窗口就是一个白方块。
    """
    flags = (Qt.WindowType.FramelessWindowHint
             | Qt.WindowType.Tool
             | Qt.WindowType.NoDropShadowWindowHint
             | Qt.WindowType.WindowDoesNotAcceptFocus)
    if topmost:
        flags |= Qt.WindowType.WindowStaysOnTopHint
    widget.setWindowFlags(flags)

    widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    widget.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
    widget.setAttribute(Qt.WidgetAttribute.WA_AlwaysStackOnTop, True)
    widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
