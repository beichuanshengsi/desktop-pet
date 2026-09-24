"""素材库体检 + 联系表：一次下载几十上百个 GIF 时，用它快速过一遍再挑。

**为什么需要这个工具**：素材包动辄上百个文件，一个个打开看不现实；
而"只看单帧"又判断不出动作类型（走路要看有没有横向位移，不是看某一帧像不像）。
所以把它拆成三步，都用同一次扫描的数据：

1. **体检**（`*_audit.txt`）—— 每张的帧数/尺寸/背景能不能抠/主体是米黄狗还是白狗。
   *带实景背景的直接排除*：那种抠不干净，当贴图会带一块照片背景。
2. **联系表**（`*_sheet.png`）—— 编号缩略图拼成一张大图，翻一张图就等于翻完整批，
   靠眼睛挑出"看起来像"的候选。**编号是后面所有命令的索引。**
3. **运动特征**（`*_motion.txt`）—— 各帧质心的横向/纵向位移、底边与高度变化。
   用来把"可能有走路"的候选筛出来（横向位移大 + 底边几乎不变），
   缩小到十来个再逐个看动画（`--strip`）。

最后用 `--strip` 把候选的**动画过程**渲染成帧条 —— 判断动作类型只能靠这一步，
指标只负责把范围缩小。

用法::

    # 第一步：全量扫描，出联系表 + 体检表 + 运动特征
    python tools/review_materials.py assets/raw/_library/0921_1530_线条小狗GIF

    # 第二步：只看米黄狗、跳过带实景底/水印的
    python tools/review_materials.py <目录> --clean

    # 第三步：把候选的动画过程渲染成帧条（编号来自联系表）
    python tools/review_materials.py <目录> --strip 26 93 38 --strip-frames 8

产物默认写到 ``reports/materials/``（已 gitignore）。

**不用 Qt** —— 纯 Pillow，几十毫秒一张，也不会因为离屏平台缺字体而崩。
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw                                # noqa: E402

#: 线条小狗那套的米黄身体色。换角色时改这里（或者干脆靠 --clean 只按背景筛）。
BODY_REF = (233, 206, 168)
BODY_TOL = 34

IMAGE_SUFFIXES = (".gif", ".png", ".webp", ".apng", ".jpg", ".jpeg")


# ---------------------------------------------------------------- 读帧

def sample_frames(path: Path, cap: int) -> tuple[int, tuple[int, int], list[Image.Image]]:
    """只解码要用到的那几帧（等间隔抽样）。返回 ``(总帧数, 尺寸, 抽样帧)``。

    ⚠️ **不要写成 ``[f.convert("RGBA") for f in ImageSequence.Iterator(im)]``**：
    那样会把整条 GIF 全部解码进内存再抽样，一个 150 帧的 500×500 动图就是
    上百 MB，扫上百个文件时进程直接被系统干掉（实测表现为 Segmentation fault，
    连 traceback 都没有，很容易误判成"代码写错了"）。
    """
    im = Image.open(path)
    try:
        n = getattr(im, "n_frames", 1)
        size = im.size
        if n <= cap:
            idxs = list(range(n))
        else:
            step = n / cap
            idxs = sorted({min(int(i * step), n - 1) for i in range(cap)})
        out = []
        for i in idxs:
            im.seek(i)
            out.append(im.convert("RGBA"))
        return n, size, out
    finally:
        im.close()


# ---------------------------------------------------------------- 体检

def _rgba_pixels(im: Image.Image) -> list[tuple[int, int, int, int]]:
    """取一张 RGBA 图的像素列表。

    **为什么要包一层**：PIL 的类型桩把 ``getdata()`` / ``load()`` 标得很含糊
    （说是可能是 None，还可能是个 DeferredError），于是迭代它、解包成
    ``r, g, b, a``、或者索引取值全会被类型检查器报错 —— 一报一大片，
    真正的问题就淹在里面看不见了。这里统一收口一次，运行时它们就是
    RGBA 四元组的序列，没有别的可能。
    """
    return list(cast("list[tuple[int, int, int, int]]", im.getdata()))


def _corner_hist(frames: list[Image.Image]) -> tuple[Counter, bool]:
    """看四角是什么颜色，顺便判断有没有透明像素。"""
    corners: Counter = Counter()
    transparent = False
    for f in frames:
        w, h = f.size
        px: Any = f.load()          # 见 _rgba_pixels 的说明
        for cx, cy in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
            xs = range(cx, cx + 10) if cx == 0 else range(cx, cx - 10, -1)
            ys = range(cy, cy + 10) if cy == 0 else range(cy, cy - 10, -1)
            for x in xs:
                for y in ys:
                    r, g, b, a = px[x, y]
                    if a < 200:
                        transparent = True
                    else:
                        corners[(r // 48 * 48, g // 48 * 48, b // 48 * 48)] += 1
    return corners, transparent


def _static_light_alpha(frames: list[Image.Image], box: int = 200) -> int:
    """数"在所有帧里都位于同一位置"的**半透明**浅色像素 —— 只能算一条弱线索。

    **为什么要跨帧对照**：白狗素材的边缘本身就是半透明白的，逐帧单独数会把
    狗的抗锯齿边缘全算成水印（实测 198 张里误报 40 张）。水印是**静止贴上去的**，
    而狗会动，所以"每帧都命中同一个像素"才说明那里有东西没动。

    ⚠️ **这条指标测不到爱给网那批预览图的水印**：那种水印是**不透明**的浅灰实心像素
    （alpha=255，跟狗身一样），`0 < a < 200` 直接把它滤掉了。试过改成"静止浅灰像素占比"
    甚至加 `MaxFilter` 腐蚀做净空区，**结果都和人工标注对不齐** —— 白狗自身的抗锯齿边
    和水印得分几乎一样，分不开。

    所以：**这个数只用来把候选范围缩小，不能当结论。**判断有没有水印只能靠看 ——
    `make_sheet()` / `make_strip()` 垫中性灰放大输出，然后人眼过一遍（见
    `reports/README.md` 的「挑素材」一节）。
    """
    if len(frames) < 2:
        return 0
    smalls = []
    for f in frames:
        w, h = f.size
        smalls.append(f.resize((min(w, box), min(h, box))))
    w0, h0 = smalls[0].size
    hits = [0] * (w0 * h0)
    for s in smalls:
        for i, (r, g, b, a) in enumerate(s.getdata()):
            if 0 < a < 200 and r > 200 and g > 200 and b > 200:
                hits[i] += 1
    return sum(1 for c in hits if c == len(smalls))


def probe(path: Path, sample: int = 8) -> dict:
    """一张图的体检：帧数、尺寸、背景类型、主体色、水印迹象。"""
    n, size, frames = sample_frames(path, sample)
    if not frames:
        raise ValueError("没有可读帧")

    corners, transparent = _corner_hist(frames[:1])

    body = white = total = 0
    for f in frames:
        w, h = f.size
        small = f.resize((min(w, 200), min(h, 200)))
        for r, g, b, a in _rgba_pixels(small):
            if a < 200:
                continue
            total += 1
            if all(abs(c - ref) <= BODY_TOL for c, ref in zip((r, g, b), BODY_REF)):
                body += 1
            elif r > 235 and g > 235 and b > 235:
                white += 1

    bg = corners.most_common(1)[0][0] if corners else None
    return {
        "n": n,
        "size": size,
        "transparent": transparent,
        "bg": bg,
        "light_bg": bg is not None and sum(bg) > 600,
        "body": body / total if total else 0.0,
        "white": white / total if total else 0.0,
        "wm": _static_light_alpha(frames),
    }


def bg_kind(r: dict) -> str:
    if r["transparent"]:
        return "透明底"
    return "浅色底" if r["light_bg"] else "实景底"


def who(r: dict) -> str:
    if r["body"] > 0.10:
        return "米黄"
    if r["white"] > 0.10:
        return "白"
    return "?"


#: 跨帧静止的**半透明**浅色像素超过这个数就标"疑似站点水印"。
#: 实测这批 198 张：中位数 0，数值偏高的大多来自素材自带的半透明道具
#: （比如笔记本屏幕 = 382），**不是水印**。
#: ⚠️ 爱给网那种**不透明**浅灰水印这个数测不出来（见 `_static_light_alpha` 的说明），
#: 所以这一列**既会误报也会漏报**，只能当"值得多看一眼"的提示，不能当判据。
WM_LIMIT = 8


def is_clean(r: dict) -> tuple[bool, str]:
    """能不能直接拿去用（不干净就说明原因）。

    ⚠️ 返回 True **不等于**无水印 —— 理由见 `WM_LIMIT` 与 `_static_light_alpha`。
    真正拍板还得靠 `make_sheet()` / `make_strip()` 垫灰底放大后人眼过一遍。
    """
    if bg_kind(r) == "实景底":
        return False, "实景底抠不干净"
    if r["wm"] > WM_LIMIT:
        return False, "疑似站点水印"
    return True, ""


# ---------------------------------------------------------------- 运动特征

def motion(path: Path, cap: int = 24, box: int = 160) -> dict | None:
    """各帧质心/底边/高度的变化范围 —— 用来找"走路的形状"。

    用 ``getdata()`` 一次取完缩略图再累加（**别用 ``getpixel`` 逐点扫**：
    逐点扫在几百张图上会慢到进程被系统干掉）。
    """
    n, _size, frames = sample_frames(path, cap)

    cxs, cys, bots, tops = [], [], [], []
    for f in frames:
        w, h = f.size
        small = f.resize((min(w, box), min(h, box)))
        sw, sh = small.size
        sx = sy = cnt = 0
        top = bot = None
        for i, (_, _, _, a) in enumerate(_rgba_pixels(small)):
            if a <= 40:
                continue
            x, y = i % sw, i // sw
            sx += x
            sy += y
            cnt += 1
            top = y if top is None else min(top, y)
            bot = y if bot is None else max(bot, y)
        # cnt 为 0 说明整帧全透明；top/bot 也只在 cnt > 0 时才被赋过值。
        # 这里把两个条件一起写出来，免得读到 None（类型检查器也认这个）
        if not cnt or top is None or bot is None:
            continue
        cxs.append(sx / cnt / sw)
        cys.append(sy / cnt / sh)
        bots.append(bot / sh)
        tops.append(top / sh)
    if not cxs:
        return None
    return {
        "n": n,
        "dx": max(cxs) - min(cxs),          # 质心横向漂移
        "dy": max(cys) - min(cys),          # 质心纵向漂移
        "bot_range": max(bots) - min(bots),  # 底边起伏（离地）
        "h_range": max(tops) - min(tops),    # 顶部起伏（跳/坐）
    }


# ---------------------------------------------------------------- 产物

def load_frames(path: Path, cap: int = 8) -> list[Image.Image]:
    return sample_frames(path, cap)[2]


def make_sheet(items: list[tuple[int, Path]], out: Path,
               cell: int = 120, cols: int = 10,
               bg: tuple[int, int, int] = (140, 143, 150)) -> Path:
    """编号缩略图拼成的联系表（每张展示首帧 + 中间帧，便于一眼看变化）。

    默认垫**中性灰**而不是白 —— 爱给网预览图盖的是**浅灰**水印，
    垫白底或浅色底几乎看不出来，灰底才照得出来。

    尺寸提醒：水印要放大到**每格 300px 以上**才稳定可辨；默认 120 的格子适合
    看"主体长啥样"，判断水印请用 `--cell 320 --cols 6`。
    """
    rows = (len(items) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell, max(1, rows) * (cell + 14)),
                      (238, 238, 241))
    d = ImageDraw.Draw(sheet)
    for i, (n, p) in enumerate(items):
        try:
            fs = load_frames(p, cap=8)
            a, b = fs[0], fs[len(fs) // 2]
        except Exception:                                  # noqa: BLE001
            continue
        x, y = (i % cols) * cell, (i // cols) * (cell + 14)
        for j, f in enumerate((a, b)):
            th = f.copy()
            th.thumbnail((cell // 2 - 4, cell - 14), Image.Resampling.LANCZOS)
            tile = Image.new("RGB", th.size, bg)
            tile.paste(th, (0, 0), th)
            sheet.paste(tile, (x + j * (cell // 2) + 1, y + 12))
        d.text((x + 3, y + 1), f"#{n}", fill=(190, 50, 50))
        d.rectangle([x, y, x + cell - 1, y + cell + 13], outline=(212, 212, 218))
    sheet.save(out)
    return out


def make_strip(items: list[tuple[int, Path]], out: Path,
               cell: int = 170, frames_wanted: int = 8,
               bg: tuple[int, int, int] = (140, 143, 150)) -> Path:
    """把候选的动画过程逐帧排开 —— 判断动作类型只能靠看这个。

    同样垫中性灰：浅灰水印在灰底上才显形（白底基本看不见）。
    """
    rows = len(items)
    sheet = Image.new("RGB", (cell * frames_wanted, max(1, rows) * (cell + 18)),
                      (238, 238, 241))
    d = ImageDraw.Draw(sheet)
    for r, (n, p) in enumerate(items):
        fs = load_frames(p, cap=frames_wanted)
        y = r * (cell + 18)
        d.text((6, y + 2), f"#{n}  {p.name[:64]}", fill=(190, 50, 50))
        for c, f in enumerate(fs):
            th = f.copy()
            th.thumbnail((cell - 6, cell - 6), Image.Resampling.LANCZOS)
            tile = Image.new("RGB", th.size, bg)
            tile.paste(th, (0, 0), th)
            sheet.paste(tile, (c * cell + 3, y + 18))
        d.rectangle([0, y, sheet.width - 1, y + cell + 17],
                    outline=(214, 214, 220))
    sheet.save(out)
    return out


def _do_strip(items: list[tuple[int, Path]], out_dir: Path, name: str,
              args) -> None:
    """按 ``--strip`` 的编号渲染动画帧条（编号超出范围时提示并忽略）。"""
    want = set(args.strip)
    picks = [(n, p) for n, p in items if n in want]
    missing = want - {n for n, _ in picks}
    if missing:
        print(f"[review] 编号超出范围，忽略：{sorted(missing)}")
    if not picks:
        print("[review] 没有可渲染的编号")
        return
    strip_path = make_strip(picks, out_dir / f"{name}_strip.png",
                            cell=args.strip_cell,
                            frames_wanted=args.strip_frames)
    print(f"[review] 动画帧条: {strip_path}  （{len(picks)} 张）")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="素材库体检 + 联系表 + 运动特征（挑素材用）")
    ap.add_argument("src", help="素材目录（整批下载的 GIF 放哪就指哪）")
    ap.add_argument("--out", default=None,
                    help="产物目录，默认 reports/materials/")
    ap.add_argument("--name", default=None, help="产物前缀，默认取目录名")
    ap.add_argument("--cols", type=int, default=10, help="联系表每行几个，默认 10")
    ap.add_argument("--cell", type=int, default=120, help="联系表格子边长，默认 120")
    ap.add_argument("--clean", action="store_true",
                    help="只列干净可用的（排除实景底与水印），并据此出联系表")
    ap.add_argument("--list", action="store_true",
                    help="只打印体检结果，不出图（大批量时先跑这个）")
    ap.add_argument("--strip", type=int, nargs="+", metavar="N",
                    help="渲染这些编号的动画帧条（编号来自联系表）。"
                         "默认**只做这一步**，不重算联系表和运动特征（那两步很重）")
    ap.add_argument("--full", action="store_true",
                    help="和 --strip 一起用时，强制把三步全跑一遍（默认 --strip 会跳过前两步）")
    ap.add_argument("--no-motion", action="store_true",
                    help="跳过运动特征计算（只想出联系表时用，能省一大半时间）")
    ap.add_argument("--strip-frames", type=int, default=8,
                    help="帧条每张画几帧，默认 8")
    ap.add_argument("--strip-cell", type=int, default=170,
                    help="帧条格子边长，默认 170")
    ap.add_argument("--top-motion", type=int, default=25,
                    help="运动特征表里按横向位移取前几名，默认 25")
    ap.add_argument("--all", action="store_true",
                    help="运动特征表不做筛选，全列出来")
    args = ap.parse_args(argv)

    src = Path(args.src)
    if not src.is_dir():
        print(f"[review] 目录不存在：{src}")
        return 2
    name = args.name or src.name
    out_dir = Path(args.out) if args.out else ROOT / "reports" / "materials"
    out_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(p for p in src.iterdir()
                   if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES)
    if not files:
        print(f"[review] {src} 里没找到图片")
        return 1
    items = list(enumerate(files, 1))          # 编号从 #1 开始，和联系表一致

    # ---- 只渲染帧条（默认）：挑素材的节奏是"先看联系表 -> 再回来看几个候选的动画"，
    #      每看一次候选都重算 198 张的体检+运动特征没必要，也慢。
    if args.strip and not args.full:
        _do_strip(items, out_dir, name, args)
        print("[review] 只做了这一步；要顺带重算体检/联系表/运动特征，加 --full")
        return 0

    # ---- 体检
    rows, info = [], {}
    for n, p in items:
        try:
            r = probe(p)
        except Exception as exc:                            # noqa: BLE001
            rows.append(f"#{n:03d}\t读失败\t{exc}")
            continue
        info[n] = r
        ok, why = is_clean(r)
        rows.append(f"#{n:03d}\t{r['n']:>3}f\t{r['size'][0]}x{r['size'][1]}\t"
                    f"{bg_kind(r)}\t主色{r['body']:.2f}/白{r['white']:.2f}\t"
                    f"{who(r)}\t{r['wm']}\t{'' if ok else why}\t{p.name}")
    audit_path = out_dir / f"{name}_audit.txt"
    audit_path.write_text("\n".join(rows), encoding="utf-8")
    print(f"[review] 体检表  : {audit_path}  （{len(info)} 张）")
    if args.list:
        print("\n".join(rows))
        return 0

    # ---- 联系表
    sheet_items = items
    if args.clean:
        sheet_items = [(n, p) for n, p in items
                       if n in info and is_clean(info[n])[0]]
        print(f"[review] --clean 后剩 {len(sheet_items)} 张")
    sheet_path = make_sheet(sheet_items, out_dir / f"{name}_sheet.png",
                            cell=args.cell, cols=args.cols)
    print(f"[review] 联系表  : {sheet_path}")

    # ---- 运动特征
    if args.no_motion:
        print("[review] 运动特征: 已按 --no-motion 跳过")
        if args.strip:
            _do_strip(items, out_dir, name, args)
        return 0
    mrows = []
    for n, p in items:
        if args.clean and (n not in info or not is_clean(info[n])[0]):
            continue
        try:
            m = motion(p)
        except Exception:                                   # noqa: BLE001
            continue
        if m is None:
            continue
        mrows.append((n, p.name, m))
    # 纵向往返 vs 横向位移分开排：走路看 dx，原地反应看 dy / bot_range
    ranked = sorted(mrows, key=lambda t: -t[2]["dx"])
    keep = ranked if args.all else ranked[:max(1, args.top_motion)]
    lines = [f"#编号\t帧\t横向dx\t纵向dy\t底边起伏\t顶部起伏\t文件名",
             "# 走路候选 = 横向dx 大 且 底边起伏小；原地起跳 = 纵向dy/底边起伏 大"]
    for n, nm, m in keep:
        lines.append(f"#{n:03d}\t{m['n']:>3}\t{m['dx']:.3f}\t{m['dy']:.3f}\t"
                     f"{m['bot_range']:.3f}\t{m['h_range']:.3f}\t{nm}")
    motion_path = out_dir / f"{name}_motion.txt"
    motion_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[review] 运动特征: {motion_path}  （按横向位移排序，前 {len(keep)} 条）")

    # ---- 动画帧条（配合 --full 时，前三步跑完再出）
    if args.strip:
        _do_strip(items, out_dir, name, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
