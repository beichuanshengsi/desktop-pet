# custom_pet/ —— 用户自定义贴图（覆盖内置素材）

**这里的东西优先级最高。** `pet/config.py` 里的 `pet_asset_dir()` 逻辑是：

```python
custom = data_dir() / "custom_pet"
if custom.is_dir() and any(custom.glob("*.png")):
    return custom          # 有自定义素材 -> 用它
return asset_dir() / "pet" # 否则 -> 用内置素材
```

也就是说：**只要这个目录里存在任意一个 `.png`，内置素材就被整体接管。**
（注意是"接管"而不是"合并"——所以要么搬全套，要么接受缺失状态借用 `idle` 兜底。）

## 为什么单独放一份而不是直接改 assets/pet/

| | `assets/pet/` | `custom_pet/` |
|---|---|---|
| 性质 | 程序内置资源，只读 | 用户数据，可写 |
| 打包后位置 | PyInstaller 解包临时目录（**只读**） | `%APPDATA%\DesktopPet\custom_pet\` |
| 适合 | 开发时改内置素材 | 用户换自己的形象、测试多套素材 |

打包后的程序目录通常不可写，所以**用户自定义的东西不能放在 assets 里**，这就是分开的原因。

## 放素材的两种方式

```bash
# 方式一：用预处理工具直接写进来（推荐）
python tools/prep_sticker.py assets/raw/我的表情.gif --state idle --auto-key --custom

# 方式二：手工把 128×128 透明 PNG 拖进来，命名遵循 <状态>_<序号>.png
#         想给同一个动作配多套（每次随机演一套）就写 <状态>_<套名>_<序号>.png，
#         详见下面「一个动作多套素材」
```

## 换回来

想恢复内置素材，把这个目录里的 `*.png` 删掉即可 —— 目录本身留着没问题，
判断条件是"里面有没有 png"，空目录会自动回落。

## facing.json：素材是朝左还是朝右

这个目录里的 `facing.json` 记两件事 —— **贴图原图朝哪一边**，以及**哪几套例外**：

```json
{
  "base": "left",
  "sets": { "walk_a": "right" },
  "note": "线条小狗素材：脸在左、后腿在右。walk_a 那套原图方向相反，按套单独声明"
}
```

程序只知道"往哪走"，不知道"素材画的是哪一边"；两者对不上，狗就会倒着走，
而且从代码上看不出来。所以绘制时才需要这份声明：**行走方向与素材朝向不一致**
才水平镜像。删掉这个文件也不会崩，只是按默认值（朝右）处理。

`base` 是**整个目录**的默认值。但一个动作可以有好几套素材，而各套是分开下载、
分开抠图的，**原图方向未必一致** —— 那种套就写进 `sets` 单独覆盖。
`sets` 的 key 是**素材前缀**（`walk_a`，跟 `walk_a_00.png` 对得上），不是裸套名
（裸的 `a` 在 `walk_a`/`poke_a`/`feed_a` 里重名，一定会串台）。

改朝向的方式（任选其一）：

```bash
python tools/set_facing.py                     # 看当前值，以及各套左右走要不要镜像
python tools/set_facing.py flip                # 把默认朝向翻过来（各套的相对关系保持）
python tools/set_facing.py flip --set walk_a   # 只翻某一套
python tools/set_facing.py left --set walk_a   # 让某一套改回跟随默认
```

或者右键桌宠 → `左右翻向（走反了改这个）`。

判断方法：看素材里**头在哪一侧**。当前这套「线条小狗」脸在左边、后腿在右下方，所以朝左。
（`walk` 默认套是正面张臂的构图，左右镜像看着差不多 —— 声明成哪边都不太出错。）

**`walk_a` 是唯一的例外**：那套原图是**朝右**画的（前爪朝右举起、小尾巴甩在左下），
和目录里其余素材相反，所以单独声明成 `right`。它原先当 `idle` 用，那时候看不出来；
2026-09-22 挪去做走路素材后才暴露成"倒着走"（见 `tools/verify_facing.py` 的按套验收）。

---

## 当前用的是哪套素材

（这一节是记录，删掉不影响运行。）

**2026-09-21 下午换过一轮**：从爱给网批量下的 198 个「线条小狗」GIF 里挑了 5 个
重新做全部 5 个状态。整批原素材归档在
`assets/raw/_library/0921_1530_线条小狗GIF/`（见 `assets/raw/README.md` 的 `_library/` 约定），
上一轮的成品备份在 `assets/raw/_snapshots/pre_1550/`。

挑素材的结论：

| 状态 | 用的原始 GIF | 源尺寸/帧 | 输出帧 | 缩放比 | 内容高 |
|---|---|---|---|---|---|
| `walk_a`（2026-09-22 前是 `idle`） | `xian_tiao_xiao_6024_线条小狗.gif` | 360×360 / 14f | 14 | `--scale 0.4564` | 100 |
| `walk` | `xian_tiao_xiao_5197_线条小狗C (82).gif` | 500×493 / 8f | 8 | `--scale 0.4000` | 94 |
| `drag` | `xian_tiao_xiao_6588_线条小狗害怕.gif` | 240×240 / 23f | 23 | `--scale 0.7383` | 95 |
| `poke` | `xian_tiao_xiao_3411_线条小狗 (307).gif` | 240×240 / 9f | 9 | `--scale 0.9000` | 99 |
| `feed` | `xian_tiao_xiao_218_线条小狗表情包动图 (2).gif` | 360×360 / 22f | 22 | `--scale 0.5046` | 109 |

**2026-09-21 傍晚又加了 4 套**，给「逗它玩」「喂一口」各配三种演法（每次都随机挑一套，
机制见下面「一个动作多套素材」）：

| 状态 | 用的原始 GIF | 源尺寸/帧 | 输出帧 | 缩放比 | 内容高 |
|---|---|---|---|---|---|
| `poke_a` | `xian_tiao_xiao_894_线条小狗开心动态表情包.gif` | 478×484 / 14f | 14 | `--scale 0.4200` | 100 |
| `poke_b` | `xian_tiao_xiao_129_线条小狗表情包动图 (9).gif` | 360×360 / 20f | 20 | `--scale 0.4150` | 99 |
| `feed_a` | `ke_ai_xian_tiao_219_可爱线条小狗.gif` | 282×282 / 18f | 18 | `--scale 0.4630` | 99 |
| `feed_b` | `xian_tiao_xiao_3382_线条小狗 (155).gif` | 360×360 / 16f | 16 | `--scale 0.4930` | 97 |

**2026-09-22：待机换成坐板凳，走路变成两套轮播**

| 状态 | 来源 | 帧数 | 处理 |
|---|---|---|---|
| `idle` | `assets/raw/_snapshots/线条小狗晃脚脚2_idle/` | 17 | `tools/rebuild_from_snapshot.py` 按 ×1.26 重摆 |
| `walk`（默认套） | 见上表 | 8 | 未动 |
| `walk_a` | `assets/raw/_snapshots/pre_0922/idle_*.png` | 14 | 就是上一版 `idle`，原样搬过来 |

原来那套站姿挥手并没有被丢掉，它转去当了 `walk_a`：走路时和默认套交替播
（起步挑一套、整段行走不换，机制见下面「一个动作多套素材」）。

**2026-09-23：新增 `sleep`（精力见底时趴下睡，v2.0.0）**

| 状态 | 用的原始 GIF | 源尺寸/帧 | 输出帧 | 缩放比 | 内容 |
|---|---|---|---|---|---|
| `sleep` | `xian_tiao_xiao_5191_线条小狗C (13).gif` | 250×250 / 22f | 22 | `0.7436`（自动） | 112×62（趴着的横长姿势）|

复现：

```bash
python tools/prep_sticker.py \
  "assets/raw/_library/0921_1530_线条小狗GIF/xian_tiao_xiao_5191_线条小狗C (13).gif" \
  --state sleep --auto-key --tolerance 4 --custom
```

> **这套 GIF 是黑底**（不是常见的白底），`--auto-key` 自动探到的键色就是 `#000000`。
> 上面这个命令与现役 22 帧逐像素比对，残余差异 0.115%（全在抗锯齿边缘），
> 几何（缩放比 / 贴底基线）完全一致。
> 来源是用**像素反查**确认的：拿现役帧当模板去比素材库 198 个 GIF，
> 该 GIF 的平均绝对差 7.17，第二名 46.8 —— 且它**正好也是 22 帧**，无歧义。
>
> **朝向不用单独声明**：放大对图确认原图**脸在左**，和 `facing.json` 的 `base="left"`
> 一致，所以 `sets` 里不需要加 `sleep`（对照图见
> `reports/materials/sleep_facing_check.png`）。同时提醒：这套源 GIF 是爱给网预览图，
> 带浅色斜排水印，成品约 96px 显示尺寸下看不见，放大才明显。
>
> 另外 `sleep` 的缩放比是**自动算**的（没像 idle/walk 那几套一样用 `--scale` 钉死），
> 因为趴下的姿势是"横长"的，并集宽（172px）成了限制维度，自动结果 0.7436 已经合适。
> 代价是它比其它动作**矮一截**（内容高 62，其余状态 94~109）——
> 这是睡姿本身的形状，不是缩放错了。

复现（幂等，可反复跑）：

```bash
python tools/rebuild_from_snapshot.py            # 默认 ×1.26
python tools/rebuild_from_snapshot.py --scale 1.2
python tools/rebuild_from_snapshot.py --dry-run  # 只看计划
```

> **为什么 idle 是 ×1.26。** 坐板凳那套的原始 GIF 已经没了
> （随 `_archive/0921_1228/` 那次误删），只剩 `_snapshots/` 里当年加工过的 128px 帧。
> 而那批帧当年为了迁就木凳的包围盒被压在 `scale 0.678`，**狗本体只有约 75 高**，
> 其它状态都在 100 上下。1.26 是「不裁到木凳」的上限：并集宽 100 × 1.26 = 126，
> 128 的画布还留得住凳子两端的描边（1.28 就正好贴边，再大就把凳子切了）。
> 重摆后狗本体约 94，和 `walk` 的 100 基本齐平。
> 注意判大小的依据是**狗本体**，不是「狗 + 凳子」的并集 —— 凳子占了约 20px，
> 按并集对齐会把狗缩小一圈。

复现命令（`$L` = 上面那个 `_library` 目录）：

```bash
python tools/prep_sticker.py "$L/xian_tiao_xiao_6024_线条小狗.gif"       --state walk_a --custom --scale 0.4564
python tools/prep_sticker.py "$L/xian_tiao_xiao_5197_线条小狗C (82).gif" --state walk --custom --scale 0.4000
python tools/prep_sticker.py "$L/xian_tiao_xiao_6588_线条小狗害怕.gif"   --state drag --custom --scale 0.7383
python tools/prep_sticker.py "$L/xian_tiao_xiao_3411_线条小狗 (307).gif" --state poke --custom --scale 0.9000
python tools/prep_sticker.py "$L/xian_tiao_xiao_218_线条小狗表情包动图 (2).gif" --state feed --custom --scale 0.5046

# 多套（每次触发随机挑一套）
python tools/prep_sticker.py "$L/xian_tiao_xiao_894_线条小狗开心动态表情包.gif" --state poke_a --custom --scale 0.4200
python tools/prep_sticker.py "$L/xian_tiao_xiao_129_线条小狗表情包动图 (9).gif" --state poke_b --custom --scale 0.4150
python tools/prep_sticker.py "$L/ke_ai_xian_tiao_219_可爱线条小狗.gif"          --state feed_a --custom --scale 0.4630
python tools/prep_sticker.py "$L/xian_tiao_xiao_3382_线条小狗 (155).gif"        --state feed_b --custom --scale 0.4930
```

`fall` 没有素材，会自动借 `idle` 的帧兜底。

## 一个动作多套素材（每次随机演一套）

同一状态可以放多套素材，命名 **`<状态>_<套名>_<序号>.png`**，套名用字母：

```
poke_00.png   poke_01.png …      默认套（不写套名）
poke_a_00.png poke_a_01.png …    套 a
poke_b_00.png poke_b_01.png …    套 b
```

加载逻辑在 `pet/assets.py` 的 `_split()`：**最后一段永远是帧序**，倒数第二段
若不是纯数字就当套名。于是 `poke_01` 是默认套的第 1 帧，不会被误认成套名 `01`。

窗口层（`pet/window.py`）在每次触发动作前调 `_pick_set()` 随机挑一套，挑的时候
**排除上次用过的那套** —— 正好两套就是完美轮换，三套也不会连着两次一样。
时长按**这次挑中的那一套**的帧数算，所以几套帧数不同也不会被掐断或空转。

`idle` 固定用默认套：它要在状态里停好几秒，中途换套画面会跳一下。
`walk` 反过来 —— 它**在起步那一刻**挑一套、整段行走不再换
（`PetWindow._track_state` 盯状态变化），所以看不到接缝，但每趟出门的走法会变。
walk 没有"点一下触发"的入口可以挂钩，只能靠主循环里比状态，这是它唯一的接入点。

各套的**原图朝向可以单独声明**（`facing.json` 的 `sets`，见上一节）—— 多套素材是
分开抠的图，方向未必一致，不声明就会有一半的时候在倒着走。

验收：

* `python tools/verify_variants.py` → `reports/variants.png`（poke / feed 连点，看有没有换套）
* `python tools/verify_walk_sets.py` → `reports/walk_sets.png`（反复起步，看走路的两套是否交替）
* `python tools/verify_facing.py` → `reports/facing_fix.png`（**逐套**验证"走哪边就朝哪边"）

### 为什么五套都要 `--scale` 钉死

这批素材的狗在源图里画得**大小差很多**（有的 360 画布上狗只占一小块，有的是
特写大脸）。如果让脚本自己按"刚好塞进画布"算，各套会得出 0.32~0.74 一堆不同的值，
切换动作时狗会突然变大变小。所以逐套量出目标缩放比、直接钉死，
让各状态的**内容高度**都落在 100 上下（上表最后一列）。

校验办法：量各状态的"内容高度"（`getbbox()` 的高度），齐平就对了。
**别用整体包围盒宽度当尺** —— 装饰性的花、闪光、旁边的第二只狗都会混进来。
`poke` 第一次入库时按素材自带的自动缩放做出来只有 81 高（比 idle 小一圈），
就是漏了这一步，后来单独调到 0.90 才齐。

### 四个已知的不完美（素材本身的限制，不是 bug）

1. **`walk` 是正面张臂的原地蹦跳，不是侧向走路循环** —— 这个素材包里**没有走路动画**
   （198 个全查过：横向位移大的都是平移/倾斜，不是迈腿）。用户确认
   "能看出在走路就行，不用侧面行走"，所以保留。要走得更像，得另找带侧面走路的素材。
2. **`drag` 素材里带一只小白狗当配角**（黄狗在甩开它）—— 包里没有"单独被拎起来"的素材。
   读起来是"挣扎"，可以用；介意的话换成 `xian_tiao_xiao_5132`（吊在单杠上）之类，
   但那套带杠铃道具。
3. **`poke` 的闪光帧贴到画布顶边** —— 素材内容并集 150px 高，画布只有 128，
   狗的大小按主体定，闪光只能超出后裁掉一点。
4. **`feed` 比其它状态大 9%**（内容高 109 vs idle 100）—— 吃饭那套低头前倾，
   构图本身占得更大，属正常范围。

> **上一轮（14:00 那批）的素材和参数**见 `assets/raw/_snapshots/pre_1550/`，
> 原 GIF 在 `assets/raw/_archive/0921_1400/`。白狗 `jump` 素材已退役
> （`PLAY` 状态删除、`jump_*` 从本目录移除）—— 好处是从那之后各状态
> **全是同一只米黄狗 + 红项圈**，不再有"点一下就换只狗"的突兀感
> （2026-09-23 新增的 `sleep` 也是同一只，见上）。


