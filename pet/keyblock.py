"""幼儿模式·严格档用的低级键盘钩子（Windows 专用）。

**为什么需要它**：全屏遮罩只能拦住鼠标。``Win`` / ``Alt+Tab`` / ``Alt+F4`` /
``Ctrl+Esc`` 是系统级的切换手势、走的是键盘，遮罩根本碰不到 —— 小朋友按一下就
出去了。要拦住它们只有一条路：``SetWindowsHookEx(WH_KEYBOARD_LL)``。系统会在
**任何一个按键送到目标窗口之前**先把这次按键交给我们的回调，返回非 0 就是"吃掉"。

**同一个 API 也正是键盘记录器在用的**，所以这个模块有两条自我约束，改它之前先读：

1. **只拦不记**。拦截名单写死在下面的 ``ALWAYS_BLOCKED`` / ``CHORD_BLOCKED``，
   回调里只做"查表 + 返回"，一个字节都不落盘、不出网。这也是杀软可能对打包后的
   exe 报启发式警告的原因（本项目不接受这个 API 的"记录"用法）。
2. **回调里绝不能慢**。它跑在系统的输入链路上：慢一帧就是全系统键盘顿一下。
   所以这里不 import Qt、不做任何 IO。

**这个模块不认识 Qt，也不认识 Config** —— 它只回答"哪些键该吃掉"。
因此那条规则可以脱离 Windows 直接跑测试（见 ``should_block``），
而"怎么装钩子、装不上怎么办"留给 ``pet/kids.py``。
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Any

# ---------------------------------------------------------------- 虚拟键码
VK_TAB = 0x09
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12            # 就是 Alt
VK_ESCAPE = 0x1B
VK_SPACE = 0x20
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_APPS = 0x5D            # 菜单键（键盘右边那个"右键"）
VK_F4 = 0x73

#: 无论有没有配修饰键，一律吃掉。这三个键自己就能弹开始菜单 / 菜单栏，
#: 单独按就已经能"切走"，没有放行的理由。
ALWAYS_BLOCKED = frozenset({VK_LWIN, VK_RWIN, VK_APPS})

#: 只有**按住某个修饰键**时才有"切走 / 关掉"含义的键。
#: 它们不能进 ``ALWAYS_BLOCKED``：单独按 Tab / Esc / F4 是正常打字或操作，
#: 一律吃掉会把小游戏和密码键盘搞得没法用。
#: 元素是 ``(键, 修饰键名元组)``，元组里**任一**按住就吃。
CHORD_BLOCKED: tuple[tuple[int, tuple[str, ...]], ...] = (
    (VK_TAB, ("alt",)),         # Alt+Tab   切窗口
    (VK_ESCAPE, ("alt",)),      # Alt+Esc   直接切到下一个窗口
    (VK_ESCAPE, ("ctrl",)),     # Ctrl+Esc 开始菜单；Ctrl+Shift+Esc 任务管理器
    (VK_F4, ("alt",)),          # Alt+F4    关窗口
    (VK_SPACE, ("alt",)),       # Alt+Space 系统菜单（里面有"关闭"）
)


def should_block(vk: int, *, alt: bool = False, ctrl: bool = False,
                 shift: bool = False) -> bool:
    """这个键该不该吃掉。

    **纯函数、不碰 Windows** —— 钩子里真正跑的就是它。整个模块只有这一处
    有判断逻辑，所以"锁得住哪些键"这件事能脱机验（见 ``tools/smoke_test.py``）。
    """
    if vk in ALWAYS_BLOCKED:
        return True
    down = {"alt": alt, "ctrl": ctrl, "shift": shift}
    for key, mods in CHORD_BLOCKED:
        if vk == key and any(down[m] for m in mods):
            return True
    return False


# ---------------------------------------------------------------- 钩子本体

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104


class KBDLLHOOKSTRUCT(ctypes.Structure):
    """``WH_KEYBOARD_LL`` 回调拿到的结构。**字段顺序不能改**，改了就是读错内存。"""

    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


try:
    #: 回调的函数类型。``c_ssize_t`` 对应 Windows 的 ``LRESULT``（64 位上 8 字节）
    #: —— 写成 ``c_int`` 在 64 位下返回值会被截断，钩子会时灵时不灵。
    _HOOKPROC = ctypes.WINFUNCTYPE(
        ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
except AttributeError:              # 非 Windows：让 import 不炸，但永远装不上
    _HOOKPROC = None


class KeyBlocker:
    """低级键盘钩子的生命周期。**同一个进程只该有一个实例。**

    用法::

        b = KeyBlocker()
        if b.install():          # 返回 False 时必须拒绝进入严格档
            ...
            b.uninstall()        # 退出幼儿模式时一定要解掉

    为什么"装不上就拒绝"而不是"凑合进"：用户要的是"锁住"，而装不上的表现
    是**一切照旧、什么也没锁**，他自己看不出来 —— 那种"以为锁了其实没锁"的
    状态比直接不开这个功能危险得多。
    """

    def __init__(self) -> None:
        self._hook: int | None = None
        # 这两个是 ctypes 侧的句柄与回调，类型全在运行期由 ctypes 自己管，
        # 静态检查给不出有意义的名字 —— 标 ``Any`` 比到处写 ``# type: ignore``
        # 诚实（也不能更糟：反正它们只在 Windows 上有值）。
        self._proc: Any = None
        self._user32: Any = None
        #: 累计吃掉的按键数。**只用于自检和日志**，不上报、不落盘。
        self.blocked = 0

    # ------------------------------------------------------------ 状态

    @property
    def active(self) -> bool:
        return self._hook is not None

    # ------------------------------------------------------------ 装 / 卸

    def install(self) -> bool:
        """装上钩子。成功返回 ``True``；非 Windows / 被系统拒绝都返回 ``False``。"""
        if self._hook is not None:
            return True
        if sys.platform != "win32" or _HOOKPROC is None:
            return False

        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        except OSError:
            return False

        # 参数类型必须逐个写清楚：不写的话 ctypes 默认按 c_int 传，
        # 64 位下句柄会被截断成 32 位，``UnhookWindowsHookEx`` 会静默失败
        # —— 症状是"退出幼儿模式之后 Win 键还是坏的"。
        user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
        user32.GetAsyncKeyState.restype = ctypes.c_short
        user32.CallNextHookEx.argtypes = (wintypes.HHOOK, ctypes.c_int,
                                          wintypes.WPARAM, wintypes.LPARAM)
        user32.CallNextHookEx.restype = ctypes.c_ssize_t
        user32.SetWindowsHookExW.argtypes = (ctypes.c_int, _HOOKPROC,
                                             wintypes.HINSTANCE, wintypes.DWORD)
        user32.SetWindowsHookExW.restype = wintypes.HHOOK
        user32.UnhookWindowsHookEx.argtypes = (wintypes.HHOOK,)
        user32.UnhookWindowsHookEx.restype = wintypes.BOOL
        kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE

        self._user32 = user32
        # 回调对象必须留一份强引用：交给系统之后本地就没人持有了，
        # 被 GC 掉的话下一次按键会直接踩到已回收的内存（进程崩掉）。
        self._proc = _HOOKPROC(self._callback)
        hmod = kernel32.GetModuleHandleW(None)
        hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, hmod, 0)
        if not hook:
            self._proc = None
            self._user32 = None
            return False
        self._hook = hook
        self.blocked = 0
        return True

    def uninstall(self) -> None:
        """卸掉钩子。没装过、或已经卸过，都安静返回（退出路径上不该再抛异常）。"""
        if self._hook is None:
            return
        hook, self._hook = self._hook, None
        try:
            if self._user32 is not None:
                self._user32.UnhookWindowsHookEx(hook)
        except (OSError, AttributeError):
            pass            # 系统已经在收了：不该因为卸不掉就中断退出流程
        self._proc = None
        self._user32 = None

    # ------------------------------------------------------------ 回调

    def _down(self, vk: int) -> bool:
        """这个修饰键此刻是不是按下的。"""
        if self._user32 is None:
            return False
        try:
            return bool(self._user32.GetAsyncKeyState(vk) & 0x8000)
        except (OSError, AttributeError):
            return False

    def _callback(self, n_code: int, w_param: int, l_param: int) -> int:
        """系统在每次按键到达目标窗口之前调它。返回非 0 = 吃掉这个键。

        只处理"按下"，不管"抬起"：抬起事件放行不会让功能逃出去，而拦抬起会
        让某些程序的状态机错乱（它们以为键还按着）。这也是各路 kiosk 工具的
        通行做法。
        """
        if n_code == 0 and w_param in (WM_KEYDOWN, WM_SYSKEYDOWN):
            kb = ctypes.cast(ctypes.c_void_p(l_param),
                             ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            if should_block(int(kb.vkCode), alt=self._down(VK_MENU),
                            ctrl=self._down(VK_CONTROL), shift=self._down(VK_SHIFT)):
                self.blocked += 1
                return 1
        if self._user32 is None:
            return 0
        return int(self._user32.CallNextHookEx(None, n_code, w_param, l_param))
