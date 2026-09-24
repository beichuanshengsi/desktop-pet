"""路径与素材目录。

从 ``config.py`` 里拆出来，因为它和"配置存档"是两件不同的事：一个是
**东西放哪儿**（本模块），一个是 **用户选了什么**（``Config``）。混在一起时，
想加一类素材得先在一堆存档字段里找到那几个 `xxx_dir()` 函数。

两种根目录必须分开，这是打包后最容易翻车的地方：

* **资源目录**（只读）—— 开发态是项目目录，PyInstaller 打包后是解包临时目录
  ``sys._MEIPASS``。素材永远从这里读。
* **数据目录**（可写）—— 开发态为了方便也放在项目目录，打包后必须挪到
  ``%APPDATA%``，否则写存档会失败（程序目录通常不可写）。

素材目录的统一形状
------------------

每一类素材都有**两个候选位置**，用户目录优先：

    ========  ==========================  ================================
    类别      随程序分发（只读）            用户自定义（可写、优先）
    ========  ==========================  ================================
    pet       ``assets/pet/``             ``<数据目录>/custom_pet/``
    game      ``assets/game/``            ``<数据目录>/game/``
    sfx       ``assets/sfx/``             ——（没有用户覆盖层）
    fonts     ``assets/fonts/``           ——（没有用户覆盖层）
    ========  ==========================  ================================

**加一类新素材只用在下面的 ``ASSET_KINDS`` 里登记一行**，
:func:`asset_dir` / :func:`user_asset_dir` / :func:`resolve_asset_dir` 三个函数
就都认它了 —— 不用再照抄一个 ``xxx_asset_dir()``（以前每加一类素材就得抄一份
"用户目录有 png 就整体接管"的判定，抄三遍就有三处会漏改）。
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


# ---------------------------------------------------------------- 两个根

def app_root() -> Path:
    """只读资源根目录。"""
    if getattr(sys, "frozen", False):           # PyInstaller 冻结态
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    """可写数据根目录（存档、用户自定义素材）。"""
    if getattr(sys, "frozen", False):
        base = Path(os.environ.get("APPDATA") or Path.home()) / "DesktopPet"
    else:
        base = Path(__file__).resolve().parent.parent
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError:
        base = Path.home() / ".desktop-pet"
        base.mkdir(parents=True, exist_ok=True)
    return base


# ---------------------------------------------------------------- 素材类别登记表

@dataclass(frozen=True)
class AssetKind:
    """一类素材的存放规则。

    ``user_dir`` 为空表示这类素材**没有用户覆盖层**（比如音效和字体），
    用户想换就直接改 ``assets/sfx/`` —— 它们本来就随程序走。
    """

    key: str                    #: 目录名，也是 ``asset_dir()`` 的参数
    title: str                  #: 中文说明，报错信息里用
    user_dir: str = ""          #: 数据目录下的子目录名；空 = 没有用户层
    marker: str = "*.png"       #: 判定"用户目录接管了没有"的通配符


#: 登记表 —— **加一类素材就在这里加一行**。
ASSET_KINDS: tuple[AssetKind, ...] = (
    AssetKind("pet", "宠物贴图", user_dir="custom_pet"),
    AssetKind("game", "小游戏素材", user_dir="game"),
    AssetKind("sfx", "音效"),
    AssetKind("fonts", "字体"),
)

KINDS: dict[str, AssetKind] = {k.key: k for k in ASSET_KINDS}


def kind(key: str) -> AssetKind:
    """取登记信息。没登记的类别当作"只有内置目录"处理，不报错。"""
    return KINDS.get(key, AssetKind(key, key))


# ---------------------------------------------------------------- 素材目录

def asset_dir(name: str | None = None) -> Path:
    """随程序分发的素材目录（只读）。不传 ``name`` 就是 ``assets/`` 本身。"""
    base = app_root() / "assets"
    return base if name is None else base / name


def user_asset_dir(name: str) -> Path | None:
    """用户自定义素材目录（可写）。这类素材没有用户层时返回 ``None``。"""
    sub = kind(name).user_dir
    return data_dir() / sub if sub else None


def resolve_asset_dir(name: str) -> Path:
    """程序实际该读哪个目录：**用户目录里有素材就整体接管**，否则用内置的。

    注意是"接管"不是"合并"：用户目录里只要有一个匹配文件，内置目录就整个不读。
    好处是换素材时不会出现"一半新一半旧"，代价是缺哪个状态就得自己补齐
    （缺的状态按 ``AssetBank`` 的规则借 idle 兜底，不会崩）。
    """
    k = kind(name)
    custom = user_asset_dir(name)
    if custom is not None and custom.is_dir() and any(custom.glob(k.marker)):
        return custom
    return asset_dir(name)


def pet_asset_dir() -> Path:
    """宠物贴图目录 —— 运行时会读的那一个。"""
    return resolve_asset_dir("pet")


def game_asset_dir() -> Path:
    """小游戏素材目录。

    「有一个 png 就整体接管」这条规则和宠物贴图一样，但**后果轻得多**：
    小游戏读的是 ``catcher_*.png`` / ``puppy_a_*.png`` 这类**独立前缀**，
    缺哪一套就只让那一套退回代码画的占位形象（炸弹现在就是占位），互不影响。
    """
    return resolve_asset_dir("game")


def config_path() -> Path:
    return data_dir() / "config.json"
