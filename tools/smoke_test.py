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
from PySide6.QtCore import QEvent, QPointF, Qt              # noqa: E402
from PySide6.QtGui import QMouseEvent                       # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu            # noqa: E402

from pet import __version__                              # noqa: E402
from pet import facing                                   # noqa: E402
from pet import menu as menulib                          # noqa: E402
from pet.assets import STATES as ALL_STATES               # noqa: E402
from pet.assets import DEFAULT_SET, AssetBank, default_set_files  # noqa: E402
from pet.behavior import Brain, State                     # noqa: E402
from pet.behavior import FPS as BFPS                      # noqa: E402
from pet.config import Config
from pet.paths import game_asset_dir, pet_asset_dir                     # noqa: E402
from pet.physics import (FLING_MAX, FLING_MIN, Motion, VelocitySampler,  # noqa: E402
                         clamp_fling)
from pet.pomodoro import Pomodoro                         # noqa: E402
from pet.vitals import FEED_GAIN, OFFLINE_FLOOR, PLAY_GAIN, Vitals  # noqa: E402
from pet.window import PetWindow                          # noqa: E402
from game import COIN_PER_SCORE, GAMES, coins_for, create_game, game_kinds  # noqa: E402
from game.catcher import (BONE_SCORE, BONE_SIZE, CATCHER_W, COMBO_BONUS,  # noqa: E402
                          COMBO_STEP, DRIFT_MAX, FALLER_KINDS, FALL_LIMIT,
                          GRACE_SPAWNS, MAX_BOMB_STREAK, MAX_HP, PUPPY_SCORE,
                          RAMP_TIME, CatchGame, discover_puppy_prefixes,
                          load_sprites)
from game.common import GROUND_Y, W as GAME_W             # noqa: E402
from game.common import GameWindow                         # noqa: E402
from game.minigame import MiniGame                        # noqa: E402

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
    check("买下真的抬了对应的值",
          bw.vitals.get(first.gains[0][0]) > 20.0,
          f"{first.gains[0][0]} -> {bw.vitals.get(first.gains[0][0]):.1f}")

    bcfg.coins = 0
    before = bw.vitals.satiety
    bw.buy(first.key)
    check("钱不够时静默不买（不进负数、也不给东西）",
          bcfg.coins == 0 and abs(bw.vitals.satiety - before) < 1e-9)
    bw.buy("查无此物")                      # 不存在的 key：不该崩
    check("买不存在的商品不会崩", True)

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
    bw.vitals.mood = 5.0
    clickable = [a for a in rich_sub.actions()
                 if not a.isSeparator() and a.isEnabled()]
    clickable[-1].trigger()
    check("点最后一个买到的就是最后一个（闭包没捕获错 key）",
          bcfg.coins == 999 - last.price and bw.vitals.mood > 5.0,
          f"剩 {bcfg.coins} 金币 / 心情 {bw.vitals.mood:.1f}")
    bw._timer.stop()
    bw._save_timer.stop()

    # ---------------------------------------------------------- 番茄钟
    section("番茄钟")

    p = Pomodoro()
    check("没启动时推进不会有反应", p.tick(10.0) is False and not p.running)
    p.start(25.0)
    check("启动后剩余 == 设定时长", abs(p.remaining_minutes - 25.0) < 1e-9,
          p.label())
    hits = 0
    for _ in range(25 * 60):
        if p.tick(1.0):
            hits += 1
    check("25 分钟刚好到点一次（不是每帧都喊）", hits == 1, f"hits={hits}")
    check("到点后自己停下并记下一轮",
          not p.running and p.finished_rounds == 1)
    check("停下后 label 归零，但仍记得这一轮是 25 分钟（提醒文案要用）",
          p.label() == "00:00" and abs(p.total_minutes - 25.0) < 1e-9,
          f"{p.label()} / {p.total_minutes:.0f} 分钟")
    p.start(25.0)
    for _ in range(60):
        p.tick(1.0)
    check("进度与剩余时间对得上",
          0.03 < p.progress < 0.05 and p.label() == "24:00",
          f"{p.label()} progress={p.progress:.3f}")
    p.stop()
    check("停止后剩余归零、不再跑", not p.running and p.remaining == 0.0)

    pyc = Config()
    pw = PetWindow(pyc, bank, GAMES)
    got: list[int] = []
    pw.pomodoro_done.connect(got.append)
    pw.start_pomodoro(1)                   # 1 分钟
    for _ in range(130):
        pw._advance(0.5)                   # 共 65 秒
    check("到点时窗口发出通知（参数是本轮的分钟数，主程序靠它弹托盘气泡）",
          got == [1], f"{got}")
    check("到点后番茄钟不再是运行中", not pw.pomodoro.running)
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
