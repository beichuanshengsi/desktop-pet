"""从素材目录生成卡池：``assets/cards/cards.json`` + ``thumb/*.png``。

卡册要的两样东西都由它产出：

1. **清单** ``cards.json`` —— 每张卡的 id / 文件名 / 档位。程序运行时不读
   ``卡片分档.csv``：csv 是"分档过程的记录"，带着彩色像素占比那些中间指标，
   而运行时只需要最后那三列。分开的另一个好处是改档位不用重生成缩略图。
2. **缩略图** ``thumb/<id>.png`` —— 原图是 630×630、104 张共 12 MB，
   而卡册格子里只显示 80px、徽章栏只有 26px。把原图塞进版本库没有意义。

跑法：

    python tools/build_cards.py                       # 用下面的默认路径
    python tools/build_cards.py --src <素材目录> --csv <分档表>

**这个脚本只在换素材时跑一次**，产物直接入库（卡册是纯静态资源）。
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent

#: 默认的分档表与素材目录。分档表是人工过了一遍的产物（白狗身体是透明的，
#: 程序看不出"穿没穿衣服"，只能人眼分），所以它是**输入**而不是中间产物。
DEFAULT_CSV = ROOT / "docs" / "卡片分档.csv"
DEFAULT_SRC = Path.home() / "Downloads" / "线条小狗PNG素材_透明版"
DEFAULT_DST = ROOT / "assets" / "cards"

THUMB = 160
#: 展示顺序：传说在前。卡册的翻页顺序按它排 —— 先把稀有的摆在前面，
#: "还差几张传说"这件事才一眼看得见。
TIER_ORDER = ("传说", "史诗", "稀有", "普通")


def main() -> int:
    ap = argparse.ArgumentParser(description="生成卡池清单与缩略图")
    ap.add_argument("--csv", type=Path, default=DEFAULT_CSV, help="分档表")
    ap.add_argument("--src", type=Path, default=DEFAULT_SRC, help="原图目录")
    ap.add_argument("--dst", type=Path, default=DEFAULT_DST, help="输出目录")
    args = ap.parse_args()

    if not args.csv.exists():
        print(f"找不到分档表：{args.csv}")
        return 1
    if not args.src.is_dir():
        print(f"找不到素材目录：{args.src}")
        return 1

    args.dst.mkdir(parents=True, exist_ok=True)
    (args.dst / "thumb").mkdir(exist_ok=True)

    have = {p.name for p in args.src.glob("*.png")}
    rows: list[dict] = []
    with args.csv.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            name = (row.get("file") or "").strip()
            tier = (row.get("tier") or "").strip()
            if not name:
                continue
            if name not in have:
                print(f"  [跳过] 分档表里有、素材目录里没有：{name}")
                continue
            rows.append({"idx": int(row["idx"]), "file": name, "tier": tier})

    for name in sorted(have - {r["file"] for r in rows}):
        print(f"  [注意] 素材目录里有、分档表里没有（不会进卡池）：{name}")

    known = set(TIER_ORDER)
    for tier in sorted({r["tier"] for r in rows} - known):
        print(f"  [警告] 出现了未知档位 {tier!r}，它不会出现在卡册里")

    stat: dict[str, int] = {}
    for r in rows:
        stat[r["tier"]] = stat.get(r["tier"], 0) + 1
    print("\n档位统计：")
    for tier in TIER_ORDER:
        print(f"  {tier}  {stat.get(tier, 0):3d} 张")
    print(f"  合计 {len(rows)} 张")

    rows.sort(key=lambda r: (TIER_ORDER.index(r["tier"])
                             if r["tier"] in known else 99, r["idx"]))

    cards = []
    for r in rows:
        cid = f"c{r['idx']:03d}"
        cards.append({"id": cid, "file": r["file"], "tier": r["tier"]})

        src = args.src / r["file"]
        dst = args.dst / "thumb" / f"{cid}.png"
        # 素材没动就不重做缩略图（104 张全做一遍要几秒）
        if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
            continue
        im = Image.open(src).convert("RGBA")
        im.thumbnail((THUMB, THUMB), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (THUMB, THUMB), (0, 0, 0, 0))
        canvas.paste(im, ((THUMB - im.width) // 2, (THUMB - im.height) // 2), im)
        canvas.save(dst, optimize=True)

    (args.dst / "cards.json").write_text(
        json.dumps({"version": 1, "tiers": list(TIER_ORDER), "cards": cards},
                   ensure_ascii=False, indent=1),
        encoding="utf-8")

    thumbs = list((args.dst / "thumb").glob("*.png"))
    total = sum(p.stat().st_size for p in thumbs) / 1e6
    print(f"\n写出 {args.dst / 'cards.json'}（{len(cards)} 张）")
    print(f"缩略图 {len(thumbs)} 个，共 {total:.2f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
