# Celeste 对话复刻 DEMO

![图标](demo_img\madeline_talk.png)

用原生 HTML + Canvas 复刻《Celeste》的对话系统：逐字显示、标点停顿、变速指令、波浪字、
**角色立绘（原版 Sprite 动画）**、角色语音（原版 FMOD 事件渲染）、切换说话人时文本框收起/展开、
继续按钮闪烁与分页等待。页首可选择 4 段对话：

| # | 场景 | 对话条目 | 立绘 |
|---|---|---|---|
| 1 | 序章 · 奶奶 | `CH0_GRANNY` | Madeline / Granny |
| 2 | 第一章 · Theo | `CH1_THEO_A` + `CH1_THEO_B` | Madeline / Theo |
| 3 | 第二章 · 梦里电话 | `CH2_DREAM_PHONECALL` | Madeline(手机) / Ex(电话、噪点) / Badeline |
| 4 | 第三章 · Oshiro | `CH3_OSHIRO_SUITE` | Oshiro（含文本框面具叠层）/ Madeline / Badeline |

> ⚠️ 本仓库**不包含**任何《Celeste》原版资源。
> 运行前需要在你自己的游戏安装上执行一次提取脚本，资源会生成到 `assets/celeste/`
> （该目录已在 `.gitignore` 中排除）。

---

## 快速开始

1. 安装 **Python 3.8+**（Windows 即可，无第三方依赖）。
2. 运行一键提取：

   ```bat
   tools\extract_all.cmd
   ```

   默认读取 `E:\Programs\Steam\steamapps\common\Celeste`。
   如果游戏在别处：

   ```bat
   set CELESTE_DIR=D:\SteamLibrary\steamapps\common\Celeste
   tools\extract_all.cmd
   ```

3. **双击 `index.html`** 即可。

### 操作

| 输入 | 行为 |
|---|---|
| 空格 / 回车 / 鼠标左键 | 继续 / 翻页 |
| 打字过程中按一次 | 立即显示本页剩余文字（原版的 skip） |
| Esc / 鼠标右键 | 同「继续」 |
| `1` ~ `4` | 随时切换场景（页首选择面板也可点） |
| `R` | 重新播放当前场景 |
| 对话结束后点击 | 重新播放 |

URL 参数：

- `index.html?debug=1`：左上角显示场景、页码、节点索引、缓动、当前语音、当前立绘动画。
- `index.html?scene=ch1_theo`：直接进入某个场景（`ch0_granny` / `ch1_theo` / `ch2_phone` / `ch3_oshiro`）。
- `index.html?name=你的名字`：替换 `{savedata Name}`（第三、四章用到）。

---

## 实现与原版的对应关系

| 内容 | 原版实现（反编译参考） | 本项目 |
|---|---|---|
| 文本命令解析 | `Celeste.FancyText.Parse` | `js/fancytext.js` |
| 打字节奏 | 0.01s/字；逗号 +0.15；句号/感叹/问号 +0.3；`{>> x}` 改速；`<0.016s` 的延迟合并 | 同 |
| 分页 | 语言文件里每个文本行自动插入 `{break}`；`NewPage` 等待确认 | 同 |
| 行宽 | 以 `maxLineWidth = 1333` 计算换行，按有无立绘选 `1605`/`1333` 居中 | 同 |
| 文本框布局 | 1688×272；行高 `lineHeight-1`（63）；3 行/页；内边距 41.5 | `js/render.js` |
| 开合动画 | `EaseOpen` / `EaseClose` 0.4s + `textbox_*_in/out` 音效 | `js/textbox.js` |
| 立绘动画 | `Monocle.Sprite`：`begin_*` / `idle_*` / `talk_*`，`delay` + `goto` 权重选择 | `js/portrait.js` |
| 立绘布局 | `240/size` 缩放；X 轴 ±（右立绘镜像）；Y `(272*ease-32)/240`；`0.9+wiggle*0.1` | `js/render.js` |
| 立绘原点 | `<Center/>` → `Justify=(0.5,0.5)`，`SetFrame` **按当前帧尺寸**重算原点 | 同 |
| 电话立绘 | `phonestatic="ex"` 循环音 + `glitchy` 时叠加 `noise/` 噪点（alpha 0.2） | 同 |
| 文本框叠层 | `textbox/<name>_overlay`（Oshiro 的面具），右立绘时水平镜像 | 同 |
| 角色语音 | `event:/char/dialogue/<角色>`，参数 `dialogue_portrait` / `dialogue_end` 门控 | `tools/render_audio.py` 渲染为 WAV |
| 字体 | `Noto Sans CJK SC Medium` 64px BMFont | 直接解析 `chinese.fnt` |
| 文本框贴图 | `Content/Graphics/Atlases/Portraits/textbox/*.data` | 解码为 PNG |
| 继续按钮 | `Gui` 图集的 `textboxbutton` | 从 `Gui0.data` 中裁切 |
| 文本颜色 | `{# FF9523}` / `{#}` 颜色栈 | 同 |
| 波浪字 | `{~}...{/~}` → `sin(index*0.25 + time*8) * 4` | 同 |

### 几个容易踩错的细节

- 《Celeste》的语言文件在 `Language.FromTxt` 里会先执行 `[...]` → `{portrait ...}` 的替换，
  **连 `SPLIT_REGEX=` 这一行也会被替换**：原本的字符类 `[、|。|！|」|，]` 被打散成
  `{portrait ...}|。|！|」|，`，于是 `|` 从字面量变成了正则的分支分隔符。
  本 DEMO 直接读取游戏生成的 `.txt.export`，使用游戏运行时真正生效的这个正则，
  因此中文长句会在 `。！」，` 处换行，与原版一致。
- `.data` 纹理的 RLE 在 **alpha == 0 时只写 1 个字节**（透明 run 优化），不是固定 4 字节。
- 文本框贴图比 1688×272 大（带发光边），必须从 `Portraits.meta` 读取 `frameWidth/Height`
  与绘制偏移，否则会错位。
- 语音不是「每个字一个音效」，而是一个常驻循环事件；参数 `dialogue_portrait` 表示表情序号，
  停止时把参数置 0。本项目将每个（角色，表情）渲染成一段约 2s 的循环，用音量门控模拟。
- FMOD 参数的**索引是按 ParameterId 排序**，不是按名字。绝大多数对话事件是
  `[dialogue_portrait, dialogue_end]`，但 `event:/char/dialogue/ex`（第二章电话）正好相反；
  用 `SetParameterValueByIndex` 时顺序搞反会把 `dialogue_end` 设成 1，整段静音。
- 立绘的 `<Center/>` 只决定 `Justify=(0.5,0.5)`；真正绘制时 `Sprite.SetFrame` 会用
  **当前帧的宽高**重算原点，所以 160×160 与 391×432 的帧都能正确居中。
- 立绘动画里 `idle_*` 的 `goto` 是带权重的随机分支（`idle_normal:5,idle_normal_blink`），
  而 `<Loop>` 的 `goto` 指向自己；漏掉权重会导致眨眼永远不会发生。
- 立绘数量：只导出「场景实际用到的表情 + 其 goto 闭包」，避免把 660+ 张原始帧全部搬进仓库。

---

## 目录结构

```text
.
├─ index.html                 DEMO 入口
├─ css/style.css
├─ js/
│  ├─ config.js               常量（布局、路径）
│  ├─ font.js                 BMFont 度量与染色缓存
│  ├─ fancytext.js            FancyText 解析（逐函数移植）
│  ├─ portrait.js             Monocle.Sprite 立绘动画 / Wiggler / 噪点叠层
│  ├─ textbox.js              Textbox 协程 / 跳过 / 开合 / 立绘状态机
│  ├─ render.js               1920×1080 Canvas 渲染
│  ├─ audio.js                语音门控、电话杂音与 UI 音效
│  └─ main.js                 资源加载、场景选择与主循环
├─ tools/
│  ├─ extract_all.cmd         一键提取
│  ├─ celeste_common.py       共用：场景配置 / .export / Portraits.xml 解析
│  ├─ extract_textures.py     .data/.meta → PNG（字体/文本框/立绘帧）；chinese.fnt → JSON
│  ├─ extract_dialog.py       语言 .export → 多场景对话；Portraits.xml → 语音映射
│  ├─ render_audio.py         FMOD Studio 运行时录音
│  └─ README.md               提取脚本细节与排错
└─ assets/celeste/            （gitignore）提取出来的原版资源
   ├─ fonts/                  chinese.json / chinese.js / chinese_0.png
   ├─ ui/                     textbox_<skin>.png（madeline/granny/theo/oshiro/badeline/default
   │                          + oshiro_overlay）/ textboxbutton.png
   ├─ portraits/              <sprite>/<frame>.png（只含本 DEMO 用到的帧）+ noise/
   ├─ dialog/                 scenes.json / scenes.js / <scene>.json / voice_jobs.json
   ├─ portraits.js            角色 → 动画表 / 帧文件 / 文本框名 / 语音事件 / 表情序号
   └─ audio/                  21 段语音 + 1 段电话杂音 + 4 个 UI 音效 + audio-data.js（内联 base64）
```

---

## 为什么音频要内联成 base64

浏览器在 `file://` 下会拦截 `<audio src="xxx.wav">`（`net::ERR_ABORTED`），
因此提取脚本会额外生成 `audio-data.js`，把语音以 data URI 内联（左右声道完全相同，
降为单声道后 26 段音频合计约 5.6 MB）。这样**双击 `index.html` 就能直接出声**，不需要起服务器。

如果你更喜欢用 HTTP 调试：

```bat
python -m http.server 8000
```

然后访问 `http://127.0.0.1:8000/index.html`。

---

## 资源与版权

- 对话文本、字体、文本框贴图、语音均来自《Celeste》，版权归 **Maddy Makes Games / Extremely OK Games** 所有。
- 本项目仅用于本地学习与演示，不随仓库分发任何原版资源。
- 请勿将 `assets/celeste/` 下的内容用于再分发。

---

## 已知限制

- 立绘使用提取出的 `begin_/idle_/talk_` 动画帧，但**只导出对话里用到的表情**；
  其他表情的帧不会出现在 `assets/celeste/portraits/` 里。
- `{trigger ...}`（原版用来触发剧情动画）只做空实现，按 `debug` 打日志。
- 语音停止使用约 70ms 音量淡出，没有逐帧调用 FMOD 的 `dialogue_end` 尾音。
- 背景为暗色渐变，不是游戏场景。
- `tools\extract_all.cmd` 自身的提示为英文（避免 cmd 代码页乱码），Python 脚本输出为中文。
