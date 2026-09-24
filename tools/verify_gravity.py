"""「重力下坠」开关的验收：把勾选 / 不勾 / 中途改 三种情况各抓一排真帧。

为什么要抓真帧：这个开关以前是**空的**（判定写成 ``cfg.gravity or not on_ground``），
逻辑上怎么看都"有判断"，只有把窗口摆到半空跑几帧、看它到底掉不掉下来，
才能证明它真的起作用了。

产出 ``reports/gravity_switch.png``：

* 每一排 = 一种设置，横轴是时间，纵轴是**真实屏幕坐标**下的高度；
* 每格贴的就是那一刻 ``grab()`` 抓到的真帧，不是示意图；
* 排尾写着这一排的结论。

脚本不跑事件循环、结束用 ``hide()`` 而不是 ``close()``，并把存档指到临时文件 ——
``closeEvent`` 会把临时 Config 存回用户的 ``config.json``，那会覆盖位置和统计。
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFont                        # noqa: E402
from PySide6.QtWidgets import QApplication                          # noqa: E402

#: 采样帧号（1/30 s 一步）。前四个密一点，好看清加速下坠的过程
SAMPLES = (0, 4, 9, 13, 18, 30)
DT = 1 / 30
#: 中途改设置的那一排，在第几个采样点把重力关掉
SWITCH_AT = 2

CELL_W = 132            # 每格宽度
THUMB_W = 92            # 缩略图宽度
TRACK_H = 300           # 纵向轨道高度（代表整个屏幕高度）
PANEL_PAD = 12
HEAD_H = 30             # 每排的标题高度
FOOT_H = 20             # 每格的坐标标注高度
BG = (243, 244, 247)
INK = (32, 34, 40)
MUTED = (108, 112, 122)
OK = (24, 128, 72)
BAD = (198, 52, 52)
GROUND = (150, 152, 160)
TRACE = (52, 108, 200)


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
    """存档指到临时文件 —— 绝不能让脚本里的临时 Config 覆盖用户的存档。"""
    from pet import config as pcfg
    tmp = Path(tempfile.mkdtemp()) / "cfg.json"
    pcfg.config_path = lambda: tmp


def run_case(pet, gravity: bool, switch_off_at: int | None,
             start_y: float, shot_dir: Path, tag: str):
    """跑一种设置，返回 [(帧号, 窗口顶部的屏幕 y, 抓到的图路径)]。

    ``switch_off_at`` 非空表示"跑到第几个采样点时把重力关掉"。
    """
    pet.cfg.gravity = gravity
    pet.body.teleport(pet.body.x, start_y)
    pet.body.on_ground = False
    pet.body.stop()

    shots: list[tuple[int, float, Path]] = []
    plan = {n: i for i, n in enumerate(SAMPLES)}          # 帧号 -> 第几个采样点
    for frame in range(SAMPLES[-1] + 1):
        if switch_off_at is not None and plan.get(frame) == switch_off_at:
            pet.set_gravity(False)
        if frame in plan:
            out = shot_dir / f"{tag}_{frame:02d}.png"
            pet.grab().save(str(out))
            shots.append((frame, pet.body.y, out))
        pet._advance(DT)
    return shots


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

    left, top, right, bottom = pet._bounds()
    size = pet.body.h
    # 起点摆到屏幕上方 12% 处 —— 有重力时这一趟掉得够长，看得出加速
    start_y = top + (bottom - top - size) * 0.12

    shot_dir = Path(tempfile.mkdtemp())
    cases = [
        ("勾选「重力下坠」（默认）", True, None, "on"),
        ("不勾「重力下坠」", False, None, "off"),
        (f"先勾选，跑到第 {SAMPLES[SWITCH_AT]} 帧改成不勾", True, SWITCH_AT, "switch"),
    ]
    results = [(label, run_case(pet, g, s, start_y, shot_dir, tag))
               for label, g, s, tag in cases]
    pet.hide()

    # ---- 拼图 ----------------------------------------------------------
    cols = len(SAMPLES)
    panel_h = HEAD_H + TRACK_H + FOOT_H + PANEL_PAD
    W = PANEL_PAD * 2 + cols * CELL_W
    H = PANEL_PAD + len(results) * panel_h + 46
    sheet = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(sheet)
    d.text((PANEL_PAD, 12),
           "「重力下坠」开关验收：同一只狗、同一个起点，只改这一个开关"
           "（每格是真帧，纵轴是真实屏幕高度）",
           fill=INK, font=_font(16))

    # 屏幕高度 -> 轨道高度 的映射：以"狗脚"为准，脚踩到地面时正好落在轨道底，
    # 轨道顶部留一个缩略图的高度，免得狗跑到屏幕最上面时被裁掉
    screen_h = max(1.0, bottom - top)
    lines: list[str] = []
    deltas = [shots[-1][1] - shots[0][1] for _, shots in results]
    kinds = ["on", "off", "switch"]

    def verdict_of(i: int, delta: float) -> tuple[str, tuple[int, int, int]]:
        """y 轴向下为正：delta > 0 才是真的往下走。"""
        if kinds[i] == "on":
            return ((f"结论：下坠了 {delta:.0f}px —— 重力在起作用", OK) if delta > 1.0
                    else ("结论：没掉下来 —— 开关没生效", BAD))
        if kinds[i] == "off":
            return (("结论：原地不动 —— 开关生效（不下坠）", OK) if abs(delta) < 1.0
                    else (f"结论：不该动却动了 {delta:+.0f}px", BAD))
        # switch：前半段在掉、关掉之后应该冻住
        if 1.0 < delta < abs(deltas[0]) * 0.8:
            return (f"结论：掉 {delta:.0f}px 后冻住 —— 对照上排 {deltas[0]:+.0f}px，"
                    "关掉就止住", OK)
        return (f"结论：异常（Δ={delta:+.0f}px）", BAD)

    y_cursor = 40
    for i, (label, shots) in enumerate(results):
        d.text((PANEL_PAD, y_cursor), label, fill=INK, font=_font(14))
        track_top = y_cursor + HEAD_H
        track_x0 = PANEL_PAD
        # 轨道底色 + 地面横线
        d.rectangle([track_x0, track_top, track_x0 + cols * CELL_W - 6, track_top + TRACK_H],
                    fill=(228, 230, 236))
        ground_y = track_top + TRACK_H
        d.line([track_x0, ground_y, track_x0 + cols * CELL_W - 6, ground_y],
               fill=GROUND, width=3)

        points: list[tuple[float, float]] = []
        for j, (frame, wy, path) in enumerate(shots):
            foot = wy + size
            ratio = min(1.0, max(0.0, (foot - top) / screen_h))
            feet_y = track_top + THUMB_W + ratio * (TRACK_H - THUMB_W)
            cx = track_x0 + j * CELL_W + CELL_W // 2

            im = Image.open(path).convert("RGBA")
            im = im.resize((THUMB_W, THUMB_W), Image.Resampling.LANCZOS)
            sheet.paste(im, (int(cx - THUMB_W / 2), int(feet_y - THUMB_W)), im)
            d.text((cx, feet_y + 2), f"t={frame * DT:.2f}s", fill=MUTED,
                   font=_font(10), anchor="ma")
            d.text((cx, feet_y + 14), f"y={wy:.0f}", fill=MUTED, font=_font(10), anchor="ma")
            points.append((cx, feet_y - THUMB_W / 2))

        for a, b in zip(points, points[1:]):
            d.line([a, b], fill=TRACE, width=2)

        first_y, last_y = shots[0][1], shots[-1][1]
        text, color = verdict_of(i, last_y - first_y)
        d.text((PANEL_PAD, track_top + TRACK_H + 2), text, fill=color, font=_font(12))
        lines.append(f"{label}：y {first_y:.0f} -> {last_y:.0f}"
                     f"（Δ={last_y - first_y:+.0f}px）")
        y_cursor += panel_h

    out = ROOT / "reports" / "gravity_switch.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)

    print("[gravity] 起点 y = %.0f，地面 y = %.0f，屏幕底 y = %.0f"
          % (start_y, bottom - size, bottom))
    for line in lines:
        print("  " + line)
    print(f"[gravity] 对比图 -> {out.relative_to(ROOT)}  {sheet.size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
