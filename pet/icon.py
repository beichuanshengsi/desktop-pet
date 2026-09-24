"""应用图标生成。

为什么单独有这么个模块：

    图标最早和 ``pet_asset_dir()``（程序真正显示的那套贴图）**没有任何关系**：
    它由生成内置贴图的代码顺手产出。于是换了自定义素材之后，桌面上是奶油色小狗，
    托盘和游戏窗口上还是旧的那只。（那套生成器已在 2026-09-22 删除。）

    这里的规则很简单：**图标跟随贴图**。贴图从哪儿来，图标就从哪儿裁。

为什么不是整只狗缩到 64px：
    整只狗（还带板凳）缩到托盘尺寸只剩一团糊。所以只裁**头部**——
    凑近看才有辨识度。裁哪一块由 ``head`` 比例决定，不满意可以命令行改。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

from .paths import asset_dir, pet_asset_dir

# alpha 大于这个值才算"有内容"。素材压缩过，边缘常有 1~2 的噪点
ALPHA_MIN = 16

# 图标输出边长。托盘要 16/24/32，任务栏要 32/48，Alt-Tab 要 64，
# 源图取 256 让 Windows 自己在各尺寸里挑，比自己缩好
ICON_SIZE = 256

# 图标里的留白比例（相对边长）。Windows 托盘图标惯例四周留空，
# 顶到边会被任务栏的圆角切掉
ICON_PAD = 0.07

# 头部占内容高度的比例。0.46 是拿现在的素材调出来的：
# 坐着的小狗，内容高 90px，取上 41px，正好是"耳朵到下巴"
HEAD_RATIO = 0.46

ICO_SIZES = ((16, 16), (24, 24), (32, 32), (48, 48),
             (64, 64), (128, 128), (256, 256))


# ---------------------------------------------------------------- 选源

def candidate_dir() -> Path:
    """图标该从哪个目录取素材 —— 和贴图完全同源。"""
    return pet_asset_dir()


def pick_frame(explicit: Path | str | None = None, frame: int = 0,
               root: Path | None = None) -> Path:
    """挑一帧当图标的来源。

    优先 idle（待机姿势最端正、最好认），idle 没有才退而取目录里任意一张。
    """
    if explicit:
        p = Path(explicit)
        if not p.exists():
            raise FileNotFoundError(f"指定的源文件不存在：{p}")
        return p

    root = Path(root) if root else candidate_dir()
    if not root.is_dir():
        raise FileNotFoundError(f"素材目录不存在：{root}")

    for pattern in ("idle_*.png", "*.png"):
        found = _sorted_frames(root, pattern)
        if found:
            return found[frame % len(found)]
    raise FileNotFoundError(f"{root} 下没有任何 PNG 素材")


def _sorted_frames(root: Path, pattern: str) -> list[Path]:
    def index(p: Path) -> int:
        try:
            return int(p.stem.rsplit("_", 1)[-1])
        except (IndexError, ValueError):
            return 0
    return sorted(root.glob(pattern), key=index)


# ---------------------------------------------------------------- 裁头部

def content_span(im: Image.Image, y0: int, y1: int) -> tuple[int, int] | None:
    """在 [y0, y1) 这段扫描线里，找有内容的水平范围。

    逐行从两侧往中间探，命中即停 —— 比整行列表推导快得多，
    而且只关心左右边界，中间空心不影响。
    """
    # PIL 的 ``.load()`` 运行时返回的是像素访问器（支持 ``px[x, y]``），
    # 但类型桩把它标成联合类型甚至可能是 None，取值和比较都会被误报。
    # 这里显式标成 Any：运行时它就是个二维访问器，没有别的可能。
    px: Any = im.getchannel("A").load()
    left = right = None
    for y in range(y0, y1):
        for x in range(im.width):
            if px[x, y] > ALPHA_MIN:
                left = x if left is None else min(left, x)
                break
        for x in range(im.width - 1, -1, -1):
            if px[x, y] > ALPHA_MIN:
                right = x if right is None else max(right, x)
                break
    if left is None or right is None:
        return None
    return left, right


def head_box(im: Image.Image, head: float = HEAD_RATIO,
             square: str = "auto") -> tuple[int, int, int, int]:
    """算出"头部"所在的正方形裁剪框 (x0, y0, x1, y1)。

    步骤：
      1. 取内容包围盒 —— 别用整张画布，素材四周的透明边会把头缩得很小
      2. 内容顶部往下 ``head`` 比例划一条带，量这条带的水平范围（含耳朵）
      3. 取正方形，边长 = max(带宽, 带高)，避免裁出来是长条
    """
    bbox = im.getbbox()
    if not bbox:
        raise ValueError("源图整张都是透明的，没有内容可以裁")

    cx0, cy0, cx1, cy1 = bbox
    band_end = cy0 + max(1, round((cy1 - cy0) * head))
    span = content_span(im, cy0, band_end) or (cx0, cx1)

    hx0, hx1 = span
    side = max(hx1 - hx0 + 1, band_end - cy0)
    center_x = (hx0 + hx1 + 1) / 2

    if square == "top":
        x0 = round(center_x - side / 2)
        y0 = cy0
    else:                                   # auto：跟着头部块居中
        y_center = (cy0 + band_end) / 2
        x0 = round(center_x - side / 2)
        y0 = round(y_center - side / 2)

    return _clamp_square(im, x0, y0, side)


def _clamp_square(im: Image.Image, x0: int, y0: int,
                  side: int) -> tuple[int, int, int, int]:
    """框必须落在图内且保持正方形 —— 越界时平移，平移不够就整体缩小。"""
    side = int(min(side, im.width, im.height))
    x0 = max(0, min(int(x0), im.width - side))
    y0 = max(0, min(int(y0), im.height - side))
    return x0, y0, x0 + side, y0 + side


# ---------------------------------------------------------------- 生成

def build(src: Path | str, size: int = ICON_SIZE, head: float = HEAD_RATIO,
          pad: float = ICON_PAD,
          square: str = "auto") -> tuple[Image.Image, tuple[int, int, int, int]]:
    """把一帧素材裁成正方形图标，返回 (图标, 用到的裁剪框)。"""
    im = Image.open(src).convert("RGBA")
    box = head_box(im, head, square)
    crop = im.crop(box)

    inner = max(1, round(size * (1 - pad * 2)))
    crop = crop.resize((inner, inner), Image.Resampling.LANCZOS)

    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    offset = (size - inner) // 2
    canvas.alpha_composite(crop, (offset, offset))
    return canvas, box


def refresh(source: Path | str | None = None, *, frame: int = 0,
            size: int = ICON_SIZE, head: float = HEAD_RATIO,
            pad: float = ICON_PAD, square: str = "auto",
            out_dir: Path | None = None, make_ico: bool = True,
            dry_run: bool = False) -> dict:
    """从当前素材生成 ``icon.png``（以及多尺寸 ``icon.ico``）。

    返回一份报告字典，调用方（CLI / intake）自己决定怎么打印。
    """
    src = pick_frame(source, frame)
    icon, box = build(src, size, head, pad, square)

    out_dir = Path(out_dir) if out_dir else asset_dir()
    png = out_dir / "icon.png"
    ico = out_dir / "icon.ico"

    report = {
        "source": src,
        "box": box,
        "size": size,
        "png": png,
        "ico": ico if make_ico else None,
        "written": [],
        "dry_run": dry_run,
    }
    if dry_run:
        return report

    out_dir.mkdir(parents=True, exist_ok=True)
    icon.save(png)
    report["written"].append(png)

    if make_ico:
        # Windows 会按场景从 .ico 里挑尺寸（托盘 16、任务栏 32、Alt-Tab 64），
        # 比自己缩一张 256 更锐利
        icon.save(ico, sizes=list(ICO_SIZES))
        report["written"].append(ico)

    return report


def app_icon_path() -> Path:
    """程序启动时该加载哪个图标文件：.ico 优先，退回 .png。"""
    for name in ("icon.ico", "icon.png"):
        p = asset_dir() / name
        if p.exists():
            return p
    return asset_dir() / "icon.png"


def make_ico(png: Path | str, ico: Path | str | None = None) -> Path:
    """给一张现成的图标 PNG 补出多尺寸 .ico。

    用户自己设计/下载的图标通常只有一张 PNG，Windows 的托盘、任务栏、
    Alt-Tab 各要不同尺寸，缺了 .ico 就只能靠系统缩放，边角会糊。
    """
    src = Path(png)
    im = Image.open(src).convert("RGBA")
    if max(im.size) < ICON_SIZE:
        # .ico 里最大那一档要有 256，源图不够就先放大，别让 Windows 拿到空档
        im = im.resize((ICON_SIZE, ICON_SIZE), Image.Resampling.LANCZOS)

    out = Path(ico) if ico else src.with_suffix(".ico")
    im.save(out, sizes=list(ICO_SIZES))
    return out
