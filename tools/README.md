# 资源提取脚本说明

脚本都只依赖 **Python 标准库**，可单独运行：

```bat
python tools\extract_textures.py [--game-dir <Celeste>] [--out-dir <dir>]
python tools\extract_dialog.py   [--game-dir <Celeste>] [--out-dir <dir>]
python tools\render_audio.py     [--game-dir <Celeste>] [--keep-raw] [--limit N]
```

`--game-dir` 未指定时读取环境变量 `CELESTE_DIR`，再回退到
`E:\Programs\Steam\steamapps\common\Celeste`。

## 0. `celeste_common.py`

三个脚本共用的部分（不单独运行）：

| 内容 | 说明 |
|---|---|
| `SCENES` | DEMO 的场景表：`id / title / subtitle / entries[]` |
| `read_language_export` | `.export` → 语言元数据 + `{条目: 文本}` |
| `parse_portraits` | `Portraits.xml` → `sfx / textbox / size / phonestatic / glitchy / expressions / animations` |
| `parse_frames` / `parse_goto` | `Calc.ReadCSVIntWithTricks`（`0-1,2*3,4`）与 `Chooser<string>.FromString`（`id:权重`） |
| `collect_portrait_usage` | 从文本里抽出 `{portrait ...}` 用法（角色 / 表情 / 左右侧） |
| `animation_closure` | 从用到的表情推出 `begin_/idle_/talk_` 以及它们 `goto` 指向的所有动画 |
| `write_js_global` | 输出成 `<script>` 可直接加载的 `window.CelesteDemo.assets.*` |

改场景只需要改这里的 `SCENES`，三个脚本会自动跟着变。

---

## 1. `extract_textures.py`

| 输入 | 输出 |
|---|---|
| `Content/Dialog/Fonts/chinese.fnt` + `chinese_0.png` | `fonts/chinese.json`、`fonts/chinese.js`、`fonts/chinese_0.png` |
| `Content/Graphics/Atlases/Portraits/textbox/*.data`（只取用到的皮肤 + `_overlay`） | `ui/textbox_<skin>.png` |
| `Content/Graphics/Atlases/Portraits/<sprite>/<frame>.data` | `portraits/<sprite>/<frame>.png` |
| `Content/Graphics/Atlases/Portraits/noise/*.data` | `portraits/noise/*.png`（仅当有 glitchy 立绘）|
| `Content/Graphics/Atlases/Gui0.data` + `Gui.meta` | `ui/textboxbutton.png` |
| — | `portraits.json` / `portraits.js`、`manifest.json` / `manifest.js` |

### 只导出需要的帧

`Portraits.xml` 里每个 `<portrait_x>` 有几十个动画，全部导出会有 660+ 张图。
脚本先扫 `SCENES` 的对话文本，得到「哪些立绘 × 哪些表情」，再用
`animation_closure` 沿 `goto` 展开，最后只解码这些动画引用到的帧：

```text
{portrait MADELINE left sad}
  -> idle_sad / talk_sad / begin_sad
  -> idle_sad 的 goto：idle_sad, idle_sad_shake
  -> idle_sad_blink 的 goto：idle_sad
```

`portraits.js` 里每个角色长这样：

```json
{
  "size": 160, "textbox": "madeline", "center": true,
  "phonestatic": "", "glitchy": false,
  "expressions": { "normal": 1, "sad": 3 },
  "animations": {
    "idle_normal": { "path": "normal", "delay": 0.1, "loop": false,
                    "goto": [["idle_normal", 5], ["idle_normal_blink", 1]],
                    "frames": [0, 0, 0, 0] }
  },
  "frameFiles": { "normal/0": "normal00.png" }
}
```

> `frames` 存的是索引，具体文件名由 `frameFiles` 映射——因为游戏自己在
> `Atlas.GetAtlasSubtextureFromAtlasAt` 里对索引做了左补 0 的尝试，文件名不一定固定宽度。

### Celeste `.data` 纹理格式

```text
u32le width
u32le height
u8    alphaFlag     (0 = RGB, 非 0 = RGBA)
重复直到像素填满：
  u8  runLength
  if RGBA:
      u8 alpha
      if alpha == 0:  （透明 run 优化，只写 1 个字节！）
         像素 = (0,0,0,0)
      else:
          u8 blue, u8 green, u8 red
  else:
      u8 blue, u8 green, u8 red
```

> 注意 `alpha == 0` 的分支：这是本项目最初解出「花屏」的原因。

### Celeste `.meta` 图集格式

`Atlas.AtlasDataFormat.CrunchBinary`：

```text
i32   version
string 源信息（.NET BinaryWriter 的 7bit 变长长度 + UTF-8）
i32   时间戳
i16   图集数量
每个图集：
  string 数据文件名（不含 .data，例如 "Gui0"）
  i16    条目数
  每个条目：
    string name
    i16 x, y, w, h, offsetX, offsetY, frameWidth, frameHeight
```

`Gui` 图集是 4096×4096，`textboxbutton` 的实际像素区域是 `28×12`，但 `frame` 是 `40×40`，
绘制时要按 `frame` 居中、再叠加 `offset`。

`Portraits.meta` 是另一种变体（每个条目指向一张独立 `.data`），只提供 `frame` 与偏移；
本项目用它把 1800×400 的文本框贴图对齐到 1688×272 的逻辑框。

---

## 2. `extract_dialog.py`

读取 `Content/Dialog/Simplified Chinese.txt.export`（`Language.FromExport` 的格式）：

```text
string Id, Label, IconPath
i32    Order
string FontFace
f32    FontFaceSize
string SplitRegex, CommaCharacters, PeriodCharacters
i32    Lines, Words, Count
Count × (string Key, string Value, string Cleaned)
```

为什么不用 `.txt`：游戏启动时优先加载 `.export`，它是游戏自己解析 `.txt` 后的最终结果，
已经完成：

- `[MADELINE left normal]` → `{portrait MADELINE left normal}`
- `{+MOUNTAIN}` 之类的嵌套条目展开
- 每个文本行之间自动插入 `{break}`

顺带一提：`FromTxt` 的 `[...]` 替换会作用到 **所有** 行，包括 `SPLIT_REGEX=` 元数据行，
所以中文的 `.export` 里分词正则已经变形：

- 原字符类 `[、|。|！|」|，]` 被拆成 `{portrait ...}|。|！|」|，`；
- `|` 于是从字面量变成了正则分支分隔符。

最终效果是：中文仍会在 `。` `！` `」` `，` 处分词换行（但 `、` 不再生效）。
本项目原样使用 `.export` 里的正则，才能和游戏分页完全一致。

同时解析 `Content/Graphics/Portraits.xml`：

- `sfx="madeline"` → 语音事件 `event:/char/dialogue/madeline`
- `<sfxs><normal index="1"/>...</sfxs>` → 表情名 → `dialogue_portrait` 序号
- `textbox="granny"` → 文本框贴图 `textbox/granny`
- `phonestatic="ex"` → 额外渲染 `phone_static_ex` 循环层
- `glitchy="true"` → 前端叠 `noise/` 噪点

输出：

- `assets/celeste/dialog/scenes.js`：`{ language, scenes:[{ id, title, subtitle, text, portraitUsage }] }`
  （页面实际加载这个文件；多条目场景用 `{break}` 拼起来）
- `assets/celeste/dialog/<scene>.json`：单场景，便于自查
- `assets/celeste/dialog/voice_jobs.json`：`{ voices:[{event,expression}], loops:[{event,name}] }`
- `assets/celeste/portraits_full.json`：全部角色 × 全部动画（仅调试用，前端不加载）
- 附加校验：对话里出现的每个字符是否都在字体中（缺字会打印警告）

---

## 3. `render_audio.py`

用游戏自带的 `lib64-win-x64/fmod64.dll` + `fmodstudio.dll` 播放原版事件并录音。

### 流程

1. `FMOD_Studio_System_Create`（版本常量用 PowerShell 读 DLL 版本，失败则穷举；
   本机实际接受 `0x00011000`）。
2. 在低层系统上 `FMOD_System_SetOutput(FMOD_OUTPUTTYPE_WAVWRITER)`，
   然后 `FMOD_Studio_System_Initialize(..., extradriverdata = 输出 wav 路径)`。
3. 依次加载 `Master Bank.bank` → `Master Bank.strings.bank` → `sfx.bank` → `ui.bank`，
   并启动 `snapshot:/dialogue_in_progress`（对话时压低音乐的官方快照）。
4. 对每个任务：`GetEvent` → `CreateInstance` → 设参数 → `Start` → 实时 `Update` 录音。
5. 释放系统后，把整段录音按每个任务的起止时间戳切分，再：
   - 去掉首尾静音；
   - 语音取约 2s，在目标长度附近找 20ms 能量最低点作为循环接缝，并做 10/12ms 淡入淡出；
   - `kind="loop"`（电话杂音）不裁切、不做淡入淡出，整段留作 loop 播放；
   - UI 音效保留完整包络。
6. 生成 `assets/celeste/audio/audio-data.js`：把所有 wav 转成单声道 base64 data URI，
   供 `file://` 直接播放。

### 踩过的坑

- **`FMOD_Studio_System_GetParameter` / `GetParameterByIndex` 有隐藏的 `value` / `finalvalue` 输出参数。**
  参数个数传少一个，DLL 会往野指针写，第一次调用看似成功，下一次调用就 access violation。
- **`FMOD_Studio_EventInstance_SetParameterValue` 的 `FMOD_STUDIO_PARAMETER_ID` 是 8 字节结构体按值传参**，
  在 ctypes/Win64 下不可靠，会破坏栈。改用 `SetParameterValueByIndex`。
- 这个 `fmodstudio.dll` 的 `FileVersion` 是 1.10.14，但 `FMOD_Studio_System_Create` 只接受
  `0x00011000`，与常规 `(major<<16|minor<<8|patch)` 编码不一致，所以脚本会先读版本再穷举兜底。
- `extradriverdata` 必须用 `ctypes.create_string_buffer` 持有内存；用
  `ctypes.cast(ctypes.c_char_p(...), c_void_p)` 会因临时对象被 GC 而得到悬空指针，
  表现为「根本没有生成 wav」。
- 参数索引（`dialogue_portrait` = 0、`dialogue_end` = 1）在脚本里通过「试录一小段并检查峰值」
  自动确认；如果换成别的 Celeste 版本，索引可能不同，脚本会自动交换重试。
- **顺序不是全局一致的**：FMOD 按 `ParameterId` 排序参数，所以 `event:/char/dialogue/ex`
  （第二章的电话角色）顺序正好相反。把它当成普通事件处理时 `dialogue_end` 会被设成 1，
  结果是「事件找到了、也有长度，但整段静音」。脚本里用 `SWAPPED_EVENT_PARAMS` 显式列出这类事件。
- 试图用 `FMOD_Studio_EventDescription_GetParameterByIndex` 直接按名字查索引很危险：
  这个函数的 `name` 输出缓冲区长度在不同 1.10.x 小版本里签名不同，签名猜错会写坏内存，
  表现是第一次调用返回值正常、第二次直接崩。本项目最终改用「已知索引 + 白名单交换」。
- `FMOD_Studio_EventDescription_GetParameter`（按名字查 ID）本身是安全的，可以拿来确认事件到底有
  几个参数（例如第二章电话事件只有 1 个可用表情值）。

### 常见问题

| 现象 | 处理 |
|---|---|
| `[错误] 找不到 Celeste 安装` | 设置 `CELESTE_DIR` 或传 `--game-dir` |
| `加载 bank 失败` | 确认 `Content/FMOD/Desktop` 下四个 bank 齐全；Everest 修改过音频的版本可能不兼容 |
| `两种参数索引组合都录不到语音` | 打开 `--keep-raw` 检查 `_raw.wav`，确认 `sfx.bank` 与 DLL 版本匹配 |
| 浏览器里没有声音 | 先点「点击开始」（浏览器要求手势解锁音频）；确认 `assets/celeste/audio/audio-data.js` 已生成 |
| 浏览器拦截 `file://` 资源 | 已通过内联 base64 规避；若仍异常，用 `python -m http.server` 走 HTTP |
