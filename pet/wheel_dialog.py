"""时长滚轮对话框 —— 用户在"时 / 分 / 秒"三列上滚出想要的番茄钟时长。

分开成"模型 + 控件"两层，理由和 ``behavior.py`` / ``window.py`` 一样：

* 取值规则（哪一列能滚出什么、怎么联动、上下限）在 ``pet/wheel.py``，纯逻辑、
  能喂固定输入断言；
* 这个文件只管**画出来、接住鼠标滚轮与拖动**。

为什么自己画而不是用 ``QSpinBox``
--------------------------------
需求要的是"滚轮下滑那种"手感：中间一格是选中项、上下能看到相邻的值、
滚到头会绕回另一端。``QSpinBox`` 是"输入框 + 上下小箭头"，既看不出相邻值，
也滚不出循环。所以中心那一格高亮、上下淡出的效果是必须自己画的 ——
``QWheelEvent`` 的接入也就顺手一起做了。

三个交互都通到同一个 ``WheelModel.scroll()``
-------------------------------------------

    | 鼠标滚轮 | 悬停在哪一列就滚哪一列（滚轮下滑 = 数值增大）      |
    | 拖动     | 按住往上下拉，每拉过一格的高度滚一格               |
    | 键盘     | ↑ ↓ 滚当前列，← → 换列                             |

它们只产生一个 ``delta``，剩下全交给模型 —— **循环、联动、夹紧都只有一份实现**，
不会出现"滚轮能滚到 2:30，拖动就不行"这种两套逻辑打架的 bug。
"""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from . import uitheme
from .menu import POMODORO_CHOICES
from .pomodoro import MAX_SECONDS, MIN_SECONDS, describe
from .wheel import COLUMNS, MINUTE, WheelModel

#: 一列滚轮的宽度
COL_W = 78
#: 一行的行高
ROW_H = 38
#: 中心格上下各能看到几行（总行数 = 2*VISIBLE + 1）
VISIBLE = 2
#: 顶部"时 / 分 / 秒"表头高度
HEAD_H = 22

PICKER_W = COL_W * len(COLUMNS)
PICKER_H = HEAD_H + ROW_H * (VISIBLE * 2 + 1)

ACCENT = QColor(uitheme.ACCENT)
INK = QColor(uitheme.INK)
FAINT = QColor(uitheme.INK_FAINT)


class WheelPicker(QWidget):
    """三列滚轮。改动时发 ``changed(seconds)``。"""

    changed = Signal(int)

    def __init__(self, parent=None, seconds: float | None = None):
        super().__init__(parent)
        self.model = WheelModel(seconds)
        #: 键盘操作针对哪一列
        self.focus_col = MINUTE
        #: 拖动状态：起点、已经消化掉的像素、从哪个值开始拖的
        self._drag_y: float | None = None
        self._drag_acc = 0.0
        self._drag_col = MINUTE

        self.setFixedSize(PICKER_W, PICKER_H)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self.setToolTip("滚轮下滑 / 按住拖动 / ↑↓ 都能调，←→ 换列")

    # ------------------------------------------------------------ 取值

    def seconds(self) -> float:
        return self.model.value

    def set_seconds(self, seconds: float) -> None:
        self.model.set_value(seconds)
        self._emit()

    def _emit(self) -> None:
        self.update()
        self.changed.emit(int(round(self.seconds())))

    def _col_at(self, x: float) -> int:
        """横坐标落在哪一列。越界夹到两端 —— 在边缘滚轮也该有反应。"""
        return max(0, min(len(COLUMNS) - 1, int(x // COL_W)))

    def _scroll(self, col: int, delta: int) -> None:
        self.model.scroll(col, delta)
        self.focus_col = col
        self._emit()

    # ------------------------------------------------------------ 鼠标

    def wheelEvent(self, event) -> None:
        """鼠标滚轮：**向下滚 = 数值增大**（"滚轮下滑"的手感）。

        触控板给的是 ``pixelDelta``，鼠标滚轮给的是 ``angleDelta``（一格 120）。
        两者都收，触控板上才不会"滚半天不动"。
        """
        dy = event.angleDelta().y() or event.pixelDelta().y()
        if not dy:
            return
        steps = -dy / 120.0 if event.angleDelta().y() else -dy / 18.0
        # 积累到整整一格才滚，避免触控板的碎步把一列滚飞
        self._drag_acc += steps
        whole = int(self._drag_acc)
        if whole:
            self._drag_acc -= whole
            self._scroll(self._col_at(event.position().x()), whole)
        event.accept()

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self._drag_y = event.position().y()
        self._drag_acc = 0.0
        self._drag_col = self._col_at(event.position().x())
        self.focus_col = self._drag_col
        self.update()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_y is None:
            # 只是划过：把当前列跟过去，才有"悬停高亮"的效果
            hover = self._col_at(event.position().x())
            if hover != self.focus_col and not self.hasFocus():
                self.focus_col = hover
                self.update()
            return
        # 拖动：往上拉 = 数值减小（和滚轮方向一致）
        dy = self._drag_y - event.position().y()
        self._drag_acc += dy / ROW_H
        whole = int(self._drag_acc)
        if whole:
            self._drag_acc -= whole
            self._scroll(self._drag_col, whole)
        self._drag_y = event.position().y()

    def mouseReleaseEvent(self, event) -> None:
        self._drag_y = None

    def leaveEvent(self, event) -> None:
        self._drag_y = None
        super().leaveEvent(event)

    # ------------------------------------------------------------ 键盘

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self._scroll(self.focus_col, -1 if key == Qt.Key.Key_Up else 1)
            return
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            step = -1 if key == Qt.Key.Key_Left else 1
            self.focus_col = (self.focus_col + step) % len(COLUMNS)
            self.update()
            return
        # 回车/ESC 交给对话框的默认按钮处理，别在这里吞掉
        super().keyPressEvent(event)

    # ------------------------------------------------------------ 绘制

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#f8fafc"))
        p.drawRoundedRect(QRect(0, 0, PICKER_W, PICKER_H), 12, 12)

        self._paint_head(p)
        self._paint_center_band(p)
        for col in range(len(COLUMNS)):
            self._paint_column(p, col)

    def _paint_head(self, p: QPainter) -> None:
        p.setFont(uitheme.ui_font(9))
        for col, (_key, label) in enumerate(COLUMNS):
            p.setPen(ACCENT if col == self.focus_col else FAINT)
            p.drawText(QRect(col * COL_W, 0, COL_W, HEAD_H),
                       Qt.AlignmentFlag.AlignCenter, label)

    def _center_top(self) -> int:
        return HEAD_H + VISIBLE * ROW_H

    def _paint_center_band(self, p: QPainter) -> None:
        """中间那一条选中带。上下各留 8px，左右合起来画一条，别每列一段。"""
        top = self._center_top()
        p.setPen(QPen(QColor(uitheme.ACCENT), 1))
        p.setBrush(QColor("#ffffff"))
        p.drawRoundedRect(QRect(4, top + 3, PICKER_W - 8, ROW_H - 6), 9, 9)

    def _paint_column(self, p: QPainter, col: int) -> None:
        """画一列：中心是选中项，上下各 ``VISIBLE`` 行，越远越淡。

        列里只有一个值时（比如"时"滚到 2，分和秒就只能是 0）**不能循环画**，
        否则上下会重复出现同一个数字，看着像坏了。
        """
        values = self.model.values(col)
        idx = self.model.index(col)
        top = self._center_top()
        x = col * COL_W

        for offset in range(-VISIBLE, VISIBLE + 1):
            if len(values) == 1:
                if offset != 0:
                    continue
                value = values[0]
            else:
                value = values[(idx + offset) % len(values)]

            y = top + offset * ROW_H
            if y < HEAD_H - ROW_H or y > PICKER_H:
                continue                      # 裁掉画不下的行

            dist = abs(offset)
            center = dist == 0
            if center:
                color = ACCENT
                font = uitheme.ui_font(15, bold=True)
            else:
                # 越远越淡：2 格以外基本只是"还有东西"的暗示
                alpha = (200, 150)[dist > 1]
                color = QColor(INK)
                color.setAlpha(alpha)
                font = uitheme.ui_font(11 if dist == 1 else 9)

            p.setFont(font)
            p.setPen(color)
            p.drawText(QRect(x, y, COL_W, ROW_H),
                       Qt.AlignmentFlag.AlignCenter, f"{value:02d}")

        # 分隔线（只在对齐中心带的那一段，免得整列被切得太硬）
        if col < len(COLUMNS) - 1:
            p.setPen(QPen(QColor("#e8edf5"), 1))
            line_x = (col + 1) * COL_W
            p.drawLine(line_x, top - ROW_H + 8, line_x, top + ROW_H - 8)


class DurationDialog(QDialog):
    """挑一个番茄钟时长。

    刻意**不给它 parent**：桌宠窗口带着 ``WindowDoesNotAcceptFocus`` 一整套
    "绝不抢焦点"的标志，Qt 的对话框会继承父窗口的一部分行为，在某些机器上
    就变成"对话框弹出来了但完全点不动"。独立顶层窗口 + 置顶（否则可能被
    用户正在用的窗口盖住）反而最稳。
    """

    def __init__(self, seconds: float | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("番茄钟 · 选择时长")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setStyleSheet(uitheme.dialog_qss())

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(12)

        self.big = QLabel("", self)
        self.big.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.big.setFont(uitheme.ui_font(17, bold=True))
        self.big.setStyleSheet(f"color:{uitheme.ACCENT};")

        self.hint = QLabel(f"滚轮 / 拖动 / ↑↓ 调节，范围 {describe(MIN_SECONDS)} ~ "
                           f"{describe(MAX_SECONDS)}", self)
        self.hint.setObjectName("hint")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint.setFont(uitheme.ui_font(9))

        self.picker = WheelPicker(self, seconds)
        self.picker.changed.connect(self._on_changed)

        root.addWidget(self.big)
        root.addWidget(self.hint, 0, Qt.AlignmentFlag.AlignHCenter)
        root.addWidget(self.picker, 0, Qt.AlignmentFlag.AlignHCenter)
        root.addWidget(self._build_chips(), 0, Qt.AlignmentFlag.AlignHCenter)
        root.addWidget(self._build_buttons())

        self._on_changed(int(round(self.picker.seconds())))
        self.picker.setFocus()

    # ------------------------------------------------------------ 零件

    def _build_chips(self) -> QWidget:
        """快捷档位。滚轮是"自己调"，但绝大多数人还是想要 25 分钟一下点到。

        直接复用 ``menu.POMODORO_CHOICES`` —— 菜单里的档位和这里的按钮
        **必须是同一份清单**，否则会出现"菜单里有 50 分钟、对话框里没有"。
        """
        box = QWidget(self)
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        for secs in POMODORO_CHOICES:
            btn = QPushButton(describe(secs), box)
            btn.setObjectName("chip")
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, s=secs: self._apply_chip(s))
            row.addWidget(btn)
        return box

    def _build_buttons(self) -> QWidget:
        box = QWidget(self)
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 4, 0, 0)
        row.setSpacing(8)

        cancel = QPushButton("取消", box)
        cancel.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        cancel.clicked.connect(self.reject)

        ok = QPushButton("开始专注", box)
        ok.setObjectName("primary")
        ok.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        ok.setDefault(True)
        ok.clicked.connect(self.accept)

        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(ok)
        return box

    # ------------------------------------------------------------ 行为

    def _apply_chip(self, seconds: int) -> None:
        """点到"2 小时"这种上限档时，模型会自己把分秒清零。"""
        self.picker.set_seconds(seconds)

    def _on_changed(self, seconds: int) -> None:
        """把当前选择说成人话显示在最上面 —— 三列数字是给手用的，
        这一行是给眼睛确认的（"1 小时 5 分"比 "01 05 00" 好认）。"""
        self.big.setText(describe(seconds))

    def selected_seconds(self) -> int:
        return int(round(self.picker.seconds()))

    # ------------------------------------------------------------ 位置

    def center_on(self, rect: QRect | None = None) -> None:
        """摆在给定矩形中间（给的通常是桌宠所在屏幕的工作区）。

        每次都摆到屏幕中央，是为了"我点了菜单、对话框就出现在我正看着的地方"。
        跟着桌宠摆的话，桌宠可能缩在屏幕角上，对话框会有一半在屏幕外。
        """
        self.adjustSize()
        if rect is None:
            screen = self.screen()
            rect = screen.availableGeometry() if screen else QRect(0, 0, 1280, 720)
        self.move(rect.center().x() - self.width() // 2,
                  rect.center().y() - self.height() // 2)


__all__ = ["DurationDialog", "WheelPicker"]
