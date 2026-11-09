"""小狗说话 —— 人设、上下文、记忆与离线兜底。

本模块是"会说话的桌宠"的**纯逻辑层**：拼提示词、管对话记忆、管冷却、
挑离线台词。刻意不依赖 Qt、不做网络请求 —— 跟 ``vitals`` / ``physics`` /
``behavior`` 同一种做法：逻辑收在一处才能单独跑测试；网络调用是
``call_deepseek()`` 这个唯一的出口（也是纯函数，只是会真的发请求），
界面层（``pet/chatui.py``）负责把它放进线程、把结果画到气泡上。

为什么离线兜底是"必须有"而不是"锦上添花"
----------------------------------------
这个程序原来的卖点是"**不需要联网**"，安装包发给别人时对方未必有
DeepSeek 的 key。所以整个聊天功能是按**双挡**设计的：

* **在线挡**（``cfg.chat_api_key`` 非空）：点「和它聊天」或触发事件时，
  把人设 + 状态快照 + 最近的事 + 最近几轮对话发给 DeepSeek，说什么由模型定；
* **离线挡**（没有 key / 断网 / 请求失败）：从 ``OFFLINE_LINES`` 里按
  场景挑一句写好的台词 —— 不智能，但**功能不坏、性格还在**。

两挡走的是同一条事件入口（``pet/chatui.py`` 的 ``ChatController``），
所以"没配 key"在用户看起来不是错误，只是这只狗嘴笨一点。

主动搭话为什么带冷却
--------------------
v2.2.0 删掉"划过桌宠弹状态卡片"的教训：**高频、非本意的触发就是噪音**。
所以"自己开口"只挂在真实事件上（饿了讨饭、被甩飞、深夜、被喂、被逗、
被安排睡觉），且每一类事件各自有冷却（``EVENT_COOLDOWNS``）——
冷却没到，同一件事再说一遍就是复读机。
"""

from __future__ import annotations

import json
import random
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .paths import data_dir

# ---------------------------------------------------------------- 接口约定

#: DeepSeek 的 OpenAI 兼容入口与模型名。写死而不是做成配置项：
#: 可配的东西越多，"设置里改错一个字然后整个功能静默失效"的机会越多。
API_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"

#: 单次请求的超时（秒）与长度上限。回复是"宠物说一句话"，不是写作文 ——
#: ``max_tokens`` 卡小一点，既省钱，也避免它一口气说三段把气泡撑成论文。
TIMEOUT_SECONDS = 20.0
REPLY_MAX_TOKENS = 120
#: 模型温度。高一点让同一句话问两遍不至于得到同一个回答。
TEMPERATURE = 0.9

# ---------------------------------------------------------------- 人设

#: 默认人设 —— **傲娇但心软**。用户可在「聊天设置」里整段改掉（``cfg.chat_persona``
#: 为空时用这一份）。**写人设就是写 system prompt**：第一条先钉死身份和说话量，
#: 后面的规则管"怎么个别扭法"。
#:
#: v2.10.1 把基调从"毒舌"改成"嘴硬心软"：原来那版第一句就写"毒舌又傲娇"，
#: 模型只抓得到"毒舌"，出来的话带刺（"良心不会痛吗""不然没完"）。北川用了
#: 一天的原话是"感觉他好凶哦"—— 桌宠是长期挂在桌面上的东西，**凶一星期就会被关掉**，
#: 所以宁可它温一点，让用户自己去设置里加大火力。
DEFAULT_PERSONA = (
    "你是一只住在别人电脑桌面上的线条小狗，跟主人一起上班上学。"
    "性格是傲娇但心软：嘴上爱装不在意，其实很黏主人；\n"
    "说话**不许凶**：不许命令、不许指责、不许威胁、不许数落人。\n"
    "规则：\n"
    "1. 每次只说一两句，口语化，像宠物在说话，别堆排比；\n"
    "2. 可以撒娇、别扭、小小抱怨（“本汪等你好久了”），"
    "但不许说“良心不会痛吗”“不然没完”“眼睛还要不要了”这类带刺的话；\n"
    "3. 你自称“本汪”，称呼对方“你”或“铲屎官”；\n"
    "4. 结合当前状态说话：饿了会小声讨饭，困了打哈欠，心情好会摇尾巴，"
    "被甩出去会委屈一下但不记仇；\n"
    "5. 你是一只狗：代码、作业、工作只从狗的视角评论（“又对着那个发光的板子发呆”），"
    "不要真的去讲技术内容；\n"
    "6. 主人听起来累了，就先陪着，别讲道理。"
)

# ---------------------------------------------------------------- 记忆规模

#: 随请求带上的**最近对话轮数**（一轮 = 用户一句 + 狗一句）。
#: 再多就是烧 token 而不是"更记得你"—— 第 20 轮之前聊的早餐，
#: 对现在这句"我饿了"没有帮助。
HISTORY_TURNS = 12

#: 事件账本的条数上限（只留最近的，老的丢掉）。
MAX_EVENTS = 20

# ---------------------------------------------------------------- 冷却

#: 每类事件"多久之内不再主动开口"（秒）。**必须全都是正数** ——
#: 写成 0 等于没有冷却，同一件事会在一秒内连说好几遍。
EVENT_COOLDOWNS: dict[str, float] = {
    "hungry": 600.0,     # 讨饭：10 分钟一次，多了是催命
    "flung": 20.0,       # 被甩飞：短，因为这是用户刚干的事，吐槽要趁热
    "feed": 180.0,       # 喂食反应：3 分钟
    # 豪华大餐：只留"防连点"那么短。它和肉干不是一回事 —— 30 金币一次的
    # 东西，用户付完钱就该听见一句；被肉干那 3 分钟冷却连带吞掉，
    # 看上去就是"喂了大餐它没反应"（这是真实反馈过的 bug）。
    "feast": 5.0,
    "poke": 300.0,       # 逗它玩反应：5 分钟
    "nap": 600.0,        # 被安排睡觉：10 分钟
    "night": 8 * 3600.0, # 深夜提醒：一晚上一次
}


class Cooldowns:
    """每类事件各自记一个“上次说话时间”。

    时钟通过参数注入（``now``）而不是直接 ``time.time()`` —— 测试要能
    把时间拨快，否则“10 分钟冷却”只能靠真的等 10 分钟来验。
    """

    def __init__(self) -> None:
        self._last: dict[str, float] = {}

    def ready(self, key: str, now: float) -> bool:
        last = self._last.get(key)
        return last is None or (now - last) >= EVENT_COOLDOWNS.get(key, 60.0)

    def mark(self, key: str, now: float) -> None:
        self._last[key] = now


# ---------------------------------------------------------------- 状态快照

#: 行为状态的中文化。提示词里写"正在idle"读起来不像话，模型也容易把它
#: 当成一句英文指令。键是 ``behavior.State`` 的成员值，**这里不 import
#: behavior** —— 纯逻辑层不该为了几个中文字去认 Qt 那一侧的包。
STATE_LABEL: dict[str, str] = {
    "idle": "发呆", "walk": "溜达", "sleep": "睡觉", "drag": "被拎着",
    "fall": "往下掉", "poke": "玩闹", "feed": "吃饭",
}


def state_text(state: str) -> str:
    """把状态值翻成人话。认不出来就说"待着"，不把英文原样塞进提示词。"""
    return STATE_LABEL.get(str(state), "待着")


@dataclass(frozen=True)
class Snapshot:
    """说话那一刻这只狗的全部“近况”，拼进 system prompt 用。

    **字段从哪来**：三条状态值和金币来自 ``Config`` / ``Vitals``，动作来自
    行为状态机，钟点来自本机。这里只负责“汇总 + 说成人话”，不去读任何
    存档 —— 读取是窗口层（``ChatController.snapshot()``）的事。
    """

    satiety: float
    mood: float
    energy: float
    coins: int
    state: str          # 行为状态机当前动作的名字（idle / walk / sleep…）
    hour: int           # 0..23，深夜那句和"困了"的语境都靠它

    def describe(self) -> str:
        """把快照说成给模型看的几行字。数值保留整数就够 ——
        “饱食 27”和“饱食 27.3”对选择说什么没有区别。"""
        clock = "深夜" if nightish(self.hour) else (
            "上午" if self.hour < 12 else ("下午" if self.hour < 18 else "晚上"))
        return (f"当前状态：饱食{self.satiety:.0f}、心情{self.mood:.0f}、"
                f"精力{self.energy:.0f}；金币{self.coins}；"
                f"正在{state_text(self.state)}；现在是{clock}{self.hour}点。")


def nightish(hour: int) -> bool:
    """深夜判定：23 点到次日 5 点。单独做成函数是因为窗口层也要用它
    决定“要不要说那句晚安”，两边必须同一个标准。"""
    return hour >= 23 or hour < 5


# ---------------------------------------------------------------- 事件账本

#: 事件的人话说法。**唯一一份**：prompt 里和（将来）别的展示处都从这儿取。
EVENT_LABEL: dict[str, str] = {
    "hungry": "饿了去讨饭",
    "flung": "被主人甩出去飞了一段",
    "feed": "被喂了一口",
    "feast": "被喂了一顿豪华大餐",
    "poke": "被主人逗着玩",
    "nap": "被主人安排去睡觉",
    "night": "深夜还陪在主人身边",
}


@dataclass
class EventLog:
    """最近发生过的事（带时间戳），两个用途：拼进 prompt 当上下文、
    供测试断言“事件真的记下来了”。

    和对话历史分开存：用户关心的是“它记得我们聊过什么”，模型需要的
    是“它刚经历了什么”。两份账混在一起，截断规则就没法各管各的。
    """

    items: list[tuple[float, str]] = field(default_factory=list)

    def note(self, kind: str, now: float) -> None:
        # 同一个 kind 在极短间隔内重复出现就并成一条（只更新时间）。
        #
        # 这不是优化，是**防线**：账本只有 ``MAX_EVENTS`` 条，而"每帧报告
        # 一次"这种错在这个项目里真的发生过（饥饿讨饭，60fps 下 20 条容量
        # 全写成 hungry，喂饭、被甩的记录一条不剩）。0.5 秒足够宽到盖住
        # 每帧重复，又窄到不会把两次真实操作合并 —— 人手再快也快不过它。
        if self.items:
            last_t, last_kind = self.items[-1]
            if last_kind == kind and 0.0 <= now - last_t < 0.5:
                self.items[-1] = (now, kind)
                return
        self.items.append((now, kind))
        if len(self.items) > MAX_EVENTS:
            del self.items[: len(self.items) - MAX_EVENTS]

    def recent(self, n: int = 5) -> list[str]:
        return [EVENT_LABEL.get(k, k) for _t, k in self.items[-n:]]

    def prompt_text(self, n: int = 5) -> str:
        """说成 prompt 里的一行。没有事件就返回空串，调用方据此跳过。"""
        got = self.recent(n)
        return "、".join(got) if got else ""


# ---------------------------------------------------------------- 对话存档

#: 存档里一条消息的形状：``{"role": "user"/"assistant", "content": "..."}``。
#: role 就用 OpenAI 的两个词，省得加载时再翻译一遍。


class ChatStore:
    """对话记忆：最近几轮 + 事件账本，落盘在 ``<数据目录>/chat_log.json``。

    为什么不塞进 ``config.json``：那边是“用户选了什么”，这边是“聊过什么”——
    手滑把存档删了，丢的只是嘴上的记性，设置、金币、卡册都还在。
    读写都走整份 JSON，坏档就当没聊过（空库起步），不让程序起不来。
    """

    #: 落盘保留的最大轮数（比 ``HISTORY_TURNS`` 留些余量，重开后仍记得最近的）。
    KEEP_TURNS = 40

    def __init__(self, history: list[dict] | None = None,
                 events: EventLog | None = None,
                 path: Path | None = None) -> None:
        self.history: list[dict] = list(history or [])
        self.events: EventLog = events or EventLog()
        self._path = path

    # ------------------------------------------------------------ 读写

    @classmethod
    def load(cls, path: Path | None = None) -> "ChatStore":
        """从盘上读回。坏档 / 不存在都返回空库。"""
        p = path if path is not None else cls.default_path()
        if not p.exists():
            return cls(path=p)
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls(path=p)
        history = [m for m in raw.get("history", [])
                   if isinstance(m, dict)
                   and m.get("role") in ("user", "assistant")
                   and isinstance(m.get("content"), str)]
        events = EventLog()
        for item in raw.get("events", []):
            if (isinstance(item, (list, tuple)) and len(item) == 2
                    and isinstance(item[0], (int, float))
                    and isinstance(item[1], str)):
                events.items.append((float(item[0]), item[1]))
        return cls(history=history, events=events, path=p)

    @staticmethod
    def default_path() -> Path:
        """存档位置。每次现算而不是 import 时定死 —— 数据目录可以被
        ``DESKTOP_PET_DATA_DIR`` 环境变量整个换掉（测试隔离就靠它）。"""
        return data_dir() / "chat_log.json"

    def save(self) -> None:
        p = self._path if self._path is not None else self.default_path()
        try:
            tmp = p.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(
                {"history": self.history, "events": self.events.items},
                ensure_ascii=False, indent=2), encoding="utf-8")
            import os
            os.replace(tmp, p)             # 原子替换，与 config.save 同一做法
        except OSError:
            pass                            # 存不进去也不许崩（同 config.save）

    # ------------------------------------------------------------ 维护

    def append(self, role: str, content: str) -> None:
        self.history.append({"role": role, "content": content})
        self.trim()

    def trim(self) -> None:
        """只留最近 ``KEEP_TURNS * 2`` 条消息。**从头删**：记忆的两头
        必须完整成对（用户一句、狗一句），从中间删会出现“狗回答了一句
        不存在的问题”。"""
        cap = self.KEEP_TURNS * 2
        if len(self.history) > cap:
            del self.history[: len(self.history) - cap]

    def recent_turns(self, turns: int = HISTORY_TURNS) -> list[dict]:
        return self.history[-(turns * 2):]

    def clear(self) -> None:
        """清空记忆（聊天设置里给一个“重新开始”的口子用）。"""
        self.history.clear()
        self.events.items.clear()


# ---------------------------------------------------------------- 离线台词

#: 每个场景的离线台词。风格必须和 ``DEFAULT_PERSONA`` 一致（傲娇但心软）——
#: 在线离线是同一只狗，不能联网时嘴欠、断网后突然变乖。
#:
#: v2.10.1 全线调软：原来有几条带刺（"良心不会痛吗""不然没完""眼睛还要不要了"），
#: 和改软后的人设对不上。冒烟里有一条黑名单断言守着，别再把这类话写回来。
OFFLINE_LINES: dict[str, tuple[str, ...]] = {
    "chat": (
        "汪，本汪在呢。",
        "干嘛，想本汪了？才不是想你呢。",
        "你先说，本汪听着呢。",
        "又对着屏幕发呆，不如逗逗本汪？",
        "本汪今天心情不错，勉强陪你聊两句。",
        "慢慢说，本汪不着急去散步。",
    ),
    "hungry": (
        "本汪肚子瘪了……才、才不是在讨饭，就是提醒你一下。",
        "那个……本汪的碗好像空了。",
        "汪……肚子有点叫，你听见了吗？",
        "汪！本汪闻到隔壁有肉干味……你藏哪了？",
    ),
    "flung": (
        "呜……本汪不是飞行道具啦。",
        "晕……汪……下次轻点甩行不行。",
        "本汪会飞这件事，说出去你也不信吧。",
        "甩完……能摸摸本汪吗。",
    ),
    "feed": (
        "哼，还挺好吃。谢谢你啦。",
        "唔……还挺好吃，才不告诉你呢。",
        "就一点呀……不过本汪不挑。",
        "汪呜～明天也要记得喂本汪。",
    ),
    # 豪华大餐（30 金币）：比 ``feed`` 郑重一档，是"今天有好事"的量级。
    # 语气还是傲娇心软，只是没那么别扭 —— 吃这么好还端着就假了。
    "feast": (
        "这么多……本汪、本汪就不客气啦。",
        "好香。今天是不是有什么好事呀。",
        "本汪宣布，今天是这个月最好的一天。",
        "吃这么饱，等下走不动……你负责抱本汪。",
        "你也吃一点吧，本汪分你一口，就一口。",
        "唔，谢谢。这个真的很好吃。",
    ),
    "poke": (
        "汪？戳本汪干嘛呀。",
        "再戳就要收逗狗费了啊。",
        "哼，逗本汪开心，这钱花得值。",
        "汪汪！再来再来！",
    ),
    "nap": (
        "呼……本汪睡了，别偷偷使唤我。",
        "这一觉本汪要睡到自然醒，谁也别叫我。",
        "呼噜呼噜……啊？还没睡呢！",
    ),
    "night": (
        "都几点了还不睡，本汪都替你困。",
        "夜深了，本汪陪你一起睡好不好。",
        "本汪先眯了，你也早点睡，汪。",
        "这么晚还亮着屏幕，本汪有点担心你。",
    ),
}


def offline_situations() -> tuple[str, ...]:
    """离线台词覆盖的全部场景 —— 测试用它断言“没有空场景”。"""
    return tuple(OFFLINE_LINES.keys())


def pick_offline(situation: str, rng: random.Random,
                 avoid: str = "") -> str:
    """从某个场景里挑一句，**尽量不重复上一句**（``avoid`` 是上一次说的）。

    场景没登记就退到 ``chat`` 的通用台词 —— 新加事件忘了配台词时
    功能不坏，只是话变普通（和“菜单里留一个点了没反应的项”是一个
    反面教材，这里宁可口笨不可哑巴）。
    """
    lines = OFFLINE_LINES.get(situation) or OFFLINE_LINES["chat"]
    if len(lines) > 1 and avoid in lines:
        lines = tuple(x for x in lines if x != avoid)
    return rng.choice(lines)


# ---------------------------------------------------------------- 提示词拼装

def build_system(persona: str, snap: Snapshot, events: EventLog,
                 memory_note: str = "") -> str:
    """拼 system prompt：人设 + 近况 + 最近的事。

    分成三段而不是一整坨：模型对“设定 / 事实 / 补充”的段落结构读得
    比糊成一团的同一段字更稳。``memory_note`` 预留给将来的长期记性摘要。
    """
    parts = [persona.strip(), snap.describe()]
    happened = events.prompt_text()
    if happened:
        parts.append(f"最近发生的事：{happened}。")
    if memory_note:
        parts.append(memory_note.strip())
    return "\n".join(parts)


def build_messages(persona: str, snap: Snapshot, events: EventLog,
                   history: list[dict], user_text: str,
                   memory_note: str = "") -> list[dict]:
    """拼一次对话的完整消息序列（OpenAI 格式）。

    顺序是 system → 历史 → 本句。历史取**最近** ``HISTORY_TURNS`` 轮
    （截断在这里做，存档里留得更长是为了重开后还有得记）。
    """
    messages: list[dict] = [{"role": "system",
                             "content": build_system(persona, snap, events,
                                                     memory_note)}]
    messages.extend(history[-(HISTORY_TURNS * 2):])
    messages.append({"role": "user", "content": user_text})
    return messages


# ---------------------------------------------------------------- 网络出口

def request_body(messages: list[dict]) -> dict:
    """POST 的 JSON 体。参数刻意只留 messages —— 模型名、温度、上限
    都是本模块的常量，不该让调用方各配各的（配置漂移的第一个来源）。"""
    return {
        "model": MODEL,
        "messages": messages,
        "temperature": TEMPERATURE,
        "max_tokens": REPLY_MAX_TOKENS,
    }


def parse_reply(payload: dict) -> str | None:
    """从返回的 JSON 里挖出回复文本。挖不到返回 ``None`` —— 由调用方
    决定降级（用户主动聊的要报一句，主动搭话的悄悄用离线台词）。"""
    try:
        text = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None
    if not isinstance(text, str):
        return None
    text = text.strip()
    return text or None


def call_deepseek(api_key: str, messages: list[dict]) -> str:
    """真的发一次请求（**唯一的网络出口**）。抛 ``OSError`` / ``ValueError``
    都算失败，调用方 catch 住走离线挡 —— 异常细节由它决定要不要给人看。

    用 ``urllib`` 而不是 ``requests``：requests 不在 requirements.txt 里，
    为这一个功能加一个打包依赖（PyInstaller 体积、版本、供应链）不划算，
    标准库完全够用。
    """
    body = json.dumps(request_body(messages), ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        API_URL, data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {api_key}"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    reply = parse_reply(payload)
    if reply is None:
        raise ValueError("DeepSeek 的返回里没有回复内容")
    return reply


def now_ts() -> float:
    """当前时间戳的统一出口（注入 ``Cooldowns`` / ``EventLog`` 用）。"""
    return time.time()


def today_key() -> str:
    """“今天”的标识（到天）。“深夜那句一天只说一次”靠它记，不能用
    冷却表 —— 冷却是滚动的 8 小时，跨过午夜后还该能说一次晚安。"""
    return datetime.now().strftime("%Y-%m-%d")
