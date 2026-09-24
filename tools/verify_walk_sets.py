"""「走路两套素材交替播」的验收。

和 ``verify_variants.py`` 的差别在哪
-----------------------------------
poke / feed 的多套是**点一次换一次**，连点几遍就能看到；走路不一样 ——
它是行为状态机自己溜达进去的，没有任何"点一下"的动作可以挂钩，
挑套只发生在**进入 walk 的那一帧**（见 ``PetWindow._track_state``）。

所以这里不能"连点"，只能**反复让它重新起步**：每次先回 idle、再进 walk，
然后取真正画出来的那一帧。六次里如果只出现一套，说明交替没生效。

产出 ``reports/walk_sets.png``：
* 第 1 行 —— 现在的 idle（坐板凳那套）连续几帧，顺带确认待机素材换对了
* 第 2 行 —— 连续 6 次起步各抓一帧，每格下面标出这次用的套名
* 第 3 行 —— 非默认套自己的连续帧，确认那套素材本身能正常播

不调 ``close()``：``closeEvent`` 会把脚本里的临时 ``Config`` 存盘，
覆盖用户的位置 / 投喂次数 / 最高分（这件事真发生过）。
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CELL = 150
GAP = 6
LABEL_H = 20
COLS = 7
INFO_H = 54
STARTS = 6              # 起步几次


def isolate_config() -> None:
    from pet import config as pcfg
    tmp = Path(tempfile.mkdtemp(prefix="pet_walk_")) / "cfg.json"
    pcfg.config_path = lambda: tmp


def load_cjk_font(size: int):
    from PIL import ImageFont
    for name in ("msyh.ttc", "simhei.ttf", "simsun.ttc"):
        try:
            return ImageFont.truetype(rf"C:\Windows\Fonts\{name}", size)
        except OSError:
            continue
    return ImageFont.load_default()


def main() -> int:
    from PySide6.QtWidgets import QApplication

    inst = QApplication.instance()
    app = inst if isinstance(inst, QApplication) else QApplication(sys.argv)
    isolate_config()

    from main import apply_ui_font
    apply_ui_font(app)

    from pet.assets import AssetBank
    from pet.behavior import State
    from pet.config import Config
    from pet.paths import pet_asset_dir
    from pet.window import PetWindow

    bank = AssetBank(pet_asset_dir()).load()
    pet = PetWindow(Config(), bank)
    pet.hide()                      # grab() 不需要 show()，也就不弹窗

    shot_dir = Path(tempfile.mkdtemp())
    idle_shots: list[Path] = []
    start_shots: list[tuple[str, Path]] = []
    other_shots: list[Path] = []

    # ---- 第 1 行：现在的 idle（坐板凳）
    pet.brain._enter(State.IDLE)
    pet._sync_anim(True)
    for i in range(COLS):
        for _ in range(3):
            pet._advance(1 / 30)
        out = shot_dir / f"idle_{i:02d}.png"
        pet.grab().save(str(out))
        idle_shots.append(out)

    # ---- 第 2 行：反复起步，每次抓一帧
    pet.rng.seed(20260922)
    for i in range(STARTS):
        pet.brain._enter(State.IDLE)
        pet._track_state()                  # 回待机，这一步不该挑套
        pet.brain._enter(State.WALK)
        pet._track_state()                  # 起步 —— 挑套就发生在这里
        pet._sync_anim(True)
        for _ in range(4):
            pet._advance(1 / 30)
        name = pet._sprite_set.get("walk") or "default"
        out = shot_dir / f"start_{i:02d}.png"
        pet.grab().save(str(out))
        start_shots.append((name, out))

    # ---- 第 3 行：非默认套自己的连续帧
    walk_sets = bank.set_names("walk")
    non_default = [n for n in walk_sets if n]
    if non_default:
        pet._sprite_set["walk"] = non_default[0]
        pet.brain._enter(State.WALK)
        pet._sync_anim(True)
        for i in range(COLS):
            for _ in range(2):
                pet._advance(1 / 30)
            out = shot_dir / f"other_{i:02d}.png"
            pet.grab().save(str(out))
            other_shots.append(out)
    pet.hide()

    from PIL import Image, ImageDraw

    font = load_cjk_font(13)
    rows = 3
    width = COLS * CELL + GAP * (COLS + 1)
    height = INFO_H + rows * (CELL + LABEL_H + GAP) + GAP
    sheet = Image.new("RGB", (width, height), (235, 236, 240))
    d = ImageDraw.Draw(sheet)

    order = sorted(walk_sets)
    used = sorted({n for n, _ in start_shots})
    lines = [
        f"idle 现在用的素材：{bank.count('idle')} 帧（坐板凳那套）",
        f"walk 可选的套：{order}　　六次起步实际用到的套：{used}",
        f"起步每次选到的套：{' '.join(n for n, _ in start_shots)}",
    ]
    for k, text in enumerate(lines):
        d.text((GAP + 2, 8 + k * 15), text, font=font, fill=(35, 35, 35))

    def draw_row(y: int, title: str, tiles: list[tuple[str, Path]]) -> int:
        d.text((GAP + 2, y), title, font=font, fill=(60, 60, 60))
        y += LABEL_H
        for i, (label, path) in enumerate(tiles[:COLS]):
            x = GAP + i * (CELL + GAP)
            im = Image.open(path).convert("RGBA")
            bg = Image.new("RGB", im.size, (250, 250, 250))
            bg.paste(im, (0, 0), im)
            sheet.paste(bg, (x, y))
            d.rectangle([x, y, x + CELL - 1, y + CELL - 1], outline=(185, 188, 196))
            d.text((x + 3, y + CELL + 3), label, font=font, fill=(45, 45, 45))
        return y + CELL + LABEL_H + GAP

    y = INFO_H
    y = draw_row(y, "① 现在待机时（坐板凳）", [("idle", p) for p in idle_shots])
    y = draw_row(y, "② 连续起步 6 次，每格是这次真正画出来的帧",
                 [(f"第{i + 1}次 set={n}", p) for i, (n, p) in enumerate(start_shots)])
    y = draw_row(y, f"③ 非默认套「{non_default[0] if non_default else '-'}」自己的连续帧",
                 [(f"set={non_default[0]}", p) for p in other_shots])

    out = ROOT / "reports" / "walk_sets.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)

    print(f"[walk_sets] walk 可选的套：{order}")
    print(f"[walk_sets] 六次起步选到：{' '.join(n or 'default' for n, _ in start_shots)}")
    print(f"[walk_sets] 拼图 -> {out}  {sheet.size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
