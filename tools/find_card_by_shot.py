#!/usr/bin/env python3
"""从一张卡册截图，反查它是卡池里的哪张卡。

**为什么需要这个**：用户在卡册里看到一张不想要的卡，通常只截个图发过来。
而卡册里未收集的卡显示的是**剪影** —— 看不出原图长什么样，一百多张里靠肉眼翻不现实。

能对上的不是像素、是**形状**，所以做法是：

1. 从截图提取剪影掩码。判据是"不够白 + 近乎无彩"，正好排掉蓝色边框和
   "未收集"三个字（它们饱和度高）。
2. 每张 thumb 的 **alpha 通道**，就是卡册画剪影时用的那份遮罩（`SourceIn` 上色）。
   两边其实是同一份东西，只是尺寸不同。
3. 各自按**图形外框**归一化到同一尺寸再比 IoU —— 用外框而不是整幅图，
   是为了消掉"缩放到多少"这个未知量。
4. 细线条（狗头线稿那类）的 IoU 天然很低、候选之间拉不开差距（实测前六名
   只差 0.005），所以补一道对形变宽容的指标：互相被**膨胀**版本覆盖的比例。

**最难的一步是第 1 步**：截图里除了剪影，还有卡片自己的边框、以及相邻卡片露出来的
一条灰边，它们的颜色和剪影**完全一样**，还更连成片。见 `silhouette_box` 的注释。
这里不指望单一算法普适，而是**并列试几种裁剪量、挑匹配分数最高的那个**上报 ——
反正匹配分数本来就要算，用它反过来选提取方案不额外花什么。

用法::

    python tools/find_card_by_shot.py 截图.png
    python tools/find_card_by_shot.py 截图1.png 截图2.png --top 8
    python tools/find_card_by_shot.py 截图.png --out reports/反查.png

只读，不改任何东西。
"""

from __future__ import annotations

import argparse
import json
from collections import deque
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageFilter

ROOT = Path(__file__).resolve().parent.parent

#: 归一化到多大的方格上比对。
N = 128

#: 剪影判定：够暗、且几乎无色偏。蓝色边框 / "未收集"文字的 max-min 在 150 以上，
#: 会被这两条一起挡掉。
DARK_ENOUGH = 244
MAX_SAT = 45

#: 找不到剪影时的报错门槛（像素数）。
MIN_QUERY = 50


def grey_mask(im: Image.Image) -> list[list[bool]]:
    """截图 → 剪影掩码（二维布尔表）。

    用 ``ImageChops`` 逐通道算而不是逐像素 ``load()``：既快得多，
    也避开了 ``PixelAccess[x, y]`` 在类型检查里"可能是 int 也可能是 tuple"的歧义
    （本项目的 ``typecheck.py`` 要求全项目 pyright 干净）。
    """
    rgb = im.convert("RGB")
    w, h = rgb.size
    r_ch, g_ch, b_ch = rgb.split()
    lo = ImageChops.darker(ImageChops.darker(r_ch, g_ch), b_ch)     # min(r, g, b)
    hi = ImageChops.lighter(ImageChops.lighter(r_ch, g_ch), b_ch)   # max(r, g, b)
    sat = ImageChops.subtract(hi, lo)                               # 色偏程度
    dark = lo.point(lambda v: 255 if v < DARK_ENOUGH else 0)
    lowsat = sat.point(lambda v: 255 if v < MAX_SAT else 0)
    m = ImageChops.multiply(dark, lowsat).tobytes()
    return [[m[y * w + x] > 0 for x in range(w)] for y in range(h)]


def drop_edge(mask: list[list[bool]], margin: int) -> list[list[bool]]:
    """清掉贴边一圈 —— 卡片边框就画在边上，剪影不会。"""
    h = len(mask)
    w = len(mask[0]) if h else 0
    out = [row[:] for row in mask]
    for y in range(h):
        for x in range(w):
            if x < margin or y < margin or x >= w - margin or y >= h - margin:
                out[y][x] = False
    return out


def silhouette_box(mask: list[list[bool]],
                   min_area: int = 30,
                   span: float = 0.75,
                   sparse_fill: float = 0.25,
                   sparse_span: float = 0.35) -> tuple[tuple[int, int, int, int] | None, int]:
    """在掩码里找剪影的 bbox，返回 ``(bbox, 剪影像素数)``。

    麻烦在于**卡片边框和相邻卡片的灰边，颜色和剪影一模一样，还更连成片**，
    直接取最大连通块会被它们抢走（实测会得到"又窄又高"的一大块，而不是狗）。
    边框还常常碎成很多小段，所以"整块横跨"这种判据也抓不全。

    两条判据一起用，命中任一即丢：

    * **横跨/纵跨**：宽或高超过全图 ``span`` —— 边框会跨，剪影不会
    * **又大又稀**：bbox 占全图 ``sparse_span`` 以上、填充率却低于 ``sparse_fill``
      —— 剪影要么密（实心），要么小（线稿），不会是"一大片空格子"
    """
    h = len(mask)
    w = len(mask[0]) if h else 0
    seen = [[False] * w for _ in range(h)]
    keep: list[tuple[int, int]] = []
    for y0 in range(h):
        for x0 in range(w):
            if not mask[y0][x0] or seen[y0][x0]:
                continue
            q = deque([(x0, y0)])
            seen[y0][x0] = True
            cells: list[tuple[int, int]] = []
            while q:
                x, y = q.popleft()
                cells.append((x, y))
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1),
                               (1, 1), (1, -1), (-1, 1), (-1, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h and mask[ny][nx] and not seen[ny][nx]:
                        seen[ny][nx] = True
                        q.append((nx, ny))
            if len(cells) < min_area:
                continue
            xs = [c[0] for c in cells]
            ys = [c[1] for c in cells]
            bw, bh = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
            if bw > span * w or bh > span * h:
                continue
            if (bw * bh) > sparse_span * w * h and len(cells) / (bw * bh) < sparse_fill:
                continue
            keep.extend(cells)
    if not keep:                              # 判据都没留下东西，就退回全部像素
        keep = [(x, y) for y in range(h) for x in range(w) if mask[y][x]]
    if not keep:
        return None, 0
    kx = [c[0] for c in keep]
    ky = [c[1] for c in keep]
    return (min(kx), min(ky), max(kx) + 1, max(ky) + 1), len(keep)


def normalise(gray: Image.Image, box: tuple[int, int, int, int]) -> set[tuple[int, int]]:
    """裁到 box、等比放到 N×N，返回前景点集。"""
    x0, y0, x1, y1 = box
    bw, bh = max(1, x1 - x0), max(1, y1 - y0)
    sc = min(N / bw, N / bh)
    tw, th = max(1, int(bw * sc)), max(1, int(bh * sc))
    canvas = Image.new("L", (N, N), 0)
    canvas.paste(gray.crop(box).resize((tw, th), Image.Resampling.LANCZOS),
                 ((N - tw) // 2, (N - th) // 2))
    data = canvas.tobytes()
    return {(x, y) for y in range(N) for x in range(N) if data[y * N + x] > 127}


def to_img(points: set[tuple[int, int]]) -> Image.Image:
    img = Image.new("L", (N, N), 0)
    p = img.load()
    assert p is not None
    for (x, y) in points:
        p[x, y] = 255
    return img


def as_set(img: Image.Image) -> set[tuple[int, int]]:
    if not isinstance(img, Image.Image):
        raise TypeError(f"as_set 期望 PIL 图像，实际收到 {type(img).__name__}：{img!r:.120}")
    data = img.convert("L").tobytes()
    return {(x, y) for y in range(N) for x in range(N) if data[y * N + x] > 127}


def iou(a: set[tuple[int, int]], b: set[tuple[int, int]]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def tolerant(a: set[tuple[int, int]], b: set[tuple[int, int]], radius: int = 4) -> float:
    """细线条友好：互相有多少点落在对方附近，取小的一侧。

    IoU 对"线宽差一个像素"都敏感，狗头那类线稿的 IoU 会全挤在 0.2 附近分不出来。
    """
    dil_a = as_set(to_img(a).filter(ImageFilter.MaxFilter(2 * radius + 1)))
    dil_b = as_set(to_img(b).filter(ImageFilter.MaxFilter(2 * radius + 1)))
    cover_a = len(a & dil_b) / len(a) if a else 0.0
    cover_b = len(b & dil_a) / len(b) if b else 0.0
    return min(cover_a, cover_b)


def drop_below(mask: list[list[bool]], frac: float) -> list[list[bool]]:
    """只保留上面 ``frac`` 比例的高度。

    卡片底下那行"未收集"是蓝字，但**字的抗锯齿边缘是低饱和灰**，和剪影同色，
    于是会混进掩码、把 bbox 一路撑到卡片底部（实测把 78×46 的狗头撑成 80×97）。
    剪影不会长在卡片最下沿，所以直接用"切掉下半部分"这个粗暴办法。
    """
    h = len(mask)
    cut = int(h * frac)
    return [row[:] if y < cut else [False] * len(row) for y, row in enumerate(mask)]


def variants_of(shot: Path) -> list[tuple[str, set[tuple[int, int]], tuple[int, int, int, int], int]]:
    """一张截图 → 几种可能剪影，供上层挑匹配最好的那个。

    单靠一种裁剪方式不行：裁少了边框混进来（实测会量出 110×138 的"剪影"），
    裁多了会把贴边的剪影切掉一块，不切又会被"未收集"那行字撑高。
    所以并列给几个，让匹配分数说话。
    """
    im = Image.open(shot)
    base = grey_mask(im)
    out: list[tuple[str, set[tuple[int, int]], tuple[int, int, int, int], int]] = []
    for margin, below in ((25, 1.0), (25, 0.72), (12, 1.0), (0, 1.0)):
        mask = drop_edge(base, margin) if margin else [r[:] for r in base]
        if below < 1.0:
            mask = drop_below(mask, below)
        box, area = silhouette_box(mask)
        if box is None or area < MIN_QUERY:
            continue
        x0, y0, x1, y1 = box
        only = Image.new("L", im.size, 0)
        p = only.load()
        assert p is not None
        for y in range(y0, y1):
            for x in range(x0, x1):
                if mask[y][x]:
                    p[x, y] = 255
        label = f"裁边 {margin}px" + (f"、只取上方 {int(below * 100)}%" if below < 1 else "")
        out.append((label, normalise(only, box), box, area))
    return out


def load_pool() -> list[dict[str, str]]:
    data = json.loads((ROOT / "assets/cards/cards.json").read_text(encoding="utf-8"))
    cards = data["cards"] if isinstance(data, dict) else data
    return list(cards)


def main() -> int:
    ap = argparse.ArgumentParser(description="从卡册截图反查是哪张卡")
    ap.add_argument("shots", nargs="+", type=Path, help="卡册截图（可多张）")
    ap.add_argument("--top", type=int, default=6, help="每张截图列出前几名")
    ap.add_argument("--out", type=Path, default=None, help="把对比图存到这里")
    args = ap.parse_args()

    cards = load_pool()
    thumbs: list[tuple[dict[str, str], set[tuple[int, int]]]] = []
    for c in cards:
        alpha = (Image.open(ROOT / "assets/cards/thumb" / (c["id"] + ".png"))
                 .convert("RGBA").getchannel("A"))
        box = alpha.getbbox()
        if box is None:
            continue
        thumbs.append((c, normalise(alpha, box)))
    print(f"卡池 {len(cards)} 张，可比对 {len(thumbs)} 张\n")

    tiles: list[tuple[str, set[tuple[int, int]]]] = []
    for shot in args.shots:
        variants = variants_of(shot)
        if not variants:
            print(f"[{shot.name}] 没找到剪影 —— 确认这是卡册里某一格的截图。\n")
            continue

        best: tuple[float, str, tuple[int, int, int, int], int,
                    list[tuple[float, float, dict[str, str]]]] | None = None
        for label, q, box, area in variants:
            ranked = sorted(((iou(q, cand), tolerant(q, cand), c) for c, cand in thumbs),
                            key=lambda r: (r[0] + r[1]) / 2, reverse=True)
            score = (ranked[0][0] + ranked[0][1]) / 2
            if best is None or score > best[0]:
                best = (score, label, box, area, ranked)

        assert best is not None
        _, label, box, area, ranked = best
        bw, bh = box[2] - box[0], box[3] - box[1]
        print(f"[{shot.name}]  提取方案：{label}  剪影 {bw}×{bh}  宽高比 {bw / bh:.3f}  "
              f"{area} 像素")
        for i, (s_iou, s_tol, c) in enumerate(ranked[: args.top], 1):
            mark = "   ← 最可能" if i == 1 else ""
            print(f"   {i}. {c['id']}  {c['tier']:<4}  IoU={s_iou:.3f}  宽容={s_tol:.3f}{mark}")
            print(f"      {c['file']}")
        if len(ranked) > 1:
            gap = (ranked[0][0] + ranked[0][1]) / 2 - (ranked[1][0] + ranked[1][1]) / 2
            hint = "可信" if gap > 0.06 else "差距很小，靠分数选不出来，请看对比图"
            print(f"   与第二名的差距：{gap:.3f}  ⇒ {hint}")
        print()

        by_id = {cc["id"]: cd for cc, cd in thumbs}
        tiles.append((f"{shot.stem[-9:]}", next(cd for cc, cd in thumbs
                                                if cc["id"] == ranked[0][2]["id"])))
        for _, _, c in ranked[: args.top]:
            tiles.append((c["id"], by_id[c["id"]]))

    if args.out and tiles:
        cols = args.top + 1
        cell, pad, lab = 96, 8, 16
        rows = len(args.shots)
        sheet = Image.new("RGB", (cols * (cell + pad) + pad, rows * (cell + pad + lab) + pad),
                          (246, 248, 250))
        d = ImageDraw.Draw(sheet)
        try:
            font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 12)
        except OSError:
            font = ImageFont.load_default()
        for i, (label, pts) in enumerate(tiles):
            r, cidx = divmod(i, cols)
            x = pad + cidx * (cell + pad)
            y = pad + r * (cell + pad + lab)
            up = Image.new("RGB", (cell, cell), (255, 255, 255))
            up.paste(to_img(pts).resize((cell, cell), Image.Resampling.NEAREST).convert("RGB"),
                     (0, 0))
            sheet.paste(up, (x, y))
            d.text((x + 2, y + cell + 2), label, fill=(60, 60, 65), font=font)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(args.out)
        print(f"对比图已存：{args.out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
