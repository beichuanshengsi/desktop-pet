"""装备徽章栏：右键菜单里那一排小方块。

为什么是"菜单里的一行"而不是"挂在宠物旁边"
------------------------------------------
卡片是 630×630 的整只狗图，挂在宠物旁边会跟主宠物抢视觉（两只狗贴在一起，
用户第一眼分不清哪只是"我的狗"）。而右键菜单是用户**主动打开**的区域 ——
放徽章不干扰桌面，位置也天然是"查看自己有什么"的地方。

只做展示，不做操作
------------------
装/卸都在卡册里（那里有完整的卡面、数量、碎片信息）。如果菜单里也能装，
就要在这里再写一遍"槽位够不够、这张装过没有"的判定，迟早和卡册那边分叉 ——
分叉的症状是"菜单说装上了、卡册说没装"，最难查的一类 bug。

画在哪里、用什么颜色
--------------------
**底色一律不画**，让 QMenu 自己的背景透出来。菜单可能跟着系统走深色主题，
画一块白底会在暗色菜单里变成一个刺眼的方块。同理，描边与文字取
``self.palette()`` 里的颜色，不写死 —— 写死的话在深色主题上就是"灰字灰底"。
"""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from . import uitheme
from .cards import EQUIP_SLOTS


class BadgeBar(QWidget):
    """5 个槽位的小徽章 + 右侧当前加成。只读，不接受鼠标。"""

    SLOT = 26            #: 单个徽章边长
    GAP = 6              #: 徽章间距
    PAD = 5              #: 四周留白
    TEXT_W = 84          #: 右侧文字区宽度

    def __init__(self, album, parent=None):
        super().__init__(parent)
        self.album = album
        self._icons: dict[str, QPixmap] = {}

        self.setFixedSize(self.PAD * 2 + EQUIP_SLOTS * self.SLOT
                          + (EQUIP_SLOTS - 1) * self.GAP + 10 + self.TEXT_W,
                          self.SLOT + self.PAD * 2)
        # 菜单里的装饰件：鼠标事件穿过去，别把它当成一个可以点的条目
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    # ------------------------------------------------------------ 绘制

    def _avatar(self, cid: str) -> QPixmap | None:
        pm = self._icons.get(cid)
        if pm is None:
            pm = QPixmap(str(self.album.pool.thumb_path(cid)))
            self._icons[cid] = pm
        if pm.isNull():
            return None
        return pm.scaled(self.SLOT - 6, self.SLOT - 6,
                         Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        pal = self.palette()
        ink = pal.color(QPalette.ColorRole.WindowText)
        faint = QColor(ink)
        faint.setAlpha(70)

        equipped = self.album.equipped()
        unlocked = self.album.slots()

        for i in range(EQUIP_SLOTS):
            rect = QRect(self.PAD + i * (self.SLOT + self.GAP), self.PAD,
                         self.SLOT, self.SLOT)
            if i < len(equipped):
                cid = equipped[i]
                card = self.album.pool.get(cid)
                colour = QColor(uitheme.TIER_COLOR.get(card.tier if card else "",
                                                       uitheme.SILHOUETTE))
                pm = self._avatar(cid)
                if pm is not None:
                    painter.drawPixmap(
                        rect.center().x() - pm.width() // 2,
                        rect.center().y() - pm.height() // 2, pm)
                pen = QPen(colour)
                pen.setWidth(2)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                painter.setPen(pen)
                painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 7, 7)
            elif i < unlocked:
                # 解锁了但空着：虚线框，提示"这里可以装"
                pen = QPen(faint)
                pen.setWidth(1)
                pen.setStyle(Qt.PenStyle.DashLine)
                painter.setPen(pen)
                painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 7, 7)
            else:
                # 还没解锁：更淡的实线框
                pen = QPen(QColor(ink.red(), ink.green(), ink.blue(), 38))
                pen.setWidth(1)
                painter.setPen(pen)
                painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 7, 7)

        text_x = self.PAD + EQUIP_SLOTS * self.SLOT + (EQUIP_SLOTS - 1) * self.GAP + 10
        painter.setPen(ink)
        font = self.font()
        font.setPointSizeF(max(7.5, font.pointSizeF() - 1.0))
        painter.setFont(font)
        painter.drawText(QRect(text_x, 0, self.TEXT_W, self.height()),
                         int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                         self.album.bonus_text())
