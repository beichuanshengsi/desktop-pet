"""静态检查：有没有测试脚本忘了隔离玩家的存档。

为什么需要一条 lint
------------------

``tools/`` 下面十几个脚本会造真的 ``Config()`` / ``PetWindow()``。开发态的
可写数据目录就是**项目根**，玩家的 ``config.json`` 也在那儿 —— 而
``PetWindow`` 每 3 秒自动落盘一次。于是"忘了隔离"不是个小疏忽，是**直接改玩家的
存档**：

    v2.3.0 发布当天，``verify_album_ui.py`` 漏了隔离。跑一次验证之后，
    玩家打开桌宠发现：卡册里凭空多了 40 张卡、装备栏是满的、
    金币被改成测试用的数字、首跑时间变成了"120 天前"。

这种事靠人记是记不住的（写那个脚本的时候我"知道"要隔离，但没想起来）。
所以把规矩变成一条可执行的检查：**一个脚本只要碰 ``Config()`` / ``PetWindow()``，
就必须在造它们之前调用隔离**。

判定的"合格隔离"
----------------

* ``isolate_storage(`` —— ``tools/_isolate.py``，换掉整个数据目录（推荐）
* ``config_path =`` —— 老脚本的内联写法，改 ``pet.config.config_path``
* ``isolate_config(`` —— v2.1 那套从 ``verify_v21_ui`` import 的写法

另外单独列一类"弱隔离"：靠"跑完对一遍、变了就还原"的备份-还原法
（``verify_actions`` / ``verify_desktop`` / ``verify_facing``）。它**能过检查但会
被提示** —— 中途抛异常或被 Ctrl-C 时，还原那段代码执行不到，存档照样丢。

跑法：

    python tools/check_save_isolation.py
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

#: 一个脚本"会碰到玩家存档"的指纹 —— 出现任意一条就得有隔离。
TOUCHES = ("Config()", "Config.load()", "PetWindow(")

#: 合格的隔离写法。
STRONG = ("isolate_storage(", "config_path =", "isolate_config(")

#: 弱隔离：备份-还原。能过，但会被点名。
WEAK = ("变了就还原", "已还原为运行前的版本")

#: 不参与检查的文件。
#:   ``repair_save.py`` 是**故意**要动真存档的修档工具（它干的就是这件事），
#:   所以豁免 —— 它自己也带"桌宠还开着就拒绝执行"的保护。
EXEMPT = {"_isolate.py", "check_save_isolation.py", "typecheck.py", "build_cards.py",
          "repair_save.py"}

FAILS: list[str] = []


def protected(src: str) -> tuple[bool, bool]:
    """返回 ``(是否合格, 是否只靠弱隔离)``。

    两类都不满足才算"漏了"；只满足弱隔离的**算不合格**（崩溃时会丢档），
    但描述不同 —— 一个是"完全没防"，一个是"防得不牢"，修法也不一样。
    """
    strong = any(s in src for s in STRONG)
    weak = any(s in src for s in WEAK)
    return strong, (weak and not strong)


def scan() -> list[tuple[str, str]]:
    """扫一遍 ``tools/*.py``，返回 ``[(文件名, 问题描述)]``。"""
    problems: list[tuple[str, str]] = []
    for path in sorted(HERE.glob("*.py")):
        if path.name in EXEMPT:
            continue
        src = path.read_text(encoding="utf-8")
        if not any(t in src for t in TOUCHES):
            continue                       # 不碰存档的脚本，不管
        strong, weak_only = protected(src)
        if not strong and weak_only:
            problems.append((path.name, "只做了备份-还原（中途崩溃/Ctrl-C 时仍会丢档）"))
        elif not strong:
            problems.append((path.name, "漏了隔离（会直接改玩家的 config.json）"))
    return problems


def self_test() -> list[str]:
    """先证明这条检查不是摆设：拿一段"会碰存档但没隔离"的假源码喂它。

    一个永远返回"通过"的检查比没有检查更糟 —— 它会让人以为安全。
    """
    bad = ["cfg = Config()", "pet = PetWindow(cfg, bank)"]
    ok = ["isolate_storage('x')", "cfg = Config()"]
    out = []
    if protected("\n".join(bad))[0]:
        out.append("自检失败：没隔离的样本被判成了合格")
    if not protected("\n".join(ok))[0]:
        out.append("自检失败：隔离了的样本被判成了不合格")
    return out


def main() -> int:
    print("[存档隔离检查] tools/*.py")

    problems_self = self_test()
    for p in problems_self:
        print(f"  FAIL {p}")
        FAILS.append(p)
    if not problems_self:
        print("  ok   检查器自检（能认出漏隔离的样本）")

    problems = scan()
    if problems:
        print()
        for name, why in problems:
            print(f"  FAIL {name}: {why}")
            FAILS.append(name)
    else:
        print("  ok   所有会碰存档的脚本都做了隔离")

    print()
    if FAILS:
        print(f"不通过（{len(FAILS)} 项）：")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("全部通过：没有脚本会误写玩家的存档")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
