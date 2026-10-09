# FACTS.md —— desktop-pet 单一事实源

**规则**：本区只写"有原始输出为证"的事实，每条附证据行。引用任何数字前先 `grep FACTS.md`。
`@版本` = 该结论所依据源文件的 MD5 前 8 位；源文件一改，对应条目即失效，需重验。

---

## 一、已验证事实（有原始输出为证）

### F1 · custom_pet 落位帧数
`custom_pet/` 共 **183** 张 png：idle 17 / walk 8 + walk_a 14（走路两套轮播）/ drag 23 / fall 0 /
**sleep 22（2026-09-23 新增，见 F27）**，
互动动作**各分三套** —— poke 9 + poke_a 14 + poke_b 20、feed 22 + feed_a 18 + feed_b 16
（多套机制见 F18）；`fall` 无素材，运行时借 idle 兜底。
- 证据：`for s in idle walk walk_a drag fall sleep poke poke_a poke_b feed feed_a feed_b; do echo "$s=$(ls custom_pet/${s}_[0-9][0-9].png|wc -l)"; done`
  → idle=17 walk=8 walk_a=14 drag=23 fall=0 sleep=22 poke=9 poke_a=14 poke_b=20 feed=22 feed_a=18 feed_b=16
- 证据：`ls custom_pet/*.png | wc -l` → 183
- **2026-09-23 变动**：新增 `sleep` 22 帧（来源 GIF 反查确认，见 F27）。
  原「161 张」作废。
- **2026-09-22 变动**：`idle` 从「站姿挥手」（14 帧）换成「坐木凳晃腿」（17 帧），
  换下来那 14 帧转去当 `walk_a`，走路变成两套轮播。此前「144 张」的旧值作废，见 F22。
- 非 png 文件仅 `README.md` / `facing.json`。@`16b87e8f`(assets.py)（旧值，以 F8 为准）

### F2 · custom_pet 位置（易踩）
`custom_pet/` 在**项目根目录** `desktop-pet/custom_pet/`，**不在** `assets/pet/` 下。
`assets/pet/` 是「内置素材」的落点，但**现在里面只有一份 README**
（那 21 张由 assetgen 生成的 PNG 已于 2026-09-22 随生成器一起删除，见 F26）。
- 证据：`find . -type d -name custom_pet` → `./custom_pet`
- 证据：`ls assets/pet/` → 只有 `README.md`
- 反例（错误的查法）：`ls assets/pet/custom_pet/*.png | wc -l` → 0，**不能**据此判断"没入库"。

### F3 · 状态机已无 PLAY，互动拆成两个独立状态（2026-09-23 新增 SLEEP）
`pet/behavior.py` 的 `State` = `IDLE/WALK/DRAG/FALL/POKE/FEED` + **`SLEEP`**（7 个，SLEEP 见 F27）；
全文件 grep `PLAY|jump` **无匹配**。
**状态名的唯一来源就是 `State`**：`assets.STATES` 与 `prep_sticker.VALID_STATES` 都从
`behavior.KEYS` 派生（`KEYS = tuple(s.value for s in State)`），不再各抄一份（见 F26）。
`FPS`：IDLE 7.0 / WALK 11.0 / DRAG 13.0 / FALL 7.0 / **POKE 12.5** / **FEED 10.0** / **SLEEP 4.0**。
（SLEEP 特意压到 4fps：素材原速约 12.5fps，会像抽搐；4fps 下一个循环 5.5 秒，像在慢慢呼吸翻身。）
`ONESHOT = (State.POKE, State.FEED)`，`ONESHOT_FALLBACK = 1.0`。
`pet/assets.py` 的 `STATES` 直接从 `behavior.KEYS` 派生（不再是手写元组）。
- 证据：`grep -n "class State" -A 12 pet/behavior.py`；`grep -rn "PLAY\|jump" pet/behavior.py pet/assets.py` → 空
- 证据：`grep -n "FPS = " -A 11 pet/behavior.py`；`grep -n "from .behavior import KEYS" pet/assets.py`

### F4 · 冒烟测试现状
`tools/smoke_test.py` **424 项通过 / 0 失败**（输出末行「通过 424 项，失败 0 项 / 全部通过」）。
覆盖：素材加载（含**多套素材解析**、缺状态借 `idle` 兜底）、存档读写（含坏档）、状态机、
物理、朝向（含**按套覆盖**）、互动动作时长与冷却、**「重力下坠」开关关掉后真的不下坠**、
**养成状态（在线/离线衰减、阈值、睡觉回精力）**、**甩出去（手速判定与钳制）**、
**金币折算与小卖部买卖（含"买下只进背包、状态不变"）**、**背包（增减 / 整笔失败 / 存档容错往返 / "第一样吃的"要跳过玩具）**、
**「喂一口」的每日免费额度与"吃掉背包里第一样吃的"**、
**番茄钟计时与只响一次（单位：秒）**、**滚轮时长选择器（1 秒下限 / 2 小时上限 / 三列联动 / 循环）**、
**新增界面（时长对话框吃真实 `QWheelEvent`、状态面板读数、划过气泡弹出与收起，三者离屏渲染）**、
**接狗狗的骨头回血与带风漂移**、
**弹跳得分的方块耐久 / 敲不穿=墙 / 敲穿=放行 / 连击倍率 / 掉落道具 / 加时天花板 / 攻不破的墙**、
两个游戏的规则与结算、菜单接线、游戏素材前缀自动发现、
**一个动作多套素材的随机挑选与"连续两次不重复"、多套素材下真实渲染一帧**、
**walk 起步挑套 / 行走途中不换套 / 两套 walk 都真实渲染一帧、walk 每套左右走画出的帧不同**、
（两个游戏各离屏渲染一帧）、
**两个游戏窗口继承 `GameWindow` 且没有各抄一份 `closed` 信号**。
- 证据：`"C:/Users/华硕/.workbuddy/binaries/python/envs/default/Scripts/python.exe" tools/smoke_test.py | tail -3`
  → 实测「通过 424 项，失败 0 项 / 全部通过」
- **2026-10-08（见 F31，v2.2.1）**：新增 1 段共 **19 条** ——
  **「喂一口」的每日免费额度**（今天没喂过 → 免费且不看背包、喂完记下当天、
  免费用完且背包空 → `feed_plan()` 为 `None`、空背包再点饱食一点不动、
  背包有吃的 → 计划变成"吃掉肉干"并预告吃掉之后还剩几个、真的吃掉并加它自己的效果、
  背包里只剩玩具 → 照样喂不了、跨天额度自动回来、
  菜单那一行的三种文字与"能不能点"、免费陪伴收益低于玩具球、逗它玩新数值）。
  项数 **405 → 424**，原「405 项」作废。
- **2026-09-27 深夜（见 F30，v2.2.0）**：新增 2 大段共 **62 条**，另把 3 条气泡断言
  换成 3 条**防回退**断言（见 F30 第一节）——
  **跑一跑**（27 条：难度分档与速度曲线、间距收紧、跳跃缓冲、
  `apex()` 实测跳跃高度、`FAST_FALL` 真的更快落地、判定盒收窄后"看着擦过去"算过、
  三种障碍的贴地/吊顶高度、`pick_pattern` 排除上一组、HUD 四段不叠且槽位不叠）、
  **狗粮 2048 · 规则 + 窗口**（35 条：`slide_line` 一次只合一次、不同行的两块不合、
  无效方向不冒块不记历史、撤销三元组 / 次数用光 / 撤销退分数、
  目标达成结算与金币按最大格子、死局结算、HUD 同上）。
  项数 **323 → 405**，原「323 项」作废。
- **2026-09-27 傍晚（见 F29，v2.1.0）**：新增 2 大段共 **41 条**，并把 3 条老断言改成新语义 ——
  **背包**（`normalize` 剔脏数据、`add`/`take`/`total`/`entries` 按 `SHOP` 排序、
  **不够时整笔失败不做"扣到 0 为止"**、存档往返、`from_dict` 容错）、
  **番茄钟时长**（`clamp_seconds` 夹在 1s~7200s、`hms`/`seconds_of` 往返、
  **`format_clock(0)` 必须是 `00:00` 而不是被下限夹成 `00:01`**、`describe` 三种说法）、
  **滚轮选择器**（`h=0,m=0` 时秒列 1..59、滚到 2 小时连带清零分秒、
  分/秒列循环、非法值忽略、快捷档位也走同一套联动）、
  **新增界面**（对话框停在上次选的时长、快捷档位与菜单同一份清单、
  合成 `QWheelEvent` 后下滑 = 数值变大、面板读真实数据、格子按数量画、
  点「使用」真的用掉一个、气泡不越界且不抢焦点、三者离屏 `grab()`）、
  **弹跳得分·耐久/连击/道具**（`hp_for` 梯度与 `MAX_HP` 封顶、`clear_time_bonus` 递减与下限、
  `combo_mult` 三档、敲一下扣 1 点耐久、**没敲碎的球被弹回 / 敲碎的球原样继续往上**、
  踩顶借力、倍率真的参与计分、三种道具效果、加时天花板、接住与漏掉两条路径、
  同种子同抽奖结果、金币量级未通胀、
  **让球真的在物理循环里跳一次：全盘是墙就过不去 / 下排可敲穿就顶得上上一排**）。
  「小卖部与金币」段里 3 条断言改写：原来验的是"买下就抬状态"，
  现在验"买下只进背包、状态不变"，另加"点背包里的东西才抬状态"。
  另有一组 **9 条 HUD 排版断言**（见 F29 第五节）：四张表键名一致、按最宽内容算的各段
  "占用区间"两两不交叉、每段宽度够放最宽内容、左右次序、不越界、进度条不压秒数、
  右对齐段的右端钉住。**这组断言故意不查字体度量**（offscreen 平台没有字体库）。
  项数 **234 → 323**，原「234 项」作废。
- **2026-09-23 午（见 F27，v2.0.0）**：新增 5 段共 **83 条** ——
  **养成状态**（衰减率、边界钳制、离线下限、吃饱/逗乐/睡觉回精力、饥饿与疲惫阈值、
  `tired`/`rested` 滞回不抖动）、**甩出去**（`VelocitySampler` 估速、过窗口的点被丢、
  `clamp_fling` 上下限钳制、轻放不甩）、**小卖部与金币**（`coins_for` 折算、**没结算不给钱**、
  买东西扣款与生效、**钱不够时商品项全灰掉且不把分隔线算成可点项**）、
  **番茄钟**（`tick` 只在到点返回一次 `True`、`progress`/`label`）、
  **接狗狗·骨头与漂移**（骨头给分与回血、满血不超上限、带风落体撞墙反弹）。
  另把老断言「游戏菜单接线」改成**按标题找「一起玩游戏」子菜单**（右键菜单现在有 3 个子菜单，
  原来的"只有 1 个子菜单"假设失效）。项数 **151 → 234**，原「151 项 / 159 项」作废。
- **2026-09-22 傍晚（见 F26）**：素材段改写 —— 原来跑 `pet.styles` 的两套生成器循环，
  现改为在**临时目录现造纯色 PNG**（默认套 + 套 a，各 2 帧）验 `AssetBank`，
  真实素材目录只读。`SPRITE[...]` 断言改用 `State.POKE.value / State.FEED.value`。
  项数 **159 → 149**，原「159 项」作废。
- **同批新增 2 条**（版本号段）：`CHANGELOG.md 存在`、
  `CHANGELOG 首条版本号与 __version__ 一致` —— 版本号写在 `pet/__init__.py` 与
  `CHANGELOG.md` 两处，必须有断言盯着它们别漂。项数 **149 → 151**。
- 2026-09-21 17:40 新增 9 条：`GameWindow 自己声明了 closed`、
  `MiniGame/CatchGame 继承 GameWindow`、`MiniGame/CatchGame 没有另抄一份 closed`、
  `create_game(...)` 的窗口是 `GameWindow`、`实现了 _step / _reset_scene`。
- 2026-09-22 下午新增 6 条：`walk 有多套素材可选`、`每次起步都会重新挑套`、
  `两套 walk 素材交替（不连着重复同一套）`、`行走途中不换套（一趟走法保持一致）`、
  `walk 的套「默认」/「a」能渲染出一帧`（8 帧 / 14 帧）。
  实测交替序列 = `a - a - a - a -`（`-` 指默认套）。原「134 项」作废。
- **2026-09-22 傍晚新增 10 条**（按套朝向，见 F24）：`按套朝向能读回，非法值直接丢`、
  `按套朝向按素材前缀查：walk_a 被覆盖成朝右`、`没单独声明的套跟随目录默认`、
  `套名不跨状态串台：poke_a 不受 walk_a 影响`、`只改总朝向不会抹掉按套声明`、
  `显式传空表 = 清掉按套声明`、`现役素材 默认套：向右走要镜像`、
  `现役素材 walk_a：向右走不镜像（按套声明生效）`、
  `套「默认」/「a」左走/右走画出的帧不一样（镜像真的生效）` ×2。
- **2026-09-22 夜新增 9 条**（重力开关，见 F25）：`物理层：不给重力就不动`、
  `关掉重力：悬在半空不下坠`、`打开重力：照旧落到地面并站住`、
  `关掉重力时点击不起跳（否则会一路飘到天花板）`、`关掉重力不影响逗它玩本身`、
  `关掉重力：松手不进 FALL（它等不到落地）`、`关掉重力：松手停在哪就悬在哪`、
  `打开重力：松手照旧进 FALL`、`下坠途中关掉重力：立刻退出 FALL，不留半空演下坠`。
  实测：起点 y=83，勾选跑到 y=647（下坠 564px）、不勾 y 恒为 83、中途关掉停在 193。
  原「150 项」作废。
- 版本：@`f727b687`(smoke_test.py) @`c43f489d`(minigame.py) @`ed39e56e`(catcher.py)
  @`2f766fef`(common.py) @`ff04b371`(vitals.py) @`9805fd8b`(pomodoro.py)
  @`3919a9b5`(behavior.py) @`80c94d10`(window.py)

### F5 · 桌宠 5 个状态的素材来源与缩放参数（2026-09-21 下午这批）
从素材库 `assets/raw/_library/0921_1530_线条小狗GIF/` 挑 5 个 GIF，用
`prep_sticker.py --custom --scale <绝对值>` 逐状态落位（**不是** `intake.py` 批量入库）：

| 状态 | 源文件 | 源尺寸/帧 | 输出帧 | `--scale` | 内容高 |
|---|---|---|---|---|---|
| walk_a（2026-09-22 前是 `idle`） | `xian_tiao_xiao_6024_线条小狗.gif` | 360×360 / 14f | 14 | 0.4564 | 100 |
| walk | `xian_tiao_xiao_5197_线条小狗C (82).gif` | 500×493 / 8f | 8 | 0.4000 | 94 |
| drag | `xian_tiao_xiao_6588_线条小狗害怕.gif` | 240×240 / 23f | 23 | 0.7383 | 95 |
| poke | `xian_tiao_xiao_3411_线条小狗 (307).gif` | 240×240 / 9f | 9 | 0.9000 | 99 |
| feed | `xian_tiao_xiao_218_线条小狗表情包动图 (2).gif` | 360×360 / 22f | 22 | 0.5046 | 109 |

- 证据：`for name in <上列 5 个>; do Image.open(L/name) 打印 size/n_frames; done` → 尺寸与帧数如上
- 证据：各状态内容高由 `getbbox()` 量出，中位数 100/94/95/99/109（128 画布，底边均为 y=122）
- 另有给 poke/feed 各配的 2 套备选（poke_a/poke_b/feed_a/feed_b），来源与参数见 F18。
- **`idle` 已不在这批里**：2026-09-22 换成 17 帧「坐木凳晃腿」，来源是
  `assets/raw/_snapshots/线条小狗晃脚脚2_idle/`（原 GIF 已丢失），
  用 `tools/rebuild_from_snapshot.py` 按 ×1.26 重摆 —— 详见 F22。
- 上一轮成品备份：`assets/raw/_snapshots/pre_1550/`（76 张 png + README + facing.json）；
  原 GIF 在 `assets/raw/_archive/0921_1400/`。@`3076e6cb`(prep_sticker.py)
- **本轮（2026-09-23）新增第 7 个状态 `sleep`**：`xian_tiao_xiao_5191_线条小狗C (13).gif`
  （250×250 / 22f / **黑底**），自动缩放 0.7436，内容 112×62 —— 来源用像素反查确认，
  详见 F27。本表因此只覆盖"2026-09-21 那批 5 个状态"，**不是当前全部状态的清单**。

### F6 · 朝向声明
`custom_pet/facing.json` = `{"base":"left","sets":{"walk_a":"right"},"note":…}`。
`base` 是**整个目录**的默认（脸在左、后腿在右，向右走时要镜像）；
`sets` 是**按套覆盖**表，key = 素材前缀（`walk_a`），见 F24。
- 证据：`cat custom_pet/facing.json`；`tools/set_facing.py` 输出
  「默认朝向 朝左 / 按套 walk_a -> 朝右 / [默认套] 向右走要镜像 / [walk_a] 向右走不镜像」
- ⚠️ `verify_facing.py` 的数字比对**不能**作为"朝向声明填对了"的证据：它读的就是声明，
  只能证明"绘制与声明一致"（`head_side()` 拿 base 反推头朝哪边）。
  声明对不对只能靠人眼看图里第一行的"素材原图 / 水平镜像"。
  2026-09-22 的 `walk_a` 就是这种情况 —— 代码没错，是声明漏了一套。
- @`0890187f`(pet/facing.py) @`a469a5e4`(tools/set_facing.py)

### F7 · 验收产物实体（全部在 `reports/`）
2026-09-22 傍晚（按套朝向改完之后）实测字节数：
`preview_motion.gif`（**128 帧**，2494829 B）、`preview_sheet.png`（463739 B）、
`verify_desktop.png`（19620 B）、`actions_desktop.png`（299574 B）、
`facing_fix.png`（**214808 B**，2026-09-22 傍晚改成"逐套"布局后变大，原 109192 B）、
`variants.png`（235271 B，多套素材验收，见 F19）、
`walk_sets.png`（243058 B，走路两套素材验收，见 F19 —— 字节数与改朝向之前差 3 B，
因为图里那两帧真的跟着翻转了）、
`gravity_switch.png`（192761 B，816×1144，「重力下坠」开关验收，见 F25 ——
连跑两次 md5 都是 `6c7bbab7cfbe0e32f5d1f9b24509589a`，可复现）。

**2026-09-23 午新增 3 张**（v2.0.0 五大玩法，见 F27）：

| 产物 | 尺寸 | 可复现？ | 说明 |
|---|---|---|---|
| `vitals_curve.png` | 1042×776 | **可复现**（连跑两次 md5 均 `0e039b55405ac26aa5725059c2ab576d`） | 36 小时养成曲线 + 睡眠区间色带，用**真实 `PetWindow._advance` 循环**跑出来 |
| `fling_throw.png` | 632×1054 | ✗（手速靠真实时钟采样，每跑略变） | 4 种松手方式的真实轨迹，见 F28 |
| `catch_items.png` | 990×1078 | ✗（落点与风向随机） | 真实游戏画面 + 带风落体 `x(t)` 轨迹 + 骨头占位形象 |

**2026-09-27 傍晚新增 1 张**（v2.1.0，见 F29）：

| 产物 | 尺寸 | 可复现？ | 说明 |
|---|---|---|---|
| `v21_ui.png` | 1120×2555 | **可复现**（脚本不注入时钟；落体/道具都是摆死的） | 滚轮时长对话框 + 两个滚轮（含"2 小时 → 分秒只剩 0"）+ 背包面板 + **右键菜单里的状态两行** + 打砖块一帧，五块各抓真图排成一页；跑法 `python tools/verify_v21_ui.py`。**v2.2.0 改过**：撤掉气泡那一节（原来 1120×2451），第四节换成"抓右键菜单" |

**2026-09-27 深夜新增 1 张**（v2.2.0，见 F30）：

| 产物 | 尺寸 | 可复现？ | 说明 |
|---|---|---|---|
| `v22_ui.png` | 1120×2125 | **可复现**（三姿态/两种残局都是摆死的位置；跑一跑不注入时钟，只摆一帧） | 跑一跑一帧（三种障碍同框）+ 跑一跑三种姿态（站立/低头/跳跃）+ 狗粮 2048 一帧（早局）+ 狗粮 2048 残局（含 512、外圈金边），四节竖排；跑法 `python tools/verify_v22_ui.py`。**运行时会打印两款新游戏 HUD 的"登记值 / 实量"对照，超了标 `<- 超了！`** —— 2048 的 `tile`/`undo` 差 1px 叠字就是靠它发现的 |

> 这两张图**都不能用 `QT_QPA_PLATFORM=offscreen` 跑**：那个平台插件在本机字体库是空的，
> 抓出来整张图 0 个认得的字（第一版真踩过，见 F29 第五节 / V13），
> 而且**字体度量也不能信**（量到的是方框宽，比真值宽一倍左右）。

**游戏截图不做基准**：`shot_game.png` / `shot_gameover.png` / `shot_catcher.png` /
`shot_catcher_over.png` 每次跑都会变（道具与小狗的落点是随机的），
实测同一份代码连跑两次 `shot_game.png` 的 md5 就不同 —— 只能看，不能当判据。
- 可复现的只有 `preview_motion.gif` 与 `preview_sheet.png`：连跑两次 md5 一致
  （`0cae756b…` / `2cd17f38…`），可作为"预览链没被动过"的判据 ——
  但它们**依赖当前素材与代码**（08:00 与 16:00 两次测得的值都不同，改朝向也会变），
  **别当成跨素材的常量**，改完东西必须重测。
**项目根目录不再有任何 png/gif**（`render_preview.py` / `verify_desktop.py` 已改为直接写 `reports/`）。
- 证据：`ls -la reports/*.png reports/*.gif`；`ls *.png *.gif` → 空
- 证据：`render_preview.py` 输出 `[preview] preview_motion.gif  128 帧  2436 KB` @`f981f760`
- ⚠️ 踩坑记录：加多套素材后，`render_preview.py` 里的 `glob("poke_*.png")` 一度把三套
  拼成一条序列（动图变 190 帧、对照表写成"poke 43 帧"）。改用
  `pet.assets.set_files()`（当时叫 `default_set_files`）只取默认套后恢复正常。
  脚本读素材**不能**裸 glob。
- 修正记录：2026-09-21 傍晚之前这 7 张是写在项目根目录的（见 V6）。
- 注：动图帧数（128）与 `preview_sheet.png` 的字节数**依赖当前素材与代码**
  （2026-09-22 换掉 idle 之前是 122 帧 / 454267 B；同一天改朝向之前是 2454143 / 459156 B），
  但在源文件不动时是稳定值，可以当"预览链没被动过"的判据 ——
  **别当成跨素材的常量**。
`reports/` 下另有几份一次性检查图（`pet_states_check.png` 355758 B、`walk_motion_AB.png`
453650 B、`walk_desktop.png` 203919 B、`icon_check.png` 93291 B、`icon_preview.png` 66420 B、
`size_compare.png` 95898 B、`user_gifs_raw.png` 98114 B、`idle_compare.png` 176846 B、
`scale_probe.png` 362757 B），不是每次跑都生成。

### F8 · 源文件指纹（本条即全局 @版本 基准）
`md5sum` 于 **2026-10-08**（v2.2.1「喂一口」不再白送之后，见 F31）重采：
```
4e6eb36d176f3cd3d96bac85ae596ee8  main.py                        （本文件未动）
b73a44867ebc7faa0560f27a19927f04  pet/__init__.py                （__version__ 2.2.0 → 2.2.1）
3396d7336c2c47a0f6c399a9591eea72  game/__init__.py               ★GAMES 2 款 → 4 款（+runner/+2048）
76c67e07bfa8ac01490eb8719b84a076  game/common.py                 ★新增 zone_spans / overlapping_zones / measure_zone_widest + BG_RUNNER / BG_2048
2a80f6b1b19ecf7fbb24e368c380a5b5  game/minigame.py               ★hud_zone_rect / measure_hud_widest 改为转调 common 的共享函数
ed39e56edd20be9f26712accf0a712b8  game/catcher.py                （本文件未动）
9393140eda33d1c07131251c8dd175ee  game/runner.py                 ★新增：跑一跑（横版跑酷，跳跃缓冲/可变跳高/快速下落/判定盒宽容）
b4c7255aab8d2e34c4900b841261457e  game/g2048.py                  ★新增：狗粮 2048（规则层不 import Qt；金币另有尺子 coins_for_tile）
17a44b33dc5c1cf6a53d51adbe0112c3  pet/paths.py
219d81c4de0af532b6d15eeefd3e80f4  pet/config.py                  ★+DAY_FMT / today_stamp() / free_feed_day（"每天一次"那份额度）
78cbff1d2c68f286751f5699677fd18c  pet/menu.py                    ★+is_food / _FeedPlan Protocol / feed_text；add_interactions 改成当场算文字与可用状态
89c930392f82e77b4d1fbc949700c3af  pet/vitals.py                  ★PLAY_GAIN 22 → 8；精力消耗抽成独立的 PLAY_ENERGY_COST = 3.3
17ff8dfcda51bce8f1ab24f68a9e4e8d  pet/pomodoro.py
da7e46f0b462eb9449c6da63286172ea  pet/wheel.py
e7ae7f9daec095ac17db1745ab297d01  pet/wheel_dialog.py
1d1a8e0692a962e5f188ff740ddf2ff2  pet/bag.py                     ★+first_food()（按 SHOP 顺序取第一样"吃的"）
dc4df0557230868dbae67607533cff38  pet/panel.py                   ★重写：删 StatusBubble / VitalsStrip，只剩 BagPanel + where 提示行
681e6eca2f6a13ada51ff5e1ff84009c  pet/uitheme.py
4808de34ef29caae06b2cbb78337e2ed  pet/window.py                  ★+FeedPlan / feed_plan()；feed() 改成"每天一次免费、之后吃背包里的"
bb7ff07cb2e4f69dcbbb101709689266  pet/tray.py                    ★菜单项改名（背包面板）
3919a9b5ff0e00323274631885a5b340  pet/behavior.py
77d71c7421dc2b9909cfe468629ca961  pet/facing.py
45ea83f2f28d41ca312cf04a236b796b  pet/icon.py
358a908ec3fb28951593e6df5cced09d  pet/assets.py
dbbd40d971831fd4f2449721984441f2  pet/anim.py
9134f847ccbf166f7ab6a02b9abafac0  pet/physics.py
284f6ed5453abd0cb4507b83442507e6  tools/prep_sticker.py
6d9529f7c36b51f8f3e71135ea75ac25  tools/prep_bg.py
86bd34e3508af85015a949cb787b8749  tools/intake.py
71c6e79a038e79f9c8a545c58371eb08  tools/render_preview.py
96d0be8ed1dbef1053c08954d4147015  tools/smoke_test.py            ★+1 段共 19 条（「喂一口」的每日免费额度，见 F4）
1995849ed4204c8f758b91df408c19ab  tools/typecheck.py
c4aedbe4301a671623b050f92ea9e1fe  tools/verify_desktop.py
f0e9875c661b5c019b4edaeecb6daffc  tools/review_materials.py
807da7b72d8afc94f8cd113b6da576b0  tools/verify_facing.py
d679fba574a6a7c0e6245477542855a5  tools/verify_actions.py
936e5526fe3ed4868b435d68777bc66d  tools/verify_variants.py
386d39f0ed978cc361e0f974116fd772  tools/verify_walk_sets.py
af62748bc966b04916aed03d7c12a79e  tools/verify_gravity.py
40d6b6bf1d41eeec26c18aaffb934319  tools/verify_fling.py
54baf54aebc183ac95c15d68fff4ffca  tools/verify_vitals.py
d9dbcea7e911dbd4888ba3801483c4ef  tools/verify_catch_items.py
ec77b118e95562fee15c5d539d379027  tools/rebuild_from_snapshot.py
90099636f4eaeae58672f65a04ac5e1f  tools/make_icon.py
dc8dfbf5d2728da8ffd8c47e0e0d2e66  tools/set_facing.py
dc0d217dc807f5c9497f22913e8abb8d  tools/verify_v21_ui.py         ★删气泡那节、③ 改「背包面板」、新增「状态只在右键菜单」
63c9fb408750ad16a354572a54459ff6  tools/verify_v22_ui.py         ★新增（v2.2.0 界面验收）
```
**已删除、不再有指纹**（见 F26）：`pet/assetgen.py`、`pet/assetgen_line.py`、`pet/styles.py`、
`tools/gen_assets.py`、`tools/make_fixtures.py`、`tools/fixtures/`、`assets/pet/*.png`、`.style_cache/`。

> 改动上述任一文件后，本表中引用该文件 @版本 的条目需重新验证。
> 最近一次变动（**2026-10-08**）：v2.2.1（「喂一口」每天一次免费、之后吃背包里的；
> 「逗它玩」收益 22 → 8）。**素材零增零减** —— 这一轮同样没碰 `custom_pet/`、
> `assets/game/`、`assets/raw/`，所以 F1 / F5 / F13 / F17 / F18 / F23 / F24 / F25 /
> F26 全部继续成立；F4 的项数按 F31 重测（405 → **424**）。
> 上一轮（2026-09-27 深夜，v2.2.0）见 F30。
> 更早的变动见 V11 / V12 / V13 / V14 与 F26 末尾的时间线。

### F9 · 小游戏清单与接线
`game/__init__.py` 的 `GAMES` = `(("bounce","弹跳得分",…), ("catch","接狗狗",…), ("runner","跑一跑",…), ("2048","狗粮 2048",…))`，
标识唯一；托盘菜单与桌宠右键菜单都遍历它生成「一起玩游戏」子菜单。
`create_game("bounce")` → `MiniGame`；`create_game("catch")` → `CatchGame`；
`create_game("runner")` → `Runner`；`create_game("2048")` → `Game2048`。
**2026-09-27 深夜（v2.2.0）**：从 2 款扩到 **4 款**，加游戏**只动了 `game/__init__.py` 两个地方**
（`GAMES` 加两行、`create_game()` 加两个分支），两个菜单一行没碰 —— 这套登记表扩展方式实测好用（见 F30 第六节）。
**2026-09-23（v2.0.0）**：两个游戏**结算时都发金币** ——
`GameWindow._finish()` 里调 `_award_coins()`，折算率是 `game/common.py` 的
`COIN_PER_SCORE = 10`（**10 分 = 1 金币**）；`game/__init__.py` 转出 `COIN_PER_SCORE` / `coins_for`。
**只在结算发钱**（中途关窗口不给，见 F27）。**唯一的例外是 `game/g2048.py` 的 `coins_for_tile`**
（按最大格子算，不按分数），理由见 F30 第三节。
- 证据：`smoke_test.py` 的「游戏菜单接线」段全通过；子菜单文本实测 `['弹跳得分','接狗狗','跑一跑','狗粮 2048']`，
  触发后发出的标识实测 `['bounce','catch','runner','2048']` @`3396d733`(game/__init__.py)
- 证据：`grep -n "COIN_PER_SCORE\|def coins_for\|_award_coins" game/common.py`；
  实测 `coins_for(999) == 99`、`coins_for(-5) == 0`
- 证据：`pet/tray.py`、`pet/window.py` 的菜单均为 `addMenu("一起玩游戏")` + 遍历 `GAMES`

### F10 · 接狗狗的玩法常量
`MAX_HP=5`、`PUPPY_SCORE=10`、`COMBO_STEP=5`、`COMBO_BONUS=10`、`DAMAGE_PER_HIT=1`、
`GRACE_SPAWNS=3`、`MAX_BOMB_STREAK=2`、`RAMP_TIME=75.0`；
出怪间隔 0.95→0.45s，炸弹率 0.16→0.44，下落速度 180→360 px/s（`ramp = min(1, survived/75)`）。
实测：难度 t=0 时 0.95s/0.16/162px·s⁻¹，t=75 时 0.45s/0.44/327px·s⁻¹。
**2026-09-23（v2.0.0）新增两类常量**（见 F27）：
- **骨头**：`BONE_SIZE=46`（比炸弹小一圈）、`BONE_SCORE=10`、`BONE_HEAL=1`、
  `BONE_MIN_RAMP=0.30`（难度过 30% 才可能出现）、`BONE_CHANCE=0.12`。
  `FALLER_KINDS = ("puppy","bomb","bone")`。骨头的抽取**排在"连续炸弹"规则之前**，
  不会被 `MAX_BOMB_STREAK` 连带压掉。
- **风（水平漂移）**：`DRIFT_MIN_RAMP=0.40`、`DRIFT_MAX=130.0`、`DRIFT_CHANCE=0.55`、
  `DRIFT_SPEED_MIN_RATIO=0.45`（单个落体风速取 45%~100% 的 `DRIFT_MAX`）。
  带风的落体 `edge_bounce=True` + `restitution=1.0`（撞左右墙**弹回**）。
  **骨头不给风**。
- 证据：`grep -n "^BONE_\|^DRIFT_\|^FALLER_KINDS" game/catcher.py`
- 证据：`smoke_test.py` 的「难度：出怪间隔变短 / 炸弹出现率升高 / 下落速度变快」三条
  → `0.95s -> 0.45s`、`0.16 -> 0.44`、`162 -> 327 px/s` @`c2d65504`(旧版)
- 证据：`python tools/verify_catch_items.py` → 「真帧里三种落体各 2 根骨头、2/7 个带漂移」、
  「6 根落体里 4 根撞到左右墙并弹回」
- 证据：随机 500 次出怪实测最长连续炸弹 = 2（上限 `MAX_BOMB_STREAK`），
  前 3 个必是小白狗 @`c2d65504`（本轮改动前）

### F11 · 扣血规则（实测）
* 接住小白狗：+10 分、**不**扣血、`caught` +1；连击满 5 只额外 +10（实测 4→5 时得 20 分）。
* 接到炸弹：扣 1 滴血，连击清零。
* 漏接小白狗（落到底）：扣 1 滴血。
* **炸弹落到底：不扣血**（只有"接到"才算）。
* **骨头（v2.0.0）**：+10 分，**有伤时回 1 滴血**（`BONE_HEAL=1`），满血时只加分、
  **不超上限**；漏接骨头**不扣血**（它本来就不是必须接的）。
* 血量扣光 → `over=True`，标题「血量耗尽！本局得分 N」。
- 证据：`smoke_test.py` 的「接狗狗小游戏」段对应 6 条断言全部 PASS @`c2d65504` `7424b17d`
- 证据（骨头，v2.0.0）：`smoke_test.py` 的「接狗狗：骨头与漂移」段 ——
  「骨头给分」「有伤时骨头回 1 滴血」「满血时骨头只加分不超上限」三条**
- 证据：`game/catcher.py` 的 `_on_bone()`（`heal` 终于有人调了）@`ed39e56e`

### F12 · 两个游戏互不干扰的最高分（+ 金币是共用的）
「弹跳得分」写 `cfg.best_score`，「接狗狗」写 `cfg.best_catch`，各记各的。
实测：接狗狗结算写入 `best_catch=210` 时，`best_score` 保持 80 不变。
**v2.0.0 起金币是"共用一个钱包"**：两个游戏结算都往 `cfg.coins` 里加
（`coins_for(score)`），小卖部从同一个 `cfg.coins` 扣 —— 这是有意的（钱就该是通用的）。
- 证据：`smoke_test.py` → `[PASS] 最高分写入 cfg.best_catch (best_catch=210)`、
  `[PASS] 没碰到弹跳得分的最高分 (80)` @`c2d65504` `d99338ac`(pet/config.py, 新值)
- 证据（金币，v2.0.0）：`smoke_test.py` 的「小卖部与金币」段 ——
  「结算按 10 分 = 1 金币折算」「没结算就关掉窗口不给金币」「买东西扣金币并生效」
  「钱不够买不了」全部 PASS @`2f766fef`(game/common.py)

### F13 · 游戏素材已到位
`assets/game/` 实测：`catcher_*` **8** 张、`puppy_a_*` **10** 张、`puppy_b_*` **10** 张、
`puppy_c_*` **10** 张、`bg_bounce.png` 1 张、`bg_catch.png` 1 张；**`bomb_*` 为 0**
（炸弹仍走代码画的线条卡通占位 `_draw_bomb_placeholder()`）。
- 证据：`ls assets/game/*.png | sed 's/_[0-9]*\.png//' | sort | uniq -c`
  → `8 catcher / 10 puppy_a / 10 puppy_b / 10 puppy_c / 1 bg_bounce / 1 bg_catch`
- 证据：离屏实例化 `CatchGame` 后 `len(g.puppy_sets)==3`、各套帧数 `[10,10,10]`、
  `len(g.sprites['catcher'])==8`、`len(g.sprites['bomb'])==0`、`g._bg is not None` @`c2d65504`
- ⚠️ catcher 曾一度是 **14** 张（旧素材），已换成 `#5197` 张臂那套，**只有 8 帧**。
  旧记述见 V7。

### F13b · 游戏素材的来源与复现（逐字节可复现）
4 张源 GIF 取自 `assets/raw/_library/0921_1530_线条小狗GIF/`，命令见
`assets/game/README.md` 的「这几张是怎么来的」；2026-09-21 实测四条
`prep_sticker.py` 命令的输出与 `assets/game/` 里的文件 **`cmp` 全等**。
输出画布 catcher 160×160（内容 145×129）、puppy_* 96×96（内容 80×79 / 80×78 / 81×73）。
- 证据：`prep_sticker.py <源> --state catcher --size 160 --keep 10 --out <临时目录>` 等四条，
  之后 `for f in assets/game/catcher_*.png; do cmp -s $f <临时目录>/$(basename $f); done`
  → `catcher 相同 8 / 不同 0`、`puppy_a 10/0`、`puppy_b 10/0`、`puppy_c 10/0`
- 证据：`Image.open('assets/game/*_00.png')` → `(160,160)` / `(96,96)`；`getbbox()` 如上行
- ⚠️ 这批源是爱给网**预览图**，带不透明浅灰斜排水印（58px 显示尺寸下不可见，
  2 倍放大可见）。检测方法见 `reports/README.md`。@`3076e6cb`(prep_sticker.py)

### F14 · 两张背景图规格与地平线对齐
`assets/game/bg_bounce.png` 与 `bg_catch.png` 均为 **780×580**（等于游戏窗口 `W×H`）；
游戏 `GROUND_Y = 534`。两张图由 `tools/prep_bg.py` 从
`assets/raw/_library/0921_1530_背景图/` 的 2848×1600 原图按 `--ground` 裁出，
使源图地平线落在 y=534：

| 输出 | 源文件 | `--ground` |
|---|---|---|
| `bg_bounce.png` | `1789972701282_edit_459032437780997.png` | 0.87 |
| `bg_catch.png` | `1789972756638_edit_459096029599217.png` | 0.78 |

- 证据：`from game.common import W,H,GROUND_Y` → `780 580 534`；
  `Image.open('assets/game/bg_*.png').size` → `(780, 580)`
- 证据：上表两条 `prep_bg.py` 命令输出到临时目录后 `cmp` → **与 `assets/game/` 里的逐字节一致**
  （2026-09-21 复验，此前只验到"最大像素差 = 1"）@`fa965e67`

### F15 · 小白狗套的前缀靠扫目录，不是写死的表
`game/catcher.py` 的 `discover_puppy_prefixes(root)` 扫 `puppy*.png` 去序号得前缀；
`CatchGame.__init__` 用它装 `self.puppy_sets`。空目录时退回 `PUPPY_PREFIXES`。
- 证据：`discover_puppy_prefixes(assets/game)` → `['puppy_a','puppy_b','puppy_c']`；
  `discover_puppy_prefixes(Path('__nope__'))` → `['puppy','puppy_a','puppy_b','puppy_c']`（兜底表）
- 证据：`smoke_test.py` 3 条新断言（套数 = 目录实际套数 / 每套非空 / 空目录走兜底）全 PASS @`c2d65504`

### F16 · 验收/预览工具都不会写用户的 `config.json`
`tools/render_preview.py` 的 `isolate_config()`、`tools/smoke_test.py` 的
`pcfg.config_path = lambda: tmp`，都把 `pet.config.config_path` 指向临时文件。
2026-09-23 新增的三个验收脚本（`verify_fling.py` / `verify_vitals.py` /
`verify_catch_items.py`）**都带了同一个 `isolate_config()`** ——
它们各自会实例化 `PetWindow` / `CatchGame`，`closeEvent` 里那条
`Config.save()` 不隔离就会把用户的存档覆盖掉。
**用只读锁做了确定性验证**：`attrib +R config.json` 之后跑完
`smoke_test.py` + `render_preview.py`（都正常退出、无写入报错），解锁后与锁前内容比对，
**只有 `pos_x` 差 1**（那是正在运行的桌宠自己走了一步写的），其余字段一字未变。
- 证据：`cp config.json bak && attrib +R config.json && python tools/smoke_test.py && python tools/render_preview.py && attrib -R config.json && diff bak config.json`
  → 唯一差异 `"pos_x": 1305` vs `"pos_x": 1304`
- **2026-09-23 复验（v2.0.0，把 3 个新脚本一起纳入）**：
  `cp config.json /tmp/bak && attrib +R config.json` 之后依次跑
  `verify_fling.py` / `verify_vitals.py` / `verify_catch_items.py` / `smoke_test.py`
  → **四个 exit code 全为 0，`diff` 与备份完全一致（零差异）**
  （这次连 `pos_x` 都没差 —— 因为 `config.json` 被锁住，正在跑的桌宠也写不进去）。
- 修正记录：`render_preview.py` 在加 `isolate_config()` **之前**是会写的（截结算图触发
  `_finish()` → `cfg.save()`），见 V3。
  2026-09-21 17:40 复验（`render_preview.py` / `verify_facing.py` / `verify_actions.py` /
  `verify_variants.py` 都跑过之后 `config.json` 的 md5 与跑前一致；`verify_actions.py`
  自己打印「config.json 被改动过，已还原为运行前的版本」后仍然一致）@`f981f760` `7424b17d`
- ⚠️ **新增验收脚本时务必照抄 `isolate_config()`**（照 `verify_fling.py` 第 64 行那几行走）——
  漏了不报错，只表现为"跑完测试发现桌宠位置/统计变了"。

### F17 · 素材库那批 GIF 的水印性质（决定了"怎么检测"）
`assets/raw/_library/0921_1530_线条小狗GIF/` 是爱给网的**预览图**，狗身上盖着一层
**不透明**浅灰的斜排 `aigei.com` 水印（alpha=255，与狗身同为实心像素）。
- **"半透明像素占比"检测不到它** —— `_static_light_alpha()` 的判据是 `0 < a < 200`，
  水印 a=255，直接被过滤，实测数出来的值主要来自素材自带的半透明道具（非水印）。
- 试过"静止浅灰像素占比""净空区浅灰占比（加 `MaxFilter(7)` 腐蚀）"两种改法，
  **都与人工标注对不齐**：白狗自身的抗锯齿边和水印得分几乎一样。
- **可靠做法只有看**：垫中性灰 `#8C8F96`、每格放大到 300px+、编号拼图，然后人眼过。
  这就是 `make_sheet()` / `make_strip()` 垫灰底、以及 `reports/README.md`
  建议 `--cell 320 --cols 6` 的原因。
- 影响面：58px 的游戏显示尺寸下**看不出来**，2 倍以上放大可见。故本轮**不做去水印**
  （不可靠，且属绕开站点版权标识），保留现有素材并在 README 里注明。
- 证据：`Image.open(<源>).getpixel(<水印处>)` → alpha=255、RGB 约 (200~230) 中性灰；
  `assets/game/` 放大渲染（垫灰 `#8C8F96`，每格 320px）肉眼可见斜排 `aigei`
- 证据：标注 8 个样本（#129/#050 干净，#006/#246/#222/#5207/#132 有水印）后跑两种指标，
  **均至少 1 例与标注相反**，故不作为判据。@`f0e9875c`(review_materials.py)

---

### F18 · 一个动作多套素材：命名规则与随机挑选
`pet/assets.py` 的 `_split()` 把 `<状态>_<套名>_<序号>.png` 拆成 `(套名, 帧序)`：
**最后一段永远是帧序**，倒数第二段非纯数字才算套名 —— 所以 `poke_01`（默认套第 1 帧）
不会被误当成"套名 01"。`AssetBank` 多了 `self.sets[状态] = {套名: [帧]}` 与
`set_names(state)`；`raw/count/scaled/frame` 各多一个可选 `set_name`，**不传时行为与以前
完全一致**（取默认套），老调用点不用改。

`PetWindow` 在**动作触发的那一刻**调 `_begin_action()` → `_pick_set()` 挑一套：
- 随机池**排除上一次用过的那套**（记在 `self._sprite_set[sprite]`）→ 两套素材是完美轮换，
  不会出现"点了没变"
- 动作时长按**本次选中的那一套**算：`_oneshot_seconds()` 用 `bank.count(sprite, 选中套)`
- 只有一套（或没分套）时 `_pick_set()` 返回 None，不假装随机

**哪个状态由谁触发挑套，是这块最容易记混的地方：**

| 状态 | 触发点 | 时机 |
|---|---|---|
| `poke` / `feed` | `poke()` / `feed()` 里显式调 `_begin_action()` | 点下去的那一刻 |
| `drag` | `mouseMoveEvent` 里调 | 拎起来的那一刻 |
| `walk` | `_advance()` 每帧调 `_track_state()`，比对状态 | **状态刚变成 walk 的那一帧** |
| `idle` | 不挑，永远用默认套 | —— |

`idle` 不参与：它要在状态里停好几秒，中途换套画面会跳一下。
`walk` **参与**，但只在起步那一帧挑一次、**整段行走不换**（两套帧数 8 / 14 不同，
中途换会接不上）。walk 是行为状态机自己溜达进去的，**没有任何外部事件可以挂钩**，
所以只能靠在主循环里比状态 —— 判断标准是"换套的那一帧会不会被看见"，
不是"是不是循环状态"。

- 证据：`bank.set_names('poke') == ['', 'a', 'b']`、`feed == ['', 'a', 'b']`、
  `walk == ['', 'a']`、`drag == ['']`；`_split(Path('poke_a_07.png'), 'poke') == ('a', 7)`、
  `_split(Path('poke_07.png'), 'poke') == ('', 7)`
- 证据：poke 3 套帧数 9/14/20、feed 3 套 22/18/16、walk 2 套 8/14；
  `_oneshot_seconds(State.POKE)` 随选中套给出 0.72 / 1.12 / 1.60 s（÷ FPS 12.5）
- 证据：连点 30 次（seed 20260921）→ 出现过 `['', 'a', 'b']`；12 次序列相邻两两不重复
- 证据：反复起步 8 次（seed 20260922）→ 选到 `a - a - a - a -`（`-` 表示默认套），
  相邻两次必不同；行走途中连跑 20 帧，选中的套不变
- 配套：`pet/assets.py` 另导出 `set_files(root, state, set_name)`（默认套简写
  `default_set_files(root, state)`），给预览/校验脚本按套取帧用 —— 脚本里裸
  `glob("poke_*.png")` 会把多套拼成一条（见 F7 的踩坑记录）
- ⚠️ 多套还带来一个方向问题：各套是**分开抠的图，原图朝向未必一致**，
  所以 `facing.json` 要能按套声明（见 F24）。`walk_a` 就是这么一套。
- @`16b87e8f`(assets.py) @`9ebf8f57`(window.py) @`af0a1184`(smoke_test.py)

### F19 · 多套素材的验收工具（三个）

**触发式的**（poke / feed）：`tools/verify_variants.py` —— 隔离存档后造真窗口，
poke 9 次 / feed 6 次，每次推 6 帧再 `grab()` 抓**真正画出来的那一帧**，
拼成 `reports/variants.png`（504×970），每格标注套名。
- 证据：脚本输出「逗它玩（左键单击）: 9 次里用到的套 = ['a','b','default']；
  喂一口: 6 次里用到的套 = ['a','b','default']」
- 证据：`ls -la reports/variants.png` → 235271 B；跑完 `config.json` md5 不变
- @`f3d7acd6`(verify_variants.py)

**起步式的**（walk）：`tools/verify_walk_sets.py` —— walk 没法"连点"，
**只能反复让它重新起步**：每次先 `_enter(IDLE)` + `_track_state()`（这一步不该挑套），
再 `_enter(WALK)` + `_track_state()`（挑套发生在这里），推 4 帧后 `grab()`。
三行拼图写 `reports/walk_sets.png`（1098×588）：① 现在的 idle 连续帧、
② 六次起步各一帧（标出这次用的套）、③ 非默认套自己的连续帧。
- 证据：脚本输出「walk 可选的套：['', 'a']」「六次起步选到：a default a default a default」
- 证据：`ls -la reports/walk_sets.png` → 243058 B（2026-09-22 傍晚改朝向前后差 3 B，
  因为图里那两帧真的跟着翻了一次 —— 这条也能当"朝向改动生效了"的旁证）
- @`79681ced`(verify_walk_sets.py)

**朝向的**（逐套）：`tools/verify_facing.py` —— 走路有几套就验几套，
每套渲染"向右走 / 向左走"两帧并与该套的**原图 / 水平镜像**比像素，
出 `reports/facing_fix.png`（2026-09-22 傍晚由 2×2 单套版扩成逐套版，109192 → 214808 B）。
任一方向对不上就打印"反了"并返回退出码 1。**声明填得对不对它证明不了**（见 F6 / F24）。
- 证据：脚本输出「套「默认套」声明朝左（跟随目录默认）=> 正确；
  套「a」声明朝右（按套覆盖）=> 正确；结论：验收通过：2 套都「走哪边就朝哪边」」
- @`a325e9a0`(verify_facing.py)

### F20 · 两个游戏窗口共用 `game.common.GameWindow` 底座
`class GameWindow(QWidget)` 定义在 `game/common.py`，`MiniGame` 与 `CatchGame` 都继承它。
底座持有一局结束的信号与全部"两个游戏必须一样"的部分：

- `closed = Signal(int)`（参数为本局得分）；`main.py` 靠它解除桌宠暂停
- `TITLE` / `OVERLAY_TITLE` 两个类属性决定窗口标题与结算标题
- 16ms 精确计时器（`_tick` 里 `dt = min(0.05, max(0, now-last))`；`start_clock()` 由子类
  在场景建好后显式调，避免计时器在 `_reset_scene()` 之前滴答）
- 结算浮层的 `_build_overlay` / `_center_overlay` / `_restart`、`resizeEvent` / `showEvent`
  / `closeEvent`（关窗时 `_timer.stop()` + `closed.emit(self.score)`）、`keyReleaseEvent`
- 模板方法 `_advance(dt)`：先 `_countdown`（回合规则，默认空）→ 再看 `over` 决定
  `_settle`（停住）还是 `_step`（物理）→ 最后统一 `_decay`（衰减/粒子）+ `update()`
- 子类**必填**钩子：`_step(dt)` 与 `_reset_scene(first)`（都是 `raise NotImplementedError`）

- 证据：`"closed" in GameWindow.__dict__` → True；`"closed" in MiniGame.__dict__` →
  False；`issubclass(MiniGame, GameWindow) and issubclass(CatchGame, GameWindow)` → True
- 证据：`smoke_test.py` 的「离屏渲染」段新增 9 条断言全 PASS（见 F4）
- 证据：`_settle` 的参数名必须与底座一致（都叫 `dt`）—— 子类改叫 `_dt` 会被 pyright 判为
  `Method "_settle" overrides class "GameWindow" in an incompatible manner`（已实测遇到过）
- 证据：重构后完整链复跑通过 —— 冒烟 134/0（截至 2026-09-22 夜已增至 159/0，见 F4）、预览 7 张产物、`verify_facing` 「走哪边就朝哪边」、
  `verify_actions` 12 张连拍、`verify_variants` 三套都在用；两套内置风格都仍能各生成 27 张
- @`cc6ed772`(common.py) @`db587c26`(minigame.py) @`c2d65504`(catcher.py) @`ea223241`(main.py)
  @`4be2ba5b`(game/__init__.py)

### F21 · 类型检查基线：pyright 全绿
用 pyright（Pylance 的同一套引擎）扫 `main.py game pet tools`：
**52 errors → 0 errors, 0 warnings, 0 informations**（2026-09-21 17:40）。
- 证据：`node <...>/node_modules/pyright/index.js --pythonpath <venv python> main.py game pet tools`
  → `0 errors, 0 warnings, 0 informations`
- 复现入口：`tools/typecheck.py`（默认就查这四个范围；没装 pyright 时打印安装命令并返回 0）。
  pyright 装在托管 node 目录：`~/.workbuddy/binaries/node/workspace`（v1.1.414），**没走 `npm i -g`**
- 清掉的几类（都不改运行时行为）：
  1. `Image.LANCZOS/NEAREST/BICUBIC/AFFINE` → `Image.Resampling.*` / `Image.Transform.AFFINE`
     （19 处，Pillow ≥9.1 的现代写法，常量值相同）
  2. PIL 桩把 `Image.load()` / `getdata()` / `getextrema()` 标得含糊（可能是 None /
     DeferredError），导致取值、解包、迭代全被误报 → 在 `pet/icon.py`、
     `tools/{prep_sticker,review_materials,verify_facing}.py` 里用 `Any` / `cast` 收口
  3. `getbbox()` 可能返回 None（**全透明帧会真的 None**）：`tools/render_preview.py` 加了
     fallback —— 真出问题时不崩，图里那一格直接是空的
  4. `tools/prep_sticker.py` 的 `base` / `uy0` 只在 `if motion == "keep"` 里赋值，
     取值在另一个同类 if 里 → 先给默认值（潜在 UnboundLocalError）
  5. `tools/verify_facing.py` 的 `min(d, key=d.get)` → `key=lambda k: d[k]`；
     `tools/review_materials.py` 的 `if not cnt` → 补 `or top is None or bot is None`
- 证据：`tools/typecheck.py` 输出 `[类型检查] 通过：0 error`

### F22 · 素材存放位置：四层结构（换素材前先看这条）
`assets/` 与 `custom_pet/` 是**两套完全不同的东西**，这是最容易混的一处：

| 位置 | 内容 | 谁会读它 |
|---|---|---|
| `custom_pet/` | 161 张 png + `facing.json`（现役成品） | **程序运行时唯一在读的** |
| `assets/pet/` | 内置素材位，**当前为空（只有 README）** | 只在 `custom_pet/` 里没有 png 时才读 |
| `assets/game/` | 小游戏素材（40 张） | 小游戏读（`%APPDATA%\DesktopPet\game\` 不存在时） |
| `assets/raw/` | 原始素材仓库 | **不参与运行**，只给人挑素材用 |

`assets/raw/` 内部（2026-09-22 傍晚实测；两个归档目录本日改过名，见 F26）：

| 子目录 | 数量 | 是什么 |
|---|---|---|
| `_library/0921_1530_线条小狗GIF/` | 200 个 GIF | 选材总库（爱给网批量下载的那批） |
| `_library/0921_1530_背景图/` | 2 张 png | 游戏背景原图 |
| `_archive/` | 3 个 GIF | 加工完的原始输入留档（`0921_1228/` 已被误删）**原名 `_done/`** |
| `_snapshots/` | 186 个文件（182 png） | 历史成品快照 + 原图已丢的那几套 **原名 `_recovered/`** |
| `inbox/` | 1（只有 `.gitkeep`） | 投递口，`tools/intake.py` 从这里取 |

优先级的**唯一实现**在 `pet/paths.py`：`resolve_asset_dir("pet")` 看 `user_asset_dir("pet")`
（= `data_dir()/custom_pet`）里有没有匹配 `*.png` —— **有一个就整体接管**
（不是合并；缺的状态才借 `idle` 兜底）。登记表是 `ASSET_KINDS`，**加一类素材只加一行**。
`data_dir()` 在冻结后是 `%APPDATA%\DesktopPet`、开发时是项目根目录，
所以源码树里的 `custom_pet/` 就是运行时那一个。
- 证据：`ls -1 custom_pet/*.png | wc -l` → 161；`ls "$APPDATA/DesktopPet"` → 不存在
- 证据：`grep -n "def resolve_asset_dir" -A 8 pet/paths.py` @`17a44b33`(paths.py)
- 加工链：`_library` 挑 GIF → `tools/prep_sticker.py` 拆帧/抠底/缩到 128 → 写进 `custom_pet/`。
  **换素材全程不用改代码**（只有换"状态"才动代码）。

### F23 · 「坐板凳」那套素材的来源与原图状态
`idle` 现在那 17 帧来自 `assets/raw/_snapshots/线条小狗晃脚脚2_idle/`
（奶油色小狗坐木长凳晃腿、闭眼微笑、红项圈）。

**它的原始 GIF 已经不存在了**：归档在 `_archive/0921_1228/`，随那次误删一起丢失；
复查过 `Downloads/` `Desktop/` `Documents/` `Pictures/`，没有副本
（`Downloads/线条小狗GIF/` 是个空目录）。
- 证据：`find /c/Users/华硕/{Downloads,Desktop,Documents,Pictures} -iname "*线条小狗*"`
  → 只剩 `线条小狗 (561)` / `可爱线条小狗喂一口` / `线条小狗 (160)逗他玩` 三个
- 证据：`_snapshots/README.md` 原文表格「`线条小狗晃脚脚2_idle/` | 奶油色小狗坐板凳晃腿 | `idle` | 17」
- **原图丢了 ≠ 不能用**：`custom_pet/` 里跑的所有素材本来就是 128px，
  这份 128px 加工版与它们**同规格**，重摆一次不会更糊。
- 重摆参数：`tools/rebuild_from_snapshot.py`，默认 `×1.26`。
  那批帧当年为迁就木凳的包围盒被压在 `scale 0.678`，**狗本体只有约 75 高**
  （其它状态的主体都在 100 上下）。1.26 是「不裁到木凳」的上限：
  并集宽 100 × 1.26 = 126 ≤ 128，狗本体回到约 94，与 walk 的 100 齐平。
- 证据：最大连通域量各状态**主体**高 —— idle 103 / walk 100 / drag 100 / poke 109 /
  feed 109 / poke_b 98 / feed_a 99 / feed_b 99 / **坐木凳 90（其中约 20px 是凳子）**。
  注意判大小的依据是"狗本体"而非"狗+道具"的并集，否则凳子会把狗挤小。
- 证据：`python tools/rebuild_from_snapshot.py --dry-run`
  → `[计划] idle ← 坐木凳 ×1.26 (100x91 → 126x115，贴入 (1, 7))`；脚本幂等，可反复跑

### F24 · 按套声明朝向（一个动作多套素材时，方向未必一致）
`facing.json` 除了 `base`，还认一个 **`sets`**（按素材**前缀**覆盖）：

```json
{ "base": "left", "sets": { "walk_a": "right" } }
```

查的时候统一走 `pet/facing.py` 的 `base_for(base, sets, state, set_name)`；
窗口层每帧只做一次 dict 查表（缓存在 `self.face_sets`，**绘制循环不读盘**）。

- 为什么 key 用**前缀**而不是裸套名：套名 `a` 在 `walk_a` / `poke_a` / `feed_a`
  里是重名的，裸套名一定互相串台。`facing.prefix(state, set_name)` 负责拼。
- 触发原因：`walk_a` 就是那套**原图朝右**的素材（前爪朝右举起、小尾巴甩在左下），
  装进这个"整体朝左"的目录后，`base=left` 让它**永远被镜像反了 → 倒着走**。
  它原来当 `idle` 用，站着不动时不容易察觉；2026-09-22 挪去当走路素材后暴露。
- 反查证据（那一刻桌面显示的到底是原图还是镜像）：
  `屏幕截图 2026-09-22 155557.png` 与 `walk_a` 14 帧的原图/镜像逐帧比像素 →
  **原图最小差 159.52（walk_a_07）/ 镜像最小差 169.89（walk_a_00）** → 当时显示的是原图。
- 改法：`tools/set_facing.py flip --set walk_a`；`<value> --set <前缀>`；
  值改回与默认一致时**自动把那一条删掉**（不保留冗余声明）。
- 右键菜单 `左右翻向` 会**连 `sets` 一起翻**（只翻 base 会把相对关系翻没）。
- `facing.write(..., sets=None)` 默认**原样保留**文件里已有的 `sets`
  （不然只想改总朝向，却把某套的声明顺手抹了）；传空 dict 才清空。
- 验收：`tools/verify_facing.py` 改成**逐套**验（走路有几套就验几套），
  出 `reports/facing_fix.png`，任一套对不上就退出码 1。
- 证据：`tools/verify_facing.py` 输出
  「套「默认套」声明朝左（跟随目录默认）=> 正确；套「a」声明朝右（按套覆盖）=> 正确；
  结论：验收通过：2 套都「走哪边就朝哪边」」
- 证据：`tools/set_facing.py` → 「默认朝向 朝左 / 按套 walk_a -> 朝右 /
  [默认套] 向右走要镜像 / [walk_a] 向右走不镜像」
- 证据：冒烟测试里含 10 条按套断言（见 F4）
- **素材 PNG 一个字节都没动**；`custom_pet/facing.json` 是唯一被改的数据文件
  （改前副本在 `assets/raw/_snapshots/pre_0922/facing.json`）。
- @`0890187f`(facing.py) @`9ebf8f57`(window.py) @`16b87e8f`(assets.py)
  @`a469a5e4`(set_facing.py) @`a325e9a0`(verify_facing.py) @`af0a1184`(smoke_test.py)
- 甄别办法（下次找素材直接可用）：把候选帧与 `custom_pet/` 的帧都归一化到 96×96 比像素差，
  最小的就是同一套。实测用户截图与 `idle_08.png` 差异 **58.17**，第三名（drag_12）74.47 ——
  差一个档位就能分辨，不用肉眼猜。
- @`95e3a98b`(rebuild_from_snapshot.py)

### F25 · 「重力下坠」开关（2026-09-22 夜从"点了没用"修成真的管用）
**症状**：右键菜单 / 托盘菜单里勾不勾「重力下坠」，宠物都照样往下掉。

**根因**（一行）：`pet/window.py` 的重力判定写成了

```python
use_gravity = bool(self.cfg.gravity) or not self.body.on_ground   # ← 错
```

`or not on_ground` 的意思是"脚一离地就再补一次重力"。而下坠中的宠物**必然**脚不沾地
（`physics.Motion.update` 里 `y < floor` 就置 `on_ground = False`），
于是这个 `or` 在**唯一需要它的场景里恒为真**，把整个开关架空了。
在地面上时两个分支都给 False，看不出区别 —— 所以这个 bug 从外部看就是"开关完全无效"。

**改法**（1 处判定 + 3 处连带，都在 `pet/window.py`）：

| 位置 | 改动 | 为什么必须连带 |
|---|---|---|
| `_advance` | `use_gravity=bool(self.cfg.gravity)` | 只认设置本身 |
| `mouseReleaseEvent` | `brain.drag_end(gravity=bool(self.cfg.gravity))` | `FALL` 只认"落地"这一个出口，没重力就永远出不来，松手会卡在半空演下坠 |
| `poke` | 起跳条件加 `and self.cfg.gravity` | 没重力就没有回落，`throw(0,-430)` 会让它一路飘到天花板 |
| `set_gravity` | 关掉时除清 `vy` 外，若正处于 `FALL` 则 `brain.stop_falling()` | 正掉到一半被关掉重力时，就地冻住而不是继续演完 |

`pet/behavior.py`：`drag_end(*, gravity=True)`（默认值保证老调用行为不变）+
新增 `stop_falling()`（无条件回 `IDLE`）。

- 语义定死：**不勾 = 不下坠**，拖到哪儿松手就悬在哪儿；单击不再往上蹦；
  再勾回来接着往下掉。`on_ground` 由 `physics` 每帧照常维护，与开关无关。
- 证据（冒烟 9 条，见 F4）：起点 y=83 →
  勾选 1.0s 后 y=647（下坠 564px）、不勾 y 恒为 83（Δ=0）、
  第 9 帧改不勾后停在 y=193（Δ=110px）。
- 证据（真帧图）：`tools/verify_gravity.py` → `reports/gravity_switch.png`，
  三排分别是勾选 / 不勾 / 中途改，每排贴 `grab()` 抓的真帧，纵轴是真实屏幕高度；
  连跑两次 md5 一致（`6c7bbab7cfbe0e32f5d1f9b24509589a`，192761 B）。
- 证据：`config.json` 跑前跑后 md5 一致（脚本用临时存档路径，且只 `hide()` 不 `close()`）。
- ⚠️ 这是"布尔开关被 `or` 条件架空"的典型样本：**开关的判定里不能再掺入运行时状态**，
  否则那个状态一旦与原条件相关（这里 `on_ground` 与"正在下坠"天然互锁），
  开关就永远被短路。同类风险点：`auto_walk`（判定只看 `cfg.auto_walk`，干净）。
- @`7351dc7c`(window.py) @`f9e2e895`(behavior.py) @`84631331`(smoke_test.py)
  @`6093c6a7`(verify_gravity.py)

### F26 · 删除自绘素材 + 抽出三个登记表 + 素材库改名（2026-09-22 傍晚）
用户要求：**删掉"代码画"的那套素材**（保留全部 GIF 素材），并把代码结构与素材库结构
整理成"易于加新功能、加新素材"。

**一、删除的（自绘素材与生成器）**

| 删除对象 | 说明 |
|---|---|
| `pet/assetgen.py` | 风格 classic：奶茶色小狗（22 帧几何生成） |
| `pet/assetgen_line.py` | 风格 line：线条小狗（解析剪影 + 形态学描边） |
| `pet/styles.py` | 风格注册表 + `load()` / `names()` |
| `tools/gen_assets.py` | 生成入口（`--list` / `--style` / `--force`） |
| `tools/make_fixtures.py` | 造假素材（回归验证 intake 用） |
| `tools/fixtures/` | 上述假素材的产出（14 个文件） |
| `assets/pet/*.png` | 21 张内置 PNG（保留 README.md） |
| `.style_cache/` | `render_preview.py` 的两风格对比缓存 |
| `reports/preview_styles.png` | 两套自绘风格的对比图（已无法再生成） |

**没动的**：`custom_pet/` 161 张（F1 仍成立）、`assets/game/` 40 张、`assets/raw/` 全部
（`_library` 200 GIF / `_snapshots` 186 / `_archive` 3）。
- 证据：删除后 `ls assets/pet/` → 只有 README.md；`ls -1 custom_pet/*.png | wc -l` → 161
- 证据：`find . -name "assetgen*" -o -name "gen_assets*" -o -name "styles.py"` → 空

**二、抽出的三个"登记表"（单一来源）**

| 单一来源 | 原来各抄一份的地方 | 覆盖的东西 |
|---|---|---|
| `pet/behavior.py` 的 `State`（+ `KEYS`） | `assets.STATES`、`prep_sticker.VALID_STATES`、`behavior.SPRITE`（已删） | 动作名 / 贴图前缀 |
| `pet/paths.py` 的 `ASSET_KINDS` | `config.pet_asset_dir()` / `game_asset_dir()` / 两处手写 `data_dir()/"custom_pet"` | 素材类别与两套目录 |
| `pet/menu.py` 的 `TOGGLES` | `window._build_menu` 与 `tray.update_menu` 各写一遍的三个开关 | 菜单开关项 |

配套改动：`Config.style` 字段删除（自绘没了，风格概念不再存在）；
`main.py` 的 `ensure_assets()` 改成 `check_pet_assets()`（**只提示，不生成**）；
`tools/render_preview.py` 删 `make_style_compare()` 与 `.style_cache` 用法；
`tools/smoke_test.py` 素材段改为临时目录现造纯色 PNG（见 F4）；
`.vscode/tasks.json` 删 3 个调用 `gen_assets.py` 的任务。
- 证据：`grep -rn "gen_assets\|assetgen\|pet.styles\|style_cache\|fixtures" --include=*.py .` → 无匹配
- 证据：`python tools/typecheck.py` → `0 errors`；`python tools/smoke_test.py` → `通过 151 项，失败 0 项`
- 证据：`python -c "import json;json.load(open('.vscode/tasks.json',encoding='utf-8'))"` → OK，18 个任务

**三、素材库改名（用户确认后执行，只改名不删文件）**

| 原名 | 新名 | 理由 |
|---|---|---|
| `assets/raw/_done/` | `assets/raw/_archive/` | "加工完的原始输入归档"，原名看不出含义 |
| `assets/raw/_recovered/` | `assets/raw/_snapshots/` | "历史成品快照"，原名的"recovered"像是异常状态 |
| `tools/rebuild_from_recovered.py` | `tools/rebuild_from_snapshot.py` | 跟着上面的名字走 |

同步改了 11 个文件的引用（`.gitignore` / `FACTS.md` / `README.md` / `.vscode/tasks.json` /
`custom_pet/README.md` / `reports/README.md` / `tools/intake.py` / 该脚本自身 /
`assets/raw/README.md` / `_snapshots/README.md` / `_snapshots/pre_1550/README.md`）。
`intake.py` 的常量 `DONE` 一并改名 `ARCHIVE`（代码名与盘上目录名对齐）。
- 证据：`grep -rn "_done\|_recovered\|rebuild_from_recovered" --include=*.py --include=*.md .` → 无匹配
- 证据：`ls assets/raw/` → `README.md _archive _library _snapshots inbox`

**四、给"加东西"留的入口**（README「怎么扩展」一节）
加动作 = `State` 加成员 + 挂交互；加素材套 = 按命名丢文件（不改代码）；
加开关 = `Config` 字段 + setter + `TOGGLES` 一行；加素材类别 = `ASSET_KINDS` 一行；
加游戏 = 继承 `GameWindow` + `GAMES` 一项。

**五、版本号与 `CHANGELOG.md`（本项新增）**
新增 `CHANGELOG.md`：从 v0.1.0（起步）到 v1.0.0（本次架构定型）逐条记录，
每条写"为什么改 / 改了什么 / 怎么验证的"，另附「开发过程回顾」。
`pet/__init__.py` 的 `__version__` 由 `0.1.0` 升到 **`1.0.0`**。
两处版本号由冒烟测试的「版本号」段盯着（见 F4 末条）：
读 `CHANGELOG.md` 第一条 `## vX.Y.Z` 与 `__version__` 比对，不一致就 FAIL。
新增 `assets/README.md`（素材库总索引）。
- 证据：`grep -m1 "^## v" CHANGELOG.md` → `## v1.0.0 — 2026-09-22 晚 · 架构定型`
- 证据：`grep -n "__version__" pet/__init__.py` → `1.0.0`
- 证据：`ls *.md assets/*.md` → `CHANGELOG.md FACTS.md README.md` + `assets/README.md`

- 时间线（本日，从早到晚）：idle 换"坐板凳" → walk 两套轮播 → walk_a 按套朝向 →
  重力开关修真 → **本轮：删自绘素材 + 三登记表 + 素材库改名 + 加 CHANGELOG**。

### F27 · v2.0.0 五大玩法：甩出去 / 养成状态 / 金币小卖部 / 接狗狗道具 / 番茄钟（2026-09-23 午）
用户要求：**在不动原有项目结构的前提下，把五个玩法加进去**（其中前四个是"代码写好了但从没接线"的半成品，
第五个是全新），并把这次更新记进版本更新文件。

**一、五个玩法各自接的是哪根线**

| 玩法 | 原来是"半成品"还是"没有" | 本轮接了什么 |
|---|---|---|
| 甩出去 | `physics.Motion.throw()` / `edge_bounce` / `restitution` **从没被调用** | `VelocitySampler` + `clamp_fling` + `window` 的 `_start_fling` / `_end_fling` |
| 养成状态 | `Config.feed_count` / `play_count` 是**死计数器**（存了没人读） | 新增 `pet/vitals.py`：饱食/心情/精力 + 离线衰减 + 阈值；新增 `State.SLEEP` |
| 金币小卖部 | **没有** | `game/common.py` 的 `COIN_PER_SCORE=10` / `coins_for()`；`pet/menu.py` 的 `SHOP` |
| 接狗狗道具 | `CatchGame.heal()` 写好了没人调；`Faller` 水平速度恒为 0 | 新增 `bone` 落体（给分+回血）；`_give_drift()` 给落体加风、撞墙反弹 |
| 番茄钟 | **没有** | 新增 `pet/pomodoro.py` + 右键/托盘子菜单 + `pomodoro_done` 信号 → 托盘气泡 |

**二、新增/改动的模块**

| 文件 | 性质 | 要点 |
|---|---|---|
| `pet/vitals.py` | ★新增 | 纯逻辑无 Qt。醒着每分钟 `-0.21/-0.16/-0.28`（饱食/心情/精力）；**睡着时精力 `+6.0`、心情 `+0.18` 回升，饱食 `-0.20` 降得慢**；离线每小时 `6.0`、下限 `30.0`、上限 `12h`；阈值 `HUNGRY_AT/SAD_AT=30`、`TIRED_AT=25`、`RESTED_AT=82` |
| `pet/pomodoro.py` | ★新增 | 纯逻辑无 Qt。`tick(dt)` **只在到点那一次**返回 `True`；`progress` / `label` / `total_minutes` |
| `pet/physics.py` | 改 | `VelocitySampler`（丢超过 `FLING_WINDOW=0.14s` 的旧点）、`clamp_fling`（`FLING_MIN=130` / `FLING_MAX=2200`）、`FLING_RESTITUTION=0.18` |
| `pet/behavior.py` | 改 | 新增 `State.SLEEP` + `FPS["sleep"]=4.0`；`Brain.update` 新增 `rested` 参数（**滞回出口**）；`WAKE_HOLD=25.0`；`start_seek`/`update_seek`（`SEEK_ARRIVE_PX=10`） |
| `pet/config.py` | 改 | 新增 `satiety/mood/energy`（初值 78）、`coins=0`、`last_seen`；`now_stamp()` / `hours_since()` |
| `pet/menu.py` | 改 | `SHOP`（肉干12/玩具球18/豪华大餐30）、`POMODORO_CHOICES=(25,50)`、`add_vitals` / `add_shop` / `add_pomodoro` |
| `pet/window.py` | 改 | `_tick_vitals`、`_steer_if_hungry`、`start/stop/_tick_pomodoro`、`_ring`、`buy()`、`_play_gift` |
| `pet/tray.py` | 改 | 托盘菜单也带金币/养成项 + 小卖部/番茄钟子菜单 |
| `game/common.py` | 改 | `COIN_PER_SCORE` / `coins_for()` / `GameWindow._award_coins()`（**只在结算时发钱**）|
| `game/minigame.py` `game/catcher.py` | 改 | `_finish()` 调 `_award_coins()`；catcher 另加骨头与漂移 |

**三、踩到并修掉的真 bug：睡眠抖动（滞回缺失）**

第一版 `energy < 25` 睡、`energy > 25` 醒 —— **同一个阈值进出**，睡 1 帧醒 1 帧。
`verify_vitals.py` 跑 36 小时**抖出 1052 次睡眠**（曲线上是一团噪声）。
根因：`RESTED_AT=82` 这个常量**定义了但没人用**。
改法：`Brain.update()` 加 `rested` 参数，`SLEEP` 出口从"不累了"改成"睡饱了"，
`window.py` 传 `self.vitals.rested`。修完 → **36 小时 10~11 觉、每觉约 10 分钟**。
- 证据：`python tools/verify_vitals.py` → 「完全不管：…自主睡了 10 觉，共 1.6 小时」/
  「定期照顾：…自主睡了 11 觉，共 1.8 小时」
- 证据（实测曲线）：完全不管 → 饱食最低 0（第 4 小时开始饿）、心情最低 0（第 5 小时开始蔫）、
  精力最低 25（第 17 小时开始困）；定期照顾 → 饱食最低 40、心情最低 49、精力最低 21（**都没饿过蔫过**）

**四、`sleep` 素材的来源（反查确认，非推测）**

从素材库 198 个 GIF 里挑出睡觉那一套，落 `custom_pet/sleep_00..21.png`（**22 帧**）。
来源用**像素反查**定死：拿现役帧当模板逐帧比对全部 198 个 GIF，
`xian_tiao_xiao_5191_线条小狗C (13).gif`（250×250 / **22 帧**、**黑底**）平均绝对差 **7.17**，
第二名 **46.8** —— 且帧数正好也是 22，无歧义。
缩放比是**自动算**的 **0.7436**（趴卧姿势并集 156×92，宽度成限制维度），内容是 **112×62**。
复现命令与残余差异见 `custom_pet/README.md`。
- **朝向无需单独声明**：放大对图（`reports/materials/sleep_facing_check.png`）确认
  原图**脸在左**，与 `custom_pet/facing.json` 的 `base="left"` 一致 ——
  所以 `sets` 里**不用**加 `sleep`（F24 那套"按套覆盖"这次不触发）。
- ⚠️ 源 GIF 是爱给网**预览图**，带浅色斜排水印（与 F13b 同一批素材的性质）。
  成品 112×62、实际显示约 96px 宽，水印在正常观看距离下不可见；放大看才有。
- 证据：`ls custom_pet/*.png | wc -l` → 183（v1.0.0 时 161，+22）
- 证据：`ls custom_pet/sleep_*.png | wc -l` → 22
- 证据：`ls reports/materials/sleep_facing_check.png` → 存在（放大单帧 + 水平镜像对照）

**五、版本号与文档**

`pet/__init__.py` 的 `__version__`：`1.0.0` → **`2.0.0`**（大改动：三个新模块 + 行为可感）。
`installer.iss` 的 `#define AppVer` 同步到 `2.0.0`。
`CHANGELOG.md` 新增 v2.0.0 大条目（本节即其事实底稿）；`README.md`「怎么玩」补五大玩法、
「目录结构」补新模块、「测试」补 3 个验收脚本、「怎么扩展」补加商品/加番茄钟档/调养成手感；
`custom_pet/README.md` 补 `sleep` 来源与复现；本 FACTS 新增 F27 / F28 与 V12。
- 证据：`grep -m1 "^## v" CHANGELOG.md` → `## v2.0.0 — 2026-09-23 午 · 五大玩法…`
- 证据：`grep -n "__version__" pet/__init__.py` → `2.0.0`
- 证据：`grep -n "AppVer" installer.iss` → `#define AppVer "2.0.0"`
- 证据：`python tools/typecheck.py` → `0 errors, 0 warnings, 0 informations`
- 证据：`python tools/smoke_test.py` → `通过 234 项，失败 0 项 / 全部通过`

### F28 · 甩出去（拖拽投掷）的参数与实测轨迹（2026-09-23）
**判定只看松手瞬间的手速，不看拖动距离**：`VelocitySampler` 按时间戳估速，
松手时 `clamp_fling` 把速度夹进 `[130, 2200]`；低于下限当"轻放"（不进 FALL 带速），
高于上限截断。关掉「重力下坠」开关时**一律不甩**（开关优先级高于手速）。

实测（`tools/verify_fling.py`，`QMouseEvent` 合成的真实鼠标序列，800px 宽离屏屏）：

| 松手方式 | 估到的松手速度 | 真飞出去？ | 撞墙 | 落地耗时 |
|---|---|---|---|---|
| 轻轻放 | 低于 `FLING_MIN` | ✗ | 0 | —— |
| 正常一甩（往左） | ≈ `-640 / -160` | ✓ | 0 | 1.02s |
| 使劲甩（往右） | ≈ `+2134 / -536` | ✓ | **1**（撞右墙弹回） | 1.35s |
| 使劲甩 + 关掉重力 | `0 / 0` | ✗ | 0 | 未落地（悬停） |

- ⚠️ **速度值每跑一次会小幅浮动**（手速靠真实时钟采样），
  所以 `reports/fling_throw.png` **不是逐字节可复现的产物**，只能看趋势。
- 证据：`ls -la reports/fling_throw.png` → 632×1054
- 踩坑记录：验收脚本第一版只调了 `pet.body.teleport()`、没调 `pet.move()`，
  于是松手时 `_sync_from_window()` 把 body 拉回**窗口的旧位置**，轨迹全废（0.08s 就落地）。
  加 `_place()` 同时移动 body 与窗口后才真实。

### F29 · v2.1.0 四项改进：自定义番茄钟 / 背包 / 状态面板 / 打砖块重做（2026-09-27 傍晚）
用户要求：**在原有基础和代码结构上**改四处，并**先不写新游戏的代码**。

**一、四处改动各自的问题与接法**

| 改动 | 原来的问题 | 本轮接了什么 |
|---|---|---|
| 番茄钟自定义时长 | `POMODORO_CHOICES=(25,50)` 按**分钟**写死两档，表达不了 45 秒 | `pomodoro.py` 单位改**秒**；新增 `wheel.py`（纯逻辑规则）+ `wheel_dialog.py`（自绘三列滚轮）|
| 背包 + 金币显示 | `buy()` **直接抬状态** —— "买了"和"吃了"是同一件事，金币只在商店里可见 | 新增 `bag.py`（纯逻辑）+ `panel.py` 的 `BagPanel`；`buy()` 改为只进背包，新增 `use_item()` |
| 状态更显眼 | 三个数值只在 `menu.add_vitals()` 一处显示，不进菜单就看不见 | `panel.py` 三个显示面：`BagPanel` / `StatusBubble`（划过弹出）/ 托盘 tooltip |
| 打砖块"太无聊" | 每块**一碰就碎** → 最优打法就是贴着一个地方反复跳，位置/时机/高度全不参与决策 | `minigame.py` 重做：耐久 + "敲不穿=墙" + 连击倍率 + 掉落道具 + 轮次递增 |

**二、滚轮的三条联动规则**（`wheel.py` 的 `_settle()`，纯逻辑、可单测）

| 情况 | 规则 | 为什么 |
|---|---|---|
| `h=0 且 m=0` | 秒列 1..59 | **滚不到 0** —— 最短就是 1 秒（区间下界由需求给定）|
| `h < 2` | 分、秒列 0..59 | 上限是 2 小时，下面的位随便填 |
| `h = 2` | 分、秒**只剩 0** | 于是滚到 2 小时会自动把分秒清零，`2:30:50` 这种超过上限的组合**不存在** |

- 证据：`tools/smoke_test.py` 的「滚轮时长选择器」段 ——
  `把「时」滚到 2 会连带把分秒清零（2:30:50 这种组合不存在）(7200.0)`、
  `此时分、秒两列都只剩 0 这一个值（滚不动了）`、`滚回 1 小时后分秒停在 0`、
  `值不在本列范围里时忽略掉，不会把滚轮弄成非法状态 (7200.0)`
- 证据：`tools/smoke_test.py` 的「新增界面」段 ——
  `鼠标滚轮能推动滚轮（下滑 = 数值增大）(2730.0 -> 6330.0)`（合成真实 `QWheelEvent`）

**三、买 / 用的两段式（金币与背包的一致性）**

`buy()`：扣金币 → `bag.add(key)` → 存盘 → 发 `notify`。**不动状态**。
`use_item()`：先 `bag.take(key)`（**不够整笔失败**）→ 再抬状态 → 存盘 → `_play_gift` → 发 `notify`。

- **顺序不能反**：反了会出现"状态已经涨了、东西还在背包里"的白送。
- 证据：`tools/smoke_test.py` 的「小卖部与金币」段 —— `买下扣掉相应金币`、
  `买下之后状态一点没动（v2.1.0：买 ≠ 用）`、`买下的东西进了背包`、
  `点背包里的东西才抬状态`；「背包」段 —— `不够就整笔失败（不做"扣到 0 为止"）` 等。
  v2.0.0 的旧断言「买下真的抬了对应的值」**已作废**（见第三节 V13）。

**四、弹跳得分的核心改动：敲不穿 = 墙**

| 规则 | 实现 |
|---|---|
| 球从下面顶到**没敲碎**的方块 | `vy = max(260, abs(vy) * 0.55)` —— **被挡回来** |
| 敲碎了那块 | 方块出局，**球的 vy 一个字节都不动** → 连穿上面几排 |
| 从上面踩到没碎的方块 | `vy = -max(340, abs(vy) * 0.60)` —— 借力弹起 |

- 方块耐久 `hp_for(row) = BASE_HP + (轮次-1) + (ROWS-1-row)`，封顶 `MAX_HP = 6`。
- 连击 `combo_mult()`：3 连 ×2、6 连 ×3；**唯一的清零条件是落地**。
- 分数重定：`SCORE_PER_HIT = 5`（旧版"碎一块 10 分"）。**不调就会通胀** ——
  一块最多敲 6 下，总分翻几倍，而 `COIN_PER_SCORE=10` 是按"打一局够买一两样"定的。
- 起跳 `JUMP_V` `1000 → 1060`：旧值只到 250px（球顶 220），卡在"刚够到最上排，
  位置稍偏就摸不到"，那会让"上面那排敲不到"变成说不清是技术还是运气的事。
  1060 → 281px（球顶约 189），对最上排（y=232）留 40 多像素余量。
- 加时天花板 `MAX_TIME = ROUND_TIME + 45`：没有它，手气好的一局能拖到十分钟。
- 证据：`tools/smoke_test.py` 的「弹跳得分 · 耐久 / 连击 / 道具」段（30 条），
  含 `没敲碎的方块把球挡回来（顶到的是底面）(vy=495)`、
  `敲碎之后球原样继续往上（不被弹回，连击就来自这里）(vy=-880)`、
  `从上面踩到没碎的方块 → 借力弹起 (vy=-420)`、
  `全盘都是墙时，球过不了最下面这一排 (最高 y=336，下排上沿 y=316)`、
  `下排能敲穿时，球能顶到上一排（这就是连击的来路）(最高 y=290，落在 274~316 之间)`、
  `改完耐久之后金币量级没变（一局仍够买最贵的那样）(一局 180~540 分 → 18~54 金币)`。
- 测试中踩到并记下的一个坑：那条"跳一次"的用例一开始老是失败，
  根因是**敲穿下排后掉出的道具正好被球接住**，其中「一击必碎」把后面两排一路打穿。
  那不是 bug 是设计生效，但污染了几何判定 —— 改成每帧清掉落物与限时状态。

**五、踩到并修掉的真 bug：HUD 两段文字叠着印在一起**

改版时把「最高 385」和「第 2 轮 · 剩 17 块」画到了同一段 x 上 ——
`最高` 左对齐（起点 x=360），轮次段右对齐（终点 x=436、宽 130，起点约 306），
两段在 360~436 上完全重合。**逻辑断言全绿**，验收图放大到 1:1 才看见。

改法分两步：

1. 五段文字的位置 / 字号 / "最宽内容"抽成四张表：`HUD_ZONES`（x、宽）、
   `HUD_FONT`（字号、粗细）、`HUD_WIDEST`（每种最宽的那种内容）、
   `HUD_WIDEST_PX`（那些内容实测多少像素）。**`_paint_hud_numbers` 一个坐标都不写。**
   修完各段占用区间（按最宽内容算）：
   `score=(20,122)`、`combo=(138,227)`、`best=(244,312)`、`round=(350,480)`、
   `secs=(513,548)`、进度条 `(556,200..756)` —— 两两不交叉，条前还留 8px。
2. 冒烟测试加一组 **9 条纯几何断言**（四张表键名一致、各段区间两两不交叉、
   每段宽度 ≥ 登记的最宽像素、左右次序、不越界、条不压秒数、右对齐段右端钉住）。

**为什么断言不查字体度量**：`QT_QPA_PLATFORM=offscreen` 那个平台插件在本机
**字体库是空的** —— 连阿拉伯数字都画成方框，`QFontMetrics` 量出来是方框的宽度
（比真值宽一倍左右）。第一版断言就是拿它量的，于是 5 组"重叠"全是误报，
而真正的重叠反而被淹没。改成只比登记表（纯算术、与环境无关）之后，
真字体的复测放在 `tools/verify_v21_ui.py`（跑在真实平台上，把登记值和实量值并排打印）。

- 证据（真字体重量，与登记表完全一致）：`python tools/verify_v21_ui.py` →
  `score 102/102、combo 89/89、best 68/68、round 130/130、secs 35/35`
- 证据（几何断言全过）：`python tools/smoke_test.py` →
  `最宽的内容下 HUD 各段互不重叠（叠字那次的回归网）  (score=(20, 122)；combo=(138, 227)；best=(244, 312)；round=(350, 480)；secs=(513, 548))`
- 证据（产物）：`reports/v21_ui.png` 1120×2451

**六、为什么不引 Qt 到规则层**

`wheel.py` / `bag.py` / `pomodoro.py` 全部**不 import Qt**，和 `vitals.py` / `physics.py` 一致。
理由是可单测：滚轮的边界（1 秒 / 2 小时 / `2:30:50` 不存在）、背包的整笔失败，
这些正是最容易写错又最难在界面上点出来的地方。

**七、为解决循环依赖新增 `pet/uitheme.py`**

`wheel_dialog.py` 在 `pet/` 下，需要中文字体回退链；而那条链原来定义在
`game/common.py`，`game/common.py` 又 `import pet.assets` ——
留在 game 里就会逼出 `pet → game → pet`。于是把字体与对话框 QSS 抽到
`pet/uitheme.py`，`game/common.py` 改成**转出**（`from pet.uitheme import FONT_STACK, ui_font`），
两个游戏模块（`minigame.py` / `catcher.py`）**一行都不用改**。
- 证据：`grep -n "uitheme" game/common.py pet/window.py pet/wheel_dialog.py main.py`

**八、版本号与文档**

`pet/__init__.py`：`2.0.0` → **`2.1.0`**；`installer.iss` 的 `#define AppVer` 同步。
`CHANGELOG.md` 新增 v2.1.0 条目（本节即其事实底稿）；`README.md` 同步「怎么玩 /
状态在哪看 / 小卖部+背包 / 番茄钟 / 弹跳得分 / 目录结构 / 测试 / 怎么扩展」，
并补了 3 条本轮真踩的坑（HUD 叠字、offscreen 没字体、验收用例别让掉落道具掺进来）；
本 FACTS 新增本节与 V13，F4 / F7 / F8 重测。
新增 `tools/verify_v21_ui.py` → `reports/v21_ui.png`（1120×2451）。
- 证据：`grep -n "__version__" pet/__init__.py` → `2.1.0`
- 证据：`grep -n "AppVer" installer.iss` → `#define AppVer "2.1.0"`
- 证据：`grep -m1 "^## v" CHANGELOG.md` → `## v2.1.0 — 2026-09-27 傍晚 · …`
- 证据：`python tools/typecheck.py` → `0 errors, 0 warnings, 0 informations`
- 证据：`python tools/smoke_test.py` → `通过 323 项，失败 0 项 / 全部通过`
- 证据：`python tools/verify_v21_ui.py` → `产出 …\reports\v21_ui.png  1120x2551`（v2.2.0 改后为 2555，见 F30）

### F30 · v2.2.0：撤掉划过气泡 / 新增「跑一跑」与「狗粮 2048」（2026-09-27 深夜）
用户要求：**状态条不要一碰到狗就弹那么大个窗口**，只保留右键后的状态值；并**做 A（跑一跑）和 B（狗粮 2048）**。

**一、状态显示第三次收缩（撤掉划过气泡）**

状态值的出口一路收窄，这是它第三个版本：

| 版本 | 出口 |
|---|---|
| v2.0.0 | **1 个**：右键菜单 |
| v2.1.0 | **3 个**：右键菜单 / 背包面板顶上的状态条 / **划过弹出的气泡**（178px）|
| **v2.2.0** | **2 个，且都要你主动点**：右键菜单第一行两行 + 托盘 tooltip |

**为什么撤气泡**：判断依据是**触发频次**。桌宠常驻桌面，鼠标划过它是一天几十次的
**意外**动作；而状态是按分钟级衰减的。高频 + 非本意 + 内容低频变化 = 纯打扰。
所以留下的两个出口有个共同点：**都要求用户主动去点**。

改法：
- `pet/panel.py` **重写**（348→约 250 行）：删 `StatusBubble` 整个类，以及
  `VitalsStrip` / `vitals_rows` / `_bar` / `MINI_BAR_H` / `MINI_ROW_H` / `BAR_H` /
  `BAR_ROW_H` / `ALERT` / `NORMAL`。窗口标题「桌宠 · 状态 / 背包」→「桌宠 · 背包」。
- `pet/window.py`：删 `BUBBLE_LINGER_MS` / `self._bubble` / `self._bubble_timer` /
  `_show_bubble()` / `_hide_bubble()`，**以及整个 `enterEvent` 覆盖** ——
  一去掉，`PetWindow.enterEvent` 就回到 `QWidget.enterEvent`（空实现），划过再无反应。
  `leaveEvent` 瘦身成只刷面板，`closeEvent` 不再停气泡定时器。
- `pet/tray.py` / `pet/menu.py`：菜单项「状态 / 背包面板」→「背包面板」，docstring 同步。
- **补一条"它去哪儿了"**：面板里没了状态条会让人以为状态显示丢了，所以新增一行灰字
  `BagPanel.where`：**"它饿不饿、困不困：右键它，菜单第一行"**。

- 证据：`tools/smoke_test.py` 3 条**防回退**断言 ——
  `鼠标划过桌宠不再弹窗（enterEvent 不再被覆盖）`（断言 `PetWindow.enterEvent is QWidget.enterEvent`
  且 `not hasattr(uw, "_bubble")`）、
  `背包面板里不放状态条（状态值只留一处口径）`（`not hasattr(panel, "strip")`）、
  `面板留了一行字，告诉用户状态去哪儿看`（`"右键" in panel.where.text()`）
- 证据：`tools/verify_v21_ui.py` 的 ③ 改成「背包面板」、④ 改成「状态值：只在右键菜单里」，
  实测打印 `右键菜单尺寸 269x386` 并出图

**二、跑一跑（横版跑酷）**

`game/runner.py`（新增，约 500 行）。`← →` 加速减速、`空格`/`↑` 跳、`↓` 低头、`R` 重开。

| 常量 | 值 | 作用 |
|---|---|---|
| `GRAVITY` / `JUMP_V` | 3000 / 1010 | 基础跳跃 |
| `JUMP_BUFFER` | 0.13 s | **落地前按的跳会被记住**，否则就是丢输入 |
| `JUMP_CUT` | 0.42 | 松手减速上升 → 可变跳跃高度 |
| `FAST_FALL` | 2600 | 按 ↓ 加速下坠 |
| `BASE_SPEED` / `SPEED_STEP` / `SPEED_STEP_DIST` / `MAX_SPEED` | 340 / 46 / 3000 / 780 | 难度按**跑过的距离**分档加速 |
| `GAP_SEC_START` / `GAP_SEC_DECAY` / `GAP_SEC_MIN` | 1.55 / 0.13 / 0.55 | 障碍间距随档位收紧 |
| `HIT_PAD_X` / `HIT_PAD_Y` | 9 / 6 | **玩家**判定盒四周收窄；障碍不收 |

三种障碍（`KINDS`）：`low` 矮墩（32×42，贴地）、`tall` 高墙（48×68，贴地）、
`bird` 垂杆（52×高，`hang=True` 吊在半空）—— 高墙与垂杆都必须低头。

- **刻意不做土狼时间**（coyote time）：那是给"有边缘的平台"准备的，这条赛道是**平的**，
  没有边缘可走空。理由写进模块 docstring。
- **竖直运动不复用 `pet.physics.Motion`**：本项目第一次"该复用却不复用"。
  单向运动十行算术就够，`Motion` 是为"会撞墙 / 有摩擦 / 会弹跳"的方块写的。
- 走路帧按**跑过的距离**推进（`int(distance/52.0) % len(frames)`），不是按时间 ——
  跑得快时脚底下也跟着快。
- 证据：`tools/smoke_test.py` 的「跑一跑」段（27 条），含
  `难度到顶时速度封顶在 MAX_SPEED`、`跳跃缓冲：落地前按的跳会补上`、
  `松手后上升被截断（可变跳跃高度）`、`判定盒收窄后"看着擦过去"的算过`、
  `三种障碍的贴地/吊顶高度符合 KINDS`、`HUD 四段不叠且槽位不叠`

**三、狗粮 2048**

`game/g2048.py`（新增，约 450 行）。`↑↓←→` 滑、`Z` 撤销（一局 3 次）、`R` 重开，
凑出 **512** 就结算。**规则层一行 Qt 都不 import**（`slide_line` / `move` /
`can_move` / `max_tile` / `is_finished` / `coins_for_tile` / `target_ratio`）。

| 点 | 做法 | 不这样做会怎样 |
|---|---|---|
| 一次滑动只合一次 | `slide_line` 用 `i += 2` 跳过刚合成的格子 | `2 2 2 2` 会一路合成 `8` |
| 无效方向不冒块、不记历史 | `move()` 返回"有没有真动"，没动就不 spawn、不入栈 | 顶到墙也能刷出新块 / 能空撤销 |
| 撤销存三元组 | `_history` 存 `(grid, score, undo_left)` | 只存棋盘 → 撤销退分数但不退次数，越撤越多 |
| **金币另有尺子** | `coins_for_tile` 按**最大格子**：`(exp-2)*8`，512→56 | 按分数折算会通胀（两个 256 合成 512 一次 +512 分）|
| 目标进度条是**对数**的 | `bit_length()` 算 | 线性的永远卡在 90%，看着像坏了 |

> **两把金币尺子**的代价写进了两侧注释：`game/common.py` 的 `coins_for`
> （分数 `// 10`，bounce/catch/runner 用）与 `game/g2048.py` 的 `coins_for_tile`
> （最大格子，2048 用），改汇率要记得两处。

- `is_finished()` 抽成纯函数的**唯一目的**就是让"死局"这条难在窗口层构造的路径可单测 ——
  测试里循环 300 个种子找一个真能撞出死局的种子（实测种子 0 就能）。
- `_DIRECTION_KEYS` 写在**类外**：类体里引用 `Qt` 常量拼错要到运行时才炸。
- 证据：`tools/smoke_test.py` 的「狗粮 2048 · 规则」+「狗粮 2048 · 窗口」段（35 条），含
  `一次滑动只合一次（2 2 2 2 右滑出 0 0 4 4）`、`不同行的两块不会合到一起`、
  `无效方向不冒块、不记历史`、`撤销把棋盘和分数都退回去`、`次数用光就不能再撤`、
  `凑出 512 立刻结算`、`达成目标给的金币按最大格算（56）`、
  `推不动了也会结算（死局这条路径真的走得到）(种子 0)`、`死局结算不标成"达成目标"`

**四、踩到并修掉的真 bug：HUD 登记表是"估"出来的（叠字第二次犯）**

复用 v2.1.0 那套 HUD 登记表时，`HUD_WIDEST_PX` 是照着弹跳得分的经验**估**的，
一跑验收脚本就三处超了：

```
tier   第 99 档      52 / 57  <- 超了！
speed  780 px/s     62 / 65  <- 超了！
tile   最大 2048     62 / 71  <- 超了！
```

其中 2048 的 `tile`（x=214 宽 76）与 `undo`（x=296 宽 64）**差 1px 就叠上了**。
**最阴的一点：冒烟测试用的就是登记值，登记值偏小反而查不出真重叠。**

改法三步：
1. 按实量校准：runner `tier=57 / speed=65`，g2048 `tile=71 / undo=47`；
   重排 `HUD_ZONES`（`tile` 宽 76、`undo` x=296 宽 64、`HUD_BAR=(380,360)`）。
2. 两处注释写明**"估计宽度没有意义，这张表只能是量出来的"**。
3. 断言升级：从"墨迹不叠"改成"**分配出去的槽位本身就不重叠**" ——
   墨迹不叠会被"某段恰好比最宽内容还短"骗过去，槽位不叠不会。

- 证据（修完实量与登记完全一致）：
  `python tools/verify_v22_ui.py` →
  `score 102/102、best 68/68、tier 57/57、speed 65/65`；
  `score 102/102、best 68/68、tile 71/71、undo 47/47`；三处 `<- 超了！` 全部消失
- 证据：`tools/smoke_test.py`
  `跑一跑 HUD：分配出去的槽位本身就不重叠（比墨迹不叠更严）`、
  `狗粮 2048 HUD：分配出去的槽位本身就不重叠（比墨迹不叠更严）`

**五、共享 HUD 算术收敛到 `game/common.py`**

三款游戏的 HUD 排版判断原本各一份，抽成三个共享函数：

| 函数 | 干什么 |
|---|---|
| `zone_spans(zones, widest_px, right_aligned)` | "槽位 + 最宽内容" → 占用区间；右对齐段按右端钉住往左推 |
| `overlapping_zones(spans)` | 两两相撞的是哪几对 |
| `measure_zone_widest(fonts, widest)` | 量真实像素宽（**须真实平台**，offscreen 没字体库）|

`minigame.py` 的 `hud_zone_rect` / `measure_hud_widest` 改为转调它们；
`runner.py` / `g2048.py` 直接用。
- 证据：`grep -n "zone_spans\|overlapping_zones\|measure_zone_widest" game/*.py`

**六、登记表扩展方式复验**

加这两款游戏**只动了 `game/__init__.py` 两处**：`GAMES` 加两行、`create_game()` 加两个分支。
两个菜单（桌宠右键 + 托盘）自动继承，一行没碰。
- 证据：`tools/smoke_test.py`「游戏菜单接线」段实测
  `弹跳得分/接狗狗/跑一跑/狗粮 2048`、标识 `bounce/catch/runner/2048`

**七、版本号与文档**

`pet/__init__.py`：`2.1.0` → **`2.2.0`**；`installer.iss` 的 `#define AppVer` 同步。
`CHANGELOG.md` 新增 v2.2.0 条目（本节即其事实底稿）；`README.md` 同步
「怎么玩 / 状态在哪看 / 四个游戏 / 目录结构 / 测试 / 怎么扩展 / 已知坑」，
并补了 2 条本轮真踩的坑（"有、但用不上"的功能也是负担；自绘宽度不能估只能量）；
本 FACTS 新增本节与 V14，F4 / F7 / F8 / F9 重测。
新增 `tools/verify_v22_ui.py` → `reports/v22_ui.png`（1120×2125）。
- 证据：`grep -n "__version__" pet/__init__.py` → `2.2.0`
- 证据：`grep -n "AppVer" installer.iss` → `#define AppVer "2.2.0"`
- 证据：`grep -m1 "^## v" CHANGELOG.md` → `## v2.2.0 — 2026-09-27 深夜 · …`
- 证据：`python tools/typecheck.py` → `0 errors, 0 warnings, 0 informations`
- 证据：`python tools/smoke_test.py` → `通过 405 项，失败 0 项 / 全部通过`
  （这是 **v2.2.0 当时**的数字；v2.2.1 后是 **424**，见 F31）
- 证据：`python tools/verify_v22_ui.py` → `产出 …\reports\v22_ui.png  1120x2125`
- 证据：`python tools/verify_v21_ui.py` → `产出 …\reports\v21_ui.png  1120x2555`


### F31 · v2.2.1：「喂一口」每天一次免费、之后吃背包里的（2026-10-08）

**为什么改**：v2.1.0 上了背包和小卖部，把「买」改成"先入库、要用再点"，
但菜单顶上那个「喂一口」**不认识背包** —— 饱食 +26、冷却 0.35 秒，
从饿到饱只要一秒半、一个金币不花，小卖部于是成了摆设。
这个洞留了两个版本，而且**两轮验收都没查出来**：测试全绿、验收图也好看 ——
因为它不是"坏了"，是**两条路给同一个数**，没有断言会因为"白送也能涨"而失败。

**根子**：三条养成值里**只有饱食没有别的回补渠道**（心情睡觉会回、
精力只有睡觉能给），所以"免费喂一口"等于把唯一的稀缺资源做成了无限供应。

**新规则**（两条路，按"今天那份免费额度还在不在"分）

| 情形 | 消耗 | 效果 | 菜单那行写什么 |
|---|---|---|---|
| 当天还没喂过 | 无（一天就这一份） | 饱食 +26（`vitals.FEED_GAIN`） | `喂一口（今天免费）` |
| 当天喂过了、背包里有吃的 | 背包里**第一样"吃的"** | 那样东西自己的效果 | `喂一口（吃掉肉干，还剩 1）` |
| 当天喂过了、背包里没吃的 | — | **喂不了** | `喂一口（今天的免费用完了，背包里也没吃的）`（**灰掉**） |

**关键实现点**

- **"吃的" = 加饱食的商品**（`menu.is_food`）。玩具球不算：饿的时候啃球没有意义，
  所以背包里只有玩具时那一行照样灰掉。
- **吃哪一样由 `Bag.first_food()` 定**：按 `SHOP` 顺序取第一样吃的，
  所以**肉干优先于豪华大餐**；顺序稳定，同一只狗每次喂到的都是同一样。
- **吃的那条路复用 `use_item()`**，不另写一遍 —— 于是「喂一口」和「🎒 背包」
  永远不会出现"一个扣了、一个没扣"。
- **免费用的是本地日期**（`Config.free_feed_day`，格式见新增的 `config.DAY_FMT`），
  跨天自动恢复。**不用定时器**：`PetWindow.feed_plan()` 每次开菜单现算。
- **单一事实来源**：`PetWindow.feed_plan() -> FeedPlan | None` 同时喂给"菜单文字"
  和"点下去做什么" —— 免得出现"菜单说免费、点下去却扣了肉干"。
  `menu.feed_text(plan)` 只负责措辞；`menu._FeedPlan` 用 **Protocol** 声明形状
  （不反向 import `window`，否则成环，同 `_ToggleTarget` 的老办法）。
- **`_FeedPlan` 的三项必须写成 `@property`（只读）**：对方 `FeedPlan` 是 frozen
  dataclass，写成裸注解的话 pyright 会判"不满足这个形状"（实测报了 6 个错）。
- **「逗它玩」心情 22 → 8**（`vitals.PLAY_GAIN`）；精力消耗**没跟着缩**，
  抽成独立的 `PLAY_ENERGY_COST = 3.3`。理由："玩一次费多少力"是**动作**的属性，
  不是**收益**的属性；而且精力只有睡觉能回，留着它才让逗它玩仍有成本、不能无限刷。
- **存档向前兼容**：老存档没有 `free_feed_day` 字段 → 读进来是 `""` = "从没用过" →
  升级后还能白喂一次。`Config.load` 只认 `fields()` 里的名字、缺字段走默认值，
  **不需要写迁移代码**。

- 证据：`grep -n "__version__" pet/__init__.py` → `2.2.1`
- 证据：`grep -n "AppVer" installer.iss` → `#define AppVer "2.2.1"`
- 证据：`grep -m1 "^## v" CHANGELOG.md` → `## v2.2.1 — 2026-10-08 · …`
- 证据：`python tools/smoke_test.py` → `通过 424 项，失败 0 项 / 全部通过`
- 证据：`python tools/typecheck.py` → `0 errors, 0 warnings, 0 informations`
- 证据：菜单文字实测三种形态 —— `喂一口（今天免费）` /
  `喂一口（吃掉肉干，还剩 0）` / `喂一口（今天的免费用完了，背包里也没吃的）`

**版本号为什么是 2.2.1 而不是 2.3.0**：按 `CHANGELOG.md` 开头的规则
（"小改动 +1：修 bug、调数值"，先例是 v0.7.2 修「重力下坠」开关），
这轮是**修一个漏洞 + 调两个数值**，没有加游戏、没有换体系、没有重构 → PATCH。

### F32 · v2.4.0：菜单「去睡一会儿」，第一次能主动安排它睡觉（2026-10-09）

**为什么改**：三条养成值里**精力只有睡觉能补**（小卖部刻意不卖），但全项目
**没有任何"主动让它睡"的入口** —— `SLEEP` 只能由"精力掉到 `TIRED_AT=25` 以下
累趴下"触发。于是"它累了，我让它歇会儿"这件事用户**插不上手**。

**背景**：2026-10-08 讨论过一轮"怎么快速提高精力且不违和"，列了 5 个候选，
当时只到"选方向"、没动代码。落地的是候选①（菜单入口 + 这一觉加速）。
当时给的判据里**否掉的一条**要留着：**小卖部卖咖啡/能量饮料**会形成
"玩游戏→金币→买精力→继续玩"的自循环，让桌宠退化成挂机刷币器。

**新规则**

| | 自然睡 | 主动小睡（`sleep_now`） |
|---|---|---|
| 触发 | `tired=True`（窗口喂 `vitals.tired`） | 菜单「去睡一会儿」 |
| 加速 | 无 | `NAP_BOOST = 3.0`（`vitals.py`） |
| 25 → 82 用时 | **9.5 分钟** | **3.17 分钟** |
| 最短躺多久 | 无 | `NAP_MIN_SECONDS = 60.0`（`behavior.py`） |
| 出口 | `rested` / 被戳 | **完全相同**（不另开醒来路径） |

**关键实现点**

- **两个入口、一套出口**：`Brain.sleep_now()` 只是"强制进 `SLEEP`"，不新增状态、
  不新增出口。醒来仍然是 `rested` 或 poke/feed 把它切走。
- **加速的是"整段时间"，不是单独把精力那一项调快**（`_tick_vitals` 里写的是
  `vitals.rest(dt * NAP_BOOST)`）。这一点决定它**不产生额外收益**：
  睡了 3 倍速、只睡 1/3 时长 ⇒ 三项总账与自然睡**逐项相等**
  （实测 `82/51.71/48.10` 对 `82/51.71/48.10`，见证据）。
  要是改成"只把精力调快"，就成了凭空多送心情和饱食。
- **`napping` 属性放在 `Brain` 上，不是窗口记 flag**：窗口另记一份的话，
  它睡着时被戳醒，窗口那份就留在原地，**下一觉（自然睡）会白捡加速**。
  `_enter()` 在进入非 `SLEEP` 状态时清 `_nap` / `_nap_min`。
- **最短时长闸门写在 `update()` 的 `SLEEP` 分支**：`self._nap_min` 倒数到 0
  且 `rested` 才醒。自然睡 `_nap_min` 恒为 0 ⇒ 行为与老版本**完全一致**。
- **单一事实来源**：`PetWindow.nap_plan() -> NapPlan` 同时喂"菜单文字"和
  "点下去做什么"（同 `feed_plan()` 的老办法）；`menu._NapPlan` 用 Protocol 声明形状。
- **三种"点不了"各给一句原因**：`它已经睡着了`（已在 SLEEP）/
  `先把它放到地上`（DRAG / FALL —— 半空趴下很怪，自动睡也不在这两个状态发生）/
  `它不困（精力 N）`（`rested`）。菜单那一行**灰掉并写明原因**，不是点了没反应。
- **不做每日限额**：`「喂一口」` 要限额是因为它把"唯一没有免费回补渠道"的饱食
  变成了无限供应；这里**一点资源都没多给**，只压缩等待时间，且行动本身要花
  1~3 分钟真实时间。

- 证据：`grep -n "NAP_BOOST\|NAP_MIN_SECONDS" pet/vitals.py pet/behavior.py`
  → `vitals.py:NAP_BOOST = 3.0` / `behavior.py:NAP_MIN_SECONDS = 60.0`
- 证据：`grep -n "__version__" pet/__init__.py` → `2.4.0`
- 证据：`grep -n "AppVer" installer.iss` → `#define AppVer "2.4.0"`
- 证据：`grep -m1 "^## v" CHANGELOG.md` → `## v2.4.0 — 2026-10-09 · 「去睡一会儿」…`
- 证据：`python tools/smoke_test.py` → `通过 453 项，失败 0 项 / 全部通过`
  （v2.4.0 新增 22 条：`主动小睡（去睡一会儿）` 段 19 条 + `存档隔离与每日快照`
  段里钉 `source_asset_dir()` 的 3 条）
- 证据：`python tools/typecheck.py` → `0 errors, 0 warnings, 0 informations`
- 证据（总账等价，逐项相等）：同样从精力 25 睡到 82 ——
  主动小睡 `3.17` 分钟 → `精力 82.00 / 心情 51.710 / 饱食 23.100`；
  自然睡 `9.50` 分钟 → `精力 82.00 / 心情 51.710 / 饱食 23.100`
- 证据（窗口层，同一段 190 秒）：主动小睡已回 `idle`，自然睡仍在 `sleep`
- 证据（菜单实测三态）：`去睡一会儿（它已经睡着了）`（灰）/
  `去睡一会儿（睡饱约 2 分钟）`（可点）/ `去睡一会儿（它不困（精力 95））`（灰）

**版本号为什么是 2.4.0 而不是 2.3.2**：按 `CHANGELOG.md` 开头的规则，
判断标准是"用户能不能明显感知到"—— 这轮**多了一个菜单入口和一种可见行为**
（点了它当场趴下、睡姿贴图会播），属于"加功能" → MINOR。

### F33 · 强隔离会把"用户的只读素材"一起挪走（v2.4.0 发现，坑在 v2.3.1 埋下）

**事实**：隔离用的环境变量 `DESKTOP_PET_DATA_DIR` 换的是**整个可写数据目录**，
而素材目录是**从它推导出来的**：`user_asset_dir("pet") = data_dir()/"custom_pet"`。
⇒ 一旦隔离，`pet_asset_dir()` 就退到内置的 `assets/pet/`，而**那儿是空的**
（183 张贴图全在项目根的 `custom_pet/`，见 F1 / F2）。

**后果不是崩，是静默画空**：渲染出来一只空白狗，而"空 vs 空"照样相等 ——
朝向比对 / 动作比对 / 像素比对会**安静地全部通过**。

**受害者（v2.3.1 把它们的"备份-还原"换成强隔离时弄哑的）**：
`verify_facing.py` / `verify_actions.py` / `verify_desktop.py`。
（`verify_facing` 至少会打印"没找到 walk 素材"然后退出 1；`verify_actions`
当时连这句都没有，连拍出来是一整页空白狗。）

**修法**：`tools/_isolate.source_asset_dir(name)` —— 临时摘掉那个环境变量、
按生产规则解析一次再放回去，**复用 `resolve_asset_dir` 的"用户目录整体接管"判定**
（不在这儿抄第二份）。读只读素材不会伤存档，所以隔离本身不用动。
`check_save_isolation.py` 加了一条静态检查：**凡用了 `isolate_storage()` 又直接
用 `pet_asset_dir()` / `game_asset_dir()` / `card_asset_dir()` 的脚本一律报错**。

- 证据（修前 vs 修后，隔离状态下）：`pet_asset_dir()` → `assets\pet`，
  `AssetBank(...).load().count("idle")` = **0**；
  `source_asset_dir("pet")` → `custom_pet`，`count("idle")` = **17**、`count("sleep")` = **22**
- 证据：`python tools/verify_facing.py` → 第一行 `[验收] 素材目录 : custom_pet`
  （修前会是 `assets\pet`，随后报"没找到 walk 素材"）
- 证据：`python tools/check_save_isolation.py` → `全部通过`
- **检查精度**：只对 `isolate_storage()` 判，不对"改 `config_path`"判 ——
  后者只换存档文件、`data_dir()` 不动，素材照读。一起报会**误伤 10 个脚本**
  （实测：render_preview / smoke_test / verify_catch_items / verify_fling /
  verify_gravity / verify_v21_ui / verify_v22_ui / verify_variants /
  verify_vitals / verify_walk_sets）。这条精度由检查器自检锁住。

### F34 · 卡册 4 张验收截图原本每次跑都不一样（v2.4.0 顺手修）

`verify_album_ui.py` **先抽 40 次卡再截图**，而 `Album` 默认用真的 `random.Random()`
⇒ 抽到什么直接决定截图内容。实测同一份代码连跑两次，`卡册_第1页.png` 有
**61067 / 567300 ≈ 10.76%** 的像素不同；尺寸相同（620×915），所以不是分辨率问题。

**修法**：`Album` 本来就留了 `rng` 注入口（`pet/cards.py` 的
`Album.__init__(cfg, rng=None, ...)`），脚本里钉一个固定种子即可。

- 证据：`pet.album.rng = random.Random(20261009)` 之后，连跑两次四张图 sha256 前 16 位
  完全一致（`4f8e65cf4663125d` / `5ec67e9f4166f4db` / `4f17563c88628f0d` / `906598c090ff628d`）
- 反例（修前）：同代码连跑两次 → `6d59caf26147f177` vs `2ae1266e105ad302`

## 二、推断区（每条附证伪命令；给不出证伪方法的推断不许留）

### I1 · 桌宠实例在跑时会周期性改写 `config.json`
推断依据：观察到的变动**全部是"宠物自己会改的字段"**——`pos_x`（走动位置）、
`feed_count` / `play_count`（投喂与互动次数），而工具用的是默认 `Config()`，
会写的是 `scale`/`style`/`best_*` 这类。2026-09-21 16:10~16:20 期间在跑实例存在时
反复观察到 `pos_x` 每次采样都不同（1305→1304）、`play_count` 28→30。
- 反证（工具不写）：F16 的只读锁实验 —— 锁住后两个工具照跑不报错，锁前/锁后只差 `pos_x` 1。
- 证伪/确认命令：`md5sum <config.json>` 连测两次（间隔数秒）；同时 `tasklist | grep -i python`
  对比进程有无。若进程存在而 md5 稳定不变，则本推断不成立。

### I2 · 两个互动动作的观感差异现在主要来自"帧数差"，不是帧率
推断依据：`_oneshot_seconds = max(1, 帧数) ÷ FPS`。本轮 poke 只剩 **9** 帧 / 12.5fps ≈ **0.72s**，
feed **22** 帧 / 10.0fps = **2.20s** —— 两者时长差了 3 倍，动作自然一个"弹一下"、一个"吃两口"。
**这条是算术结论，不是实测观感。**
- 证伪命令：把 `behavior.FPS[State.POKE]` 改成 2.0（时长变 ~4.5s）后重跑 `smoke_test.py`，
  若「逗它玩时长」断言仍与 feed 拉开 3 倍以上、且用户看不出差别，则本推断不成立。

### I3 · 接狗狗的难度曲线（`RAMP_TIME=75s` 爬满）对手感是合适的
推断依据：75 秒时出怪间隔收到 0.45s、炸弹率 0.44，一屏同时最多约 3 个落体；
再快（>0.5/秒）会出现"来不及移动就被判漏接"。**这条纯粹是设计判断，没有实测数据支撑。**
- 证伪命令：让用户连玩 5 局并记录每局 gameover 的存活时长。若 5 局里有 3 局以上
  **活不过 60 秒**，说明难度爬得太快，应把 `RAMP_TIME` 调大或把 `SPAWN_MIN` 调大；
  若 5 局都**超过 3 分钟**，说明太松，反过来调。

### I4 · `drag` 素材里那只小白狗不会被当成"换了一只宠物"
推断依据：`drag_*.png` 里除黄狗外还有一只小白狗（黄狗在甩开它），是全集里最接近
"挣扎/被拎"的素材；但它确实是**画面里出现了第二只狗**。判断"违和程度"没有客观方法。
- 证伪命令：问用户"把桌宠拎起来的时候，看到旁边那只白狗会不会觉得奇怪"。
  若回答"会" → 换成 `xian_tiao_xiao_5132_线条小狗C (8).gif`（狗吊在单杠上，
  但带杠铃道具），或从素材库外另找。

---

## 三、已作废结论（禁止再引用）

### V1 · ~~`State.PLAY` / `jump_*` 贴图~~（2026-09-21 下午作废）
旧文档与旧记忆中的「`PLAY` 状态复用 jump 的 20 帧」「custom_pet 有 jump 20 帧」**已作废**：
`PLAY` 已删除，`jump_*` 已从 custom_pet 移除，白狗素材退役。
想恢复白狗：`python tools/intake.py --map 小狗1=poke --apply`（需先把原 GIF 拷回 `assets/raw/inbox/`）。

### V2 · ~~F8 的旧指纹表 / 「小游戏只有一个·69 项测试」~~（2026-09-21 傍晚作废）
2026-09-21 下午那版 FACTS 里的源文件指纹（`589fa96a`/`add4e96b`/…）**只对当时的文件有效**，
本轮改了 `game/catcher.py`、`game/common.py`、`game/minigame.py`、`pet/facing.py`、
`tools/prep_sticker.py`、`tools/intake.py`、`tools/render_preview.py`、`tools/smoke_test.py`
并新增 `tools/prep_bg.py`，所以指纹已换成 F8 里那一组。**禁止再用旧指纹做"文件没被改过"的判断。**
同理以下旧记述一并作废：
- 「小游戏只有一个（弹跳得分）」→ 现有两个，见 F9。
- 「冒烟测试 69 项 / 110 项 / 113 项 / 123 项 / 125 项 / 134 项 / 150 项」→ 曾为 **159 项**，
  当日傍晚再改为 **151 项**，见 F4 / V11。
- 「`pet.assets.STATES` 是唯一的贴图状态表」→ 游戏素材走 `catcher_/puppy*_/bomb_` 前缀，
  与它无关，见 F13/F15。

### V3 · ~~「预览脚本不会动用户存档」~~（2026-09-21 傍晚作废）
旧结论认为 `render_preview.py` 是只读的。**错**：它截小游戏结算图时会走到
`MiniGame._finish()` → `cfg.save()`，把临时默认 `Config` 写进真实 `config.json`。
现已加 `isolate_config()` 修掉，但**当时之前如果跑过预览，用户的存档就已经被覆写过**。
凡以后看到"位置突然回到 -1 / 投喂次数归零 / 最高分变小"，先怀疑这个。
证据与修法见 F16 与 `reports/README.md` 坑位第 9 条。

### V4 · ~~F13「游戏素材目录当前为空」/ I4「占位形象不会被误当成成品美术」~~（2026-09-21 16:20 作废）
上一条 F13 说 `assets/game/*.png` 数量 = 0、接狗狗全走占位形象 —— **已不成立**：
本轮素材已入库（见 F13）。连带的 I4（"担心用户以为已经做好了"）也一并作废：
用户已明确知道要换素材，并且已经换完了。

### V5 · ~~custom_pet 帧数「idle 14 / walk 8 / drag 23 / poke 9 / feed 22」之外的旧记录~~
（2026-09-21 稍早的中间态，仅作历史）
本轮中途曾出现过 idle 14 / walk 8 / drag 23 / **poke 24** / feed 20 等中间状态
（poke 用的还是上一批素材）。**当前有效值只有 F1 那一行。**

### V6 · ~~「验收产物写在项目根目录」~~（2026-09-21 17:00 作废）
`render_preview.py` 与 `verify_desktop.py` 以前把图写在项目根目录，
`reports/README.md` 又按 `reports/` 列清单，导致跑完任务还得手工搬一遍。
现已改为**直接写 `reports/`**，项目根目录不再出现任何 png/gif。
任何"去项目根目录找 `preview_sheet.png`"的旧说法一律作废，见 F7。@`28fcfecd` `6dec33b3`

### V7 · ~~F13「`catcher_*` 14 张」~~（2026-09-21 17:00 作废）
旧 F13 记 `catcher_*` = 14、`len(g.sprites['catcher'])==14`。那是因为当时用的是另一套
catcher 素材；换成 `#5197`「张臂」那套（源 GIF 本身就 8 帧，`--keep 10` 截不到它）之后，
**实际是 8 张**。禁止再引用 14。@`c2d65504`

### V8 · ~~F1「custom_pet 76 张，poke 9 / feed 22 各一套」+ F4「113 项」~~（2026-09-21 傍晚作废）
poke 与 feed 现在**各 3 套**（见 F18）。
（同一条里"冒烟测试 123 项"作废 → 曾为 134 项、150 项、159 项，现 **151 项**，见 F4 / V11。）旧值只作历史；
`custom_pet/` 总数也已成 161（见 V9）。

### V9 · ~~F1「144 张 / idle 14」、F4「134 项」、F5「idle 来自 #6024」、F7「动图 122 帧 2179184 B」~~
（**2026-09-22 作废**）
2026-09-22 把待机换成「坐木凳晃腿」（17 帧，来源见 F23）、原 idle 那套转去当 `walk_a`，
并让 walk 参与两套轮播（见 F18），于是：

| 旧值 | 现值 | 依据 |
|---|---|---|
| `custom_pet/` 144 张 | **161 张** | F1 |
| `idle` 14 帧（站姿挥手） | **17 帧**（坐木凳） | F1 / F23 |
| `walk` 只有 1 套 8 帧 | **2 套：8 + 14 帧** | F1 / F18 |
| 冒烟 134 项 | **159 项**（同日晚些改为 151 项，见 V11） | F4 / V11 |
| 动图 122 帧 / 2179184 B | **128 帧 / 2494829 B** | F7 |
| `facing.json` 只有 `base` | 加了按套覆盖 `sets` | F6 / F24 |
| 读素材的命令模板（无 `walk_a`） | 已换成含 `walk_a` 的版本 | F1 证据行 |
| `pet/window.py` @`61948a82` | @`9ebf8f57` → @`7351dc7c` | F8 |
| `tools/smoke_test.py` @`7424b17d` | @`af0a1184` → @`84631331` | F8 |

> 另注意：F5 里「idle 用的是 `xian_tiao_xiao_6024_线条小狗.gif`」**并没有错、只是容易误读** ——
> 那套素材还在，只是状态名从 `idle` 换成了 `walk_a`。

### V10 · ~~F6「`facing.json` 只有 `base` 一个键，整个目录一套朝向」~~（2026-09-22 傍晚作废）
加了 `sets` 按套覆盖之后，`base` 只是**默认值**（见 F24）。
直接后果：`walk_a` 那套原图朝右的素材此前**一直在倒着走**（`base=left` 让它永远被镜像反），
这也是用户报"走路方向和面朝方向反了"的真正原因 —— **不是绘制代码的 bug**，
是声明粒度不够。查"某套对不对"只能看图，别指望 `verify_facing.py` 的数字
（它拿声明反推头朝哪边，天然自洽）。

### V11 · ~~F8 的旧指纹表 / F4「159 项」/ F22 的「`pet/config.py` 是优先级唯一实现」/ 「`_done`·`_recovered` 为目录名」~~（2026-09-22 傍晚作废）
删除自绘素材 + 抽出三个登记表 + 素材库改名之后，下列旧结论一律作废（新值见 F8 / F4 / F22 / F26）：

| 旧值 | 现值 | 依据 |
|---|---|---|
| `assets/pet/` 有 21 张 assetgen 生成的 PNG | **空，只有 README.md** | F26 |
| `pet/assetgen.py` / `pet/assetgen_line.py` / `pet/styles.py` 有 md5 | **文件已删除** | F26 |
| `tools/gen_assets.py` / `tools/make_fixtures.py` / `tools/fixtures/` 存在 | **已删除** | F26 |
| 冒烟 **159 项** | **151 项** | F4 |
| `preview_styles.png` 是 `reports/` 的产物之一 | **已删除，不再生成** | F26 |
| 素材优先级唯一实现在 `pet/config.py` | 移到 **`pet/paths.py`**（`ASSET_KINDS` 登记表） | F22 / F26 |
| 状态名在 `behavior.SPRITE` + `assets.STATES` + `prep_sticker.VALID_STATES` 各一份 | **只在 `behavior.State`**，其余派生 | F3 / F26 |
| 归档目录叫 `_done/` / `_recovered/` | **`_archive/` / `_snapshots/`** | F26 |
| `tools/rebuild_from_recovered.py` | **`tools/rebuild_from_snapshot.py`** | F26 |
| `Config` 有 `style` 字段、`main.py` 有 `ensure_assets()` | 字段删除；改为 `check_pet_assets()`（只提示不生成） | F26 |
| `.vscode/tasks.json` 里有 3 个 `gen_assets.py` 任务 | 已删，共 18 个任务 | F26 |

> **另外**：F1 / F3 / F5 / F6 / F7 / F9…等条目末尾那些**写在 2026-09-22 傍晚之前的
> `@版本` 代码**（如 `@16b87e8f`(assets.py)、`@589fa96a`(behavior.py)、`@a02ab733`(config.py)）
> 已随本轮改动失效 —— 一律以 **F8 的新指纹表**为准，引用前重新核对。

### V12 · ~~F8 的旧指纹表 / F4「151 项」/ F1「custom_pet 161 张」/ F9·F10「接狗狗只有两种落体」/ 「版本 v1.0.0」~~（2026-09-23 午作废）
v2.0.0 五大玩法（见 F27）落地后，下列旧结论一律作废（新值见 F8 / F4 / F1 / F27）：

| 旧值 | 现值 | 依据 |
|---|---|---|
| `pet/__init__.py` 的 `__version__` = `1.0.0` | **`2.0.0`**（`installer.iss` 的 `AppVer` 同步） | F27 |
| `CHANGELOG.md` 首条 = `## v1.0.0` | **`## v2.0.0 — 2026-09-23 午 · 五大玩法…`** | F27 |
| 冒烟 **151 项** | **234 项**（+5 段共 83 条） | F4 |
| `custom_pet/` **161 张** | **183 张**（+`sleep_*` 22 帧） | F1 / F27 |
| `State` 只有 IDLE/WALK/DRAG/FALL/POKE/FEED（6 个） | **多一个 `SLEEP`**（7 个） | F3 / F27 |
| `Config.feed_count` / `play_count` 是"死计数器"（存了没人读） | 仍是计数，但**新增** `satiety/mood/energy/coins/last_seen` 才是玩法状态 | F27 |
| `physics.Motion.throw()` / `edge_bounce` / `restitution` "写了没接线" | **已接线**（`VelocitySampler` + `clamp_fling` + `window._start_fling`） | F28 |
| 接狗狗只有 `puppy` / `bomb` 两种落体、`Faller` 水平速度恒为 0 | **多一种 `bone`**；带风落体有水平速度且**撞墙反弹** | F27 |
| `CatchGame.heal()` "写好了没人调" | **骨头会调它**（有伤时回 1 滴） | F27 |
| 「菜单里只有 1 个子菜单（一起玩游戏）」 | **3 个**（小卖部 / 番茄钟 / 一起玩游戏） | F4 / F27 |
| `reports/` 只有 22 个产物（改朝向那批） | **+3**：`vitals_curve.png` / `fling_throw.png` / `catch_items.png` | F7 / F27 |
| `pet/config.py` 只管"用户选了什么"（v1.0.0 的说法） | 仍然只管配置，但**多了养成与金币字段**（含时间戳换算） | F27 |
| `pet/physics.py`、`pet/anim.py` 不在 F8 指纹表里 | **已补登记**（v1.0.0 那次漏了） | F8 |

> **旧 `@版本` 提醒**：F1…F26 条目里写在 2026-09-23 之前的 `@` 代码一律失效，
> 以 **F8 的新指纹表**为准。特别是 F4 末尾那串 `@84631331` 系列，已换成 F4 末尾的新串。


### V13 · ~~F8 的 v2.0.0 指纹表 / F4「234 项」/ 「版本 v2.0.0」/ 「买下就抬状态」~~（2026-09-27 傍晚作废）
v2.1.0 四项改进（见 F29）落地后，下列旧结论一律作废（新值见 F8 / F4 / F29）：

| 旧值 | 现值 | 依据 |
|---|---|---|
| `pet/__init__.py` 的 `__version__` = `2.0.0` | **`2.1.0`**（`installer.iss` 的 `AppVer` 同步） | F29 |
| `CHANGELOG.md` 首条 = `## v2.0.0` | **`## v2.1.0 — 2026-09-27 傍晚 · …`** | F29 |
| 冒烟 **234 项** | **323 项**（+2 大段共 41 条，另 3 条改写） | F4 |
| `POMODORO_CHOICES=(25, 50)`，**单位是分钟** | **`(60, 300, 1500, 3000)`，单位是秒** | F29 / `pet/menu.py` |
| `Pomodoro.remaining_minutes` / `total_minutes` | **`remaining` / `total_seconds`**（单位改秒） | F29 / `pet/pomodoro.py` |
| 「小卖部买下就抬状态」（v2.0.0 `buy()` 的行为） | **买下只进背包、状态不变**；抬状态是 `use_item()` 的事 | F29 / `pet/window.py` |
| 「番茄钟只有 25 / 50 两档」 | **1 秒 ~ 2 小时**，三列滚轮自选，另加 4 个快捷档位 | F29 |
| 「状态只在商店菜单里看得到」 | **三个显示面**：状态面板 / 鼠标划过气泡 / 托盘 tooltip | F29 |
| `game/minigame.py`：方块**一碰就碎**、`SCORE_PER_HIT` 等价于「碎一块 10 分」 | 方块有**耐久**（封顶 6）；敲一下 **5 分**；**没敲碎的方块会挡球** | F29 |
| 「弹跳得分很无聊：贴着一个地方反复跳就行」 | 连击倍率（3 连 ×2 / 6 连 ×3）+ 掉落道具 + 轮次递增，位置与高度重新变得有意义 | F29 |
| 中文字体回退链定义在 `game/common.py` 里 | **搬到 `pet/uitheme.py`**，`game/common.py` 改为转出（解 `pet → game → pet` 循环） | F29 |
| `pet/menu.py` 只在「小卖部」里显示金币 | 另加 `add_bag`（🎒 背包）与「状态 / 背包面板」两项 | F29 |
| 弹跳得分 HUD 的坐标散在 `_paint_hud_numbers` 的 `drawText` 实参里 | 抽成 `HUD_ZONES` / `HUD_FONT` / `HUD_WIDEST` / `HUD_WIDEST_PX` 四张表，绘制函数不写坐标 | F29 |
| 「HUD 排版这种事只能靠眼睛看」 | 有五段文字各占多少 x 是可算的 —— 已有 **9 条纯几何断言**盯着（不查字体度量） | F4 / F29 |
| 「offscreen 平台跑测试最省事，抓图也能用」 | **抓图不能用**（没有字体，全画成方框）；**字体度量也不能信** | F29 第五节 |

> **旧 `@版本` 提醒**：F1…F28 条目里写在 2026-09-27 之前的 `@` 代码一律失效，
> 以 **F8 的新指纹表**为准（2026-09-27 傍晚重采）。


### V14 · ~~F8 的 v2.1.0 指纹表 / F4「323 项」/「版本 v2.1.0」/「状态三个显示面」/「划过气泡」/「两个游戏」~~（2026-09-27 深夜作废）
v2.2.0（见 F30）落地后，下列旧结论一律作废（新值见 F8 / F4 / F9 / F30）：

| 旧值 | 现值 | 依据 |
|---|---|---|
| `pet/__init__.py` 的 `__version__` = `2.1.0` | **`2.2.0`**（`installer.iss` 的 `AppVer` 同步） | F30 |
| `CHANGELOG.md` 首条 = `## v2.1.0` | **`## v2.2.0 — 2026-09-27 深夜 · …`** | F30 |
| 冒烟 **323 项** | **405 项**（+2 大段共 62 条，另 3 条气泡断言换成防回退） | F4 |
| 状态值有**三个显示面**（菜单 / 面板状态条 / 划过气泡） | **两个**：右键菜单第一行 + 托盘 tooltip，**都要主动点** | F30 第一节 |
| `pet/panel.py` 有 `StatusBubble`（划过弹 178px 卡片）+ `VitalsStrip` | **两者都已删除**，只剩 `BagPanel` + 一行 `where` 灰字 | F30 第一节 |
| `PetWindow` 覆盖了 `enterEvent` | **不再覆盖**（`PetWindow.enterEvent is QWidget.enterEvent`），划过无任何反应 | F30 第一节 |
| `pet/panel.py` 窗口标题「桌宠 · 状态 / 背包」 | **「桌宠 · 背包」** | F30 第一节 |
| 「菜单里只有 **1** 个子菜单（一起玩游戏）/ V13 写的"3 个" | **4 个**：小卖部 / 背包 / 番茄钟 / 一起玩游戏（V13 那行漏算了「背包」，是笔误） | F30 第六节 |
| `GAMES` = **2 款**（bounce / catch） | **4 款**（+ `runner` 跑一跑 / `2048` 狗粮 2048） | F9 / F30 |
| 小游戏总共**两个** | **四个** | F9 |
| HUD 登记表只有 `minigame.py` 一份、算术各写各的 | 抽到 **`game/common.py`**：`zone_spans` / `overlapping_zones` / `measure_zone_widest`，三款游戏共用 | F30 第五节 |
| `HUD_WIDEST_PX` 可以"照着经验估" | **只能量** —— 估出来的三处全偏小，2048 的 `tile`/`undo` 差 1px 叠字 | F30 第四节 |
| HUD 断言只到"墨迹不叠" | 升级为"**槽位本身不叠**"（更严） | F30 第四节 |
| 「金币折算只有一把尺子 `coins_for`」 | **两把**：`coins_for`（分数 // 10）与 `coins_for_tile`（2048 专用，按最大格子） | F9 / F30 第三节 |
| `reports/` 里界面验收图只有 `v21_ui.png`（1120×2451） | **+`v22_ui.png`（1120×2125）**；`v21_ui.png` 改成 1120×2555（撤气泡那节、④ 换抓右键菜单） | F7 / F30 |
| 冒烟项数在各个 README 里写作 314 | **405**（后为 **424**，见 V15） | F4 |

> **另外纠正 V13 的一处笔误**：V13 说 v2.1.0 的子菜单是"**3 个**（小卖部 / 番茄钟 /
> 一起玩游戏）"，漏了同版加的「背包」—— v2.1.0 起实际就是 **4 个**（见上表）。
> 这类"改了一处忘了另一处"正是本文档要靠 F8 指纹 + 冒烟断言一起守的原因。

> **旧 `@版本` 提醒**：F1…F30 条目里写在 2026-10-08 之前的 `@` 代码一律失效，
> 以 **F8 的新指纹表**为准（2026-10-08 重采）。


### V15 · ~~F8 的 v2.2.0 指纹表 / F4「405 项」/「版本 v2.2.0」/「喂一口白送 26 饱食」/「逗它玩 +22」~~（2026-10-08 作废）
v2.2.1（见 F31）落地后，下列旧结论一律作废（新值见 F8 / F4 / F31）：

| 旧值 | 现值 | 依据 |
|---|---|---|
| `pet/__init__.py` 的 `__version__` = `2.2.0` | **`2.2.1`**（`installer.iss` 的 `AppVer` 同步） | F31 |
| `CHANGELOG.md` 首条 = `## v2.2.0` | **`## v2.2.1 — 2026-10-08 · …`** | F31 |
| 冒烟 **405 项** | **424 项**（+1 段共 19 条） | F4 |
| 「喂一口」**白送 26 饱食**、0.35 秒一次、不看背包 | **每天头一次免费，之后吃背包里第一样"吃的"**；没有就灰掉 | F31 |
| 「逗它玩」心情 **+22** | **+8**（精力消耗不变，仍是 3.3） | F31 |
| 饱食的入口是"喂一口 / 肉干 / 豪华大餐"三条，其中第一条不要钱 | 第一条**每天只免费一次**，之后和另两条合流（都吃背包） | F31 |
| `Config` 没有"每天一次"这类字段 | **`free_feed_day: str = ""`**（`DAY_FMT` 日期串；老存档读进来是空串 = 当天还能白喂一次） | F31 |
| `Bag` 只有 `count` / `total` / `entries` | **+`first_food()`**（跳过不是"吃的"的商品） | F31 |
| `pet/menu.py` 的 `add_interactions` 里「喂一口」是写死的一行文字 | **文字与可用状态当场按 `PetWindow.feed_plan()` 算**；新增 `is_food()` / `_FeedPlan` Protocol / `feed_text()` | F31 |
| `pet/vitals.py` 的 `PLAY_GAIN` 是 22、精力消耗写作 `PLAY_GAIN * 0.15` | `PLAY_GAIN` = **8**，精力消耗抽成独立的 **`PLAY_ENERGY_COST = 3.3`**（不跟收益缩） | F31 |

> V14 里那条"**`HUD_WIDEST_PX` 只能量不能估**"继续有效，没有被本轮推翻。
