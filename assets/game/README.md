# assets/game/ —— 小游戏专属素材

这个目录**空了也能玩**。没有对应素材时，游戏用 `QPainter` 画一个占位形象顶上去；
你把真素材丢进来，游戏自动改用素材，**不用改任何代码**。

当前状态：**素材已到位**（2026-09-21 下午入库）。

```
assets/game/
├── bg_bounce.png            弹跳得分 · 粉色舞台背景
├── bg_catch.png             接狗狗   · 蓝天草地背景
├── catcher_00..07.png        8 帧  小黄狗（底部接板，张臂）
├── puppy_a_00..09.png       10 帧  小白狗（第 1 套，素白）
├── puppy_b_00..09.png       10 帧  小白狗（第 2 套，戴蝴蝶结）
├── puppy_c_00..09.png       10 帧  小白狗（第 3 套，举爪）
└── bomb_*.png               —— 没有，炸弹仍是代码画的线条卡通占位
```

### 这几张是怎么来的（可复现）

素材库 `assets/raw/_library/0921_1530_线条小狗GIF/` 里挑的（198 个里挑 4 个），
`$L` = 那个目录：

```bash
PY="C:/Users/华硕/.workbuddy/binaries/python/envs/default/Scripts/python.exe"

"$PY" tools/prep_sticker.py "$L/xian_tiao_xiao_5197_线条小狗C (82).gif" --state catcher --size 160 --keep 10 --game
"$PY" tools/prep_sticker.py "$L/ke_ai_xian_tiao_246_可爱线条小狗.gif"        --state puppy_a --size  96 --keep 10 --game
"$PY" tools/prep_sticker.py "$L/ke_ai_xian_tiao_222_可爱线条小狗.gif"        --state puppy_b --size  96 --keep 10 --game
"$PY" tools/prep_sticker.py "$L/xian_tiao_xiao_5207_线条小狗C (92).gif"      --state puppy_c --size  96 --keep 10 --game
```

* `--keep 10` 只对超过 10 帧的源生效 —— catcher 的源本来就只有 8 帧，所以是 8 张。
  三套小白狗分别来自 18f / 16f / 16f 的源，都被截到 10 帧。
* 输出画布 160（catcher）/ 96（puppy），给的是**比显示尺寸大一档**的值
  （显示 104 / 58），留缩放余量。
* 上面四条命令**逐字节复现了当前的文件**（2026-09-21 实测，`cmp` 全等）。

背景图来自 `assets/raw/_library/0921_1530_背景图/`（2848×1600 的竖版插画），
下面 `$B` 就是那个目录：

```bash
"$PY" tools/prep_bg.py "$B/1789972701282_edit_459032437780997.png" --name bg_bounce --ground 0.87
"$PY" tools/prep_bg.py "$B/1789972756638_edit_459096029599217.png" --name bg_catch  --ground 0.78
```

同样**逐字节复现**。（`--ground` 是地平线在源图里的纵向位置，得目测给，
程序推不出来 —— 天空顶部也是"亮且平"的色块，自动检测会认成地面。）

> ⚠️ 这批源 GIF 是爱给网的**预览图**，带一层不透明的浅灰斜排 `aigei.com` 水印。
> 在 58px 的显示尺寸下看不出来，但放大到 2 倍以上能看见。
> 换更干净的同款素材时，照着上面四条命令重跑即可，不用改代码。

---

## 一、命名：前缀决定它是谁

游戏按**文件名前缀**找素材：

| 前缀 | 是什么 | 显示尺寸 | 建议画布 |
|---|---|---|---|
| `catcher_` | 底下接东西的**小黄狗** | 104×78 | 128×128 |
| `puppy_` | 天上掉下来的**小白狗**（接了 +10 分） | 58×58 | 128×128 |
| `puppy_a_` / `puppy_b_` / … | 同上，**另一套小白狗**（多套轮换） | 58×58 | 128×128 |
| `bomb_` | 天上掉下来的**炸弹**（接到扣 1 血） | 54×54 | 128×128 |

* **后缀序号从 0 开始，补零到两位**（`_00`、`_01`…），和桌宠贴图同一套规范，
  程序靠它排序。
* 每套**至少 1 张**，多张就按 **8 fps** 循环播放（`FRAME_FPS`）。
* **每套互相独立**：只放 `bomb_` 也行，那样只有炸弹换成你的图，另外两个继续用占位。
* 长宽比不会被拉伸 —— 绘制时按比例居中放进格子里。

### 小白狗为什么可以有多套

`puppy_a_` / `puppy_b_` / `puppy_c_` 三套是**轮换**用的：每次掉落随机挑一套，
所以天上会同时出现几种不同的狗，比清一色同一只热闹。

**套数不是写死的** —— 前缀靠扫目录得出（`puppy_a_00.png` → `puppy_a`），
所以想加第 4 套，直接把 `puppy_d_00.png` 丢进来就行，**不用改代码**。
一套都没有时才退回代码画的占位。

> 探测逻辑在 `game/catcher.py` 的 `discover_puppy_prefixes()`；
> 目录读不出来时退回内置的 `PUPPY_PREFIXES` 兜底表。

---

## 二、背景图

两个游戏各有一张背景：

| 文件名 | 给谁 | 画面 |
|---|---|---|
| `bg_bounce.png` | 弹跳得分 | 粉色舞台 / 阶梯圆台 |
| `bg_catch.png` | 接狗狗 | 蓝天、云、草地 |

* 背景图**必须裁成窗口尺寸 780×580**，而且图里的**地平线要正好落在 y=534**
  （那是游戏的 `GROUND_Y`，接板站在这里、落体掉到这里算漏接）。
  直接用原图会被 `load_background()` 拉伸铺满，地平线就跑偏了 ——
  裁图用专门的工具：

```bash
# --ground 是"地平线在源图里的纵向位置"（0=顶 1=底），裁完预览一眼对不对
python tools/prep_bg.py 大图.png --name bg_catch --ground 0.78 --preview
```

* 没背景图时，两个游戏各自回退到**代码画的渐变**（不会崩、不会空屏）。
* 换过背景图之后，同进程内需要调一次 `game.common.clear_background_cache()`，
  否则还拿旧的缓存（正常重启程序不用管）。

---

## 三、怎么把 GIF 变成这些 png

用 `tools/prep_sticker.py`，加一个 `--game` 就会写进这个目录，
`--state` 起的名字就是前缀：

```bash
python tools/prep_sticker.py 小黄狗.gif --state catcher --game --size 160
python tools/prep_sticker.py 小白狗.gif --state puppy_a --game --size 96
python tools/prep_sticker.py 小白狗2.gif --state puppy_b --game --size 96
python tools/prep_sticker.py 炸弹.gif   --state bomb   --game --size 96
```

参数怎么来的：

* **`--size`** —— 给比显示尺寸大一档的值，留缩放的余量（catcher 显示 104 宽，
  所以用 160；puppy 显示 58，用 96）。素材自带的透明边由工具裁掉。
* **`--anchor center`** —— 掉下来的东西是从画布**中间**取内容的（默认值）。
  桌宠那套用 `--anchor bottom`，因为它要站在地平线上，游戏里的落体不需要"站"。
* **`--keep 10`** —— 表情包帧数太多时只留 10 帧，免得一套素材就撑出十几 MB。
* **`--game`** —— 输出到 `assets/game/`。加 `--custom` 则输出到
  `%APPDATA%\DesktopPet\game\`（用户数据目录，优先级更高，不影响程序自带的）。

背景图走另一个工具（`prep_bg.py`），见上一节。

---

## 四、优先级

和桌宠素材一个套路（见 `pet/config.py` 的 `game_asset_dir()`）：

```
%APPDATA%\DesktopPet\game\   （有 png 就整体优先）
        ↓ 没有
assets/game/                 （程序自带，随版本走）
```

改完素材**要重启桌宠**才生效 —— 素材是在建游戏窗口时读的。

---

## 五、桌宠素材和游戏素材是两回事

| | 桌宠素材 | 游戏素材 |
|---|---|---|
| 目录 | `assets/pet/` 或 `custom_pet/` | `assets/game/` 或 `%APPDATA%\DesktopPet\game\` |
| 命名 | `<状态>_序号.png`，状态固定 6 个 | `<前缀>_序号.png`，前缀自由（可多套） |
| 缺了会怎样 | 整个目录被接管，缺的状态借 `idle` 兜底 | 只有缺的那一套退回代码画的占位，互不影响 |

所以**换桌宠素材不会动到游戏**，反过来也一样。

## 六、炸弹为什么还是代码画的

素材包里没有合适的"炸弹"（线条卡通风、和狗同一套描边），所以
`game/catcher.py` 里的 `_draw_bomb_placeholder()` 按**线条卡通**的规则画了它：
粗描边 + 纯色填充 + 柔和的灰蓝球体（不用纯黑，压在浅色天空上不突兀）。
丢一个 `bomb_00.png` 进这个目录就会自动被它顶掉。

## 七、「弹跳得分」用不用这个目录

用，但只用到**背景图**。游戏里玩家就是桌宠本人（取 `idle` 第 0 帧），
方块和粒子是代码画的 —— 所以这个目录里除了 `bg_bounce.png`，
没有其它属于弹跳得分的素材。
