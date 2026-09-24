"""真实桌面上验证「逗它玩」和「喂一口」：把两个动作演一遍并连拍。

为什么不在离屏环境做：这两个动作的看点是"狗狗在真实桌面上、背景透明地演"，
离屏渲染出来的图看起来永远是对的。所以这里真的显示窗口、真的对屏幕连拍，
输出 ``reports/actions_desktop.png``（两行动图帧，每行一个动作）。

跑法：
    python tools/verify_actions.py
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
from pet.paths import pet_asset_dir                                     # noqa: E402
from pet.window import PetWindow                                 # noqa: E402

from PIL import Image, ImageDraw, ImageFont                      # noqa: E402

OUT = ROOT / "reports" / "actions_desktop.png"
TMP = ROOT / "reports" / "_tmp_actions"

POKE_PICKS = (0.10, 0.35, 0.70, 1.00, 1.30, 1.80)     # 秒，动作总长 1.92s
FEED_PICKS = (0.10, 0.40, 0.80, 1.20, 1.60, 1.95)     # 动作总长 2.00s


def _font(sz: int):
    try:
        return ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", sz)
    except OSError:
        return ImageFont.load_default()


def assemble(results: dict[str, list[Path]]) -> Path:
    tiles = []
    for kind, label in (("poke", "逗它玩（右键菜单 / 单击）"),
                        ("feed", "喂一口（右键菜单）")):
        row = [Image.open(p).convert("RGB") for p in results.get(kind, [])]
        if row:
            tiles.append((label, row))
    if not tiles:
        raise SystemExit("没抓到任何帧")
    cw = max(t.width for _, row in tiles for t in row)
    ch = max(t.height for _, row in tiles for t in row)
    cols = max(len(row) for _, row in tiles)
    pad, head = 14, 30
    W = pad + cols * (cw + 6)
    H = pad + sum(head + ch + 10 for _ in tiles)
    sheet = Image.new("RGB", (W, H), (246, 246, 250))
    d = ImageDraw.Draw(sheet)
    f = _font(16)
    y = 6
    for label, row in tiles:
        d.text((10, y), label, font=f, fill=(20, 20, 30))
        y += head
        for k, t in enumerate(row):
            sheet.paste(t, (pad + k * (cw + 6), y))
            d.rectangle([pad + k * (cw + 6), y,
                         pad + k * (cw + 6) + t.width - 1, y + t.height - 1],
                        outline=(170, 170, 180))
        y += ch + 10
    OUT.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(OUT)
    return OUT


def main() -> int:
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # 存档守卫：PetWindow.close() 会触发 closeEvent 写存档，
    # 那会把用户的位置/投喂次数/最高分盖成默认值。跑完对一遍，变了就还原。
    cfg_file = ROOT / "config.json"
    backup = cfg_file.read_bytes() if cfg_file.exists() else None

    cfg = Config()
    cfg.pos_x, cfg.pos_y = 120, 620      # 固定落点：避开用户自己那只宠物常待的位置
    cfg.auto_walk = False                # 别在连拍期间自己走开
    cfg.topmost = True
    bank = AssetBank(pet_asset_dir()).load()
    check = [(s, bank.count(s)) for s in ("poke", "feed")]
    print(f"[verify] 素材帧数 {check}")

    pet = PetWindow(cfg, bank)
    pet.show()

    TMP.mkdir(parents=True, exist_ok=True)
    results: dict[str, list[Path]] = {"poke": [], "feed": []}

    def snap(kind: str, idx: int) -> None:
        g = pet.frameGeometry()
        pad = 34
        x, y = max(0, g.x() - pad), max(0, g.y() - pad)
        screen = QGuiApplication.screenAt(g.center()) or QGuiApplication.primaryScreen()
        pm = screen.grabWindow(0, x, y, g.width() + pad * 2, g.height() + pad * 2)
        path = TMP / f"{kind}_{idx}.png"
        if not pm.isNull() and pm.save(str(path)):
            results[kind].append(path)
            print(f"[verify] {kind} 第 {idx + 1} 张  {pm.width()}x{pm.height()}")

    def start(kind: str) -> None:
        pet._last_action.clear()          # 绕开连点冷却，脚本要连拍
        if kind == "poke":
            pet.poke()
        else:
            pet.feed()
        picks = POKE_PICKS if kind == "poke" else FEED_PICKS
        base = 0 if kind == "poke" else 0
        for i, t in enumerate(picks):
            QTimer.singleShot(base + int(t * 1000), lambda k=kind, j=i: snap(k, j))

    def finish() -> None:
        out = assemble(results)
        print(f"[verify] 结果图 -> {out.relative_to(ROOT)}"
              f"  （戳 {len(results['poke'])} 张 / 喂 {len(results['feed'])} 张）")
        if backup is not None and cfg_file.read_bytes() != backup:
            cfg_file.write_bytes(backup)
            print("[verify] 注意：config.json 被改动过，已还原为运行前的版本")
        pet.hide()                        # 不要 close()，closeEvent 会写存档
        app.quit()

    QTimer.singleShot(1500, lambda: start("poke"))     # 先等它落到地面
    QTimer.singleShot(1500 + 2600, lambda: start("feed"))
    QTimer.singleShot(1500 + 2600 + 2600, finish)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
