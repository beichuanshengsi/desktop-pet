"""音效播放：一个事件表 + 一个播放器，全程序共用这一份。

为什么要有独立的一层
--------------------
调用方散在窗口层（戳/喂/落地/弹跳）、卡册（抽卡/分解/装备）、四款小游戏里，
一共二十来个点。如果每处各自 ``Sound(); set_volume(); play()``，会出现
三件必然的坏事：

1. **同一个事件被抄成好几份路径**，改文件名或换素材时漏改一处，症状是
   "这个场景没声音"——不报错，只是安静，最难发现；
2. **每个调用点都得自己判断"有没有这个文件"**，漏一处就是启动时一堆
   找不到文件的告警；
3. **音量与总开关无处安放**，只能每个点各查一次存档。

所以这一层的存在理由跟 ``uitheme`` 的字体回退链、``game.common`` 的汇率
是同一个：**只准有一份**。

事件表是唯一来源
----------------
``EVENTS`` 就是"这程序会出哪些声"的完整清单，``key`` 同时是文件名
（``assets/sfx/<key>.wav``）。加一个声音只需要：

1. 往 ``EVENTS`` 加一行；
2. 把音频按 ``<key>.wav`` 丢进 ``assets/sfx/``。

**没有第 3 步**——调用方拿 ``sfx.play("poke")`` 说话，不认识路径也不认识
音量。素材缺席时 ``play()`` 静默跳过（只是没声，不是报错），这样"音效"
这部分完全可以后补，不影响程序先跑起来。

播放后端为什么是 pygame
----------------------
试过三种，只有第三种能用：

1. **``QSoundEffect``**（Qt 自带）：延迟明显、为"连着响不互相掐"要养
   四十多个对象把 30fps 主循环拖住，而且**长时间高频播放后会静默卡死**，
   没有接口能救回来。已淘汰。
2. **``winsound.PlaySound``**（v2.8.1）：在声卡直连的机器上没问题，
   ``play()`` 只要 0.13ms。但它**每响一次都要开关一次音频设备**，
   这在蓝牙耳机上是灾难——A2DP 链路一空闲就断，重新唤醒要 0.3~1.5 秒。
   实测同一段 0.14 秒的素材（本机默认输出是蓝牙耳机）：

   | 后端 | 播一次实际耗时 |
   |---|---|
   | ``winsound`` | 1.48s / 0.51s / 0.53s |
   | ``pygame``（设备常开） | 0.137s / 0.139s / 0.141s |

   多出来的那 0.4~1.4 秒全是设备开关的成本，听感就是
   **"戳它一下，过一秒才响"**；而且这段延迟会让"戳"的声音晚到，
   人正在挪鼠标时就以为是"鼠标划过它也响"。
3. **``pygame.mixer``**（当前）：启动时开一次设备，之后**一直开着**
   （见 ``_hold_link``），于是每次播放只剩素材本身的长度。
   顺带还解决三件事：

   * **音量变成原生接口**（``Sound.set_volume``）—— v2.8.1 为了给
     ``PlaySound`` 补音量，要把素材按音量缩一份写进系统临时目录，
     那一整套（``_write_scaled`` / 缓存目录 / 指纹清理）现在全删了；
   * **可以同时响**（多路混音），于是"抽卡大音开播后一秒内别的音让路"
     那条规则也删了 —— 它挡掉的是用户真的按下去的反馈，比"叠着响"更糟；
   * 跨平台（不再只有 Windows 能出声）。

为什么开着"音效"就占着音频设备
----------------------------
"设备常开"是低延迟的**前提**，不是副作用：蓝牙链路一旦断，重新握手就要
一秒。所以只要音效是开着的，播放器就一直喂一路静音循环
（``_hold_link``）把链路按住。

代价是蓝牙耳机在你不用它的时候也在收数据（费电）。所以设了
``IDLE_RELEASE``：**连续这么久没响过就把设备还回去**，下一次要响时再开。
空闲后第一声仍然要等一次握手（跟换后端之前一样，不会更差），
但只要在用它（戳、玩小游戏、抽卡），链路一直是热的。

事件级增益
----------
``Sfx.gain`` 是这个事件**相对用户音量**的倍率，落地即生效。
用它而不是"再烘一个更轻的文件"：**"弹跳比落地轻"是这个事件的性质，
不是素材的性质** —— 换素材时不该把这个关系丢掉。
目前只有 ``land_soft``（着地后弹起的那一下）用它，见 ``EVENTS``。
"""

from __future__ import annotations

import contextlib
import os
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from . import paths

#: 必须在 ``import pygame`` **之前** 设：pygame 导入时会往 stdout 印一句
#: 欢迎语，而桌宠是用 ``pythonw`` 起的（没有控制台），那句印不出来还可能出错。
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

try:                                   # 装不上就整套降级为静默，不影响桌宠运行
    import pygame
except Exception:                      # noqa: BLE001
    pygame = None                      # type: ignore[assignment]


# ---------------------------------------------------------------- 事件表

@dataclass(frozen=True)
class Sfx:
    """一个音效事件。

    ``key`` 有两个身份：**调用方嘴里的事件名**，和**磁盘上的文件名**
    （``assets/sfx/<key>.wav``）。合成一个字段是有意的——分成 ``key`` /
    ``file`` 两个字段后，就必然出现"事件叫 poke、文件叫 click_001"这种
    对不上号的情况，而查起来得两头跑。

    ``gain`` 是相对用户音量的倍率，见模块开头的"事件级增益"。
    """

    key: str
    title: str
    about: str
    gain: float = 1.0


#: 全部事件。**加声音只改这里**。
EVENTS: tuple[Sfx, ...] = (
    # 抽卡按稀有度分四档：翻牌那一下是整套收集系统里唯一"当场看得出稀有感"
    # 的反馈，而图鉴格子的配色是静态的。四档的声音必须**一路听得出递进**，
    # 否则"又抽到普通"和"出传说了"在听觉上是一回事。
    Sfx("pull_normal", "抽卡·普通", "抽到普通卡"),
    Sfx("pull_rare", "抽卡·稀有", "抽到稀有卡"),
    Sfx("pull_epic", "抽卡·史诗", "抽到史诗卡"),
    Sfx("pull_legend", "抽卡·传说", "抽到传说卡"),
    # 互动
    Sfx("poke", "戳一戳", "单击桌宠"),
    Sfx("feed", "投喂", "喂一口 / 吃食物道具"),
    Sfx("land", "落地", "从空中掉下来着地"),
    # 着地之后弹起来的那一下。**天生比落地轻**（gain 0.6）：被甩出去的狗
    # 会连弹两三次，每次都跟落地一样响就成了砸桌子。0.6 换算过来约 -4dB，
    # 听得出"这是余波"而不是"又摔了一次"。
    Sfx("land_soft", "落地弹跳", "着地后弹起的那一下", gain=0.6),
    Sfx("coin", "金币", "金币入账"),
    Sfx("sleep", "睡着", "叫它去睡"),
    # 小卖部 / 背包
    Sfx("buy", "购买", "小卖部买下一件"),
    Sfx("use_item", "用道具", "背包里用掉一件"),
    # 卡册
    Sfx("open_album", "打开卡册", "翻开卡册面板"),
    Sfx("flip", "翻页", "卡册翻页"),
    Sfx("dissolve", "分解", "重复卡分解成碎片"),
    Sfx("equip", "装备", "装备 / 卸下一张卡"),
    # 小游戏
    Sfx("score", "得分", "小游戏得分 / 接住东西"),
    Sfx("break", "撞击", "小游戏撞上 / 挨炸"),
    Sfx("levelup", "过关", "一局打完，有得分"),
    Sfx("game_over", "游戏结束", "一局打完，颗粒无收"),
    # 作息 / 界面
    Sfx("pomodoro", "番茄钟", "专注计时结束"),
    Sfx("toggle", "开关", "右键菜单里切换开关"),
)

#: ``key -> Sfx``。菜单、验收脚本、文档都从这儿查，不再各自遍历。
BY_KEY: dict[str, Sfx] = {e.key: e for e in EVENTS}

#: 卡册的稀有度 -> 抽卡事件。键与 ``pet/cards.py`` 的 ``TIERS`` 一致。
#: **写成表而不是几个 if**：以后加一档稀有度，漏掉这里会静默落到普通档，
#: 而"传说抽出来却是普通音"这种错，得对着声音才听得出来。
TIER_EVENT: dict[str, str] = {
    "普通": "pull_normal",
    "稀有": "pull_rare",
    "史诗": "pull_epic",
    "传说": "pull_legend",
}


def event_for_tier(tier: str) -> str:
    """稀有度 -> 抽卡事件名。认不出来的一律当普通（不报错）。"""
    return TIER_EVENT.get(tier, "pull_normal")


# ---------------------------------------------------------------- 素材位置

def dir_path() -> Path:
    """音效目录（``assets/sfx/``）。

    音效**没有用户覆盖层**（见 ``pet/paths.py`` 的 ``AssetKind``）：
    它随程序走，用户想换就直接改这个目录——不像贴图那样有
    "自定义优先"的问题，因为没人会想给音效做第二套目录。
    """
    return paths.asset_dir("sfx")


def file_for(key: str) -> Path:
    return dir_path() / f"{key}.wav"


def installed() -> tuple[str, ...]:
    """已经有素材文件的事件。"""
    return tuple(e.key for e in EVENTS if file_for(e.key).is_file())


def missing() -> tuple[str, ...]:
    """还缺素材的事件。**启动时不必为空**：缺就是没声，不是错误。"""
    return tuple(e.key for e in EVENTS if not file_for(e.key).is_file())


# ---------------------------------------------------------------- 播放参数

#: 混音参数。采样率取素材的 44100（省一次重采样）；``buffer`` 是**每次回调
#: 交给系统的采样数**，1024 ≈ 23ms —— 再小（512 ≈ 11ms）在蓝牙上容易断音，
#: 而蓝牙本身的传输延迟就有 150ms 上下，把这里压到 11ms 换不来任何体感，
#: 只是拿爆音的风险赌一把。
_FREQ = 44100
_BUFFER = 1024

#: 通道数。0 号被"常开链路"的静音循环占着，其余给真正的音效。
#: 8 路足够：同时响三个以上的场合只有小游戏连吃道具。
_CHANNELS = 8
_KEEPALIVE_CHANNEL = 0

#: 连续这么久没响过就把音频设备还回去（见模块开头"为什么占着音频设备"）。
IDLE_RELEASE = 180.0

#: 设备开不起来（没有声卡 / 被独占）时，隔这么久才再试一次。
#: 不加这个的话，每帧落地判定都会去尝试 init 一次，白烧 CPU。
RETRY_AFTER = 10.0


def _clamp(value: float) -> float:
    return 0.0 if value < 0.0 else (1.0 if value > 1.0 else value)


# ---------------------------------------------------------------- 播放器

class _Engine:
    """真正的播放器。**全程序一个实例**，只经模块级 ``play()`` 使用。

    不导出这个类：一旦允许 ``_Engine()``，就会有人为了"暂停这个面板的声音"
    造出第二个，于是音量开关只管住一半的声音——正是要避免的病。
    """

    #: 同一个事件在这个间隔内重复触发只响一次。
    #:
    #: 小游戏里"一次消掉几块"是**同一帧**连着调好几次 ``play`` 的，
    #: 不挡的话那几下会叠在一起，听感是糊成一团、还白费一路通道。
    #: 90 ms 是听感上"两声"的最小间隔——再密就并成一声了。
    THROTTLE = 0.09

    def __init__(self) -> None:
        self.enabled = True
        self.volume = 0.7
        self._last: dict[str, float] = {}
        self._sounds: dict[str, object] = {}
        self._ready = False
        self._failed_at = -1e9
        self._last_play = 0.0
        self._silence: object | None = None

    # ------------------------------------------------------------ 设置

    def configure(self, enabled: bool, volume: float) -> None:
        """套用存档里的开关与音量。

        音量只是**记下来**：真正生效是在每次 ``play`` 前
        ``Sound.set_volume``（原生接口，零成本），所以这里不卡。
        """
        self.enabled = bool(enabled)
        self.volume = _clamp(float(volume))
        if not self.enabled:
            self._release()

    def stop(self) -> None:
        """掐掉正在响的。退出程序 / 进幼儿模式时用。

        **链路保持**：``mixer.stop()`` 会把常开的那一路也停掉，所以这里
        要重新按一次——"停声"之后用户多半还要用，不该让他再等一次握手。
        """
        if not self._ready:
            return
        with contextlib.suppress(Exception):
            pygame.mixer.stop()                # type: ignore[union-attr]
            self._hold_link()

    def close(self) -> None:
        """真放手（退出程序）。与 ``stop`` 的区别是连设备一起还回去。"""
        self._release()

    # ------------------------------------------------------------ 播放

    def play(self, key: str) -> None:
        if not self.enabled:
            return
        event = BY_KEY.get(key)
        if event is None:
            return

        now = time.perf_counter()
        last = self._last.get(key)
        if last is not None and now - last < self.THROTTLE:
            return                                   # 同一帧里的连发，只算一次

        sound = self._sound_for(key)
        if sound is None:
            return

        self._last[key] = now
        self._last_play = now
        with contextlib.suppress(Exception):
            sound.set_volume(_clamp(self.volume * event.gain))   # type: ignore[attr-defined]
            sound.play()                                          # type: ignore[attr-defined]

    def tick(self) -> None:
        """主循环每帧调一次：空闲够久就把音频设备还回去。

        不用定时器：主循环本来就在跑（30fps），这里的开销只是一次浮点比较。
        """
        if not self._ready or self._silence is None:
            return
        if time.perf_counter() - self._last_play < IDLE_RELEASE:
            return
        self._release()

    def warmup(self, keys: Iterable[str] | None = None) -> int:
        """把素材读进内存、并把音频设备开起来。返回备好的事件数。

        不做也能跑（第一次响时现读），提前做的意义主要在**开设备**：
        ``mixer.init`` 要 300ms 上下，放在启动时没人察觉，放在
        "戳下去的那一下"就是一个明显的卡顿。
        """
        wanted = [e.key for e in EVENTS] if keys is None else list(keys)
        return sum(1 for k in wanted if self._sound_for(k) is not None)

    # ------------------------------------------------------------ 内部

    def _open(self) -> bool:
        """把音频设备开起来。开不了就返回 False（静默，不抛异常）。"""
        if self._ready:
            return True
        if pygame is None:
            return False
        now = time.perf_counter()
        if now - self._failed_at < RETRY_AFTER:
            return False                            # 刚失败过，别每帧再试
        try:
            pygame.mixer.init(frequency=_FREQ, size=-16, channels=2,
                              buffer=_BUFFER)
            pygame.mixer.set_num_channels(_CHANNELS)
        except Exception:                           # noqa: BLE001
            self._failed_at = now
            return False
        self._ready = True
        self._last_play = now
        self._hold_link()
        return True

    def _hold_link(self) -> None:
        """喂一路循环静音，把音频设备（以及蓝牙链路）按住。

        这是低延迟的来源，见模块开头。静音是**现造的**，不落盘 ——
        一个 1 秒的空白 WAV 而已，没必要为它多一个素材文件。
        """
        if not self._ready:
            return
        with contextlib.suppress(Exception):
            if self._silence is None:
                # 1 秒 × 44100 × 双声道 × 2 字节
                self._silence = pygame.mixer.Sound(buffer=bytes(_FREQ * 4))  # type: ignore[union-attr]
            self._silence.set_volume(0.0)                              # type: ignore[attr-defined]
            channel = pygame.mixer.Channel(_KEEPALIVE_CHANNEL)         # type: ignore[union-attr]
            channel.play(self._silence, loops=-1)                      # type: ignore[arg-type]
            channel.set_volume(0.0)

    def _release(self) -> None:
        """把设备还回去。**必须清掉已读的 Sound**：``mixer.quit()`` 之后
        那些对象就失效了，留着下次播会静默失败（症状又是"没声音"）。
        """
        if not self._ready:
            return
        self._ready = False
        self._silence = None
        self._sounds.clear()
        with contextlib.suppress(Exception):
            pygame.mixer.quit()                    # type: ignore[union-attr]

    def _sound_for(self, key: str) -> object | None:
        """这个事件的发声对象，第一次用到才读盘。读不到返回 ``None``。"""
        cached = self._sounds.get(key)
        if cached is not None:
            return cached
        if not self._open():
            return None
        path = file_for(key)
        if not path.is_file():
            return None
        try:
            sound = pygame.mixer.Sound(str(path))  # type: ignore[union-attr]
        except Exception:                          # noqa: BLE001 —— 坏文件别炸
            return None
        self._sounds[key] = sound
        return sound

    # ------------------------------------------------------------ 查询

    def is_live(self) -> bool:
        """音频设备当前是不是开着（验收脚本用）。"""
        return self._ready


_ENGINE = _Engine()


# ---------------------------------------------------------------- 对外接口

def play(key: str) -> None:
    """按事件名响一下。**未知事件名、素材缺席、开关关着都只是不响**，
    一律不抛异常——音效是锦上添花，不该有能力让桌宠出问题。"""
    _ENGINE.play(key)


def play_for_tier(tier: str) -> None:
    """抽卡专用：按稀有度挑一档响。"""
    play(event_for_tier(tier))


def configure(enabled: bool, volume: float) -> None:
    """从存档套用设置。``PetWindow`` 启动时与开关变动时各调一次。"""
    _ENGINE.configure(enabled, volume)


def stop() -> None:
    _ENGINE.stop()


def close() -> None:
    _ENGINE.close()


def tick() -> None:
    """主循环每帧调一次（见 ``_Engine.tick``）。"""
    _ENGINE.tick()


def warmup(keys: Iterable[str] | None = None) -> int:
    """提前把素材备好、把设备开起来（见 ``_Engine.warmup``）。"""
    if not _ENGINE.enabled:
        return 0
    return _ENGINE.warmup(keys)


def is_enabled() -> bool:
    return _ENGINE.enabled


def current_volume() -> float:
    return _ENGINE.volume


def backend() -> str:
    """播放后端是不是可用。菜单/验收用来回答"为什么没声音"。"""
    return "pygame" if pygame is not None else "无（没装 pygame，静音）"


#: 菜单里的音量档位：``(显示名, 0..1)``。**只有这一份**——
#: 菜单构建与存档换算都读它，避免"菜单写着中、存档存的是 0.4"这种错位。
VOLUME_STEPS: tuple[tuple[str, float], ...] = (
    ("轻", 0.35),
    ("中", 0.65),
    ("响", 1.0),
)


def volume_label(volume: float) -> str:
    """把存档里的音量翻成人话（菜单勾选用）。最接近的那档算数。"""
    best = min(VOLUME_STEPS, key=lambda s: abs(s[1] - float(volume)))
    return best[0]
