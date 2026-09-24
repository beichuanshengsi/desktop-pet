"""养成状态的验收：跑满 36 小时，把三条曲线和"它什么时候自己睡了"画出来。

为什么要跑这么长：这一层最容易糊弄过去 —— 数值看起来"会变"，但变多快、
会不会见底、困了到底睡不睡、睡完精神回不回来，这些只有把时间轴拉长到
一天以上才看得出来。一小时以内的用例只能证明"数在动"。

产出 ``reports/vitals_curve.png``：

* 两条对照：「完全不管」和「每 6 小时喂一口 + 逗一下」；
* 三条曲线 = 饱食 / 心情 / 精力，横轴是小时；
* 浅色斜纹带 = 它自己趴下睡了（SLEEP 状态）；
* 虚线 = 饿 / 蔫 / 困 三条阈值线。

**全程用真实窗口跑闭环**（``PetWindow._advance``），不是直接调 ``Vitals`` ——
直接调的话就验不到"精力掉到线下会触发 SLEEP、睡着走 rest 路径回精力"这条回路，
而那正是这一层跟状态机接上的地方。

脚本不跑事件循环、结束用 ``hide()`` 而不是 ``close()``，并把存档指到临时文件。
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFont                        # noqa: E402
from PySide6.QtWidgets import QApplication                         # noqa: E402

DT = 5.0                   # 仿真步长（秒）。5 秒一步够细：睡/醒最快也要几十秒
HOURS = 36.0
SAMPLE_EVERY = 12          # 每 12 步 = 每 60 秒记一个点

PLOT_W, PLOT_H = 900, 300
PAD = 26
ROW_H = PLOT_H + 62
BG = (243, 244, 247)
PANEL_BG = (255, 255, 255)
INK = (32, 34, 40)
MUTED = (124, 128, 138)
GRID = (231, 234, 241)
SLEEP_BAND = (206, 219, 245)
C_SATIETY = (232, 145, 58)
C_MOOD = (226, 96, 138)
C_ENERGY = (74, 132, 226)


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


def _care(pet, feeds: int, plays: int) -> None:
    """喂 ``feeds`` 口、逗 ``plays`` 下。

    每次都要清掉连点冷却：那是按**真实时钟**（0.35 秒）防手滑的，
    而这个脚本里时间是被快进的 —— 不改它的话第二口就喂不进去了。
    """
    for _ in range(feeds):
        pet._last_action.clear()
        pet.feed()
    for _ in range(plays):
        pet._last_action.clear()
        pet.poke()


def simulate(care: bool) -> dict:
    """跑一遍 36 小时。``care=True`` 表示每 3 小时来照顾一次（喂两口 + 逗两下）。"""
    from pet.assets import AssetBank
    from pet.config import Config
    from pet.paths import pet_asset_dir
    from pet.window import PetWindow
    from pet.behavior import State

    bank = AssetBank(pet_asset_dir()).load()
    cfg = Config()
    cfg.auto_walk = False
    pet = PetWindow(cfg, bank)
    pet.brain.auto_walk = False
    pet.show()

    samples: list[tuple[float, float, float, float, bool]] = []   # 小时,饱和,心情,精力,睡
    sleep_bouts: list[tuple[float, float]] = []
    was_asleep = False
    bout_start = 0.0

    total = int(HOURS * 3600 / DT)
    next_care = 3 * 3600.0
    for step in range(total):
        t = step * DT
        if care and t >= next_care:
            next_care += 3 * 3600.0
            _care(pet, feeds=2, plays=2)
        pet._advance(DT)

        asleep = pet.brain.state is State.SLEEP
        if asleep and not was_asleep:
            bout_start = t
        elif was_asleep and not asleep:
            sleep_bouts.append((bout_start / 3600.0, t / 3600.0))
        was_asleep = asleep

        if step % SAMPLE_EVERY == 0:
            samples.append((t / 3600.0, pet.vitals.satiety, pet.vitals.mood,
                            pet.vitals.energy, asleep))

    if was_asleep:
        sleep_bouts.append((bout_start / 3600.0, HOURS))

    pet._timer.stop()
    pet._save_timer.stop()
    pet.hide()
    return {"samples": samples, "sleep": sleep_bouts}


def plot(d: ImageDraw.ImageDraw, box, data, title: str) -> None:
    from pet.vitals import HUNGRY_AT, SAD_AT, TIRED_AT

    x0, y0, x1, y1 = box
    d.rectangle((x0, y0, x1, y1), fill=PANEL_BG, outline=GRID)

    def mx(h: float) -> float:
        return x0 + h / HOURS * (x1 - x0)

    def my(v: float) -> float:
        return y1 - v / 100.0 * (y1 - y0)

    # 睡着的时间段：浅色竖带
    for a, b in data["sleep"]:
        d.rectangle((mx(a), y0, mx(b), y1), fill=SLEEP_BAND)

    # 阈值线
    for v, label, color in ((HUNGRY_AT, "饿", C_SATIETY),
                            (SAD_AT, "蔫", C_MOOD),
                            (TIRED_AT, "困", C_ENERGY)):
        yy = my(v)
        for px in range(int(x0), int(x1), 8):
            d.line((px, yy, px + 4, yy), fill=(206, 210, 220))
        d.text((x1 - 68, yy - 15), f"{label}线 {v:.0f}", fill=MUTED,
               font=_font(10))

    # 刻度
    for h in range(0, int(HOURS) + 1, 6):
        d.line((mx(h), y1, mx(h), y1 + 4), fill=(198, 202, 212))
        d.text((mx(h) - 8, y1 + 5), f"{h}h", fill=MUTED, font=_font(10))
    for v in (0, 50, 100):
        d.text((x0 - 24, my(v) - 7), f"{v}", fill=MUTED, font=_font(10))

    series = (("饱食", C_SATIETY, 1), ("心情", C_MOOD, 2), ("精力", C_ENERGY, 3))
    for label, color, idx in series:
        pts = [(mx(s[0]), my(s[idx])) for s in data["samples"]]
        if len(pts) >= 2:
            d.line(pts, fill=color, width=2, joint="curve")
        lx = x1 + 6
        d.text((lx, y0 + 4 + 15 * (idx - 1)), "■", fill=color, font=_font(11))
        d.text((lx + 12, y0 + 4 + 15 * (idx - 1)), label, fill=INK, font=_font(11))

    d.text((x0, y0 - 22), title, fill=INK, font=_font(15))


def summarize(name: str, data: dict) -> str:
    from pet.vitals import HUNGRY_AT, SAD_AT, TIRED_AT
    s = data["samples"]
    low = min(x[1] for x in s)
    moods = min(x[2] for x in s)
    energy = min(x[3] for x in s)
    hungry_h = next((x[0] for x in s if x[1] < HUNGRY_AT), None)
    sad_h = next((x[0] for x in s if x[2] < SAD_AT), None)
    tired_h = next((x[0] for x in s if x[3] < TIRED_AT), None)
    bouts = data["sleep"]
    parts = [
        f"饱食最低 {low:.0f}（{'第 %.0f 小时开始饿' % hungry_h if hungry_h else '没饿过'}）",
        f"心情最低 {moods:.0f}（{'第 %.0f 小时开始蔫' % sad_h if sad_h else '没蔫过'}）",
        f"精力最低 {energy:.0f}（{'第 %.0f 小时开始困' % tired_h if tired_h else '没困过'}）",
        f"自主睡了 {len(bouts)} 觉，共 {sum(b - a for a, b in bouts):.1f} 小时",
    ]
    return name + "：" + "    ".join(parts)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    isolate_config()

    print("跑「完全不管」36 小时…")
    ignored = simulate(care=False)
    print("跑「每 3 小时喂两口 + 逗两下」36 小时…")
    cared = simulate(care=True)

    lines = [summarize("完全不管", ignored), summarize("定期照顾", cared)]
    for line in lines:
        print("  " + line)
    # 睡觉必须是一觉一觉的，不能抽：这条是滞回（TIRED_AT 进 / RESTED_AT 出）的体检
    for name, data in (("完全不管", ignored), ("定期照顾", cared)):
        print(f"  {name}：睡觉次数 {len(data['sleep'])}"
              f"（一次约 {sum(b - a for a, b in data['sleep']) * 60 / max(1, len(data['sleep'])):.0f} 分钟）")

    width = PAD * 2 + PLOT_W + 90
    height = PAD + ROW_H * 2 + PAD
    sheet = Image.new("RGB", (width, height), BG)
    d = ImageDraw.Draw(sheet)

    d.text((PAD, PAD - 20),
           "养成状态验收：36 小时真实闭环（浅带 = 它自己趴下睡了）",
           fill=INK, font=_font(17))

    y = PAD + 6
    for data, title in ((ignored, lines[0]), (cared, lines[1])):
        plot(d, (PAD, y + 22, PAD + PLOT_W, y + 22 + PLOT_H), data, title)
        y += ROW_H

    out = ROOT / "reports" / "vitals_curve.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    print(f"\n产出 {out}  ({sheet.width}x{sheet.height})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
