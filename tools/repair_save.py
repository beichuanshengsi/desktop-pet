"""修存档：把不该出现在玩家卡册里的数据清掉。

为什么会有这个脚本
------------------

v2.3.0 发布当天，``tools/verify_album_ui.py`` 忘了隔离存档（它会造真的
``PetWindow``，而那个窗口每 3 秒自动落盘一次）。跑一次验证，就往玩家的
``config.json`` 里写进了：

* 40 次抽卡抽出来的卡（测试脚本花钱抽的）
* 5 张被"装上"的装备（为了截"满槽"那张图）
* 被改成 120 天前的首跑时间（为了测"老档 5 槽"）
* 被改成测试值的金币

玩家打开桌宠，发现自己什么都没干，卡册里已经躺了 40 张卡。这个脚本用来把
这些**不是玩家自己挣来的**状态清干净，恢复成"抽卡系统刚上线、还没动过"的样子。

它和 ``tools/`` 下别的脚本相反：**就是要动那份真存档**，所以不隔离、也不能隔离。
（``tools/check_save_isolation.py`` 把它列进了豁免名单，理由同上。）

用法
----

    python tools/repair_save.py --dry-run              # 只看会改什么，不落盘
    python tools/repair_save.py                        # 清空卡册相关字段
    python tools/repair_save.py --coins 0              # 顺手把金币定成 0
    python tools/repair_save.py --launched-at 2026-09-21

会先把原存档备份成 ``config.json.before-repair-<时间戳>.bak`` 再动手。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pet.config import STAMP_FMT                                 # noqa: E402
from pet.paths import config_path                                # noqa: E402

#: 卡册相关的字段 —— 清空它们就是"抽卡系统还没被动过"。
ALBUM_FIELDS: dict[str, object] = {
    "cards": {},
    "equipped": [],
    "frag_low": 0,
    "frag_high": 0,
    "weekly_used": {},
    "low_convert_used": 0,
    "dup_streak": {},
}

#: 存档在这个秒数内被写过，就认为桌宠还开着（它每 3 秒落盘一次）。
RUNNING_WINDOW_SEC = 10


def pet_maybe_running() -> bool:
    """存档刚被写过 —— 大概率桌宠还开着，它会把改动立刻覆盖回去。"""
    try:
        return (time.time() - config_path().stat().st_mtime) < RUNNING_WINDOW_SEC
    except OSError:
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description="清理被测试写进玩家存档的卡册数据")
    ap.add_argument("--dry-run", action="store_true", help="只打印，不写盘")
    ap.add_argument("--coins", type=int, default=None, help="把金币改成这个数")
    ap.add_argument("--launched-at", default=None,
                    help=f"首跑时间（YYYY-MM-DD），决定已解锁的装备槽数；"
                         f"存成 '<日期>{STAMP_FMT[10:]}' 的格式")
    ap.add_argument("--force", action="store_true",
                    help="存档刚被写过也照改（先确认桌宠已经退出）")
    args = ap.parse_args()

    path = config_path()
    print(f"[修复] 存档：{path}")
    if not path.exists():
        print("[修复] 没有存档文件，没什么可修")
        return 0

    if pet_maybe_running() and not args.force:
        print("[修复] 中止：这个存档 %d 秒内被写过 —— 桌宠多半还开着。"
              % RUNNING_WINDOW_SEC)
        print("       它每 3 秒会自动落盘，会把这里的改动立刻覆盖回去。")
        print("       先右键桌宠 -> 退出，再跑一次；确认已退出可加 --force。")
        return 1

    raw = json.loads(path.read_text(encoding="utf-8"))

    changes: list[tuple[str, object, object]] = []
    for key, empty in ALBUM_FIELDS.items():
        old = raw.get(key)
        if old != empty:
            changes.append((key, old, empty))
        raw[key] = empty

    if args.coins is not None:
        if raw.get("coins") != args.coins:
            changes.append(("coins", raw.get("coins"), args.coins))
        raw["coins"] = args.coins

    if args.launched_at is not None:
        new_stamp = f"{args.launched_at} 00:00:00"
        if raw.get("launched_at") != new_stamp:
            changes.append(("launched_at", raw.get("launched_at"), new_stamp))
        raw["launched_at"] = new_stamp

    if not changes:
        print("[修复] 卡册相关的字段本来就是干净的，无需改动")
        return 0

    print("\n[修复] 将要改动：")
    for key, old, new in changes:
        print(f"  {key}:")
        print(f"    旧 = {json.dumps(old, ensure_ascii=False)[:160]}")
        print(f"    新 = {json.dumps(new, ensure_ascii=False)[:160]}")

    if args.dry_run:
        print("\n[修复] --dry-run：没有写盘")
        return 0

    backup = path.with_name(
        f"config.json.before-repair-{datetime.now():%Y%m%d_%H%M%S}.bak")
    shutil.copy2(path, backup)
    print(f"\n[修复] 原存档已备份 -> {backup.name}")

    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    print(f"[修复] 已写回 {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
