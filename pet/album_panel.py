"""卡册面板：翻页看 104 张线条小狗，抽卡、分解、兑换、装备都在这里。

它是这次新增的"收集系统"的门面。设计上有四条沿用自 ``pet/panel.py`` 的规矩：

1. **固定尺寸、不可缩放** —— 里面的东西按像素排，能拉伸的窗口只会得到一脸空白。
2. **只做显示与转发** —— 判定（金币够不够、额度还剩几次、能不能分解）
   全在 ``PetWindow`` 那边，那边再往下问 ``pet/cards.py``。面板可能比数据旧一帧，
   按钮的灰只是提示，绝不能当成判定。
3. **没有的东西也留着位置** —— 和背包一样，未收集的卡显示成**剪影**而不是
   直接不画。空着不显示的话，用户根本不知道还有 90 多张可以收集。
4. **用户主动打开才存在** —— 懒建、复用、关掉不销毁（见 ``PetWindow.open_album``）。

为什么一页 12 张、翻页而不是滚动
--------------------------------
104 张按 4×3 分页正好 9 页。滚动条的坏处是**用户永远不知道自己收集了多少** ——
滚动条的长度不代表进度，而"第 3 页 / 共 9 页"一眼就懂。翻页还顺带把
"每页只加载 12 张图"这件事变成天然的懒加载：104 张缩略图一次性塞进
窗口太浪费，按页取就刚好。
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QPushButton, QToolButton, QVBoxLayout,
                               QWidget)

from . import uitheme
from .cards import COST, Card, TIERS
from .config import Config


def _faint(colour: str, alpha: float = 0.32) -> str:
    """把一个色值转成同色的半透明 ``rgba()`` 写法，给"未收集"的格子用。

    未收集的格子**保留档位色但压淡**：一下子去掉颜色的话，用户翻到第 5 页
    就不知道这一页是"传说"还是"普通"，也就看不出自己还差哪些档 ——
    而"还差几张传说"恰恰是这套系统里最想知道的那个数。
    """
    c = QColor(colour)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha})"


def _tile_qss() -> str:
    """格子与稀有度描边的样式。

    **描边颜色走属性选择器**（``QToolButton[tier="传说"]``）而不是每张卡
    塞一段内联 style：内联的话，同一张卡的格子、徽章栏、详情行要各写一遍
    那四个色值，改配色就有三处要跟着改。
    """
    rules = [
        f"QToolButton#tile {{ background:#fbfcfe; border:2px solid {uitheme.LINE};"
        f" border-radius:10px; padding:3px; color:{uitheme.INK_SOFT}; font-size:11px; }}",
        f"QToolButton#tile:hover {{ background:#f3f6fd; }}",
        f"QToolButton#tile:checked {{ border-color:{uitheme.ACCENT};"
        f" background:#eef2ff; color:{uitheme.ACCENT_DARK}; }}",
        f"QToolButton#tile:disabled {{ color:{uitheme.INK_FAINT}; }}",
    ]
    for tier, colour in uitheme.TIER_COLOR.items():
        rules.append(
            f'QToolButton#tile[tier="{tier}"] {{ border-color:{colour}; }}')
        # 未收集：同一个色但压淡，并且底色更灰 —— "空位"和"已有"必须一眼分开
        rules.append(
            f'QToolButton#tile[tier="{tier}"][owned="0"] {{'
            f' border-color:{_faint(colour)}; background:#f8fafc; }}')
        rules.append(
            f'QToolButton#tile[tier="{tier}"]:checked {{ border-color:{uitheme.ACCENT}; }}')
    rules.append(
        f"QPushButton#gacha {{ background:{uitheme.ACCENT}; color:white;"
        f" padding:11px 18px; font-size:14px; font-weight:bold; border-radius:10px; }}")
    rules.append(
        f"QPushButton#gacha:hover {{ background:{uitheme.ACCENT_DARK}; }}")
    rules.append(
        f"QPushButton#gacha:disabled {{ background:#c9d2e3; color:#eef1f6; }}")
    rules.append(
        f"QPushButton#trade {{ background:#f1f4fa; color:{uitheme.INK};"
        f" padding:6px 4px; font-size:11px; border-radius:8px;"
        f" border:1px solid {uitheme.LINE}; }}")
    rules.append(
        f"QPushButton#trade:hover {{ background:#e6ecf8; }}")
    rules.append(
        f"QPushButton#trade:disabled {{ color:{uitheme.INK_FAINT}; background:#f7f9fc; }}")
    rules.append(
        f"QLabel#tier {{ color:{uitheme.INK}; font-weight:bold; }}")
    rules.append(
        f"QLabel#warn {{ color:#d9534f; }}")
    return "".join(rules)


class AlbumPanel(QWidget):
    """卡册窗口。一个顶层窗口，有焦点、能点按钮。"""

    COLS = 4
    ROWS = 3
    PAGE = COLS * ROWS
    TILE_W = 104
    TILE_H = 126
    WIDTH = 496

    def __init__(self, pet, cfg: Config, parent=None):
        super().__init__(parent)
        self.pet = pet
        self.cfg = cfg
        self.album = pet.album

        self.setWindowTitle("桌宠 · 卡册")
        self.setObjectName("panel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(uitheme.dialog_qss() + _tile_qss())
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        self._cards: list[Card] = list(self.album.all_cards())
        self._page = 0
        self._selected: str | None = None
        self._icons: dict[str, QPixmap] = {}       # 缩略图缓存（按卡 id）
        self._cells: list[QToolButton] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(9)

        root.addLayout(self._build_head())
        root.addLayout(self._build_grid())
        root.addLayout(self._build_pager())
        root.addWidget(self._rule())
        root.addLayout(self._build_gacha())
        root.addWidget(self._frag_line())
        root.addLayout(self._build_trades())
        root.addWidget(self._rule())
        root.addLayout(self._build_selected())

        self.hint = QLabel("重复的卡可以分解成碎片，碎片攒够了在下面的「兑换」里换卡",
                           self)
        self.hint.setObjectName("hint")
        self.hint.setFont(uitheme.ui_font(9))
        root.addWidget(self.hint)
        root.addStretch(1)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.refresh)

        self.refresh()
        self.setFixedSize(self.WIDTH, self.sizeHint().height())

    # ------------------------------------------------------------ 零件

    def _rule(self) -> QFrame:
        rule = QFrame(self)
        rule.setObjectName("rule")
        rule.setFrameShape(QFrame.Shape.HLine)
        rule.setFixedHeight(1)
        return rule

    def _build_head(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)

        title = QLabel("卡册", self)
        title.setFont(uitheme.ui_font(15, bold=True))

        self.progress = QLabel("", self)
        self.progress.setObjectName("hint")
        self.progress.setFont(uitheme.ui_font(10))

        self.money = QLabel("0", self)
        self.money.setObjectName("big")
        self.money.setFont(uitheme.ui_font(16, bold=True))
        self.money.setAlignment(Qt.AlignmentFlag.AlignRight
                                | Qt.AlignmentFlag.AlignVCenter)

        coin_cap = QLabel("金币", self)
        coin_cap.setObjectName("hint")
        coin_cap.setFont(uitheme.ui_font(9))

        row.addWidget(title)
        row.addSpacing(8)
        row.addWidget(self.progress)
        row.addStretch(1)
        row.addWidget(coin_cap, 0, Qt.AlignmentFlag.AlignBottom)
        row.addWidget(self.money)
        return row

    def _build_grid(self) -> QGridLayout:
        grid = QGridLayout()
        grid.setContentsMargins(0, 2, 0, 2)
        grid.setSpacing(8)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for i in range(self.PAGE):
            btn = QToolButton(self)
            btn.setObjectName("tile")
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            btn.setIconSize(QSize(80, 80))
            btn.setFixedSize(self.TILE_W, self.TILE_H)
            btn.setCheckable(True)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, idx=i: self._on_cell(idx))
            self._group.addButton(btn)
            grid.addWidget(btn, i // self.COLS, i % self.COLS)
            self._cells.append(btn)
        return grid

    def _build_pager(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)

        self.prev = QPushButton("‹ 上一页", self)
        self.next = QPushButton("下一页 ›", self)
        for btn in (self.prev, self.next):
            btn.setObjectName("chip")
            btn.setFont(uitheme.ui_font(9))
            btn.setFixedHeight(26)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.prev.clicked.connect(lambda: self._turn(-1))
        self.next.clicked.connect(lambda: self._turn(1))

        self.page_label = QLabel("", self)
        self.page_label.setObjectName("hint")
        self.page_label.setFont(uitheme.ui_font(9))
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        row.addWidget(self.prev)
        row.addStretch(1)
        row.addWidget(self.page_label)
        row.addStretch(1)
        row.addWidget(self.next)
        return row

    def _build_gacha(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        left = QVBoxLayout()
        left.setSpacing(4)

        self.gacha = QPushButton("", self)
        self.gacha.setObjectName("gacha")
        self.gacha.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.gacha.setCursor(Qt.CursorShape.PointingHandCursor)
        self.gacha.clicked.connect(self._pull)

        self.result = QLabel("", self)
        self.result.setObjectName("hint")
        self.result.setFont(uitheme.ui_font(9))
        self.result.setWordWrap(True)

        left.addWidget(self.gacha)
        left.addWidget(self.result)

        row.addLayout(left, 3)

        self.convert = QPushButton("", self)
        self.convert.setObjectName("trade")
        self.convert.setFixedWidth(148)
        self.convert.setFixedHeight(52)
        self.convert.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.convert.setCursor(Qt.CursorShape.PointingHandCursor)
        self.convert.clicked.connect(self._convert)
        row.addWidget(self.convert, 0)
        return row

    def _frag_line(self) -> QLabel:
        self.frags = QLabel("", self)
        self.frags.setFont(uitheme.ui_font(10, bold=True))
        return self.frags

    def _build_trades(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self._trade_btns: dict[str, QPushButton] = {}
        for tier in TIERS:
            btn = QPushButton("", self)
            btn.setObjectName("trade")
            btn.setMinimumHeight(46)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, t=tier: self._exchange(t))
            row.addWidget(btn, 1)
            self._trade_btns[tier] = btn
        return row

    def _build_selected(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self.selected = QLabel("", self)
        self.selected.setFont(uitheme.ui_font(10))
        self.selected.setMinimumWidth(190)

        self.equip = QPushButton("装备", self)
        self.dissolve = QPushButton("分解", self)
        for btn in (self.equip, self.dissolve):
            btn.setObjectName("chip")
            btn.setFont(uitheme.ui_font(9))
            btn.setFixedHeight(28)
            btn.setFixedWidth(78)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.equip.clicked.connect(self._toggle_equip)
        self.dissolve.clicked.connect(self._dissolve)

        row.addWidget(self.selected)
        row.addStretch(1)
        row.addWidget(self.equip)
        row.addWidget(self.dissolve)
        return row

    # ------------------------------------------------------------ 缩略图

    def _thumb(self, cid: str) -> QPixmap:
        """取一张缩略图（带缓存）。文件缺失时返回空图，由调用方兜底。"""
        pm = self._icons.get(cid)
        if pm is None:
            pm = QPixmap(str(self.album.pool.thumb_path(cid)))
            self._icons[cid] = pm
        return pm

    @staticmethod
    def _silhouette(pm: QPixmap) -> QPixmap:
        """把图变成纯色剪影 —— 未收集的卡就该"看得见轮廓、看不清内容"。

        做法是标准的 SourceIn 合成：先画原图，再把一层纯色**只保留在原图
        不透明的地方**。比逐像素灰度化快，而且边缘的 alpha 过渡能原样保住
        （逐像素会把半透明边缘描成硬边，一群狗看起来像贴纸）。
        """
        out = QPixmap(pm.size())
        out.fill(Qt.GlobalColor.transparent)
        painter = QPainter(out)
        painter.drawPixmap(0, 0, pm)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(out.rect(), QColor(uitheme.SILHOUETTE))
        painter.end()
        return out

    def _icon(self, card: Card, owned: bool) -> QIcon:
        pm = self._thumb(card.id)
        if pm.isNull():
            # 素材缺了这一张：画一个问号方块，别让格子空着
            pm = QPixmap(80, 80)
            pm.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pm)
            painter.setPen(QColor(uitheme.INK_FAINT))
            painter.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "?")
            painter.end()
        elif not owned:
            pm = self._silhouette(pm)
        return QIcon(pm)

    # ------------------------------------------------------------ 翻页

    def _page_count(self) -> int:
        return max(1, (len(self._cards) + self.PAGE - 1) // self.PAGE)

    def _page_cards(self) -> list[Card]:
        start = self._page * self.PAGE
        return self._cards[start:start + self.PAGE]

    def _turn(self, delta: int) -> None:
        page = self._page + delta
        if 0 <= page < self._page_count():
            self._page = page
            self.refresh()

    # ------------------------------------------------------------ 交互

    def _on_cell(self, index: int) -> None:
        page = self._page_cards()
        if 0 <= index < len(page):
            self._selected = page[index].id
            self.refresh()

    def _label(self, card: Card) -> str:
        """卡片的人话名字。用"档位 + 该档内的序号"，比 id 好认。"""
        same = self.album.cards_of(card.tier)
        try:
            idx = next(i for i, c in enumerate(same) if c.id == card.id) + 1
        except StopIteration:
            idx = 0
        return f"{card.tier} {idx:02d}"

    def _pull(self) -> None:
        pull = self.pet.pull_card()
        if pull is None:
            self.result.setText(f"金币不够（一抽 {self.album.pull_cost()}），去玩一局再来")
            self.refresh()
            return
        tag = "新收集！" if pull.is_new else f"重复（已有 {pull.dup_count} 张）"
        self.result.setText(f"抽到 {self._label(pull.card)}　{tag}")
        self._selected = pull.card.id
        self._page = self._index_of(pull.card.id) // self.PAGE
        self.refresh()

    def _index_of(self, cid: str) -> int:
        for i, c in enumerate(self._cards):
            if c.id == cid:
                return i
        return 0

    def _exchange(self, tier: str) -> None:
        trade = self.pet.exchange_card(tier)
        if not trade.ok:
            self.result.setText(trade.reason)
        elif trade.card is None:
            self.result.setText("兑换失败")
        else:
            if trade.is_new:
                self.result.setText(f"换到 {self._label(trade.card)}　新收集！")
                self._selected = trade.card.id
                self._page = self._index_of(trade.card.id) // self.PAGE
            else:
                self.result.setText(
                    f"换到 {self._label(trade.card)}　重复，返还 {trade.refund} 碎片")
        self.refresh()

    def _convert(self) -> None:
        got = self.pet.convert_low(1)
        if got <= 0:
            self.result.setText("低级碎片不够，或本周的低换高额度用完了")
        else:
            self.result.setText("低级碎片 5:1 换到 1 个高级碎片")
        self.refresh()

    def _toggle_equip(self) -> None:
        """装上 / 卸下选中的卡。

        分两个分支调用 ``equip_card`` / ``unequip_card`` 而不是一个 toggle：
        "装不上"和"卸下了"都会让"现在装没装上"变成 False，靠返回值分不清
        到底是哪一种 —— 那种歧义最后一定变成"点了装备没反应"的报障。
        """
        cid = self._selected
        if cid is None:
            return
        if self.album.is_equipped(cid):
            self.pet.unequip_card(cid)
            self.result.setText("已卸下")
        elif self.pet.equip_card(cid):
            card = self.album.pool.get(cid)
            self.result.setText(f"已装备 {self._label(card)}　（{self.album.bonus_text()}）")
        else:
            self.result.setText(f"装不上：{self.album.can_equip(cid)}")
        self.refresh()

    def _dissolve(self) -> None:
        if self._selected is None:
            return
        ok, amount, kind = self.pet.dissolve_card(self._selected)
        if not ok:
            self.result.setText("只有一张，分解了图鉴就缺一角了")
        else:
            name = "低级碎片" if kind == "low" else "高级碎片"
            self.result.setText(f"分解了 1 张，得到 {amount} 个{name}")
        self.refresh()

    # ------------------------------------------------------------ 刷新

    def refresh(self) -> None:
        album = self.album

        if not album.pool:
            self.progress.setText("没找到卡册素材")
            self.gacha.setEnabled(False)
            return

        self.money.setText(str(self.cfg.coins))
        self.progress.setText(
            f"已收集 {album.owned_kinds()} / {album.total_kinds()}　"
            f"共 {album.duplicates()} 张重复")

        self._refresh_cells()
        self._refresh_pager()
        self._refresh_money_rows()
        self._refresh_selected()

    def _refresh_cells(self) -> None:
        page = self._page_cards()
        # 互斥组里 setChecked(False) 会被忽略（组内不允许全不选），
        # 所以逐个改选中状态前先把互斥关掉、改完再打开 —— 翻页时格子是
        # 复用的，不这么做的话旧页的选中框会跟着飘到新页上。
        self._group.setExclusive(False)
        for i, btn in enumerate(self._cells):
            if i >= len(page):
                btn.setVisible(False)
                continue
            card = page[i]
            btn.setVisible(True)
            n = self.album.count(card.id)
            btn.setIcon(self._icon(card, n > 0))
            btn.setText(f"×{n}" if n > 1 else ("已收集" if n else "未收集"))
            btn.setToolTip(f"{self._label(card)}　"
                           + (f"拥有 {n} 张" if n else "还没抽到")
                           + ("　· 已装备" if self.album.is_equipped(card.id) else ""))
            btn.setProperty("tier", card.tier)
            btn.setProperty("owned", "1" if n else "0")
            btn.style().unpolish(btn)          # 属性变了，样式要重新算一遍
            btn.style().polish(btn)
            btn.setChecked(card.id == self._selected)
        self._group.setExclusive(True)

    def _refresh_pager(self) -> None:
        self.page_label.setText(f"第 {self._page + 1} / {self._page_count()} 页")
        self.prev.setEnabled(self._page > 0)
        self.next.setEnabled(self._page + 1 < self._page_count())

    def _refresh_money_rows(self) -> None:
        album = self.album
        cost = album.pull_cost()
        self.gacha.setText(f"抽一次　·　{cost} 金币")
        self.gacha.setEnabled(album.can_pull())

        self.frags.setText(f"低级碎片 {self.cfg.frag_low}　·　高级碎片 {self.cfg.frag_high}")
        room = album.low_convert_capacity()
        self.convert.setText(
            f"低换高 5:1\n本周还可换 {room} 次")
        self.convert.setEnabled(room > 0)

        for tier, btn in self._trade_btns.items():
            left = album.week_left(tier)
            kind, price = COST[tier]
            name = "低级" if kind == "low" else "高级"
            btn.setText(f"{tier}　({price} {name})\n本周剩 {left} 次")
            btn.setEnabled(album.can_exchange(tier))
            btn.setToolTip(album.exchange_block_reason(tier) or "可以兑换")

    def _refresh_selected(self) -> None:
        cid = self._selected
        card = self.album.pool.get(cid) if cid else None
        if card is None:
            self.selected.setText("点一张卡看详情")
            self.equip.setEnabled(False)
            self.dissolve.setEnabled(False)
            self.equip.setText("装备")
            return

        n = self.album.count(card.id)
        if n <= 0:
            self.selected.setText(f"{self._label(card)}　·　还没抽到")
            self.equip.setEnabled(False)
            self.dissolve.setEnabled(False)
            self.equip.setText("装备")
            return

        on = self.album.is_equipped(card.id)
        self.selected.setText(f"{self._label(card)}　·　拥有 {n} 张")
        self.equip.setText("卸下" if on else "装备")
        self.equip.setEnabled(True)
        self.dissolve.setEnabled(n > 1)
        self.dissolve.setToolTip("必须留一张" if n <= 1 else "分解成碎片")

    # ------------------------------------------------------------ 显示

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()
        self._timer.start()

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def center_on(self, bounds=None) -> None:
        self.adjustSize()
        if bounds is None:
            screen = self.screen()
            bounds = screen.availableGeometry() if screen else None
        if bounds is None:
            return
        # 面板比屏幕还高时（小屏笔记本 + 高缩放），别按"三分之一处"摆 ——
        # 那样底部会掉出屏幕、翻页按钮永远点不到。贴顶放，至少整体可用。
        if self.height() >= bounds.height():
            top = bounds.top()
        else:
            top = bounds.top() + max(30, (bounds.height() - self.height()) // 3)
        self.move(bounds.center().x() - self.width() // 2, top)
