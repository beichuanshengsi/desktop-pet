"""真实桌面验证：把桌宠真的显示 2 秒，抓一张屏幕截图，然后自动退出。

为什么要单独写这个：透明背景、置顶、不占任务栏这三条，是桌面宠物唯一
真正困难的地方，而它们**无法在离屏环境里验证**——离屏渲染出来的透明图
看起来永远是"对"的。只有在真实桌面上截屏，才能确认窗口真的没有黑边、
真的盖在别的窗口上面。

跑法：
    python tools/verify_desktop.py

会生成 ``verify_desktop.png``：桌宠所在区域的真实屏幕截图。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer, Qt                            # noqa: E402
from PySide6.QtGui import QGuiApplication                        # noqa: E402
from PySide6.QtWidgets import QApplication                       # noqa: E402

from pet.assets import AssetBank                                 # noqa: E402
from pet.config import Config
from pet.paths import pet_asset_dir                          # noqa: E402
from pet.window import PetWindow                                 # noqa: E402

#: 和其它验收脚本保持一致，产物落进 reports/（reports/README.md 里按这个目录列了清单）
OUT = ROOT / "reports" / "verify_desktop.png"


def main() -> int:
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # 存档守卫：下面用的 cfg 是临时对象，close() 会触发 closeEvent 把它存盘，
    # 于是用户的位置、投喂次数、最高分全被默认值盖掉。跑完对一遍，变了就还原。
    cfg_file = ROOT / "config.json"
    backup = cfg_file.read_bytes() if cfg_file.exists() else None

    # 贴图现在只来自素材目录，不再有"代码画的兜底风格"生成这一步。
    # 目录空着就直说，别让人对着一张透明截图排查。
    if not any(pet_asset_dir().glob("*.png")):
        print(f"[verify] 素材目录 {pet_asset_dir()} 是空的，先放贴图再跑这个脚本")
        return 1

    cfg = Config()
    cfg.pos_x = cfg.pos_y = -1          # 用默认位置，别污染用户存档
    cfg.topmost = True
    bank = AssetBank(pet_asset_dir()).load()

    pet = PetWindow(cfg, bank)
    pet.show()
    print(f"[verify] 窗口标志 0x{int(pet.windowFlags()):x}")
    print(f"[verify] 窗口尺寸 {pet.width()}x{pet.height()}")
    print(f"[verify] 位置 ({pet.x()}, {pet.y()})")

    result = {"shot": False}

    def capture() -> None:
        g = pet.frameGeometry()
        pad = 40
        x, y = max(0, g.x() - pad), max(0, g.y() - pad)
        w, h = g.width() + pad * 2, g.height() + pad * 2
        screen = QGuiApplication.screenAt(g.center()) or QGuiApplication.primaryScreen()
        pm = screen.grabWindow(0, x, y, w, h)
        ok = not pm.isNull() and pm.save(str(OUT))
        result["shot"] = bool(ok)
        print(f"[verify] 截屏 {'成功' if ok else '失败'} -> {OUT.name}"
              f"  {pm.width()}x{pm.height()}  设备像素比 {pm.devicePixelRatio()}")

    def finish() -> None:
        print(f"[verify] 透明属性 WA_TranslucentBackground = "
              f"{pet.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)}")
        print(f"[verify] 结果：{'通过' if result['shot'] else '未取到截图'}")
        if backup is not None and cfg_file.read_bytes() != backup:
            cfg_file.write_bytes(backup)
            print("[verify] 注意：config.json 被改动过，已还原为运行前的版本")
        pet.hide()                  # 不要 close()，closeEvent 会写存档
        app.quit()

    QTimer.singleShot(1200, capture)
    QTimer.singleShot(2200, finish)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
