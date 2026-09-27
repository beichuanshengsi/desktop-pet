"""v2.1.0 新增界面的验收：滚轮时长选择器 / 状态面板 / 划过气泡 / 打砖块重做。

这些东西有个共同点：**逻辑全绿也可能不好看**。

* 三列滚轮是自绘的 —— 中心带高亮、越远越淡、滚到上限时某列只剩一个值，
  这些只有画出像素来才知道"像不像一个滚轮"。
* 状态面板和气泡全是自绘的条与字，排版歪一像素在代码里看不出来。
* 打砖块重做后新增了四条绘制路径（耐久数字 / 裂纹 / 道具方块 / 限时状态标签），
  只测 `_hit_block` 的返回值是覆盖不到它们的。

产出 ``reports/v21_ui.png``：把上面四块各抓一张真图，右边配一段"这张图在说什么"。

跑法（会写 `reports/`，不会碰用户的 `config.json`）：

    python tools/verify_v21_ui.py

**故意不设 `QT_QPA_PLATFORM=offscreen`**（虽然那看着更"干净"）：
offscreen 那个平台插件在本机的 Qt 里**字体库是空的**，连阿拉伯数字都画成
方框 —— 抓出来的图全是豆腐块，正好把"这张图想给人看什么"毁掉。
（这个坑在 `reports/v21_ui.png` 的第一版真踩了一次：整张图没有一个认得的字。）
所以这里和 `render_preview.py` / `verify_catch_items.py` 一样跑在真实平台上，
但要抓的控件**一律不 `show()`**，只 `grab()` —— 唯一的例外是状态气泡，
它得走一遍 `popup_near()` 才能验证"会不会摆到屏幕外"，所以它那一瞬间会闪一下。
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

BG = (243, 244, 247)
INK = (32, 34, 40)
MUTED = (122, 128, 140)
GRID = (223, 228, 238)
NOTE = (72, 80, 96)

PAD = 22
#: 版面宽度。最宽的一张图是打砖块那一帧（780 × 0.86 ≈ 670），
#: 右侧留 380 放说明 —— 说明是手写折行的，最长的行约 200px，够用。
SHEET_W = 1120
NOTE_W = 380


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
    """把存档指到临时文件 —— 验收脚本绝不能动用户真实的 ``config.json``。"""
    from pet import config as pcfg
    tmp = Path(tempfile.mkdtemp()) / "cfg.json"
    pcfg.config_path = lambda: tmp


def to_pil(qimg, scale: float = 1.0) -> Image.Image:
    """QPixmap / QImage -> PIL，可选缩放。

    走一次 PNG 落盘再读回来，而不是直接读 `constBits()` —— 省得去操心
    每行字节对齐和通道顺序（这个项目在 `verify_desktop.py` 里已经踩过
    一次"字节序读反了，图看着像底片"）。
    """
    from PySide6.QtGui import QImage
    if not isinstance(qimg, QImage):
        qimg = qimg.toImage()
    tmp = Path(tempfile.mkdtemp()) / "grab.png"
    qimg.save(str(tmp))
    im = Image.open(tmp).convert("RGB")
    if scale != 1.0:
        im = im.resize((max(1, int(im.width * scale)),
                        max(1, int(im.height * scale))),
                       Image.Resampling.LANCZOS)
    return im


class Sheet:
    """一路往下贴：每节 = 标题 + 一行图 + 右侧说明。"""

    def __init__(self) -> None:
        self.canvas = Image.new("RGB", (SHEET_W, 4000), BG)
        self.d = ImageDraw.Draw(self.canvas)
        self.y = PAD

    def title(self, text: str, sub: str = "") -> None:
        self.d.text((PAD, self.y), text, fill=INK, font=_font(19))
        self.y += 28
        if sub:
            self.d.text((PAD, self.y), sub, fill=MUTED, font=_font(12))
            self.y += 22
        self.y += 6

    def section(self, title: str, images, notes: str, scale: float = 1.0) -> None:
        if not isinstance(images, (list, tuple)):
            images = [images]
        self.d.text((PAD, self.y), title, fill=INK, font=_font(15))
        self.y += 26

        x = PAD
        max_h = 0
        for qimg in images:
            im = to_pil(qimg, scale)
            self.canvas.paste(im, (x, self.y))
            self.d.rectangle((x, self.y, x + im.width, self.y + im.height),
                             outline=GRID)
            x += im.width + 14
            max_h = max(max_h, im.height)

        self.d.multiline_text((SHEET_W - PAD - NOTE_W, self.y), notes,
                              fill=NOTE, font=_font(12), spacing=6)
        self.y += max_h + 26

    def finish(self, out: Path) -> Image.Image:
        sheet = self.canvas.crop((0, 0, SHEET_W, self.y + PAD))
        sheet.save(out)
        return sheet


def print_hud_widths() -> int:
    """把 HUD 各段"最宽内容"的真字体宽度重量一遍，和登记表对照。

    这是**唯一能验这件事的地方**：冒烟测试跑在 offscreen 平台，那个插件的字体库
    是空的，量出来是方框宽度（比真值宽一倍左右），所以那边只能比登记表。
    两者对不上就说明字号或文案改了、``HUD_WIDEST_PX`` 要更新。
    """
    from game.minigame import (HUD_BAR, HUD_WIDEST_PX, HUD_ZONES, HUD_WIDEST,
                               measure_hud_widest, hud_zone_rect)

    got = measure_hud_widest()
    bad = []
    print("HUD 各段最宽内容的真实像素宽度（登记值 / 实量）:")
    for name in ("score", "combo", "best", "round", "secs"):
        mark = "" if got[name] <= HUD_WIDEST_PX[name] else "  <- 超了！"
        print(f"  {name:6s} {HUD_WIDEST[name]:<20s} "
              f"{HUD_WIDEST_PX[name]:4d} / {got[name]:4d}{mark}")
        if got[name] > HUD_WIDEST_PX[name]:
            bad.append(name)
    spans = {k: hud_zone_rect(k) for k in HUD_ZONES}
    print("  各段占用区间:", "；".join(f"{k}={spans[k]}" for k in spans))
    print(f"  倒计时条 {HUD_BAR}")
    if bad:
        print(f"  [!] {bad} 的宽度不够了，HUD_ZONES / HUD_WIDEST_PX 要一起改")
    return len(bad)


def main() -> int:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    isolate_config()

    from game.minigame import (BLOCK_LEFT, BLOCK_W, DROP_BY_KEY, Drop,
                               MiniGame, Pop, combo_mult)
    from pet.assets import AssetBank
    from pet.config import Config
    from pet.panel import BagPanel
    from pet.paths import pet_asset_dir
    from pet.window import PetWindow
    from pet.wheel_dialog import DurationDialog, WheelPicker
    from game import GAMES

    bank = AssetBank(pet_asset_dir()).load()
    cfg = Config()
    # 故意把状态设成一个"该管管它了"的样子：饱食低、精力见底，
    # 三条状态条的颜色分档（低 = 红）才看得出来。
    cfg.coins = 137
    cfg.pomodoro_seconds = 45 * 60 + 30

    pet = PetWindow(cfg, bank, GAMES)
    pet.bag.add("treat", 2)
    pet.bag.add("ball")
    pet.bag.add("feast")
    pet.vitals.satiety = 12.0
    pet.vitals.mood = 64.0
    pet.vitals.energy = 21.0

    sheet = Sheet()
    sheet.title("v2.1.0 新增界面与玩法验收",
                "五张都是控件自己 grab() 出来的真图（v2.2.0 重画：划过气泡已撤掉，"
                "第 ③④ 节按新行为出图）")

    print_hud_widths()

    # ---------------------------------------------------- ① 滚轮时长对话框
    dlg = DurationDialog(cfg.pomodoro_seconds)
    dlg.adjustSize()
    print(f"对话框停在 {dlg.selected_seconds()} 秒（上次选的）")
    sheet.section(
        "① 番茄钟：自定义时长对话框（滚轮 = 1 秒 ~ 2 小时）",
        dlg.grab(),
        "三个入口都通到同一个 WheelModel：\n"
        "  · 鼠标滚轮（悬停在哪列滚哪列）\n"
        "  · 按住上下拖动\n"
        "  · ↑↓ 翻格、←→ 换列\n\n"
        "所以循环 / 联动 / 夹紧只有一份\n"
        "实现，不会出现「滚轮能滚到\n"
        "2:30、拖动就不行」这种打架。\n\n"
        "中间高亮条里的数字才是选中的；\n"
        "上下两行是前后一格的预览，\n"
        "越远越淡。\n\n"
        "下面一排快捷档位直接复用\n"
        "menu.POMODORO_CHOICES ——\n"
        "菜单和对话框必须是同一份清单。",
    )

    # ---------------------------------------------------- ② 三条联动规则
    p1 = WheelPicker(seconds=45 * 60 + 30)
    p2 = WheelPicker(seconds=7200)          # 直接给上限：看"分秒只剩 0"
    print(f"左：{int(p1.seconds())} 秒；右：{int(p2.seconds())} 秒（上限）")
    sheet.section(
        "② 联动规则（写在 pet/wheel.py，纯逻辑可单测）",
        [p1.grab(), p2.grab()],
        "左：45 分 30 秒 —— 三列都能滚。\n\n"
        "右：2 小时 —— 到了上限，\n"
        "「分」「秒」两列只剩 0 这一个值，\n"
        "所以 2:30:50 这种组合不存在。\n"
        "（列里只有一个值时不再循环画，\n"
        "否则上下会重复出现同一个数字，\n"
        "看着像坏了。）\n\n"
        "另外两条：\n"
        "  · 时 = 0 且 分 = 0 → 秒列 1..59\n"
        "    （滚不到 0，最短就是 1 秒）\n"
        "  · 时 < 2 → 分、秒列 0..59",
        scale=1.0,
    )

    # ---------------------------------------------------- ③ 背包面板
    panel = BagPanel(pet, cfg)
    panel.refresh()
    print(f"面板：金币 {panel.money.text()}，{panel.bag_title.text()}")
    sheet.section(
        "③ 背包面板（右键菜单「背包面板」）",
        panel.grab(),
        "金币用 22pt 大字打头，下面是背包。\n\n"
        "商品格子「没买的也画出来」：\n"
        "灰掉、写 ×0 —— 这样「还能买\n"
        "什么」一眼看得见，而不是\n"
        "「背包里没有就整行消失」，\n"
        "让人以为小卖部缺货。\n\n"
        "底部那行灰字指着状态的去处：\n"
        "v2.2.0 把面板里的三条状态条\n"
        "撤了（状态值只在右键菜单看），\n"
        "不指一下的话老用户会以为\n"
        "状态显示丢了。",
    )

    # ---------------------------------------------------- ④ 状态值只在右键菜单
    menu = pet._build_menu()
    menu.adjustSize()
    print(f"右键菜单尺寸 {menu.width()}x{menu.height()}")
    sheet.section(
        "④ 状态值：只在右键菜单里（划过不再弹任何东西）",
        menu.grab(),
        "上一版鼠标划过狗就弹一个\n"
        "178px 宽的状态卡片，用户用了\n"
        "一天就要求撤掉 —— 问题不在\n"
        "「看不看得见」，而在**频次**：\n"
        "划过是最高频的意外动作，\n"
        "每次路过都汇报一次就成了打扰。\n\n"
        "现在状态值只剩两个出口，\n"
        "都是用户主动触发的：\n"
        "  · 右键菜单顶上那两行（本图）\n"
        "  · 托盘 tooltip（鼠标停一下）\n\n"
        "第一行是三个数值 + 金币；\n"
        "只有真该管了的时候，才多出\n"
        "一行「要注意：……」。",
    )

    # ---------------------------------------------------- ⑤ 打砖块重做
    mg = MiniGame(bank, cfg)
    mg.rng = random.Random(20260927)
    mg._reset_scene(first=True)
    # 摆一个"打到第 2 轮、上排快碎、刚好连了 6 下"的局面：
    # 耐久数字、裂纹、道具、连击倍率、限时状态五条绘制路径同时走到。
    for b in mg.blocks:
        if b.row == 0:
            b.hp = 1                 # 上排快碎了 → 裂纹最密
        elif b.row == 1:
            b.hp = max(1, b.hp - 1)
    # 打掉下面那排的一格：看得出"这局已经在打了"，而不是刚开局
    hole_x = BLOCK_LEFT + 4 * (BLOCK_W + 14)
    mg.blocks = [b for b in mg.blocks
                 if not (b.row == 2 and abs(b.body.x - hole_x) < 1.0)]
    mg.round_no = 2
    mg.score = 385
    mg.combo = 6
    mg.best_combo = 6
    mg.power_left = 5.0
    mg.double_left = 4.0
    mg.time_left = 42.0
    mg.ball.teleport(300.0, 150.0)
    mg.ball.vy = -400.0
    mg.ball.on_ground = False
    mg.drops = [Drop(470.0, 300.0, DROP_BY_KEY["power"]),
                Drop(660.0, 190.0, DROP_BY_KEY["time"])]
    mg.pops.append(Pop(340.0, 330.0, "+15"))
    print(f"打砖块一帧：{len(mg.blocks)} 块在场，combo={mg.combo} "
          f"×{combo_mult(mg.combo)}，道具 {len(mg.drops)} 个")
    shot = mg.grab()
    mg.close()

    sheet.section(
        "⑤ 弹跳得分重做：耐久 / 裂纹 / 连击 / 道具 / 轮次",
        shot,
        "五条新增的绘制路径都在这一帧里：\n\n"
        "  · 方块上的数字 = 还剩几下\n"
        "    （只画 > 1 的，免得满屏数字）\n"
        "  · 斜裂纹 + 颜色变暗 = 损伤程度\n"
        "    （旧版一碰就碎，根本没有\n"
        "     「还差一下」这个中间状态）\n"
        "  · HUD 里的「连击 6 ×3」\n"
        "  · 下方两个色块 = 「一击必碎」\n"
        "    与「双倍得分」还剩几秒\n"
        "  · 场上的圆角方块 = 掉落道具\n\n"
        "核心规则改动在「被挡回来」：\n"
        "球顶到没敲碎的方块会被弹回，\n"
        "敲碎了才穿得过去 ——\n"
        "于是「这一跳打穿了多远」\n"
        "第一次变成了玩家能练的东西。",
        scale=0.86,
    )

    out = ROOT / "reports" / "v21_ui.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    im = sheet.finish(out)
    print(f"产出 {out}  {im.width}x{im.height}")

    # 收尾：把窗口的定时器都停掉，别让脚本挂住
    panel.close()
    dlg.close()
    pet._timer.stop()
    pet._save_timer.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
