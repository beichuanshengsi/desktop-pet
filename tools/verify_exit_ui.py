"""游戏中途退出的验收：确认框长什么样、结算浮层说了什么。

跑法：

    python tools/verify_exit_ui.py [输出目录]

产出 ``reports/中途退出_确认框.png``：一张对照表，每节一行真帧 + 右侧说明。

为什么这件事必须靠"看图"才能验
------------------------------
* 确认框是**盖在正在跑的游戏画面上**的。三个按钮挤不挤、会不会压住 HUD、
  半透明底够不够让人看清后面的局面 —— 断言一个字都答不上来。
* 「提前收工」这版结算文案比「时间到」多两个字，而浮层宽度是**自适应**的：
  只有画出来才知道会不会被挤断行、金币那句会不会溢出。
* 确认框的浮层和结算浮层**共用同一套 QSS**。两处样式漂了（比如按钮圆角
  或字号不一致），只会表现为"看着不像一家人"，没有任何断言能发现。

**不会真的弹到屏幕上**：窗口设了 ``WA_DontShowOnScreen``（Qt 照常渲染但不映射
到屏幕）。**也别改成 ``QT_QPA_PLATFORM=offscreen``** —— 那个平台在本机字体库
是空的，截出来满屏方块字（同 ``verify_album_ui.py`` / ``verify_kids_ui.py``）。

**不会碰玩家的存档**：先 ``isolate_storage()`` 把整个可写数据目录换到临时目录，
再取素材 —— 拿素材必须走 ``source_asset_dir()``（隔离一开，``pet_asset_dir()``
会退到空的内置目录，画出来是空白狗，而"空比空"照样相等 ⇒ 比对假通过）。
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _isolate import assert_isolated, isolate_storage, source_asset_dir  # noqa: E402

#: 存档隔离 —— **必须排在所有 pet.* 导入和一切 Config()/GameWindow() 之前**
STORAGE = isolate_storage("exit_ui")
assert_isolated()

from PySide6.QtCore import Qt                                     # noqa: E402
from PySide6.QtWidgets import QApplication                        # noqa: E402

from verify_v21_ui import Sheet                                   # noqa: E402

from pet.assets import AssetBank                                   # noqa: E402
from pet.config import Config                                      # noqa: E402
from pet.window import PetWindow                                   # noqa: E402
from game import GAMES                                             # noqa: E402
from game.common import HUD_H                                      # noqa: E402

FAILS: list[str] = []
PASSES = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASSES
    if ok:
        PASSES += 1
        print(f"  ok   {name}" + (f"   {detail}" if detail else ""))
    else:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f"   {detail}" if detail else ""))


def make(kind: str, cfg: Config, bank: AssetBank, score: int):
    """造一个离屏的游戏窗口并摆好分数（**不显示到屏幕上**）。"""
    from game import create_game

    w = create_game(kind, bank, cfg)
    w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    w.score = score
    w._timer.stop()                    # 抓图要的是静止的一帧
    w.show()                           # 只有 show() 过，子浮层才画得出来
    return w


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)

    app = QApplication.instance() or QApplication(sys.argv)

    bank = AssetBank(source_asset_dir("pet")).load()
    cfg = Config()
    check("素材用的是玩家那份只读素材（不是隔离后空的内置目录）",
          bank.count("idle") > 0, f"idle {bank.count('idle')} 帧")

    print("\n[1] 四个游戏都能弹出确认框")
    wins = {}
    for kind in ("bounce", "catch", "runner", "2048"):
        w = make(kind, cfg, bank, 480)
        w.ask_exit()
        wins[kind] = w
        check(f"{kind}：按 Esc 后确认框弹出来了（且没关窗）",
              w.confirm.isVisible() and not w.over,
              f"confirm={w.confirm.isVisible()} over={w.over}")
        check(f"{kind}：确认框压在 HUD 下面，挡不住顶部信息条",
              w.confirm.geometry().top() >= HUD_H,
              f"top={w.confirm.geometry().top()} HUD={HUD_H}")

    sheet = Sheet()
    sheet.title("v2.5.1 新增：游戏中途退出会先问一句（真帧，不是示意图）",
                "以前按 Esc / 关闭按钮 / R，没打完的分数和金币直接丢；现在三个出口。")

    # ------------------------------------------------ ① 确认框
    shot = wins["bounce"]
    from PySide6.QtWidgets import QPushButton

    buttons = shot.confirm.findChildren(QPushButton)
    labels = [b.text() for b in buttons]
    ys = [b.mapTo(shot.confirm, b.rect().topLeft()).y() for b in buttons]
    check("三个出口自上而下是「结算 / 暂停 / 取消」",
          labels == ["按当前分数结算", "暂停，回头再玩", "取消，继续玩"]
          and ys == sorted(ys), f"{labels} {ys}")
    print(f"弹跳得分一帧：分数 {shot.score}，确认框 {shot.confirm.width()}×"
          f"{shot.confirm.height()}")

    sheet.section(
        "① 弹跳得分 · 按 Esc：确认框（画面没停，分数还在背后）",
        shot.grab(),
        "背后是**正在跑的这一局**，不是静态背景图：\n"
        "  · 顶部 HUD 还写着本局得分 —— 分数一个字节没动；\n"
        "  · 三个出口自上而下 = 主按钮在前、安全出口垫底；\n"
        "  · 「取消，继续玩」按下去直接接着打。\n"
        "\n"
        "为什么不是系统 QMessageBox：\n"
        "  · 和结算浮层共用同一套 QSS，弹灰框太出戏；\n"
        "  · QMessageBox 是模态 exec()，冒烟测试没法断言\n"
        "    点击之后这一局还在不在。",
        scale=0.62)

    # ------------------------------------------------ ② 按当前分数结算
    settled = make("bounce", cfg, bank, 480)
    settled.cfg.best_score = 0
    settled.ask_exit()
    settled._settle_early()
    sub = settled.label_sub.text()
    check("结算后：标题写「提前收工」而不是「时间到」",
          "提前收工" in settled.label_title.text(), settled.label_title.text())
    check("结算后：副标题里有金币数和总数",
          "金币" in sub and "共" in sub, sub)
    check("结算后：确认框收起、结算浮层顶上（两个浮层不会同框）",
          not settled.confirm.isVisible() and settled.overlay.isVisible())
    print(f"结算一帧：{settled.label_title.text()} / {sub}")

    sheet.section(
        "② 「按当前分数结算」→ 走正常结算浮层（和打完一模一样）",
        settled.grab(),
        "选「结算」不是把窗口关掉，而是**把这一局收掉**：\n"
        "  · 文案换成「提前收工」，不会让人以为是自己输了；\n"
        "  · 记最高分、发金币、弹浮层三件事和打完走同一条路；\n"
        "  · 浮层上还能直接「再来一局」—— 退出的是这一局，不是这个窗口。\n"
        "\n"
        "金币按**当时的分数**算（480 // 10 = 48），\n"
        "2048 那款例外：按最大格子折算。",
        scale=0.62)

    # ------------------------------------------------ ③ 暂停之后的续玩入口
    pet = PetWindow(cfg, bank, GAMES)
    pet.set_suspended_game("runner")
    menu = pet._build_menu()
    titles = [a.text() for a in menu.actions()]
    check("暂停之后，右键菜单第一层挂着「继续上一局（跑一跑）」",
          any(t == "▶ 继续上一局（跑一跑）" for t in titles),
          str([t for t in titles if "继续" in t]))
    menu.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    menu.show()
    check("菜单能离屏渲染一帧（条目没被裁掉）",
          not menu.grab().isNull(), f"{menu.width()}×{menu.height()}")
    sheet.section(
        "③ 暂停之后的续玩入口（右键桌宠 → 第一层就有）",
        menu.grab(),
        "选「暂停，回头再玩」之后的三个后果：\n"
        "  · 桌宠恢复走动（不再是游戏期间那种冻结）；\n"
        "  · 菜单第一层多出这一条，点它就接着打 ——\n"
        "    场景、分数、方块位置全在，一帧都没丢；\n"
        "  · 托盘菜单里也挂了同一条（有人习惯去点托盘）。\n"
        "\n"
        "万一玩家暂停之后又去点了别的游戏：\n"
        "那一局会按当时分数结掉并弹托盘气泡，不会悄悄扔掉。",
        scale=0.62)
    menu.hide()
    pet.hide()

    for w in wins.values():
        w._timer.stop()
        w.hide()
    settled._timer.stop()
    settled.hide()

    out = out_dir / "中途退出_确认框.png"
    sheet.finish(out)
    print(f"\n截图输出到 {out}")

    print("\n" + "=" * 60)
    if FAILS:
        print(f"有 {len(FAILS)} 项没过：")
        for name in FAILS:
            print(f"  - {name}")
        return 1
    print(f"全部通过（{PASSES} 项）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
