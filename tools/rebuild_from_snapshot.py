"""从 ``_snapshots/`` 里把早期那套帧重新加工进 ``custom_pet/``。

为什么需要它
------------
2026-09-21 那批素材的**原始 GIF 已经丢了**（`_archive/0921_1228/` 被误删，
下载目录里也没有副本），只剩 ``_snapshots/`` 里当年加工过的 128px 帧序列。
想调整它们的尺寸或换到别的状态，就只能从这份加工版重新摆一遍 ——
这个脚本就是那条路径，免得每次临时写一段。

它做两件事（幂等，可以反复跑）
------------------------------
1. ``_snapshots/线条小狗晃脚脚2_idle/``（17 帧，奶油狗坐木凳晃腿）
   → ``custom_pet/idle_*.png``，按 ``--scale`` 重新缩放。
2. ``_snapshots/pre_0922/idle_*.png``（搬进来之前的站姿挥手那套，14 帧）
   → ``custom_pet/walk_a_*.png``，作为走路的两套之一。

摆放规则（与其它状态一致）
------------------------
* 用**全部帧的并集包围盒**做一次性变换 —— 逐帧各自裁剪再缩放会让每帧的
  居中基准都不一样，播起来狗会左右抖。
* 底边压在 y=122，水平居中。

关于 ``--scale``（默认 1.26）
---------------------------
``_snapshots`` 里的帧当年为迁就木凳的包围盒被压在 0.678，狗本体只有约 75 高，
而其它状态的主体都在 100 上下。1.26 是**不裁到木凳的上限附近**：
并集宽 100 × 1.26 = 126，128 的画布还留得住凳子两端的描边
（到 1.28 就正好贴边，再大就切凳子）。此时狗本体约 94，和 walk 的 100 基本齐平。

用法
----
    python tools/rebuild_from_snapshot.py            # 按默认值重建
    python tools/rebuild_from_snapshot.py --scale 1.2
    python tools/rebuild_from_snapshot.py --dry-run  # 只看会写哪些文件
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent

#: 坐木凳那套（现在的 idle）的来源目录
BENCH_SRC = ROOT / "assets" / "raw" / "_snapshots" / "线条小狗晃脚脚2_idle"
#: 站姿挥手那套（搬进 custom_pet 之前的 idle，现在做 walk 的第二套）
STANCE_SRC = ROOT / "assets" / "raw" / "_snapshots" / "pre_0922"

CANVAS = 128
BOTTOM = 122
#: 坐木凳那套的并集包围盒（17 帧共同的最大范围）
BENCH_UNION = (14, 31, 114, 122)

IDLE_PAT = re.compile(r"^idle_(\d+)\.png$")


def _frames(directory: Path, pattern: re.Pattern[str]) -> list[Path]:
    return sorted(
        (p for p in directory.glob("*.png") if pattern.match(p.name)),
        key=lambda p: int(pattern.match(p.name).group(1)),      # type: ignore[union-attr]
    )


def _place(src: Path, union: tuple[int, int, int, int], scale: float) -> Image.Image:
    """把 src 的 union 区域按 scale 缩放后，底边压 y=BOTTOM、水平居中地放进画布。"""
    ux0, uy0, ux1, uy1 = union
    w = max(1, round((ux1 - ux0) * scale))
    h = max(1, round((uy1 - uy0) * scale))
    crop = Image.open(src).convert("RGBA").crop(union)
    crop = crop.resize((w, h), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    canvas.paste(crop, ((CANVAS - w) // 2, BOTTOM - h), crop)
    return canvas


def main() -> int:
    ap = argparse.ArgumentParser(description="从 _snapshots/ 重建 custom_pet 的 idle 与 walk_a")
    ap.add_argument("--scale", type=float, default=1.26,
                    help="坐木凳那套的缩放比（默认 1.26，上限 1.28）")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不写文件")
    args = ap.parse_args()

    custom = ROOT / "custom_pet"
    if not BENCH_SRC.is_dir() or not STANCE_SRC.is_dir():
        print(f"缺来源目录：{BENCH_SRC} / {STANCE_SRC}")
        return 1

    bench = sorted(BENCH_SRC.glob("*.png"), key=lambda p: int(p.stem))
    stance = _frames(STANCE_SRC, IDLE_PAT)
    ux0, uy0, ux1, uy1 = BENCH_UNION
    tw, th = round((ux1 - ux0) * args.scale), round((uy1 - uy0) * args.scale)

    print(f"[来源] 坐木凳 {len(bench)} 帧  ← {BENCH_SRC.name}")
    print(f"[来源] 站姿挥手 {len(stance)} 帧  ← {STANCE_SRC.name}/idle_*.png")
    print(f"[计划] idle   ← 坐木凳 ×{args.scale}  ({ux1 - ux0}x{uy1 - uy0} → {tw}x{th}，"
          f"贴入 ({(CANVAS - tw) // 2}, {BOTTOM - th}))")
    print(f"[计划] walk_a ← 站姿挥手（尺寸不动，主体 103 与 walk 的 100 齐平）")
    if tw > CANVAS or th > BOTTOM:
        print(f"[警告] 缩放后 {tw}x{th} 放不进画布，木凳会被裁")
    if args.dry_run:
        print("[dry-run] 没有写任何文件")
        return 0

    if not stance:
        print("找不到站姿那套的备份，walk_a 会保持原样")

    for i, src in enumerate(stance):
        shutil.copy2(src, custom / f"walk_a_{i:02d}.png")
    for p in custom.glob("idle_*.png"):
        if IDLE_PAT.match(p.name):
            p.unlink()
    for i, src in enumerate(bench):
        _place(src, BENCH_UNION, args.scale).save(custom / f"idle_{i:02d}.png")

    print()
    print(f"[完成] custom_pet：idle {len(bench)} 帧 / walk_a {len(stance)} 帧")
    print("       桌宠正在跑的话要重启才看得到")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
