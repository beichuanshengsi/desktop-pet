# assets/pet/ —— 宠物贴图（随程序分发的内置目录）

`pet.assets.AssetBank` 启动时扫这个目录，按**文件名前缀**归类成动作帧。

> **这里是"只读"的内置素材位。** 运行时不一定会读它 —— `pet.paths.resolve_asset_dir("pet")`
> 的规则是：只要用户目录 `custom_pet/` 里有任意一张 png，就**整体接管**，这个目录就不读了。
> 只想给这台机器换素材，请写 `custom_pet/`（见文末「三种放素材的方式」），别改这里。

## 命名规范

```
单套（最常见）   <状态>_<序号>.png           idle_00.png  idle_01.png …
多套（同一动作几种演法） <状态>_<套名>_<序号>.png   poke_a_00.png  poke_b_00.png …
```

- **套名用字母**，最后一段永远是帧序 —— 所以 `poke_01` 是默认套的第 1 帧，不会被误认成套名。
- 序号按**数字排序**（不是文件系统顺序），位数不必统一，连续就好。
- 不带套名的那一套叫「默认套」（`pet.assets.DEFAULT_SET`，值是空串 `""`）。

多套的用途：窗口每次触发互动时会**随机挑一套**（`PetWindow._pick_set`，且排除上一次用过的那套），
一套贴图能演出好几种反应。**加套不用改代码** —— 按上面的命名丢文件进去就自动生效。

## 状态清单

动作名（= 贴图前缀）**只有一份定义**：`pet/behavior.py` 的 `State` 枚举。
`pet.assets.STATES` 与 `tools/prep_sticker.py` 的白名单都从它派生 ——
加一个动作只需改 `behavior.py` 一处。

| 状态 | 用途 | 触发方式 |
|---|---|---|
| `idle` | 待机 | 默认常态 |
| `walk` | 自主漫步 | 计时到且掷骰通过（可关） |
| `drag` | 被鼠标拎起来 | 按住拖动 |
| `fall` | 松手后下坠 | 松手且开了「重力下坠」 |
| `poke` | **「逗它玩」** | 左键点一下 |
| `feed` | **「喂一口」** | 右键菜单 → 喂一口 |

小游戏里的玩家角色用的是 `idle` 的第 0 帧（见 `game/minigame.py`），和 `poke` 无关。

> `poke` 以前叫 `jump`（那会儿两个互动动作共用一套"蹦一下"的帧，换素材后逗它玩
> 和喂一口长得一模一样）。2026-09-21 拆成两个状态时一起改了名。

## 容错规则（改素材前先知道这个）

- **某个状态缺帧不会崩**：直接借用 `idle` 的帧兜底，`AssetBank.fallback_used` 里会记下用了兜底的状态。
- **连 `idle` 都没有**：把目录里任意 PNG 拿来用，保证窗口有东西可显示。
- 所以可以**只做 `idle` 一套先跑起来**，之后再逐个补状态。

## 现在这个目录是空的（只剩本 README）

2026-09-22 起，程序**不再自带"代码画"的贴图**了：那两套脚本生成的形象
（`pet/assetgen.py` classic / `pet/assetgen_line.py` line）连同生成器
`tools/gen_assets.py`、风格注册表 `pet/styles.py` 一起删掉了。
程序只读真实素材，现役素材在 `custom_pet/`（见其 README 的复现命令）。

目录本身**保留**是故意的：它是"内置素材"的标准落点，
`tools/prep_sticker.py` / `tools/intake.py --builtin` 都可以往这里写。

## 三种放素材的方式

```bash
# 1. 单件加工（推荐先看方案再落位）
python tools/prep_sticker.py assets/raw/我的表情.gif --state idle --auto-key --custom

# 2. 整批入库：把 GIF 丢进投递口，一条命令扫完落到各处
#    默认写 custom_pet/（不碰内置）；加 --builtin 才写 assets/pet/
python tools/intake.py                 # 先看方案，不动文件
python tools/intake.py --apply         # 确认后落位

# 3. 手工放：把 128×128 透明 PNG 按上面的命名规范丢进来即可
```

`--custom` 的目标目录是 `custom_pet/`（开发态在项目根，打包后在 `%APPDATA%\DesktopPet\`）：
只要里面有一个 `*.png` 就会**整体接管**内置素材，好处是换素材不会出现"一半新一半旧"。

## 尺寸与对齐

统一 **128×128**，透明底，角色**脚底对齐画布底边**（`prep_sticker.py --anchor bottom` 是默认行为）。
`--scale` 钉死绝对缩放比、`--zoom` 是本批基准的倍数 —— 跟错基准会把角色缩成一个点，
校验方法是看各状态加工出来的「内容高度」是否齐平。
显示尺寸由程序在运行时按 `Config.scale` 处理，源图不必为不同大小各做一套。
