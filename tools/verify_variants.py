"""多套素材随机播放的验收：连点若干次，把每次**真正画出来的那一帧**拼成一张图。

为什么要抓真实的一帧：套选没选对、素材到底画出来没有，只有 ``paintEvent``
跑过才知道 —— 逻辑断言（时长、套名）覆盖不到绘制，这正是以前漏掉
``GROUND_H`` 那次踩的坑。

产出 ``reports/variants.png``。
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw                                    # noqa: E402
from PySide6.QtWidgets import QApplication                          # noqa: E402

#: 要验收的动作：状态名 -> (中文名, 抓几次)
ACTIONS = {
    "poke": ("逗它玩（左键单击）", 9),
    "feed": ("喂一口", 6),
}

ROUNDS_PER_SHOT = 6         # 点完之后推进几帧，让动作离开起始姿势
CELL = 168
COLS = 3
PAD = 26                    # 每格底部留给标签的高度


def isolate_config() -> None:
    """把存档指到临时文件 —— 脚本里的 Config 绝不能覆盖用户的位置/次数/最高分。"""
    from pet import config as pcfg
    tmp = Path(tempfile.mkdtemp()) / "cfg.json"
    pcfg.config_path = lambda: tmp


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    isolate_config()

    from pet.assets import AssetBank
    from pet.config import Config
    from pet.paths import pet_asset_dir
    from pet.window import PetWindow

    bank = AssetBank(pet_asset_dir()).load()
    pet = PetWindow(Config(), bank)
    pet.show()

    shot_dir = Path(tempfile.mkdtemp())
    rows: list[tuple[str, list[tuple[str, Path]]]] = []
    summary: list[str] = []

    for state, (label, times) in ACTIONS.items():
        pet.rng.seed(1234)
        got: list[tuple[str, Path]] = []
        for i in range(times):
            pet._last_action.clear()
            getattr(pet, state)()               # poke() / feed()
            for _ in range(ROUNDS_PER_SHOT):
                pet._advance(1 / 30)
            name = pet._sprite_set.get(state) or "default"
            out = shot_dir / f"{state}_{i:02d}.png"
            pet.grab().save(str(out))
            got.append((name, out))
        used = sorted({n for n, _ in got})
        summary.append(f"{label}: {times} 次里用到的套 = {used}")
        rows.append((label, got))

    pet.hide()

    # ---- 拼图（每格下面写清这一帧用的是哪一套）
    cols = COLS
    total_rows = sum((len(got) + cols - 1) // cols for _, got in rows)
    width = cols * CELL
    height = total_rows * (CELL + PAD)
    sheet = Image.new("RGB", (width, height), (235, 236, 240))
    d = ImageDraw.Draw(sheet)

    y = 0
    for label, got in rows:
        for idx, (name, path) in enumerate(got):
            im = Image.open(path).convert("RGBA")
            x = (idx % cols) * CELL
            row = y + (idx // cols) * (CELL + PAD)
            sheet.paste(im, (x, row), im)
            d.rectangle([x, row, x + CELL - 1, row + CELL - 1], outline=(190, 192, 200))
            d.text((x + 6, row + CELL + 6), f"{label} #{idx + 1}  set={name}",
                   fill=(40, 40, 40))
        y += ((len(got) + cols - 1) // cols) * (CELL + PAD)

    out = ROOT / "reports" / "variants.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)

    print("[variants] 每个动作实际用到的素材套：")
    for line in summary:
        print("  " + line)
    print(f"[variants] 拼图 -> {out}  {sheet.size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
