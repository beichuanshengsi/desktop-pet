"""类型检查：把 Pylance 会报的问题在命令行里一次看全。

**为什么要有这个脚本**：编辑器里的诊断只对"打开过的文件"刷新。改完一处
没顺手打开另一个文件，很容易漏 —— ``main.py`` 里曾经把一个游戏窗口标成
``QWidget``，连 ``closed`` 信号就报 ``reportAttributeAccessIssue``，
但只在你打开 ``main.py`` 时才看得见。

底层用 **pyright**：它就是 Pylance 的类型检查引擎，规则完全一致，
只是不需要开编辑器。装法是把它放到托管 node 目录里（不要 `npm i -g`）：

    npm --prefix "$HOME/.workbuddy/binaries/node/workspace" install pyright

用法::

    python tools/typecheck.py                 # 默认查 main.py game pet tools
    python tools/typecheck.py pet/icon.py     # 只查指定文件

找不到 pyright 时**打印安装命令并返回 0**（不算失败）—— 这是可选的
辅助工具，不该让 CI 或"一键全跑"因为它没装就红掉。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: 默认检查范围。**不含 reports/**：那里是随时可删的产物和一次性探针，
#: 掺进来只会让真正的问题淹在噪音里。
DEFAULT_TARGETS = ("main.py", "game", "pet", "tools")

#: pyright 的入口。托管 node 目录是约定位置，也可以用环境变量覆盖
#: （换机器 / 换了安装位置时不用改代码）。
PYRIGHT_INDEX = Path.home() / ".workbuddy/binaries/node/workspace/node_modules/pyright/index.js"
NODE_DIR = Path.home() / ".workbuddy/binaries/node/versions"

INSTALL_HINT = (
    'npm --prefix "{}" install pyright'.format(PYRIGHT_INDEX.parents[2])
)


def find_node() -> str | None:
    """找一个 node 可执行文件：先看 PATH，再翻托管 node 目录。"""
    exe = shutil.which("node")
    if exe:
        return exe
    # 托管目录是 <...>/node/versions/<版本>/node.exe，取版本最高的那个
    for cand in sorted(NODE_DIR.glob("*/node.exe"), reverse=True):
        return str(cand)
    return None


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    targets = args or list(DEFAULT_TARGETS)

    index = Path(os.environ.get("PYRIGHT_INDEX", PYRIGHT_INDEX))
    if not index.exists():
        print(f"[类型检查] 没找到 pyright：{index}")
        print(f"[类型检查] 需要的话这样装：\n    {INSTALL_HINT}")
        print("[类型检查] 跳过（编辑器里的 Pylance 照常工作）")
        return 0

    node = find_node()
    if node is None:
        print("[类型检查] 找到了 pyright 但没找到 node，跳过")
        return 0

    cmd = [node, str(index),
           # 用当前解释器去解析 PySide6 / Pillow 的存根，
           # 否则会拿"默认 Python"去找包，import 全部报成缺失
           "--pythonpath", sys.executable,
           *targets]
    # flush：pyright 是子进程、直接写 fd，不刷的话我们的标题会跑到它后面去
    print("[类型检查] " + " ".join(targets), flush=True)
    proc = subprocess.run(cmd, cwd=str(ROOT), check=False)
    if proc.returncode == 0:
        print("[类型检查] 通过：0 error")
    else:
        print("[类型检查] 有错误，见上面的清单")
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
