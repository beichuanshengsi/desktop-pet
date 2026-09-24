"""改贴图朝向 —— 狗倒着走的时候用这个。

    python tools/set_facing.py                     看现在声明的是哪边
    python tools/set_facing.py left                声明素材原图朝左（向右走时自动镜像）
    python tools/set_facing.py flip                在当前声明上直接翻过来
    python tools/set_facing.py flip --set walk_a   只翻某一套（同一动作多套素材时用）

为什么要有"声明"这件事：程序只知道往哪走，不知道素材画的是哪一边。
两件事对不上就会倒着走，而且从代码上完全看不出来。朝向存成素材自带的
``facing.json``，跟贴图放在一起，换素材时跟着一起换。

一个动作有几套素材时，各套是分开下的图，**原图方向不一定一致**：用
``--set`` 给方向相反的那套单独声明，其余套继续跟随默认值。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pet import facing                                          # noqa: E402
from pet.paths import pet_asset_dir                            # noqa: E402

ARROW = {-1: "左", 1: "右"}


def _show(pet_dir: Path) -> tuple[int, dict[str, int]]:
    base = facing.read(pet_dir)
    sets = facing.read_sets(pet_dir)
    where = facing.meta_path(pet_dir)

    print(f"素材目录 : {pet_dir}")
    print(f"默认朝向 : 朝{ARROW[base]}"
          + ("" if where.exists() else "（没有声明文件，按默认值）"))
    if sets:
        for name in sorted(sets):
            print(f"  按套   : {name} -> 朝{ARROW[sets[name]]}")
    else:
        print("  按套   : 无（所有套都跟随默认朝向）")
    return base, sets


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="查看/修改贴图朝向声明")
    ap.add_argument("value", nargs="?", default=None,
                    help="left / right / flip，留空只看当前值")
    ap.add_argument("--dir", default=None, help="素材目录，默认当前生效的那套")
    ap.add_argument("--set", dest="set_name", default=None,
                    help="只改某一套素材，写素材前缀（如 walk_a / poke_b），"
                         "就是文件名的前两段")
    args = ap.parse_args(argv)

    pet_dir = Path(args.dir) if args.dir else pet_asset_dir()
    base, sets = _show(pet_dir)
    target_set = args.set_name

    if args.value is None:
        for name, value in [("默认套", base), *sets.items()]:
            print(f"行走判断 : [{name}] 向右走"
                  f"{'要镜像' if facing.should_mirror(1, value) else '不镜像'}，"
                  f"向左走{'要镜像' if facing.should_mirror(-1, value) else '不镜像'}")
        print("要改就加参数：left / right / flip（可再跟 --set <素材前缀>）")
        return 0

    word = args.value.strip().lower()
    target: int | None
    if target_set is None:
        target = -base if word == "flip" else facing.normalize(word)
    else:
        now = sets.get(target_set, base)
        target = -now if word == "flip" else facing.normalize(word)
    if target is None:
        print(f"认不出「{args.value}」，只能是 left / right / flip")
        return 2

    if target_set is None:
        path = facing.write(pet_dir, target, sets=sets)
        print(f"已改成   : 默认朝向 朝{ARROW[target]}  ->  {path}")
    else:
        new_sets = dict(sets)
        if target == base:
            new_sets.pop(target_set, None)      # 与默认一致就没必要单独留着
            print(f"已改成   : 套 {target_set!r} 跟随默认（朝{ARROW[base]}）")
        else:
            new_sets[target_set] = target
            print(f"已改成   : 套 {target_set!r} 朝{ARROW[target]}")
        path = facing.write(pet_dir, base, sets=new_sets)
        print(f"           {path}")
    print("重新启动桌宠生效（运行中的程序不会自动刷新）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
