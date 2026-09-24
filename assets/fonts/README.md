# assets/fonts/ —— 自定义字体（可选，当前使用系统字体）

文字渲染目前走**系统字体回退链**（`main.py` 的 `apply_ui_font()`），按顺序尝试：

```
Microsoft YaHei UI -> Microsoft YaHei -> SimHei -> SimSun -> sans-serif
```

Windows 上必定命中第一个，所以**中文能正常显示**，不需要放字体文件。

## 为什么要有这个目录

两个实际场景：

1. **换机器演示**：万一目标机器字体缺失（精简版系统、英文版系统），中文会变方框。
   把一份字体丢进来并在 `apply_ui_font()` 里用 `QFontDatabase.addApplicationFont()` 注册，
   就能彻底摆脱对系统字体的依赖。
2. **打包分发**：想统一观感时，附字体是唯一可靠的做法。

## 注意授权

**中文字体版权问题比英文字体严重得多。** 微软雅黑（Microsoft YaHei）是随 Windows 授权的，
不能随你的程序再分发。要内置的话选明确开源可商用的：

- 思源黑体 / Noto Sans CJK SC（SIL OFL）
- 霞鹜文楷 LXGW WenKai（SIL OFL）
- 寒蝉正楷体（SIL OFL）

课程作业交上去一般没事，但如果你以后把这个程序放出去给人下载，这一条必须过一遍。
