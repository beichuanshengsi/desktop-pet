"""音效的无头验收：事件表与素材对不对得上、开关和音量落不落存档、
菜单入口齐不齐、**触发点是不是真的在响**。

跑法：

    python tools/verify_sfx.py [输出目录]

**不弹窗口、不出声**：窗口设了 ``WA_DontShowOnScreen``，菜单只 ``grab()``；
播放调用被换成一个记账函数（见 ``_spy``）—— 于是这个脚本既不会在用户
机器上"叮"一下，又能拿到"哪个动作响了哪个事件"的确切证据。

**不碰玩家存档**：本脚本会造真的 ``PetWindow``（它每 3 秒自动落盘），
所以开头先把可写数据目录整个换到临时目录。见 ``tools/_isolate.py``。

为什么"触发点"要在这里验而不是靠读源码找 ``play(`` 字样：字符串搜索
找不出"这一行到底会不会被执行到"。换成记账之后，"点一下真的响没响"
是跑出来的，不是猜出来的。
"""

from __future__ import annotations

import json
import sys
import tempfile
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _isolate import assert_isolated, isolate_storage              # noqa: E402

#: 存档隔离 —— **必须排在所有 pet.* 导入和一切 Config()/PetWindow() 之前**。
STORAGE = isolate_storage("sfx")
assert_isolated()

from pet import menu as menulib                                    # noqa: E402
from pet import sfx as sfxlib                                      # noqa: E402
from pet.assets import AssetBank                                   # noqa: E402
from pet.cards import TIERS                                        # noqa: E402
from pet.config import Config, config_path                         # noqa: E402
from pet.paths import pet_asset_dir                                # noqa: E402
from pet.window import PetWindow                                   # noqa: E402

FAILS: list[str] = []
PASSES = 0

#: 播放调用的账本。见 ``_spy``。
CALLS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASSES
    if ok:
        PASSES += 1
        print(f"  ok   {name}" + (f"   {detail}" if detail else ""))
    else:
        FAILS.append(name)
        print(f"  FAIL {name}   {detail}")


def _spy(key: str) -> None:
    """把 ``sfx.play`` 换成记账：不动硬件，只留下"谁响了"。

    换的是模块属性而不是 ``_Engine`` 里的方法 —— 所有调用点写的都是
    ``sfxlib.play(...)``，改这一处就全覆盖了（这也正是本模块要收敛成
    单一入口的理由之一）。
    """
    CALLS.append(key)


def wav_seconds(path: Path) -> float:
    """wav 时长（秒）。用标准库读，验收脚本不该为读个时长多一个依赖。"""
    with wave.open(str(path)) as w:
        rate = w.getframerate() or 1
        return w.getnframes() / float(rate)


def took(event: str) -> bool:
    """账本里有没有这个事件。"""
    return event in CALLS


def since(mark: int, event: str) -> bool:
    """``mark`` 之后有没有响过这个事件（用来定位"是哪一下响的"）。"""
    return event in CALLS[mark:]


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else (ROOT / "reports")
    out_dir.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- [1] 事件表
    print("\n[1] 事件表")
    keys = [e.key for e in sfxlib.EVENTS]
    check("事件名不重复", len(keys) == len(set(keys)),
          f"{len(keys)} 个")
    check("每个事件都有中文名和用途说明",
          all(e.title and e.about for e in sfxlib.EVENTS))
    check("事件名全是小写英文 + 下划线（要当文件名用）",
          all(k.replace("_", "").isalnum() and k.islower() for k in keys),
          " ".join(keys))
    check("BY_KEY 与 EVENTS 对得上",
          set(sfxlib.BY_KEY) == set(keys))

    print("\n[2] 抽卡四档")
    check("TIER_EVENT 覆盖 card 的全部档位",
          set(sfxlib.TIER_EVENT) == set(TIERS),
          f"{sorted(TIERS)}")
    check("四档映射到四个不同事件",
          len(set(sfxlib.TIER_EVENT.values())) == 4,
          str(sfxlib.TIER_EVENT))
    for tier, event in sfxlib.TIER_EVENT.items():
        check(f"「{tier}」-> {event}", event in sfxlib.BY_KEY)
    check("认不出的档位兜底到普通（不抛异常）",
          sfxlib.event_for_tier("不存在的档") == "pull_normal")

    # ---------------------------------------------------------------- 素材
    print("\n[3] 素材文件")
    missing = sfxlib.missing()
    check("每个事件都有对应音频", not missing, "缺：" + " ".join(missing) if missing else "21/21")
    bad: list[str] = []
    durations: dict[str, float] = {}
    for e in sfxlib.EVENTS:
        p = sfxlib.file_for(e.key)
        if not p.is_file():
            continue
        try:
            secs = wav_seconds(p)
        except Exception as exc:                                   # noqa: BLE001
            bad.append(f"{e.key}({exc})")
            continue
        durations[e.key] = secs
        if secs < 0.05:
            bad.append(f"{e.key}(只有 {secs:.3f}s，等于没声)")
    check("音频都能读、且不是空的", not bad, " ".join(bad))

    tier_order = ["pull_normal", "pull_rare", "pull_epic", "pull_legend"]
    if all(k in durations for k in tier_order):
        seq = [durations[k] for k in tier_order]
        small = [durations["pull_normal"], durations["pull_rare"]]
        big = [durations["pull_epic"], durations["pull_legend"]]
        check("抽卡四档是四段互不相同的时长",
              len({round(s, 3) for s in seq}) == 4,
              " / ".join(f"{s:.2f}s" for s in seq))
        # 这里曾经断言"四档严格递增"。北川把**史诗与传说的主选按耳朵对调**之后
        # 就不成立了 —— 时长不等于气势，两段大的谁更长是听感问题，
        # 不该由一条断言替用户决定。留下的才是真该守的那条：
        # **两段大的一定比两段小的长**，也就是"听得出递进"。
        check("史诗/传说明显长于普通/稀有（听得出递进）",
              max(small) < min(big),
              f"小档最长 {max(small):.2f}s < 大档最短 {min(big):.2f}s")
    else:
        check("抽卡四档都在", False, "缺 " + " ".join(k for k in tier_order
                                                   if k not in durations))

    # ---------------------------------------------------------------- 音量
    print("\n[4] 音量档位")
    names = [n for n, _ in sfxlib.VOLUME_STEPS]
    values = [v for _, v in sfxlib.VOLUME_STEPS]
    check("档位名不重复", len(names) == len(set(names)), str(names))
    check("音量值递增且都落在 0..1",
          all(a < b for a, b in zip(values, values[1:]))
          and all(0.0 <= v <= 1.0 for v in values),
          str(values))
    check("每一档都能被 volume_label 认回自己",
          all(sfxlib.volume_label(v) == n for n, v in sfxlib.VOLUME_STEPS))
    check("任意数值都有归属（不会返回空）",
          bool(sfxlib.volume_label(0.0)) and bool(sfxlib.volume_label(1.0))
          and bool(sfxlib.volume_label(0.42)))

    # ---------------------------------------------------------------- 播放器
    print("\n[5] 播放器")
    eng = sfxlib._ENGINE                                   # noqa: SLF001 —— 验收要看内部

    src_text = (ROOT / "pet" / "sfx.py").read_text(encoding="utf-8")
    check("后端是 pygame（音频设备常开，蓝牙上不用每次等握手）",
          sfxlib.backend().startswith("pygame"), sfxlib.backend())
    check("不再用 winsound（它每响一次都要开关一次音频设备）",
          "import winsound" not in src_text)
    check("不再靠 Qt 多媒体模块出声（那套会延迟、卡顿、放哑）",
          "from PySide6.QtMultimedia" not in src_text)
    # 找的是**定义**而不是名字：新模块的说明里正好要提到这两个被删掉的东西
    # （"以前为了补音量得把素材缩一份进临时目录"），按名字搜会误报。
    check("音量改成原生接口，不再往临时目录烘缩过的副本",
          "def _write_scaled" not in src_text and "_CACHE_ROOT =" not in src_text)

    # 只把"真正发声的那一步"换成记账：节流、事件级增益、事件表查找这些
    # **真逻辑**就都留在被测范围内了。整段替换 ``play`` 的话那些全绕过，
    # 测了等于没测。
    heard: list[tuple[str, float]] = []

    class _FakeSound:
        """发声对象的替身：记下「谁、以多大音量」响了。"""

        def __init__(self, key: str) -> None:
            self.key = key
            self._vol = 0.0

        def set_volume(self, value: float) -> None:
            self._vol = float(value)

        def play(self) -> None:
            heard.append((self.key, self._vol))

    real_sound_for = eng._sound_for                        # noqa: SLF001
    eng._sound_for = lambda key: _FakeSound(key)           # type: ignore[assignment]
    try:
        sfxlib.configure(True, 1.0)
        eng._last.clear()                                  # noqa: SLF001

        heard.clear()
        sfxlib.play("绝对不存在的事件")
        check("未知事件名不炸（只是不响）", heard == [], str(heard))

        heard.clear()
        sfxlib.play("poke")
        check("poke 一路走到发声那一步", [k for k, _ in heard] == ["poke"], str(heard))

        heard.clear()
        for _ in range(5):
            sfxlib.play("score")
        check("同一帧连发只算一次（节流）", len(heard) == 1, str(heard))

        eng._last.clear()                                  # noqa: SLF001
        heard.clear()
        sfxlib.play("pull_legend")
        sfxlib.play("poke")
        check("长音与短音能同时响（多路混音，不再需要「让路」那条规则）",
              [k for k, _ in heard] == ["pull_legend", "poke"], str(heard))

        # 事件级增益：弹跳天生比落地轻
        eng._last.clear()                                  # noqa: SLF001
        heard.clear()
        sfxlib.play("land")
        sfxlib.play("land_soft")
        got = dict(heard)
        check("弹跳比落地轻（land_soft 的 gain 生效）",
              got.get("land_soft", 9.0) < got.get("land", 0.0), str(got))
        check("增益就是事件表里那一个（不是散在调用点的魔法数）",
              abs(got.get("land_soft", 0.0) - sfxlib.BY_KEY["land_soft"].gain) < 1e-6
              and abs(got.get("land", 0.0) - 1.0) < 1e-6, str(got))

        eng._last.clear()                                  # noqa: SLF001
        heard.clear()
        sfxlib.configure(True, 0.5)
        sfxlib.play("poke")
        check("音量乘进发声对象（不再靠烘文件）",
              bool(heard) and abs(heard[0][1] - 0.5) < 1e-6, str(heard))

        sfxlib.configure(True, 4.0)
        check("音量被夹在 0..1（存档被改坏也不会爆音）",
              abs(sfxlib.current_volume() - 1.0) < 1e-6,
              f"{sfxlib.current_volume()}")

        sfxlib.configure(False, 0.5)
        check("关掉之后 is_enabled 为假", not sfxlib.is_enabled())
        check("音量被记住", abs(sfxlib.current_volume() - 0.5) < 1e-6)
        heard.clear()
        sfxlib.play("poke")
        check("关着的时候一声不吭", heard == [], str(heard))
    finally:
        eng._sound_for = real_sound_for                    # type: ignore[assignment]
        sfxlib.configure(True, 0.35)

    # 下面测触发点用记账版 ``play``：真跑 Engine 会被节流干扰，
    # 而节流刚在上面单独验过了。
    sfxlib.play = _spy                                     # type: ignore[assignment]
    CALLS.clear()
    sfxlib.play_for_tier("传说")
    check("play_for_tier 按档位派发", CALLS[-1] == "pull_legend", CALLS[-1])
    sfxlib.play_for_tier("没这个档")
    check("坏档位兜底到普通", CALLS[-1] == "pull_normal", CALLS[-1])
    # ---------------------------------------------------------------- 存档
    print("\n[6] 存档字段")
    fresh = Config()
    check("默认开着音效", fresh.sfx_enabled is True)
    check("默认音量是 0.7", abs(fresh.sfx_volume - 0.7) < 1e-6,
          f"{fresh.sfx_volume}")
    check("默认音量能对上某个档位", sfxlib.volume_label(fresh.sfx_volume) in names,
          sfxlib.volume_label(fresh.sfx_volume))

    config_path().write_text(json.dumps({"pos_x": 12}, ensure_ascii=False),
                             encoding="utf-8")
    old = Config.load()
    check("老存档（没有这两个字段）读进来仍是默认值",
          old.sfx_enabled is True and abs(old.sfx_volume - 0.7) < 1e-6,
          f"enabled={old.sfx_enabled} volume={old.sfx_volume}")

    # ---------------------------------------------------------------- 菜单
    print("\n[7] 菜单入口")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QMenu
    app = QApplication.instance() or QApplication([])          # noqa: F841

    bank = AssetBank(pet_asset_dir()).load()
    pet = PetWindow(Config(), bank)
    pet.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)

    check("开关表里有「音效」",
          any(t.field == "sfx_enabled" for t in menulib.TOGGLES),
          " / ".join(t.label for t in menulib.TOGGLES))

    menu = pet._build_menu()
    sfx_act = next((a for a in menu.actions() if a.text() == "音效"), None)
    check("右键菜单里有「音效」勾选", sfx_act is not None and sfx_act.isCheckable(),
          " / ".join(a.text() for a in menu.actions()))
    check("默认是勾上的", sfx_act is not None and sfx_act.isChecked())

    # ``action.menu()`` 的类型在 PySide6 存根里是 ``QObject | None``，
    # 用 isinstance 收窄成 QMenu（而不是 cast）—— 顺便真的验了它是个子菜单。
    vol_menu: QMenu | None = None
    for act in menu.actions():
        if act.text() == "音效音量":
            got = act.menu()
            vol_menu = got if isinstance(got, QMenu) else None
            break
    check("有「音效音量」子菜单", vol_menu is not None)
    if vol_menu is not None:
        labels = [a.text() for a in vol_menu.actions()]
        check("三档齐全", labels == names, " / ".join(labels))
        checked = [a.text() for a in vol_menu.actions() if a.isChecked()]
        check("勾的是当前那一档（默认「中」）",
              checked == [sfxlib.volume_label(pet.cfg.sfx_volume)],
              f"勾了 {checked}")

        # 点「响」这一档。**会真的走一遍 set_sfx_volume**，所以它同时也验了
        # "试听音效"那一下 —— 但账本记的是调用，不会真在机器上出声。
        CALLS.clear()
        loud = next(a for a in vol_menu.actions() if a.text() == "响")
        loud.trigger()
        check("点「响」之后存档音量变成 1.0",
              abs(pet.cfg.sfx_volume - 1.0) < 1e-6, f"{pet.cfg.sfx_volume}")
        check("调音量时试听了一声", since(0, "toggle"), str(CALLS))
        saved = json.loads(config_path().read_text(encoding="utf-8"))
        check("改动落进了 config.json", abs(float(saved.get("sfx_volume", -1)) - 1.0) < 1e-6,
              f"config.json 里是 {saved.get('sfx_volume')}")
        menu.grab().save(str(out_dir / "音效_菜单.png"))

    # 关掉之后音量档位整项应当消失
    assert sfx_act is not None                               # 上面那一项验过它在
    sfx_act.setChecked(False)                                # 触发 set_sfx_enabled
    check("取消勾选后存档里 enabled 为假", pet.cfg.sfx_enabled is False)
    menu_off = pet._build_menu()
    names_off = [a.text() for a in menu_off.actions()]
    check("音效关着时「音效音量」整项不出现",
          "音效音量" not in names_off, " / ".join(names_off))
    sfx_act_off = next((a for a in menu_off.actions() if a.text() == "音效"), None)
    check("但「音效」勾选还在（要能再打开）",
          sfx_act_off is not None and not sfx_act_off.isChecked())

    # 开回来，后面的触发点验收要靠它
    assert sfx_act_off is not None
    sfx_act_off.setChecked(True)
    check("重新勾上之后 enabled 为真", pet.cfg.sfx_enabled is True)
    menu.grab().save(str(out_dir / "音效_菜单.png"))

    # ---------------------------------------------------------------- 预热
    print("\n[8] 预热与设备占用")
    sfxlib.configure(False, 0.35)
    check("关着时 warmup 不做事（也就不去开设备）", sfxlib.warmup() == 0)

    sfxlib.configure(True, 0.35)
    n = sfxlib.warmup()
    check("warmup 覆盖全部事件", n == len(sfxlib.EVENTS), f"{n} 个事件")
    if sfxlib.backend().startswith("pygame"):
        check("预热之后音频设备是开着的（低延迟就靠这个）", eng.is_live())
        check("素材都读进了内存（之后响不用再读盘）",
              set(eng._sounds) == set(sfxlib.installed()),   # noqa: SLF001
              f"{len(eng._sounds)} 个")                      # noqa: SLF001

        # 关掉音效 = **把设备还回去**，不是"留着但不出声"。这条是给蓝牙耳机的：
        # 占着设备就等于占着它的蓝牙链路，会一直耗电。
        sfxlib.configure(False, 0.35)
        check("关掉音效就把音频设备还回去了", not eng.is_live())
        check("还设备时清掉了内存里的素材对象（quit 之后它们会失效）",
              not eng._sounds)                               # noqa: SLF001
        sfxlib.configure(True, 1.0)
        sfxlib.warmup()
        check("重新打开之后设备又开起来了", eng.is_live())
    else:
        check("音频后端不可用 —— 设备相关的检查跳过", True, sfxlib.backend())
    sfxlib.configure(True, 1.0)
    # ---------------------------------------------------------------- 触发点
    print("\n[9] 触发点是不是真的在响")
    sfxlib.configure(True, 1.0)

    # --- 窗口层：真的调一次动作，看账本里有没有
    CALLS.clear()
    pet._last_action.clear()
    pet.poke()
    check("逗它玩 -> poke", since(0, "poke"), str(CALLS))

    pet.cfg.coins = 999
    CALLS.clear()
    pet.buy("treat")
    check("小卖部买一件 -> buy", since(0, "buy"), str(CALLS))

    CALLS.clear()
    pet.use_item("treat")
    check("用掉吃的 -> feed（咀嚼声，不是确认音）",
          since(0, "feed") and not since(0, "use_item"), str(CALLS))

    CALLS.clear()
    pet.buy("ball")
    pet.use_item("ball")
    check("用掉玩具 -> use_item", since(0, "use_item"), str(CALLS))

    pet.cfg.free_feed_day = ""
    CALLS.clear()
    pet._last_action.clear()
    pet.feed()
    check("喂一口（免费那份）-> feed", since(0, "feed"), str(CALLS))

    pet.vitals.energy = 40.0
    CALLS.clear()
    pet._last_action.clear()
    pet.nap()
    check("叫它去睡 -> sleep", since(0, "sleep"), str(CALLS))

    # 抽卡要真的抽到卡才响：给足钱
    CALLS.clear()
    pet.cfg.coins = 9999
    pet.album.refresh_week()
    pulled = pet.pull_card()
    check("抽卡真的抽到了", pulled is not None)
    if pulled is not None:
        want = sfxlib.event_for_tier(pulled.card.tier)
        # 窗口层的 pull_card 不发声（发声在卡册面板那一下），
        # 所以这里直接验"按档位派发"，面板那一路见下面的静态核对
        sfxlib.play_for_tier(pulled.card.tier)
        check(f"抽到「{pulled.card.tier}」派发 {want}", since(0, want), str(CALLS))

    # 分解 / 装备：都要先有重复卡
    pet.cfg.coins = 9999
    dups = [cid for cid, n in pet.cfg.cards.items() if n >= 2]
    if dups:
        CALLS.clear()
        pet.dissolve_card(dups[0])
        check("分解重复卡 -> dissolve", since(0, "dissolve"), str(CALLS))
    else:
        check("分解重复卡 -> dissolve（跳过：这局没抽到重复）", True, "没有重复卡")

    owned = [cid for cid, n in pet.cfg.cards.items() if n >= 1]
    if owned:
        CALLS.clear()
        pet.equip_card(owned[0])
        check("装备一张卡 -> equip", since(0, "equip"), str(CALLS))

    CALLS.clear()
    pet.open_album()
    check("打开卡册 -> open_album", since(0, "open_album"), str(CALLS))

    # ⚠️ 「左右翻向」**不在这里真调**：它会往素材目录写 ``facing.json``
    # （``facinglib.write(pet_asset_dir(), ...)``），而素材目录是只读的、
    # ``_isolate`` 只隔离数据目录。真调一次就会在项目里留下一个
    # ``assets/pet/facing.json``。所以它改成在下面静态核对。

    # --- 卡册面板与小游戏：这些要造真场景，改成核对源码里那一行还在
    print("\n[10] 其余触发点（核对源码）")
    def source_has(rel: str, needle: str) -> bool:
        text = (ROOT / rel).read_text(encoding="utf-8")
        return needle in text

    check("卡册面板：翻页响 flip",
          source_has("pet/album_panel.py", 'sfxlib.play("flip")'))
    check("卡册面板：抽卡按稀有度派发",
          source_has("pet/album_panel.py", "play_for_tier(pull.card.tier)"))
    check("窗口层：左右翻向响 toggle",
          source_has("pet/window.py", 'sfxlib.play("toggle")'))
    for rel, event in (("game/minigame.py", '"score"'),
                       ("game/minigame.py", '"levelup"'),
                       ("game/catcher.py", '"score"'),
                       ("game/catcher.py", '"coin"'),
                       ("game/catcher.py", '"break"'),
                       ("game/runner.py", '"break"'),
                       ("game/g2048.py", '"score"'),
                       ("game/g2048.py", '"flip"'),
                       ("game/common.py", '"levelup" if self.score > 0 else "game_over"')):
        check(f"{rel} 响 {event}", source_has(rel, event))

    # ---------------------------------------------------------------- 回归
    print("\n[11] 四个症状的回归（本次修复）")
    from game import DEFAULT_GAME, create_game

    # 症状「没点它自己也出声」有三处源头，逐个钉死。
    #  (a) 启动时把狗摆到桌面上，接下来那一秒不该被判成"从空中落下"。
    #      **要跑够多帧**：它离地面只差 1 像素，单跑一帧只下落 0.6px、还没着地，
    #      就算有 bug 那帧也是 False —— 第一版断言就是这么漏过去的。
    pet.body.on_ground = False
    pet._restore_position()
    lands_at_boot = sum(1 for _ in range(60)               # 一秒 60 帧
                        if pet.body.update(1 / 60, pet._bounds(),
                                           use_gravity=True)["landed"])
    check("刚摆好位置后的一秒内不报落地（启动不响落地音）",
          lands_at_boot == 0, f"{lands_at_boot} 次")

    #  (b) 走路时 y 根本不变，不该反复报落地
    from pet.physics import Motion
    walker = Motion(w=128, h=128)
    walker.teleport(300.0, 952.0)                 # 1080 的屏幕，蹲在地面上
    walker.on_ground = True
    lands = 0
    for _ in range(240):                          # 4 秒 60fps 的一直走
        walker.vx = 120.0
        if walker.update(1 / 60, (0.0, 0.0, 1920.0, 1080.0),
                         use_gravity=True)["landed"]:
            lands += 1
    check("连走 4 秒，一次落地音都不该响", lands == 0, f"{lands} 次")

    #  (c) 换游戏 / 收起一局走的是"提前结算"那条路，不该响收尾音
    game = create_game(DEFAULT_GAME, bank, pet.cfg)
    game.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    game.score = 0
    CALLS.clear()
    game.close_settling()                         # 换游戏走的就是这条路
    check("换游戏/退出时提前结算，一声收尾音都不响", CALLS == [], str(CALLS))
    game.deleteLater()

    # 但真打完还得响 —— 别为了修这个把功能一起修没了
    game2 = create_game(DEFAULT_GAME, bank, pet.cfg)
    game2.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    game2.score = 0
    CALLS.clear()
    game2._finish(early=False)
    check("一局真的打完、颗粒无收 —— 仍然响 game_over",
          since(0, "game_over"), str(CALLS))
    game2.deleteLater()

    game3 = create_game(DEFAULT_GAME, bank, pet.cfg)
    game3.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    game3.score = 500
    CALLS.clear()
    game3._finish(early=False)
    check("一局打完、有得分 —— 仍然响 levelup", since(0, "levelup"), str(CALLS))
    game3.deleteLater()

    #  (d) 被砸下去时：弹起来那几下要另有一个更轻的音（land_soft）
    CALLS.clear()
    pet.body.teleport(float(pet._bounds()[0]) + 200.0, 0.0)
    pet.body.throw(0.0, 700.0)                    # 直接往下砸
    pet.body.on_ground = False
    for _ in range(300):                          # 最多跑 5 秒 60fps
        pet._advance(1 / 60)
        if CALLS.count("land"):
            break
    check("砸下去会响一次落地音", CALLS.count("land") == 1, str(CALLS))
    check("弹起来那几下另有更轻的音（land_soft）",
          CALLS.count("land_soft") >= 1 and "land_soft" in sfxlib.BY_KEY, str(CALLS))
    check("落地只响一次、弹跳可以不止一次（两个音不是同一个）",
          CALLS.count("land") == 1 and CALLS.count("land_soft") >= 1, str(CALLS))

    # 症状「卡顿」：一次播放占主线程多少时间。分两截量 ——
    # Engine 的簿记（查事件表、节流、增益），和真把声音交给音频后端。
    # 旧后端在这儿是几十毫秒级的调度，那才是"加了音效就卡"的来源。
    import time as _time
    eng2 = sfxlib._ENGINE                              # noqa: SLF001

    real_sound_for2 = eng2._sound_for                  # noqa: SLF001
    eng2._sound_for = lambda key: _FakeSound(key)      # type: ignore[assignment]
    try:
        t0 = _time.perf_counter()
        for _ in range(200):
            eng2._last.clear()                         # noqa: SLF001 —— 绕过节流
            eng2.play("poke")
        book_ms = (_time.perf_counter() - t0) / 200 * 1000
    finally:
        eng2._sound_for = real_sound_for2              # type: ignore[assignment]

    # 真后端那一次**换成静音素材**：这里要连播 200 次，用真音效就是 200 声
    # 砸在用户耳朵上。静音一样能量出"交给后端"的开销。
    silence = Path(tempfile.gettempdir()) / "desktop-pet-sfx-selftest.wav"
    with wave.open(str(silence), "wb") as o:
        o.setnchannels(1)
        o.setsampwidth(2)
        o.setframerate(44100)
        o.writeframes(b"\x00\x00" * 2205)             # 50 毫秒静音
    real_file_for = sfxlib.file_for
    sfxlib.file_for = lambda key: silence              # type: ignore[assignment]
    sfxlib.configure(True, 1.0)
    eng2._release()                                    # noqa: SLF001 —— 丢掉旧素材
    try:
        eng2.warmup(["poke"])                          # 开设备 + 读那份静音
        t0 = _time.perf_counter()
        for _ in range(200):
            eng2._last.clear()                         # noqa: SLF001
            eng2.play("poke")
        real_ms = (_time.perf_counter() - t0) / 200 * 1000
    finally:
        sfxlib.file_for = real_file_for                # type: ignore[assignment]
        eng2._release()                                # noqa: SLF001
        silence.unlink(missing_ok=True)
        sfxlib.warmup()
    check("一次播放占主线程不到 1ms（旧后端是几十毫秒级的调度）",
          book_ms + real_ms < 1.0,
          f"簿记 {book_ms:.3f}ms + 交给后端 {real_ms:.3f}ms")
    # ---------------------------------------------------------------- 清单
    print("\n[12] 验收产物")
    lines = ["# 音效清单", "",
             f"共 {len(sfxlib.EVENTS)} 个事件。音量三档："
             + "、".join(f"{n} {v * 100:.0f}%" for n, v in sfxlib.VOLUME_STEPS),
             "", "| 事件 | 说明 | 主文件时长 | 备选 |", "|---|---|---|---|"]
    for e in sfxlib.EVENTS:
        main_file = sfxlib.file_for(e.key)
        main_secs = f"{wav_seconds(main_file):.2f}s" if main_file.is_file() else "缺"
        alts = sorted(sfxlib.dir_path().glob(f"alternates/{e.key}_*.wav"))
        lines.append(f"| `{e.key}` | {e.title} · {e.about} | {main_secs} | "
                     f"{len(alts)} 份 |")
    report = out_dir / "音效清单.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    check("写出了音效清单", report.is_file(), str(report))
    check("写出了菜单截图", (out_dir / "音效_菜单.png").is_file())

    print("\n" + "=" * 46)
    if FAILS:
        print(f"通过 {PASSES} 项，失败 {len(FAILS)} 项")
        for name in FAILS:
            print(f"  - {name}")
        return 1
    print(f"通过 {PASSES} 项，失败 0 项")
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
