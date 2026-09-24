"""朝向验收图：证明"往哪边走，就朝哪边"。

    python tools/verify_facing.py

产出一张 ``reports/facing_fix.png``，**按套逐套**验收（一个动作可能有好几套
素材，各套原图方向不一定一致）：

* 每套第一行 —— 该套素材原图 / 水平镜像。哪张是"朝左"用眼睛看，不靠代码猜。
* 每套第二行 —— **真正实例化 PetWindow 后 render() 出来的**向右走、向左走画面。
  不是复刻绘制逻辑，走的就是 paintEvent 那条路径，所以能当证据。

脚本自己还会比一遍像素：向右走那格应该最接近"素材镜像"，向左走那格应该
最接近"素材原图"。任何一套对不上就直接报错退出——省得又要靠人眼盯着看。
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFont                       # noqa: E402
from PySide6.QtCore import Qt                                     # noqa: E402
from PySide6.QtGui import QImage                                  # noqa: E402
from PySide6.QtWidgets import QApplication                        # noqa: E402

from pet import facing as facinglib                               # noqa: E402
from pet.assets import AssetBank, set_files                       # noqa: E402
from pet.behavior import State                                    # noqa: E402
from pet.config import Config
from pet.paths import pet_asset_dir                                     # noqa: E402
from pet.window import PetWindow                                  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="pet_facing_"))     # 两帧渲染的落脚处，收尾会删
OUT = ROOT / "reports" / "facing_fix.png"
ZOOM = 2
PAD = 22
GAP = 22
LABEL_H = 40
TITLE_H = 72
HEAD_H = 30

BG = (245, 246, 248, 255)
INK = (31, 36, 48, 255)
MUTED = (108, 117, 133, 255)
OK = (32, 122, 82, 255)
BAD = (186, 47, 47, 255)


def _font(size: int):
    for name in ("msyh.ttc", "msyhbd.ttc", "simhei.ttf", "simsun.ttc"):
        p = Path("C:/Windows/Fonts") / name
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size)
            except OSError:
                continue
    return ImageFont.load_default()


def render_window(bank: AssetBank, facing: int, set_name: str = "") -> Image.Image:
    """按给定行走方向（以及指定的一套素材）渲染一次真实窗口，返回 RGBA 图。

    注意：**绝不能** ``win.close()`` —— closeEvent 会把 cfg 存回 config.json，
    而这个脚本里的 Config 是临时对象，一存就把用户的位置/分数覆盖成默认值。
    不跑事件循环 + 不 close，定时器也不会自己跳出来写盘。
    """
    win = PetWindow(Config(), bank)
    win.brain.state = State.WALK          # 摆成走路姿态，才看得出朝向
    win.brain.facing = facing
    # 把"这一趟走哪一套"钉死。不钉的话走的是 _track_state 的随机挑套，
    # 拿 A 套的画面去和 B 套的图比像素，结论必然是错的。
    win._sprite_set["walk"] = set_name
    img = QImage(win.size(), QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    win.render(img)
    TMP.mkdir(parents=True, exist_ok=True)
    tag = set_name or "default"
    path = TMP / f"facing_{tag}_{'right' if facing > 0 else 'left'}.png"
    img.save(str(path))
    win.hide()
    return Image.open(path).convert("RGBA")


def mean_diff(a: Image.Image, b: Image.Image) -> float:
    """两张同尺寸图的平均像素差（含 alpha），用来判断"更接近哪一张"。"""
    if a.size != b.size:
        b = b.resize(a.size, Image.Resampling.NEAREST)
    # PIL 的 .load() 运行时是像素访问器，类型桩把它标得含糊，取值/解包会被误报
    pa: Any = a.load()
    pb: Any = b.load()
    total = 0
    for y in range(a.height):
        for x in range(a.width):
            ra, ga, ba, aa = pa[x, y]
            rb, gb, bb, ab = pb[x, y]
            total += abs(ra - rb) + abs(ga - gb) + abs(ba - bb) + abs(aa - ab)
    return total / (a.width * a.height * 4)


def _rel(p: Path) -> str:
    try:
        return str(Path(p).relative_to(ROOT))
    except ValueError:
        return str(p)


def head_side(pick: str, base: int) -> int:
    """"显示的是原图/镜像" -> 狗头实际朝哪边（-1 左 / 1 右）。"""
    return base * (-1 if pick == "镜像" else 1)


def cell(img: Image.Image, label: str, note: str = "", note_color=OK):
    """一格 = 放大后的图 + 两行小字。"""
    big = img.resize((img.width * ZOOM, img.height * ZOOM), Image.Resampling.NEAREST)
    w = max(big.width, 200)
    box = Image.new("RGBA", (w, big.height + LABEL_H), BG)
    box.alpha_composite(big, ((w - big.width) // 2, 0))
    d = ImageDraw.Draw(box)
    f = _font(15)
    d.text((w // 2, big.height + 4), label, fill=INK, font=f, anchor="ma")
    if note:
        d.text((w // 2, big.height + 22), note, fill=note_color, font=_font(13), anchor="ma")
    return box


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)

    # 存档守卫：这个脚本会 new 真窗口，万一哪条路径把 cfg 存了盘，
    # 用户的位置/分数就被默认值盖掉了。跑完对一遍，变了就还原回去。
    cfg_file = ROOT / "config.json"
    backup = cfg_file.read_bytes() if cfg_file.exists() else None

    pet_dir = pet_asset_dir()
    base = facinglib.current()
    sets = facinglib.read_sets(pet_dir)

    bank = AssetBank(pet_dir).load()
    names = bank.set_names("walk")
    if not names:
        print("[验收] 没找到 walk 素材，先入库走路素材")
        return 1

    print(f"[验收] 素材目录 : {_rel(pet_dir)}")
    print(f"[验收] 默认朝向 : 朝{'左' if base < 0 else '右'}"
          f"  ({facinglib.meta_path(pet_dir).name})")
    print(f"[验收] 按套覆盖 : {sets or '无'}")

    blocks: list[tuple[str, list[list[Image.Image]]]] = []
    pass_ok = True
    for name in names:
        label = name or "默认套"
        files = set_files(pet_dir, "walk", name)
        if not files:
            print(f"[验收] 套「{label}」没有帧文件，跳过")
            continue

        one = facinglib.base_for(base, sets, "walk", name)
        src = "按套覆盖" if facinglib.prefix("walk", name) in sets else "跟随目录默认"
        orig = Image.open(files[0]).convert("RGBA")
        mirror = orig.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        shot_right = render_window(bank, 1, name)      # 向右走，且钉死用这一套
        shot_left = render_window(bank, -1, name)

        d_r = {"原图": mean_diff(shot_right, orig), "镜像": mean_diff(shot_right, mirror)}
        d_l = {"原图": mean_diff(shot_left, orig), "镜像": mean_diff(shot_left, mirror)}
        # key 写成 lambda 而不是 ``d_r.get``：dict.get 有 (key, default) 那个重载，
        # 类型检查器分不清是想传 key，会直接报"没有匹配的重载"
        right_pick = min(d_r, key=lambda k: d_r[k])
        left_pick = min(d_l, key=lambda k: d_l[k])
        right_head = head_side(right_pick, one)
        left_head = head_side(left_pick, one)
        ok = right_head == 1 and left_head == -1
        pass_ok = pass_ok and ok

        print(f"[验收] 套「{label}」声明朝{'左' if one < 0 else '右'}（{src}）："
              f"向右走画面最接近{right_pick}（差 {d_r[right_pick]:.2f}）-> 头朝"
              f"{'右' if right_head > 0 else '左'}；向左走最接近{left_pick}"
              f"（差 {d_l[left_pick]:.2f}）-> 头朝{'右' if left_head > 0 else '左'}"
              f"  =>  {'正确' if ok else '反了'}")

        blocks.append((f"套「{label}」  声明 base={'left' if one < 0 else 'right'}"
                       f"（{src}）  ——  {'通过' if ok else '反了'}",
                       [
                           [cell(orig, f"{label} 素材原图",
                                 f"声明朝{'左' if one < 0 else '右'}：脸在"
                                 f"{'左' if one < 0 else '右'}边", MUTED),
                            cell(mirror, f"{label} 水平镜像",
                                 f"镜像后就是朝{'右' if one < 0 else '左'}", MUTED)],
                           [cell(shot_right, "向右走（facing=+1）",
                                 f"显示{right_pick} -> 狗头朝{'右' if right_head > 0 else '左'}"
                                 + ("（正确）" if right_head > 0 else "（反了）"),
                                 OK if right_head > 0 else BAD),
                            cell(shot_left, "向左走（facing=-1）",
                                 f"显示{left_pick} -> 狗头朝{'右' if left_head > 0 else '左'}"
                                 + ("（正确）" if left_head < 0 else "（反了）"),
                                 OK if left_head < 0 else BAD)],
                       ]))

    if not blocks:
        print("[验收] 没有任何一套可比对")
        return 1

    cw = blocks[0][1][0][0].width
    ch = blocks[0][1][0][0].height
    W = PAD * 2 + cw * 2 + GAP
    H = PAD * 2 + TITLE_H + len(blocks) * (HEAD_H + ch * 2 + GAP) + 46
    sheet = Image.new("RGBA", (W, H), BG)
    d = ImageDraw.Draw(sheet)
    d.text((PAD, PAD), "走路朝向验收：素材朝向 vs 实际画面（真窗口渲染，非示意图）",
           fill=INK, font=_font(18))
    d.text((PAD, PAD + 26),
           f"声明 base={'left' if base < 0 else 'right'}"
           f"（{_rel(pet_dir)}/facing.json）；按套覆盖 {sets or '无'}",
           fill=MUTED, font=_font(13))
    d.text((PAD, PAD + 44),
           "一个动作的每一套都要「走哪边就朝哪边」——对不上就报错退出",
           fill=MUTED, font=_font(13))

    y = PAD + TITLE_H
    for heading, grid in blocks:
        d.text((PAD, y), heading, fill=INK, font=_font(15))
        y += HEAD_H - 8
        for cells in grid:
            for c, box in enumerate(cells):
                sheet.alpha_composite(box.convert("RGBA"), (PAD + c * (cw + GAP), y))
            y += ch + GAP
        y += 4

    verdict = (f"验收通过：{len(blocks)} 套都「走哪边就朝哪边」" if pass_ok
               else "验收不通过：有套的朝向与行走方向相反")
    d.text((PAD, y + 4), verdict, fill=OK if pass_ok else BAD, font=_font(15))

    sheet.convert("RGB").save(OUT)
    print(f"[验收] 结果图 : {OUT.relative_to(ROOT)}  {len(blocks)} 套")
    print(f"[验收] 结论   : {verdict}")

    if backup is not None and cfg_file.read_bytes() != backup:
        cfg_file.write_bytes(backup)
        print("[验收] 注意：config.json 被改动过，已还原为运行前的版本")
    shutil.rmtree(TMP, ignore_errors=True)          # 中间产物，图已经拼好了
    return 0 if pass_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
