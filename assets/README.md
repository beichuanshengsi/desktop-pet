# assets/ —— 素材总入口

这一层是**随程序分发**的素材根目录（只读）。但**运行时真正读的不一定在这儿** ——
见下面「两套目录」那张表。

> 加一类新素材只用在 `pet/paths.py` 的 `ASSET_KINDS` 里**登记一行**，
> 三个路径函数（`asset_dir` / `user_asset_dir` / `resolve_asset_dir`）就都认它了。
> 这是"易于加素材"的关键设计，细节见 `pet/paths.py` 的模块注释。

---

## 目录地图

```
assets/
├── icon.png / icon.ico      应用图标（托盘 / 窗口 / 任务栏；由当前素材裁头部生成）
├── pet/                     宠物动作帧             → pet/README.md
├── game/                    小游戏素材（两张背景 + 小黄狗 + 三套小白狗）→ game/README.md
├── sfx/                     音效（可选；当前完全静音）
├── fonts/                   内置字体（可选；当前用系统字体回退链）
└── raw/                     原始素材与素材库       → raw/README.md
    ├── inbox/               投递口：下载来的 GIF 先丢这里
    ├── _library/            整批下载的素材库归档（只留档，不参与加工）
    ├── _archive/            加工完的原始输入归档 ⚠️ 你的原稿，别整个删
    └── _snapshots/          历史成品快照（原图丢了时靠它重摆）
```

`raw/` 里的东西**不计入版本库**（体积大、带版权），只保目录结构与各层 README。

## 两套目录（最容易搞混的地方）

每类素材都有**两个候选位置**，**用户目录优先**：

| 类别 | 随程序分发（只读） | 用户自定义（可写、优先） |
|---|---|---|
| `pet` | `assets/pet/` | `<数据目录>/custom_pet/` |
| `game` | `assets/game/` | `<数据目录>/game/` |
| `sfx` / `fonts` | `assets/sfx/` · `assets/fonts/` | ——（没有用户覆盖层） |

- `<数据目录>` = 开发态是项目根目录，打包后在 `%APPDATA%\DesktopPet\`。
- **"接管"不是"合并"**：用户目录里只要有一个匹配文件，内置目录就整个不读。
  好处是换素材不会"一半新一半旧"；代价是缺哪个状态要自己补齐
  （缺的状态按 `AssetBank` 的规则借 `idle` 兜底，不会崩）。

## 放素材的三步

```bash
# 1. 下载来的东西全部丢进投递口（不用分类、不用改名）
#    —— 或者直接把文件拷进 assets/raw/inbox/
# 2. 先看方案，不动文件
python tools/intake.py
# 3. 确认无误后落位（默认写 custom_pet/，不碰内置）
python tools/intake.py --apply
```

单件加工用 `tools/prep_sticker.py`（`--custom` 写用户目录、`--game` 出小游戏素材）；
背景大图用 `tools/prep_bg.py`。**换素材全程不用改代码。**

## 命名规范（程序靠文件名归类）

```
<状态>_<序号>.png              idle_00.png  walk_01.png  …          单套
<状态>_<套名>_<序号>.png        poke_a_00.png  walk_b_03.png  …      多套（随机演）
```

- 状态名 = 贴图前缀，**唯一来源是 `pet/behavior.py` 的 `State`**。
- 套名用字母，**最后一段永远是帧序**（所以 `poke_01` 是默认套第 1 帧，不会被当成套名）。
- 游戏素材的命名见 `game/README.md`；游戏里的"套"是靠扫目录自动发现的，加第 4 套不用改代码。

```bash
# 某类素材当前加起来有多少帧 / 有哪些套（改素材后跑这个自检）
python tools/smoke_test.py
```
