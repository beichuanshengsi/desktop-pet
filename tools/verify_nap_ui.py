"""「去睡一会儿」的无头验收：菜单那一行长什么样、点下去贴图换没换。

跑法：

    python tools/verify_nap_ui.py [输出目录]

**不会真的在桌面上弹出东西**：窗口设了 ``WA_DontShowOnScreen``（Qt 会给它
正常渲染但不映射到屏幕），菜单也只 ``grab()`` 不 ``exec()``。
**别用 ``QT_QPA_PLATFORM=offscreen``** —— 那个平台看不到系统字体（实测 0 个
family），截出来满屏方块字（同 ``verify_album_ui.py``）。

**也不会碰玩家的存档**：本脚本会造真的 ``PetWindow``（它每 3 秒自动落盘），
所以开头先把可写数据目录整个换到临时目录。见 ``tools/_isolate.py``。
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _isolate import (assert_isolated, isolate_storage,              # noqa: E402
                      source_asset_dir)

#: 存档隔离 —— **必须排在所有 pet.* 导入和一切 Config()/PetWindow() 之前**。
STORAGE = isolate_storage("nap_ui")
assert_isolated()

from PySide6.QtCore import Qt                               # noqa: E402
from PySide6.QtGui import QImage                            # noqa: E402

from pet.assets import AssetBank                            # noqa: E402
from pet.behavior import State                              # noqa: E402
from pet.config import Config                               # noqa: E402
from pet.vitals import NAP_BOOST, RESTED_AT                 # noqa: E402
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


def pixels(pix) -> bytes:
    """把一张抓图压成字节串，用来判"这两张画的是不是同一个东西"。

    **先固定朝向再比**：``paintEvent`` 会按 ``brain.facing`` 做水平镜像，
    朝向不同的话同一个贴图抓出来也不一样 —— 那样这个断言就永远为真、
    什么都验不出来。所以调用方比之前会把 ``facing`` 拧到同一个值。
    """
    img = pix.toImage().convertToFormat(QImage.Format.Format_RGB32)
    return bytes(img.constBits())


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else (ROOT / "reports")
    out_dir.mkdir(parents=True, exist_ok=True)

    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    bank = AssetBank(source_asset_dir("pet")).load()
    if bank.count("sleep") == 0:
        print("[验收] 没读到 sleep 素材 —— 这个脚本要靠渲染睡姿来判断"
              "'贴图真的换了'，读到空目录的话会变成'空比空'然后假通过。"
              "先确认项目根的 custom_pet/ 里有 sleep_*.png。")
        return 1
    pet = PetWindow(Config(), bank)
    pet.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    pet.brain.auto_walk = False
    pet.brain.facing = 1

    print("\n[1] 右键菜单那一行")
    pet.vitals.energy = 40.0
    menu = pet._build_menu()
    labels = [a.text() for a in menu.actions()]
    nap_line = next((t for t in labels if t.startswith("去睡一会儿")), "")
    check("菜单里有「去睡一会儿」", bool(nap_line), " / ".join(labels))
    check("能睡时那一行写着'睡饱约 N 分钟'",
          "分钟" in nap_line and "不困" not in nap_line, nap_line)
    menu_pix = menu.grab()
    check("菜单能渲染出图", not menu_pix.isNull(), f"{menu_pix.width()}×{menu_pix.height()}")
    menu_pix.save(str(out_dir / "小睡_菜单.png"))

    print("\n[2] 精力充足时那一行灰掉并写明原因")
    pet.vitals.energy = 95.0
    menu2 = pet._build_menu()
    acts = {a.text(): a for a in menu2.actions()}
    grey = next((a for t, a in acts.items() if t.startswith("去睡一会儿")), None)
    check("精力充足时菜单仍有这一行", grey is not None, " / ".join(acts))
    check("但仍然灰掉、点不动", grey is not None and not grey.isEnabled(),
          grey.text() if grey else "(没有这一行)")
    check("并且说清是'不困'而不是别的原因",
          grey is not None and "不困" in grey.text(),
          grey.text() if grey else "")
    menu2.grab().save(str(out_dir / "小睡_不困.png"))

    print("\n[3] 点下去：真的睡下、贴图换成睡姿")
    pet.vitals.satiety = pet.vitals.mood = 50.0
    pet.vitals.energy = 40.0
    pet.brain._enter(State.IDLE)
    pet._sync_anim(True)
    idle_pix = pet.grab()

    plan = pet.nap_plan()
    check("nap_plan 就绪并给出时长", plan.ready and plan.minutes > 0,
          f"{plan.minutes:.1f} 分钟")
    pet._last_action.clear()
    pet.nap()
    check("nap() 之后进入 SLEEP", pet.brain.state is State.SLEEP, pet.brain.state.value)
    check("并且被标记为'用户安排的'（窗口据此加速）", pet.brain.napping)
    check("贴图前缀换成了 sleep", pet.brain.sprite == "sleep", pet.brain.sprite)

    pet.brain.facing = 1                    # 固定朝向，好和上面那张 idle 逐像素比
    pet._sync_anim(True)
    sleep_pix = pet.grab()
    # grab() 给的是**设备像素**：本机 125% 缩放，128 逻辑点 → 160 像素。
    # 直接拿 width() 和 pet.width() 比会永远不等，得先除掉 devicePixelRatio。
    ratio = sleep_pix.devicePixelRatio() or 1.0
    logical = sleep_pix.width() / ratio
    check("入睡那张能渲染、逻辑尺寸与窗口一致",
          not sleep_pix.isNull() and abs(logical - pet.width()) < 1e-6,
          f"{sleep_pix.width()}×{sleep_pix.height()} 像素 @{ratio:g}x = "
          f"{logical:.0f} 逻辑点（窗口 {pet.width()}）")
    sig_idle, sig_sleep = pixels(idle_pix), pixels(sleep_pix)
    check("睡姿和站姿是两张不同的图（真的换了贴图，不是只改了状态字段）",
          sig_idle != sig_sleep,
          f"各 {len(sig_idle)} 字节，{'相同' if sig_idle == sig_sleep else '不同'}")
    sleep_pix.save(str(out_dir / "小睡_入睡.png"))

    print("\n[4] 睡到该醒的时候会自己起来")
    # 按 5 秒一步推进，直到它醒（加速后应远早于自然睡的 9.5 分钟）
    steps = 0
    while pet.brain.state is State.SLEEP and steps < 600:
        pet._advance(5.0)
        steps += 1
    secs = steps * 5
    natural = (RESTED_AT - 40.0) / 6.0 * 60.0
    check("自己会醒", pet.brain.state is not State.SLEEP, pet.brain.state.value)
    check(f"起床用时远短于自然睡（{secs:.0f}s vs {natural:.0f}s，倍率 {NAP_BOOST}）",
          secs < natural,
          f"实际 {secs/60:.1f} 分钟 / 自然睡要 {natural/60:.1f} 分钟")
    check("醒来后'主动小睡'标记已清掉（否则下一觉会白捡加速）", not pet.brain.napping)

    pet._timer.stop()
    pet._save_timer.stop()
    pet.hide()                              # 不要 close()，closeEvent 会写存档

    print("\n" + "=" * 62)
    print(f"截图输出到 {out_dir}")
    print(f"隔离用的临时数据目录：{STORAGE}")
    if FAILS:
        print(f"失败 {len(FAILS)} 项 / 通过 {PASSES} 项：")
        for name in FAILS:
            print(f"  - {name}")
        return 1
    print(f"全部通过（{PASSES} 项）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
