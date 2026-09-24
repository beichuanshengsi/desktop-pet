"""素材预处理：把拿到的动图/表情包加工成桌宠能直接吃的动作帧。

"找到素材"和"素材可用"之间隔着三步，这个脚本就是干这三步的：

1. **拆帧** —— GIF / 精灵表 / 图片序列 -> 一帧一张 PNG
2. **去底** —— 表情包通常是白底或纯色底且不带透明通道，直接用会在桌面上
   显示出一个方块。这里用色键抠图把底色刷成透明。
3. **规范尺寸与命名** —— 统一缩放到 128，并输出成 ``<状态>_<序号>.png``，
   让 ``pet.assets.AssetBank`` 可以直接按名字找帧。

用法示例
--------
    # 表情包是白底的 GIF，当作待机动作
    python tools/prep_sticker.py 表情.gif --state idle --auto-key

    # 一张 4x4 的精灵表，每格是一个动作帧
    python tools/prep_sticker.py sheet.png --sheet --cols 4 --rows 4 --state walk

    # 已经抠好的透明 PNG 序列，放在一个文件夹里
    python tools/prep_sticker.py ./frames --state drag

    # 小游戏素材：输出前缀决定它是哪一套（catcher / puppy / bomb）
    python tools/prep_sticker.py 小黄狗.gif --state catcher --game --auto-key --anchor center
    python tools/prep_sticker.py 小白狗.gif --state puppy   --game --auto-key --anchor center
    python tools/prep_sticker.py 炸弹.gif   --state bomb    --game --auto-key --anchor center

输出默认写到 ``assets/pet/``；``--game`` 写到 ``assets/game/``（小游戏用）；
也可以写进 ``%APPDATA%/DesktopPet/custom_pet/`` 来覆盖内置贴图（``--custom``）。
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Any, cast

from PIL import Image, ImageSequence

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pet.behavior import KEYS as _STATE_KEYS       # noqa: E402
from pet.paths import asset_dir, user_asset_dir   # noqa: E402

#: 合法动作名。**从行为状态机派生**（``pet/behavior.py`` 的 ``State``）——
#: 以前这里另抄一份，加一个动作就得记着改三处（behavior / assets / 这里），
#: 漏掉的那次表现为"图都切好了，落到目录里程序却不认"。
#: 仍可用 ``--state`` 传自定义前缀（多于状态机的前缀照样能落盘）。
VALID_STATES = _STATE_KEYS

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".tga"}


# ---------------------------------------------------------------- 读帧

def load_frames(src: Path, *, sheet: bool = False,
                cols: int = 1, rows: int = 1) -> list[Image.Image]:
    """把各种输入统一读成 RGBA 帧列表。"""
    if src.is_dir():
        frames = []
        for path in sorted(p for p in src.iterdir()
                           if p.suffix.lower() in IMAGE_EXT):
            with Image.open(path) as im:
                frames.extend(_expand(im, sheet, cols, rows))
        if not frames:
            raise SystemExit(f"目录里没有可用图片：{src}")
        return frames

    if not src.exists():
        raise SystemExit(f"找不到输入文件：{src}")

    with Image.open(src) as im:
        return _expand(im, sheet, cols, rows)


def _expand(im: Image.Image, sheet: bool, cols: int, rows: int) -> list[Image.Image]:
    # 注意顺序：必须先判断 is_animated，再 convert。
    # Pillow 的 convert() 会返回一个全新的 Image，把 GIF 插件挂在实例上的
    # is_animated / n_frames 一起丢掉 —— 先 convert 的话动图会静默退化成单帧。
    if sheet:
        return _split_sheet(im.convert("RGBA"), cols, rows)
    if getattr(im, "is_animated", False):
        return [f.convert("RGBA") for f in ImageSequence.Iterator(im)]
    return [im.convert("RGBA")]


def _split_sheet(im: Image.Image, cols: int, rows: int) -> list[Image.Image]:
    """按网格切分精灵表，逐行从左到右。"""
    cols = max(1, cols)
    rows = max(1, rows)
    cw, ch = im.width // cols, im.height // rows
    out = []
    for r in range(rows):
        for c in range(cols):
            out.append(im.crop((c * cw, r * ch, (c + 1) * cw, (r + 1) * ch)))
    return out


# ---------------------------------------------------------------- 去底

def guess_key_color(im: Image.Image) -> tuple[int, int, int]:
    """取四角像素里出现最多的那个颜色，作为键色。"""
    w, h = im.size
    probe = max(1, min(w, h) // 40)
    corners: list[Any] = []
    for box in ((0, 0, probe, probe), (w - probe, 0, w, probe),
                (0, h - probe, probe, h), (w - probe, h - probe, w, h)):
        corners.extend(cast("list[tuple[int, int, int]]",
                            im.crop(box).getdata()))
    rgb = Counter((p[0], p[1], p[2]) for p in corners)
    return rgb.most_common(1)[0][0]


def key_out(im: Image.Image, key: tuple[int, int, int],
            tol: int = 24) -> Image.Image:
    """色键抠图：接近键色的像素透明化，边缘给一段渐变避免硬锯齿。"""
    key = (int(key[0]), int(key[1]), int(key[2]))
    out = im.convert("RGBA")
    # PIL 的 .load() 运行时是像素访问器（支持 px[x, y] 读写），类型桩把它标成
    # 可能为 None 的联合类型，取值/赋值/解包全会被误报。显式标 Any。
    px: Any = out.load()
    soft = max(1, tol)
    for y in range(out.height):
        for x in range(out.width):
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            # 单通道最大差值，比欧氏距离更能容忍底色不均
            dist = max(abs(r - key[0]), abs(g - key[1]), abs(b - key[2]))
            if dist <= tol:
                px[x, y] = (r, g, b, 0)
            elif dist <= tol + soft:
                ratio = (dist - tol) / soft
                px[x, y] = (r, g, b, int(a * ratio))
    return out


# ---------------------------------------------------------------- 归一

def normalize(im: Image.Image, size: int, *, trim: bool = True,
              anchor: str = "bottom", pad: int = 6,
              motion: str = "flatten") -> Image.Image:
    """单张图的归一化，等价于只含一帧的 ``normalize_series``。"""
    return normalize_series([im], size, trim=trim, anchor=anchor, pad=pad,
                            motion=motion)[0]


def normalize_series(frames: list[Image.Image], size: int, *, trim: bool = True,
                     anchor: str = "bottom", pad: int = 6,
                     scale: float | None = None,
                     motion: str = "flatten") -> list[Image.Image]:
    """整组帧统一缩放后再逐帧定位。

    为什么不逐帧独立缩放：真实表情包的包围盒每帧都在变（这一帧手臂张开、
    下一帧收拢），逐帧"缩放到刚好填满画布"会让角色在播放时**忽大忽小**。
    这里改成先用整组帧的并集包围盒算一个统一缩放比，所有帧共用。

    ``scale`` 可以外部指定。多套素材（idle/walk/drag…）来自同一角色时，
    应该由调用方算一个**跨素材共用**的缩放比传进来 —— 否则带道具的那套
    （比如狗坐在长凳上）并集更大、被缩得更小，切换动作时角色会突然变大。

    ``motion`` 决定"素材自带的位移"怎么处理，这是两种真实需求：

    - ``"flatten"``（默认）—— 每帧按自身包围盒居中 + 底边落地。素材里的平移
      被抹平成原地动作，位移完全交给窗口（走路移动窗口、跳跃抬升窗口），
      两处位移不会叠加。适合"原地做动作"的素材：坐在凳子上晃脚、躺着打滚。
    - ``"keep"`` —— 所有帧共用一套并集坐标系，只把每帧水平居中，
      **垂直位移原样保留**。适合自带起伏的素材：蹦蹦跳跳的走路、发抖。
      用 flatten 处理这类素材会把腾空压成"脚踩地原地伸缩"，弹跳感全丢。
    """
    if not frames:
        return []

    boxes = []
    for f in frames:
        box = f.getbbox() if trim else (0, 0, f.width, f.height)
        boxes.append(box or (0, 0, 1, 1))

    union_w = max(b[2] - b[0] for b in boxes)
    union_h = max(b[3] - b[1] for b in boxes)
    avail = max(1, size - pad * 2)
    if scale is None:
        scale = min(avail / max(1, union_w), avail / max(1, union_h))

    # keep 模式：并集坐标系（含各帧之间的相对位移），y 偏移按并集算。
    # 先给默认值 —— 下面的赋值和使用分处两个 `if motion == "keep"`，类型检查器
    # 没法把两处条件关联起来；而且这确实是隐患：万一以后有人在中间改动了
    # motion，取值那次就会读到没赋过的名字（UnboundLocalError）。
    uy0, base = 0, 0
    if motion == "keep":
        uy0 = min(b[1] for b in boxes)
        span = round((max(b[3] for b in boxes) - uy0) * scale)
        if anchor == "bottom":
            base = size - span - pad
        elif anchor == "top":
            base = pad
        else:
            base = (size - span) // 2
        base = max(0, min(base, size - span))

    out = []
    for f, box in zip(frames, boxes):
        crop = f.crop(box)
        w = max(1, round(crop.width * scale))
        h = max(1, round(crop.height * scale))
        crop = crop.resize((w, h), Image.Resampling.LANCZOS)

        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        x = (size - w) // 2
        if motion == "keep":
            y = base + round((box[1] - uy0) * scale)
        elif anchor == "bottom":
            y = size - h - pad
        elif anchor == "top":
            y = pad
        else:
            y = (size - h) // 2
        canvas.alpha_composite(crop, (max(0, x), max(0, y)))
        out.append(canvas)
    return out


def fit_scale(frames: list[Image.Image], size: int, *, trim: bool = True,
              pad: int = 6) -> float:
    """算出"这组帧刚好放进画布"的缩放比，供跨素材取最小值用。"""
    if not frames:
        return 1.0
    boxes = []
    for f in frames:
        box = f.getbbox() if trim else (0, 0, f.width, f.height)
        boxes.append(box or (0, 0, 1, 1))
    union_w = max(b[2] - b[0] for b in boxes)
    union_h = max(b[3] - b[1] for b in boxes)
    avail = max(1, size - pad * 2)
    return min(avail / max(1, union_w), avail / max(1, union_h))


# ---------------------------------------------------------------- 主流程

def parse_key(value: str) -> tuple[int, int, int]:
    v = value.strip().lstrip("#")
    if len(v) == 3:
        v = "".join(ch * 2 for ch in v)
    if len(v) != 6:
        raise argparse.ArgumentTypeError("键色要写成 #RRGGBB 或 RRGGBB")
    return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))       # type: ignore[return-value]


def _default_out(args) -> Path:
    """按 --game / --custom 组合决定默认输出目录。

    走 ``pet.paths`` 的登记表，不再手写 ``data_dir()/"custom_pet"`` ——
    用户目录名（custom_pet / game）以前在两个地方各写一份，改一处必漏一处。
    """
    name = "game" if args.game else "pet"
    if args.custom:
        return user_asset_dir(name) or asset_dir(name)
    return asset_dir(name)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="把 GIF / 精灵表 / 图片序列加工成桌宠动作帧",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", help="输入：.gif、单张图、或图片目录")
    ap.add_argument("--state", default="idle",
                    help=f"输出到哪个动作，如 {'/'.join(VALID_STATES)}，也可自定义")
    ap.add_argument("--out", default=None,
                    help="输出目录，默认 assets/pet（--game 时是 assets/game）")
    ap.add_argument("--game", action="store_true",
                    help="输出到小游戏素材目录（assets/game）。配合 --state 起名字："
                         "catcher（小黄狗）/ puppy（小白狗）/ bomb（炸弹）")
    ap.add_argument("--custom", action="store_true",
                    help="输出到用户数据目录（pet 走 custom_pet，game 走 game），会覆盖内置素材")
    ap.add_argument("--size", type=int, default=128, help="输出边长，默认 128")
    ap.add_argument("--scale", type=float, default=None,
                    help="直接钉死缩放比，默认按「刚好放进画布」自动算。"
                         "同一个角色的几套素材分批入库时用它对齐大小 —— "
                         "带道具/装饰的那套并集更大，自动算会被缩得更小，"
                         "切换动作时角色会突然变大变小")
    ap.add_argument("--sheet", action="store_true", help="输入按精灵表处理")
    ap.add_argument("--cols", type=int, default=1, help="精灵表列数")
    ap.add_argument("--rows", type=int, default=1, help="精灵表行数")
    ap.add_argument("--auto-key", action="store_true", help="自动探测底色并抠图")
    ap.add_argument("--key-color", type=parse_key, default=None,
                    help="手动指定底色，如 #FFFFFF")
    ap.add_argument("--tolerance", type=int, default=24, help="抠图容差，默认 24")
    ap.add_argument("--no-trim", action="store_true", help="不裁透明边")
    ap.add_argument("--anchor", choices=("bottom", "center", "top"),
                    default="bottom", help="归一化锚点，默认 bottom")
    ap.add_argument("--pad", type=int, default=6,
                    help="锚点为 bottom/top 时距边框的空隙像素，默认 6。"
                         "想让自定义帧和内置帧站在同一条地平线上就给 8~12")
    ap.add_argument("--motion", choices=("flatten", "keep"), default="flatten",
                    help="素材自带的位移怎么处理：flatten（默认）每帧底边落地，"
                         "位移交给窗口；keep 保留垂直位移，适合自带弹跳的走路/"
                         "发抖素材，否则会被压成原地伸缩")
    ap.add_argument("--keep", type=int, default=0, help="最多保留多少帧，0 表示全部")

    args = ap.parse_args(argv)

    src = Path(args.source).expanduser()
    frames = load_frames(src, sheet=args.sheet, cols=args.cols, rows=args.rows)

    if args.keep and len(frames) > args.keep:
        step = len(frames) / args.keep
        frames = [frames[int(i * step)] for i in range(args.keep)]

    out_dir = Path(args.out) if args.out else _default_out(args)
    out_dir.mkdir(parents=True, exist_ok=True)

    key = args.key_color
    if args.auto_key and key is None:
        key = guess_key_color(frames[0])
    if key is not None:
        frames = [key_out(f, key, args.tolerance) for f in frames]

    # 先把自动缩放比算出来打印：多批素材要大小一致时，靠这个数字互相校准，
    # 否则只能"入库 -> 量出来 -> 再入库"来回试。
    _boxes = [f.getbbox() or (0, 0, 1, 1) for f in frames]
    _uw = max(b[2] - b[0] for b in _boxes)
    _uh = max(b[3] - b[1] for b in _boxes)
    _avail = max(1, args.size - args.pad * 2)
    _auto = min(_avail / max(1, _uw), _avail / max(1, _uh))

    frames = normalize_series(frames, args.size, trim=not args.no_trim,
                              anchor=args.anchor, pad=args.pad,
                              scale=args.scale, motion=args.motion)

    written = []
    for i, frame in enumerate(frames):
        path = out_dir / f"{args.state}_{i:02d}.png"
        frame.save(path)
        written.append(path)

    print(f"[prep] 输入      : {src}")
    print(f"[prep] 读出帧数  : {len(frames)}")
    if key is not None:
        print(f"[prep] 抠图键色  : #{key[0]:02X}{key[1]:02X}{key[2]:02X}  容差 {args.tolerance}")
    else:
        print("[prep] 抠图      : 未启用（若贴图带白底，用 --auto-key 或 --key-color）")
    print(f"[prep] 输出目录  : {out_dir}")
    print(f"[prep] 缩放比    : "
          f"{args.scale if args.scale is not None else _auto:.4f}"
          f"{'（--scale 指定）' if args.scale is not None else '（自动：刚好放进画布）'}"
          f"   内容并集 {_uw}x{_uh}")
    print(f"[prep] 写出文件  : {written[0].name} … {written[-1].name}（共 {len(written)}）")
    print(f"[prep] 提示：尺寸不用和内置帧一致（程序会按显示大小缩放），"
          f"但脚底要落在同一条地平线上——不同来源的帧拼一起时用 --pad 对齐。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
