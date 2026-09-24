"""「甩出去」的验收：四种手速各来一下，把真实轨迹画出来。

为什么要跑真帧：这件事的**代码一直都在**（``Motion.throw`` / ``edge_bounce`` /
``restitution`` 从写小游戏那天就有了），缺的只是"手速"这一个输入。
所以"看起来像能甩"没有意义 —— 必须真的按住、拖、松手，看它到底飞没飞出去、
飞出去之后撞不撞墙、什么时候落地。纯逻辑用例证明不了这一条，
因为它们不经过鼠标事件那一层。

产出 ``reports/fling_throw.png``：

* 上排 = 使劲甩那一把的真实帧，横轴是时间（``grab()`` 抓的真窗口，不是示意图）；
* 下面 = 四种手速各一条轨迹，坐标系就是**真实屏幕坐标**，底部横线是地面。

脚本不跑事件循环、结束用 ``hide()`` 而不是 ``close()``，并把存档指到临时文件 ——
``closeEvent`` 会把临时 Config 存回用户的 ``config.json``，那会覆盖位置和统计。
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFont                        # noqa: E402
from PySide6.QtCore import QEvent, QPointF, Qt                     # noqa: E402
from PySide6.QtGui import QMouseEvent                              # noqa: E402
from PySide6.QtWidgets import QApplication                         # noqa: E402

DT = 1 / 60.0              # 物理步长
FLIGHT_LIMIT = 6.0         # 最多跟踪这么多秒
MOVE_PAUSE = 0.02          # 合成事件之间的间隔，见 _drag_and_release

PANEL_W, PANEL_H = 604, 158
PAD = 14
HEAD_H = 34
NOTE_H = 18
ROW_H = PANEL_H + HEAD_H + NOTE_H
BG = (243, 244, 247)
PANEL_BG = (255, 255, 255)
INK = (32, 34, 40)
MUTED = (120, 124, 134)
GRID = (228, 231, 238)
GROUND = (150, 196, 158)
TRUE_C = (222, 74, 74)          # 真的甩出去了
FALSE_C = (128, 132, 142)       # 没甩出去


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


def _mouse_event(kind, gx: float, gy: float) -> QMouseEvent:
    held = kind is not QEvent.Type.MouseButtonRelease
    return QMouseEvent(kind, QPointF(6.0, 6.0), QPointF(gx, gy),
                       Qt.MouseButton.LeftButton,
                       Qt.MouseButton.LeftButton if held
                       else Qt.MouseButton.NoButton,
                       Qt.KeyboardModifier.NoModifier)


def _drag_and_release(pet, step_px: float, steps: int, sign: int = -1,
                      shot_dir: Path | None = None, tag: str = "") -> Path | None:
    """合成一次"按住 → 拖 → 松手"，返回"被拎在半空"那一帧的路径（抓了就返回）。

    ``sign`` 决定往哪边拖（-1 左 / 1 右）。

    **必须在两次事件之间真的睡一下**：采样器给"两点时间差太小"留了保护
    （``dt <= 1e-3`` 就返回 0），因为真实鼠标事件本来就隔十几毫秒，
    同一个微秒里喂完一串会算出无穷大速度。所以这里照着真实节奏来。
    """
    x0, y0 = float(pet.x()) + 60.0, float(pet.y()) + 60.0
    pet.mousePressEvent(_mouse_event(QEvent.Type.MouseButtonPress, x0, y0))
    for i in range(1, steps + 1):
        pet.mouseMoveEvent(_mouse_event(QEvent.Type.MouseMove,
                                        x0 + sign * i * step_px,
                                        y0 - i * step_px * 0.25))
        time.sleep(MOVE_PAUSE)
    gx = x0 + sign * steps * step_px
    gy = y0 - steps * step_px * 0.25
    pet.mouseMoveEvent(_mouse_event(QEvent.Type.MouseMove, gx, gy))

    drag_shot: Path | None = None
    if shot_dir is not None:
        drag_shot = shot_dir / f"{tag}_drag.png"     # 松手前一刻：还在 DRAG 状态
        pet.grab().save(str(drag_shot))

    pet.mouseReleaseEvent(_mouse_event(QEvent.Type.MouseButtonRelease, gx, gy))
    return drag_shot


def _place(pet, x: float, y: float) -> None:
    """把宠物挪到屏幕上的某个位置。

    **必须同时改 ``body`` 和窗口**：只 ``teleport(body)`` 的话窗口还留在原地，
    而松手那一步 ``_sync_from_window()`` 会拿窗口位置去覆盖 ``body`` ——
    摆好的起点会被悄悄丢掉，于是每次都从屏幕右下角开始掉。
    """
    pet.body.teleport(x, y)
    pet.move(round(x), round(y))


def fly(pet, shot_dir: Path | None, tag: str) -> dict:
    """松手之后一直推进到落地，返回轨迹与结论。

    轨迹点 = ``[(x, y)]``（窗口左上角的屏幕坐标）。结论里带"到底飞没飞出去"、
    峰值高度、撞墙次数、什么时候落地。
    """
    path: list[tuple[float, float]] = [(pet.body.x, pet.body.y)]
    edges = 0
    peak_y = pet.body.y
    flung = bool(pet._flung)
    throw_vx, throw_vy = pet.body.vx, pet.body.vy
    shots: list[Path] = []
    landed_at: float | None = None

    for frame in range(int(FLIGHT_LIMIT / DT)):
        if shot_dir is not None and frame in (0, 12, 40):
            out = shot_dir / f"{tag}_f{frame:02d}.png"
            pet.grab().save(str(out))
            shots.append(out)

        ev = pet.body.update(DT, pet._bounds(),
                             use_gravity=bool(pet.cfg.gravity))
        pet.brain.update(DT, on_ground=pet.body.on_ground)
        if ev["edge"] and pet._flung:
            edges += 1
        if pet._flung and ev["landed"]:
            pet._end_fling()            # 落地就把反弹参数还回去
        pet.move(round(pet.body.x), round(pet.body.y))
        path.append((pet.body.x, pet.body.y))
        peak_y = min(peak_y, pet.body.y)

        if frame > 0 and pet.body.on_ground and not pet._flung:
            landed_at = frame * DT
            break

    return {
        "path": path,
        "shots": shots,
        "flung": flung,
        "throw": (throw_vx, throw_vy),
        "peak": peak_y,
        "edges": edges,
        "landed_at": landed_at,
    }


def draw_plot(d: ImageDraw.ImageDraw, box, result, g, xr, label: str) -> None:
    """把一条轨迹画进 box。

    横轴范围 ``xr`` 是**所有情况共用的**（含拖拽时被拖到屏幕外的那一段），
    再叠一个浅框标出屏幕的真实边界 —— 这样既不会画出画布，又能一眼看出
    "拖拽能把窗口带出屏幕，物理第一步就把它拽回来"。
    """
    left, top, right, bottom = g
    x0, y0, x1, y1 = box
    d.rectangle((x0, y0, x1, y1), fill=PANEL_BG, outline=GRID)

    lo, hi = xr

    def mx(x: float) -> float:
        return x0 + (x - lo) / max(1.0, hi - lo) * (x1 - x0)

    def my(y: float) -> float:
        return y0 + (y - top) / max(1.0, bottom - top) * (y1 - y0)

    # 屏幕真实边界（超出它的部分 = 拖动时被带出屏幕）
    d.rectangle((mx(left), my(top), mx(right), my(bottom)), outline=(216, 220, 228))

    # 地面
    gy = my(bottom)
    d.line((x0, gy, x1, gy), fill=GROUND, width=2)

    path = result["path"]
    color = TRUE_C if result["flung"] else FALSE_C
    pts = [(mx(px), my(py)) for px, py in path]
    if len(pts) >= 2:
        d.line(pts, fill=color, width=2, joint="curve")
    sx, sy = pts[0]
    d.ellipse((sx - 3, sy - 3, sx + 3, sy + 3), fill=color)
    ex, ey = pts[-1]
    d.ellipse((ex - 4, ey - 4, ex + 4, ey + 4), outline=color, width=2)

    vx, vy = result["throw"]
    speed = (vx * vx + vy * vy) ** 0.5
    landed = result["landed_at"]
    note = (f"松手速度 {speed:.0f} px/s    最高点 y={result['peak']:.0f}    "
            f"撞墙 {result['edges']} 次    "
            + (f"{landed:.2f}s 落地" if landed is not None else "未落地")
            + f"    横向范围 x={min(p[0] for p in path):.0f}..{max(p[0] for p in path):.0f}")
    d.text((x0, y0 - HEAD_H + 4), label, fill=INK, font=_font(14))
    d.text((x0, y1 + 2), note, fill=color, font=_font(11))


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
    g = pet._bounds()

    # (说明, 每步拖动多少 px, 拖几步, 开着重力?, 往哪边拖)
    cases = [
        ("轻轻放下：拖到位就松手（不该算甩）", 2.0, 8, True, -1),
        ("正常一甩：往左甩，横跨半个屏幕", 16.0, 8, True, -1),
        ("使劲甩：往右甩，撞上屏幕边再弹回来", 90.0, 8, True, 1),
        ("关掉「重力下坠」再使劲甩（甩不动）", 90.0, 8, False, 1),
    ]

    results = []
    for label, step, steps, gravity, sign in cases:
        pet.cfg.gravity = gravity
        # 从屏幕正中起手，左右都留得下足够的路程
        _place(pet, (g[0] + g[2]) / 2.0 - pet._size / 2.0, (g[1] + g[3]) / 2.0)
        pet.body.on_ground = False
        pet.body.stop()
        pet.brain.stop_falling()
        pet._end_fling()
        shot_dir = Path(tempfile.mkdtemp()) if gravity else None
        tag = f"case{len(results)}"
        drag_shot = _drag_and_release(pet, step, steps, sign, shot_dir, tag)
        r = fly(pet, shot_dir, tag)
        if drag_shot is not None:
            r["shots"] = [drag_shot, *r["shots"]]
        r["label"] = label
        results.append(r)
        print(f"  {label}\n      松手速度 {r['throw'][0]:+.0f}/{r['throw'][1]:+.0f}"
              f"  真飞出去={r['flung']}  撞墙 {r['edges']} 次  "
              f"{'落地 %.2fs' % r['landed_at'] if r['landed_at'] else '未落地'}")

    # ---- 拼图
    strip_h = 150
    shots = results[2]["shots"][:4]
    width = PANEL_W + PAD * 2
    height = PAD + 26 + strip_h + 10 + ROW_H * len(cases) + PAD
    sheet = Image.new("RGB", (width, height), BG)
    d = ImageDraw.Draw(sheet)

    d.text((PAD, PAD), "「甩出去」验收：同一只狗、四种手速，真实轨迹",
           fill=INK, font=_font(17))
    y = PAD + 26

    # 真实帧条：被拎起来 / 刚松手 / 飞行中 / 落地后
    if shots:
        labels = ("拖拽中（DRAG）", "刚松手（FALL）", "飞行中", "落地后（IDLE）")
        x = PAD
        for i, sp in enumerate(shots):
            im = Image.open(sp).convert("RGBA")
            k = (strip_h - 40) / max(1, im.height)
            tw = max(1, int(im.width * k))
            im = im.resize((tw, strip_h - 40), Image.Resampling.LANCZOS)
            tile = Image.new("RGB", (tw, strip_h - 40), (255, 255, 255))
            tile.paste(im, (0, 0), im)
            sheet.paste(tile, (x, y + 26))
            d.rectangle((x, y + 26, x + tw, y + strip_h - 14), outline=GRID)
            d.text((x, y), labels[i] if i < len(labels) else f"第 {i} 帧",
                   fill=MUTED, font=_font(11))
            x += tw + 8
        d.text((x + 4, y + 26),
               "↑ 使劲甩那一把的真截图\n（grab() 抓的，不是示意图）",
               fill=MUTED, font=_font(12))
    y += strip_h + 10

    # 横轴范围所有面板共用：把"拖动时被带出屏幕"那一段也装进来，才不会画出画布
    xs = [px for r in results for px, _py in r["path"]]
    xr = (min(min(xs), g[0]) - 20.0, max(max(xs), g[2]) + 20.0)
    for r in results:
        box = (PAD, y + HEAD_H, PAD + PANEL_W, y + HEAD_H + PANEL_H)
        draw_plot(d, box, r, g, xr, r["label"])
        y += ROW_H

    d.text((PAD, y + 2),
           f"横轴范围 x={xr[0]:.0f}..{xr[1]:.0f}（浅框 = 屏幕真实边界 "
           f"{g[0]:.0f}..{g[2]:.0f}）："
           "拖动时窗口会跟着鼠标跑到屏幕外，松手后物理的第一步就把它拉回来。",
           fill=MUTED, font=_font(11))

    out = ROOT / "reports" / "fling_throw.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    print(f"\n产出 {out}  ({sheet.width}x{sheet.height})")

    pet._timer.stop()
    pet._save_timer.stop()
    pet.hide()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
