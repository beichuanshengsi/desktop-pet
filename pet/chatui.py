"""会说话的桌宠 —— 界面层与调度。

分工：

* ``pet/chat.py``  —— 纯逻辑：人设、提示词、记忆、冷却、离线台词、网络出口；
* **本模块**      —— 线程、气泡、聊天窗口、设置对话框，以及把两件事缝起来的
  ``ChatController``。

三条不能破的规矩
----------------
1. **绝不阻塞 UI**。DeepSeek 一次请求 1~3 秒、超时 20 秒，放在主线程里就是
   "点一下狗，整个桌面卡住"。所以请求全在 ``ChatWorker``（QThread）里跑。
2. **绝不抢焦点**。气泡走 ``uitheme.apply_overlay_flags`` 那套（无边框、透明、
   ``WindowDoesNotAcceptFocus``、``WA_TransparentForMouseEvents``），
   鼠标点上去等于点到下面的东西。**用户在打字时它冒出来，不能把他的输入吃走**
   —— 这是桌宠存在的底线。
3. **主动开口必须有理由、有冷却**。所有自发台词都从 ``ChatController.event()``
   进来，由 ``chat.py`` 的 ``EVENT_COOLDOWNS`` 把关。v2.2.0 删掉划过弹卡片的
   教训就在这儿：高频、非本意的触发是噪音，不是陪伴。

为什么主动台词不进对话历史
--------------------------
对话历史（``ChatStore.history``）只装「你一句、它一句」的真聊天。事件台词
（饿了、被甩了）走 ``EventLog``，会随提示词一起发过去 —— 模型照样知道
"刚才被甩飞了"，但下次打开聊天窗口时，历史里不会突然插进一句没头没尾的
"喂！本汪不是飞行道具！"。
"""

from __future__ import annotations

import html
import random
import urllib.error
from datetime import datetime
from typing import Any

from PySide6.QtCore import (QObject, QPoint, QRect, Qt, QThread, QTimer,
                            Signal)
from PySide6.QtGui import QColor, QFontMetrics, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QTextBrowser, QTextEdit,
                               QVBoxLayout, QWidget)

from . import chat
from . import uitheme

#: 气泡最宽多少像素。再宽就横跨小半个屏幕，看起来像系统通知而不是"狗在说话"。
BUBBLE_MAX_WIDTH = 300
#: 气泡停留时长 = 基础 + 每个字多少毫秒，封顶。长句子给够时间读完，
#: 但不能停在屏幕上一整天。
BUBBLE_LINGER_MS = 2400
BUBBLE_MS_PER_CHAR = 150
BUBBLE_LINGER_MAX_MS = 11000
#: 气泡跟随桌宠的刷新间隔。16ms 是每帧都跟（白烧 CPU，狗走起来每秒 60 次 move）；
#: 60ms 肉眼看不出滞后，拖动时也跟得上。
BUBBLE_FOLLOW_MS = 60


# ==================================================================== 线程

class ChatWorker(QThread):
    """一次 DeepSeek 请求。成功发 ``done``（回复文本），失败发 ``failed``（人话原因）。

    ``failed`` 给的是**给人看的**一句话（"key 不对" / "余额不足" / "网络不通"），
    不是异常字符串 —— 用户点开聊天是想说话，不是想看 traceback。
    """

    done = Signal(str)
    failed = Signal(str)

    def __init__(self, api_key: str, messages: list[dict], parent=None) -> None:
        super().__init__(parent)
        self._api_key = api_key
        self._messages = messages

    def run(self) -> None:
        try:
            reply = chat.call_deepseek(self._api_key, self._messages)
        except urllib.error.HTTPError as exc:
            # 401/402 是"配置问题"，说清楚比"请求失败"有用得多：
            # 用户填错 key 或没充钱时，唯一的线索就是这句话。
            hint = {401: "API key 不对", 402: "账户余额不足",
                    429: "请求太频繁"}.get(exc.code, f"服务返回 {exc.code}")
            self.failed.emit(hint)
        except urllib.error.URLError:
            self.failed.emit("网络不通")
        except TimeoutError:
            self.failed.emit("等太久了，没等到回复")
        except (OSError, ValueError) as exc:
            self.failed.emit(str(exc) or "请求失败")
        else:
            self.done.emit(reply)


# ==================================================================== 气泡

def _wrap_text(text: str, fm: QFontMetrics, max_width: int) -> list[str]:
    """按像素宽度折行。逐字折 —— 中文没有空格可断，英文单词被切断也只是
    难看一点，不会读错；为了"英文单词不切断"去写一套分词，不值得。"""
    lines: list[str] = []
    cur = ""
    for ch in text:
        if ch == "\n":
            lines.append(cur)
            cur = ""
            continue
        if cur and fm.horizontalAdvance(cur + ch) > max_width:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    if cur or not lines:
        lines.append(cur)
    return lines


class ChatBubble(QWidget):
    """桌宠头顶的对话气泡：圆角白底、一个小尖角、说完全自动消失。

    **不接收鼠标**（``WA_TransparentForMouseEvents``）：它可能正好盖在你
    正在点的按钮上，吃一下点击就是事故。位置只由锚点决定，气泡自己不认识
    桌宠 —— 这样它也能给别的锚点复用。

    **会跟着锚点走**（v2.10.1）：只说一次位置不够 —— 狗会走来走去、会被
    拖着甩，气泡留在原地就成了"屏幕角落飘着一句话"。所以 :meth:`speak`
    可以多给一个 ``anchor_getter``，气泡自己按 ``BUBBLE_FOLLOW_MS`` 轮询
    重定位。传 ``None`` 就是老行为（只定位一次），测试也走这一条。
    """

    PAD = 12
    TAIL = 7            # 底部尖角高度

    def __init__(self) -> None:
        super().__init__(None)
        uitheme.apply_overlay_flags(self)      # 无边框 / 透明 / 置顶 / 不抢焦点
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._lines: list[str] = []
        self._font = uitheme.ui_font(10)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        # 跟随：单独一个定时器，hide 时停掉，免得跟一辈子
        self._anchor_getter: Any = None
        self._follow = QTimer(self)
        self._follow.setInterval(BUBBLE_FOLLOW_MS)
        self._follow.timeout.connect(self.follow_once)

    def speak(self, text: str, anchor: QRect,
              anchor_getter: Any = None) -> None:
        """在 ``anchor``（桌宠窗口的全局矩形）上方说 ``text``。

        ``anchor_getter`` 给了就一直跟着锚点走（返回最新全局矩形），
        不给就固定在开口那一刻的位置。
        """
        fm = QFontMetrics(self._font)
        self._lines = _wrap_text(text, fm, BUBBLE_MAX_WIDTH)
        text_w = max(fm.horizontalAdvance(line) for line in self._lines)
        text_h = fm.height() * len(self._lines)
        w = text_w + self.PAD * 2
        h = text_h + self.PAD * 2 + self.TAIL
        self.resize(w, h)

        self._anchor_getter = anchor_getter
        self._place(anchor)

        self.show()
        self.raise_()
        self.update()
        self._timer.start(min(BUBBLE_LINGER_MAX_MS,
                              BUBBLE_LINGER_MS
                              + BUBBLE_MS_PER_CHAR * len(text)))
        if anchor_getter is not None:
            self._follow.start()
        else:
            self._follow.stop()

    def _place(self, anchor: QRect) -> None:
        """按锚点把气泡摆好。尺寸已经由 :meth:`speak` 定好，这里只管位置。"""
        w, h = self.width(), self.height()
        screen = (QGuiApplication.screenAt(anchor.center())
                  or QGuiApplication.primaryScreen())
        area = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        x = anchor.center().x() - w // 2
        y = anchor.top() - h - 4
        if y < area.top():                  # 顶到屏幕上沿就翻到脚底下说
            y = anchor.bottom() + 4
        x = max(area.left(), min(x, area.right() - w))
        if (x, y) != (self.x(), self.y()):
            self.move(x, y)

    def follow_once(self) -> None:
        """跟一帧：由定时器驱动，也单独可调（测试用）。"""
        if self._anchor_getter is None or not self.isVisible():
            return
        try:
            anchor = self._anchor_getter()
        except RuntimeError:
            # 桌宠已经销毁（PySide 会抛 RuntimeError: Internal C++ object
            # already deleted）—— 别为了一个气泡让整个进程崩掉，安静停下。
            self._follow.stop()
            self._anchor_getter = None
            return
        if isinstance(anchor, QRect):
            self._place(anchor)

    def hideEvent(self, event) -> None:
        self._follow.stop()
        super().hideEvent(event)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        body = self.rect().adjusted(1, 1, -1, -self.TAIL - 1)
        cx = self.width() // 2
        left_x, right_x = cx - 7, cx + 7
        base_y, tip_y = body.bottom(), body.bottom() + self.TAIL

        p.setPen(QPen(QColor(uitheme.LINE), 1))
        p.setBrush(QColor(uitheme.SURFACE))
        p.drawRoundedRect(body, 10, 10)

        # 尖角：一个和气泡同色的三角，盖住底部那条描边，看起来才是"长"出来的
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(uitheme.SURFACE))
        p.drawPolygon([QPoint(left_x, base_y), QPoint(right_x, base_y),
                       QPoint(cx, tip_y)])
        # 三角两侧的描边补一下，否则尖角是"贴"上去的，接缝处看得出断口
        p.setPen(QPen(QColor(uitheme.LINE), 1))
        p.drawLine(QPoint(left_x, base_y), QPoint(cx, tip_y))
        p.drawLine(QPoint(right_x, base_y), QPoint(cx, tip_y))

        p.setFont(self._font)
        p.setPen(QColor(uitheme.INK))
        line_h = QFontMetrics(self._font).height()
        for i, line in enumerate(self._lines):
            p.drawText(self.PAD, self.PAD + line_h * (i + 1) - 4, line)


# ==================================================================== 聊天窗口

class ChatWindow(QDialog):
    """点「和它聊天」打开的窗口：上面是聊天记录，下面一行输入。

    和背包/卡册面板一样**懒建、建好复用**（见 ``PetWindow.open_chat``）：
    每次点都新建的话，用户挪过的窗口会跳回屏幕中间。

    这个窗口是**正常窗口**（不是气泡那套无焦点挂件）：用户既然点进来聊天，
    就是要打字，该能正常获得焦点、该能被 Alt+Tab 找到。
    """

    def __init__(self, controller: "ChatController") -> None:
        super().__init__(None)
        self._ctl = controller
        self.setWindowTitle("和小狗聊天")
        self.setMinimumSize(400, 440)
        self.setStyleSheet(uitheme.dialog_qss())

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        self.hint = QLabel("")
        self.hint.setObjectName("hint")
        root.addWidget(self.hint)

        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(False)
        self.view.setStyleSheet(
            f"QTextBrowser {{ background: #fbfcfe; border: 1px solid {uitheme.LINE};"
            f" border-radius: 10px; padding: 8px; color: {uitheme.INK}; }}")
        root.addWidget(self.view, 1)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.input = QLineEdit()
        self.input.setPlaceholderText("跟它说点什么…（回车发送）")
        self.input.setStyleSheet(
            f"QLineEdit {{ background: white; border: 1px solid {uitheme.LINE};"
            f" border-radius: 8px; padding: 8px 10px; color: {uitheme.INK}; }}")
        self.input.returnPressed.connect(self._send)
        send = QPushButton("发送")
        send.setObjectName("primary")
        send.clicked.connect(self._send)
        row.addWidget(self.input, 1)
        row.addWidget(send)
        root.addLayout(row)

        self.reload_history()
        self.refresh_hint()

    # ------------------------------------------------------------ 内容

    def reload_history(self) -> None:
        """按存档里的历史重画一遍（窗口是复用的，可能关过再开）。"""
        self.view.clear()
        for msg in self._ctl.store.recent_turns(chat.HISTORY_TURNS):
            who = "你" if msg.get("role") == "user" else "小狗"
            self._append(who, str(msg.get("content", "")))
        if not self._ctl.store.history:
            self._append("小狗", "汪。本汪在这儿呢，有事说事。")

    def _append(self, who: str, text: str) -> None:
        color = uitheme.ACCENT_DARK if who == "小狗" else uitheme.INK_SOFT
        self.view.append(
            f'<p style="margin:6px 0;"><b style="color:{color};">{who}</b>'
            f'　<span>{html.escape(text)}</span></p>')
        bar = self.view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def append_user(self, text: str) -> None:
        self._append("你", text)

    def append_reply(self, text: str) -> None:
        self._append("小狗", text)

    def refresh_hint(self) -> None:
        if self._ctl.online:
            self.hint.setText("DeepSeek 已连接 · 对话会记住最近 "
                              f"{chat.HISTORY_TURNS} 轮")
        else:
            self.hint.setText("离线模式：没填 API key，它在用本地台词说话"
                              "（菜单「聊天 → 聊天设置」里填）")

    # ------------------------------------------------------------ 交互

    def _send(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self.append_user(text)
        self._ctl.user_send(text)


# ==================================================================== 设置

class ChatSettingsDialog(QDialog):
    """聊天设置：API key、人设、清空记忆。

    **key 明文存进 config.json**：和 ``kids_passcode`` 同一个理由 —— 这是
    用户自己可以手改的文件，存哈希只会在"想换 key"时给他添堵；而这个 key
    是他自己的、本机上的、随时能在平台后台重置的东西。
    """

    def __init__(self, cfg, controller: "ChatController") -> None:
        super().__init__(None)
        self.cfg = cfg
        self._ctl = controller
        self.setWindowTitle("聊天设置")
        self.setMinimumWidth(460)
        self.setStyleSheet(uitheme.dialog_qss())

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        tip = QLabel("在 platform.deepseek.com 注册后创建 API key，粘到下面。\n"
                     "不填也能用：小狗会改用本地台词，功能不坏、只是不会接话。")
        tip.setObjectName("hint")
        tip.setWordWrap(True)
        root.addWidget(tip)

        root.addWidget(QLabel("API key"))
        self.key = QLineEdit(cfg.chat_api_key)
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("sk-…（留空 = 离线模式）")
        root.addWidget(self.key)

        root.addWidget(QLabel("人设（想换性格就改这段字，留空用默认的「傲娇但心软」；"
                              "想让它嘴更欠可以自己加，但别怪它凶）"))
        self.persona = QTextEdit()
        self.persona.setPlainText(cfg.chat_persona)
        self.persona.setPlaceholderText(chat.DEFAULT_PERSONA)
        self.persona.setFixedHeight(150)
        root.addWidget(self.persona)

        row = QHBoxLayout()
        forget = QPushButton("清空对话记忆")
        forget.clicked.connect(self._forget)
        row.addWidget(forget)
        row.addStretch(1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        save = QPushButton("保存")
        save.setObjectName("primary")
        save.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(save)
        root.addLayout(row)

    def _forget(self) -> None:
        """清空记忆。**点一下就清是危险的**，所以要先问一句 ——
        "记仇"这个功能好玩的前提是它真的记得，误点清空等于把这只狗的记性归零。"""
        from PySide6.QtWidgets import QMessageBox
        got = QMessageBox.question(
            self, "清空对话记忆",
            "要把本汪记得的聊天和最近发生的事都忘掉吗？\n（设置、金币、卡册都不会动）")
        if got != QMessageBox.StandardButton.Yes:
            return
        self._ctl.store.clear()
        self._ctl.store.save()
        if self._ctl.window is not None:
            self._ctl.window.reload_history()

    def accept(self) -> None:
        self.cfg.chat_api_key = self.key.text().strip()
        self.cfg.chat_persona = self.persona.toPlainText().strip()
        self.cfg.save()
        if self._ctl.window is not None:
            self._ctl.window.refresh_hint()
        super().accept()


# ==================================================================== 调度

class ChatController(QObject):
    """把"事件 / 用户输入"变成"一次请求或一句离线台词"，再把结果送到气泡和窗口。

    窗口层（``PetWindow``）只认识三个入口：``event()``（有事情发生）、
    ``user_send()``（用户在聊天窗口里说了什么）、``shutdown()``（退出时收尾）。
    其他全在这里 —— 窗口那 1200 行已经够重了，不该再知道 API key 长什么样。
    """

    def __init__(self, pet, cfg, *, store: chat.ChatStore | None = None,
                 rng: random.Random | None = None) -> None:
        # ``pet`` 在真程序里就是 ``PetWindow``（QObject），但调度器只用到它
        # 的 ``vitals`` / ``brain`` / ``frameGeometry()`` / ``isVisible()`` /
        # ``notify`` —— 测试传一个鸭子类型的假桌宠就够，不必造真窗口。
        # 不是 QObject 时 parent 只能是 None，否则 Qt 会直接抛 TypeError。
        super().__init__(pet if isinstance(pet, QObject) else None)
        self.pet: Any = pet
        self.cfg = cfg
        #: 懒加载：**构造窗口时不碰磁盘**。``PetWindow`` 在测试里会被造出来
        #: （冒烟测试的「桌宠窗口」那一段），构造期就去读/写 chat_log.json
        #: 会污染开发态的版本库根目录 —— 和 v2.3.0 那次"验证脚本写坏玩家存档"
        #: 是同一类坑，只是文件不同。
        self._store = store
        self.cooldowns = chat.Cooldowns()
        self.rng = rng if rng is not None else random.Random()

        self._bubble: ChatBubble | None = None
        self._window: ChatWindow | None = None
        self._workers: set[ChatWorker] = set()
        self._last_offline: dict[str, str] = {}
        self._night_day = ""          # 哪一天已经说过"该睡了"
        self._night_checked = 0.0     # 上次检查钟点的时间戳

    # ------------------------------------------------------------ 状态

    @property
    def store(self) -> chat.ChatStore:
        """对话记忆。**第一次真用到时才读盘**（理由见 ``__init__``）。"""
        if self._store is None:
            self._store = chat.ChatStore.load()
        return self._store

    @property
    def online(self) -> bool:
        return bool(self.cfg.chat_api_key.strip())

    @property
    def proactive(self) -> bool:
        """「主动搭话」开关。关掉只影响它自己开口，不影响聊天窗口。"""
        return bool(self.cfg.chat_enabled)

    @property
    def window(self) -> ChatWindow | None:
        return self._window

    def persona(self) -> str:
        return self.cfg.chat_persona.strip() or chat.DEFAULT_PERSONA

    def snapshot(self) -> chat.Snapshot:
        v = self.pet.vitals
        return chat.Snapshot(
            satiety=v.get("satiety"), mood=v.get("mood"), energy=v.get("energy"),
            coins=int(self.cfg.coins), state=str(self.pet.brain.state.value),
            hour=datetime.now().hour)

    # ------------------------------------------------------------ 气泡与投递

    def _bubble_up(self) -> ChatBubble:
        if self._bubble is None:
            self._bubble = ChatBubble()
        return self._bubble

    def anchor_rect(self) -> QRect:
        """桌宠此刻在屏幕上的矩形 —— 气泡每 60ms 问一次，用来跟着走。"""
        return self.pet.frameGeometry()

    def _speak(self, text: str, *, remember: bool) -> None:
        """说一句：气泡 + （窗口开着的话）记进聊天窗口。

        ``remember`` 只对"真聊天"为真 —— 事件台词进 ``EventLog``，
        不进对话历史（理由见模块开头）。
        """
        self._bubble_up().speak(text, self.anchor_rect(),
                                anchor_getter=self.anchor_rect)
        if self._window is not None:
            self._window.append_reply(text)
        if remember:
            self.store.append("assistant", text)
            self.store.save()

    # ------------------------------------------------------------ 用户主动聊

    def user_send(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        self.store.append("user", text)
        self.store.save()

        if not self.online:
            # 离线：直接给一句本地台词。**不进历史**的狗话会显得它没在听，
            # 所以这里的回复是要记住的（和在线回复一样）。
            line = chat.pick_offline("chat", self.rng,
                                     self._last_offline.get("chat", ""))
            self._last_offline["chat"] = line
            self._speak(line, remember=True)
            return

        messages = chat.build_messages(
            self.persona(), self.snapshot(), self.store.events,
            self.store.recent_turns(), text)
        self._ask(messages, situation="chat", complain=True)

    # ------------------------------------------------------------ 事件触发的主动开口

    def note_event(self, kind: str) -> None:
        """有事情发生了（饿了 / 被甩 / 被喂 / 被逗 / 被安排睡）。

        名字**不能叫 ``event``**：``ChatController`` 是 QObject，``event`` 是
        Qt 自己的事件分发入口（``event(self, QEvent) -> bool``），覆盖它会把
        Qt 投递过来的事件全部吞掉，而且签名对不上（pyright 也会报
        incompatible override）。这一条是踩过才写的，别再改回去。

        **记账总是发生**（哪怕关了主动搭话）—— 记账是"它记得刚发生了什么"，
        这件事和"要不要现在开口"是两回事：关了开关之后再打开聊天窗口，
        它照样能说"你刚才把我甩得可远了"。
        """
        now = chat.now_ts()
        self.store.events.note(kind, now)
        if not self.proactive:
            return
        if not self.pet.isVisible():
            # 藏在托盘里就别在空桌面上飘一个气泡 —— 而且**不消耗冷却**，
            # 等它被叫出来之后，这件事还能再说一次。
            return
        if not self.cooldowns.ready(kind, now):
            return
        self.cooldowns.mark(kind, now)

        if not self.online:
            line = chat.pick_offline(kind, self.rng, self._last_offline.get(kind, ""))
            self._last_offline[kind] = line
            self._speak(line, remember=False)
            return

        label = chat.EVENT_LABEL.get(kind, "发生了点事")
        clue = {"hungry": "它饿得不行，正在朝主人走过来讨饭",
                "flung": "它刚被主人拎起来甩出去，摔在地上",
                "feed": "它刚被喂了一口，正吃着",
                "feast": "主人刚给它买了一份豪华大餐，它正吃得很开心",
                "poke": "它刚被主人逗着玩，很开心",
                "nap": "它刚被主人安排去睡觉",
                "night": "已经很晚了，主人还醒着"}.get(kind, label)
        messages = chat.build_messages(
            self.persona(), self.snapshot(), self.store.events, [],
            f"（{clue}。就这个情况，主动对主人说一句话，只一句。）")
        self._ask(messages, situation=kind, complain=False)

    def maybe_night(self) -> None:
        """深夜提醒。由 ``_advance`` 每帧调，内部 30 秒才真检查一次。

        用"按天记"而不是只靠冷却：冷却是滚动的 8 小时，23:50 说过一次之后，
        第二天 23:40 才刚够 8 小时 —— 而用户那天可能通宵。按天记更符合
        "一晚上念叨一次"这个意图。
        """
        now = chat.now_ts()
        if now - self._night_checked < 30.0:
            return
        self._night_checked = now
        if not self.proactive or not self.pet.isVisible():
            return
        if not chat.nightish(datetime.now().hour):
            return
        day = chat.today_key()
        if self._night_day == day:
            return
        self._night_day = day
        self.note_event("night")

    # ------------------------------------------------------------ 请求

    def _ask(self, messages: list[dict], *, situation: str,
             complain: bool) -> None:
        """发一次请求。失败了就退到离线台词 —— **对用户永远是"它说了句话"，
        而不是"功能报错了"**；只有 ``complain``（用户主动聊）才额外提示一句原因。"""
        key = self.cfg.chat_api_key.strip()
        worker = ChatWorker(key, messages)
        self._workers.add(worker)

        def finish() -> None:
            self._workers.discard(worker)
            worker.deleteLater()

        def ok(reply: str) -> None:
            finish()
            self._speak(reply, remember=situation == "chat")

        def fail(reason: str) -> None:
            finish()
            line = chat.pick_offline(situation, self.rng,
                                     self._last_offline.get(situation, ""))
            self._last_offline[situation] = line
            self._speak(line, remember=situation == "chat")
            if complain:
                self.pet.notify.emit("聊天没连上", f"{reason}，先回你一句本地台词。")

        worker.done.connect(ok)
        worker.failed.connect(fail)
        worker.start()

    # ------------------------------------------------------------ 入口

    def open_window(self) -> None:
        if self._window is None:
            self._window = ChatWindow(self)
        self._window.refresh_hint()
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()
        self._window.input.setFocus()

    def open_settings(self) -> None:
        ChatSettingsDialog(self.cfg, self).exec()

    # ------------------------------------------------------------ 收尾

    def shutdown(self) -> None:
        """退出时收尾：断开信号、等一会儿在飞的请求、关掉两个窗口。

        等的时间很短（1.5 秒）：用户点了退出就是要走，不能因为一个请求
        卡着他。没等到也没关系 —— 线程会在进程结束时被回收，而
        ``worker.deleteLater`` 已经断开了回调，不会有"窗口没了还在 setText"。
        """
        workers = list(self._workers)
        self._workers.clear()
        for worker in workers:
            try:
                worker.done.disconnect()
                worker.failed.disconnect()
            except (RuntimeError, TypeError):
                pass
            worker.wait(1500)
        if self._window is not None:
            self._window.close()
            self._window = None
        if self._bubble is not None:
            self._bubble.hide()
            self._bubble.deleteLater()
            self._bubble = None
