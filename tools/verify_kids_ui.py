"""幼儿模式的无头验收：遮罩画出来什么样、密码键盘能不能退出。

跑法：

    python tools/verify_kids_ui.py [输出目录]

**不会真的铺满你的屏幕**：窗口设了 ``WA_DontShowOnScreen``（Qt 会给它正常渲染
但不映射到屏幕）。**别用 ``QT_QPA_PLATFORM=offscreen``** —— 那个平台看不到系统
字体（实测 0 个 family），截出来满屏方块字（同 ``verify_album_ui.py``）。

**也不会碰玩家的存档**：本脚本只造 ``KidsOverlay``（不认识 ``Config``，一个字节
都不落盘），但照样先把可写数据目录换到临时目录 —— 这样以后谁往这里加一句
造 ``Config`` 的代码都不会出事。见 ``tools/_isolate.py``。

截图是**拼出来的**：先画一张假的"桌面"（几个图标方块 + 一个窗口 + 一条任务栏），
再把遮罩抓图叠上去，最后把"桌宠"画在最上面 —— 正好复现真实的窗口层次
（遮罩盖住桌面，桌宠盖住遮罩），一眼就能看出这个模式在干什么。
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _isolate import assert_isolated, isolate_storage              # noqa: E402

#: 存档隔离 —— **必须排在所有 pet.* 导入和一切 Config()/PetWindow() 之前**。
STORAGE = isolate_storage("kids_ui")
assert_isolated()

from PySide6.QtCore import QRect, Qt                              # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen   # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton           # noqa: E402

from pet import kids as kidslib                                   # noqa: E402
from pet.uitheme import ui_font                                   # noqa: E402

#: 截图用的假屏幕尺寸。**不取真实屏幕** —— 验收图要可复现，
#: 换台机器换分辨率就变了（同 ``verify_album_ui.py`` 的做法）。
CANVAS_W, CANVAS_H = 1280, 800

PASSCODE = "2468"

FAILS: list[str] = []
PASSES = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASSES
    if ok:
        PASSES += 1
        print(f"  ok   {name}" + (f"   {detail}" if detail else ""))
    else:
        FAILS.append(name)
        print(f"  FAIL {name}   {detail}")


def paint_fake_desktop(scene: QImage, font: QFont) -> None:
    """画一张"用户原来的桌面"，给遮罩当背景。纯装饰，只为看图时看得懂。"""
    p = QPainter(scene)
    p.fillRect(scene.rect(), QColor("#dfe6f0"))
    p.setPen(Qt.PenStyle.NoPen)
    for index, (label, x, y) in enumerate(
            [("此电脑", 60, 60), ("回收站", 60, 160), ("作业", 60, 260),
             ("游戏", 60, 360)]):
        p.setBrush(QColor("#8fa8c8" if index % 2 == 0 else "#a8bcd8"))
        p.drawRoundedRect(QRect(x, y, 56, 56), 10, 10)
        p.setPen(QColor("#5b6b82"))
        p.setFont(font)
        p.drawText(QRect(x - 24, y + 60, 104, 20),
                   Qt.AlignmentFlag.AlignHCenter, label)
        p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#ffffff"))
    p.setPen(QPen(QColor("#c3cedd"), 1))
    p.drawRoundedRect(QRect(420, 180, 560, 360), 10, 10)
    p.setPen(QColor("#8a97a8"))
    p.setFont(font)
    p.drawText(QRect(444, 202, 520, 24), Qt.AlignmentFlag.AlignLeft,
               "这是用户正在写的东西.doc —— 小朋友不该碰得到")
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#1f2733"))
    p.drawRect(QRect(0, CANVAS_H - 48, CANVAS_W, 48))
    p.setPen(QColor("#c9d4e2"))
    p.drawText(QRect(16, CANVAS_H - 48, 460, 48),
               Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
               "任务栏 / 开始菜单 —— 也该点不到")
    p.end()


def paint_pet_above(scene: QImage, hero: bool) -> None:
    """把"桌宠"画在遮罩**之上**。

    真实情况里它是独立窗口、被抬到了玻璃上面，所以这个画法是照实来的。
    ``hero`` 为真时多说一句"点得到"（第一张图用），否则只画个狗影。
    """
    p = QPainter(scene)
    box = QRect(CANVAS_W // 2 - 90, CANVAS_H // 2 + 40, 180, 120)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(247, 250, 255))
    p.drawRoundedRect(box, 18, 18)
    p.setPen(QPen(QColor("#c8d0dc"), 2))
    p.drawRoundedRect(box, 18, 18)
    p.setPen(QColor("#4a5568"))
    p.setFont(ui_font(15, True))
    p.drawText(box, Qt.AlignmentFlag.AlignCenter, "桌宠")
    if hero:
        p.setPen(QColor("#2f6f4f"))
        p.setFont(ui_font(11))
        p.drawText(QRect(box.x() - 160, box.bottom() + 8, box.width() + 320, 24),
                   Qt.AlignmentFlag.AlignHCenter, "↑ 只有这一个点得到，别的都点不动")
    p.end()


def compose(overlay, font: QFont, *, with_pet: bool, hero: bool = False) -> QImage:
    """假桌面 + 遮罩抓图（+ 桌宠）= 一张能看懂窗口层次的图。

    ``with_pet=False`` 用于"小键盘弹出来"那张 —— 桌宠在屏幕正中偏下，
    正好压在键盘上，两张图叠一起就都看不清了。
    """
    scene = QImage(CANVAS_W, CANVAS_H, QImage.Format.Format_ARGB32_Premultiplied)
    paint_fake_desktop(scene, font)
    p = QPainter(scene)
    # grab() 给的是 QPixmap，drawImage 只收 QImage，得转一道
    p.drawImage(0, 0, overlay.grab().toImage())    # 遮罩叠在假桌面上
    p.end()
    if with_pet:
        paint_pet_above(scene, hero)
    return scene


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)

    app = QApplication(sys.argv)
    font = ui_font(11)

    print("[1] 遮罩窗口")
    overlay = kidslib.KidsOverlay(PASSCODE)
    overlay.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    overlay.setGeometry(0, 0, CANVAS_W, CANVAS_H)
    overlay.show()
    check("遮罩盖住了给定矩形",
          overlay.width() == CANVAS_W and overlay.height() == CANVAS_H,
          f"{overlay.width()}×{overlay.height()}")
    check("暗底的 alpha 大于 0（全透明的地方鼠标会穿过去，等于没锁）",
          overlay.BACKDROP.alpha() > 0, f"alpha={overlay.BACKDROP.alpha()}")
    check("是 Tool 窗口（不进任务栏、不进 Alt+Tab）",
          bool(overlay.windowFlags() & Qt.WindowType.Tool))
    check("不是「鼠标穿透」窗口（穿过去就等于没遮罩）",
          not overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
    cls = type(overlay)
    check("右键 / 滚轮 / 双击都自己接住了（不让它们冒泡回默认处理）",
          all(name in cls.__dict__ for name in
              ("contextMenuEvent", "wheelEvent", "mouseDoubleClickEvent",
               "mousePressEvent", "mouseReleaseEvent")))

    zone = overlay._zone_rect()
    check("家长热区贴着右上角（在右上那一块里）",
          zone.left() > CANVAS_W * 0.8 and zone.top() < 40, str(zone))
    check("桌面中间不是热区（点它什么也不发生）",
          not zone.contains(CANVAS_W // 2, CANVAS_H // 2))

    print("\n[2] 出图：只有遮罩的样子")
    path_a = out_dir / "幼儿模式_遮罩.png"
    check("遮罩图存下来了",
          compose(overlay, font, with_pet=True, hero=True).save(str(path_a)),
          str(path_a))

    print("\n[3] 密码键盘")
    check("一开始不显示键盘", overlay._pad is None)
    overlay._show_pad()
    check("调用后弹出来了", overlay._pad is not None and overlay._pad.isVisible())
    pad = overlay._pad
    assert pad is not None
    buttons = pad.findChildren(QPushButton)
    check("一共 12 个键（1-9 + 清除 + 0 + 退格）", len(buttons) == 12,
          str(len(buttons)))
    check("键盘在遮罩范围内", overlay.rect().contains(pad.geometry()),
          str(pad.geometry()))
    check("键盘水平居中（差 2px 以内）",
          abs((pad.x() + pad.width() // 2) - CANVAS_W // 2) <= 2,
          f"中心 {pad.x() + pad.width() // 2} vs {CANVAS_W // 2}")
    check("密码键都不抢焦点（否则实体键盘敲的数字全喂给按钮了）",
          all(b.focusPolicy() == Qt.FocusPolicy.NoFocus for b in buttons))

    print("\n[4] 输密码：错的进不去，对的才放行")
    fired: list[int] = []
    overlay.unlocked.connect(lambda: fired.append(1))
    for digit in "1111":
        overlay._push(digit)
    check("错密码不解锁", fired == [])
    check("错密码自动清空（不用小朋友自己退格）", overlay._entry.typed == "")
    check("圆点空回来", overlay._entry.dots() == "○ ○ ○ ○", overlay._entry.dots())
    for digit in PASSCODE[:-1]:
        overlay._push(digit)
    check("输到第 3 位还不解锁、圆点跟着走",
          fired == [] and overlay._entry.dots() == "● ● ● ○",
          overlay._entry.dots())
    overlay._push(PASSCODE[-1])
    check("第 4 位对上就解锁", fired == [1])

    print("\n[5] 出图：密码键盘的样子")
    # 重新弹一次键盘：清掉上一段测试留下的"密码不对"提示与满格圆点，
    # 再敲前两位 —— 图上就是"输到一半"的自然状态。
    overlay._show_pad()
    overlay._push(PASSCODE[0])
    overlay._push(PASSCODE[1])
    path_b = out_dir / "幼儿模式_密码键盘.png"
    check("带键盘的图存下来了",
          compose(overlay, font, with_pet=False).save(str(path_b)),
          str(path_b))

    overlay.close()

    print("\n" + "=" * 60)
    if FAILS:
        print(f"失败 {len(FAILS)} 项 / 通过 {PASSES} 项：")
        for name in FAILS:
            print(f"  - {name}")
        return 1
    print(f"全部通过（{PASSES} 项）")
    print(f"截图输出到 {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
