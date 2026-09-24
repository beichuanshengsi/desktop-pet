"""生成应用图标（托盘 / 小游戏窗口 / 任务栏共用一个）。

    python tools/make_icon.py                 # 跟随当前素材刷新图标
    python tools/make_icon.py --preview       # 顺便出各尺寸预览图
    python tools/make_icon.py --dry-run       # 只看会裁哪一块，不写文件
    python tools/make_icon.py --head 0.40     # 头部比例调小一点
    python tools/make_icon.py --from D:/狗.png --frame 2

素材从 ``pet_asset_dir()`` 取 —— 和程序显示的贴图同源，
所以「换了宠物」和「换了图标」不会再脱节。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pet import icon as iconlib                                   # noqa: E402
from pet.paths import asset_dir                                  # noqa: E402

# Pillow 自带的位图字体没有中文，标题会画成一排方框。
# 从系统字体里挑一个，挑不到就退回默认（中文变方框，但不至于崩）。
FONT_CANDIDATES = (
    r"C:\Windows\Fonts\msyh.ttc",           # 微软雅黑
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf",         # 黑体
    r"C:\Windows\Fonts\Deng.ttf",           # 等线
    r"C:\Windows\Fonts\simsun.ttc",         # 宋体
)


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """挑一个系统里真有的中文字体。

    返回类型写全两个分支：``truetype()`` 给的是 ``FreeTypeFont``，
    ``load_default()`` 给的是基类 ``ImageFont``，只写基类会被判成类型不兼容
    （明明更宽的那个才是子类）。
    """
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def make_preview(png: Path, out: Path) -> Path:
    """把图标在浅底/深底上按真实尺寸排一遍。

    图标唯一的验收标准是"16px 下还认得出是谁" —— 而 16px 的样子
    在大图上完全看不出来，所以必须按原尺寸看。
    """
    sizes = [16, 24, 32, 48, 64, 128]
    src = Image.open(png).convert("RGBA")
    pad, gap, title_h = 18, 16, 30
    row_w = sum(sizes) + gap * (len(sizes) - 1) + pad * 2
    row_h = max(sizes) + pad * 2 + title_h + 18
    font = load_font(13)
    small = load_font(11)

    sheet = Image.new("RGB", (row_w, row_h * 2), (246, 247, 250))
    draw = ImageDraw.Draw(sheet)
    draw.rectangle([0, row_h, row_w, row_h * 2], fill=(30, 32, 36))

    for r, (bg, fg, note) in enumerate((
            ((246, 247, 250), (56, 60, 70), "浅色托盘"),
            ((30, 32, 36), (214, 218, 226), "深色托盘"))):
        base = row_h * r
        draw.rectangle([0, base, row_w, base + row_h], fill=bg)
        draw.text((pad, base + 8), f"{note} —— 16px 下还要认得出是谁",
                  fill=fg, font=font)

        y_top = base + title_h + 8
        x = pad
        for s in sizes:
            thumb = src.resize((s, s), Image.Resampling.LANCZOS)
            y = y_top + (max(sizes) - s) // 2
            sheet.paste(thumb, (x, y), thumb)
            draw.text((x, base + row_h - 20), f"{s}px", fill=fg, font=small)
            x += s + gap

    sheet.save(out)
    return out


def _rel(p: Path) -> Path | str:
    """尽量显示相对路径；目标在项目外（--out 指定到别处）时显示绝对路径。

    Path.relative_to 在不是子路径时是抛异常而不是返回原值 —— 不包一层的话
    "--out 到项目外" 会在打印日志这一步崩掉，明明文件已经写好了。
    """
    try:
        return Path(p).relative_to(ROOT)
    except ValueError:
        return p


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="生成桌宠应用图标")
    ap.add_argument("--from", dest="source", default=None,
                    help="指定源图，默认从当前素材目录里挑")
    ap.add_argument("--frame", type=int, default=0, help="用第几帧，默认 0")
    ap.add_argument("--head", type=float, default=iconlib.HEAD_RATIO,
                    help=f"头部占内容高度的比例，默认 {iconlib.HEAD_RATIO}")
    ap.add_argument("--pad", type=float, default=iconlib.ICON_PAD,
                    help=f"图标四周留白比例，默认 {iconlib.ICON_PAD}")
    ap.add_argument("--square", choices=("auto", "top"), default="auto",
                    help="正方形取法：auto 跟着头部居中，top 头顶对齐上沿")
    ap.add_argument("--size", type=int, default=iconlib.ICON_SIZE,
                    help=f"输出边长，默认 {iconlib.ICON_SIZE}")
    ap.add_argument("--out", default=None, help="输出目录，默认 assets/")
    ap.add_argument("--no-ico", action="store_true", help="不生成多尺寸 .ico")
    ap.add_argument("--dry-run", action="store_true", help="只看方案，不写文件")
    ap.add_argument("--preview", action="store_true",
                    help="顺便生成 reports/icon_preview.png")
    args = ap.parse_args(argv)

    try:
        rep = iconlib.refresh(
            source=args.source, frame=args.frame, size=args.size,
            head=args.head, pad=args.pad, square=args.square,
            out_dir=Path(args.out) if args.out else None,
            make_ico=not args.no_ico, dry_run=args.dry_run)
    except (FileNotFoundError, ValueError) as exc:
        print(f"[icon] 失败：{exc}")
        return 1

    src = rep["source"]
    x0, y0, x1, y1 = rep["box"]
    print(f"[icon] 源图   {_rel(src)}")
    print(f"[icon] 裁剪   x {x0}~{x1}  y {y0}~{y1}  ({x1 - x0}px 见方)")
    print(f"[icon] 依据   顶部 {args.head:.0%} 内容为头部，四周留白 {args.pad:.0%}")

    if rep["dry_run"]:
        print("[icon] --dry-run，没有写任何文件")
        return 0

    for p in rep["written"]:
        size_kb = p.stat().st_size / 1024
        print(f"[icon] 写出   {_rel(p)}  ({size_kb:.1f} KB)")
    if rep["ico"] is None:
        print("[icon] 未生成 .ico，Windows 托盘会自己缩 .png（略糊）")

    if args.preview:
        out = make_preview(rep["png"], ROOT / "reports" / "icon_preview.png")
        print(f"[icon] 预览   {_rel(out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
