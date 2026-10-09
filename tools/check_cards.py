"""卡册系统的自检：抽卡概率、碎片折算、周额度、保底、装备加成。

**不依赖 Qt**，所以能在没有图形环境的地方跑：

    python tools/check_cards.py

它和 ``tools/smoke_test.py`` 的分工：那边管"窗口能不能起来、动作对不对"，
这里管"数值和规则对不对"。抽卡概率这种东西必须跑上万次才看得出偏差，
塞进冒烟测试会把整套测试拖慢十几倍。
"""

from __future__ import annotations

import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pet.cards import (COIN_PER_PULL, COST, DISSOLVE, EQUIP_BONUS, EQUIP_CAP,
                       GUARD, LOW_TO_HIGH_CAP, LOW_TO_HIGH_RATE, RATE, WEEKLY_QUOTA,
                       Album, coin_bonus, coins_with_bonus, load_pool, week_stamp)
from pet.config import STAMP_FMT, Config

FAILS: list[str] = []
PASSES = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASSES
    if ok:
        PASSES += 1
        print(f"  ok   {name}" + (f"   {detail}" if detail else ""))
    else:
        FAILS.append(name)
        print(f"  FAIL {name}   {detail}")


def fresh_cfg(**kw) -> Config:
    cfg = Config()
    for key, value in kw.items():
        setattr(cfg, key, value)
    return cfg


def main() -> int:
    print("\n[1] 卡池")
    pool = load_pool(fresh=True)
    check("卡池非空", bool(pool), f"{len(pool)} 张")
    check("共 104 张", len(pool) == 104, f"{len(pool)}")
    for tier, want in (("普通", 53), ("稀有", 26), ("史诗", 18), ("传说", 7)):
        got = pool.count_tier(tier)
        check(f"{tier} {want} 张", got == want, f"{got}")
    check("出率之和为 1", abs(sum(RATE.values()) - 1.0) < 1e-9,
          f"{sum(RATE.values()):.4f}")

    print("\n[2] 抽卡出率（2 万次）")
    cfg = fresh_cfg()
    album = Album(cfg, rng=random.Random(20261009), cards=pool)
    tally = {t: 0 for t in RATE}
    for _ in range(20000):
        tally[album.roll_tier()] += 1
    for tier, want in RATE.items():
        got = tally[tier] / 20000
        check(f"{tier} 出率 ≈ {want:.0%}", abs(got - want) < 0.015, f"{got:.1%}")

    print("\n[3] 抽卡的收支")
    cfg = fresh_cfg(coins=1000)
    album = Album(cfg, rng=random.Random(7), cards=pool)
    before = cfg.coins
    pull = album.pull()
    check("能抽到卡", pull is not None)
    assert pull is not None, "抽不出卡，后面的断言没有意义"
    check(f"扣了 {COIN_PER_PULL} 金币", cfg.coins == before - COIN_PER_PULL, f"{cfg.coins}")
    check("卡进了卡册", album.count(pull.card.id) == 1)
    check("首抽算新卡", pull.is_new)
    album.pull()
    check("抽卡会重复加张数",
          sum(cfg.cards.values()) == 2, f"{cfg.cards}")
    check("金币不够时抽不了", not Album(fresh_cfg(coins=COIN_PER_PULL - 1),
                                     cards=pool).can_pull())

    print("\n[4] 分解（必须留一张）")
    cfg = fresh_cfg()
    album = Album(cfg, rng=random.Random(3), cards=pool)
    legendary = pool.by_tier("传说")[0]
    album._grant(legendary.id)
    ok, amount, kind = album.dissolve(legendary.id)
    check("只剩一张时不能分解", not ok and amount == 0)
    album._grant(legendary.id)
    ok, amount, kind = album.dissolve(legendary.id)
    check("两张时可以分解", ok)
    check("传说分解得 10 高级碎片",
          (amount, kind) == (10, "high") and cfg.frag_high == 10,
          f"{amount} {kind} / 高 {cfg.frag_high}")
    check("分解后还剩 1 张", album.count(legendary.id) == 1)
    low_card = pool.by_tier("普通")[0]
    album._grant(low_card.id)
    album._grant(low_card.id)
    album.dissolve(low_card.id)
    check("普通分解得 2 低级碎片", cfg.frag_low == 2, f"{cfg.frag_low}")

    print("\n[5] 兑换：额度 / 碎片 / 保底")
    cfg = fresh_cfg(frag_high=1000)
    album = Album(cfg, rng=random.Random(11), cards=pool)
    cfg.dup_streak["传说"] = GUARD          # 制造"连续撞了 3 次"的处境
    trade = album.exchange("传说")
    check("保底触发时必出新", trade.ok and trade.is_new, f"{trade}")
    check("保底后计数归零", album.dup_streak("传说") == 0)
    check("扣了 30 高级碎片", cfg.frag_high == 1000 - COST["传说"][1],
          f"{cfg.frag_high}")
    check("本周额度用掉 1 次", album.week_left("传说") == WEEKLY_QUOTA["传说"] - 1)
    for _ in range(WEEKLY_QUOTA["传说"] - 1):
        album.exchange("传说")
    check("额度用完就换不了",
          not album.exchange("传说").ok and album.week_left("传说") == 0,
          album.exchange_block_reason("传说"))
    cfg2 = fresh_cfg(frag_high=5)
    a2 = Album(cfg2, cards=pool)
    t2 = a2.exchange("传说")
    check("碎片不够时说得出原因", not t2.ok and "还差" in t2.reason, t2.reason)

    print("\n[6] 兑换撞重复要部分返还（净亏 > 0）")
    cfg = fresh_cfg(frag_high=10000)
    album = Album(cfg, rng=random.Random(5), cards=pool)
    for card in pool.by_tier("传说"):       # 先集齐传说档，之后必然撞重复
        album._grant(card.id)
    before = cfg.frag_high
    cfg.dup_streak["传说"] = 0
    trade = album.exchange("传说")
    price = COST["传说"][1]
    refund = DISSOLVE["传说"][1]
    check("撞重复返回返还款", trade.ok and not trade.is_new and trade.refund == refund,
          f"{trade}")
    check("净亏 = 兑换价 − 返还 > 0",
          before - cfg.frag_high == price - refund and price - refund > 0,
          f"亏 {before - cfg.frag_high}")

    print("\n[7] 低换高：5:1 且每周封顶")
    cfg = fresh_cfg(frag_low=200)
    album = Album(cfg, cards=pool)
    check("本周最多换 6 个（34 // 5）", album.low_convert_capacity() == 6,
          f"{album.low_convert_capacity()}")
    got = album.convert_low(1)
    check("换到 1 个高级碎片", got == 1 and cfg.frag_high == 1)
    check("扣了 5 个低级碎片", cfg.frag_low == 195, f"{cfg.frag_low}")
    album.convert_low(99)
    check("连续换到周上限就停",
          album.low_convert_capacity() == 0
          and cfg.low_convert_used == (LOW_TO_HIGH_CAP // LOW_TO_HIGH_RATE) * LOW_TO_HIGH_RATE,
          f"已用 {cfg.low_convert_used} / 上限 {LOW_TO_HIGH_CAP}")

    print("\n[8] 装备：槽位解锁、加成、硬顶")
    old = (datetime.now() - timedelta(days=120)).strftime(STAMP_FMT)
    cfg = fresh_cfg(launched_at=old)
    album = Album(cfg, rng=random.Random(9), cards=pool)
    check("老玩家满 5 槽", album.slots() == 5, f"{album.slots()}")
    newbie = Album(fresh_cfg(), cards=pool)
    check("新玩家第 1 周只有 1 槽", newbie.slots() == 1, f"{newbie.slots()}")

    legendaries = pool.by_tier("传说")
    for card in legendaries[:5]:
        album._grant(card.id)
    for card in legendaries[:5]:
        album.equip(card.id)
    check("能装 5 张", len(cfg.equipped) == 5, f"{len(cfg.equipped)}")
    check("5 张传说的裸加成是 25%",
          abs(5 * EQUIP_BONUS["传说"] - 0.25) < 1e-9)
    check("被硬顶截到 20%", abs(album.bonus() - EQUIP_CAP) < 1e-9,
          f"{album.bonus():.2f}")
    check("加成文案", album.bonus_text() == "金币 +20%", album.bonus_text())
    final, rate = coins_with_bonus(cfg, 100)
    check("100 金币 × 1.20 = 120", final == 120 and abs(rate - 0.2) < 1e-9,
          f"{final}（+{rate:.0%}）")
    check("没装备时加成为 0（不改动原值）",
          coins_with_bonus(fresh_cfg(), 100) == (100, 0.0))

    print("\n[9] 未拥有的卡不能装备")
    cfg = fresh_cfg(launched_at=old)
    album = Album(cfg, cards=pool)
    check("没抽到就装不上", album.equip(pool.by_tier("传说")[0].id) is False)
    check("原因说得清楚", "还没抽到" in album.can_equip(pool.by_tier("传说")[0].id))

    print("\n[10] 跨周重置")
    cfg = fresh_cfg(frag_high=1000, week_stamp="2020-W01",
                    weekly_used={"传说": 1}, low_convert_used=20)
    album = Album(cfg, cards=pool)
    check("跨周会重置", album.refresh_week() is True)
    check("额度清零", cfg.weekly_used == {} and cfg.low_convert_used == 0)
    check("周标识是本周", cfg.week_stamp == week_stamp(), cfg.week_stamp)
    check("同一周内不会重复重置", album.refresh_week() is False)

    print("\n[11] 满收集后再抽只能得到重复张")
    cfg = fresh_cfg(coins=10 ** 6)
    album = Album(cfg, rng=random.Random(13), cards=pool)
    for card in pool.all():
        album._grant(card.id)
    check("图鉴已满", album.owned_kinds() == 104)
    pull = album.pull()
    check("满图鉴后抽到的是重复（图鉴数不变）",
          pull is not None and not pull.is_new and album.owned_kinds() == 104)
    check("重复张会计数", album.duplicates() == 1, f"{album.duplicates()}")

    print("\n" + "=" * 62)
    if FAILS:
        print(f"失败 {len(FAILS)} 项 / 通过 {PASSES} 项：")
        for name in FAILS:
            print(f"  - {name}")
        return 1
    print(f"全部通过（{PASSES} 项）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
