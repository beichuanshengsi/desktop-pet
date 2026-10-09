"""卡册 UI 的无头验证：窗口能建、菜单能搭、徽章栏能画。

跑法：

    python tools/verify_album_ui.py [输出目录]

**不会真的在桌面上弹出东西**：所有窗口都设了 ``WA_DontShowOnScreen``
（Qt 会给它正常渲染，但不映射到屏幕）。这一点很关键 —— 用
``QT_QPA_PLATFORM=offscreen`` 也能跑，但那个平台**看不到任何系统字体**
（实测 0 个 family），截出来满屏方块字，没法拿来判断排版对不对。

**也不会碰玩家的存档**：本脚本会造真的 ``PetWindow``（它每 3 秒自动落盘），
所以开头先把可写数据目录整个换到临时目录（见 ``tools/_isolate.py``）。
v2.3.0 刚发布时这里漏了这一步，跑一次验证就往玩家卡册里塞了 40 张卡、
把装备栏填满、还把金币和首跑时间改成了测试数值 —— 别再犯。
"""

from __future__ import annotations

import os
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _isolate import (assert_isolated, isolate_storage,             # noqa: E402
                      source_asset_dir)

#: 存档隔离 —— **必须排在所有 pet.* 导入和一切 Config()/PetWindow() 之前**。
STORAGE = isolate_storage("album_ui")
assert_isolated()

from PySide6.QtCore import Qt                               # noqa: E402
from PySide6.QtGui import QPixmap                           # noqa: E402
from PySide6.QtWidgets import QApplication, QWidgetAction    # noqa: E402

from pet.assets import AssetBank                            # noqa: E402
from pet.badge_bar import BadgeBar                          # noqa: E402
from pet.config import STAMP_FMT, Config                    # noqa: E402
from pet.window import PetWindow                            # noqa: E402

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


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else (ROOT / "reports")
    out_dir.mkdir(parents=True, exist_ok=True)

    app = QApplication.instance() or QApplication([])

    cfg = Config()
    cfg.coins = 5000
    # 素材目录用 source_asset_dir 而不是 pet_asset_dir：后者由可写数据目录推导，
    # 已经被上面的隔离换到临时目录了，会退到**空的**内置目录 assets/pet/，
    # 于是一只狗都画不出来（本脚本只看卡册界面，所以不会报错，但没必要留个假窗口）。
    bank = AssetBank(source_asset_dir("pet")).load()
    pet = PetWindow(cfg, bank)
    # 抽卡换成固定种子：这个脚本先抽 40 次来验经济参数，**抽到什么直接决定
    # 截图内容** —— 不固定的话每次跑出来的卡册图都不一样（实测同一份代码连跑
    # 两次，`卡册_第1页.png` 就有 10% 的像素不同），既没法比对、也没法说"可复现"。
    # `Album` 本来就支持注入 rng（见 pet/cards.py），这里只是把种子钉住。
    pet.album.rng = random.Random(20261009)

    print("\n[1] 右键菜单里的徽章栏")
    menu = pet._build_menu()
    widgets = [a for a in menu.actions() if isinstance(a, QWidgetAction)]
    check("菜单顶部插入了徽章栏", len(widgets) == 1, f"{len(widgets)} 个 QWidgetAction")
    bar = widgets[0].defaultWidget() if widgets else None
    check("徽章栏是 BadgeBar", isinstance(bar, BadgeBar))
    assert isinstance(bar, BadgeBar), "徽章栏没建出来，后面的断言没有意义"
    bar.resize(bar.size())
    pix = bar.grab()
    check("徽章栏能渲染成图", not pix.isNull() and pix.width() > 40,
          f"{pix.width()}×{pix.height()}")
    pix.save(str(out_dir / "徽章栏_空.png"))

    labels = [a.text() for a in menu.actions()]
    check("菜单里有卡册入口",
          any("卡册" in t for t in labels), " / ".join(t for t in labels if "卡册" in t))

    print("\n[2] 抽卡（走 PetWindow，不直接碰 Album）")
    got = []
    for _ in range(40):
        pull = pet.pull_card()
        if pull is None:
            break
        got.append(pull)
    check("40 次都能抽到", len(got) == 40, f"{len(got)}")
    check("金币按 60/抽扣掉", cfg.coins == 5000 - 40 * 60, f"{cfg.coins}")
    check("卡册里有东西了", pet.album.owned_kinds() > 0,
          f"{pet.album.owned_kinds()} / {pet.album.total_kinds()}")

    print("\n[3] 卡册窗口")
    pet.open_album()
    panel = pet._album_panel
    # assert 而不是 if：类型检查器认它，后面几十处 panel.xxx 才不用逐个判空；
    # 真出了错这里就断，也不会拿着一堆 "None 没有这个属性" 的噪音往下跑。
    assert panel is not None, "open_album 之后应该有面板"
    # 建完就改成"渲染但不映射到屏幕"，免得验证脚本一闪而过地在桌面上弹窗
    panel.hide()
    panel.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    panel.show()
    check("窗口建起来了", True)
    total = len(panel._cards)
    page = panel.PAGE
    check(f"一页 {page} 张", len(panel._cells) == page)
    want_pages = -(-total // page)  # 向上取整
    check(f"总页数 = ceil({total} / {page}) == {want_pages}",
          panel._page_count() == want_pages, f"{panel._page_count()}")
    check("第一页显示的卡数正确", len(panel._page_cards()) == page)
    panel.resize(panel.size())
    shot = panel.grab()
    check("卡册能渲染成图", not shot.isNull(), f"{shot.width()}×{shot.height()}")
    shot.save(str(out_dir / "卡册_第1页.png"))

    print("\n[4] 翻页与选中")
    panel._turn(1)
    check("翻到第 2 页", panel._page == 1, f"{panel._page}")
    panel._turn(-1)
    panel._turn(-1)
    check("第一页不能再往前", panel._page == 0)
    panel._page = panel._page_count() - 1
    panel.refresh()
    last_n = total - page * (panel._page_count() - 1)
    check(f"最后一页是 {last_n} 张", len(panel._page_cards()) == last_n,
          f"{len(panel._page_cards())}")
    panel.grab().save(str(out_dir / "卡册_最后一页.png"))

    owned = [c for c in pet.album.all_cards() if pet.album.count(c.id) > 0]
    if owned:
        card = owned[0]
        panel._page = panel._index_of(card.id) // panel.PAGE
        panel._on_cell(panel._index_of(card.id) % panel.PAGE)
        check("选中一张已拥有的卡", panel._selected == card.id)
        panel.grab().save(str(out_dir / "卡册_选中态.png"))

    print("\n[4b] 「仅看已有」开关（v2.6.0）")
    panel.cfg.album_owned_only = False
    panel._page = 0
    panel.refresh()
    all_total = len(panel._cards)
    panel._toggle_mode()
    check("切到「仅看已有」", panel.cfg.album_owned_only is True)
    check("列表只剩已拥有的", len(panel._cards) == pet.album.owned_kinds(),
          f"{all_total} → {len(panel._cards)}")
    check("切换后页号归零（两个模式列表长度不同，保留页号会指到别的卡）",
          panel._page == 0)
    check("按钮写的是「看全部」（写的是点下去会变成什么，不是当前状态）",
          panel.mode.text() == "看全部", panel.mode.text())
    want_owned_pages = -(-len(panel._cards) // page)
    check("页数公式照旧", panel._page_count() == want_owned_pages,
          f"{panel._page_count()} 页")
    panel.grab().save(str(out_dir / "卡册_仅看已有.png"))
    panel._toggle_mode()
    check("切回整本图鉴", len(panel._cards) == all_total
          and not panel.cfg.album_owned_only)

    print("\n[5] 装备后的徽章栏")
    legendary = pet.album.cards_of("传说")
    for card in legendary[:3]:
        pet.album._grant(card.id)
    for card in legendary[:3]:
        pet.equip_card(card.id)
    pet.album._grant(legendary[0].id)          # 造一张重复的，好测分解
    pet.album._grant(legendary[0].id)
    check("装上了卡", len(cfg.equipped) > 0, f"{cfg.equipped}")
    check("加成算得对", pet.album.bonus() > 0, pet.album.bonus_text())

    menu2 = pet._build_menu()
    widgets2 = [a for a in menu2.actions() if isinstance(a, QWidgetAction)]
    bar2 = widgets2[0].defaultWidget()
    assert isinstance(bar2, BadgeBar)
    bar2.resize(bar2.size())
    bar2.grab().save(str(out_dir / "徽章栏_已装备.png"))
    check("带装备的徽章栏能渲染", not bar2.grab().isNull())

    # 新档只有 1 槽，装不出"5 格全满"的样子 —— 借用一下老档的首次运行时间
    cfg.launched_at = (datetime.now() - timedelta(days=120)).strftime(STAMP_FMT)
    check("老档解锁 5 槽", pet.album.slots() == 5, f"{pet.album.slots()}")
    for card in (pet.album.cards_of("史诗")[1], pet.album.cards_of("史诗")[2],
                 pet.album.cards_of("稀有")[0], pet.album.cards_of("普通")[0]):
        pet.album._grant(card.id)
        pet.equip_card(card.id)
    check("5 格装满", len(cfg.equipped) == 5, f"{cfg.equipped}")
    bar3 = [a for a in pet._build_menu().actions()
            if isinstance(a, QWidgetAction)][0].defaultWidget()
    assert isinstance(bar3, BadgeBar)
    bar3.resize(bar3.size())
    bar3.grab().save(str(out_dir / "徽章栏_满槽.png"))
    check("满槽能渲染", not bar3.grab().isNull(), pet.album.bonus_text())

    panel.refresh()
    panel.grab().save(str(out_dir / "卡册_装备后.png"))

    print("\n[6] 装备加成真的进了结算")
    from game.common import coins_with_bonus
    from game import coins_for
    base = coins_for(480)
    final, rate = coins_with_bonus(cfg, base)
    check("结算时按加成放大", final > base and rate > 0,
          f"{base} → {final}（+{rate:.0%}）")

    print("\n[7] 关窗口不炸")
    pet.close()
    check("关掉桌宠顺带关掉卡册", panel.isVisible() is False)

    print("\n" + "=" * 62)
    print(f"截图输出到 {out_dir}")
    if FAILS:
        print(f"失败 {len(FAILS)} 项 / 通过 {PASSES} 项：")
        for name in FAILS:
            print(f"  - {name}")
        return 1
    print(f"全部通过（{PASSES} 项）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
