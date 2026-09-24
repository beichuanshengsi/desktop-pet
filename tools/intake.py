"""素材入库：把一堆没整理的文件自动分派到项目里该去的位置。

你只做一件事 —— **把文件全丢进 ``assets/raw/inbox/``**。剩下三步脚本负责：

1. **认类型** —— 图片 / 音频 / 字体 / 视频 / 工程文件，各有各的去处
2. **认动作** —— 图片先看文件名里的关键词；认不出来就看动图的**运动轨迹**：
   横向位移大 = 走路，纵向往返 = 跳跃，抬上去不下来 = 被拎起来，越掉越低 = 下落
3. **归位** —— 图片交给 ``prep_sticker.py`` 抠底、缩放、按 ``<状态>_<序号>.png`` 命名
4. **换图标** —— 有宠物素材入库就顺便把 ``assets/icon.png`` / ``icon.ico`` 也重裁一遍，
   免得出现"桌面上的狗换了、托盘上还是上一只"

默认**只打印方案不动手**。看一遍觉得对，加 ``--apply`` 才真正执行。

用法
----
    python tools/intake.py                  # 只看方案
    python tools/intake.py --apply          # 按方案落位
    python tools/intake.py --as idle --apply        # 强制全部当待机动作
    python tools/intake.py --map 晃脚=idle --map 害怕=drag --apply   # 逐文件指定
    python tools/intake.py --scale 逗他玩=0.56 --apply  # 钉死缩放，跟已有动作一样大
    python tools/intake.py --builtin --apply        # 写进 assets/pet 而不是 custom_pet
    python tools/intake.py --no-icon --apply        # 入库但不动图标
    python tools/intake.py --dir D:/下载/表情包 --apply
"""

from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parent.parent
TOOLS = Path(__file__).resolve().parent
for _p in (str(ROOT), str(TOOLS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from PIL import Image                                    # noqa: E402

import prep_bg as bgprep                               # noqa: E402
import prep_sticker as prep                              # noqa: E402
from pet import facing as facinglib                      # noqa: E402
from pet import icon as iconlib                          # noqa: E402
from pet.paths import asset_dir, user_asset_dir          # noqa: E402

INBOX = ROOT / "assets" / "raw" / "inbox"
#: 加工完的原始输入归档处。名字和目录一致（都叫 archive），免得"代码里叫 DONE、
#: 盘上叫 _archive"这种对不上的情况。
ARCHIVE = ROOT / "assets" / "raw" / "_archive"

IMG_EXT = {".png", ".gif", ".webp", ".apng", ".bmp", ".tga", ".jpg", ".jpeg"}
ANIM_EXT = {".gif", ".webp", ".apng"}
AUDIO_EXT = {".wav", ".mp3", ".ogg", ".flac", ".m4a", ".aac"}
FONT_EXT = {".ttf", ".otf", ".ttc"}
VIDEO_EXT = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv"}
LAYER_EXT = {".psd", ".ai", ".xcf", ".aseprite", ".clip", ".sketch"}

# 关键词表：命中哪个词就归哪个动作。
# 顺序即优先级 —— 先判"被动"的动作，再判"主动"的，idle 放最后当兜底。
# poke / feed 是点出来的两个互动动作，关键词放在 walk / idle 之前判：
# "逗他玩.gif"、"喂一口.gif" 这类文件名本身就把动作写清楚了。
# "跳 / 蹦 / 跃" 也归 poke —— 新素材里那个位置就是"点一下演一段"的槽，
# 名字叫不叫 jump 都进这一个动作（旧版本里它叫 jump，已经改名）。
STATE_HINTS: list[tuple[str, tuple[str, ...]]] = [
    ("drag", ("drag", "拎", "提", "抓", "拽", "悬空", "hold", "grab", "catch", "pick")),
    ("poke", ("poke", "逗", "戳", "拍", "爱心", "比心", "撒娇", "play",
              "jump", "跳", "蹦", "跃", "hop", "leap", "bounce")),
    ("feed", ("feed", "喂", "吃", "饭", "food", "eat", "bowl", "饼干", "零食")),
    ("fall", ("fall", "掉", "落", "坠", "drop")),
    ("walk", ("walk", "run", "走", "跑", "漫步", "移动", "溜达", "move", "stroll")),
    ("idle", ("idle", "待机", "发呆", "静止", "呼吸", "眨眼", "站", "坐",
              "blink", "still", "stay", "sit")),
]

GAME_HINTS: list[tuple[str, tuple[str, ...]]] = [
    ("bg", ("bg", "背景", "background", "backdrop", "scene", "场景", "星空")),
    ("block", ("block", "方块", "砖", "brick", "platform", "平台", "箱子")),
    ("ball", ("ball", "球")),
]

ICON_HINTS = ("icon", "图标", "logo", "标志", "封面", "cover")

SFX_HINTS: list[tuple[str, tuple[str, ...]]] = [
    ("break", ("break", "碎", "撞", "命中", "hit")),
    ("score", ("score", "得分", "加分", "计分")),
    ("levelup", ("levelup", "level_up", "过关", "升级", "结算", "胜利")),
    ("land", ("land", "落地", "着地", "着落")),
    ("poke", ("poke", "单击", "点击", "戳", "click", "回应")),
]


# ---------------------------------------------------------------- 工具

def _dw(text: str) -> int:
    """字符串显示宽度（中日韩字符算两格）。"""
    return sum(2 if ord(ch) > 0x2E7F else 1 for ch in text)


def _pad(text: str, width: int, align: str = "left") -> str:
    gap = max(0, width - _dw(text))
    if align == "right":
        return " " * gap + text
    return text + " " * gap


def _fit(text: str, width: int) -> str:
    """按显示宽度截断（中文算两格），超长补省略号。"""
    if _dw(text) <= width:
        return _pad(text, width)
    out, used = "", 0
    for ch in text:
        w = 2 if ord(ch) > 0x2E7F else 1
        if used + w > width - 1:
            break
        out += ch
        used += w
    return out + "…" + " " * max(0, width - used - 1)


def _cls() -> None:
    """Windows 终端里把编码切到 UTF-8，避免中文变问号。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8")        # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass


@dataclass
class Decision:
    """一条分派结论。"""

    src: Path
    kind: str = "skip"          # pet / game / sfx / font / icon / skip
    state: str = ""             # kind == pet 时有意义
    target: str = ""
    reason: str = ""
    note: str = ""
    frames: int = 0

    @property
    def ok(self) -> bool:
        return self.kind != "skip"


# ---------------------------------------------------------------- 认动作

def analyze_motion(frames: list[Image.Image], key: tuple[int, int, int] | None
                   ) -> tuple[str, str]:
    """看动图的运动轨迹猜动作，返回 (状态, 依据文字)。

    用"内容包围盒底边"当脚线、"左右中心"当水平位置：
    * 横向来回  -> 走路
    * 纵向 抬起后不回位 -> 被拎起来
    * 纵向 一路往下      -> 下落
    * 纵向 上下往返      -> 跳跃
    * 基本不动          -> 待机
    """
    if len(frames) < 2:
        return "idle", "静态图，无轨迹可判 → 待机"

    bottoms, centers = [], []
    for frame in frames:
        img = prep.key_out(frame, key) if key else frame.convert("RGBA")
        box = img.getbbox()
        if box:
            bottoms.append(box[3])
            centers.append((box[0] + box[2]) / 2)

    if len(bottoms) < 2:
        return "idle", "整幅透明，判不出 → 待机"

    dx = max(centers) - min(centers)
    dy = max(bottoms) - min(bottoms)

    if dx <= 3 and dy <= 3:
        return "idle", f"几乎不动（横{dx:.0f}px 纵{dy:.0f}px）→ 待机"
    if dx > dy:
        return "walk", f"横向位移占优（横{dx:.0f} > 纵{dy:.0f}）→ 走路"

    net = bottoms[-1] - bottoms[0]
    if net <= -dy * 0.6:
        return "drag", f"抬高后不回位（净升{-net:.0f}px）→ 被拎起来"
    if net >= dy * 0.6:
        return "fall", f"一路往下（净降{net:.0f}px）→ 下落"
    return "poke", f"纵向往返（纵{dy:.0f}px 净{net:+.0f}px）→ 原地起跳式反应（逗它玩）"


def _has_alpha(img: Image.Image) -> bool:
    """图里是否存在真正的透明像素。

    按"alpha 通道最小值 < 阈值"判断，而不是只看模式 —— 很多 GIF 转出来
    是 RGBA 模式但整图不透明，按模式判会把它们全算成"已经抠好底了"。
    """
    if img.mode not in ("RGBA", "LA", "P"):
        return False
    alpha = img.convert("RGBA").getchannel("A")
    # 单通道图的 getextrema() 一定是 (最小, 最大) 二元组；类型桩把返回值标成
    # 可能是单个 float 或嵌套元组，所以这里 cast 一次，运行时不做任何转换
    lo, _hi = cast("tuple[int, int]", alpha.getextrema())
    return lo < 240


# ---------------------------------------------------------------- 分派

def _bg_decision(path: Path, frames: list) -> Decision:
    """背景图分派到具体哪个游戏的 ``bg_*.png``。

    两个游戏各要一张背景，所以不能再像只有一个游戏时那样统一写成 ``bg.png``。
    文件名里带「弹跳 / 舞台 / 粉」或「接 / 蓝天 / 草地」就直接对上；都没命中时
    看哪张还缺 —— 缺哪张补哪张，两张都在就默认给弹跳得分。
    """
    stem = path.stem
    low = stem.lower()
    target = None
    for bg_name, keywords in bgprep.NAME_HINTS:
        if any(k in stem or k in low for k in keywords):
            target = bg_name
            break
    if target is None:
        game_dir = asset_dir("game")
        target = ("bg_bounce" if not (game_dir / "bg_bounce.png").exists()
                  else "bg_catch")
    return Decision(path, "game", target=f"assets/game/{target}.png",
                    reason="背景图（按文件名认是哪个游戏的）",
                    frames=len(frames),
                    note="落位时会按地平线裁成游戏窗口尺寸，"
                         "地平线位置不对就用 tools/prep_bg.py 重裁")


def classify(path: Path, force_state: str | None = None,
             overrides: tuple[tuple[str, str], ...] = ()) -> Decision:
    """决定一个文件（或帧目录）该去哪儿。"""
    ext = path.suffix.lower()
    name = path.name.lower()

    # ---- 明确不支持的
    if ext in VIDEO_EXT:
        return Decision(path, "skip", reason="视频不支持",
                        note="桌宠只吃静态图和 GIF，视频要先转成 GIF")
    if ext in LAYER_EXT:
        return Decision(path, "skip", reason="工程源文件",
                        note="请在 PS/AI 里导出带透明通道的 PNG")
    if ext in (".md", ".txt", ".zip", ".rar", ".7z"):
        return Decision(path, "skip", reason="非素材文件")

    # ---- 字体
    if ext in FONT_EXT:
        return Decision(path, "font", target=f"assets/fonts/{path.name}",
                        reason="字体文件")

    # ---- 音频
    if ext in AUDIO_EXT:
        return _classify_audio(path)

    # ---- 图片（含无扩展名的帧目录）
    if ext in IMG_EXT or path.is_dir() or ext == "":
        return _classify_image(path, force_state, overrides)

    return Decision(path, "skip", reason=f"未知类型 {ext or '(无扩展名)'}")


def _classify_audio(path: Path) -> Decision:
    name = path.stem.lower()
    for canon, keywords in SFX_HINTS:
        if any(k in name for k in keywords):
            return Decision(path, "sfx", target=f"assets/sfx/{canon}{path.suffix.lower()}",
                            reason=f"音效（命中「{canon}」）",
                            note="" if path.suffix.lower() == ".wav"
                                 else "建议转成 .wav，Qt 对 wav 支持最稳")
    return Decision(path, "sfx", target=f"assets/sfx/{path.name}",
                    reason="音效（未命中事件名，保留原名）")


def _classify_image(path: Path, force_state: str | None,
                    overrides: tuple[tuple[str, str], ...] = ()) -> Decision:
    name = path.name.lower()

    # ---- 先试着读帧，读不出来就跳过
    try:
        frames = prep.load_frames(path)
    except (SystemExit, OSError, ValueError) as exc:
        return Decision(path, "skip", reason=f"读不出图像（{exc}）")

    frames = frames[:400]                            # 超大动图防呆
    has_alpha = _has_alpha(frames[0])
    anim = len(frames) > 1

    # ---- JPG 没有透明通道，只能当背景图
    if path.suffix.lower() in (".jpg", ".jpeg"):
        if any(k in name for k in GAME_HINTS[0][1]):
            return _bg_decision(path, frames)
        return Decision(path, "skip", reason="JPG 无透明通道",
                        note="桌宠贴图必须带 alpha；要当背景请改名为 bg*.jpg")

    # ---- 手动指定优先于一切自动判定
    hit = next((st for kw, st in overrides if kw in name), None)
    if hit:
        return Decision(path, "pet", state=hit, reason="命令行 --map 指定",
                        frames=len(frames), note=_alpha_note(has_alpha, anim))
    if force_state:
        return Decision(path, "pet", state=force_state, reason="命令行 --as 指定",
                        frames=len(frames), note=_alpha_note(has_alpha, anim))

    # ---- 图标 / 背景 / 方块 / 球
    if any(k in name for k in ICON_HINTS) and not anim:
        return Decision(path, "icon", target="assets/icon.png",
                        reason="图标（文件名含 icon/图标）")
    for tag, keywords in GAME_HINTS:
        if any(k in name for k in keywords):
            if tag == "bg":
                return _bg_decision(path, frames)
            stem = path.stem.lower()
            return Decision(path, "game", target=f"assets/game/{tag}_{stem[:12]}.png",
                            reason=f"小游戏素材（命中「{tag}」）", frames=len(frames))

    # ---- 文件名关键词
    for state, keywords in STATE_HINTS:
        kw = next((k for k in keywords if k in name), None)
        if kw:
            return Decision(path, "pet", state=state,
                            reason=f"文件名命中「{kw}」", frames=len(frames),
                            note=_alpha_note(has_alpha, anim))

    # ---- 认不出名字，看轨迹
    key = None if has_alpha else prep.guess_key_color(frames[0])
    state, why = analyze_motion(frames, key)
    return Decision(path, "pet", state=state, reason=why, frames=len(frames),
                    note="靠轨迹推断，可能不准，可用 --map 关键词=动作 覆盖")


def _alpha_note(has_alpha: bool, anim: bool) -> str:
    if has_alpha:
        return "" if anim else "静态图，只有一个姿势"
    return "白底/纯色底，入库时会自动抠图"


# ---------------------------------------------------------------- 落位

def _pet_out_dir(builtin: bool) -> Path:
    """贴图落到哪儿：``--builtin`` 写随程序分发的 assets/pet，否则写用户目录。

    目录名走 ``pet.paths`` 登记表，不手写 ``"custom_pet"`` —— 加一类素材
    或改目录名时，只改登记表那一行就够。
    """
    if builtin:
        return asset_dir("pet")
    return user_asset_dir("pet") or asset_dir("pet")


def _start_index(name: str) -> int:
    """从 ``idle_03.png`` 里取出起始序号 3。"""
    try:
        return int(name.rsplit("_", 1)[1][:-4])
    except (IndexError, ValueError):
        return 0


def _assign_indices(decisions: list[Decision]) -> dict[int, str]:
    """给同一动作的多条来源编号，返回 {decision下标: 起始文件名}。

    一个来源可能拆出好几帧，所以按 ``d.frames`` 预留号段，
    否则后一个来源会覆盖前一个来源写出的帧。
    """
    counters: dict[str, int] = {}
    names: dict[int, str] = {}
    for i, d in enumerate(decisions):
        if d.kind != "pet":
            continue
        start = counters.get(d.state, 0)
        names[i] = f"{d.state}_{start:02d}.png"
        counters[d.state] = start + max(1, d.frames)
    return names


@dataclass
class PetPlan:
    """读帧 + 抠底 + 定缩放比的中间结果。

    报告和执行共用同一份 —— 两处各算一次的话，"方案里写 0.56、真落位缩成
    0.44"这种事故迟早会发生，而缩放比错了正是本项目最爱踩的坑
    （狗忽大忽小、带道具的那套被缩没）。
    """

    loaded: dict[int, tuple[list[Image.Image], tuple[int, int, int] | None]] = field(default_factory=dict)
    scale_of: dict[int, float] = field(default_factory=dict)
    how: dict[int, str] = field(default_factory=dict)
    base_scale: float = 1.0


def plan_pet(decisions: list[Decision], size: int,
             zoom: tuple[tuple[str, float], ...] = (),
             fixed: tuple[tuple[str, float], ...] = ()) -> PetPlan:
    """把 pet 类素材读进来、抠底，并给每套定一个缩放比。

    跨素材共用基准比：同一只角色的几套表情包，狗在原始素材里本来就是一样大
    的；各套各自"缩放到填满画布"的话，带道具的那套（狗坐在长凳上）并集更大、
    被缩得更小，切换动作时角色就会突然变大变小。取最小值可以保证不裁切。

    新素材的狗画得比老素材大/小时，用 ``--scale 关键词=值`` 单独钉死，
    不跟着本批的基准走。
    """
    plan = PetPlan()
    fits: dict[int, float] = {}

    for i, d in enumerate(decisions):
        if d.kind != "pet":
            continue
        frames = prep.load_frames(d.src)[:400]
        key = None if _has_alpha(frames[0]) else prep.guess_key_color(frames[0])
        keyed = [prep.key_out(f, key) if key else f.convert("RGBA") for f in frames]
        plan.loaded[i] = (keyed, key)
        fits[i] = prep.fit_scale(keyed, size)

    plan.base_scale = min(fits.values()) if fits else 1.0

    for i, fit in fits.items():
        name = decisions[i].src.name.lower()
        pinned = next((v for kw, v in fixed if kw in name), None)
        gain = next((z for kw, z in zoom if kw in name), 1.0)
        if pinned is not None:
            plan.scale_of[i], plan.how[i] = pinned, "--scale 钉死"
        elif gain != 1.0:
            plan.scale_of[i] = plan.base_scale * gain
            plan.how[i] = f"基准×{gain:g}"
        else:
            plan.scale_of[i] = plan.base_scale
            plan.how[i] = f"基准（本套最大 {fit:.3f}）"
    return plan


def _apply_pet(decisions: list[Decision], names: dict[int, str],
               out_dir: Path, size: int, keep_old: bool, plan: PetPlan,
               motion: str = "flatten") -> list[str]:
    log: list[str] = []
    out_dir.mkdir(parents=True, exist_ok=True)

    written_states = {d.state for d in decisions if d.kind == "pet"}
    if not keep_old:
        for state in sorted(written_states):
            for stale in sorted(out_dir.glob(f"{state}_*.png")):
                stale.unlink()
                log.append(f"清除旧帧  {stale.relative_to(ROOT)}")

    for i, d in enumerate(decisions):
        if d.kind != "pet":
            continue
        keyed, key = plan.loaded[i]
        scale = plan.scale_of[i]
        out_frames = prep.normalize_series(keyed, size, scale=scale, motion=motion)

        base = _start_index(names[i])
        for k, f in enumerate(out_frames):
            f.save(out_dir / f"{d.state}_{base + k:02d}.png")
        log.append(f"入库贴图  {d.state}_{base:02d}…{d.state}_{base + len(out_frames) - 1:02d}"
                   f"  <- {d.src.name}  ({len(out_frames)} 帧"
                   + ("，已抠底" if key else "")
                   + f"，缩放 ×{scale:.3f}（{plan.how[i]}）"
                   + ("，保留原始位移" if motion == "keep" else "") + ")")

    if plan.scale_of:
        every = "/".join(f"{s:.3f}" for s in plan.scale_of.values())
        log.append(f"缩放比   {every}（跨素材基准 {plan.base_scale:.3f}）")
    return log


def _apply_face(face: str, out_dir: Path) -> list[str]:
    """贴图朝向声明（判断逻辑见 pet/facing.py）。

    程序只知道"往哪走"，不知道"素材画的是哪一边"；两者对不上就会倒着走，
    而这一点从代码上完全看不出来。所以朝向存成素材自带的 ``facing.json``：
    不指定就沿用原声明，**没有声明也不瞎猜**，只在报告里留一句提示。
    """
    if face == "keep":
        if (out_dir / "facing.json").exists():
            word = "左" if facinglib.read(out_dir) < 0 else "右"
            return [f"贴图朝向  沿用已有声明：素材朝{word}"]
        return ["贴图朝向  未声明，按默认（朝右）处理。若发现倒着走，"
                "加 --face left，或右键菜单「左右翻向」"]
    try:
        facinglib.write(out_dir, face)
    except (OSError, ValueError) as exc:
        return [f"贴图朝向  写入失败：{exc}"]
    return [f"贴图朝向  已声明素材朝{'左' if face == 'left' else '右'}，"
            "行走方向与它不一致时才水平镜像"]


def _apply_other(decisions: list[Decision]) -> list[str]:
    log: list[str] = []
    for d in decisions:
        if d.kind in ("pet", "skip") or not d.target:
            continue
        dest = ROOT / d.target
        dest.parent.mkdir(parents=True, exist_ok=True)
        src = d.src
        if src.is_dir():
            shutil.copytree(src, dest.with_suffix(""), dirs_exist_ok=True)
        elif d.target.startswith("assets/game/bg_"):
            # 背景图不能直接拷：原图是竖版大图，要按地平线裁成游戏窗口尺寸，
            # 否则图里的地面和游戏的地面（GROUND_Y）对不上，角色看着悬空站。
            before = dest.stat().st_size if dest.exists() else None
            bgprep.crop_for_game(src, dest)
            size = Image.open(dest).size
            log.append(f"{d.kind:5s} 落位  {d.target}  <- {src.name}"
                       f"  （裁成 {size[0]}x{size[1]}"
                       f"{'，覆盖了同名旧图' if before else ''}）")
            continue              # 背景的日志上面已经写过了
        else:
            shutil.copy2(src, dest)
        log.append(f"{d.kind:5s} 落位  {d.target}  <- {src.name}")
    return log


# ---------------------------------------------------------------- 报告

def _rel(p: Path) -> str:
    """尽量显示相对路径；扫描目录在项目外时显示原样。"""
    try:
        return str(Path(p).relative_to(ROOT))
    except ValueError:
        return str(p)


def report(decisions: list[Decision], names: dict[int, str], out_dir: Path,
           applied: bool, scan: Path | None = None,
           plan: PetPlan | None = None) -> str:
    lines: list[str] = []
    head = "已执行" if applied else "预计方案（还没动手，加 --apply 才执行）"
    lines.append("=" * 78)
    lines.append(f"素材分派{head}")
    lines.append("=" * 78)
    # 目录要显示实际扫描的那个 —— 写死 inbox 的话，用 --dir 换目录后
    # 报告和事实不符，排查时会先怀疑错地方
    lines.append(f"输入目录 : {_rel(scan or INBOX)}")
    lines.append(f"贴图去向 : {out_dir.relative_to(ROOT)}")
    face_word = "左" if facinglib.read(out_dir) < 0 else "右"
    declared = (out_dir / "facing.json").exists()
    lines.append(f"贴图朝向 : 素材朝{face_word}"
                 + ("" if declared else "（未声明，按默认；走反了用 --face left）"))
    if plan is not None and plan.scale_of:
        # 缩放比是"狗看起来一样大"的唯一保证，落位前先摆出来给人核对
        for i in sorted(plan.scale_of):
            lines.append(f"缩放比   : {_fit(decisions[i].state, 6)}"
                         f"×{plan.scale_of[i]:.3f}  （{plan.how[i]}）")
    lines.append("")

    order = {"pet": 0, "game": 1, "icon": 2, "sfx": 3, "font": 4, "skip": 9}
    rows = sorted(enumerate(decisions), key=lambda t: (order[t[1].kind], t[0]))

    lines.append(f"{_pad('文件', 34)}{_pad('判定', 12)}{_pad('去向', 26)}依据")
    lines.append("-" * 84)
    for i, d in rows:
        if d.kind == "pet":
            n = max(1, d.frames)
            start = _start_index(names.get(i, f"{d.state}_00.png"))
            dest = (f"{d.state}_{start:02d}.png" if n == 1
                    else f"{d.state}_{start:02d}…{d.state}_{start + n - 1:02d}.png")
            verdict = f"动作 {d.state}"
        elif d.kind == "skip":
            dest = "—"
            verdict = "跳过"
        else:
            dest = d.target
            verdict = {"game": "小游戏", "icon": "图标",
                       "sfx": "音效", "font": "字体"}[d.kind]
        lines.append(f"{_fit(d.src.name, 34)}{_pad(verdict, 12)}"
                     f"{_fit(dest, 26)}{d.reason}")

    lines.append("-" * 84)
    counts: dict[str, int] = {}
    for d in decisions:
        key = d.state if d.kind == "pet" else d.kind
        counts[key] = counts.get(key, 0) + 1
    lines.append("汇总 : " + "  ".join(f"{k}×{v}" for k, v in sorted(counts.items())))

    # 缺口要按"落位之后"的实际状态算：已经在 out_dir 里的帧本次不会被删，
    # 只看本批投递会误报成"缺 idle/drag/poke"，让人以为旧帧没了。
    incoming = {d.state for d in decisions if d.kind == "pet"}
    existing = {p.stem.rsplit("_", 1)[0] for p in out_dir.glob("*.png")} \
        if out_dir.is_dir() else set()
    have = incoming | existing
    missing = [s for s in prep.VALID_STATES if s not in have]
    if missing:
        lender = "idle" if "idle" in have else "内置贴图"
        lines.append(f"缺口 : 缺 {'/'.join(missing)} —— 缺的动作会自动借 {lender} 的帧顶，"
                     "不会崩，只是没有那个动作的样子")
    kept = sorted(existing - incoming)
    if kept:
        lines.append(f"保留 : {'/'.join(kept)} 沿用已有帧，本次不动")

    # 一个动作来自多个文件 = 极可能是两个不同角色被拼进同一套动作，画面会"变脸"
    multi: dict[str, list[str]] = {}
    for d in decisions:
        if d.kind == "pet":
            multi.setdefault(d.state, []).append(d.src.name)
    clash = {k: v for k, v in multi.items() if len(v) > 1}
    if clash:
        lines.append("")
        lines.append("冲突 : 同一个动作匹配到了多个文件，入库后会连在一起播放，"
                     "如果它们不是同一个角色，画面会中途变脸 ——")
        for state, names_ in sorted(clash.items()):
            lines.append(f"  · {state} <- {' + '.join(names_)}  "
                         f"（用 --as 分开，或先只放一套进 inbox）")
    notes = [d for d in decisions if d.note]
    if notes:
        lines.append("")
        lines.append("提醒 :")
        for d in notes:
            lines.append(f"  · {d.src.name} —— {d.note}")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------- 主流程

def _refresh_icon(decisions: list[Decision], skip: bool) -> list[str]:
    """贴图换完，顺手把图标也换掉。

    图标是从贴图里裁出来的。贴图变了、图标没跟着变的话，
    托盘和游戏窗口上就还是上一只宠物 —— 这个坑已经踩过一次，
    所以做成入库流程的一部分，而不是留给用户自己想起来。

    例外：本次入库里带了专门的图标文件时，以**用户给的那张**为准。
    用户肯单独挑一张图当图标，意图比"从贴图裁个头部"明确得多。
    """
    if skip:
        return ["更新图标  已跳过（--no-icon），需要时跑 tools/make_icon.py"]

    given = [d for d in decisions if d.kind == "icon"]
    if given:
        log = []
        for d in given:
            try:
                ico = iconlib.make_ico(d.target)
            except OSError as exc:
                log.append(f"更新图标  {d.target} 补 .ico 失败：{exc}")
                continue
            log.append(f"更新图标  以你提供的 {d.src.name} 为准，"
                       f"并补出多尺寸 {Path(ico).name}")
        return log

    if not any(d.kind == "pet" for d in decisions):
        return []
    try:
        rep = iconlib.refresh()
    except (FileNotFoundError, ValueError, OSError) as exc:
        return [f"更新图标  失败：{exc}（可单独跑 tools/make_icon.py）"]

    names = rep["png"].name + (f" + {rep['ico'].name}" if rep["ico"] else "")
    return [f"更新图标  {names} <- {rep['source'].name}"]


def main(argv: list[str] | None = None) -> int:
    _cls()
    ap = argparse.ArgumentParser(
        description="把 assets/raw/inbox/ 里的素材自动分派到项目各处",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=str(INBOX), help="要扫描的目录，默认 assets/raw/inbox")
    ap.add_argument("--apply", action="store_true", help="真正执行（默认只看方案）")
    ap.add_argument("--as", dest="as_state", default=None,
                    choices=prep.VALID_STATES, help="把所有图片强制当成这个动作")
    ap.add_argument("--map", action="append", default=[], metavar="关键词=动作",
                    help="逐个文件指定：文件名里含「关键词」的就当这个动作，可重复。"
                         "例：--map 晃脚=idle --map 害怕=drag")
    ap.add_argument("--zoom", action="append", default=[], metavar="关键词=倍数",
                    help="微调某套素材的缩放，可重复。例：--zoom 晃脚=1.15 让它大一点")
    ap.add_argument("--scale", action="append", default=[], metavar="关键词=缩放比",
                    help="直接钉死某套素材的缩放比（不跟本批最小值走），可重复。"
                         "换素材时想让新动作的狗和已有动作一样大，就用它："
                         "例：--scale 逗他玩=0.56 --scale 喂一口=0.44")
    ap.add_argument("--motion", choices=("flatten", "keep"), default="flatten",
                    help="素材自带的位移怎么处理。默认 flatten：每帧底边落地，"
                         "位移交给窗口，适合原地做动作的素材（坐着晃脚、躺着打滚）；"
                         "keep：保留垂直位移，适合自带弹跳/发抖的素材，"
                         "否则腾空会被压成「脚踩地原地伸缩」")
    ap.add_argument("--builtin", action="store_true",
                    help="写进 assets/pet（覆盖内置贴图），默认写 custom_pet")
    ap.add_argument("--face", choices=("keep", "left", "right"), default="keep",
                    help="这批素材原图朝哪边走。keep（默认）沿用已有声明；"
                         "写 left/right 会记进 facing.json，用来判断要不要水平镜像 —— "
                         "设错了的表现就是「狗倒着走」")
    ap.add_argument("--keep-old", action="store_true",
                    help="保留目标目录里同动作的旧帧（默认清掉，避免新旧画风混在一起）")
    ap.add_argument("--size", type=int, default=128, help="贴图输出边长，默认 128")
    ap.add_argument("--no-archive", action="store_true",
                    help="执行后不把原文件挪进 _archive/")
    ap.add_argument("--no-icon", action="store_true",
                    help="入库宠物素材后不自动更新图标")
    args = ap.parse_args(argv)

    scan = Path(args.dir).expanduser()
    if not scan.is_dir():
        scan.mkdir(parents=True, exist_ok=True)
        print(f"已创建投递目录：{scan}")

    items = sorted(p for p in scan.iterdir() if not p.name.startswith("."))
    if not items:
        # 没有新素材，也可能只是来改朝向的：这项是幂等的元数据，不要求 --apply
        if args.face != "keep":
            for line in _apply_face(args.face, _pet_out_dir(args.builtin)):
                print("[落位] " + line)
            return 0
        print(f"{scan} 是空的。把下载好的 GIF / PNG / 音频 / 字体丢进去即可。")
        return 0

    overrides: list[tuple[str, str]] = []
    for spec in args.map:
        kw, _, st = spec.partition("=")
        if not st:
            print(f"--map 要写成「关键词=动作」，收到的是「{spec}」")
            return 2
        if st not in prep.VALID_STATES:
            print(f"--map 的动作只能是 {'/'.join(prep.VALID_STATES)}，收到「{st}」")
            return 2
        overrides.append((kw.lower(), st))

    zoom: list[tuple[str, float]] = []
    for spec in args.zoom:
        kw, _, z = spec.partition("=")
        try:
            zoom.append((kw.lower(), float(z)))
        except ValueError:
            print(f"--zoom 要写成「关键词=倍数」，收到的是「{spec}」")
            return 2

    fixed: list[tuple[str, float]] = []
    for spec in args.scale:
        kw, _, s = spec.partition("=")
        try:
            value = float(s)
        except ValueError:
            print(f"--scale 要写成「关键词=缩放比」，收到的是「{spec}」")
            return 2
        if value <= 0:
            print(f"--scale 的缩放比要大于 0，收到的是「{spec}」")
            return 2
        fixed.append((kw.lower(), value))

    decisions = [classify(p, args.as_state, tuple(overrides)) for p in items]
    names = _assign_indices(decisions)
    out_dir = _pet_out_dir(args.builtin)
    plan = plan_pet(decisions, args.size, tuple(zoom), tuple(fixed))

    print(report(decisions, names, out_dir, args.apply, scan, plan))

    if not args.apply:
        print("确认无误后加 --apply 执行。")
        return 0

    log = _apply_pet(decisions, names, out_dir, args.size, args.keep_old,
                     plan, args.motion)
    log += _apply_face(args.face, out_dir)
    log += _apply_other(decisions)
    log += _refresh_icon(decisions, args.no_icon)
    for line in log:
        print("[落位] " + line)

    if not args.no_archive:
        ARCHIVE.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%m%d_%H%M")
        bucket = ARCHIVE / stamp
        bucket.mkdir(parents=True, exist_ok=True)
        moved = 0
        for d in decisions:
            try:
                shutil.move(str(d.src), str(bucket / d.src.name))
                moved += 1
            except (OSError, shutil.Error):
                pass
        print(f"[归档] {moved} 个原文件 -> {bucket.relative_to(ROOT)}")

    print("\n下一步：")
    print("  python main.py                         # 直接看效果（自动优先读 custom_pet）")
    print("  python tools/render_preview.py         # 生成动作帧对照表 preview_sheet.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
