"""背包面板：一个独立的常驻窗口，看金币、盘点背包、直接使用道具。

状态显示的三次收缩（这一节是设计记录，别删）
--------------------------------------------

**第一版**：状态只出现在右键菜单顶上那**一行**摘要（而且状态正常时只有
"状态不错"四个字），和小卖部子菜单里的一行数字。换句话说：**用户不点开
两个菜单，就完全不知道自己的狗饿不饿。** "养成"这件事，反馈看不见就等于
不存在。

**第二版（v2.1.0）**：补了三个显示面 —— 常驻面板（金币 + 三条状态条 + 背包）、
鼠标划过狗时弹出的浮卡、托盘 tooltip。

**第三版（v2.2.0，现在）**：把"划过就弹"那个浮卡**删掉**了。用户的原话是
"不要这样一碰到小狗就显示这么大个窗口，只用保留右键后显示的状态值就行"。
这个反馈是对的，第一个版本的问题被我过度修正了：

* 桌宠是**常驻桌面**的东西，鼠标从它身上划过是**最高频**的意外动作 ——
  拖窗口、选文件、划到屏幕右下角，一天能碰上几十次。每一次都弹一个
  178px 宽的窗口，那已经不是"看得见"，是**打扰**。而桌宠的硬约束恰恰是
  绝不打断用户（见 ``pet/window.py`` 模块开头）。
* 状态是**按分钟级的速率衰减**的东西，值得"想起来的时候看一眼"，
  不值得"每次路过都汇报一次"。这两件事的频次差了两个数量级。

所以最终留两个面，都是**用户主动**触发的：

    | 右键菜单顶上两行 | 状态三值 + 金币 + 该管了的那条 | 最常用：想看一眼 |
    | 托盘 tooltip     | 同上，鼠标停一下就有            | 连右键都不用点   |

顺带把面板里的三条状态条也撤了 —— 既然"状态值只在右键菜单看"是用户的
选择，面板里再放一套就是**两处口径**。面板退成纯粹的**背包**：金币打头，
下面是每样东西几个、点「使用」当场生效。这一层它本来就有独立价值
（子菜单一行行点只能"用掉"，看不全也点不顺手）。

为什么面板是独立窗口、而"划过的提示"当初也得是另一个窗口
--------------------------------------------------------
面板要能点按钮、要能看背包，就一定得接收焦点；而划过类的提示的**唯一硬约束
是绝不抢焦点**（用户可能正在输入框里打字，鼠标恰好划过桌宠）。两种窗口标志
互斥，所以当初只能是两个窗口类。现在划过那层删了，这个矛盾也就不存在了 ——
本模块只剩一个有焦点的正经窗口。
"""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout, QWidget)

from . import uitheme
from .config import Config
from .menu import SHOP, gains_text


class BagPanel(QWidget):
    """一个独立的常驻窗口：金币 + 背包。

    尺寸固定、不可缩放：里面的数据是按像素排的，能拉伸的窗口只会得到一堆
    奇怪的空白。要变大就用系统缩放（``cfg.scale``），那是另一回事。

    它是**只读的显示层**：不认识 ``Bag`` 也不改 ``Vitals``，只问"现在是多少"。
    所以不存在"面板和真实状态不一致"这种 bug，最多是慢一拍，而那一拍由
    1 秒的定时器补上。买与用的判定都在 ``PetWindow`` 那边（权威判定只有一处）。
    """

    WIDTH = 348

    def __init__(self, pet, cfg: Config, parent=None):
        super().__init__(parent)
        self.pet = pet
        self.cfg = cfg

        self.setWindowTitle("桌宠 · 背包")
        self.setObjectName("panel")
        # 普通 QWidget 子类想用 QSS 的 background，必须先声明"我自己画背景"
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(uitheme.dialog_qss())
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        self._cards: dict[str, tuple[QLabel, QPushButton]] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        root.addLayout(self._build_money_row())
        root.addWidget(self._rule())

        self.bag_title = QLabel("", self)
        self.bag_title.setFont(uitheme.ui_font(10, bold=True))
        root.addWidget(self.bag_title)

        self.grid = QGridLayout()
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(10)
        self.grid.setVerticalSpacing(10)
        root.addLayout(self.grid)
        self._build_cards()

        self.tip = QLabel("用小卖部买、在这里用；点「使用」才会生效", self)
        self.tip.setObjectName("hint")
        self.tip.setFont(uitheme.ui_font(9))
        root.addWidget(self.tip)
        self.where = self._where_row()
        root.addWidget(self.where)
        root.addStretch(1)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.refresh)

        self.refresh()
        self.setFixedSize(self.WIDTH, self.sizeHint().height())

    # ------------------------------------------------------------ 零件

    def _build_money_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        cap = QLabel("金币", self)
        cap.setFont(uitheme.ui_font(10))
        cap.setStyleSheet(f"color:{uitheme.INK_SOFT};")

        self.money = QLabel("0", self)
        self.money.setObjectName("big")
        self.money.setFont(uitheme.ui_font(22, bold=True))
        self.money.setAlignment(Qt.AlignmentFlag.AlignRight
                                | Qt.AlignmentFlag.AlignVCenter)

        row.addWidget(cap, 0, Qt.AlignmentFlag.AlignBottom)
        row.addStretch(1)
        row.addWidget(self.money)
        return row

    def _rule(self) -> QFrame:
        rule = QFrame(self)
        rule.setObjectName("rule")
        rule.setFrameShape(QFrame.Shape.HLine)
        rule.setFixedHeight(1)
        return rule

    def _where_row(self) -> QLabel:
        """告诉用户状态值去哪儿看。

        存这一行的理由：把状态条从面板里撤掉之后，**面板上没有任何一处
        提到它饿不饿** —— 用户如果本来习惯在这里看，会以为状态显示没了。
        指明去处比让人自己找强，成本就是一行灰字。
        """
        hint = QLabel("它饿不饿、困不困：右键它，菜单第一行", self)
        hint.setObjectName("hint")
        hint.setFont(uitheme.ui_font(9))
        return hint

    def _build_cards(self) -> None:
        """按 ``SHOP`` 一次建好格子，之后只改文字。

        和「小卖部」同一个取舍：**没有的东西也留着位置**（灰着、写着 ×0），
        用户才知道"还能有这些"。空着的格子直接不显示的话，背包看起来
        就永远只有一两样东西，攒钱的动力也就没了。
        """
        for i, item in enumerate(SHOP):
            card = QFrame(self)
            card.setObjectName("card")
            col = QVBoxLayout(card)
            col.setContentsMargins(8, 8, 8, 8)
            col.setSpacing(2)

            name = QLabel(item.label, card)
            name.setFont(uitheme.ui_font(10, bold=True))
            name.setAlignment(Qt.AlignmentFlag.AlignCenter)

            count = QLabel("×0", card)
            count.setFont(uitheme.ui_font(13, bold=True))
            count.setAlignment(Qt.AlignmentFlag.AlignCenter)
            count.setStyleSheet(f"color:{uitheme.ACCENT};")
            count.setToolTip(gains_text(item))

            use = QPushButton("使用", card)
            use.setFont(uitheme.ui_font(9))
            use.setFixedHeight(26)
            use.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            use.setCursor(Qt.CursorShape.PointingHandCursor)
            use.clicked.connect(lambda _=False, k=item.key: self._use(k))

            col.addWidget(name)
            col.addWidget(count)
            col.addWidget(use)
            self.grid.addWidget(card, 0, i)
            self._cards[item.key] = (count, use)

    # ------------------------------------------------------------ 行为

    def _use(self, key: str) -> None:
        """按一下「使用」= ``PetWindow.use_item``。

        **判定在窗口那边**（东西够不够、加到哪一项），面板只管转发 ——
        和菜单转发 ``buy`` 是同一个道理：面板可能比背包旧一帧。
        """
        self.pet.use_item(key)
        self.refresh()

    def refresh(self) -> None:
        """把数据源的最新值搬进控件。"""
        self.money.setText(str(self.cfg.coins))

        bag = self.pet.bag
        self.bag_title.setText(f"背包　共 {bag.total()} 件")
        for key, (count, use) in self._cards.items():
            n = bag.count(key)
            count.setText(f"×{n}")
            use.setEnabled(n > 0)

    # ------------------------------------------------------------ 显示

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()
        self._timer.start()

    def hideEvent(self, event) -> None:
        self._timer.stop()          # 藏起来了就别白跑定时器
        super().hideEvent(event)

    def center_on(self, bounds: QRect | None = None) -> None:
        self.adjustSize()
        if bounds is None:
            screen = self.screen()
            bounds = screen.availableGeometry() if screen else QRect(0, 0, 1280, 720)
        self.move(bounds.center().x() - self.width() // 2,
                  bounds.top() + max(40, (bounds.height() - self.height()) // 3))
