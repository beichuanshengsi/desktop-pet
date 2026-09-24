"""素材加载。

只做一件事：把 ``assets/pet/``（或 ``custom_pet/``）下的图片读成按状态分组的
QPixmap 列表。命名规范由 ``tools/prep_sticker.py`` 保证，所以这里的解析逻辑
可以保持得很薄。

**一个状态可以有多套素材**
------------------------

    单套（老写法）   poke_00.png  poke_01.png ...
    多套             poke_a_00.png  poke_b_00.png ...
                     └套名用字母，最后一段永远是帧序

套名的意义是"同一个动作的几种演法"。窗口层在每次触发互动时会随机挑一套
（见 ``PetWindow._pick_set``），于是一套贴图能演出好几种反应。
不带套名的老素材不会被冷落：它就是"唯一的那一套"，查询时不传 ``set_name``
就能拿到。

两个设计取舍：
* 缺状态时不留空档——直接借用 idle 的帧兜底，让程序永远能显示出来。
* 缩放结果按 (状态, 套名, 尺寸) 整组缓存，避免每帧都做一次 SmoothTransformation。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap

from .behavior import KEYS as STATES

#: ``STATES`` 直接来自行为状态机（``pet/behavior.py`` 的 ``State``）——
#: **状态清单只有那一份实现**。以前这里另抄一遍，加一个动作就得记着改两处，
#: 漏掉的那次会表现为"素材放进去了但程序不认"。
#: 加载器按它扫目录（见 ``AssetBank.load``）。

#: 无套名素材所属的"套"。老素材、内置素材全落在这里。
DEFAULT_SET = ""


def _split(path: Path, state: str) -> tuple[str, int]:
    """把文件名拆成 (套名, 帧序)。

    ``poke_a_03.png`` → ``("a", 3)``；
    ``poke_03.png``   → ``("", 3)``（无套名 = 默认套）。

    套名只认"非纯数字"的第一段，所以不会把 ``poke_03`` 里的序号误当成套名。
    """
    rest = path.stem[len(state) + 1:]
    parts = rest.split("_")
    if len(parts) >= 2 and not parts[0].isdigit():
        set_name = parts[0]
    else:
        set_name = DEFAULT_SET
    try:
        return set_name, int(parts[-1])
    except ValueError:
        return set_name, 0


def _frame_index(path: Path) -> int:
    try:
        return int(path.stem.rsplit("_", 1)[-1])
    except (IndexError, ValueError):
        return 0


def set_files(root: Path, state: str, set_name: str | None = DEFAULT_SET) -> list[Path]:
    """该状态**某一套**的帧文件，按帧序排好。``set_name=None`` 就是默认套。

    为什么要专门有个函数：一个状态可以放多套素材之后，直接
    ``glob("poke_*.png")`` 会同时命中 ``poke_00`` / ``poke_a_00`` / ``poke_b_00``，
    把三套混成一条 43 帧的序列（预览图上会写成"poke 有 43 帧"，其实是三套拼的）。
    程序本体走 ``AssetBank`` 不受影响，但脚本得用同一套规则筛。
    """
    want = DEFAULT_SET if set_name is None else set_name
    files = [p for p in Path(root).glob(f"{state}_*.png")
             if _split(p, state)[0] == want]
    return sorted(files, key=lambda p: _split(p, state)[1])


def default_set_files(root: Path, state: str) -> list[Path]:
    """该状态「默认套」的帧文件 —— ``set_files(root, state)`` 的简写。"""
    return set_files(root, state)


class AssetBank:
    """按状态（以及状态内的套）组织的贴图仓库。"""

    def __init__(self, root: Path):
        self.root = Path(root)
        #: 每个状态的"主套"帧列表（兼容老 API：count/raw/scaled/frame 的默认值）
        self.frames: dict[str, list[QPixmap]] = {s: [] for s in STATES}
        #: 每个状态的全部套：套名 -> 帧列表。键 ``""`` 是无套名的那一套。
        self.sets: dict[str, dict[str, list[QPixmap]]] = {s: {} for s in STATES}
        self.fallback_used: list[str] = []
        self._cache: dict[tuple[str, str | None, int], list[QPixmap]] = {}

    # ------------------------------------------------------------ 加载

    def load(self) -> "AssetBank":
        for state in STATES:
            buckets: dict[str, list[tuple[int, QPixmap]]] = {}
            for path in sorted(self.root.glob(f"{state}_*.png")):
                set_name, idx = _split(path, state)
                pm = QPixmap(str(path))
                if not pm.isNull():
                    buckets.setdefault(set_name, []).append((idx, pm))

            ordered: dict[str, list[QPixmap]] = {}
            for name, items in buckets.items():
                items.sort(key=lambda t: t[0])          # 按帧序排，别信文件系统顺序
                ordered[name] = [pm for _, pm in items]
            self.sets[state] = ordered

            # 主套：优先无套名那一套，否则拿出现的第一套当代表
            if DEFAULT_SET in ordered:
                self.frames[state] = ordered[DEFAULT_SET]
            elif ordered:
                self.frames[state] = ordered[next(iter(ordered))]
            else:
                self.frames[state] = []

        base = self.frames["idle"] or self._scan_any()
        self.frames["idle"] = base
        if not self.sets["idle"]:
            self.sets["idle"] = {DEFAULT_SET: base}
        for state in STATES:
            if not self.frames[state]:
                # 借 idle 兜底：连同"套"一起借，不然多套查询会查到空
                self.frames[state] = base
                self.sets[state] = {DEFAULT_SET: base}
                self.fallback_used.append(state)

        self._cache.clear()
        return self

    def _scan_any(self) -> list[QPixmap]:
        """连 idle 都没有时，把目录里任何 PNG 都拿来用，保证有东西可显示。"""
        out = []
        for path in sorted(self.root.glob("*.png"), key=_frame_index):
            pm = QPixmap(str(path))
            if not pm.isNull():
                out.append(pm)
        return out

    # ------------------------------------------------------------ 查询

    def ok(self) -> bool:
        return bool(self.frames.get("idle"))

    def set_names(self, state: str) -> list[str]:
        """该状态有哪几套素材（按加载顺序）。空列表表示连兜底都没有。"""
        return list(self.sets.get(state, {}).keys())

    def raw(self, state: str, set_name: str | None = None) -> list[QPixmap]:
        if set_name is not None:
            got = self.sets.get(state, {}).get(set_name)
            if got:
                return got
        return self.frames.get(state) or self.frames.get("idle") or []

    def count(self, state: str, set_name: str | None = None) -> int:
        return len(self.raw(state, set_name))

    def scaled(self, state: str, size: int,
               set_name: str | None = None) -> list[QPixmap]:
        """按显示尺寸取整组帧（带缓存）。"""
        size = max(8, int(size))
        key = (state, set_name, size)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        out = [
            pm.scaled(size, size,
                      Qt.AspectRatioMode.KeepAspectRatio,
                      Qt.TransformationMode.SmoothTransformation)
            for pm in self.raw(state, set_name) if not pm.isNull()
        ]
        self._cache[key] = out
        return out

    def frame(self, state: str, index: int, size: int,
              set_name: str | None = None) -> QPixmap | None:
        frames = self.scaled(state, size, set_name)
        if not frames:
            return None
        return frames[index % len(frames)]
