"""生成预览图，方便放进报告或 README。

产出的图统一写进 ``reports/``（就是 reports/README.md 里列的那几张，
以前是写项目根目录、还得手动挪过去，现在直接落位）：

* ``preview_sheet.png``    当前素材的全部动作帧对照表，带地平线辅助线
* ``shot_game.png``        弹跳得分 · 游戏界面
* ``shot_gameover.png``    弹跳得分 · 结算界面
* ``shot_catcher.png``     接狗狗 · 游戏界面
* ``shot_catcher_over.png`` 接狗狗 · 结算界面

用离屏方式渲染，不会在屏幕上弹窗。
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: 产物目录。reports/ 是"交作业用"的截图仓库，README 里已经按这个目录列了清单，
#: 所以直接写进去，不再落到项目根目录再手动搬。
OUT_DIR = ROOT / "reports"

from PIL import Image, ImageDraw, ImageOps                    # noqa: E402
from PySide6.QtCore import Qt                                   # noqa: E402
from PySide6.QtWidgets import QApplication                      # noqa: E402

from pet import facing as facinglib                            # noqa: E402
from pet.assets import AssetBank, default_set_files             # noqa: E402
from pet.config import Config
from pet.paths import pet_asset_dir                          # noqa: E402
from game.minigame import MiniGame, Pop                         # noqa: E402


def isolate_config() -> Path:
    """把存档路径指到临时文件。

    **必须最先调用。** 小游戏跑到结算会 ``cfg.save()``，而这个脚本用的是
    临时 ``Config()``（位置 -1、最高分 0）—— 不隔开的话，跑一次预览就把
    用户的位置 / 投喂次数 / 最高分全覆写成默认值。

    这不是假想的风险：``verify_desktop.py`` 当初就是因为收尾调了 ``close()``
    把用户存档冲掉，才给所有真窗口脚本立了「备份-还原」的规矩。
    """
    import pet.config as pcfg

    tmp = Path(tempfile.mkdtemp(prefix="pet_preview_")) / "config.json"
    pcfg.config_path = lambda: tmp
    return tmp

ROW_ORDER = ("idle", "walk", "drag", "fall", "poke", "feed")
CELL = 128
GAP = 6
LABEL_H = 22
GROUND_IN_CELL = 116          # 与各生成器的 GROUND_Y 对齐


def make_sheet() -> Path:
    """把五个状态的帧排成一张对照表。

    每条序列只取**默认套**：多套素材（poke_a/poke_b…）混进来会变成
    "poke 有 43 帧"的错觉。多套的效果看 ``tools/verify_variants.py`` 出的
    ``reports/variants.png``。
    """
    pet_dir = pet_asset_dir()
    rows = []
    for state in ROW_ORDER:
        frames = default_set_files(pet_dir, state)
        if not frames:
            continue
        row = Image.new("RGBA", (CELL * 6, CELL + LABEL_H), (240, 242, 248, 255))
        draw = ImageDraw.Draw(row)
        # 地平线：一眼看出各帧的脚底是否对齐
        draw.line([(0, LABEL_H + GROUND_IN_CELL), (CELL * 6, LABEL_H + GROUND_IN_CELL)],
                  fill=(206, 212, 224, 255))
        draw.text((6, 5), f"{state}  ({len(frames)} frames)", fill=(90, 100, 118, 255))
        for i, path in enumerate(frames[:6]):
            with Image.open(path) as im:
                row.alpha_composite(im.convert("RGBA"), (i * CELL, LABEL_H))
        rows.append(row)

    width = CELL * 6
    height = sum(r.height + GAP for r in rows)
    sheet = Image.new("RGBA", (width, height), (255, 255, 255, 255))
    y = 0
    for row in rows:
        sheet.alpha_composite(row, (0, y))
        y += row.height + GAP

    out = OUT_DIR / "preview_sheet.png"
    sheet.save(out)
    return out


def make_game_shots() -> list[Path]:
    from PySide6.QtGui import QLinearGradient, QPainter, QColor   # noqa: F401

    cfg = Config()
    cfg.best_score = max(cfg.best_score, 260)
    bank = AssetBank(pet_asset_dir()).load()

    game = MiniGame(bank, cfg)
    game.score = 180
    game.round_no = 3
    game.time_left = 41.0
    game.ball.teleport(300, 330)
    game.ball.throw(120, -420)
    game.ball.on_ground = False
    game.squash = 1.0
    game._flash = 0.6
    game.pops.append(Pop(360, 250))
    game.pops[0].life = 0.18
    for blk in list(game.blocks)[:4]:
        blk.alive = False
    game.blocks = [b for b in game.blocks if b.alive]
    game._advance(1 / 60)

    p1 = OUT_DIR / "shot_game.png"
    game.grab().save(str(p1))

    game.time_left = 0.01
    game._advance(0.05)
    p2 = OUT_DIR / "shot_gameover.png"
    game.grab().save(str(p2))
    game.close()
    return [p1, p2]


def make_catcher_shots() -> list[Path]:
    """接狗狗的两张截图：正常游玩 + 血量耗尽的结算。

    和 ``make_game_shots`` 一样，摆一个"看起来玩到一半"的场面再抓图 ——
    刚开局那种空场面的截图放进报告里说明不了任何问题。
    """
    from game.catcher import CATCHER_H, CATCHER_W, CatchGame
    from game.common import GROUND_Y, W as GW

    cfg = Config()
    cfg.best_catch = max(cfg.best_catch, 240)
    bank = AssetBank(pet_asset_dir()).load()

    game = CatchGame(bank, cfg)
    game.fallers.clear()
    game._spawn_timer = 1e6                 # 关掉自动出怪，场面自己摆
    game.hp = 3
    game.score = 150
    game.caught = 12
    game.combo = 4
    game.best_combo = 7
    game.survived = 42.0
    game.catcher.teleport((GW - CATCHER_W) / 2, GROUND_Y - CATCHER_H)
    # 三只小白狗各给一套贴图，截图里能同时看到几种不同的形象
    for i, (x, y, kind) in enumerate(((118, 150, "puppy"), (332, 92, "bomb"),
                                      (500, 226, "puppy"), (648, 300, "puppy"))):
        f = game.spawn(kind)
        f.body.teleport(float(x), float(y))
        if kind == "puppy":
            f.variant = i % max(1, len(game.puppy_sets))
    game._advance(1 / 60)

    p1 = OUT_DIR / "shot_catcher.png"
    game.grab().save(str(p1))

    game.hp = 1
    f = game.spawn("bomb")
    f.body.teleport(game.catcher.x, game.catcher.y)
    game._step(1 / 60)
    game._advance(1 / 60)
    p2 = OUT_DIR / "shot_catcher_over.png"
    game.grab().save(str(p2))
    game._timer.stop()
    return [p1, p2]


def make_motion_gif() -> Path:
    """把各个动作连成一段循环动图，并合成到一个假桌面上。

    帧率**从 behavior.FPS 取**，走路的横向位移**从 behavior.WALK_SPEED 取** ——
    不在这里另写一份。预览和实际播放的节奏必须一致，否则预览好看、
    真跑起来不是那个节奏，就白预览了。

    走路那两段是"贴图原地蹦跳 + 整块左右平移"，因为真实实现就是这样：
    窗口负责位移、贴图负责动作，两处分开放才不会叠加。只播贴图不动位置，
    是看不出"它在走"的。向左那段走的是镜像帧，和程序里的处理一致。

    背景画了一个假窗口，让宠物压在窗口边缘上，一眼能看出它是"浮在最上层"的。
    """
    from pet.behavior import FPS, WALK_SPEED, State               # noqa: E402

    pet_dir = pet_asset_dir()
    SPRITE = 192
    MARGIN = 60                      # 左右各留这么宽给走路横移
    BAR_H = 26                       # 假任务栏
    CW, CH = SPRITE + MARGIN * 2, SPRITE + BAR_H + 22
    TOP = (223, 231, 243)
    BOT = (194, 207, 226)

    def load(state: str) -> list[Image.Image]:
        # 只取默认套：多套素材混进来会让动图里同一条序列突然换形象
        files = default_set_files(pet_dir, state)
        if not files:                                   # 缺状态就借 idle，和程序行为一致
            files = default_set_files(pet_dir, "idle")
        out = []
        for path in files:
            with Image.open(path) as im:
                out.append(im.convert("RGBA").resize((SPRITE, SPRITE), Image.Resampling.LANCZOS))
        return out

    def backdrop() -> Image.Image:
        im = Image.new("RGBA", (CW, CH), (0, 0, 0, 0))
        draw = ImageDraw.Draw(im)
        for y in range(CH - BAR_H):
            t = y / max(1, CH - BAR_H)
            draw.line([(0, y), (CW, y)],
                      fill=tuple(int(a + (b - a) * t) for a, b in zip(TOP, BOT)) + (255,))
        # 假窗口：宠物压在它的右下角上，用来说明"置顶"
        draw.rounded_rectangle([10, 14, CW - 34, CH - BAR_H - 34], radius=8,
                               fill=(255, 255, 255, 255), outline=(206, 214, 228, 255))
        draw.line([(10, 34), (CW - 34, 34)], fill=(226, 232, 242, 255))
        draw.ellipse([18, 22, 26, 30], fill=(255, 138, 128, 255))
        draw.ellipse([32, 22, 40, 30], fill=(255, 208, 120, 255))
        # 假任务栏
        draw.rectangle([0, CH - BAR_H, CW, CH], fill=(246, 248, 252, 255))
        draw.line([(0, CH - BAR_H), (CW, CH - BAR_H)], fill=(210, 217, 230, 255))
        return im

    # 每帧实际横向位移：窗口按 WALK_SPEED px/s 移动，贴图这里是 128 -> SPRITE 的放大图
    step = WALK_SPEED / FPS[State.WALK] * (SPRITE / 128.0)

    # 播放脚本：(状态, 播几帧, 用哪个状态的帧率, 每帧横向位移, 是否左右镜像)
    # 帧数写 None = 把这套素材的帧全播完，换素材不用回来改数字
    # 向右走要不要镜像，取决于素材原图朝哪边 —— 和窗口绘制同一套判断
    base = facinglib.current()
    mirror_right = facinglib.should_mirror(1, base)
    mirror_left = facinglib.should_mirror(-1, base)
    script = [("idle", None, State.IDLE, 0.0, False),
              ("walk", None, State.WALK, step, mirror_right),
              ("idle", 8, State.IDLE, 0.0, False),
              ("poke", None, State.POKE, 0.0, False),
              ("idle", 8, State.IDLE, 0.0, False),
              ("feed", None, State.FEED, 0.0, False),
              ("idle", 8, State.IDLE, 0.0, False),
              ("drag", None, State.DRAG, 0.0, False),
              ("walk", None, State.WALK, -step, mirror_left),
              ("idle", None, State.IDLE, 0.0, False)]

    frames: list[Image.Image] = []
    delays: list[int] = []
    for state, limit, key, dx, mirror in script:
        seq = load(state)
        if not seq:
            continue
        if limit:
            seq = seq[:limit]
        # 对齐用第一帧的内容底边，整段共用一个落点（逐帧对齐会把动作压平）。
        # getbbox() 对**全透明**的帧返回 None —— 图坏掉时不该整个脚本崩，
        # 退回"整张画布"继续跑，出来的对比图里一眼就能看出那一帧是空的。
        bb = seq[0].getbbox() or (0, 0, seq[0].width, seq[0].height)
        anchor = bb[3]
        base = backdrop()
        for i, sprite in enumerate(seq):
            if mirror:
                sprite = ImageOps.mirror(sprite)
            x = MARGIN + round(dx * i)
            shot = base.copy()
            shot.alpha_composite(sprite, (x, CH - BAR_H - anchor))
            frames.append(shot.convert("RGB"))
            delays.append(round(1000.0 / FPS[key]))

    out = OUT_DIR / "preview_motion.gif"
    frames[0].save(out, save_all=True, append_images=frames[1:],
                   duration=delays, loop=0, optimize=True, disposal=2)
    print(f"[preview] {out.name}  {len(frames)} 帧  "
          f"{out.stat().st_size / 1024:.0f} KB")
    return out


def main() -> int:
    if not any(pet_asset_dir().glob("*.png")):
        print(f"素材目录 {pet_asset_dir()} 下没有任何贴图，")
        print("先把 GIF/PNG 放进 custom_pet/（或在 raw/inbox 里跑 tools/intake.py --apply）")
        return 1

    isolate_config()                      # 必须在任何 cfg 落盘之前
    app = QApplication(sys.argv)          # noqa: F841  (QPixmap 需要 QApplication)

    # 和程序本体共用同一条中文字体回退链，否则截图里的中文会渲染成方框
    from main import apply_ui_font        # 延迟导入：main 会拉起一整套依赖
    apply_ui_font(app)

    sheet = make_sheet()
    shots = make_game_shots() + make_catcher_shots()
    print(f"[preview] {sheet.name}")
    for p in shots:
        print(f"[preview] {p.name}")
    make_motion_gif()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
