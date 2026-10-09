"""抽卡翻牌浮层的无头验收：翻得出来、档位分得开、跳过与收得掉。

跑法：

    python tools/verify_reveal_ui.py [输出目录]

**不会在桌面上弹窗**：卡册用 ``WA_DontShowOnScreen``（Qt 照常渲染，但不映射
到屏幕）。这一点和 ``verify_album_ui.py`` 是同一个理由 ——
``QT_QPA_PLATFORM=offscreen`` 那个平台看不到任何系统字体（实测 0 个 family），
截出来满屏方块字，没法判断"卡名写对没有、字有没有压到卡上"。

**不会碰玩家存档**：本脚本造真的 ``PetWindow``（每 3 秒自动落盘）并抽卡，
所以开头先把可写数据目录整个换到临时目录（见 ``tools/_isolate.py``）。

粒子位置是钉死种子的（``CardReveal.SEED``），所以同一份代码跑两次，
截出来的图**逐像素一致** —— 这才叫"可复现的验收证据"。
"""

from __future__ import annotations

import os
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _isolate import (assert_isolated, isolate_storage,          # noqa: E402
                      source_asset_dir)

#: 存档隔离 —— **必须排在所有 pet.* 导入和一切 Config()/PetWindow() 之前**。
STORAGE = isolate_storage("reveal_ui")
assert_isolated()

from PySide6.QtCore import Qt, QTimer                            # noqa: E402
from PySide6.QtWidgets import QApplication                       # noqa: E402

from pet.assets import AssetBank                                 # noqa: E402
from pet.config import Config                                    # noqa: E402
from pet.reveal import SPARK, CardReveal, ease_out_back          # noqa: E402
from pet.window import PetWindow                                 # noqa: E402

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


def seek(reveal: CardReveal, t: float) -> None:
    """把动画定格在 t 这一刻再截屏。

    直接写 ``_t`` 是为了让截图可复现：真跑计时器的话，抓拍到的进度取决于
    机器负载，"0.45 秒那一帧长什么样"就永远说不清了。
    （动画本身由冒烟测试里的 tick 断言盯着。）
    """
    reveal._t = t
    reveal._done = t >= 1.0
    reveal._timer.stop()
    reveal.repaint()


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else (ROOT / "reports")
    out_dir.mkdir(parents=True, exist_ok=True)

    app = QApplication.instance() or QApplication([])

    cfg = Config()
    cfg.coins = 5000
    # 素材目录要用 source_asset_dir：pet_asset_dir 由可写数据目录推导，
    # 已经被上面的隔离换到临时目录了，会退到**空的**内置素材目录。
    bank = AssetBank(source_asset_dir("pet")).load()
    pet = PetWindow(cfg, bank)
    pet.album.rng = random.Random(20261009)

    print("\n[1] 浮层是卡册的子控件，初始不显示")
    pet.open_album()
    panel = pet._album_panel
    assert panel is not None, "open_album 之后应该有面板"
    panel.hide()
    panel.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    panel.show()
    reveal = panel.reveal
    check("卡册带一个翻牌浮层", isinstance(reveal, CardReveal))
    check("浮层在卡册里、初始是隐藏的", reveal.parent() is panel and not reveal.isVisible())
    check("浮层没翻过卡的时候不画东西", reveal.card is None)

    print("\n[2] 抽一次：浮层自己起来")
    pull = pet.pull_card()
    check("金币够，抽得到", pull is not None)
    assert pull is not None
    panel._focus(pull.card.id)                     # _pull 里的翻页那一步
    reveal.show_card(pull.card, panel._label(pull.card),
                     panel._thumb(pull.card.id),
                     is_new=pull.is_new, dup_count=pull.dup_count)
    check("浮层显示出来了", reveal.isVisible())
    check("浮层铺满整册（盖住所有按钮，翻牌期间点不到「抽一次」）",
          reveal.size() == panel.size(), f"{reveal.width()}×{reveal.height()}")
    check("动画从 0 开始、还没结束", reveal.progress == 0.0 and not reveal.done)
    check("浮层拿到了这次抽到的卡",
          reveal.card is not None and reveal.card.id == pull.card.id,
          pull.card.id)

    print("\n[3] 动画真的在走，而且到点会自己停")
    for _ in range(3):
        reveal._tick()
    check("走三帧之后进度前进了", 0.0 < reveal.progress < 1.0,
          f"{reveal.progress:.2f}")
    for _ in range(80):
        reveal._tick()
    check("进度封顶在 1（不会越走越多）", reveal.progress == 1.0)
    check("到终态就停表（不会再空转）",
          reveal.done and not reveal._timer.isActive())

    print("\n[4] 点一下跳过 / 再点一下收起")
    reveal.show_card(pull.card, panel._label(pull.card),
                     panel._thumb(pull.card.id), is_new=True, dup_count=2)
    reveal._tick()
    reveal.advance()
    check("动画没放完时点一下 = 跳到终态，而不是直接关掉",
          reveal.progress == 1.0 and reveal.isVisible() and reveal.done)
    reveal.advance()
    check("已经停在终态时点一下 = 收起", not reveal.isVisible())

    print("\n[5] 档位分得开：粒子与光环数递增")
    tiers = ["普通", "稀有", "史诗", "传说"]
    counts = []
    for tier in tiers:
        card = pet.album.cards_of(tier)[0]
        reveal.show_card(card, panel._label(card), panel._thumb(card.id),
                         is_new=True)
        counts.append(reveal.sparks)
    check("粒子数按 普通<稀有<史诗<传说 递增",
          counts == sorted(counts) and len(set(counts)) == 4, f"{counts}")
    check("每一档都真的摆了粒子（不是空表）", all(c > 0 for c in counts))
    check("光环层数也按档位递增（特效强度写在一张表里）",
          [SPARK[t][1] for t in tiers] == sorted(SPARK[t][1] for t in tiers),
          f"{[SPARK[t][1] for t in tiers]}")
    reveal.dismiss()

    print("\n[6] 新收集与重复长得不一样")
    card = pet.album.cards_of("传说")[0]
    thumb = panel._thumb(card.id)
    reveal.show_card(card, panel._label(card), thumb, is_new=True)
    check("新收集时标 is_new", reveal.is_new and reveal.progress == 0.0)
    reveal.show_card(card, panel._label(card), thumb, is_new=False, dup_count=3)
    check("重复时带着已有的张数（文案里要说出来）",
          not reveal.is_new and reveal.dup_count == 3)
    reveal.dismiss()

    print("\n[7] 键盘也能跳过（Esc / 空格 / 回车）")
    from PySide6.QtGui import QKeyEvent
    for key in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Escape):
        reveal.show_card(card, panel._label(card), thumb, is_new=True)
        event = QKeyEvent(QKeyEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
        reveal.keyPressEvent(event)               # 第一下：跳过
        skipped = reveal.done and reveal.isVisible()
        reveal.keyPressEvent(event)               # 第二下：收起
        check(f"{key.name} 能跳过并收起",
              skipped and reveal.progress == 1.0 and not reveal.isVisible())

    print("\n[8] 回弹缓动：冲过头再收回来（这是「弹出来」而不是「变大」的来源）")
    check("起步慢、中途过冲、末了归位",
          ease_out_back(0.0) == 0.0 and ease_out_back(1.0) == 1.0
          and ease_out_back(0.6) > 1.0,
          f"0.6 → {ease_out_back(0.6):.3f}")

    print("\n[9] 出截图（钉死种子 + 定格进度 = 可复现）")
    for tier in tiers:
        card = pet.album.cards_of(tier)[0]
        reveal.show_card(card, panel._label(card), panel._thumb(card.id),
                         is_new=True)
        seek(reveal, 1.0)
        shot = panel.grab()
        check(f"{tier}翻牌能渲染成图", not shot.isNull(),
              f"{shot.width()}×{shot.height()}")
        shot.save(str(out_dir / f"抽卡翻牌_{tier}.png"))

    card = pet.album.cards_of("传说")[0]
    reveal.show_card(card, panel._label(card), panel._thumb(card.id), is_new=True)
    seek(reveal, 0.22)                       # 正在横向翻出来的那一瞬间
    panel.grab().save(str(out_dir / "抽卡翻牌_过程.png"))
    check("翻牌中途那一帧也画得出来", reveal.progress == 0.22)

    reveal.show_card(card, panel._label(card), panel._thumb(card.id),
                     is_new=False, dup_count=4)
    seek(reveal, 1.0)
    panel.grab().save(str(out_dir / "抽卡翻牌_重复.png"))
    check("重复的翻牌图也出得来", not panel.grab().isNull())

    # 真的走一遍信号/计时器的路：这里才用真计时器，确认 start 之后会自己动
    reveal.show_card(card, panel._label(card), panel._thumb(card.id), is_new=True)
    check("翻牌会自动开始计时（不用谁去推它）", reveal._timer.isActive())
    QTimer.singleShot(120, app.quit)
    app.exec()
    check("计时器自己把进度推上去了", reveal.progress > 0.0,
          f"{reveal.progress:.2f}")
    reveal.dismiss()

    print("\n[10] 卡册「仅看已有」开关")
    cfg.album_owned_only = False
    panel.refresh()
    all_n = len(panel._cards)
    panel._toggle_mode()
    owned_n = len(panel._cards)
    check("切到「仅看已有」后列表变短", owned_n < all_n, f"{all_n} → {owned_n}")
    check("剩下的全是已拥有的",
          len(panel._cards) == pet.album.owned_kinds(), f"{owned_n}")
    check("切换写进了存档", cfg.album_owned_only is True)
    check("按钮上写的是「点下去会变成什么」", panel.mode.text() == "看全部",
          panel.mode.text())
    panel._toggle_mode()
    check("再切回来是整本图鉴", len(panel._cards) == all_n and not cfg.album_owned_only)
    panel.refresh()
    panel.grab().save(str(out_dir / "卡册_仅看已有按钮.png"))

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
