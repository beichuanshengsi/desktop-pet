"""接狗狗新玩法的验收：骨头道具 + 落体横向漂移。

两件事都是"看不见就等于没做"的类型：

* 骨头是第三种落体，靠**代码画的占位形象**（还没有真素材）。不抓一帧出来看，
  谁也不知道它在浅色天空上认不认得出是根骨头。
* 漂移（"风"）改的是 ``Faller.body.vx``（以前恒为 0）。数值对不对要画成
  ``x(t)`` 才看得出：撞到左右边到底弹没弹回来、会不会贴着边走完剩下的路。

产出 ``reports/catch_items.png``：

* 上：真实游戏窗口的一帧（``grab()``），里面同时有小白狗、炸弹、骨头；
* 中：几根被风吹偏的落体，横向位置随时间的变化，虚线是左右墙；
* 下：骨头占位形象的几个相位（同一个函数、不同 ``t``）。

脚本不跑事件循环、结束用 ``hide()`` 而不是 ``close()``，并把存档指到临时文件。
"""

from __future__ import annotations

import random
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFont                        # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter                 # noqa: E402
from PySide6.QtWidgets import QApplication                         # noqa: E402

DT = 1 / 60.0
BG = (243, 244, 247)
PANEL_BG = (255, 255, 255)
INK = (32, 34, 40)
MUTED = (124, 128, 138)
GRID = (231, 234, 241)
WALL = (222, 120, 120)
LINE_COLORS = ((226, 96, 138), (74, 132, 226), (232, 145, 58),
               (108, 176, 132), (150, 118, 206), (196, 150, 60))


def _font(size: int):
    for name in ("msyh.ttc", "msyhbd.ttc", "simhei.ttf", "simsun.ttc"):
        p = Path("C:/Windows/Fonts") / name
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size)
            except OSError:
                continue
    return ImageFont.load_default()


def isolate_config() -> None:
    from pet import config as pcfg
    tmp = Path(tempfile.mkdtemp()) / "cfg.json"
    pcfg.config_path = lambda: tmp


def bone_strip(width: int, height: int) -> QImage:
    """用游戏自己的绘制函数画一排骨头（不同相位），证明占位形象长什么样。"""
    img = QImage(width, height, QImage.Format.Format_ARGB32)
    img.fill(QColor(233, 242, 252))          # 和游戏天空一个底色
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    from game.catcher import BONE_SIZE, _draw_bone_placeholder
    n = 4
    cell = width / n
    k = 1.6
    for i in range(n):
        size = BONE_SIZE * k
        x = i * cell + (cell - size) / 2.0
        _draw_bone_placeholder(p, x, (height - size) / 2.0, size, size, i * 0.21)
    p.end()
    return img


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    isolate_config()

    from pet.assets import AssetBank
    from pet.config import Config
    from pet.paths import pet_asset_dir
    from game.catcher import (BONE_SIZE, DRIFT_MAX, FALL_LIMIT, HUD_H, MAX_HP,
                              PUPPY_SIZE, RAMP_TIME, CatchGame)

    bank = AssetBank(pet_asset_dir()).load()
    cfg = Config()
    cg = CatchGame(bank, cfg)
    cg.rng = random.Random(20260923)
    cg.show()

    # ---- 把难度拉满：这时候才有风、才会掉骨头
    cg.survived = RAMP_TIME
    print(f"难度已拉满：骨头上线，风速上限 {cg.drift_speed():.0f} px/s "
          f"（前半程是 0，笔直落下来）")

    # ---- 上半张图：真实一帧，三种落体同时在场
    cg.fallers.clear()
    cg.hp = MAX_HP
    cg.catcher.teleport(80.0, float(cg.catcher.y))
    layout = [
        ("puppy", 60.0, 120.0), ("bomb", 250.0, 210.0),
        ("puppy", 430.0, 150.0), ("bone", 350.0, 300.0),
        ("bomb", 560.0, 240.0), ("puppy", 660.0, 330.0),
        ("bone", 170.0, 380.0),
    ]
    for kind, x, y in layout:
        f = cg.spawn(kind)
        f.body.x, f.body.y = x, y
        f.body.on_ground = False
    drifters = [f for f in cg.fallers if f.body.vx]
    print(f"真帧里三种落体各 {[k for k, _x, _y in layout].count('bone')} 根骨头、"
          f"{len(drifters)}/{len(cg.fallers)} 个带漂移")
    frame = Path(tempfile.mkdtemp()) / "catch_items.png"
    cg.grab().save(str(frame))

    # ---- 中半张图：被吹偏的落体 x(t)
    # 风速就用游戏里真实的上限 ``DRIFT_MAX`` 那一档，不放大参数。
    # 起点选在"撞得到墙，但撞完还够时间往回飘一段"的位置 —— 从贴墙起步
    # 的话反弹发生在第一帧，图上看不出来，等于没证明。
    spread = [(150.0, -130.0), (630.0, 130.0), (120.0, -99.0),
              (700.0, 109.0), (390.0, 120.0), (240.0, -130.0)]
    cg.fallers.clear()
    cg.catcher.teleport(-9999.0, 0.0)         # 接板挪走，纯看轨迹
    tracks: list[tuple[list[tuple[float, float]], int, float]] = []
    total_steps = int(2.0 / DT)
    for start_x, vx in spread:
        f = cg.spawn("puppy")
        f.body.y = float(HUD_H - PUPPY_SIZE)
        f.body.x = start_x
        f.body.vx = vx
        f.body.edge_bounce = True
        f.body.restitution = 1.0              # 和 _give_drift 里给的一样

        path: list[tuple[float, float]] = []
        edges = 0
        for step in range(total_steps):
            ev = f.body.update(DT, (0.0, float(HUD_H),
                                    float(cg.width()), float(FALL_LIMIT)),
                               use_gravity=False)
            if ev["edge"]:
                edges += 1
            path.append((step * DT, f.body.x))
            if f.body.y > 534.0:
                break
        tracks.append((path, edges, abs(vx)))

    bounced = sum(1 for _p, e, _s in tracks if e)
    print(f"6 根落体里 {bounced} 根撞到左右墙并弹回（其余还没飘到墙）")

    # ---- 拼图
    pad = 20
    shot_w = 700
    plot_w, plot_h = 700, 300
    strip_h = 130
    side_note_w = 250
    width = pad * 2 + max(shot_w, plot_w) + side_note_w
    sheet = Image.new("RGB", (width, 10), BG)          # 高度先占位，最后按需裁
    d = ImageDraw.Draw(sheet)

    # 先把真帧缩放到看得清的大小 —— 780x580 缩到 140px 高根本看不出是什么
    im = Image.open(frame).convert("RGB")
    k = min(0.66, shot_w / im.width)
    im = im.resize((int(im.width * k), int(im.height * k)), Image.Resampling.LANCZOS)
    shot_h = im.height

    plot_block = 24 + plot_h + 18
    strip_block = 24 + strip_h + pad
    height = (pad + 26 + 20 + shot_h + 18) + plot_block + strip_block
    sheet = Image.new("RGB", (width, height), BG)
    d = ImageDraw.Draw(sheet)

    d.text((pad, pad), "接狗狗新玩法验收：骨头道具 + 落体漂移（「风」）",
           fill=INK, font=_font(17))
    y = pad + 26

    sheet.paste(im, (pad, y + 20))
    d.rectangle((pad, y + 20, pad + im.width, y + 20 + im.height), outline=GRID)
    d.text((pad + im.width + 16, y + 20),
           "↑ 真实游戏窗口一帧\n\n"
           "  灰蓝圆球 = 炸弹（接到扣血）\n"
           "  白狗 = 接住加分\n"
           "  骨头 = 新的回血道具\n"
           "        （接到 +10 分，\n"
           "          有伤时回一滴血）\n\n"
           "  骨头还没有真素材，\n"
           "  你现在看到的是\n"
           "  代码画的占位形象。\n\n"
           "  往 assets/game/ 丢一张\n"
           "  bone_00.png 就会自动顶掉，\n"
           "  不用改任何代码。",
           fill=MUTED, font=_font(12))
    y += 20 + shot_h + 18

    # x(t)
    d.text((pad, y), "被风吹偏的落体：横向位置随时间（横轴 2 秒，纵轴 = 屏幕上的 x）",
           fill=INK, font=_font(14))
    y += 24
    x0, y0, x1, y1 = pad, y, pad + plot_w, y + plot_h
    d.rectangle((x0, y0, x1, y1), fill=PANEL_BG, outline=GRID)

    def mx(t: float) -> float:
        return x0 + t / 2.0 * (x1 - x0)

    def wx(x: float) -> float:
        return y0 + x / float(cg.width()) * (y1 - y0)

    for wall in (0.0, float(cg.width())):
        yy = wx(wall)
        for px in range(int(x0), int(x1), 10):
            d.line((px, yy, px + 5, yy), fill=WALL)
    d.text((x1 - 62, wx(0.0) + 2), "左右墙", fill=WALL, font=_font(10))

    for i, (path, edges, speed) in enumerate(tracks):
        color = LINE_COLORS[i % len(LINE_COLORS)]
        pts = [(mx(t), wx(x)) for t, x in path]
        if len(pts) >= 2:
            d.line(pts, fill=color, width=2, joint="curve")
        ex, ey = pts[-1]
        d.ellipse((ex - 3, ey - 3, ex + 3, ey + 3), fill=color)
        # 图例放到右边空白处，别压在曲线上
        ly = y0 + 8 + 17 * i
        d.rectangle((x1 + 22, ly + 3, x1 + 32, ly + 13), fill=color)
        travel = (max(x for _t, x in path) - min(x for _t, x in path))
        note = f"#{i}  风 {speed:.0f} px/s · 横向 {travel:.0f}px"
        if edges:
            note += f" · 反弹 {edges} 次"
        d.text((x1 + 40, ly), note, fill=INK, font=_font(11))

    for t in (0.0, 0.5, 1.0, 1.5, 2.0):
        d.line((mx(t), y1, mx(t), y1 + 4), fill=(198, 202, 212))
        d.text((mx(t) - 6, y1 + 5), f"{t:.1f}s", fill=MUTED, font=_font(10))
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        v = frac * float(cg.width())
        d.text((x0 + 4, max(y0 + 2, wx(v) - 14)), f"x={v:.0f}",
               fill=MUTED, font=_font(9))
    y += plot_h + 18

    # 骨头占位
    d.text((pad, y), "骨头的占位形象（4 个相位）",
           fill=INK, font=_font(14))
    y += 24
    bq = bone_strip(plot_w, strip_h)
    bpath = Path(tempfile.mkdtemp()) / "bone_strip.png"
    bq.save(str(bpath))
    sheet.paste(Image.open(bpath).convert("RGB"), (pad, y))
    d.rectangle((pad, y, pad + plot_w, y + strip_h), outline=GRID)

    out = ROOT / "reports" / "catch_items.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    print(f"\n产出 {out}  ({sheet.width}x{sheet.height})")

    cg._timer.stop()
    cg.hide()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
