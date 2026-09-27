"""v2.2.0 的验收：两款新游戏（跑一跑 / 狗粮 2048）。

产出 ``reports/v22_ui.png``，四节：

    ① 跑一跑 · 一帧       障碍三态同框（矮墩 / 垂杆 / 高墙）+ 一整条 HUD
    ② 跑一跑 · 三种姿态   站立 / 低头 / 跳跃，**低头是把贴图压扁**，得看像素
    ③ 狗粮 2048 · 一帧    棋盘配色阶 + 格子里的数字
    ④ 狗粮 2048 · 两种盘面 早局（2~32）与残局（含 512），验配色阶与数字字号

为什么这些必须靠"看图"才能验
----------------------------
* **低头**是"现役素材里没有这个状态、只好把走路帧压扁"的占位做法。
  压扁之后还认不认得出是那只狗，``height()`` 返回 34 这件事一个字都答不上来。
* **垂杆**是一根从屏幕顶垂到离地 40 的柱子。"看着像不像一道要低头的门"
  直接决定玩家会不会本能地去按 ↓ —— 规则对、但看着不像，玩家就不会用。
* **2048 的配色阶与字号**：88px 的格子塞 "1024" 要缩到多大才不溢出，
  只有画出像素来才知道（溢出会压到隔壁格子，和 HUD 叠字是同一类错误）。
* **HUD 各段的真字宽**：冒烟测试跑在 offscreen 平台上，那个平台插件在本机
  **字体库是空的**，``QFontMetrics`` 量出来是方框的宽度（约真值两倍）。
  所以"预算宽度够不够"只能在这里量，量完和登记表 ``HUD_WIDEST_PX`` 对照。

跑法（会写 `reports/`，不会碰用户的 `config.json`）：

    python tools/verify_v22_ui.py

**故意不设 offscreen** —— 理由见 ``tools/verify_v21_ui.py`` 开头（字体库是空的）。
``Sheet`` / ``to_pil`` / ``isolate_config`` 这些排版零件直接从那个脚本 import，
免得抄第二份（本文件只多一个"裁剪"的辅助）。
"""

from __future__ import annotations

import random
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from PIL import Image                                              # noqa: E402

from verify_v21_ui import Sheet, isolate_config, to_pil            # noqa: E402


def crop_shot(pm, box: tuple[int, int, int, int], scale: float = 1.0):
    """把一张抓图裁出一块（可选缩放）再转回 QPixmap 交给 ``Sheet``。

    为什么要转回去：``Sheet`` 只认 QPixmap / QImage（它内部再走 ``to_pil``）。
    这里多绕一次 PNG，换的是"不必给 ``Sheet`` 加一条只在本次用得到的 PIL 分支"。
    """
    from PySide6.QtGui import QPixmap

    im = to_pil(pm).crop(box)
    if scale != 1.0:
        im = im.resize((max(1, int(im.width * scale)),
                        max(1, int(im.height * scale))),
                       Image.Resampling.LANCZOS)
    tmp = Path(tempfile.mkdtemp()) / "crop.png"
    im.save(tmp)
    return QPixmap(str(tmp))


def print_hud_widths() -> int:
    """量两款新游戏 HUD 各段最宽内容的**真字宽**，和登记表对照。

    两者对不上就说明字号或文案改了、``HUD_WIDEST_PX`` 要跟着更新。
    这是唯一能验这件事的地方（理由见模块开头）。
    """
    from game import g2048 as glib
    from game import runner as rlib

    bad: list[str] = []
    for tag, mod in (("跑一跑", rlib), ("狗粮2048", glib)):
        got = mod.measure_hud_widest()
        print(f"{tag} HUD 最宽内容的真实像素宽度（登记值 / 实量）:")
        for name in mod.HUD_ZONES:
            over = got[name] > mod.HUD_WIDEST_PX[name]
            print(f"  {name:6s} {mod.HUD_WIDEST[name]:<12s} "
                  f"{mod.HUD_WIDEST_PX[name]:4d} / {got[name]:4d}"
                  f"{'  <- 超了！' if over else ''}")
            if over:
                bad.append(f"{tag}.{name}")
    return len(bad)


def main() -> int:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    isolate_config()

    from game.common import GROUND_Y
    from game.g2048 import BOARD, BOARD_X, BOARD_Y, Game2048, TARGET
    from game.runner import (KINDS, PLAYER_X, PIXELS_PER_POINT, SPEED_STEP_DIST,
                             Rock as RunRock, Runner, speed_for)
    from pet.assets import AssetBank
    from pet.config import Config
    from pet.paths import pet_asset_dir

    bank = AssetBank(pet_asset_dir()).load()
    cfg = Config()

    sheet = Sheet()
    sheet.title("v2.2.0 新增：跑一跑 / 狗粮 2048（都是真帧，不是示意图）",
                "两款各抓一帧整图；② 的三种姿态是从整帧里裁出来的局部。")

    bad = print_hud_widths()
    if bad:
        print(f"[!] 这些段的预算宽度不够了，HUD_ZONES / HUD_WIDEST_PX 要一起改：{bad}")

    # ------------------------------------------------ ① 跑一跑 · 一帧
    run = Runner(bank, cfg)
    run._timer.stop()
    run.rng = random.Random(20260927)
    run._reset_scene()
    run.tier = 5
    run.speed = speed_for(5)
    run.distance = 5 * SPEED_STEP_DIST + 1500          # 让档位进度条走到一半
    run.score = int(run.distance / PIXELS_PER_POINT)
    run.feet = float(GROUND_Y)
    # 为了让三种障碍同框，间距比实战紧（实战是 speed × 0.9~1.5 秒）
    run.rocks = [RunRock(KINDS["low"], 210.0),
                 RunRock(KINDS["tall"], 400.0),
                 RunRock(KINDS["bird"], 620.0)]
    print(f"跑一跑一帧：{len(run.rocks)} 个障碍，第 {run.tier + 1} 档，"
          f"{run.speed:.0f} px/s")
    sheet.section(
        "① 跑一跑 · 一帧（三种障碍同框）",
        run.grab(),
        "从左到右：\n"
        "  · 矮墩（地上长出来）→ 跳\n"
        "  · 高墙（更宽更高）→ 跳\n"
        "  · 垂杆（从顶上垂到离地 40）\n"
        "    → **只能低头**。它必须占满\n"
        "    从顶到底的整段：否则玩家\n"
        "    跳得够高就能从上面越过去，\n"
        "    「低头」这个动作就废了。\n\n"
        "HUD 四段：得分 / 最高 / 档位 /\n"
        "速度（右对齐），中间那条进度\n"
        "条是「离下一档还差多远」。\n\n"
        "地面那几道短横线按跑过的距离\n"
        "滚动 —— 静止的一帧里也要能\n"
        "看出它在跑。",
        scale=0.86,
    )

    # ------------------------------------------------ ② 跑一跑 · 三种姿态
    box = (PLAYER_X - 80, GROUND_Y - 220, PLAYER_X + 120, GROUND_Y + 26)

    def pose(crouch: bool, lift: float):
        """抓一帧指定姿态（裁剪到玩家周围）。``lift`` 是脚底离地高度。"""
        w = Runner(bank, cfg)
        w._timer.stop()
        w._reset_scene()
        w.rocks = []
        w.crouching = crouch
        w.on_ground = lift == 0.0
        w.feet = float(GROUND_Y - lift)
        return crop_shot(w.grab(), box)

    poses = [pose(False, 0.0), pose(True, 0.0), pose(False, 96.0)]
    print("三种姿态抓图完成：站立 / 低头 / 跳跃")
    sheet.section(
        "② 跑一跑 · 三种姿态（站立 / 低头 / 跳跃）",
        poses,
        "现役素材里**没有「低头」这个\n"
        "状态**，所以低头是把走路帧\n"
        "压扁到 34px 高 —— 占位做法，\n"
        "和另外几款的「代码画素材」\n"
        "是一个路子：等真有素材了，\n"
        "换掉 _frame() 就行，规则不用动。\n\n"
        "跳跃那一帧用的是 idle 帧：\n"
        "素材里没有「腾空」这个状态，\n"
        "走路帧在空中有种「还在原地\n"
        "跑」的怪异感。\n\n"
        "脚底始终贴在地面线上（影子在\n"
        "下面），所以三种高度的差别\n"
        "一眼看得出。",
    )

    # ------------------------------------------------ ③ 狗粮 2048 · 一帧
    game = Game2048(bank, cfg)
    game._timer.stop()
    game.rng = random.Random(7)
    game._reset_scene()
    game.grid = ((2, 8, 32, 4),
                 (128, 16, 2, 64),
                 (4, 256, 8, 2),
                 (16, 2, 4, 32))
    game.score = 2564
    game.undo_left = 2
    print(f"2048 一帧：最大 {max(c for row in game.grid for c in row)}，"
          f"得分 {game.score}")
    sheet.section(
        "③ 狗粮 2048 · 一帧",
        game.grab(),
        "棋盘 420×420 居中，格子 87px。\n"
        "底色随数值加深（越大的块\n"
        "越像烤得越焦），数字越大\n"
        "字号越往下调。\n\n"
        "空位是浅一档的暖灰 ——\n"
        "它和「2」的米黄要一眼分得开，\n"
        "否则满盘时看不出哪儿还有空。\n\n"
        "HUD 第四段是撤销次数。\n"
        "棋盘下那行灰字把三个按键\n"
        "说全（方向键 / Z / R）。\n\n"
        "右侧进度条是**对数**的：\n"
        "线性的话，最后那一格会永远\n"
        "卡在 90%，看着像没在动。",
        scale=0.86,
    )

    # ------------------------------------------------ ④ 狗粮 2048 · 两种盘面
    board_box = (BOARD_X - 16, BOARD_Y - 16,
                 BOARD_X + BOARD + 16, BOARD_Y + BOARD + 16)

    def board_of(cells, over: bool = False):
        w = Game2048(bank, cfg)
        w._timer.stop()
        w._reset_scene()
        w.grid = cells
        w.over = over
        w.won = over
        w.undo_left = 2 if not over else 0
        return crop_shot(w.grab(), board_box, 0.72)

    early = board_of(((2, 0, 0, 0),
                      (0, 4, 0, 0),
                      (0, 0, 8, 0),
                      (0, 0, 0, 16)))
    late = board_of(((512, 256, 64, 8),
                     (4, 128, 32, 2),
                     (16, 64, 8, 4),
                     (2, 4, 2, 16)), over=True)
    print(f"两种盘面抓图完成（残局已含 {TARGET}，外圈带金边）")
    sheet.section(
        "④ 狗粮 2048 · 早局与残局（配色阶 / 数字字号）",
        [early, late],
        "左：刚开局那种稀疏盘面，\n"
        "底色几乎都是浅的。\n\n"
        "右：残局。三件事在这一图里：\n"
        "  · 数值越大底色越深，256 和\n"
        "    512 的差别一眼看得出；\n"
        "  · 「512」是三位数，字号已经\n"
        "    降过一档，没有溢出格子；\n"
        "  · 外圈金边 = 已经达成目标\n"
        "    （512 就是这一款的目标）。\n\n"
        "数字字号是按**位数**查表定的\n"
        "（1~2 位 30px、3 位 24px、\n"
        "4 位 19px），另外还有一道\n"
        "兜底：真量出宽度超过格子就\n"
        "再降一档 —— 溢出会压到隔壁\n"
        "格子，和 HUD 叠字是同一类错。",
    )

    out = ROOT / "reports" / "v22_ui.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    im = sheet.finish(out)
    print(f"产出 {out}  {im.width}x{im.height}")

    for w in (run, game):
        w._timer.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
