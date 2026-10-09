"""小游戏：接狗狗。

玩法：小黄狗在屏幕底部左右跑，接住天上掉下来的**小白狗**（+分）；
天上还会掉**炸弹**——接到炸弹扣 1 滴血，**漏掉**一只小白狗也扣 1 滴血。
血量上限 5 滴，扣光即 game over。

天上偶尔还会掉一根**骨头**（+分，有伤时回 1 滴血）——这是 ``heal()``
在写出来很久之后第一次真正有了调用方。

和「弹跳得分」共享的东西（窗口尺寸 / HUD 底板 / 结算浮层 / 金币汇率）都在
``game.common`` 里，见那个文件开头的说明。这里只写本游戏自己的逻辑。

四个刻意的设计取舍
------------------

1. **落体也走 ``pet.physics.Motion``**。小白狗、炸弹和骨头只需要一个下落速度，
   不吃重力，所以用 ``use_gravity=False`` 调它。好处是它和接板共用同一套
   矩形判交（``overlaps``），碰撞代码不用写第二份。

2. **素材是可插拔的，且缺了也能玩**。``assets/game/`` 下的
   ``catcher_*.png`` / ``puppy*_*.png`` / ``bomb_*.png`` / ``bone_*.png``
   有就加载（支持多帧动画），没有就用 QPainter 画一个**占位形象**。
   占位不是成品美术，只是"别让屏幕空着"——等真素材到位，丢进目录就自动替换，
   **不用改这里任何一行代码**。小白狗可以放**多套**（``puppy_a_`` / ``puppy_b_`` / …），
   掉下来时随机挑一套，前缀是扫目录得出的，加套数不用改代码。
   背景图 ``bg_catch.png`` 同理，读不到就回退到代码画的渐变天空。

3. **难度只由"活着的时长"决定**。不随分数涨，所以在单位置发呆和
   疯狂接狗面对的难度曲线一样，不会因为手气好而突然被压死。

4. **后半程才刮风**。落体前 40% 的难度里都是笔直落下来的（``vx`` 恒为 0，
   和以前完全一样），之后一部分会被风吹偏、撞到左右边会弹回来。
   这是为了让"越玩越难"不只体现在速度和密度上 —— 速度和密度加到最后
   有手速上限，风向则要求你提前判断。

三条保底规则（不然玩起来会很不讲理）
------------------------------------
* 开局前 ``GRACE_SPAWNS`` 个必是小白狗，不会一睁眼就被炸弹糊脸。
* 炸弹最多连出 ``MAX_BOMB_STREAK`` 个，之后强制来一只小白狗。
* 骨头**先掷**，不受上面那条"炸弹连出上限"约束 —— 挨完一串炸弹正是最
  需要一根骨头的时候，被那条规则挡掉就太不讲理了。
"""

from __future__ import annotations

import math
import random
from pathlib import Path

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import (QColor, QFontMetricsF, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap)

from game.common import (BG_CATCH, GROUND_Y, HUD_H, W, H, GameWindow,
                         load_background, paint_hud_bar, ui_font)
from pet.paths import game_asset_dir
from pet.physics import Motion

# ---------------------------------------------------------------- 玩法数值

MAX_HP = 5                       # 血量上限

CATCHER_W, CATCHER_H = 104, 78   # 小黄狗（接板）尺寸
CATCHER_SPEED = 560.0            # 水平最高速度 px/s
CATCHER_ACCEL = 16.0             # 速度趋近系数，越大越跟手
MOUSE_GAIN = 12.0                # 鼠标跟随的比例增益

PUPPY_SIZE = 58                  # 小白狗
BOMB_SIZE = 54                   # 炸弹
BONE_SIZE = 46                   # 骨头（比炸弹小一圈：它是"捡漏"用的，别太抢眼）

PUPPY_SCORE = 10                 # 接住一只小白狗的分数
COMBO_STEP = 5                   # 连击每满这么多只……
COMBO_BONUS = 10                 # ……额外奖这么多分
DAMAGE_PER_HIT = 1               # 漏一只 / 接一个炸弹，各扣几滴血

BONE_SCORE = 10                  # 接住骨头的分数（按一只小白狗算，别让它变刷分手段）
BONE_HEAL = 1                    # 有伤时额外回几滴血

FALL_SPEED_MIN, FALL_SPEED_MAX = 180.0, 360.0    # 下落速度区间 px/s
SPAWN_START, SPAWN_MIN = 0.95, 0.45              # 出怪间隔（秒），随难度收紧
BOMB_CHANCE_START, BOMB_CHANCE_END = 0.16, 0.44  # 出炸弹的概率区间
RAMP_TIME = 75.0                 # 难度爬满需要活多久（秒）

GRACE_SPAWNS = 3                 # 开局放水：前几个必是小白狗
MAX_BOMB_STREAK = 2              # 连续炸弹上限，超过就强制来小白狗

#: 骨头出现的难度门槛与概率。开门前一段时间不给：那会儿血是满的，
#: 接了也只是加分，还挤掉了一只小白狗的位置。
BONE_MIN_RAMP = 0.30
BONE_CHANCE = 0.12

#: 横向漂移（"风"）。难度过 ``DRIFT_MIN_RAMP`` 之后才起风，幅度线性爬满。
#:
#: 上限刻意压在 130 px/s：接板最高速度 560 px/s、下落速度 180~360 px/s，
#: 风再大就变成"够不着"，而不是"要提前判断"。有风之后也**不是每个都飘**
#: （``DRIFT_CHANCE``），否则整局都在追东西，反而单调。
DRIFT_MIN_RAMP = 0.40
DRIFT_MAX = 130.0
DRIFT_CHANCE = 0.55
DRIFT_SPEED_MIN_RATIO = 0.45     # 单个落体的风速在 45%~100% 之间随机

FRAME_FPS = 8                    # 多帧素材的动画帧率
FALL_LIMIT = H + 240             # 落体的"掉出屏幕"边界，比地面低很多

#: 会从天上掉下来的三种东西。``spawn(kind=...)`` 只认这三个，
#: 别拿 ``SPRITE_SIZE`` 的键来判断 —— 那里面还有"接板"，而接板不会掉下来。
FALLER_KINDS = ("puppy", "bomb", "bone")

#: 固定单套的素材前缀 -> 显示尺寸。改前缀就改这里一处。
SPRITE_PREFIX = {"catcher": "catcher", "bomb": "bomb", "bone": "bone"}
SPRITE_SIZE = {"catcher": CATCHER_W, "puppy": PUPPY_SIZE, "bomb": BOMB_SIZE,
               "bone": BONE_SIZE}

#: 小白狗可以有多套，生成时随机挑一套 —— 同时掉下来几种不同的狗比
#: 清一色同一只热闹。缺哪套都不影响，一套都没有才走占位绘制。
#:
#: 前缀靠**扫目录**得出（``puppy_00.png`` → ``puppy``；``puppy_a_00.png`` → ``puppy_a``），
#: 所以多加一套只要丢文件，不用回来改这里。下面这个元组只是"目录读不出来时的兜底"。
PUPPY_PREFIXES = ("puppy", "puppy_a", "puppy_b", "puppy_c")

# 占位形象的配色（真素材到位后这些就只用于地面和天空了）
CATCHER_BODY = QColor(246, 199, 74)
CATCHER_DARK = QColor(219, 165, 44)
PUPPY_BODY = QColor(252, 250, 245)
PUPPY_DARK = QColor(214, 210, 201)
BOMB_BODY = QColor(126, 132, 156)     # 灰蓝：比纯黑柔和，压在浅色背景上不突兀
BOMB_DARK = QColor(96, 102, 126)
BOMB_INK = QColor(43, 43, 43)         # 和狗贴图一样的粗描边色（骨头也用它）
BONE_BODY = QColor(252, 243, 214)     # 奶白偏黄：和纯白的小白狗一眼分得开
SPARK_WARM = QColor(255, 156, 92)
SPARK_HEART = QColor(245, 112, 138)
SPARK_HURT = QColor(206, 74, 84)      # 扣血用红色，比灰烟显眼，也和红闪是一套语言
SPARK_HEAL = QColor(112, 196, 152)    # 回血用青绿：红=掉血、绿=回血，不用读字就懂
HEART_FULL = QColor(242, 101, 122)
HEART_EMPTY = QColor(226, 231, 239)


def _frame_index(path: Path) -> int:
    """``puppy_03.png`` -> 3。解析不了就当 0，不抛异常。"""
    try:
        return int(path.stem.rsplit("_", 1)[-1])
    except (IndexError, ValueError):
        return 0


def discover_puppy_prefixes(root: Path) -> list[str]:
    """扫出目录里所有小白狗套的前缀（去掉序号后缀、去重、排序）。

    ``puppy_00.png`` -> ``puppy``；``puppy_a_00.png`` -> ``puppy_a``。
    这样多加一套小白狗只要丢文件，不必改代码；读不出来时退回 ``PUPPY_PREFIXES``。
    """
    if not root or not Path(root).is_dir():
        return list(PUPPY_PREFIXES)
    seen = set()
    for p in Path(root).glob("puppy*.png"):
        prefix = p.stem.rsplit("_", 1)[0] if "_" in p.stem else p.stem
        if prefix:
            seen.add(prefix)
    if not seen:
        return list(PUPPY_PREFIXES)
    # 不带字母的 ``puppy`` 排最前，单套老素材（只有 puppy_*.png）行为不变
    return sorted(seen, key=lambda s: (s != "puppy", s))


def load_sprites(root: Path, prefix: str, size: int) -> list[QPixmap]:
    """读一整套 ``<prefix>_*.png``（也接受单个 ``<prefix>.png``）。

    读不到就返回空列表 —— 调用方据此走占位形象的绘制分支。
    缩放用 KeepAspectRatio，实际绘制时再按比例居中，所以素材是什么长宽比都不会被拉变形。
    """
    if not root or not Path(root).is_dir():
        return []
    root = Path(root)
    files = sorted(root.glob(f"{prefix}_*.png"), key=_frame_index)
    if not files:
        single = root / f"{prefix}.png"
        files = [single] if single.exists() else []

    out: list[QPixmap] = []
    for path in files:
        pm = QPixmap(str(path))
        if pm.isNull():
            continue
        out.append(pm.scaled(size, size,
                             Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation))
    return out


# ---------------------------------------------------------------- 绘制零件

def _blit_centered(p: QPainter, pm: QPixmap, x: float, y: float,
                   w: float, h: float) -> None:
    """把贴图按自身比例居中画进 (x,y,w,h) 这个格子，不拉伸。"""
    pw, ph = pm.width(), pm.height()
    if pw <= 0 or ph <= 0:
        return
    k = min(w / pw, h / ph)
    dw, dh = max(1, round(pw * k)), max(1, round(ph * k))
    p.drawPixmap(int(x + (w - dw) / 2), int(y + (h - dh) / 2), dw, dh, pm)


def _draw_outlined_text(p: QPainter, cx: float, cy: float, text: str,
                        color: QColor, font, *,
                        outline: QColor | None = None, width: float = 3.0) -> None:
    """居中画一行带描边的字。

    飘字经常正好落在角色身上（扣血提示就在狗肚子上），只画纯色字会糊成一片。
    用"先描边再填色"的路径画法，比把同一个字偏移四次画四遍干净得多 ——
    后者的白边会顺着细笔画渗进字里面，字就变成空心的了。
    """
    path = QPainterPath()
    fm = QFontMetricsF(font)
    x = cx - fm.horizontalAdvance(text) / 2.0
    y = cy + (fm.ascent() - fm.descent()) / 2.0
    path.addText(x, y, font, text)

    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(outline or QColor(255, 255, 255, 235), width,
                  Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                  Qt.PenJoinStyle.RoundJoin))
    p.drawPath(path)

    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawPath(path)


def _heart_path(cx: float, cy: float, s: float) -> QPainterPath:
    """心形路径：两段三次贝塞尔，s 是整体宽度。"""
    path = QPainterPath()
    bottom = cy + s * 0.36
    path.moveTo(cx, bottom)
    path.cubicTo(cx - s * 0.72, cy - s * 0.04, cx - s * 0.46, cy - s * 0.62,
                 cx, cy - s * 0.14)
    path.cubicTo(cx + s * 0.46, cy - s * 0.62, cx + s * 0.72, cy - s * 0.04,
                 cx, bottom)
    path.closeSubpath()
    return path


def _draw_heart(p: QPainter, cx: float, cy: float, s: float, filled: bool) -> None:
    path = _heart_path(cx, cy, s)
    if filled:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(HEART_FULL)
    else:
        p.setPen(QPen(HEART_EMPTY.darker(104), 1.5))
        p.setBrush(QColor(250, 251, 253))
    p.drawPath(path)


# ---------------------------------------------------------------- 占位形象
# 下面三个函数只在"对应素材没找到"时走。画得够用就行，不值得为它们调美术。

def _draw_catcher_placeholder(p: QPainter, x: float, y: float,
                              w: float, h: float) -> None:
    """小黄狗（侧脸朝右，身体压得很低，像个会跑的簸箕）。"""
    p.setPen(Qt.PenStyle.NoPen)
    # 影子
    p.setBrush(QColor(96, 108, 92, 46))
    p.drawEllipse(int(x + w * 0.04), int(y + h - 8), int(w * 0.92), 11)

    # 四条腿
    p.setBrush(CATCHER_DARK)
    for fx in (0.16, 0.28, 0.68, 0.80):
        p.drawRoundedRect(int(x + w * fx), int(y + h * 0.60),
                          max(6, int(w * 0.08)), int(h * 0.40), 3, 3)

    # 身体
    body = QRect(int(x), int(y + h * 0.20), int(w), int(h * 0.52))
    p.setBrush(CATCHER_BODY)
    p.drawRoundedRect(body, int(h * 0.26), int(h * 0.26))

    # 尾巴（往上翘一点，显得在使劲）
    tail = QPainterPath()
    tail.moveTo(x + w * 0.02, y + h * 0.44)
    tail.cubicTo(x - w * 0.16, y + h * 0.30, x - w * 0.14, y + h * 0.02,
                 x + w * 0.04, y + h * 0.08)
    p.setPen(QPen(CATCHER_DARK, max(3.0, w * 0.05), Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(tail)
    p.setPen(Qt.PenStyle.NoPen)

    # 头（右侧，抬起来看天上掉下来的东西）
    head_d = h * 0.54
    hx, hy = x + w - head_d, y + h * 0.06
    p.setBrush(CATCHER_BODY)
    p.drawEllipse(int(hx), int(hy), int(head_d), int(head_d))

    # 耳朵
    p.setBrush(CATCHER_DARK)
    p.drawEllipse(int(hx + head_d * 0.02), int(hy + head_d * 0.06),
                  int(head_d * 0.30), int(head_d * 0.52))
    p.drawEllipse(int(hx + head_d * 0.66), int(hy + head_d * 0.04),
                  int(head_d * 0.30), int(head_d * 0.50))

    # 眼睛 / 鼻子 / 嘴
    p.setBrush(QColor(58, 48, 42))
    p.drawEllipse(int(hx + head_d * 0.30), int(hy + head_d * 0.38),
                  max(3, int(head_d * 0.13)), max(3, int(head_d * 0.15)))
    p.setBrush(QColor(70, 56, 48))
    p.drawEllipse(int(hx + head_d * 0.72), int(hy + head_d * 0.56),
                  max(4, int(head_d * 0.20)), max(3, int(head_d * 0.15)))
    p.setPen(QPen(QColor(120, 92, 70), 1.6))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(int(hx + head_d * 0.52), int(hy + head_d * 0.58),
              int(head_d * 0.40), int(head_d * 0.28), 200 * 16, 140 * 16)


def _draw_puppy_placeholder(p: QPainter, x: float, y: float,
                            w: float, h: float, t: float) -> None:
    """小白狗（侧脸朝右，四腿摊开，像被拎出来那种）。"""
    p.setPen(Qt.PenStyle.NoPen)
    # 身体
    body = QRect(int(x + w * 0.04), int(y + h * 0.34), int(w * 0.80), int(h * 0.40))
    p.setBrush(PUPPY_BODY)
    p.drawRoundedRect(body, int(h * 0.20), int(h * 0.20))
    p.setPen(QPen(PUPPY_DARK, 1.4))
    p.drawRoundedRect(body, int(h * 0.20), int(h * 0.20))
    p.setPen(Qt.PenStyle.NoPen)

    # 腿（轻微摆动，让静态素材也有点生气）
    swing = 1.0 + 0.35 * (0.5 + 0.5 * math.sin(t * 7.0))
    p.setBrush(PUPPY_DARK)
    for fx, dl in ((0.14, 1.0), (0.30, 1.0), (0.62, swing), (0.76, swing)):
        p.drawRoundedRect(int(x + w * fx), int(y + h * 0.68),
                          max(5, int(w * 0.09)), int(h * 0.24 * dl), 3, 3)

    # 尾巴
    p.setPen(QPen(PUPPY_DARK, max(3.0, w * 0.07), Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap))
    twist = 0.5 + 0.5 * math.sin(t * 6.0 + 1.0)
    p.drawArc(int(x - w * 0.14), int(y + h * 0.12 + h * 0.10 * twist),
              int(w * 0.30), int(h * 0.34), 300 * 16, 240 * 16)
    p.setPen(Qt.PenStyle.NoPen)

    # 头
    head_d = h * 0.54
    hx, hy = x + w * 0.56, y + h * 0.06
    p.setBrush(PUPPY_BODY)
    p.drawEllipse(int(hx), int(hy), int(head_d), int(head_d))
    p.setPen(QPen(PUPPY_DARK, 1.4))
    p.drawEllipse(int(hx), int(hy), int(head_d), int(head_d))
    p.setPen(Qt.PenStyle.NoPen)

    # 耳朵
    p.setBrush(PUPPY_DARK)
    p.drawEllipse(int(hx + head_d * 0.06), int(hy + head_d * 0.02),
                  int(head_d * 0.30), int(head_d * 0.50))
    p.drawEllipse(int(hx + head_d * 0.62), int(hy - head_d * 0.02),
                  int(head_d * 0.32), int(head_d * 0.52))

    # 眼睛 / 鼻子
    p.setBrush(QColor(58, 52, 48))
    p.drawEllipse(int(hx + head_d * 0.34), int(hy + head_d * 0.40),
                  max(3, int(head_d * 0.12)), max(3, int(head_d * 0.14)))
    p.setBrush(QColor(84, 68, 62))
    p.drawEllipse(int(hx + head_d * 0.80), int(hy + head_d * 0.52),
                  max(4, int(head_d * 0.16)), max(3, int(head_d * 0.12)))


def _draw_bomb_placeholder(p: QPainter, x: float, y: float,
                           w: float, h: float, t: float) -> None:
    """炸弹：圆球 + 高光 + 冒火星的引线。

    画法必须和狗贴图是一套语言（粗描边 + 纯色填充）。第一版是"深灰渐变球"，
    单独看没问题，放在浅色背景上活像贴了张深色贴纸 —— 和旁边工笔画线的小狗
    完全不是一回事。现在改成描边卡通风，淡灰蓝底 + 近黑描边。
    """
    d = min(w, h) * 0.78
    bx, by = x + (w - d) / 2, y + (h - d) / 2 + h * 0.07
    sw = max(2.4, d * 0.075)          # 描边粗细跟着球径走

    # 引线（先画，被球压住一端）
    fuse = QPainterPath()
    fuse.moveTo(bx + d * 0.60, by + d * 0.12)
    fuse.cubicTo(bx + d * 0.84, by - d * 0.08, bx + d * 0.96, by - d * 0.20,
                 bx + d * 0.90, by - d * 0.38)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(BOMB_INK, sw, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap))
    p.drawPath(fuse)
    p.setPen(QPen(QColor(214, 176, 126), sw * 0.55, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap))
    p.drawPath(fuse)

    # 球体：纯色填充 + 粗描边
    p.setBrush(BOMB_BODY)
    p.setPen(QPen(BOMB_INK, sw, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.drawEllipse(int(bx), int(by), int(d), int(d))

    # 高光：一块大的 + 一小点，位置和狗贴图的高光习惯一致（左上）
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(255, 255, 255, 118))
    p.drawEllipse(int(bx + d * 0.17), int(by + d * 0.15),
                  int(d * 0.26), int(d * 0.21))

    # 火星（呼吸）
    spark = 0.72 + 0.28 * math.sin(t * 13.0)
    sr = d * 0.19 * spark
    sx, sy = bx + d * 0.92, by - d * 0.38
    p.setBrush(QColor(255, 196, 92, 120))
    p.drawEllipse(int(sx - sr), int(sy - sr), int(sr * 2), int(sr * 2))
    p.setBrush(QColor(255, 224, 140))
    p.drawEllipse(int(sx - sr * 0.5), int(sy - sr * 0.5),
                  max(2, int(sr)), max(2, int(sr)))


def _draw_bone_placeholder(p: QPainter, x: float, y: float,
                           w: float, h: float, t: float) -> None:
    """骨头：一根两头带节的棒子。

    画法和炸弹一样是"纯色填充 + 粗描边"（``BOMB_INK``）：奶白的身子压在
    浅色天空上本来几乎看不见，靠这道深描边才有轮廓 —— 和旁边工笔画线的小狗、
    炸弹才是同一套语言。

    骨节先画、棒子后压：反过来的话棒子的描边会横切过四个骨节，
    看着像被绳子捆住了。轻微上下浮动（``t``）让静态道具也有点生气。
    """
    d = min(w, h) * 0.92
    cx = x + w / 2.0
    cy = y + h / 2.0 + h * 0.06 * math.sin(t * 5.0)

    knob = d * 0.34                  # 骨节直径
    shaft_h = d * 0.26               # 棒子粗细
    off_x, off_y = d * 0.30, d * 0.11
    sw = max(2.0, d * 0.07)

    p.setPen(QPen(BOMB_INK, sw, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(BONE_BODY)

    # 注意 ``drawEllipse`` / ``drawRoundedRect`` 只有以 int 为坐标的重载
    # （带 qreal 的那两个要传 QRectF / QPointF），所以这里必须显式取整 ——
    # 和本文件其它占位函数一样。
    for sx in (-1, 1):
        for sy in (-1, 1):
            p.drawEllipse(int(cx + sx * off_x - knob / 2.0),
                          int(cy + sy * off_y - knob / 2.0),
                          int(knob), int(knob))
    p.drawRoundedRect(int(cx - d * 0.34), int(cy - shaft_h / 2.0),
                      int(d * 0.68), int(shaft_h),
                      shaft_h / 2.0, shaft_h / 2.0)

    # 一道高光，和狗贴图的高光习惯一致（左上）
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(255, 255, 255, 150))
    p.drawEllipse(int(cx - d * 0.20), int(cy - shaft_h * 0.34),
                  int(d * 0.16), int(shaft_h * 0.34))


# ---------------------------------------------------------------- 实体

class Faller:
    """一个从天上掉下来的东西。``kind`` 是 ``"puppy"`` / ``"bomb"`` / ``"bone"``。

    横向速度放在 ``body.vx`` 里，不再恒为 0 —— 见 ``CatchGame._give_drift``。
    它不需要自己的字段，``Motion`` 本来就带着 ``vx`` 和 ``edge_bounce``，
    这里再存一份就是三个地方要对齐的同一件事。
    """

    __slots__ = ("kind", "body", "gone", "variant")

    def __init__(self, kind: str, x: float, y: float, size: int, vy: float,
                 variant: int = 0):
        self.kind = kind
        self.body = Motion(x=x, y=y, w=size, h=size, gravity=0.0)
        self.body.vy = vy                 # use_gravity=False，这个速度会一直保持
        self.gone = False                 # 已结算（接住 / 挨炸 / 漏掉）
        self.variant = variant            # 用第几套小白狗贴图（炸弹不用）

    @property
    def center(self) -> tuple[float, float]:
        return self.body.center


class Spark:
    """接住 / 挨炸的粒子与飘字。"""

    def __init__(self, x: float, y: float, color: QColor, text: str = "",
                 n: int = 9, rise: bool = True):
        self.x, self.y = float(x), float(y)
        self.life, self.max_life = 0.0, 0.62
        self.color = QColor(color)
        self.text = text
        self.shards = [
            (random.uniform(-170, 170),
             random.uniform(-330, -120) if rise else random.uniform(-130, 130))
            for _ in range(n)
        ]

    def update(self, dt: float) -> bool:
        self.life += dt
        return self.life < self.max_life


# ---------------------------------------------------------------- 游戏

class CatchGame(GameWindow):
    """接狗狗小游戏窗口。

    窗口尺寸、计时器、结算浮层、关闭时发信号都在 ``GameWindow`` 里，
    这里只管本游戏的规则：接板、落体、血量与难度。
    """

    TITLE = "桌宠小游戏 · 接狗狗"
    OVERLAY_TITLE = "游戏结束"

    def __init__(self, bank, cfg, parent=None):
        super().__init__(bank, cfg, parent)
        self.setMouseTracking(True)       # 鼠标跟随需要，否则不按键收不到 move

        # ---- 本游戏自己的场景
        # 素材：有就加载，没有就 None（绘制时走占位分支）
        root = game_asset_dir()
        self.sprites = {
            kind: load_sprites(root, prefix, SPRITE_SIZE[kind])
            for kind, prefix in SPRITE_PREFIX.items()
        }
        # 小白狗有多套：前缀扫目录得出，空套直接丢掉（不然随机到空集会画不出东西）
        self.puppy_sets = [
            frames for frames in
            (load_sprites(root, p, PUPPY_SIZE)
             for p in discover_puppy_prefixes(root))
            if frames
        ]
        self.sprites["puppy"] = self.puppy_sets[0] if self.puppy_sets else []

        # 背景图（蓝天草地）。读不到就是 None，_paint_background 回退到代码画渐变。
        self._bg = load_background(BG_CATCH)

        self.catcher = Motion(x=(W - CATCHER_W) / 2, y=GROUND_Y - CATCHER_H,
                              w=CATCHER_W, h=CATCHER_H, gravity=0.0)
        self.fallers: list[Faller] = []
        self.pops: list[Spark] = []
        self.target_x: float | None = None      # 鼠标跟随时用

        self.hp = MAX_HP
        self.caught = 0                          # 累计接住的小白狗
        self.combo = 0
        self.best_combo = 0
        self.survived = 0.0

        self._spawn_timer = 0.0
        self._spawned = 0                        # 本局已出怪数（放水规则用）
        self._bomb_streak = 0
        self._hurt = 0.0                         # 受伤红闪 0..1
        self._shake = 0.0                        # 震屏 0..1
        self._clock = 0.0                        # 动画时钟

        # 云的位置一次定好，否则每帧重随机会闪成雪花屏
        self._clouds = [
            (self.rng.uniform(20, W - 160), self.rng.uniform(HUD_H + 26, 250),
             self.rng.uniform(0.7, 1.35))
            for _ in range(6)
        ]

        self._reset_scene(first=True)
        self.start_clock()

    # ================================================================ 难度

    def ramp(self) -> float:
        """难度进度 0..1，只看活了多久。"""
        return min(1.0, self.survived / RAMP_TIME)

    def spawn_interval(self) -> float:
        """出怪间隔（秒），越到后面越短。"""
        return SPAWN_START + (SPAWN_MIN - SPAWN_START) * self.ramp()

    def bomb_chance(self) -> float:
        """出炸弹的概率，越到后面越高。"""
        return BOMB_CHANCE_START + (BOMB_CHANCE_END - BOMB_CHANCE_START) * self.ramp()

    def bone_chance(self) -> float:
        """出骨头的概率。开局那一段是 0 —— 那时血还满着，接了只是加分。"""
        return 0.0 if self.ramp() < BONE_MIN_RAMP else BONE_CHANCE

    def drift_speed(self) -> float:
        """此刻的横向漂移速度上限（px/s）。难度过半才开始刮风，之后线性爬满。"""
        r = self.ramp()
        if r <= DRIFT_MIN_RAMP:
            return 0.0
        k = (r - DRIFT_MIN_RAMP) / (1.0 - DRIFT_MIN_RAMP)
        return DRIFT_MAX * k

    def fall_speed(self) -> float:
        """这一只的下落速度，在区间里带一点随机。"""
        base = FALL_SPEED_MIN + (FALL_SPEED_MAX - FALL_SPEED_MIN) * self.ramp()
        return base * self.rng.uniform(0.90, 1.10)

    # ================================================================ 一局

    def _reset_scene(self, first: bool = False) -> None:
        """新一局的起始状态。``GameWindow._restart()`` 也走这里。"""
        self._reset_match(first=first)

    def _reset_match(self, first: bool = False) -> None:
        self.fallers.clear()
        self.pops.clear()
        self.hp = MAX_HP
        self.score = 0
        self.caught = 0
        self.combo = 0
        self.best_combo = 0
        self.survived = 0.0
        self.over = False
        self._spawned = 0
        self._bomb_streak = 0
        self._hurt = 0.0
        self._shake = 0.0
        # 开局缓一下，别一进场就劈头盖脸
        self._spawn_timer = 0.6 if first else 0.45
        self._center_catcher()

    def _center_catcher(self) -> None:
        self.catcher.teleport((W - CATCHER_W) / 2, GROUND_Y - CATCHER_H)
        self.catcher.on_ground = True

    def _record_best(self) -> None:
        if self.score > self.cfg.best_catch:
            self.cfg.best_catch = self.score
            self.cfg.save()

    def _finish(self, early: bool = False) -> None:
        self.over = True
        self._record_best()
        earned = self._award_coins()
        headline = "提前收工" if early else "血量耗尽！"
        self.label_title.setText(f"{headline}本局得分 {self.score}")
        self.label_sub.setText(
            f"最高分 {self.cfg.best_catch}    接住 {self.caught} 只    "
            f"最长连击 {self.best_combo}    撑过 {self.survived:.0f} 秒    "
            f"+{earned} 金币{self.coins_note()}（共 {self.cfg.coins}）")
        self.overlay.show()
        self.overlay.raise_()
        self._center_overlay()

    # ================================================================ 循环

    def _settle(self, dt: float) -> None:
        self.catcher.stop()

    def _decay(self, dt: float) -> None:
        self._clock += dt
        self._hurt = max(0.0, self._hurt - dt * 2.6)
        self._shake = max(0.0, self._shake - dt * 4.0)
        super()._decay(dt)

    def _step(self, dt: float) -> None:
        self.survived += dt

        self._move_catcher(dt)
        self._spawn_step(dt)
        self._fall_step(dt)

    def _move_catcher(self, dt: float) -> None:
        desired = self._desired_vx()
        self.catcher.vx += (desired - self.catcher.vx) * min(1.0, CATCHER_ACCEL * dt)
        # 复用 Motion 的夹边逻辑：撞墙自动贴住，不用自己写 min/max
        self.catcher.update(dt, (0.0, 0.0, float(W), float(GROUND_Y)),
                            use_gravity=False)

    def _desired_vx(self) -> float:
        """想要的水平速度：鼠标跟随优先，其次键盘。"""
        if self.target_x is not None:
            err = (self.target_x - self.catcher.w / 2.0) - self.catcher.x
            return max(-CATCHER_SPEED, min(CATCHER_SPEED, err * MOUSE_GAIN))

        left = Qt.Key.Key_Left in self.keys or Qt.Key.Key_A in self.keys
        right = Qt.Key.Key_Right in self.keys or Qt.Key.Key_D in self.keys
        if left and not right:
            return -CATCHER_SPEED
        if right and not left:
            return CATCHER_SPEED
        return 0.0

    def _spawn_step(self, dt: float) -> None:
        self._spawn_timer -= dt
        if self._spawn_timer <= 0.0:
            self.spawn()
            self._spawn_timer += self.spawn_interval()

    def _fall_step(self, dt: float) -> None:
        bounds = (0.0, float(HUD_H), float(W), float(FALL_LIMIT))
        for f in self.fallers:
            if f.gone:
                continue
            f.body.update(dt, bounds, use_gravity=False)

            if self.catcher.overlaps(f.body):
                f.gone = True
                if f.kind == "bomb":
                    self._take_damage(f)
                elif f.kind == "bone":
                    self._on_bone(f)
                else:
                    self._on_caught(f)
            elif f.body.y > GROUND_Y:
                # 从接板旁边溜下去了。炸弹和骨头落地无害，只有小白狗算漏接 ——
                # 骨头漏掉不罚，是刻意的：它本来就是"能接就赚"，不该变成负担。
                f.gone = True
                if f.kind == "puppy":
                    self._on_missed(f)

        self.fallers = [f for f in self.fallers if not f.gone]

    # ================================================================ 出怪

    def _choose_kind(self) -> str:
        """决定下一个掉什么。三条保底规则在这里。

        骨头**先掷**：它不该被"炸弹连出上限"那条挡住 —— 刚挨完一串炸弹，
        正是最需要一根骨头的时候，被那条规则挡掉就太不讲理了。
        """
        if self._spawned < GRACE_SPAWNS:
            return "puppy"                      # 开局放水
        if self.rng.random() < self.bone_chance():
            return "bone"
        if self._bomb_streak >= MAX_BOMB_STREAK:
            return "puppy"                      # 不许连砸一串炸弹
        return "bomb" if self.rng.random() < self.bomb_chance() else "puppy"

    def spawn(self, kind: str | None = None) -> Faller:
        """生成一个落体。``kind`` 传 None 就按当前难度随机（带保底）。

        测试可以直接指定 kind，绕过随机和保底规则。
        """
        kind = kind if kind in FALLER_KINDS else self._choose_kind()
        size = SPRITE_SIZE[kind]
        # 小白狗随机挑一套贴图，让掉下来的狗不是清一色同一只
        variant = (self.rng.randrange(len(self.puppy_sets))
                   if kind == "puppy" and self.puppy_sets else 0)
        # x 范围保证"玩家一定够得着"：接板宽 104，能覆盖 0..W
        x = self.rng.uniform(0.0, float(W - size))
        f = Faller(kind, x, float(HUD_H - size), size, self.fall_speed(), variant)
        if kind != "bone":
            self._give_drift(f)               # 骨头不吹风，见 _give_drift 的说明
        self.fallers.append(f)

        self._spawned += 1
        self._bomb_streak = self._bomb_streak + 1 if kind == "bomb" else 0
        return f

    def _give_drift(self, f: Faller) -> None:
        """给一个落体加横向漂移（"风"）。

        在接狗狗之前，``Faller.body`` 建出来就没动过水平速度，所以所有东西
        都是笔直落下来的 —— 玩到后面只剩"往左还是往右"一个判断，全靠手速顶。
        这里让它真的会飘：撞到左右边界会**反弹**（``Motion`` 的 ``edge_bounce``），
        所以飘出去的那些还会飘回来，不会贴着边走完剩下的路。

        两个刻意的例外：

        * ``restitution`` 调成 1.0。默认的 0.30 会让它一碰边就慢下来，
          几趟之后几乎不飘了 —— 那这道风就只剩开局两秒有意思。
          这一程是"风"，不是弹性碰撞，不该掉速。
        * **骨头一律不飘**。它是个礼物，让礼物躲着人跑就变成折磨了。

        只有左右边界受影响：``Motion`` 的 ``edge_bounce`` 只作用于水平方向，
        垂直方向照旧按 ``vy`` 匀速下落、到底就被判"掉出去了"（见 ``_fall_step``）。
        """
        top = self.drift_speed()
        if top <= 0.0 or self.rng.random() >= DRIFT_CHANCE:
            return
        v = top * self.rng.uniform(DRIFT_SPEED_MIN_RATIO, 1.0)
        f.body.vx = v if self.rng.random() < 0.5 else -v
        f.body.edge_bounce = True
        f.body.restitution = 1.0

    # ================================================================ 结算

    def _on_caught(self, f: Faller) -> None:
        cx, cy = f.center
        self.caught += 1
        self.combo += 1
        self.best_combo = max(self.best_combo, self.combo)
        self.score += PUPPY_SCORE
        self.pops.append(Spark(cx, cy, SPARK_HEART, f"+{PUPPY_SCORE}"))

        if self.combo % COMBO_STEP == 0:          # 连击每满 5 只再来一笔
            self.score += COMBO_BONUS
            self.pops.append(Spark(cx, cy - 26, SPARK_WARM, f"连击 x{self.combo}"))

    def _on_missed(self, f: Faller) -> None:
        cx, cy = f.center
        self.pops.append(Spark(cx, min(cy, GROUND_Y - 12), SPARK_HURT, "漏了"))
        self._take_damage(f)

    def _on_bone(self, f: Faller) -> None:
        """接住骨头：加分，有伤就回一滴血。

        满血时那滴血不会浪费（``heal`` 自己也夹了上限），但也变不出血来 ——
        所以飘字改成纯加分，让玩家看得出"这一根回的是分，不是命"，
        不然会以为自己攒了血、下一只躲不掉时反而更慌。
        """
        cx, cy = f.center
        self.score += BONE_SCORE
        if self.hp < MAX_HP:
            self.heal(BONE_HEAL)
            self.pops.append(Spark(cx, cy, SPARK_HEAL, f"+{BONE_HEAL} 血"))
        else:
            self.pops.append(Spark(cx, cy, SPARK_HEAL, f"+{BONE_SCORE}"))

    def _take_damage(self, f: Faller) -> None:
        cx, cy = f.center
        self.hp = max(0, self.hp - DAMAGE_PER_HIT)
        self.combo = 0
        self._hurt = 1.0
        self._shake = 1.0
        self.pops.append(Spark(cx, cy, SPARK_HURT, f"-{DAMAGE_PER_HIT} 血"))
        if self.hp <= 0:
            self._finish()

    def heal(self, amount: int = 1) -> None:
        """回血，上限 ``MAX_HP``。

        这里曾经写着"目前玩法里没有来源，留给以后想加道具时用" —— 现在有来源了：
        接住骨头（``_on_bone`` 调的）。测试也一直用它。
        """
        self.hp = min(MAX_HP, self.hp + int(amount))

    # ================================================================ 输入

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_A, Qt.Key.Key_D):
            self.keys.add(key)
            # 一旦摸键盘就放弃鼠标跟随，否则鼠标会把狗一直拽在右上角
            self.target_x = None
            return
        if key == Qt.Key.Key_R:
            # 走 request_restart 而不是直接 _restart：这一局没打完的话
            # 要先弹确认框，否则按一下 R 分数就没了、连个提示都没有
            self.request_restart()
            return
        if key == Qt.Key.Key_Escape:
            self.request_close()
            return
        super().keyPressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        self.target_x = float(event.position().x())

    def leaveEvent(self, _event) -> None:
        self.target_x = None

    # ================================================================ 绘制

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        self._paint_background(p)

        # 震屏只晃场景，HUD 必须钉在原地 —— 否则扣血时读不出血条
        p.save()
        if self._shake > 0.01:
            p.translate(round(7.0 * self._shake
                              * math.sin(self._clock * 62.0)), 0)
        self._paint_fallers(p)
        self._paint_catcher(p)
        p.restore()

        self._paint_pops(p)
        self._paint_ground(p)
        self._paint_flash(p)
        self._paint_hud(p)

    def _paint_background(self, p: QPainter) -> None:
        if self._bg is not None:
            # 背景图自带天空、云和草地，铺满整个窗口（HUD 半透明底板压在上面）
            p.drawPixmap(0, 0, self._bg)
            return

        # 没有背景图时回退到代码画渐变 + 三朵静态的云
        g = QLinearGradient(0, HUD_H, 0, H)
        g.setColorAt(0.0, QColor(228, 240, 253))
        g.setColorAt(0.55, QColor(242, 246, 250))
        g.setColorAt(1.0, QColor(250, 247, 240))
        p.fillRect(QRect(0, HUD_H, W, H - HUD_H), g)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 132))
        for cx, cy, k in self._clouds:
            p.drawEllipse(int(cx), int(cy), int(78 * k), int(30 * k))
            p.drawEllipse(int(cx + 26 * k), int(cy - 14 * k),
                          int(60 * k), int(30 * k))
            p.drawEllipse(int(cx - 22 * k), int(cy + 6 * k),
                          int(52 * k), int(24 * k))

    def _sprite(self, kind: str, variant: int = 0) -> QPixmap | None:
        if kind == "puppy":
            if not self.puppy_sets:
                return None
            frames = self.puppy_sets[variant % len(self.puppy_sets)]
        else:
            frames = self.sprites.get(kind) or []
        if not frames:
            return None
        return frames[int(self._clock * FRAME_FPS) % len(frames)]

    def _paint_fallers(self, p: QPainter) -> None:
        for f in self.fallers:
            b = f.body
            pm = self._sprite(f.kind, f.variant)
            if pm is not None:
                _blit_centered(p, pm, b.x, b.y, b.w, b.h)
            elif f.kind == "puppy":
                _draw_puppy_placeholder(p, b.x, b.y, b.w, b.h, self._clock)
            elif f.kind == "bone":
                _draw_bone_placeholder(p, b.x, b.y, b.w, b.h, self._clock)
            else:
                _draw_bomb_placeholder(p, b.x, b.y, b.w, b.h, self._clock)

    def _paint_catcher(self, p: QPainter) -> None:
        b = self.catcher
        pm = self._sprite("catcher")
        if pm is not None:
            _blit_centered(p, pm, b.x, b.y, b.w, b.h)
        else:
            _draw_catcher_placeholder(p, b.x, b.y, b.w, b.h)

    def _paint_pops(self, p: QPainter) -> None:
        for s in self.pops:
            t = s.life / s.max_life
            alpha = int(255 * (1 - t))
            p.setPen(Qt.PenStyle.NoPen)
            for vx, vy in s.shards:
                px = s.x + vx * s.life
                py = s.y + vy * s.life + 0.5 * 700 * s.life ** 2
                c = QColor(s.color)
                c.setAlpha(alpha)
                p.setBrush(c)
                p.drawEllipse(int(px), int(py), 6, 6)
            if s.text and t < 0.72:
                c = QColor(s.color)
                c.setAlpha(int(255 * (1 - t / 0.72)))
                o = QColor(255, 255, 255)
                o.setAlpha(int(235 * (1 - t / 0.72)))
                _draw_outlined_text(p, s.x, s.y - 14 - 24 * t, s.text, c,
                                    ui_font(12, bold=True), outline=o)

    def _paint_ground(self, p: QPainter) -> None:
        if self._bg is not None:
            return            # 背景图自带草地，再画一条会看出是两层边
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(203, 224, 206))
        p.drawRoundedRect(0, GROUND_Y, W, H, 10, 10)
        p.setBrush(QColor(224, 240, 225))
        p.drawRoundedRect(0, GROUND_Y, W, 9, 4, 4)

    def _paint_flash(self, p: QPainter) -> None:
        """挨打时整个场景压一层红。扣血必须有反馈，不然玩家不知道发生了什么。"""
        if self._hurt <= 0:
            return
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(228, 74, 84, int(78 * self._hurt)))
        p.drawRect(QRect(0, HUD_H, W, H - HUD_H))

    def _paint_hud(self, p: QPainter) -> None:
        paint_hud_bar(p, W)

        p.setPen(QColor(48, 56, 70))
        p.setFont(ui_font(15, bold=True))
        p.drawText(20, 0, 170, HUD_H, Qt.AlignmentFlag.AlignVCenter,
                   f"得分 {self.score}")

        p.setFont(ui_font(11))
        p.setPen(QColor(120, 130, 148))
        p.drawText(196, 0, 150, HUD_H, Qt.AlignmentFlag.AlignVCenter,
                   f"最高 {max(self.cfg.best_catch, self.score)}")

        if self.combo >= 2:
            p.setFont(ui_font(11, bold=True))
            p.setPen(SPARK_HEART.darker(112))
            p.drawText(352, 0, 150, HUD_H, Qt.AlignmentFlag.AlignVCenter,
                       f"连击 ×{self.combo}")

        # ---- 右侧：存活时间 + 血条（五颗心）
        hsize, hgap = 20.0, 5.0
        hw = MAX_HP * hsize + (MAX_HP - 1) * hgap
        hx = W - 26 - hw
        p.setFont(ui_font(11))
        p.setPen(QColor(120, 130, 148))
        p.drawText(int(hx - 112), 0, 100, HUD_H,
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                   f"{self.survived:.0f}s")

        cy = HUD_H / 2.0
        for i in range(MAX_HP):
            cx = hx + i * (hsize + hgap) + hsize / 2.0
            _draw_heart(p, cx, cy, hsize, filled=i < self.hp)

        p.setFont(ui_font(9))
        p.setPen(QColor(150, 158, 172))
        p.drawText(20, HUD_H + 8, W - 40, 24, Qt.AlignmentFlag.AlignLeft,
                   "← → / 鼠标 移动     接住小白狗加分     漏掉或接到炸弹都扣血     "
                   "R 重开     Esc 退出")
