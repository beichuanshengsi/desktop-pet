"""把背景大图裁成游戏窗口尺寸，让图里的地平线正好落在游戏的 GROUND_Y 上。

直接 ``cover`` 缩放会出问题：背景图是 2848x1600 的竖版插画，游戏窗口是
780x580。按"填满窗口"缩放出来的地面会落在 440~475 的位置，而游戏里角色
站的地面在 534 —— 差几十像素，狗看上去是悬空站着的。

所以这里按 **地平线对齐** 定缩放比：

    scale = GROUND_Y / (源图高度 x ground)

再水平居中裁到窗口宽、从顶部取窗口高。``ground`` 是地平线在源图里的纵向
位置（0~1），需要按每张图目测给定 —— 程序推不出来：天空顶部也是"亮且平"
的色块，自动检测会误判成地面。

用法::

    # 看看这张图的默认裁法对不对（先渲染出来再确认）
    python tools/prep_bg.py 背景.png --name bg_bounce --ground 0.87 --preview

    # 直接落到游戏素材目录
    python tools/prep_bg.py 背景.png --name bg_catch --ground 0.78
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: 文件名命中这些词就自动判断成哪个游戏的背景
NAME_HINTS = (
    ("bg_bounce", ("bounce", "弹跳", "砖块", "舞台", "粉")),
    ("bg_catch", ("catch", "接", "草地", "蓝天", "天空", "云")),
)

DEFAULT_GROUND = 0.80


def window_size() -> tuple[int, int, int]:
    """从 game.common 取窗口尺寸与地面位置，避免两处写死不一致。"""
    from game.common import GROUND_Y, H, W
    return W, H, GROUND_Y


def guess_name(stem: str) -> str | None:
    low = stem.lower()
    for name, keywords in NAME_HINTS:
        if any(k in stem or k in low for k in keywords):
            return name
    return None


def crop_for_game(src: str | Path, dst: str | Path, *,
                  ground: float = DEFAULT_GROUND,
                  focus: float = 0.5,
                  size: tuple[int, int, int] | None = None) -> Path:
    """裁剪并保存。``ground`` 是地平线在源图里的纵向比例。

    ``focus`` 控制水平取景：0 看左边、1 看右边、0.5 居中。
    """
    w, h, ground_y = size or window_size()
    im = Image.open(src).convert("RGB")

    if (im.width, im.height) == (w, h):
        im.save(dst)                      # 已经是窗口尺寸，别再缩一遍
        return Path(dst)

    k = ground_y / max(1e-6, im.height * ground)
    nw, nh = max(1, round(im.width * k)), max(1, round(im.height * k))
    im = im.resize((nw, nh), Image.Resampling.LANCZOS)

    # 水平取景
    x0 = round((nw - w) * focus)
    x0 = max(0, min(x0, max(0, nw - w)))
    # 垂直：让地平线落在 ground_y
    y0 = round(im.height * ground * 1.0) - ground_y
    y0 = max(0, min(y0, max(0, nh - h))) if nh > h else 0

    canvas = Image.new("RGB", (w, h), (255, 255, 255))
    canvas.paste(im.crop((x0, y0, x0 + w, y0 + h)), (0, 0))
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dst)
    return Path(dst)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", help="背景大图")
    ap.add_argument("--name", default=None,
                    help="bg_bounce / bg_catch；不给就按文件名里的词猜")
    ap.add_argument("--ground", type=float, default=DEFAULT_GROUND,
                    help=f"地平线在源图里的纵向位置 0~1，默认 {DEFAULT_GROUND}")
    ap.add_argument("--focus", type=float, default=0.5,
                    help="水平取景 0=最左 1=最右，默认 0.5 居中")
    ap.add_argument("--out", default=None, help="输出文件，默认 assets/game/<name>.png")
    ap.add_argument("--preview", action="store_true",
                    help="输出到 reports/_tmp/ 看效果，不碰游戏素材目录")
    args = ap.parse_args()

    src = Path(args.source)
    if not src.exists():
        print(f"找不到 {src}")
        return 1

    name = args.name or guess_name(src.stem)
    if not name:
        print("判断不出这是哪个游戏的背景，用 --name bg_bounce 或 bg_catch 指定")
        return 1

    if args.out:
        out = Path(args.out)
    elif args.preview:
        out = ROOT / "reports" / "_tmp" / f"{name}_preview.png"
    else:
        from pet.paths import asset_dir
        out = asset_dir() / "game" / f"{name}.png"

    w, h, gy = window_size()
    crop_for_game(src, out, ground=args.ground, focus=args.focus, size=(w, h, gy))

    im = Image.open(out)
    print(f"[bg] {src.name}  ->  {out}")
    print(f"[bg] 地平线 ground={args.ground:.3f}  取景 focus={args.focus:.2f}"
          f"  输出 {im.width}x{im.height}（窗口 {w}x{h}，地面 y={gy}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
