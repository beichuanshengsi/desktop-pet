"""无界面冒烟测试。

用 Qt 的 offscreen 平台插件跑，不弹任何窗口，把核心逻辑过一遍：
素材加载、桌宠状态机与物理、小游戏的跳跃与撞击判定、存档读写。

跑法：
    python tools/smoke_test.py

这是课程报告里"测试记录"那一节的直接素材。
"""

from __future__ import annotations

import math
import os
import random
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")     # 必须在 Qt 之前设

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image                                      # noqa: E402
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt     # noqa: E402
from PySide6.QtGui import QMouseEvent, QWheelEvent         # noqa: E402
from PySide6.QtWidgets import (QApplication, QMenu,        # noqa: E402
                               QPushButton, QWidget)

from pet import __version__                              # noqa: E402
from pet import facing                                   # noqa: E402
from pet import menu as menulib                          # noqa: E402
from pet.assets import STATES as ALL_STATES               # noqa: E402
from pet.assets import DEFAULT_SET, AssetBank, default_set_files  # noqa: E402
from pet.bag import Bag                                   # noqa: E402
from pet.behavior import Brain, State                     # noqa: E402
from pet.behavior import FPS as BFPS                      # noqa: E402
from pet.config import Config
from pet.paths import game_asset_dir, pet_asset_dir                     # noqa: E402
from pet.physics import (FLING_MAX, FLING_MIN, Motion, VelocitySampler,  # noqa: E402
                         clamp_fling)
from pet.pomodoro import (MAX_SECONDS, MIN_SECONDS, Pomodoro,  # noqa: E402
                          clamp_seconds, describe, format_clock)
from pet.vitals import FEED_GAIN, OFFLINE_FLOOR, PLAY_GAIN, Vitals  # noqa: E402
from pet.wheel import HOUR, MINUTE, SECOND, WheelModel     # noqa: E402
from pet.wheel_dialog import DurationDialog                # noqa: E402
from pet.panel import BagPanel                            # noqa: E402
from pet.window import PetWindow                          # noqa: E402
from game import COIN_PER_SCORE, GAMES, coins_for, create_game, game_kinds  # noqa: E402
from game.catcher import (BONE_SCORE, BONE_SIZE, CATCHER_W, COMBO_BONUS,  # noqa: E402
                          COMBO_STEP, DRIFT_MAX, FALLER_KINDS, FALL_LIMIT,
                          GRACE_SPAWNS, MAX_BOMB_STREAK, MAX_HP, PUPPY_SCORE,
                          RAMP_TIME, CatchGame, discover_puppy_prefixes,
                          load_sprites)
from game.common import GROUND_Y, W as GAME_W             # noqa: E402
from game.common import GameWindow                         # noqa: E402
from game.common import overlapping_zones                  # noqa: E402
from game.runner import (BASE_SPEED as RUN_BASE_SPEED,     # noqa: E402
                         FIRST_SPAWN_DIST, GAP_SEC_MIN, GAP_SEC_START,
                         HUD_WIDEST as RUN_HUD_WIDEST,
                         HUD_WIDEST_PX as RUN_HUD_WIDEST_PX,
                         HUD_ZONES as RUN_HUD_ZONES, KINDS as RUN_KINDS,
                         MAX_SPEED as RUN_MAX_SPEED, PATTERNS as RUN_PATTERNS,
                         PLAYER_W as RUN_PLAYER_W, PLAYER_X as RUN_PLAYER_X,
                         Rock as RunRock, Runner, SPEED_STEP_DIST,
                         gap_seconds_for, pick_pattern as run_pick_pattern,
                         speed_for, tier_for)
from game.runner import HUD_BAR as RUN_HUD_BAR             # noqa: E402
from game.runner import hud_zone_rect as run_hud_zone_rect  # noqa: E402
from game.g2048 import (Game2048, TARGET as G_TARGET,      # noqa: E402
                        UNDO_LIMIT as G_UNDO_LIMIT, can_move, coins_for_tile,
                        empty_grid, is_finished, max_tile,
                        move as g_move, slide_line, target_ratio)
from game.g2048 import HUD_WIDEST as G_HUD_WIDEST          # noqa: E402
from game.g2048 import HUD_WIDEST_PX as G_HUD_WIDEST_PX    # noqa: E402
from game.g2048 import HUD_ZONES as G_HUD_ZONES            # noqa: E402
from game.g2048 import hud_zone_rect as g_hud_zone_rect    # noqa: E402
from game.minigame import (BASE_HP as MG_BASE_HP,        # noqa: E402
                           BLOCK_H as MG_BLOCK_H,
                           BLOCK_W as MG_BLOCK_W, Block,
                           CLEAR_BONUS_TIME, CLEAR_BONUS_TIME_MIN,
                           COLS as MG_COLS, DROP_BY_KEY, Drop, HUD_ALIGN_RIGHT,
                           HUD_BAR, HUD_FONT, HUD_WIDEST, HUD_WIDEST_PX,
                           HUD_ZONES, MAX_HP as MG_MAX_HP,
                           MAX_TIME as MG_MAX_TIME, PLAYER as MG_PLAYER, Pop,
                           ROWS as MG_ROWS, SCORE_PER_HIT, TIME_BONUS, MiniGame,
                           combo_mult, hud_zone_rect)

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  ({detail})" if detail else ""))


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def _write_frame(path: Path, color: tuple[int, int, int]) -> None:
    """写一张 128×128 纯色透明 PNG 当测试素材。

    这一段以前跑的是 ``pet.styles``（代码画的两套风格）。那套生成器已随
    自绘素材一起删（2026-09-22）。测试真正要验的是"能加载 / 帧数对 /
    多套能分套"，纯色块就够，而且不用往仓库里塞任何图片文件。
    """
    Image.new("RGBA", (128, 128), (*color, 255)).save(path)


def main() -> int:
    qapp = QApplication(sys.argv)

    # ---------------------------------------------------------- 素材
    section("素材加载")
    # 临时造一组素材验 AssetBank：默认套 + 套 a，各 2 帧。
    # 一律写临时目录，绝不碰仓库里的真实素材（以前 overwrite 写 assets/pet，
    # 把用户换好的图覆盖回默认风格，踩过）。
    tmp_assets = Path(tempfile.mkdtemp(prefix="pet_assets_"))
    for state in ("idle", "walk"):
        for i in range(2):
            _write_frame(tmp_assets / f"{state}_{i:02d}.png", (200, 120, 80))
            _write_frame(tmp_assets / f"{state}_a_{i:02d}.png", (80, 160, 200))
    ib = AssetBank(tmp_assets).load()
    check("临时素材可加载", ib.ok())
    check("帧数与文件一致", ib.count("idle") == 2 and ib.count("walk") == 2,
          f"idle={ib.count('idle')} walk={ib.count('walk')}")
    check("同一状态的两套能被分开",
          set(ib.set_names("idle")) == {DEFAULT_SET, "a"},
          f"{sorted(ib.set_names('idle'))}")
    check("缺的状态借 idle 兜底",
          ib.count("poke") == 2 and "poke" in ib.fallback_used,
          f"poke={ib.count('poke')} 帧")

    # 真实素材目录（只读，不生成也不修改），后面窗口与小游戏的用例要用它
    bank = AssetBank(pet_asset_dir()).load()
    check("项目素材目录可加载", bank.ok())
    for state in ALL_STATES:
        check(f"{state} 帧数 >= 2", bank.count(state) >= 2,
              f"{bank.count(state)} 帧")

    # ---------------------------------------------------------- 存档
    section("配置存档")
    tmp = Path(tempfile.mkdtemp()) / "cfg.json"
    import pet.config as pcfg
    pcfg.config_path = lambda: tmp            # 临时改掉存档位置，别污染用户配置
    cfg = Config()
    cfg.pos_x, cfg.best_score, cfg.gravity = 123, 456, False
    cfg.save()
    back = Config.load()
    check("位置可持久化", back.pos_x == 123, f"pos_x={back.pos_x}")
    check("最高分可持久化", back.best_score == 456, f"best={back.best_score}")
    check("布尔量可持久化", back.gravity is False)

    tmp.write_text("{ 这不是合法 JSON", encoding="utf-8")
    check("坏存档不崩溃", isinstance(Config.load(), Config))

    # ---------------------------------------------------------- 状态机
    section("行为状态机")
    # speed=1.0，让 IDLE 时长维持在 2.2~6.5 秒，断言才不会被随机漫步打乱
    brain = Brain(auto_walk=True, speed=1.0)
    check("初始为 IDLE", brain.state is State.IDLE)
    brain.drag_start()
    check("拖拽 -> DRAG", brain.state is State.DRAG)
    brain.drag_end()
    check("松手 -> FALL", brain.state is State.FALL)
    brain.update(0.1, on_ground=True)
    check("落地 -> IDLE", brain.state is State.IDLE)
    brain.poke(seconds=0.6)
    check("点击 -> POKE", brain.state is State.POKE)
    for _ in range(14):                   # 0.7s：越过 0.6s 的动作，又远不到下次漫步
        brain.update(0.05, on_ground=True)
    check("POKE 播完自动回 IDLE", brain.state is State.IDLE, brain.state.value)

    brain.feed(seconds=0.6)
    check("投喂 -> FEED", brain.state is State.FEED)
    brain.update(1.0, on_ground=True)     # 一次跨过整个时长
    check("FEED 播完自动回 IDLE", brain.state is State.IDLE, brain.state.value)

    check("逗它玩和喂一口是两个状态、两套贴图",
          State.POKE is not State.FEED and State.POKE.value != State.FEED.value,
          f"{State.POKE.value} / {State.FEED.value}")

    brain.drag_start()
    brain.poke(seconds=0.6)
    check("拎着的时候点击不打断拖拽", brain.state is State.DRAG)
    brain.drag_end()
    brain.update(0.1, on_ground=True)

    brain2 = Brain(auto_walk=True, speed=30.0)
    states = set()
    for _ in range(600):
        brain2.update(0.05, on_ground=True)
        states.add(brain2.state)
    check("长时间运行会自发产生漫步", State.WALK in states,
          "/".join(sorted(s.value for s in states)))

    brain3 = Brain(auto_walk=False, speed=30.0)
    seen = set()
    for _ in range(600):
        brain3.update(0.05, on_ground=True)
        seen.add(brain3.state)
    check("关闭自动漫步后不再行走", State.WALK not in seen)

    # ---------------------------------------------------------- 朝向
    section("贴图朝向")
    face_tmp = Path(tempfile.mkdtemp(prefix="pet_face_"))
    check("没有声明文件时按默认朝右", facing.read(face_tmp) == 1)
    facing.write(face_tmp, "left")
    check("声明朝左能读回", facing.read(face_tmp) == -1)
    check("朝左素材 向右走要镜像", facing.should_mirror(1, -1) is True)
    check("朝左素材 向左走不镜像", facing.should_mirror(-1, -1) is False)
    check("朝右素材 向右走不镜像", facing.should_mirror(1, 1) is False)
    check("朝右素材 向左走要镜像", facing.should_mirror(-1, 1) is True)

    facing.meta_path(face_tmp).write_text("???", encoding="utf-8")
    check("声明写坏了也不崩，退回默认", facing.read(face_tmp) == 1)
    try:
        facing.write(face_tmp, "up")
        bad_rejected = False
    except ValueError:
        bad_rejected = True
    check("非法朝向值被拒绝", bad_rejected)

    # 一个动作有好几套素材时，各套是分开下的图，原图方向未必一致 ——
    # 所以朝向声明要能"按套覆盖"，key 用素材前缀（walk_a，跟文件名对得上）
    sets_tmp = Path(tempfile.mkdtemp(prefix="pet_face_sets_"))
    facing.write(sets_tmp, "left",
                 sets={"walk_a": "right", "poke_b": 1, "坏的": "up"})
    check("按套朝向能读回，非法值直接丢",
          facing.read_sets(sets_tmp) == {"walk_a": 1, "poke_b": 1},
          f"{facing.read_sets(sets_tmp)}")
    check("按套朝向按素材前缀查：walk_a 被覆盖成朝右",
          facing.base_for(-1, facing.read_sets(sets_tmp), "walk", "a") == 1)
    check("没单独声明的套跟随目录默认",
          facing.base_for(-1, facing.read_sets(sets_tmp), "walk", "") == -1)
    check("套名不跨状态串台：poke_a 不受 walk_a 影响",
          facing.base_for(-1, facing.read_sets(sets_tmp), "poke", "a") == -1)
    facing.write(sets_tmp, "right")
    check("只改总朝向不会抹掉按套声明",
          facing.read_sets(sets_tmp) == {"walk_a": 1, "poke_b": 1},
          f"{facing.read_sets(sets_tmp)}")
    facing.write(sets_tmp, "left", sets={})
    check("显式传空表 = 清掉按套声明", facing.read_sets(sets_tmp) == {})

    # 实际生效的这套素材：walk_a 原图方向与其余相反，必须单独声明，否则倒着走
    real_dir = pet_asset_dir()
    real_base = facing.read(real_dir)
    real_sets = facing.read_sets(real_dir)
    if "walk_a" in real_sets:
        check("现役素材 默认套：向右走要镜像",
              facing.should_mirror(
                  1, facing.base_for(real_base, real_sets, "walk", "")) is True)
        check("现役素材 walk_a：向右走不镜像（按套声明生效）",
              facing.should_mirror(
                  1, facing.base_for(real_base, real_sets, "walk", "a")) is False)

    # 只提示不断言：换素材后有没有写声明是使用者的事，
    # 但"没声明就是按默认朝右算"这件事值得在测试输出里露一面
    meta = facing.meta_path(pet_asset_dir())
    print(f"  [INFO] 当前素材朝向：{'左' if facing.current() < 0 else '右'}"
          f"（{'已声明 ' + meta.name if meta.exists() else '未声明，按默认'}）")

    # ---------------------------------------------------------- 物理
    section("物理")
    body = Motion(x=100, y=0, w=128, h=128)
    bounds = (0.0, 0.0, 1920.0, 1000.0)
    for _ in range(200):
        body.update(1 / 60, bounds, use_gravity=True)
    check("自由落体会停在地面", body.on_ground and abs(body.y + 128 - 1000) < 1,
          f"y={body.y:.1f}")
    check("重力下速度归零", abs(body.vy) < 1e-6)

    body.teleport(1800, 500)
    body.throw(900, 0)
    for _ in range(120):
        body.update(1 / 60, bounds, use_gravity=False)
    check("撞右边界被夹住", body.x + 128 <= 1920.0 + 1e-6, f"x={body.x:.1f}")

    body.gravity = 0.0
    body.edge_bounce = True
    body.teleport(1700, 100)
    body.throw(600, 0)
    for _ in range(120):                  # 0.5s 只走 300px，要够它撞到 1792 边界
        body.update(1 / 60, bounds, use_gravity=False)
    check("开启反弹后反向", body.vx < 0, f"vx={body.vx:.1f}")

    # ---------------------------------------------------------- 桌宠窗口
    section("桌宠窗口")
    pet = PetWindow(cfg, bank)
    pet.show()
    pos0 = (pet.body.x, pet.body.y)
    for _ in range(300):
        pet._advance(1 / 30)
    check("连续 10 秒逻辑无异常", True)
    check("宠物仍在屏幕内",
          0 <= pet.body.x <= 4096 and 0 <= pet.body.y <= 4096,
          f"({pet.body.x:.0f},{pet.body.y:.0f})")
    check("窗口尺寸与贴图一致", pet.width() == pet._size, f"{pet.width()}px")

    pet._last_action.clear()
    pet.poke()
    check("点击后进入 POKE", pet.brain.state in (State.POKE, State.FALL),
          pet.brain.state.value)
    # 每次点击会随机挑一套素材，所以时长要按**这次挑中的那一套**算
    want = max(1, pet.bank.count("poke", pet._sprite_set.get("poke"))) / BFPS[State.POKE]
    check("逗它玩时长 = 素材帧数 ÷ 帧率（恰好播完一圈）",
          abs(pet.brain._duration - want) < 1e-6, f"{want:.2f}s")

    pet._last_action.clear()              # feed 有自己的冷却，这里只是别被打断
    pet.feed()
    check("投喂后进入 FEED", pet.brain.state in (State.FEED, State.FALL),
          pet.brain.state.value)
    want_feed = max(1, pet.bank.count("feed", pet._sprite_set.get("feed"))) / BFPS[State.FEED]
    check("喂一口时长 = 素材帧数 ÷ 帧率",
          abs(pet.brain._duration - want_feed) < 1e-6, f"{want_feed:.2f}s")

    for _ in range(int(want_feed * 30) + 6):   # 足够放完喂一口
        pet._advance(1 / 30)
    check("动作播完不卡在 FEED", pet.brain.state is not State.FEED,
          pet.brain.state.value)

    # ---------------------------------------------------------- 重力开关
    # 这个开关曾经是空的：判定写成 ``cfg.gravity or not on_ground``，
    # 脚一离地就再补一次重力，于是勾不勾都往下掉。
    section("重力下坠开关")
    free = Motion(x=100, y=100, w=128, h=128)
    for _ in range(120):
        free.update(1 / 60, bounds, use_gravity=False)
    check("物理层：不给重力就不动", abs(free.y - 100.0) < 1e-6, f"y={free.y:.1f}")

    gcfg = Config()                       # 独立存档对象，save 落到上面的临时路径
    gpet = PetWindow(gcfg, bank)
    gpet.body.teleport(200.0, 120.0)      # 摆到半空（地面在最下面）
    gpet.body.on_ground = False
    gcfg.gravity = False
    for _ in range(40):
        gpet._advance(1 / 30)
    check("关掉重力：悬在半空不下坠",
          abs(gpet.body.y - 120.0) < 1e-6 and not gpet.body.on_ground,
          f"y={gpet.body.y:.1f}")

    gcfg.gravity = True
    for _ in range(240):
        gpet._advance(1 / 30)
    floor = gpet._bounds()[3] - gpet.body.h
    check("打开重力：照旧落到地面并站住",
          gpet.body.on_ground and abs(gpet.body.y - floor) < 2.0,
          f"y={gpet.body.y:.1f} / 地面 {floor:.1f}")

    gpet._last_action.clear()
    gcfg.gravity = False
    gpet.poke()
    check("关掉重力时点击不起跳（否则会一路飘到天花板）",
          gpet.body.vy == 0.0 and gpet.body.on_ground, f"vy={gpet.body.vy:.0f}")
    check("关掉重力不影响逗它玩本身", gpet.brain.state is State.POKE,
          gpet.brain.state.value)

    gcfg.gravity = False
    gpet.brain.drag_start()
    gpet.body.teleport(300.0, 150.0)
    gpet.body.on_ground = False
    gpet.brain.drag_end(gravity=bool(gcfg.gravity))
    check("关掉重力：松手不进 FALL（它等不到落地）",
          gpet.brain.state is State.IDLE, gpet.brain.state.value)
    for _ in range(40):
        gpet._advance(1 / 30)
    check("关掉重力：松手停在哪就悬在哪", abs(gpet.body.y - 150.0) < 1e-6,
          f"y={gpet.body.y:.1f}")

    gcfg.gravity = True
    gpet.brain.drag_start()
    gpet.brain.drag_end()                 # 默认 gravity=True，行为与老版本一致
    check("打开重力：松手照旧进 FALL", gpet.brain.state is State.FALL,
          gpet.brain.state.value)
    gpet.set_gravity(False)
    check("下坠途中关掉重力：立刻退出 FALL，不留半空演下坠",
          gpet.brain.state is not State.FALL and gpet.body.vy == 0.0,
          gpet.brain.state.value)
    gpet.hide()                           # 不许 close()：closeEvent 会写存档

    # ---------------------------------------------------------- 多套素材
    section("一个动作多套素材（随机播）")
    poke_sets = bank.set_names("poke")
    feed_sets = bank.set_names("feed")
    check("poke 有多套素材可选", len(poke_sets) >= 2, f"{poke_sets}")
    check("feed 有多套素材可选", len(feed_sets) >= 2, f"{feed_sets}")
    check("每套素材都真的有帧",
          all(bank.count("poke", n) >= 2 for n in poke_sets),
          str([(n, bank.count("poke", n)) for n in poke_sets]))

    pet.rng.seed(20260921)
    seen = set()
    for _ in range(30):
        pet._last_action.clear()
        pet.poke()
        seen.add(pet._sprite_set["poke"])
    check("连点 30 次会随机到不同的套", len(seen) >= 2, f"出现过 {sorted(seen)}")
    check("随机到的套都能取到帧",
          all(bank.count("poke", n) >= 2 for n in seen))

    # 连着两次点到同一套会让人觉得"怎么没变"，所以挑的时候排除上一套
    pet.rng.seed(7)
    seq = []
    for _ in range(12):
        pet._last_action.clear()
        pet.poke()
        seq.append(pet._sprite_set["poke"])
    check("连续两次不会重复同一套",
          all(a != b for a, b in zip(seq, seq[1:])), " ".join(s or "-" for s in seq))

    # 时长必须跟着"这次选中的套"走：几套帧数不同，不能拿同一套的帧数糊弄
    na, nb = bank.count("poke", "a"), bank.count("poke", "b")
    pet._sprite_set["poke"] = "a"
    da = pet._oneshot_seconds(State.POKE)
    pet._sprite_set["poke"] = "b"
    db = pet._oneshot_seconds(State.POKE)
    check("不同套各自按自己的帧数算时长",
          abs(da - na / BFPS[State.POKE]) < 1e-6
          and abs(db - nb / BFPS[State.POKE]) < 1e-6,
          f"a={na}帧→{da:.2f}s  b={nb}帧→{db:.2f}s")

    # 只有一套素材时不该假装随机：drag 目前就一套
    drag_sets = bank.set_names("drag")
    check("未分套的状态只报一套（drag）",
          len(drag_sets) == 1 and bank.count("drag", drag_sets[0]) >= 2,
          f"{drag_sets}")

    # 预览/校验脚本用 default_set_files 取帧。它必须只给默认套 ——
    # 直接 glob("poke_*.png") 会把三套拼成一条 43 帧的序列（踩过）。
    dflt = default_set_files(pet_asset_dir(), "poke")
    check("default_set_files 只取默认套（不混多套）",
          len(dflt) == bank.count("poke") and len(dflt) < len(list(
              pet_asset_dir().glob("poke_*.png"))),
          f"{len(dflt)} 个：{[q.name for q in dflt][:3]}…")
    check("default_set_files 结果里没有带套名的文件",
          all("_a_" not in q.stem and "_b_" not in q.stem for q in dflt))

    # idle 仍不参与随机：它要在状态里停好几秒，中途换套画面会跳一下
    pet.brain.state = State.IDLE
    check("idle 不指定套（走默认素材）", pet._current_set() is None)

    # walk 反过来 —— 起步那一刻挑一套，整段行走保持不换（_track_state 负责）
    walk_sets = bank.set_names("walk")
    check("walk 有多套素材可选", len(walk_sets) >= 2, f"{walk_sets}")
    pet.rng.seed(20260922)
    pet.brain.state = State.IDLE
    pet._last_state = State.IDLE
    picked = []
    for _ in range(8):
        pet.brain.state = State.IDLE
        pet._track_state()               # 回到待机，不该挑套
        pet.brain.state = State.WALK
        pet._track_state()               # 起步 —— 挑套发生在这里
        picked.append(pet._current_set())
    check("每次起步都会重新挑套", len(set(picked)) >= 2,
          " ".join(p or "-" for p in picked))
    check("两套 walk 素材交替（不连着重复同一套）",
          all(a != b for a, b in zip(picked, picked[1:])),
          " ".join(p or "-" for p in picked))

    mid = pet._current_set()
    for _ in range(20):                  # 模拟行走途中连跑 20 帧
        pet._track_state()
    check("行走途中不换套（一趟走法保持一致）", pet._current_set() == mid, f"{mid}")

    # 多套素材也必须真的能画出来（纯逻辑断言测不到 paintEvent）
    pet._sprite_set["poke"] = "a"
    pet.brain.state = State.POKE
    shot = pet.grab()
    check("多套素材能渲染出一帧",
          not shot.isNull() and shot.width() == pet.width(),
          f"{shot.width()}x{shot.height()}")

    # walk 的每一套都要能画：帧数不同（8 / 14），_sync_anim 得跟着重算
    for name in walk_sets:
        pet._sprite_set["walk"] = name
        pet.brain.state = State.WALK
        pet._sync_anim(True)
        img = pet.grab()
        check(f"walk 的套「{name or '默认'}」能渲染出一帧",
              not img.isNull() and img.width() == pet.width(),
              f"{img.width()}x{img.height()}，{bank.count('walk', name)} 帧")

    # 按套声明的朝向要真的落到画面上：同一套素材左右走必须画出不同的两帧
    for name in walk_sets:
        pet._sprite_set["walk"] = name
        pet.brain.state = State.WALK
        pet.brain.facing = 1
        pet._sync_anim(True)
        shot_r = pet.grab().toImage()
        pet.brain.facing = -1
        shot_l = pet.grab().toImage()
        check(f"套「{name or '默认'}」左走/右走画出的帧不一样（镜像真的生效）",
              shot_r != shot_l)
    pet.brain.state = State.IDLE

    pet._last_action.clear()
    check("连点保护：同一动作 0.35s 内只放行一次",
          pet._action_ready("poke") and not pet._action_ready("poke"))
    check("连点保护只挡自己，不挡另一个动作",
          pet._action_ready("feed"))

    pet.apply_scale(1.5)
    check("缩放生效", pet.width() == int(128 * 1.5), f"{pet.width()}px")
    pet.apply_scale(1.0)

    pet.close()

    # ---------------------------------------------------------- 小游戏
    section("小游戏")
    cfg.best_score = 0                     # 前面的存档测试把它改成过 456
    game = MiniGame(bank, cfg)
    game.show()
    check("开局方块数正确", len(game.blocks) >= 10, f"{len(game.blocks)} 块")
    check("初始得分 0", game.score == 0)

    # 把球挪到某个方块正下方，再起跳，验证一定能撞到
    target = game.blocks[0]
    game.ball.teleport(target.body.x + 16, 400)
    game.ball.on_ground = False
    game.ball.throw(0.0, -1000.0)
    before = game.score
    for _ in range(160):
        game._step(1 / 60)
    check("起跳能撞碎方块并加分", game.score > before,
          f"{before} -> {game.score}")

    # 打光所有方块应当进入下一轮并有奖励分
    cleared_before = game.score
    game.blocks.clear()
    game._step(1 / 60)
    check("清空本轮回合数 +1", game.round_no == 2, f"round={game.round_no}")
    check("通关有奖励分", game.score == cleared_before + 50, f"{game.score}")
    check("新回合重新生成方块", len(game.blocks) > 0, f"{len(game.blocks)} 块")

    # 左右移动
    from PySide6.QtCore import Qt as _Qt
    game.keys.add(_Qt.Key.Key_Right)
    x0 = game.ball.x
    for _ in range(60):
        game._step(1 / 60)
    check("按右键向右移动", game.ball.x > x0, f"{x0:.0f} -> {game.ball.x:.0f}")
    game.keys.clear()

    # 时间耗尽 -> 结算
    game.time_left = 0.02
    game._advance(0.05)
    check("时间到进入结算", game.over)
    check("最高分被记录", cfg.best_score == game.score, f"best={cfg.best_score}")
    game.close()

    # ------------------------------------------- 弹跳得分 · v2.1.0 的玩法改动
    section("弹跳得分 · 耐久 / 连击 / 道具")

    # 这一节验的是这次改动的四条新规则：方块有耐久、"敲不穿"和"敲穿了"是
    # 两种完全不同的处境、连击有倍率、敲碎会掉道具。
    # 旧版一碰就碎，根本产生不了这些状态 —— 所以这些用例在旧代码下必挂，
    # 它们就是这次重写的回归网。
    mg = MiniGame(bank, cfg)
    mg.show()
    check("开局满盘", len(mg.blocks) == MG_ROWS * MG_COLS,
          f"{len(mg.blocks)} 块")

    # ---- 耐久梯度：越靠上越硬，轮次越高整体越硬，但封顶
    mg.round_no = 1
    check("第 1 轮：越靠上越硬",
          mg.hp_for(0) > mg.hp_for(MG_ROWS - 1),
          f"上 {mg.hp_for(0)} 下 {mg.hp_for(MG_ROWS - 1)}")
    check("第 1 轮：脚边那排只要 1 下",
          mg.hp_for(MG_ROWS - 1) == MG_BASE_HP, f"{mg.hp_for(MG_ROWS - 1)} 下")
    mg.round_no = 2
    check("轮次越高整体越硬", mg.hp_for(MG_ROWS - 1) == MG_BASE_HP + 1,
          f"{mg.hp_for(MG_ROWS - 1)} 下")
    mg.round_no = 99
    check("耐久封顶在 MAX_HP（不封顶就从难变成磨）",
          mg.hp_for(0) == MG_MAX_HP and mg.hp_for(MG_ROWS - 1) == MG_MAX_HP,
          f"{MG_MAX_HP} 下")

    # ---- 清台加时：越往后加得越少，但有下限
    mg.round_no = 1
    check("第 1 轮清台加满分",
          mg.clear_time_bonus() == CLEAR_BONUS_TIME, f"+{mg.clear_time_bonus():.0f}s")
    mg.round_no = 3
    check("轮次越靠后加时越少",
          mg.clear_time_bonus() < CLEAR_BONUS_TIME, f"+{mg.clear_time_bonus():.0f}s")
    mg.round_no = 99
    check("加时不会掉到 0（有个下限）",
          mg.clear_time_bonus() == CLEAR_BONUS_TIME_MIN,
          f"+{mg.clear_time_bonus():.0f}s")

    # ---- 连击倍率：计分和 HUD 共用同一个阶梯，改了不会两边不一致
    check("连击倍率：1~2 连是 ×1",
          combo_mult(1) == 1 and combo_mult(2) == 1)
    check("连击倍率：3 连起 ×2", combo_mult(3) == 2 and combo_mult(5) == 2)
    check("连击倍率：6 连起 ×3，再往上不涨",
          combo_mult(6) == 3 and combo_mult(99) == 3)

    def fresh_block(hp: int = 3) -> Block:
        """一个孤立方块，摆在固定位置，让"球顶上去"这件事可复现。"""
        return Block(200.0, 300.0, 1, hp)

    def ram_ball(mg_, dy: float, vy: float) -> None:
        """把球摆到方块横向居中、纵向偏移 dy 的地方，并给它一个初速。"""
        mg_.ball.teleport(200.0 + (MG_BLOCK_W - MG_PLAYER) / 2, 300.0 + dy)
        mg_.ball.vy = vy
        mg_.ball.on_ground = False

    # ---- 核心规则：没敲碎 = 一堵墙；敲碎了 = 放行
    brick = fresh_block(hp=3)
    mg.score = 0
    mg.combo = 0
    mg.double_left = 0.0
    ram_ball(mg, MG_BLOCK_H - 6, -900.0)          # 球顶在方块底面，正在上飞
    mg._hit_block(brick, power=False)
    check("敲一下扣一点耐久",
          brick.hp == 2 and brick.alive and brick.damage > 0,
          f"hp={brick.hp}/{brick.max_hp}")
    check("没敲碎的方块把球挡回来（顶到的是底面）", mg.ball.vy > 0,
          f"vy={mg.ball.vy:.0f}")
    check("敲一下记 SCORE_PER_HIT 分", mg.score == SCORE_PER_HIT,
          f"{mg.score} 分")

    broken = fresh_block(hp=1)
    mg.score = 0
    mg.combo = 0
    ram_ball(mg, MG_BLOCK_H - 6, -880.0)
    mg._hit_block(broken, power=False)
    check("耐久归零的方块出局", not broken.alive)
    check("敲碎之后球原样继续往上（不被弹回，连击就来自这里）",
          mg.ball.vy == -880.0, f"vy={mg.ball.vy:.0f}")

    tank = fresh_block(hp=MG_MAX_HP)
    ram_ball(mg, MG_BLOCK_H - 6, -900.0)
    mg._hit_block(tank, power=True)
    check("「力」生效时满耐久方块也一击必碎", not tank.alive)

    lid = fresh_block(hp=3)
    ram_ball(mg, -MG_PLAYER + 6, 700.0)           # 球在方块上面，正在下落
    mg._hit_block(lid, power=False)
    check("从上面踩到没碎的方块 → 借力弹起", mg.ball.vy < 0,
          f"vy={mg.ball.vy:.0f}")

    # ---- 计分真的乘上了倍率（不是只写在 HUD 上）
    mg.score = 0
    mg.combo = 2                                  # 下一击就是第 3 连
    ram_ball(mg, MG_BLOCK_H - 6, -900.0)
    mg._hit_block(fresh_block(hp=1), power=False)
    check("第 3 连按 ×2 计分", mg.score == SCORE_PER_HIT * 2, f"{mg.score} 分")

    mg.score = 0
    mg.combo = 0
    mg.double_left = 5.0                          # 假装刚接到「分」
    ram_ball(mg, MG_BLOCK_H - 6, -900.0)
    mg._hit_block(fresh_block(hp=1), power=False)
    mg.double_left = 0.0
    check("「分」生效时得分再翻一倍", mg.score == SCORE_PER_HIT * 2,
          f"{mg.score} 分")

    # ---- 掉落道具
    mg.picked = 0
    mg.power_left = mg.double_left = 0.0
    mg.time_left = 30.0
    mg._take_drop(Drop(0.0, 0.0, DROP_BY_KEY["time"]))
    check("「时」加时", mg.time_left == 30.0 + TIME_BONUS, f"{mg.time_left:.0f}s")
    mg._take_drop(Drop(0.0, 0.0, DROP_BY_KEY["power"]))
    check("「力」进入限时状态", mg.power_left > 0, f"{mg.power_left:.0f}s")
    mg._take_drop(Drop(0.0, 0.0, DROP_BY_KEY["double"]))
    check("「分」进入限时状态", mg.double_left > 0, f"{mg.double_left:.0f}s")
    check("接住一个就记一个", mg.picked == 3, f"{mg.picked} 个")

    mg.time_left = MG_MAX_TIME - 1.0
    mg._take_drop(Drop(0.0, 0.0, DROP_BY_KEY["time"]))
    check("加时有天花板（不然手气好的一局能拖到十分钟）",
          mg.time_left == MG_MAX_TIME, f"{mg.time_left:.0f}s")

    mg.power_left = 0.0
    mg.ball.teleport(200.0, 200.0)
    mg.ball.on_ground = False
    mg.drops = [Drop(200.0, 200.0, DROP_BY_KEY["power"])]
    mg._step_drops(1 / 60)
    check("球碰到掉下来的道具就接住", mg.power_left > 0 and not mg.drops,
          f"场上还剩 {len(mg.drops)} 个")

    mg.time_left = 30.0
    mg.drops = [Drop(0.0, GROUND_Y - 40, DROP_BY_KEY["time"])]
    mg.ball.teleport(float(GAME_W - MG_PLAYER), float(GROUND_Y - MG_PLAYER))
    for _ in range(120):
        mg._step_drops(1 / 60)
    check("没接住的道具掉地上就消失（不会白送）",
          not mg.drops and mg.time_left == 30.0, f"场上还剩 {len(mg.drops)} 个")

    mg.rng.seed(4242)
    roll_a = [mg._pick_drop().key for _ in range(8)]
    mg.rng.seed(4242)
    roll_b = [mg._pick_drop().key for _ in range(8)]
    check("掉落抽奖走实例随机源（同种子同结果，测试才可复现）",
          roll_a == roll_b and set(roll_a) <= set(DROP_BY_KEY),
          "/".join(roll_a))

    # ---- 汇率没被打崩
    # 一块最多要敲 MAX_HP 下，所以"每下给几分"必须跟着调 —— 不调的话
    # 同一局的分数会翻好几倍，小卖部的金币立刻通胀。这里按"第 1 轮满盘
    # 全清"算一遍边界：最差（全程断连击）到最好（全程 ×3）折算出来
    # 仍然落在 common.py 里「打一局够买一两样」的设计区间内。
    mg.round_no = 1
    swings = sum(mg.hp_for(r) for r in range(MG_ROWS)) * MG_COLS
    low, high = swings * SCORE_PER_HIT, swings * SCORE_PER_HIT * 3
    check("改完耐久之后金币量级没变（一局仍够买最贵的那样）",
          coins_for(low) < 30 <= coins_for(high),
          f"一局 {low}~{high} 分 → {coins_for(low)}~{coins_for(high)} 金币")

    # ---- 走完整循环再验一遍"墙"和"穿透"
    #      上面验的是 _hit_block 单个函数，这里让球真的跳一次，
    #      确认在真正的物理循环里也是同一个结果。
    def height_of(target_row: int, hard: bool) -> float:
        """把整盘设成同一硬度，球从最下面跳起来，返回这一跳最高摸到哪。

        每帧把掉落道具清掉、限时状态抹平。不是作弊 —— 是这一用例只问
        "几何上过不过得去"：16% 的掉落率一旦掉出「一击必碎」又正好被球
        接住，后面几排会被一路打穿，测到的就不是"墙"了。
        （那个连锁本身是对的设计，只是不该混进几何判定。）
        """
        mg._reset_scene(first=True)
        for b in mg.blocks:
            b.hp = b.max_hp = 9 if (hard or b.row != MG_ROWS - 1) else 1
        mg.score = 0
        mg.combo = 0
        start = [b for b in mg.blocks if b.row == target_row][0]
        mg.ball.teleport(start.body.x + (MG_BLOCK_W - MG_PLAYER) / 2,
                         float(GROUND_Y - MG_PLAYER))
        mg.ball.on_ground = True
        mg._jump()
        top = mg.ball.y
        for _ in range(120):
            mg._step(1 / 60)
            mg.drops.clear()
            mg.power_left = mg.double_left = 0.0
            top = min(top, mg.ball.y)
        return top

    mg._reset_scene(first=True)
    bottom_y = [b for b in mg.blocks if b.row == MG_ROWS - 1][0].body.y
    up_y = [b for b in mg.blocks if b.row == MG_ROWS - 2][0].body.y

    blocked = height_of(MG_ROWS - 1, hard=True)
    check("全盘都是墙时，球过不了最下面这一排",
          blocked > bottom_y, f"最高 y={blocked:.0f}，下排上沿 y={bottom_y:.0f}")

    punched = height_of(MG_ROWS - 1, hard=False)
    check("下排能敲穿时，球能顶到上一排（这就是连击的来路）",
          up_y < punched < bottom_y,
          f"最高 y={punched:.0f}，落在 {up_y:.0f}~{bottom_y:.0f} 之间")

    # ---- 整帧画得出来（裂纹 / 道具 / 连击 / 限时状态四条绘制路径都要走）
    mg._reset_scene(first=True)
    mg.blocks[0].hp = 1                            # 弄出裂纹
    mg.drops = [Drop(300.0, 140.0, DROP_BY_KEY["power"])]
    mg.pops.append(Pop(300.0, 200.0, "+10"))
    mg.combo = 4
    mg.best_combo = 6
    mg.power_left = 4.0
    mg.double_left = 3.0
    frame = mg.grab()
    check("整帧画得出来（含裂纹/道具/连击/限时状态）",
          not frame.isNull() and frame.width() == GAME_W,
          f"{frame.width()}×{frame.height()}")

    # ---- HUD 排版：不许有两段文字落在同一片像素上
    # 这条是**真踩过之后补的**：第一版 HUD 把「最高 385」和
    # 「第 2 轮 · 剩 17 块」画到了同一段 x 上，两个字叠着印在一起。
    # 逻辑用例一条都测不出来 —— 只有把验收图放大看才看见。
    # 所以位置抽成了 HUD_ZONES / HUD_FONT 两张表，这里对表做纯几何检查：
    #   **不查字体度量**（offscreen 平台没有字体库，量出来是方框的宽度，
    #   拿它断言会误报），只比"登记的最宽内容放不放得下、两段有没有交叉"。
    # 真字体的重量放在 tools/verify_v21_ui.py（跑在真实平台上）。
    order = ["score", "combo", "best", "round", "secs"]
    check("HUD 每一段都登记了位置 / 字号 / 最宽内容 / 实测宽度",
          all(k in HUD_ZONES and k in HUD_FONT and k in HUD_WIDEST
              and k in HUD_WIDEST_PX for k in order),
          "/".join(sorted(HUD_ZONES)))
    check("HUD 的四张表键名完全一致（漏一个就是那一段没画或没量）",
          set(HUD_ZONES) == set(HUD_FONT) == set(HUD_WIDEST)
          == set(HUD_WIDEST_PX) == set(order))

    spans = {k: hud_zone_rect(k) for k in order}
    clashes = [(a, b) for i, a in enumerate(order) for b in order[i + 1:]
               if spans[a][0] < spans[b][1] and spans[b][0] < spans[a][1]]
    check("最宽的内容下 HUD 各段互不重叠（叠字那次的回归网）",
          not clashes,
          "；".join(f"{k}={spans[k]}" for k in order) if not clashes
          else f"重叠 {clashes}")

    check("每段都比自己要放的最宽内容宽（HUD_WIDEST_PX 没被改小到放不下）",
          all(HUD_ZONES[k][1] >= HUD_WIDEST_PX[k] for k in order),
          "/".join(f"{k}:{HUD_ZONES[k][1]}>={HUD_WIDEST_PX[k]}" for k in order))

    check("各段从左到右的次序与声明一致（左边是得分，右边是秒数）",
          [k for k, _v in sorted(HUD_ZONES.items(), key=lambda kv: kv[1][0])]
          == order)

    off = [k for k in order if spans[k][0] < 0 or spans[k][1] > GAME_W]
    check("HUD 每段都落在窗口里（不会画到窗口外面）", not off, f"越界 {off}")

    check("倒计时条接在秒数右边，且不越出右边界",
          HUD_BAR[0] >= spans["secs"][1] and HUD_BAR[0] + HUD_BAR[1] <= GAME_W,
          f"条 {HUD_BAR} vs 秒数右端 {spans['secs'][1]}")

    check("右对齐的段位数变多时朝左长（右端钉住不动，不会把进度条推走）",
          spans["round"][1] == HUD_ZONES["round"][0] + HUD_ZONES["round"][1]
          and spans["secs"][1] == HUD_ZONES["secs"][0] + HUD_ZONES["secs"][1],
          f"round 右端 {spans['round'][1]} / secs 右端 {spans['secs'][1]}")
    check("声明为右对齐的段都在 HUD 表里",
          set(HUD_ALIGN_RIGHT) <= set(HUD_ZONES), "/".join(HUD_ALIGN_RIGHT))

    mg.close()

    # ---------------------------------------------------------- 接狗狗
    section("接狗狗小游戏")

    def quiet(g):
        """关掉自动出怪，用例只面对自己摆上去的那一个落体。"""
        g.fallers.clear()
        g._spawn_timer = 1e6
        return g

    def put_on_catcher(g, kind):
        """把一个落体直接摆到接板身上，下一步必然判为"接到"。"""
        f = g.spawn(kind)
        f.body.teleport(g.catcher.x, g.catcher.y)
        return f

    bounce_best = cfg.best_score              # 弹跳得分的最高分，后面要确认没被动过

    cg = CatchGame(bank, cfg)
    cg.show()
    check("初始血量 = 5", cg.hp == MAX_HP, f"{cg.hp} 滴")
    check("初始不在结算状态", not cg.over)

    # 素材：目录里有几套就认几套（前缀靠扫目录，不是写死的表）
    _root = game_asset_dir()
    _want = discover_puppy_prefixes(_root)
    _have = [f for f in (load_sprites(_root, p, 16) for p in _want) if f]
    check("小白狗套数 = 目录里实际有素材的套数",
          len(cg.puppy_sets) == len(_have),
          f"{len(cg.puppy_sets)} 套 / 目录 {len(_want)} 个前缀")
    check("每套小白狗都不是空的",
          all(len(s) > 0 for s in cg.puppy_sets),
          str([len(s) for s in cg.puppy_sets]))
    check("空目录时前缀表退回内置兜底",
          len(discover_puppy_prefixes(Path("__definitely_not_here__"))) > 0)

    quiet(cg)
    cg.score = 0
    put_on_catcher(cg, "puppy")
    cg._step(1 / 60)
    check("接住小白狗加 10 分", cg.score == PUPPY_SCORE, f"{cg.score} 分")
    check("接住小白狗不扣血", cg.hp == MAX_HP, f"{cg.hp} 滴")
    check("接住计数 +1", cg.caught == 1, f"{cg.caught} 只")

    # 连击奖励：combo 从 4 接到 5，正好踩在 COMBO_STEP 上
    cg.score = 0
    cg.combo = COMBO_STEP - 1
    put_on_catcher(cg, "puppy")
    cg._step(1 / 60)
    check(f"连击满 {COMBO_STEP} 只额外加 {COMBO_BONUS} 分",
          cg.score == PUPPY_SCORE + COMBO_BONUS, f"{cg.score} 分")

    # 接到炸弹
    quiet(cg)
    cg.hp = MAX_HP
    put_on_catcher(cg, "bomb")
    cg._step(1 / 60)
    check("接到炸弹扣 1 滴血", cg.hp == MAX_HP - 1, f"{cg.hp} 滴")
    check("挨炸后连击清零", cg.combo == 0)

    # 漏接小白狗：摆在最左边，接板在中间够不着
    quiet(cg)
    cg.hp = MAX_HP
    f = cg.spawn("puppy")
    f.body.teleport(0.0, GROUND_Y - 20)
    f.body.vy = 600.0
    for _ in range(10):
        cg._step(1 / 60)
    check("漏接小白狗扣 1 滴血", cg.hp == MAX_HP - 1, f"{cg.hp} 滴")

    # 炸弹掉到底不该扣血（只有"接到"才算）
    quiet(cg)
    cg.hp = MAX_HP
    f = cg.spawn("bomb")
    f.body.teleport(0.0, GROUND_Y - 20)
    f.body.vy = 600.0
    for _ in range(10):
        cg._step(1 / 60)
    check("炸弹掉到底不扣血（只有接到才扣）", cg.hp == MAX_HP, f"{cg.hp} 滴")

    # 血量扣光 -> 结算
    quiet(cg)
    cg.hp = 1
    cg.score = 210
    put_on_catcher(cg, "bomb")
    cg._step(1 / 60)
    check("血量扣光进入 game over", cg.over and cg.hp == 0, f"hp={cg.hp}")
    check("最高分写入 cfg.best_catch", cfg.best_catch == 210, f"best_catch={cfg.best_catch}")
    check("没碰到弹跳得分的最高分", cfg.best_score == bounce_best, f"{cfg.best_score}")
    check("结算标题写的是血量耗尽", "血量耗尽" in cg.label_title.text(),
          cg.label_title.text())

    cg._restart()
    check("重开回满血、分数归零",
          cg.hp == MAX_HP and cg.score == 0 and not cg.over,
          f"hp={cg.hp} score={cg.score}")

    cg.hp = MAX_HP
    cg.heal()
    check("回血不会超过上限", cg.hp == MAX_HP, f"{cg.hp} 滴")

    # 难度随时间上升
    ramp = CatchGame(bank, cfg)
    ramp.survived = 0.0
    i0, c0, s0 = ramp.spawn_interval(), ramp.bomb_chance(), ramp.fall_speed()
    ramp.survived = RAMP_TIME
    i1, c1, s1 = ramp.spawn_interval(), ramp.bomb_chance(), ramp.fall_speed()
    check("难度：出怪间隔变短", i1 < i0, f"{i0:.2f}s -> {i1:.2f}s")
    check("难度：炸弹出现率升高", c1 > c0, f"{c0:.2f} -> {c1:.2f}")
    check("难度：下落速度变快", s1 > s0, f"{s0:.0f} -> {s1:.0f} px/s")

    # 出怪的两条保底规则（各跑 500 次）
    streaker = CatchGame(bank, cfg)
    kinds = [streaker.spawn().kind for _ in range(500)]
    run = best_run = 0
    for k in kinds:
        run = run + 1 if k == "bomb" else 0
        best_run = max(best_run, run)
    check(f"炸弹最多连出 {MAX_BOMB_STREAK} 个", best_run <= MAX_BOMB_STREAK,
          f"实测最长 {best_run}")
    check(f"开局前 {GRACE_SPAWNS} 个必是小白狗",
          kinds[:GRACE_SPAWNS] == ["puppy"] * GRACE_SPAWNS, "/".join(kinds[:4]))
    check("出怪种类只有小白狗和炸弹", set(kinds) <= {"puppy", "bomb"})

    # 两条保底规则放一起也不能出现"一整局没小白狗"
    check("500 次里小白狗数量占多数",
          kinds.count("puppy") > kinds.count("bomb"),
          f"狗 {kinds.count('puppy')} / 弹 {kinds.count('bomb')}")

    # 操作
    from PySide6.QtCore import Qt as _Qt2
    mover = quiet(CatchGame(bank, cfg))
    mover.hp = MAX_HP
    x0 = mover.catcher.x
    mover.keys.add(_Qt2.Key.Key_Right)
    for _ in range(60):
        mover._step(1 / 60)
    check("按右键接板向右移动", mover.catcher.x > x0,
          f"{x0:.0f} -> {mover.catcher.x:.0f}")
    mover.keys.clear()

    mover.catcher.teleport(0.0, GROUND_Y - 78)
    mover.target_x = 400.0
    for _ in range(90):
        mover._step(1 / 60)
    cxx = mover.catcher.x + CATCHER_W / 2
    check("鼠标跟随能走到目标位置附近", abs(cxx - 400.0) < 20, f"停在 {cxx:.0f}")

    # 这里必须走真实的键盘事件，不能直接往 keys 里塞 ——
    # "放弃鼠标跟随"是在 keyPressEvent 里做的，绕过它等于没测到
    from PySide6.QtCore import QEvent as _QEvent
    from PySide6.QtGui import QKeyEvent as _QKeyEvent
    mover.keyPressEvent(_QKeyEvent(_QEvent.Type.KeyPress, _Qt2.Key.Key_Left,
                                   _Qt2.KeyboardModifier.NoModifier))
    check("一动键盘就放弃鼠标跟随", mover.target_x is None)
    check("键盘事件也把按键记进了 keys",
          _Qt2.Key.Key_Left in mover.keys)
    mover.keys.clear()

    # 接板不会跑出画面
    edger = quiet(CatchGame(bank, cfg))
    edger.keys.add(_Qt2.Key.Key_Left)
    for _ in range(300):
        edger._step(1 / 60)
    check("接板被左墙夹住", edger.catcher.x >= -1e-6, f"x={edger.catcher.x:.1f}")
    edger.keys.clear()
    edger.keys.add(_Qt2.Key.Key_Right)
    for _ in range(300):
        edger._step(1 / 60)
    check("接板被右墙夹住",
          edger.catcher.x + CATCHER_W <= GAME_W + 1e-6, f"x={edger.catcher.x:.1f}")

    # 落体必须落在"接板够得着"的范围里
    spawner = CatchGame(bank, cfg)
    xs = []
    for _ in range(200):
        f = spawner.spawn("puppy")
        xs.append(f.body.x)
        f.gone = True
    spawner.fallers.clear()
    check("小白狗落点都在接板能覆盖的范围",
          all(-1e-6 <= x <= GAME_W - 58 + 1e-6 for x in xs),
          f"[{min(xs):.0f}, {max(xs):.0f}]")

    cg.close()

    # ---------------------------------------------------------- 菜单接线
    section("游戏菜单接线")
    check("游戏清单标识唯一（菜单靠它区分）",
          len(GAMES) >= 1 and len(set(game_kinds())) == len(GAMES),
          "/".join(game_kinds()))

    menu_pet = PetWindow(cfg, bank, GAMES)
    menu = menu_pet._build_menu()
    # 显式收一边再断言：写成列表推导时 ``a.menu()`` 会被求值两次，
    # 条件里那次判断没法把表达式那次的类型收窄，类型检查器会判成可能是 None
    subs: list[tuple[str, QMenu]] = []
    for act in menu.actions():
        sub = act.menu()
        # 桩里 ``QAction.menu()`` 标成 ``QObject | None``，运行时给的是 QMenu
        if isinstance(sub, QMenu):
            subs.append((act.text(), sub))
    # **按标题找**，不能假设"游戏子菜单是唯一/第一个"：右键菜单现在还有
    # 小卖部和番茄钟两个子菜单，写死 subs[0] 会拿到小卖部，然后测出一堆假失败
    game_subs = [sub for title, sub in subs if title == "一起玩游戏"]
    check("右键菜单里有游戏子菜单", len(game_subs) == 1,
          "/".join(t for t, _s in subs))
    sub_acts = game_subs[0].actions() if game_subs else []
    check("游戏子菜单项数与 GAMES 一致", len(sub_acts) == len(GAMES),
          "/".join(a.text() for a in sub_acts))

    emitted = []
    menu_pet.request_game.connect(emitted.append)
    for act in sub_acts:
        act.trigger()
    check("点菜单发出的标识与清单一致",
          tuple(emitted) == game_kinds(), "/".join(emitted))

    no_games = PetWindow(cfg, bank)
    check("没传游戏清单时不出现游戏子菜单",
          "一起玩游戏" not in [a.text() for a in
                               no_games._build_menu().actions()])

    # 小卖部 / 番茄钟两个新入口两个菜单都要有（共用登记表，漏一个就是漏了）
    for label in ("小卖部", "番茄钟"):
        check(f"右键菜单里有「{label}」",
              label in [a.text() for a in menu.actions()])
    tray_src = (ROOT / "pet" / "tray.py").read_text(encoding="utf-8")
    check("托盘菜单也接了这两块（不是只在右键菜单里有）",
          "add_shop" in tray_src and "add_pomodoro" in tray_src)

    # ---------------------------------------------------------- 离屏渲染
    section("离屏渲染")

    # 两个游戏窗口都必须继承 GameWindow 底座：main.py 手里只有一个窗口变量，
    # 它调 .closed / ._advance 是**靠基类这份契约**，不是靠"两个文件记得写一样"。
    check("GameWindow 自己声明了 closed（契约只此一处）",
          "closed" in GameWindow.__dict__)
    for cls in (MiniGame, CatchGame):
        check(f"{cls.__name__} 继承 GameWindow", issubclass(cls, GameWindow))
        check(f"{cls.__name__} 没有另抄一份 closed（要靠继承）",
              "closed" not in cls.__dict__)

    for kind in game_kinds():
        w = create_game(kind, bank, cfg)
        check(f"create_game({kind}) 造得出窗口", w is not None,
              type(w).__name__)
        check(f"{kind} 的窗口是 GameWindow（类型标注才成立）",
              isinstance(w, GameWindow))
        check(f"{kind} 有 closed 信号（主程序靠它解除暂停）",
              hasattr(w, "closed"))
        check(f"{kind} 实现了 _step / _reset_scene（底座的两个必填钩子）",
              type(w)._step is not GameWindow._step
              and type(w)._reset_scene is not GameWindow._reset_scene)

        # 真画一帧。paintEvent 里的错（漏导入常量、坐标写错）在纯逻辑用例里
        # 暴露不出来 —— 把常量搬去 game/common 那次就漏掉一个 GROUND_H，
        # 逻辑用例全绿，直到生成预览图才炸。
        try:
            shot = w.grab()
            drawn, detail = not shot.isNull(), f"{shot.width()}x{shot.height()}"
        except Exception as exc:                       # noqa: BLE001
            drawn, detail = False, repr(exc)
        check(f"{kind} 能离屏渲染出一帧（paintEvent 不抛异常）", drawn, detail)

        w._timer.stop()
        w.hide()

    # ---------------------------------------------------------- 养成状态
    section("养成状态（饱食 / 心情 / 精力）")

    v = Vitals()
    check("三项初值都在 0..100 内",
          all(0.0 <= v.get(n) <= 100.0 for n, _l in
              (("satiety", ""), ("mood", ""), ("energy", ""))),
          f"{v.satiety:.0f}/{v.mood:.0f}/{v.energy:.0f}")
    check("第一天打开时不算饿 / 困 / 蔫（不然一开门就是只惨狗）",
          not v.hungry and not v.tired and not v.sad, v.summary())
    check("状态正常时 summary 是短的那句（不能常年占着菜单宽度）",
          v.summary() == "状态不错", v.summary())

    v1 = Vitals()
    v1.awake(3600.0)                       # 挂一小时
    check("挂一小时有明显衰减，但还不至于饿",
          v1.satiety < v.satiety and v1.mood < v.mood and v1.energy < v.energy
          and not v1.hungry,
          f"{v1.satiety:.1f}/{v1.mood:.1f}/{v1.energy:.1f}")
    check("衰减节奏按'半天'这个尺度来：一小时掉不到三分之一",
          v1.energy > v.energy * 0.6, f"精力 {v.energy:.0f} -> {v1.energy:.0f}")

    v2 = Vitals()
    v2.awake(3600.0 * 20.0)                # 20 小时不管
    check("放着不管一整天，三项都会掉到底并报饿 / 困 / 蔫",
          v2.hungry and v2.tired and v2.sad, v2.summary())
    check("三项都不会掉到负数",
          (v2.satiety, v2.mood, v2.energy) == (0.0, 0.0, 0.0),
          f"{v2.satiety:.1f}/{v2.mood:.1f}/{v2.energy:.1f}")

    v3 = Vitals(20.0, 50.0, 80.0)
    v3.feed()
    check("喂一口真的补饱食（不再是只加计数器）",
          abs(v3.satiety - (20.0 + FEED_GAIN)) < 1e-9, f"{v3.satiety:.1f}")
    v3.play()
    check("逗它玩补心情，并花掉一点精力（玩是要费力的）",
          abs(v3.mood - (50.0 + PLAY_GAIN)) < 1e-9 and v3.energy < 80.0,
          f"心情 {v3.mood:.1f} / 精力 {v3.energy:.1f}")
    v4 = Vitals(99.0, 99.0, 99.0)
    v4.feed()
    v4.play()
    check("补过头会被夹在 100，不会溢出",
          v4.satiety == 100.0 and v4.mood == 100.0)

    v5 = Vitals()
    v5.offline(4.0)
    check("离线也掉（关掉程序不是免责）", v5.satiety < 78.0, f"{v5.satiety:.1f}")
    v6 = Vitals()
    v6.offline(24.0)
    check("离线有下限：回来看到的是一只'有点饿'的狗，不是濒死的狗",
          v6.satiety >= OFFLINE_FLOOR - 1e-9 and not v6.tired,
          f"{v6.satiety:.1f}")
    v7 = Vitals()
    v7.offline(240.0)
    check("离线超过封顶时长后不再累加",
          abs(v7.satiety - v6.satiety) < 1e-9, f"{v7.satiety:.1f}")
    v8 = Vitals(10.0, 10.0, 10.0)
    v8.offline(12.0)
    check("本来就比下限还低时，离线不会把它反抬上来",
          abs(v8.satiety - 10.0) < 1e-9, f"{v8.satiety:.1f}")

    # ---- 窗口层：睡 / 醒走不同推进路径
    g2 = PetWindow(Config(), bank, GAMES)
    g2.brain.auto_walk = False
    g2.vitals.energy = 10.0                # 先弄困，它才会一直睡着
    g2.brain._enter(State.SLEEP)
    e0 = g2.vitals.energy
    for _ in range(120):
        g2._advance(0.5)                   # 共 60 秒
    check("睡着时精力回升，而且会一直睡着（rest 路径）",
          g2.vitals.energy > e0 and g2.brain.state is State.SLEEP,
          f"{e0:.0f} -> {g2.vitals.energy:.0f}")

    g2.poke()
    check("戳一下能把它叫醒（SLEEP 不挡互动）", g2.brain.state is State.POKE)
    for _ in range(8):
        g2._advance(0.5)                   # 动作播完，缓冲期内
    check("被叫醒后不会立刻又趴回去（WAKE_HOLD 缓冲，不然会睡-醒-睡地抽搐）",
          g2.brain.state is not State.SLEEP, g2.brain.state.value)

    g2.brain._wake_hold = 0.0
    g2.brain._enter(State.IDLE)
    g2._advance(0.5)
    check("缓冲过后精力还低，就自己回去睡",
          g2.brain.state is State.SLEEP, g2.brain.state.value)

    g2.brain._wake_hold = 0.0
    g2.vitals.energy = 90.0                # 喂饱精力，免得它又趴回去
    g2.brain._enter(State.IDLE)
    s0 = g2.vitals.satiety
    for _ in range(120):
        g2._advance(0.5)
    check("醒着时饱食是往下走的（awake 路径）",
          g2.vitals.satiety < s0 and g2.brain.state is not State.SLEEP,
          f"{s0:.1f} -> {g2.vitals.satiety:.1f}")
    g2._timer.stop()
    g2._save_timer.stop()

    # ---- 存档：三项值 + 金币 + 时间戳都能来回
    vc = Config()
    vc.satiety, vc.mood, vc.energy = 41.5, 62.25, 7.0
    vc.coins = 137
    vc.last_seen = "2026-09-23 12:00:00"
    vc.save()
    vb = Config.load()
    check("养成三项 / 金币 / 上次退出时间都能存进去再读回来",
          (vb.satiety, vb.mood, vb.energy) == (41.5, 62.25, 7.0)
          and vb.coins == 137 and vb.last_seen == "2026-09-23 12:00:00",
          f"{vb.satiety}/{vb.mood}/{vb.energy} 金币 {vb.coins}")

    oc = Config()
    oc.satiety = 90.0
    oc.last_seen = "2026-09-20 12:00:00"    # 三天前
    ow = PetWindow(oc, bank, GAMES)
    check("启动时按 last_seen 补一次离线衰减",
          OFFLINE_FLOOR - 1e-9 <= ow.vitals.satiety < 90.0,
          f"{ow.vitals.satiety:.1f}")
    ow._timer.stop()
    ow._save_timer.stop()

    # ---- 饿了会走到屏幕中间找人
    hc = Config()
    hw = PetWindow(hc, bank, GAMES)
    hw.brain.auto_walk = False
    hw.body.teleport(0.0, 0.0)             # 挪到角落，保证离屏幕中心够远
    hw.vitals.satiety = 90.0
    hw.brain.start_seek(999.0)             # 先给个目标，看它会不会被撤回
    hw._steer_if_hungry()
    check("不饿时不会自己动身（顺手撤掉旧目标）", not hw.brain.seeking)
    hw.vitals.satiety = 5.0
    hw._steer_if_hungry()
    check("饿了会主动走向屏幕中间", hw.brain.seeking, f"seek_x={hw.brain.seek_x}")
    hw.brain._enter(State.SLEEP)
    hw.brain.stop_seek()
    hw.vitals.satiety = 5.0
    hw._steer_if_hungry()
    check("睡着时再饿也不爬起来走（半夜饿醒走两步太出戏）",
          not hw.brain.seeking)
    hw._timer.stop()
    hw._save_timer.stop()

    # ---------------------------------------------------------- 甩出去
    section("甩出去（拖拽投掷）")

    s0s = VelocitySampler()
    check("一个采样点都估不出速度", s0s.velocity() == (0.0, 0.0))
    s0s.add(100.0, 500.0, t=0.0)
    check("只有一个点时不硬凑速度（会算出鬼数）", s0s.velocity() == (0.0, 0.0))
    s0s.add(300.0, 500.0, t=0.0)
    check("两点时间差为 0 时也不除（否则除出无穷大）", s0s.velocity() == (0.0, 0.0))

    fast = VelocitySampler()
    for i in range(8):
        fast.add(100.0 + i * 40.0, 500.0 - i * 10.0, t=i * 0.012)
    fvx, fvy = fast.velocity()
    check("一挥能估出方向正确的速度", fvx > 0 and fvy < 0,
          f"vx={fvx:.0f} vy={fvy:.0f}")
    stale = VelocitySampler()
    stale.add(0.0, 0.0, t=0.0)
    stale.add(600.0, 0.0, t=0.01)
    stale.add(600.0, 0.0, t=5.0)           # 拖到位后停了三秒才松手
    check("拖到位后停一会再松手，速度算出来是 0（不拿几秒前的点当手速）",
          stale.velocity() == (0.0, 0.0), f"samples={stale.samples}")

    check("轻轻放下不当成甩（低于 FLING_MIN 归 0）",
          clamp_fling(20.0, 10.0) == (0.0, 0.0))
    check("刚好够快的原样通过",
          clamp_fling(FLING_MIN * 2.0, 0.0) == (FLING_MIN * 2.0, 0.0))
    cvx, cvy = clamp_fling(9000.0, -3000.0)
    check("猛甩会被夹到上限以内，且方向保留",
          math.hypot(cvx, cvy) <= FLING_MAX + 1e-9 and cvx > 0 and cvy < 0,
          f"|v|={math.hypot(cvx, cvy):.0f}")

    # ---- 真拖一遍（合成鼠标事件走完整条链路）
    fwin = PetWindow(Config(), bank, GAMES)
    fwin.show()
    check("平时不反弹（走路撞到屏幕边要刹住，那是小球的行为）",
          fwin.body.edge_bounce is False)

    def _mouse(kind, gx: float, gy: float) -> None:
        """造一个鼠标事件喂给窗口。第四/五个参数区分"按下"和"按住拖动"。"""
        held = (kind is not QEvent.Type.MouseButtonRelease)
        ev = QMouseEvent(kind, QPointF(6.0, 6.0), QPointF(gx, gy),
                         Qt.MouseButton.LeftButton,
                         Qt.MouseButton.LeftButton if held else Qt.MouseButton.NoButton,
                         Qt.KeyboardModifier.NoModifier)
        if kind is QEvent.Type.MouseButtonPress:
            fwin.mousePressEvent(ev)
        elif kind is QEvent.Type.MouseMove:
            fwin.mouseMoveEvent(ev)
        else:
            fwin.mouseReleaseEvent(ev)

    bx, by = fwin.x() + 60, fwin.y() + 60
    _mouse(QEvent.Type.MouseButtonPress, bx, by)
    for i in range(1, 7):
        _mouse(QEvent.Type.MouseMove, bx + i * 45.0, by - i * 12.0)
        # 真实鼠标事件之间至少隔十几毫秒；同一个微秒里喂完，采样器会判成
        # "时间差太小"而返回 0 —— 那是保护，不是 bug，测试得照着真实节奏来
        time.sleep(0.02)
    _mouse(QEvent.Type.MouseMove, bx + 270.0, by - 72.0)
    _mouse(QEvent.Type.MouseButtonRelease, bx + 270.0, by - 72.0)
    check("快速甩一把：真的给了初速、并转入 FALL",
          fwin.body.vx > 0 and fwin.body.vy < 0
          and fwin.brain.state is State.FALL and fwin._flung,
          f"vx={fwin.body.vx:.0f} vy={fwin.body.vy:.0f} "
          f"state={fwin.brain.state.value}")
    check("飞出去的那一程临时打开撞墙反弹",
          fwin.body.edge_bounce is True)
    fwin._end_fling()
    check("落地后把反弹参数还回平时的样子（否则以后走路会弹）",
          fwin.body.edge_bounce is False
          and fwin.body.restitution == fwin._base_restitution)
    fwin._timer.stop()
    fwin._save_timer.stop()

    slow = PetWindow(Config(), bank, GAMES)
    slow.show()
    sx, sy = slow.x() + 60, slow.y() + 60
    sp = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(6.0, 6.0),
                     QPointF(sx, sy), Qt.MouseButton.LeftButton,
                     Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    slow.mousePressEvent(sp)
    for i in range(1, 7):
        mv = QMouseEvent(QEvent.Type.MouseMove, QPointF(6.0, 6.0),
                         QPointF(sx + i * 2.0, sy), Qt.MouseButton.NoButton,
                         Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        slow.mouseMoveEvent(mv)
        time.sleep(0.02)
    rl = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(6.0, 6.0),
                     QPointF(sx + 12.0, sy), Qt.MouseButton.LeftButton,
                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    slow.mouseReleaseEvent(rl)
    check("慢慢拖到目的地再松手：不会被当成甩（否则手抖一下狗就飞了）",
          slow.body.vx == 0.0 and slow.body.vy == 0.0
          and slow.body.edge_bounce is False,
          f"vx={slow.body.vx:.0f} vy={slow.body.vy:.0f}")
    slow._timer.stop()
    slow._save_timer.stop()

    ng = Config()
    ng.gravity = False
    ngw = PetWindow(ng, bank, GAMES)
    ngw._start_fling(1500.0, -400.0)
    check("关掉重力时甩不动（否则会飞出去挂着、再也落不了地）",
          ngw.body.vx == 0.0 and ngw.body.vy == 0.0
          and ngw.body.edge_bounce is False)
    ngw._timer.stop()
    ngw._save_timer.stop()

    # ---------------------------------------------------------- 小卖部与金币
    section("小卖部与金币")

    check("汇率只有一个来源，两个游戏共用同一把尺子",
          coins_for(COIN_PER_SCORE * 7) == 7
          and coins_for(COIN_PER_SCORE - 1) == 0
          and coins_for(-5) == 0,
          f"{COIN_PER_SCORE} 分 = 1 金币")
    check("商品清单够用，价格都是正数",
          len(menulib.SHOP) >= 3 and all(i.price > 0 for i in menulib.SHOP))
    check("商品 key 唯一（菜单靠它找回商品）",
          len({i.key for i in menulib.SHOP}) == len(menulib.SHOP))
    check("只卖吃的和玩的：精力买不到（只有睡能回精力）",
          all(f != "energy" for i in menulib.SHOP for f, _v in i.gains),
          "/".join(i.key for i in menulib.SHOP))

    bcfg = Config()
    bw = PetWindow(bcfg, bank, GAMES)
    bcfg.coins = 100
    bw.vitals.satiety = 20.0
    # 转成 list 再取下标：类型检查器对 ``tuple[ShopItem, ...]`` 直接下标会误判成空元组
    shop_items = list(menulib.SHOP)
    first, last = shop_items[0], shop_items[-1]
    bw.buy(first.key)
    check("买下扣掉相应金币", bcfg.coins == 100 - first.price, f"{bcfg.coins}")
    # v2.1.0 起"买"和"用"分开了：买下只入库，不立刻抬值 ——
    # 否则饱食已经 90 的时候买肉干就是白扔钱，用户没有挑时候用的余地
    check("买下只进背包，不当场生效",
          bw.bag.count(first.key) == 1
          and abs(bw.vitals.get(first.gains[0][0]) - 20.0) < 1e-9,
          f"背包 ×{bw.bag.count(first.key)} / {first.gains[0][0]} "
          f"{bw.vitals.get(first.gains[0][0]):.1f}")

    bw.buy(first.key)
    check("同一个东西可以叠着放（不然打三局攒不齐一批）",
          bw.bag.count(first.key) == 2 and bw.bag.total() == 2,
          repr(bw.bag))

    field = first.gains[0][0]
    before = bw.vitals.get(field)
    used = bw.use_item(first.key)
    check("从背包用掉一个才真的生效（扣数量 + 抬值 + 演动作）",
          used and bw.bag.count(first.key) == 1
          and bw.vitals.get(field) > before,
          f"剩 ×{bw.bag.count(first.key)} / {field} "
          f"{bw.vitals.get(field):.1f}")

    bw.bag.clear()
    before = bw.vitals.get(field)
    check("背包空的时候用不出来，也不会白给数值",
          bw.use_item(first.key) is False
          and abs(bw.vitals.get(field) - before) < 1e-9)

    bcfg.coins = 0
    had = bw.bag.total()
    bw.buy(first.key)
    check("钱不够时静默不买（不进负数、也不给东西）",
          bcfg.coins == 0 and bw.bag.total() == had)
    bw.buy("查无此物")                      # 不存在的 key：不该崩
    check("买不存在的商品不会崩", True)
    check("用不存在的商品也不会崩", bw.use_item("查无此物") is False)

    bcfg.coins = 0
    poor_menu = QMenu()
    poor_sub = menulib.add_shop(poor_menu, bw, bcfg)
    # 分隔符也算 action 而且永远是 enabled —— 比"能不能点"时必须把它排掉，
    # 否则这条断言永远为真，等于没测
    poor_clickable = [a for a in poor_sub.actions()
                      if not a.isSeparator() and a.isEnabled()]
    check("钱不够时商品项全灰掉（但位置留着，让人知道有东西可攒钱买）",
          not poor_clickable,
          "/".join(a.text() for a in poor_sub.actions() if not a.isSeparator()))

    bcfg.coins = 999
    rich_menu = QMenu()                    # 必须留住：临时对象会被回收，sub 就成野指针
    rich_sub = menulib.add_shop(rich_menu, bw, bcfg)
    check("钱够时商品项都能点",
          sum(1 for a in rich_sub.actions()
              if not a.isSeparator() and a.isEnabled()) == len(menulib.SHOP))

    bcfg.coins = 999
    bw.bag.clear()
    clickable = [a for a in rich_sub.actions()
                 if not a.isSeparator() and a.isEnabled()]
    clickable[-1].trigger()
    check("点最后一个买到的就是最后一个（闭包没捕获错 key）",
          bcfg.coins == 999 - last.price and bw.bag.count(last.key) == 1,
          f"剩 {bcfg.coins} 金币 / 背包 ×{bw.bag.count(last.key)}")

    # ---- 背包菜单：能点的就是手上有的，点一下就用掉
    bag_menu = QMenu()                     # 同样必须留住，否则 sub 成野指针
    bag_sub = menulib.add_bag(bag_menu, bw, bcfg)
    bag_live = [a for a in bag_sub.actions()
                if not a.isSeparator() and a.isEnabled()]
    check("背包菜单里能点的就是手上的道具",
          len(bag_live) == 1, "/".join(a.text() for a in bag_sub.actions()
                                       if not a.isSeparator()))
    last_item = menulib.shop_item(last.key)
    field = last_item.gains[0][0] if last_item else "satiety"
    before = bw.vitals.get(field)
    bag_live[0].trigger()
    check("背包里点一下就真的用掉了",
          bw.bag.count(last.key) == 0 and bw.vitals.get(field) > before,
          f"{bw.bag!r} / {field} {bw.vitals.get(field):.1f}")

    empty_menu = QMenu()
    empty_sub = menulib.add_bag(empty_menu, bw, bcfg)
    check("空背包时只给一行灰提示，没有能点的东西",
          not [a for a in empty_sub.actions()
               if not a.isSeparator() and a.isEnabled()])

    bw._timer.stop()
    bw._save_timer.stop()

    # ---------------------------------------------------------- 背包（纯逻辑）
    section("背包")

    check("脏存档不会崩：非字典 / 负数 / 零 / 已下架的商品 全被剔掉",
          Bag.from_dict(None).is_empty()
          and Bag.from_dict("坏数据").is_empty()
          and Bag.from_dict({"treat": -3, "ball": 0, "已下架": 9}).is_empty(),
          repr(Bag.from_dict({"treat": -3, "ball": 0, "已下架": 9})))
    check("数量被规整成整数（存档里手写成 2.7 也不会变成 2.7 个）",
          Bag.from_dict({"ball": 2.7}).count("ball") == 2)
    check("存进去再读回来是一样的一包东西",
          Bag.from_dict(Bag({"treat": 2, "ball": 1}).to_dict()).total() == 3)

    bag = Bag({"treat": 1})
    check("不够就整笔失败（不做「扣到 0 为止」，那种语义调用方必然用错）",
          bag.take("treat", 2) is False and bag.count("treat") == 1)
    check("拿走了就真的没了，不会留下计数为 0 的空条目",
          bag.take("treat") is True and bag.count("treat") == 0 and bag.is_empty())
    check("列出持有的东西时按商品清单排序（两个菜单的顺序才一致）",
          [i.key for i, _n in Bag({"feast": 1, "treat": 1}).entries()]
          == ["treat", "feast"],
          repr(Bag({"feast": 1, "treat": 1})))

    # ---------------------------------------------------------- 番茄钟时长
    section("番茄钟时长：范围、读数与说法")

    check("时长下限 1 秒、上限 2 小时（滚轮和 start() 都按它夹）",
          MIN_SECONDS == 1.0 and MAX_SECONDS == 7200.0,
          f"{MIN_SECONDS} ~ {MAX_SECONDS} 秒")
    check("越界会被夹住，不会出现 0 秒或 3 小时",
          clamp_seconds(0) == 1.0 and clamp_seconds(-5) == 1.0
          and clamp_seconds(99999) == 7200.0)
    # 存档是用户能手改的文件，进来一个字符串是真实场景。签名上这里收 float，
    # 而这一行要证的恰恰是"类型不对也别崩" —— 所以下面这次调用必须放它过去
    dirty_seconds = "坏数据"
    check("时长是脏数据（手改存档）时按 1 秒处理，不抛异常",
          clamp_seconds(dirty_seconds) == 1.0)      # type: ignore[arg-type]
    check("读数：不到 1 小时是 mm:ss，超过就是 h:mm:ss",
          format_clock(1500) == "25:00" and format_clock(45) == "00:45"
          and format_clock(3723) == "1:02:03",
          "/".join([format_clock(45), format_clock(1500), format_clock(3723)]))
    check("倒计时归零时读数是 00:00（不是被下限夹成 00:01）",
          format_clock(0) == "00:00", format_clock(0))
    check("说法：翻成人话而不是报时",
          describe(1) == "1 秒" and describe(45) == "45 秒"
          and describe(1500) == "25 分钟" and describe(3600) == "1 小时"
          and describe(3903) == "1 小时 5 分",
          "/".join([describe(1), describe(45), describe(1500),
                    describe(3600), describe(3903)]))

    # ---------------------------------------------------------- 滚轮取值
    section("滚轮时长选择器")

    w = WheelModel(0)
    check("秒列不许滚出 0：下限是 1 秒，没有 0 秒这一档",
          w.values(SECOND)[0] == 1 and w.value == 1.0, f"{w.value}")
    check("时列能滚出 0 / 1 / 2（上限 2 小时）",
          w.values(HOUR) == (0, 1, 2), f"{w.values(HOUR)}")

    w = WheelModel(60)                     # 0:01:00
    w.scroll(SECOND, -1)
    check("滚到头会绕回另一端（「滚轮下滑」的手感就来自这个循环）",
          w.current(SECOND) == 59 and w.value == 119.0, f"{w.value}")
    w.scroll(SECOND, 1)
    check("往回滚一格就回到 0", w.current(SECOND) == 0 and w.value == 60.0)

    w = WheelModel(3600 + 1800 + 50)       # 1:30:50
    w.scroll(HOUR, 1)                      # 时 +1 -> 2
    check("把「时」滚到 2 会连带把分秒清零（2:30:50 这种组合不存在）",
          w.value == 7200.0 and w.current(MINUTE) == 0 and w.current(SECOND) == 0,
          f"{w.value}")
    check("此时分、秒两列都只剩 0 这一个值（滚不动了）",
          w.values(MINUTE) == (0,) and w.values(SECOND) == (0,))
    w.scroll(HOUR, -1)
    check("滚回 1 小时后分秒停在 0（可预期比「记住上次」重要）",
          w.value == 3600.0, f"{w.value}")

    w = WheelModel(3600)                   # 1:00:00
    w.scroll(MINUTE, -1)
    check("分列也是循环的", w.current(MINUTE) == 59, f"{w.current(MINUTE)}")

    w = WheelModel(1500)
    w.choose(HOUR, 2)                      # 快捷档位点到 2 小时
    check("快捷档位也走同一套联动规则（不会变成 2:25:00）",
          w.value == 7200.0, f"{w.value}")
    w.choose(MINUTE, 30)
    check("值不在本列范围里时忽略掉，不会把滚轮弄成非法状态",
          w.value == 7200.0, f"{w.value}")

    # ---------------------------------------------------------- 番茄钟
    section("番茄钟")

    p = Pomodoro()
    check("没启动时推进不会有反应", p.tick(10.0) is False and not p.running)
    p.start(1500)                          # 25 分钟
    check("启动后剩余 == 设定时长", abs(p.remaining - 1500) < 1e-9, p.label())
    hits = 0
    for _ in range(1500):
        if p.tick(1.0):
            hits += 1
    check("25 分钟刚好到点一次（不是每帧都喊）", hits == 1, f"hits={hits}")
    check("到点后自己停下并记下一轮",
          not p.running and p.finished_rounds == 1)
    check("停下后 label 归零，但仍记得这一轮是 25 分钟（提醒文案要用）",
          p.label() == "00:00" and abs(p.total_seconds - 1500) < 1e-9,
          f"{p.label()} / {p.describe_total()}")
    p.start(1500)
    for _ in range(60):
        p.tick(1.0)
    check("进度与剩余时间对得上",
          0.03 < p.progress < 0.05 and p.label() == "24:00",
          f"{p.label()} progress={p.progress:.3f}")
    p.stop()
    check("停止后剩余归零、不再跑", not p.running and p.remaining == 0.0)
    check("1 秒这种极限时长也能正常跑完（滚轮能滚出来就得能跑）",
          Pomodoro().start_hms(0, 0, 1) == 1.0)

    pyc = Config()
    pw = PetWindow(pyc, bank, GAMES)
    got: list[int] = []
    pw.pomodoro_done.connect(got.append)
    pw.start_pomodoro(60)                  # 1 分钟
    for _ in range(130):
        pw._advance(0.5)                   # 共 65 秒
    check("到点时窗口发出通知（参数是本轮的总秒数，主程序靠它弹托盘气泡）",
          got == [60], f"{got}")
    check("到点后番茄钟不再是运行中", not pw.pomodoro.running)

    # 菜单：快捷档位 + 自定义入口。时长现在是用户自己滚的，
    # "自定义"必须是菜单里的常驻项，不能只有两个写死的档
    pomo_menu = QMenu()
    pomo_sub = menulib.add_pomodoro(pomo_menu, pw)
    pomo_acts = [a.text() for a in pomo_sub.actions()]
    check("番茄钟菜单里有「自定义时长…」入口（滚轮是主入口）",
          any("自定义" in t for t in pomo_acts), "/".join(pomo_acts))
    check("快捷档位也都在（懒得多滚的人直接点）",
          sum(1 for t in pomo_acts if "分钟" in t) == len(menulib.POMODORO_CHOICES),
          "/".join(pomo_acts))
    check("档位清单的单位是秒（混着分钟迟早有人把 45 当分钟用）",
          all(s >= 1 and s <= MAX_SECONDS for s in menulib.POMODORO_CHOICES),
          "/".join(str(s) for s in menulib.POMODORO_CHOICES))
    check("上次选的时长记得住（下次打开对话框停在上次那儿）",
          isinstance(pyc.pomodoro_seconds, float)
          and pyc.pomodoro_seconds == Config().pomodoro_seconds)
    pw._timer.stop()
    pw._save_timer.stop()

    # ---------------------------------------------------------- 接狗狗：骨头与漂移
    section("接狗狗：骨头与漂移")

    check("骨头是第三种落体，和狗、炸弹并列",
          set(FALLER_KINDS) == {"puppy", "bomb", "bone"}, "/".join(FALLER_KINDS))

    kcfg = Config()
    kg = CatchGame(bank, kcfg)             # 直接造子类：要摸它的内部，才拿得到类型
    kg.rng = random.Random(20260923)

    kg.survived = 0.0
    check("开局不给骨头（血还满着，接了只是加分）", kg.bone_chance() == 0.0)
    kg.survived = RAMP_TIME * 0.5
    check("过了一段才可能掉骨头", kg.bone_chance() > 0.0,
          f"{kg.bone_chance():.2f}")

    bone = kg.spawn("bone")
    check("骨头按自己的尺寸来（比炸弹小一圈）", bone.body.w == BONE_SIZE,
          f"{bone.body.w}")
    check("骨头是笔直掉下来的（礼物不该躲着人跑）", bone.body.vx == 0.0)

    kg.hp = 2
    kg.score = 0
    kg._on_bone(bone)
    check("有伤时接住骨头：加分 + 回一滴血",
          kg.hp == 3 and kg.score == BONE_SCORE,
          f"hp={kg.hp} score={kg.score}")
    kg.hp = MAX_HP
    kg.score = 0
    kg._on_bone(kg.spawn("bone"))
    check("满血时接住骨头：只加分，不会把血顶破",
          kg.hp == MAX_HP and kg.score == BONE_SCORE, f"hp={kg.hp}")
    kg.hp = MAX_HP
    kg.heal(3)
    check("heal() 仍夹在血量上限（老接口行为没变）", kg.hp == MAX_HP)

    kg.hp = 3
    miss = kg.spawn("bone")
    miss.body.y = GROUND_Y + 1.0
    kg.fallers = [miss]
    kg.catcher.teleport(-9999.0, 0.0)      # 接板挪走，保证是"漏掉"
    kg._fall_step(0.05)
    check("漏掉骨头不扣血（能接就赚，不该变成负担）", kg.hp == 3, f"hp={kg.hp}")

    kg.survived = 0.0
    check("前半程没有风（和以前一样笔直落下来）", kg.drift_speed() == 0.0)
    kg.survived = RAMP_TIME
    check("难度爬满时风速到上限", abs(kg.drift_speed() - DRIFT_MAX) < 1e-9,
          f"{kg.drift_speed():.0f} px/s")

    kg.fallers.clear()
    kg.rng = random.Random(7)
    pool = [kg.spawn("puppy") for _ in range(80)]
    moving = [f for f in pool if f.body.vx != 0.0]
    check("有风之后只有一部分落体被吹偏（全都飘就又变成单调了）",
          0 < len(moving) < len(pool), f"{len(moving)}/{len(pool)}")
    check("被吹偏的那些打开了撞墙反弹，且不掉速（是风，不是弹性碰撞）",
          all(f.body.edge_bounce and f.body.restitution == 1.0 for f in moving))

    d = moving[0]
    d.body.x = 0.0
    d.body.vx = -abs(d.body.vx)
    dvx = d.body.vx
    d.body.update(0.05, (0.0, 0.0, float(GAME_W), float(FALL_LIMIT)),
                  use_gravity=False)
    check("飘到左右边会弹回来（不会贴着边走完剩下的路）",
          d.body.vx == -dvx and abs(d.body.vx) == abs(dvx),
          f"{dvx:+.1f} -> {d.body.vx:+.1f}")

    kg.fallers = []
    kg.hp = MAX_HP
    kg.catcher.teleport(-9999.0, 0.0)
    worst = 0
    in_bounds = True
    for _ in range(500):
        kg.spawn("puppy")
        kg._fall_step(0.016)
        worst = max(worst, len(kg.fallers))
        for f in kg.fallers:
            if not (-1e-6 <= f.body.x <= GAME_W - f.body.w + 1e-6):
                in_bounds = False
    check("8 秒长跑：所有落体始终在窗口内（反弹不会把它们推出界外）",
          in_bounds, f"峰值 {worst} 个同时在场")

    kg.survived = RAMP_TIME
    kg._spawned = 99
    # 变量名别叫 seen：本函数前面已经用 seen 存过"走过的状态"（一个 set），
    # 同名再赋成 dict 会让类型检查器判定前面那些 set 用法是错的
    kind_count: dict[str, int] = {"puppy": 0, "bomb": 0, "bone": 0}
    streak = longest = 0
    for _ in range(300):
        k = kg.spawn().kind                # 必须走 spawn：_bomb_streak 只在那里更新
        kind_count[k] += 1
        streak = streak + 1 if k == "bomb" else 0
        longest = max(longest, streak)
        kg.fallers.clear()
    check("三种落体都会出（骨头不是摆设）",
          all(n > 0 for n in kind_count.values()), f"{kind_count}")
    check("炸弹不会连出超过上限（保底规则还在）",
          longest <= MAX_BOMB_STREAK, f"最长连击 {longest}")
    kg.close()

    # ---- 金币：只在结算时给
    ccfg = Config()
    cw = CatchGame(bank, ccfg)
    cw.score = 480
    cw._finish()
    check("接狗狗结算按得分折算金币",
          ccfg.coins == coins_for(480), f"480 分 -> {ccfg.coins} 金币")
    check("结算文案写明了这一局挣了多少",
          "金币" in cw.label_sub.text(), cw.label_sub.text())
    cw.close()

    mcfg = Config()
    mw = MiniGame(bank, mcfg)
    mw.score = 345
    mw._finish()
    check("弹跳得分用同一把尺子折算（两个游戏收益不能有差）",
          mcfg.coins == coins_for(345), f"345 分 -> {mcfg.coins} 金币")
    mw.close()

    xcfg = Config()
    xw = CatchGame(bank, xcfg)
    xw.score = 999
    xw.close()
    check("没结算就关掉窗口不给金币（不然看要输了就关窗最划算）",
          xcfg.coins == 0, f"{xcfg.coins}")

    # ---------------------------------------------------------- 新增界面
    section("新增界面：滚轮对话框 / 状态面板 / 悬停气泡")

    # 窗口标志那份配方现在只有一份实现（uitheme.apply_overlay_flags），
    # 桌宠和气泡共用。这一条盯着"桌宠的那几条没被搬家搬丢"。
    uicfg = Config()
    uw = PetWindow(uicfg, bank, GAMES)
    check("桌宠仍然是不抢焦点、置顶、无边框的挂件窗口",
          bool(uw.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus)
          and bool(uw.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
          and bool(uw.windowFlags() & Qt.WindowType.FramelessWindowHint)
          and uw.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground),
          f"{uw.windowFlags()}")

    dlg = DurationDialog(uicfg.pomodoro_seconds)
    check("对话框打开时停在上次选的时长上",
          dlg.selected_seconds() == int(uicfg.pomodoro_seconds),
          f"{dlg.selected_seconds()} 秒")
    chips = [b.text() for b in dlg.findChildren(QPushButton)
             if b.objectName() == "chip"]
    check("对话框上的快捷档位与菜单用的是同一份清单（说法也一致）",
          chips == [describe(s) for s in menulib.POMODORO_CHOICES],
          "/".join(chips))
    dlg.picker.set_seconds(45 * 60 + 30)
    check("滚轮摆到 45 分 30 秒，对话框读到的是同一个数",
          dlg.selected_seconds() == 45 * 60 + 30, f"{dlg.selected_seconds()}")

    # 鼠标滚轮真的接上了没有 —— 合成的 QWheelEvent 走一遍（角度 -120 = 往下滚一格）
    before = dlg.picker.seconds()
    pos = QPointF(10.0, 60.0)
    dlg.picker.wheelEvent(QWheelEvent(
        pos, pos, QPoint(0, 0), QPoint(0, -120),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase, False))
    check("鼠标滚轮能推动滚轮（下滑 = 数值增大）",
          dlg.picker.seconds() > before,
          f"{before} -> {dlg.picker.seconds()}")

    check("对话框能离屏画出图来（paintEvent 里的错在纯逻辑用例里看不见）",
          not dlg.grab().isNull() and not dlg.picker.grab().isNull(),
          f"{dlg.size().width()}x{dlg.size().height()}")

    uw.bag.add("treat", 2)
    uw.bag.add("ball")
    uw.cfg.coins = 137
    uw.vitals.satiety = 12.0
    panel = BagPanel(uw, uw.cfg)
    panel.refresh()
    check("面板读的是窗口的真实数据：金币、背包件数",
          panel.money.text() == "137" and "共 3 件" in panel.bag_title.text(),
          f"{panel.money.text()} / {panel.bag_title.text()}")
    count_label, use_btn = panel._cards["treat"]
    empty_label, empty_btn = panel._cards["feast"]
    check("背包里有几个就写几个，没有的格子灰掉但留着",
          count_label.text() == "×2" and use_btn.isEnabled()
          and empty_label.text() == "×0" and not empty_btn.isEnabled(),
          f"treat {count_label.text()} / feast {empty_label.text()}")
    check("面板能离屏画出图来", not panel.grab().isNull(),
          f"{panel.size().width()}x{panel.size().height()}")

    before = uw.vitals.satiety
    panel._use("treat")
    check("面板上按「使用」= 真的用掉一个",
          uw.bag.count("treat") == 1 and uw.vitals.satiety > before,
          f"剩 ×{uw.bag.count('treat')} / 饱食 {uw.vitals.satiety:.1f}")

    # v2.2.0：划过桌宠不再弹任何窗口。这两条是**防回退**断言 ——
    # 那张浮卡曾经因为「状态更显眼」被加进来过一次，用户用了一天就要求撤掉。
    # "enterEvent 不再被覆盖"是最直接的证据：没有这个覆盖，鼠标划过什么都不会发生。
    check("鼠标划过桌宠不再弹窗（enterEvent 不再被覆盖）",
          PetWindow.enterEvent is QWidget.enterEvent
          and not hasattr(uw, "_bubble"),
          f"{PetWindow.enterEvent is QWidget.enterEvent}")
    check("背包面板里不放状态条（状态值只留一处口径）",
          not hasattr(panel, "strip"))
    check("面板留了一行字，告诉用户状态去哪儿看",
          "右键" in panel.where.text(), panel.where.text())

    panel.close()
    dlg.close()
    uw._timer.stop()
    uw._save_timer.stop()

    # ================================================== 跑一跑（v2.2.0 新增）
    section("跑一跑")

    rcfg = Config()

    def fresh_run():
        """造一个跑一跑窗口并停掉计时器 —— 用例只面对自己摆上去的场景。"""
        w = Runner(bank, rcfg)
        w._timer.stop()
        return w

    # ---- 难度曲线
    check("难度：每 3000px 提一档",
          tier_for(0) == 0 and tier_for(2999) == 0
          and tier_for(3000) == 1 and tier_for(9000) == 3,
          f"0→{tier_for(0)} 2999→{tier_for(2999)} 3000→{tier_for(3000)}")
    check("难度：速度随档位上升、且有上限",
          speed_for(0) == RUN_BASE_SPEED and speed_for(1) > speed_for(0)
          and speed_for(99) == RUN_MAX_SPEED,
          f"{speed_for(0):.0f} → {speed_for(1):.0f} → {speed_for(99):.0f} px/s")
    check("难度：障碍间隔随档位缩短，且留了下限",
          gap_seconds_for(0) == GAP_SEC_START > gap_seconds_for(6)
          and gap_seconds_for(99) == GAP_SEC_MIN,
          f"{gap_seconds_for(0):.2f}s → {gap_seconds_for(6):.2f}s → "
          f"{gap_seconds_for(99):.2f}s")

    # ---- 图案表
    check("图案表里的障碍标识都在 KINDS 里（拼错了会在这条上暴露）",
          all(k in RUN_KINDS for p in RUN_PATTERNS for k, _dx in p.parts),
          "/".join(sorted(RUN_KINDS)))
    check("每组图案都登记了解锁档位，最高那组是高难度的",
          all(p.min_tier >= 0 for p in RUN_PATTERNS)
          and RUN_PATTERNS[-1].min_tier >= 5,
          f"{RUN_PATTERNS[-1].label} @{RUN_PATTERNS[-1].min_tier}")

    # ---- 跳跃手感三件套
    r = fresh_run()
    r._reset_scene()
    r.press_jump()
    r._step(1 / 60)
    check("按跳立刻离地、速度朝上", not r.on_ground and r.vy < 0, f"vy={r.vy:.0f}")

    def apex(cut: bool) -> tuple[float, bool]:
        """跳一次能跳多高（px）+ 1.5 秒内有没有落回来。

        ``cut=True`` 在第 4 帧松手 —— 模拟"轻点一下"。
        """
        w = fresh_run()
        w._reset_scene()
        w.press_jump()
        top = GROUND_Y
        for i in range(90):
            w._step(1 / 60)
            if cut and i == 3:
                w.release_jump()
            top = min(top, w.feet)
        return GROUND_Y - top, w.on_ground

    (hold, hold_landed), (tap, _tap_landed) = apex(False), apex(True)
    check("跳得起来也落得回去（顶点约 170px，1.5 秒内落地）",
          140 < hold < 210 and hold_landed, f"按住 {hold:.0f}px")
    check("可变跳跃高度：轻点比按住跳得矮（不是按键时间无关的固定弧线）",
          0 < tap < hold * 0.7, f"轻点 {tap:.0f}px / 按住 {hold:.0f}px")

    def air_frames(fast_fall: bool) -> int:
        """一次跳跃从起跳到落地的帧数。"""
        w = fresh_run()
        w._reset_scene()
        w.press_jump()
        w._step(1 / 60)
        n = 1
        while not w.on_ground and n < 300:
            if fast_fall:
                w.press_crouch(True)
            w._step(1 / 60)
            n += 1
        return n

    slow_air, fast_air = air_frames(False), air_frames(True)
    check("空中按 ↓ 会更快落地（快速下落）", fast_air < slow_air,
          f"{slow_air} 帧 → {fast_air} 帧")

    # ---- 判定：垂杆只能低头过
    r._reset_scene()
    r.rocks = [RunRock(RUN_KINDS["bird"], float(RUN_PLAYER_X))]
    check("垂杆：站着会撞", r.collides())
    r.press_crouch(True)
    check("垂杆：低头能过", not r.collides())
    r.press_crouch(False)
    r.feet = GROUND_Y - 170.0
    check("垂杆：跳得再高也撞 —— 「必须低头」这条规则才成立",
          r.collides(), f"离地 170px 时判定盒 {r.hitbox()[1]:.0f}~{r.hitbox()[3]:.0f}")

    # ---- 判定：矮墩要跳过去
    r.feet = float(GROUND_Y)
    r.rocks = [RunRock(RUN_KINDS["low"], float(RUN_PLAYER_X))]
    check("矮墩：站着会撞", r.collides())
    r.feet = GROUND_Y - 60.0
    check("矮墩：跳起来能过", not r.collides())
    check("判定盒比贴图窄一圈（宁可放过，不可错杀）",
          r.hitbox()[0] > RUN_PLAYER_X
          and r.hitbox()[2] < RUN_PLAYER_X + RUN_PLAYER_W,
          f"盒 {r.hitbox()[0]:.0f}~{r.hitbox()[2]:.0f} / 贴图 "
          f"{RUN_PLAYER_X}~{RUN_PLAYER_X + RUN_PLAYER_W}")

    # ---- 撞上就结算，且用同一把尺子折算金币
    dead_cfg = Config()
    dead = Runner(bank, dead_cfg)
    dead._timer.stop()
    dead._reset_scene()
    dead.distance = 25000.0                 # 先让它"跑够分"，才好验结算口径
    dead.rocks = [RunRock(RUN_KINDS["low"], float(RUN_PLAYER_X))]
    dead._step(1 / 60)
    check("撞上就结束", dead.over, f"第 {dead.score} 分处撞上")
    check("最高分写进 best_runner", dead_cfg.best_runner == dead.score,
          f"best_runner={dead_cfg.best_runner}")
    check("没碰另外三款的最高分",
          dead_cfg.best_score == 0 and dead_cfg.best_catch == 0
          and dead_cfg.best_2048 == 0)
    check("金币用 coins_for 那把尺子（和另外三款一致）",
          dead_cfg.coins == coins_for(dead.score),
          f"{dead.score} 分 → {dead_cfg.coins} 金币")

    frozen = dead.distance
    dead._advance(1 / 60)
    check("结算之后不再前进（画面真的停住了）", dead.distance == frozen,
          f"{frozen:.0f}px")

    # ---- 生成与清理
    warm = fresh_run()
    warm.rng = random.Random(5)
    for _ in range(30):
        warm._advance(1 / 60)
    check("开局先热身一段，不立刻糊脸",
          not warm.rocks and not warm.over,
          f"0.5 秒跑了 {warm.distance:.0f}px（第一个障碍在 "
          f"{FIRST_SPAWN_DIST:.0f}px）")

    idle = fresh_run()
    idle.rng = random.Random(5)
    frames = 0
    while not idle.over and frames < 1800:
        idle._advance(1 / 60)
        frames += 1
    check("站着不跳迟早会撞上（障碍真的拦得住人）", idle.over,
          f"第 {frames} 帧（{frames / 60:.1f} 秒）撞上，{idle.score} 分")

    cleaner = fresh_run()
    cleaner._reset_scene()
    cleaner.rocks = [RunRock(RUN_KINDS["low"], -100.0)]
    cleaner._step(1 / 60)
    check("跑出屏幕的障碍会被清掉（不会越攒越多）", not cleaner.rocks)

    # ---- HUD 排版（纯几何，不查字体 —— offscreen 下量出来的字宽是假的）
    rspans = {n: run_hud_zone_rect(n) for n in RUN_HUD_ZONES}
    check("跑一跑 HUD：四段文字两两不重叠", not overlapping_zones(rspans),
          " ".join(f"{n}{v}" for n, v in sorted(rspans.items())))
    check("跑一跑 HUD：都在窗口里",
          all(0 <= a and b <= GAME_W for a, b in rspans.values()))
    check("跑一跑 HUD：进度条也不压到任何一段文字",
          all(b <= RUN_HUD_BAR[0] or a >= RUN_HUD_BAR[0] + RUN_HUD_BAR[1]
              for a, b in rspans.values()), f"进度条 {RUN_HUD_BAR}")
    check("跑一跑 HUD：每段都登记了最宽内容（改文案要连表一起改）",
          set(RUN_HUD_WIDEST) == set(RUN_HUD_ZONES)
          and set(RUN_HUD_WIDEST_PX) == set(RUN_HUD_ZONES))
    # 这一条比"墨迹不叠"更严：它盯的是**分配出去的槽位**。
    # 为什么需要它：墨迹宽度用的是登记表，登记值偏小就会掩盖真重叠 ——
    # 2048 的 tile/undo 就是这么差 1px 叠上的（见 game/g2048.py 的 HUD_ZONES 注释）。
    rslots = {n: (x, x + w) for n, (x, w) in RUN_HUD_ZONES.items()}
    check("跑一跑 HUD：分配出去的槽位本身就不重叠（比墨迹不叠更严）",
          not overlapping_zones(rslots),
          " ".join(f"{n}{v}" for n, v in sorted(rslots.items())))

    # ================================================== 狗粮 2048（v2.2.0 新增）
    section("狗粮 2048 · 规则")

    check("[2,2,0,0] 左滑合出 4，加 4 分",
          slide_line([2, 2, 0, 0]) == ([4, 0, 0, 0], 4))
    check("[2,2,2,2] 一次滑动只合成一次（[4,4] 而不是 [8]）",
          slide_line([2, 2, 2, 2]) == ([4, 4, 0, 0], 8),
          f"{slide_line([2, 2, 2, 2])}")
    check("[4,4,8,8] 各合各的", slide_line([4, 4, 8, 8]) == ([8, 16, 0, 0], 24))
    check("[2,0,0,2] 隔空也能合", slide_line([2, 0, 0, 2]) == ([4, 0, 0, 0], 4))
    check("刚合出来的块不再参与合成（[4,2,2,0] → [4,4,0,0]）",
          slide_line([4, 2, 2, 0]) == ([4, 4, 0, 0], 4))
    check("没有相邻相等就只是靠左，不给分",
          slide_line([2, 4, 2, 4]) == ([2, 4, 2, 4], 0))

    gcol = ((2, 0, 0, 0), (2, 0, 0, 0), (0,) * 4, (0,) * 4)
    grow = ((0, 0, 0, 2), (0, 0, 0, 2), (0,) * 4, (0,) * 4)
    check("上滑把同一列合起来，且推到了最上面", g_move(gcol, "up")[0][0][0] == 4)
    check("下滑把它推到最底下（同一列才合，不是同一行）",
          g_move(gcol, "down")[0][3][0] == 4)
    check("右滑把同一行推到右边并合起来",
          g_move(((2, 0, 0, 2),) + ((0,) * 4,) * 3, "right")[0][0][3] == 4)
    check("左滑把它推到最左边",
          g_move(((0, 0, 0, 2),) + ((0,) * 4,) * 3, "left")[0][0][0] == 2)
    check("不同行的两块不会合到一起（右滑两行的 2 还是 2）",
          g_move(grow, "right")[0][0][3] == 2 and g_move(grow, "right")[0][1][3] == 2)
    check("没推动的那一次会被认出来（不冒新块、不给分）",
          g_move(((2, 4, 8, 16),) + ((0,) * 4,) * 3, "left")[2] is False)
    check("推得动就是 True", g_move(gcol, "up")[2] is True)

    dead_board = ((2, 4, 2, 4), (4, 2, 4, 2), (2, 4, 2, 4), (4, 2, 4, 2))
    check("满盘且没有相邻相等的，才算真死局", not can_move(dead_board))
    check("满盘但只要有一对相邻相等就还能动",
          can_move(((2, 4, 2, 4), (4, 2, 4, 2), (2, 4, 2, 4), (4, 2, 4, 4))))
    check("有空位就算还能动", can_move(empty_grid()))
    check("该不该收：死局算收", is_finished(dead_board))
    check("该不该收：凑到目标算收",
          is_finished(((G_TARGET, 0, 0, 0), (0,) * 4, (0,) * 4, (0,) * 4)))
    check("该不该收：中间状态不算",
          not is_finished(((2, 0, 0, 0), (0,) * 4, (0,) * 4, (0,) * 4)))
    check("max_tile 取得对（空盘是 0）",
          max_tile(dead_board) == 4 and max_tile(empty_grid()) == 0)

    check("进度条是对数的：到 512 满格",
          target_ratio(((G_TARGET, 0, 0, 0), (0,) * 4, (0,) * 4, (0,) * 4)) == 1.0)
    check("进度条从 16 才开始有",
          target_ratio(((8, 0, 0, 0), (0,) * 4, (0,) * 4, (0,) * 4)) == 0.0)
    check("进度条每翻一倍走一格（不是线性 —— 线性会在最后永远卡住）",
          0.0 < target_ratio(((64, 0, 0, 0), (0,) * 4, (0,) * 4, (0,) * 4)) < 0.5)

    check("金币按最大格折算：达成目标 512 = 56", coins_for_tile(G_TARGET) == 56,
          f"{coins_for_tile(G_TARGET)}")
    check("不够 8 的格子不给钱（白玩一局不该是纯负反馈）",
          coins_for_tile(4) == 0 and coins_for_tile(8) == 8)
    check("越大给得越多",
          coins_for_tile(2048) > coins_for_tile(1024) > coins_for_tile(G_TARGET))
    check("这一款和另外三款的收益在同一量级（20~80 金币）",
          20 <= coins_for_tile(G_TARGET) <= 80, f"{coins_for_tile(G_TARGET)}")

    section("狗粮 2048 · 窗口")
    wcfg = Config()
    g = Game2048(bank, wcfg)
    g._timer.stop()
    g.rng = random.Random(11)
    g._reset_scene()
    check("开局摆两块", sum(1 for row in g.grid for c in row if c > 0) == 2,
          f"共 {sum(1 for row in g.grid for c in row if c > 0)} 块")
    check("开局的块只会是 2 或 4",
          all(c in (0, 2, 4) for row in g.grid for c in row))

    g.grid = ((2, 2, 0, 0), (0,) * 4, (0,) * 4, (0,) * 4)
    g.score = 0
    g._history.clear()
    g.undo_left = G_UNDO_LIMIT
    moved = g.push("left")
    check("推一步：合成、加分、并冒出一块新的",
          moved and g.grid[0][0] == 4 and g.score == 4
          and sum(1 for row in g.grid for c in row if c > 0) == 2,
          f"{g.grid[0]} 得分 {g.score}")
    check("推完之后就能撤销", g.can_undo())

    g.undo()
    check("撤销把棋盘和分数都退回去",
          g.grid[0][0] == 2 and g.score == 0, f"{g.grid[0]} 得分 {g.score}")
    check("撤销会消耗次数", g.undo_left == G_UNDO_LIMIT - 1,
          f"剩 {g.undo_left}")

    g.undo_left = 0
    check("次数用光就不能再撤", not g.can_undo() and g.undo() is False,
          f"剩 {g.undo_left}")

    win_cfg = Config()
    win = Game2048(bank, win_cfg)
    win._timer.stop()
    win.rng = random.Random(3)
    win._reset_scene()
    win.grid = ((256, 256, 0, 0), (0,) * 4, (0,) * 4, (0,) * 4)
    win.score = 1000
    win.push("left")
    check("凑出 512 立刻结算",
          win.over and win.won and "512" in win.label_title.text(),
          win.label_title.text())
    check("达成目标给的金币按最大格算（56）",
          win_cfg.coins == coins_for_tile(G_TARGET), f"{win_cfg.coins} 金币")
    check("最高分写进 best_2048", win_cfg.best_2048 == win.score,
          f"best_2048={win_cfg.best_2048}")
    check("没碰跑一跑和另外两款的最高分",
          win_cfg.best_runner == 0 and win_cfg.best_score == 0
          and win_cfg.best_catch == 0)
    check("结算之后再推也不动", win.push("left") is False)

    # 死局：满盘、只有一处能合，合完就没路 —— 用固定种子把新块落进那个空位。
    # 要循环找种子，是因为冒出来的块是 2 还是 4 会决定"合完还能不能动"，
    # 而 300 个种子里总有一个能把死局填出来（找不到就说明这条路径断了）。
    dw = Game2048(bank, dead_cfg)
    dw._timer.stop()
    found_seed = None
    for s in range(300):
        dw.rng = random.Random(s)
        dw.grid = ((2, 4, 2, 4), (4, 2, 4, 2), (2, 4, 2, 4), (4, 2, 4, 4))
        dw.score = 0
        dw.over = False
        dw.won = False
        dw._history.clear()
        if dw.push("left") and dw.over:
            found_seed = s
            break
    check("推不动了也会结算（死局这条路径真的走得到）", found_seed is not None,
          f"种子 {found_seed}，结算文案「{dw.label_title.text()}」")
    check("死局结算不标成\"达成目标\"", not dw.won)

    # ---- HUD 排版（和跑一跑同一套纯几何断言）
    gspans = {n: g_hud_zone_rect(n) for n in G_HUD_ZONES}
    check("狗粮 2048 HUD：四段文字两两不重叠", not overlapping_zones(gspans),
          " ".join(f"{n}{v}" for n, v in sorted(gspans.items())))
    check("狗粮 2048 HUD：都在窗口里",
          all(0 <= a and b <= GAME_W for a, b in gspans.values()))
    check("狗粮 2048 HUD：每段都登记了最宽内容",
          set(G_HUD_WIDEST) == set(G_HUD_ZONES)
          and set(G_HUD_WIDEST_PX) == set(G_HUD_ZONES))
    gslots = {n: (x, x + w) for n, (x, w) in G_HUD_ZONES.items()}
    check("狗粮 2048 HUD：分配出去的槽位本身就不重叠（比墨迹不叠更严）",
          not overlapping_zones(gslots),
          " ".join(f"{n}{v}" for n, v in sorted(gslots.items())))

    # ---------------------------------------------------------- 版本号
    section("版本号")
    # 版本号写两处（pet/__init__.py 的 __version__ 和 CHANGELOG.md 的第一条），
    # 两边各改各的必然漂 —— 加条断言盯着。只比 "vX.Y.Z" 这一串，不比日期说明。
    ver = __version__
    changelog = ROOT / "CHANGELOG.md"
    check("CHANGELOG.md 存在", changelog.exists())
    top = ""
    if changelog.exists():
        for line in changelog.read_text(encoding="utf-8").splitlines():
            if line.startswith("## v"):
                top = line[3:].split()[0]          # "## v2.0.0 — ..." -> "v2.0.0"
                break
    check("CHANGELOG 首条版本号与 __version__ 一致",
          top == f"v{ver}", f"CHANGELOG 首条 {top!r} / __version__ {ver!r}")

    # ---------------------------------------------------------- 汇总
    print(f"\n{'=' * 46}")
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        for name in FAIL:
            print(f"  失败：{name}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
