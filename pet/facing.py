"""贴图朝向元数据 —— 专门治"倒着走"。

程序只知道**往哪走**（``Brain.facing``），却不知道**素材画的是哪一边**。
这两件事一旦对不上，狗就会背对着前进方向滑走，而且从代码上完全看不出
问题——当年就是这么踩的坑。

所以"原图朝哪边"不能写死在绘制代码里，而是当作素材自带的属性，和贴图
放在一起（``<素材目录>/facing.json``）::

    {"base": "left", "note": "线条小狗素材，脸在左、后腿在右"}

绘制时统一走 :func:`should_mirror`：只有**行走方向与素材朝向不一致**时
才水平翻转。换一套朝向相反的素材，改这一个 json 就行，不用动代码。

一个状态可以有**好几套**素材（``walk_00`` / ``walk_a_00`` …），而它们是
分开下载、分开抠图的，**原图方向不一定一致**。所以 ``base`` 之外还允许按套
单独声明，覆盖目录默认值::

    {"base": "left", "sets": {"walk_a": "right"}}

``sets`` 的 key 是**素材前缀**（``walk_a``），跟 ``walk_a_00.png`` 对得上；
没单独声明的套一律跟随 ``base``，一套都不用改。
判断"某一套到底朝哪边"只能靠眼睛看（见 ``tools/verify_facing.py``）。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

LEFT = -1
RIGHT = 1

# 人类可能写进来的各种说法，都认
_WORDS: dict[str, int] = {
    "left": LEFT, "l": LEFT, "左": LEFT, "-1": LEFT,
    "right": RIGHT, "r": RIGHT, "右": RIGHT, "1": RIGHT,
}

# 内置素材（代码画的线条狗）本来就是朝右画的，缺省按朝右算，
# 这样没有 facing.json 的老存档行为完全不变。
DEFAULT = "right"

# 按套覆盖用哪个 key。套名就用素材文件名里的那一段（``walk_a`` 的 ``a``）。
SETS_KEY = "sets"


def meta_path(pet_dir: str | Path) -> Path:
    return Path(pet_dir) / "facing.json"


def normalize(word) -> int | None:
    """把各种写法归一成 -1 / 1，认不出来返回 None。"""
    if isinstance(word, bool):
        return None
    if isinstance(word, int):
        return LEFT if word < 0 else RIGHT
    if isinstance(word, str):
        return _WORDS.get(word.strip().lower())
    return None


def _load(pet_dir: str | Path) -> dict:
    """把声明文件读成 dict。缺文件、写坏了、写成了裸字符串，都在这里抹平。"""
    try:
        raw = json.loads(meta_path(pet_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {"base": raw}


def read(pet_dir: str | Path) -> int:
    """读素材目录里的**默认**朝向。缺文件、写坏了、值不合法，一律回退默认。"""
    raw = _load(pet_dir)
    word = raw.get("base", raw.get("face", raw.get("facing")))
    return normalize(word) or _WORDS[DEFAULT]


def read_sets(pet_dir: str | Path) -> dict[str, int]:
    """读"按套覆盖"表。没写、写坏了、里面混了非法值，都只是少几条覆盖。"""
    raw = _load(pet_dir).get(SETS_KEY)
    if not isinstance(raw, dict):
        return {}

    out: dict[str, int] = {}
    for key, word in raw.items():
        value = normalize(word)
        if value is not None:
            out[str(key)] = value
    return out


def prefix(state: str, set_name: str | None) -> str:
    """素材前缀 —— 和文件名对得上：默认套是 ``walk``，分套是 ``walk_a``。

    按套覆盖就用这个当前缀当 key（而不是裸的 ``a``）：``a`` 这种套名在
    ``poke_a`` / ``feed_a`` / ``walk_a`` 里是重名的，裸套名一定会互相串。
    """
    return state if not set_name else f"{state}_{set_name}"


def base_for(base: int, sets: Mapping[str, int], state: str,
             set_name: str | None = None) -> int:
    """某一套素材实际按哪边算。

    没单独声明的套跟随目录默认，所以只有方向相反的套需要写进 ``sets``。
    """
    return sets.get(prefix(state, set_name), base)


def _existing_note(path: Path) -> str:
    """写回时别把原有的说明吃掉。"""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    note = raw.get("note", "") if isinstance(raw, dict) else ""
    return note if isinstance(note, str) else ""


def _word(value: int) -> str:
    return "left" if value == LEFT else "right"


def write(pet_dir: str | Path, word, *, note: str = "",
          sets: Mapping[str, object] | None = None) -> Path:
    """写朝向声明。返回文件路径。

    * ``note`` 留空则保留文件里原有的说明。
    * ``sets`` 是"按套覆盖"表：**不传**就原样保留文件里已有的（免得只想改总
      朝向，却把某套的单独声明顺手抹掉）；传了（哪怕是空 dict）就以传入的为准。
      值可以是 ``"left"`` / ``-1`` 这些写法，认不出的会被丢掉。
    """
    value = normalize(word)
    if value is None:
        raise ValueError(f"朝向只能是 left / right，收到 {word!r}")

    path = meta_path(pet_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    note = note or _existing_note(path)

    payload: dict[str, object] = {"base": _word(value)}
    if sets is None:
        keep = _load(pet_dir).get(SETS_KEY)
        if isinstance(keep, dict) and keep:
            payload[SETS_KEY] = keep
    else:
        clean: dict[str, str] = {}
        for name, raw_value in sets.items():
            one = normalize(raw_value)
            if one is not None:
                clean[str(name)] = _word(one)
        if clean:
            payload[SETS_KEY] = clean
    if note:
        payload["note"] = note

    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    tmp.replace(path)
    return path


def current() -> int:
    """当前正在显示的这套贴图朝哪边。"""
    from .paths import pet_asset_dir

    return read(pet_asset_dir())


def current_sets() -> dict[str, int]:
    """当前生效目录的"按套覆盖"表（没有就是空 dict）。"""
    from .paths import pet_asset_dir

    return read_sets(pet_asset_dir())


def should_mirror(facing: int, base: int | None = None) -> bool:
    """行走方向 ``facing`` 要不要水平翻转。

    素材朝右、往右走 -> 不翻；素材朝左、往右走 -> 翻。
    ``base`` 省略时现场读一次（绘制循环里请自己缓存，别每帧读盘）。
    """
    return int(facing) != (current() if base is None else int(base))
