"""测试脚本的存档隔离 —— **凡是会造 ``Config()`` 或 ``PetWindow()`` 的脚本，
第一件事就调 ``isolate_storage()``**。

为什么需要它
------------

开发态的"可写数据目录"就是**项目根**（见 ``pet/paths.py``），玩家的真存档
``config.json`` 也在那儿。而 ``PetWindow`` 一造出来就挂了个 **3 秒一次**的
自动落盘定时器，验证脚本只要跑够 3 秒，或者收尾调了 ``close()``，
玩家那份存档就被当场覆盖。

真实事故（v2.3.0）：``verify_album_ui.py`` 造了真窗口、抽了 40 张卡、
装了 5 张装备，还为了测"老档 5 槽"把 ``launched_at`` 改成 120 天前 ——
这些**全写进了玩家的存档**。玩家下次打开桌宠，发现自己什么都没干，
卡册里已经躺着 40 张卡、装备栏还是满的，金币也被改成了测试用的数字。

这个坑以前踩过（``verify_desktop.py`` 冲掉过一次，于是有了"跑完对一遍、
变了就还原"的土办法），但那种办法**只在脚本正常跑完时有效**：中途抛异常、
被 Ctrl-C，还原那段就执行不到。所以这里改成从**根上换掉整个数据目录**。

怎么用
------

    from _isolate import isolate_storage          # 放在所有 pet.* 导入之前

    STORAGE = isolate_storage("album_ui")         # 存档/用户素材全落到临时目录

之后再 ``Config()`` / ``PetWindow(...)`` 就只会动临时目录里的文件，
跑完自动删掉（进程退出时）。真存档一个字节都不会碰。

``tools/check_save_isolation.py`` 会静态检查有没有脚本忘了调它。
"""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from pathlib import Path


def isolate_storage(tag: str = "pet") -> Path:
    """把可写数据目录指到一个临时目录，返回该目录。

    ``tag`` 只用来给临时目录起个能认出来的名字（``album_ui_xxxx``），
    方便跑测试时出问题时一眼看出是谁留下的。

    **必须在造 ``Config`` / ``PetWindow`` 之前调用。** 它改的是环境变量
    ``DESKTOP_PET_DATA_DIR``（见 ``pet/paths.py``），也就是"东西放哪儿"这件事
    的唯一开关 —— 没有别的地方需要打补丁。
    """
    from pet.paths import DESKTOP_PET_DATA_DIR_ENV

    tmp = Path(tempfile.mkdtemp(prefix=f"pet_{tag}_"))
    os.environ[DESKTOP_PET_DATA_DIR_ENV] = str(tmp)
    atexit.register(shutil.rmtree, tmp, ignore_errors=True)
    return tmp


def assert_isolated() -> Path:
    """复核一次：可写数据目录确实**不是**项目根。返回值就是该项目录。

    防的是"以为隔离了、其实变量名写错"这类哑火 —— 那种情况下脚本照样跑，
    照样静默吃掉玩家存档，只是没人在意。真出问题就当场炸掉，好过事后翻存档。
    """
    from pet.paths import app_root, data_dir

    here = data_dir().resolve()
    if here == app_root().resolve():
        raise RuntimeError(
            "存档没隔离！data_dir() 仍然指向项目根，跑下去会覆盖玩家的 config.json。"
            "先在造 Config/PetWindow 之前调用 _isolate.isolate_storage()。"
        )
    return here
