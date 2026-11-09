# assets/sfx/ —— 音效

程序会出哪些声，**唯一定义在 `pet/sfx.py` 的 `EVENTS` 里**；
这个目录只是"按那些名字摆素材"。

```
assets/sfx/
├── pull_normal.wav       ← 程序实际读的就是这些（22 个事件）
├── pull_rare.wav
├── ……
└── alternates/           ← 备选池，程序不会读
    ├── pull_normal_2.wav
    └── …
```

## 怎么换

**主文件就是当前生效的那一份。** 想换成备选：

```bash
cd assets/sfx
cp alternates/pull_legend_2.wav pull_legend.wav     # 覆盖即可，不用改代码
```

换完**不用重启程序** —— 素材是第一次响的时候才读进内存的，换完下一次
触发就是新声音（想立刻听，重启最保险）。

`alternates/` 里的文件**只有一个用途**：给你挑。程序永远不读它，
所以放着不占运行开销。

## 音量与"设备常开"

播放用的是 `pygame.mixer`，音量是它的原生接口（`Sound.set_volume`），
所以**不再需要**把素材按音量另缩一份放进临时目录了。

它和以前那个 `winsound` 方案的真正区别在这里：**音频设备是常开的**。
`winsound.PlaySound` 每响一次都要开关一次音频设备，这在蓝牙耳机上是灾难 ——
A2DP 链路一空闲就断，重新唤醒要 0.3~1.5 秒。实测同一段 0.14 秒的素材：

| 后端 | 播一次实际耗时 |
|---|---|
| `winsound`（旧） | 1.48s / 0.51s / 0.53s |
| `pygame`（现在） | 0.137s / 0.139s / 0.141s |

多出来的那 0.4~1.4 秒全是设备开关的成本，听感就是"戳它一下，过一秒才响"。

代价是**只要音效开着，程序就一直占着音频设备**（喂一路循环静音把链路按住），
蓝牙耳机在你不用的时候也在收数据。所以设了空闲释放：**连续 3 分钟没响过**
就把设备还回去（`pet/sfx.py` 的 `IDLE_RELEASE`）。空闲后第一声仍然要等一次
握手，但只要在用它（戳、玩小游戏、抽卡），链路一直是热的。

## 开关与音量

右键桌宠（或托盘图标）→ 设置那一段：

| 菜单项 | 作用 |
|---|---|
| ☑ 音效 | 总开关。取消勾选 = 完全静音，**并且把音频设备还回去** |
| 音效音量 → 轻 / 中 / 响 | 三档，对应音量 35% / 65% / 100% |

两项都存进 `config.json`（`sfx_enabled` / `sfx_volume`），下次启动照旧。
**音效关着时「音效音量」整项不出现** —— 菜单里不留点不动的项。

默认是**开、中（65%）**。桌宠是常驻程序，出场满音量会让很多人直接把
整个功能关掉；但默认静音又等于没做，所以取中间。

## 加一个声音

1. `pet/sfx.py` 的 `EVENTS` 加一行（`key` 就是文件名，别带扩展名）；
2. 把 `<key>.wav` 丢进本目录；
3. 在要响的地方写 `sfxlib.play("<key>")`。

**没有第 4 步。** 素材没放全也不会出错：`play()` 对缺失的文件静默跳过
（`pet/sfx.py` 的 `missing()` 能列出还缺哪些），所以可以先接线、后补素材。

想让 `tools/intake.py` 自动把素材归好类，再往它的 `SFX_HINTS` 加一条关键词。

### 相对音量：`Sfx.gain`

`EVENTS` 那一行还可以给一个**相对用户音量的倍率**，落地即生效：

```python
Sfx("land_soft", "落地弹跳", "着地后弹起的那一下", gain=0.6)
```

用它而不是"再烘一个更轻的文件"，是因为**"弹跳比落地轻"是这个事件的性质、
不是素材的性质** —— 换素材时不该把这个关系丢掉。目前只有 `land_soft` 用它：
被甩出去的狗会连弹两三次，每次都跟落地一样响就成了砸桌子。

## 硬性要求

- **格式 `.wav`**（16bit PCM）。混音器对 wav 支持最稳；mp3 在部分 Windows
  环境直接不出声。
- **时长**：交互音 ≤ 1 秒；抽卡那四档可以放到 3.5 秒（那是"值得等"的一下）。
- **峰值统一归一化到 0.85**。二十几个音效来自多个素材包，峰值差很多，
  不统一的话"戳一下像放炮、抽到传说听不见"。**归一化在落地时就做掉**，
  运行时不逐事件补偿 —— 补偿写进代码就没人记得为什么，写进素材则换素材时自动带着。
- **首尾淡入淡出**：没被裁过的素材留 20 ms；**被裁过的留 0.25 s**。
  长素材（几秒的闹铃）按 3 秒截断时，20 ms 的淡出等于硬切，听感是"啪"地断掉。

## 每个事件用的是哪条素材

「换素材时知道原来用的是什么」—— 单看文件名（`poke.wav`）是看不出来的，
所以把来源留在这儿。右边那列就是 `alternates/` 里的备选。
**被顶下来的旧主选一律顺延到备选列表末尾**，所以想退回旧音效也只需要
把那个编号拷回主文件名。

| 事件 | 主选（现在生效） | 备选 |
|---|---|---|
| `pull_normal` | Mixkit 精选 · `13_轻量清脆_闪光混合过渡-1秒` | Mixkit 精选 · `04_魔法闪光_闪光轻点`<br>Mixkit · `notification-2358-long-pop` |
| `pull_rare` | Mixkit 精选 · `02_魔法闪光_精灵魔法闪光-短` | Mixkit 精选 · `03_魔法闪光_魔杖闪光`<br>Mixkit · `coin-866-fairy-arcade-sparkle` |
| `pull_epic` | Mixkit 精选 · `10_游戏达成_魔法扫过-奖杯`　**本轮与传说对调** | Mixkit 精选 · `01_魔法闪光_魔法闪光-嗖`<br>Mixkit 精选 · `08_游戏达成_空灵精灵-胜利` |
| `pull_legend` | Mixkit 精选 · `05_魔法闪光_魔法过渡-上扫`　**本轮与史诗对调** | Mixkit 精选 · `07_游戏达成_胜利铃声`<br>Mixkit 精选 · `12_游戏达成_电子游戏-胜利` |
| `poke` | Mixkit · `notification-2358-long-pop`　**换成原备选 3** | Kenney ui · `click_001`<br>Kenney impact-sounds · `impactSoft_medium_000`　旧主选 |
| `feed` | Mixkit · `eating-2241-animal-eating-herb`　**换成原备选 2** | Mixkit · `eating-2252-hungry-man-eating`　旧主选<br>Kenney rpg · `chop` |
| `land` | Mixkit · `3088` 塑料小物件落地　**本轮重新找** | Mixkit · `2498` 落在沙上·闷　本轮重新找<br>Kenney impact-sounds · `impactSoft_heavy_000`　本轮重新找<br>Kenney impact-sounds · `impactSoft_heavy_001`　旧主选<br>Kenney impact-sounds · `footstep_wood_001`<br>Kenney impact-sounds · `impactWood_medium_000` |
| `land_soft` | Mixkit · `736` 卡通弹簧「嘣」　**本轮新增的事件** | Mixkit · `2894` boing 弹跳　本轮新增的事件<br>Kenney impact-sounds · `impactGeneric_light_000`　本轮新增的事件 |
| `coin` | Mixkit · `coin-1993-clinking-coins`　**换成原备选 2** | Kenney casino · `chips-handle-1`　旧主选<br>Mixkit · `coin-2069-winning-a-coin-video-game` |
| `sleep` | Mixkit · `2628` 竖琴缓扫·安心　**本轮重新找** | Mixkit · `3109` 舒缓铃音　本轮重新找<br>Juhani Junkala 512 · `sounds_pause1_in`（8bit 下沉）　本轮重新找<br>Kenney digital-audio · `lowDown`　旧主选<br>Kenney digital-audio · `phaserDown1`<br>Kenney ui · `switch_003` |
| `buy` | Mixkit · `coin-1999-gold-coin-prize`　**换成原备选 3** | Kenney ui · `confirmation_001`<br>Kenney rpg · `handleCoins`　旧主选 |
| `use_item` | Mixkit · `notification-2870-correct-answer-tone`　**换成原备选 3** | Kenney ui · `select_003`<br>Kenney ui · `confirmation_002`　旧主选 |
| `flip` | Kenney rpg · `bookFlip1` | Kenney casino · `card-slide-1`<br>Kenney casino · `card-fan-1` |
| `open_album` | Kenney casino · `cards-pack-open-1`　**换成原备选 3** | Kenney ui · `open_002`<br>Kenney rpg · `bookOpen`　旧主选 |
| `dissolve` | Kenney impact-sounds · `impactGlass_medium_000` | Kenney impact-sounds · `impactGlass_light_001`<br>Kenney ui · `scratch_004` |
| `equip` | Kenney rpg · `metalClick` | Kenney ui · `switch_001`<br>Kenney rpg · `metalLatch` |
| `score` | Kenney digital-audio · `pepSound1` | Kenney digital-audio · `phaserUp1`<br>Mixkit · `notification-2870-correct-answer-tone` |
| `break` | Kenney impact-sounds · `impactMetal_heavy_001` | Kenney impact-sounds · `impactWood_heavy_001`<br>Kenney digital-audio · `lowDown` |
| `levelup` | Kenney digital-audio · `powerUp1` | Kenney music-jingles · `jingles_NES00`　**game_over 现在用的就是它**<br>Mixkit · `notification-2574-software-interface-start` |
| `game_over` | Kenney music-jingles · `jingles_NES00`　**本轮改成「过关」的备选 2** | Kenney digital-audio · `lowThreeTone`<br>Kenney ui · `error_003`<br>Kenney digital-audio · `phaserDown1`　旧主选 |
| `pomodoro` | Mixkit · `995` 经典闹铃　**本轮重新找（闹钟方向）** | Mixkit · `988` 电子闹钟滴滴　本轮重新找<br>Mixkit · `1003` 清晨闹钟　本轮重新找<br>Mixkit · `bell-600-achievement-bell`　旧主选<br>Kenney impact-sounds · `impactBell_heavy_000`<br>Mixkit · `bell-3109-relaxing-bell-chime` |
| `toggle` | Kenney ui · `toggle_001` | Kenney ui · `switch_001` |

## 素材来源与授权

全部是**免登录、可商用**的素材，没有一处要求署名：

| 来源 | 用到的包 | 授权 |
|---|---|---|
| [Kenney](https://kenney.nl/assets) | Casino Audio / RPG Audio / UI Audio / Impact Sounds / Digital Audio | **CC0**（公共领域，连署名都不要求） |
| [Mixkit](https://mixkit.co/free-sound-effects/) | 落地、闹钟、竖琴、卡片、金币等 | Mixkit 免费授权：可商用、免署名；**唯一限制是不能把素材本身再分发** |
| [Juhani Junkala · 512 Sound Effects](https://opengameart.org/content/512-sound-effects-8-bit-style) | 落地、弹跳（8bit 那几份） | **CC0** |

Juhani Junkala 那份是开源游戏圈的事实标准（OpenGameArt 上 9 万多次下载），
很多开源项目直接用它。调查"别人的桌宠用什么音效"的结论写在
`docs/桌宠音效调研.md`。

⚠️ Kenney 与 Junkala 的原始素材分别是 `.ogg` / 8bit wav，落地时统一转成
16bit PCM wav（保持原采样率）。

> 授权上唯一要留意的是 Mixkit 那条"不能把音效当作素材再分发"。
> 这份目录是随程序一起走的**功能素材**，不是给你拿去二次分发的素材包 ——
> 正常发布没问题，但别把 `assets/sfx/` 单独打包发出去。
