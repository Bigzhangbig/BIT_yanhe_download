# BIT_yanhe_download

## 介绍

本项目 fork 自 [BITNP/BIT_yanhe_download](https://github.com/BITNP/BIT_yanhe_download)（upstream，最早由个人作者 [AuYang261](https://github.com/AuYang261/BIT_yanhe_download) 创建）。**本 fork 系 vibe coding 产物，代码与文档仅供参考，使用前请自行验证。** 在原项目基础上，本 fork 增加了以下增强（upstream release 不包含这些功能，建议从源码运行本 fork）：

- **SSO 3 层 fallback 登录**：`login_sso_requests`（纯 requests CAS 3.0）→ `headless_login`（无头 patchright）→ `auth_patchright` `headful_login`（自动启动有头浏览器完成剩余登录）
- **`ensure_auth()` 自动 SSO**：所有下载入口（CLI / TUI / WebUI）`auth.txt` 失效时自动走 3 层 fallback，用户零操作
- **统一 CLI 入口 `main.py`**：tty 下 Textual 框架 TUI，非 tty（管道/CI）自动降级 stdin 文本交互，同一脚本覆盖交互与批处理；`gui.py` 改为 5 行薄重定向保留兼容
- **三阶段 TUI 流程**：`main.py` 启动后先选课程获取方式（输入课程号 / 关键词搜索（支持学期筛选）/ 我的课程）→ 再选节数（单节 / 多节 / 全选）→ 最后选下载轨道（2 路视频 + 3 路音频自由组合：摄像头 / 屏幕 / 蓝牙话筒 / 摄像头内嵌 / 屏幕内嵌）
- **Textual 框架 TUI**：替换手写 curses，用 [Textual](https://textual.textualize.io/) 8.x 实现：`CourseApp` + 10 个 `ModalScreen` 子类分阶段，`SelectionList` / `OptionList` / `Input` 控件 + `tui.tcss` CSS 样式（圆角边框、配色、状态栏），界面更美观、跨终端兼容性更好；对外接口 `app.result` 仍返回 `(videoList, courseName, professor, selected_videos, tracks_dict)`，与 `_do_download` 兼容
- **跨平台支持（Windows / macOS / Linux）**：`get_ffmpeg_command()` 智能 ffmpeg 查找（env / cwd / homebrew / /usr/bin / /snap/bin / PATH 优先级）、PyInstaller frozen 路径、patchright 三平台 profile 路径、captcha 图片查看器跨平台调用（macOS `open` / Linux `xdg-open` / Windows `os.startfile`）、临时文件统一走 `tempfile.gettempdir()`（Linux/macOS 是 `/tmp`，Windows 是 `%TEMP%`）
- **WebUI 课程搜索面板**：`/search_courses` + `/my_courses` + `/semesters` 三个端点 + 前端 Tab 切换 + 学期筛选 + 分页
- **4 种非交互 captcha 自动识别**：图形图片（macOS Preview 弹窗）/ SMS / 邮件 / 隐形 reCAPTCHA
- **多路/音画合并**：双轨 mkv（2 video + 3 audio track，ffmpeg `-c copy` 不重编码）
- **两路视频画面+音频同步**：`-itsoffset -0.5` 提前 vga 对齐 main（sync-prober 实测）
- **MLX Qwen3-ASR 字幕**（替代原 whisper）
- **web 页面 SSO 登录按钮**：不需终端跑脚本，Tier 3 自动启动有头浏览器
- **鉴权 token 32 hex 修复**：延河 token 是 session id（32 hex）不是 JWT，修正后登录才真正可用

可下载[延河课堂 (yanhekt.cn)](https://www.yanhekt.cn/recordCourse)中的课程视频。延河课堂是北京理工大学的在线课堂，提供了大量的课程视频，但是没有提供下载功能。本项目可以下载指定课程的摄像头和屏幕信号，包括无权限的课程。

项目详细报告见[项目详解](./项目详解.md)，仅供参考。

欢迎提出建议和 star！

## 使用：下载指定课程

由于本 fork 没有预编译 release，且 upstream release 不含本 fork 的 SSO fallback、多轨 mkv、ASR 字幕等增强，建议从源码运行（macOS 步骤见下方"macOS 运行"小节；Windows 用户同样从源码运行）：

```bash
git clone https://github.com/Bigzhangbig/BIT_yanhe_download.git
cd BIT_yanhe_download
uv sync                 # 基础依赖（Windows 需提前安装 ffmpeg 并加入 PATH）
uv run python webui_interface.py
```

如果不需要上述本 fork 增强、只需要基础下载功能，可以退而使用 [upstream 预编译 release（不含本 fork 增强）](https://github.com/AuYang261/BIT_yanhe_download/releases/latest/download/release_downloader.zip)——但该 Windows 二进制不包含 SSO 自动登录、多轨合并、MLX ASR 等本 fork 功能。

在[延河课堂 (yanhekt.cn)](https://www.yanhekt.cn/recordCourse)中找到想下载的课程，以链接为 `https://www.yanhekt.cn/course/40524 `的课程为例，复制地址栏最后的五位编号 40524。注意是课程列表的链接（以 `yanhekt.cn/course/五位编号 `开头），不是视频界面的链接（以 `yanhekt.cn/session/六位编号`开头）。

![image-20231018204208066](md/README/image-20231018204208066.png)

### 登录延河课堂

新版的延河课堂要求登录才能查看课程列表，故需要先获取登录后的身份认证码。**主推 `login_sso_unified.py`（3 层 fallback 全自动）**：
- Tier 1: `login_sso_requests.py` 纯 requests（80% 情况，4-5s）
- Tier 2: `headless_login.py` headless patchright（撞非交互 captcha，10-30s）
- Tier 3: `auth_patchright.py` 有头 patchright（必须人交互的 captcha，自动启动浏览器让用户完成，无需终端跑脚本）

`auth_patchright.py` 仍保留作为最后兜底，**仅在 Tier 1+2 都跑不过时由 Tier 3 自动调用**（用户无需手动跑该脚本）。

> 运行 `main.py` / `webui_interface.py` 时，若 `auth.txt` 不存在或失效，会自动调用 `login_sso_unified` 走上述 3 层 fallback，无需先手动跑登录脚本。

#### 主推：3 层 fallback 全自动登录（推荐，N100 24/7 友好）

在项目根目录的 `.env` 填入 `STUDENT_ID` + `PASSWORD`（参考 `.env.example`）：

```bash
# 一次性：建 .env
cp .env.example .env
# 编辑 .env 填学号和密码

# 主入口：一条命令走 3 层 fallback
uv run python login_sso_unified.py
```

**E2E 流程**：

1. **Tier 1** `login_sso_requests.py` 纯 requests（默认 4-5s）
   → `GET https://sso.bit.edu.cn/cas/login?service=https://cbiz.yanhekt.cn/v1/cas/callback`
   → 拿 `SESSION` cookie + `<p id="login-page-flowkey">` 里的 execution
   → `POST /cas/login`（form: username/password/type/execution/...）
   → 302 → `https://cbiz.yanhekt.cn/v1/cas/callback?ticket=ST-...`
   → 302 → `https://www.yanhekt.cn/login?token=<32 hex>&type=Bearer&expired_at=...`
2. **Tier 2** `headless_login.py` headless patchright（撞非交互 captcha 时）
   → Patchright Python API + persistent profile 复用 TGC
   → 自动填账号密码 + 等 token 出现
3. **Tier 3** `auth_patchright.py` 有头 patchright（必须人交互的 captcha）
   → 自动启动有头浏览器, 用户在弹窗中完成登录（含验证码）

退出码：0 成功 / 1 requests 失败或拿不到有效 token / 2 headless + headful 都失败 / 4 密码错

#### 独立入口（调试用）

```bash
uv run python login_sso_requests.py   # 只跑 Tier 1
uv run python headless_login.py        # 只跑 Tier 2 (headless)
uv run python auth_patchright.py       # 只跑 Tier 3 (有头, 浏览器弹窗)
```

需要二次身份验证时，脚本会自动检测并按类型处理：

| SSO 触发条件 | 类型 | 处理方式 |
|---|---|---|
| `<p id="netEaseCaptchaId">` 非空 | 网易易盾滑块 | ❌ 报错降级到 Tier 3 自动有头（需拖动） |
| `<p id="siteKey">` 非空 | reCAPTCHA / hCaptcha | ❌ 报错降级到 Tier 3 自动有头（需勾选） |
| `<p id="recaptcha-invisible">true` | 隐形 reCAPTCHA v3 | ❌ 报错降级到 Tier 3（行为指纹难模拟） |
| `<img id="captchaImg">` 或 `<p id="captcha-url">` | 文本型图片验证码 | ✅ 下载到系统临时目录 `tempfile.gettempdir()` 下（Linux/macOS 是 `/tmp`，Windows 是 `%TEMP%`）+ 调用平台默认图片查看器（macOS `open` / Linux `xdg-open` / Windows `os.startfile`）+ 终端 prompt 输入 |
| `<p id="current-login-type">smsLogin` | 短信验证码 | ✅ 终端 prompt 输入 6 位 |
| `<p id="current-login-type">mailLogin` | 邮件验证码 | ✅ 终端 prompt 输入 6 位 |
| `<p id="current-login-type">webauthn` | 通行密钥 | ❌ 报错降级（需 Touch ID / 物理密钥） |
| `<p id="current-login-type">shuxiQr` | i北理扫码 | ❌ 报错降级（需 i北理 APP） |

文本型 captcha 触发后效果：

```
[login] 需要图形验证码: https://sso.bit.edu.cn/cas/captcha?token=xxx
[login] 验证码图片已存: <系统临时目录>/yhe_captcha.jpg (系统默认图片查看器会自动打开)

[prompt] 请输入图中验证码: ▌
```

降级路径：Tier 1/2 跑不过时由 `login_sso_unified` 自动调用 Tier 3 启动有头浏览器，用户在弹窗中完成登录，token 自动写入 `auth.txt`，N100 scheduler 可继续用。

#### Fallback：Patchright 半自动（requests 跑不过时再用）

确保本机能直接运行 `patchright` 后，在项目目录执行：

```bash
uv run python auth_patchright.py
```

该命令会调用类似下面的 Patchright 命令打开一个带持久化用户目录的浏览器窗口：

```bash
patchright open --browser chromium --user-data-dir "$HOME/Library/Application Support/BIT_yanhe_download/patchright-profile" --save-storage "$HOME/Library/Application Support/BIT_yanhe_download/patchright-storage-state.json" https://www.yanhekt.cn/recordCourse
```

在弹出的浏览器里完成登录后，脚本会轮询检查鉴权是否可用；检测成功后会自动关闭 Patchright 打开的浏览器窗口。脚本会优先从保存的 storage state 中读取 `localStorage.auth`；如果 Patchright 没有生成 state 文件，则会从持久化浏览器 profile 的 Local Storage 中提取 `token` 并写入 `auth.txt`。之后运行网页 GUI、命令行 GUI 或原始交互方式时，通常无需再手动填写身份认证码。

如果之前已经保存过 Patchright storage state，只想重新提取鉴权，可运行：

```bash
uv run python auth_patchright.py --skip-open
```

也可以顺手验证某个课程是否可用：

```bash
uv run python auth_patchright.py --course-id 40524
```

手动获取身份认证码的方式仍然可用：

```
javascript:alert(JSON.parse(localStorage.auth).token)
```

![image-20240809182406184](md/README/image-20240809182406184.png)

回车后会弹出提示框，复制该身份认证码。

![image-20240809182413373](md/README/image-20240809182413373.png)

或者可以按 `F12`键打开”控制台“，在其中输入上述代码，也能得到身份认证码。

### 网页 GUI 交互

双击运行 `webui_interface.exe` 文件打开网页服务器，会自动弹出浏览器网页。

如果使用 Python 环境启动，运行：

```bash
uv run python webui_interface.py
```

而后在打开的网页中新建任务即可。

网页中点击「SSO 登录」按钮可自动走 3 层 fallback 登录（requests -> headless -> 有头浏览器）。若 .env 配置了 STUDENT_ID + PASSWORD 则全自动；撞到验证码时会自动弹出浏览器窗口让用户完成，无需在终端运行任何脚本。

### macOS 运行

macOS 可以直接从源码运行，无需 Windows 的 `.exe` 文件。建议先安装 `uv` 和 `ffmpeg`：

```bash
brew install uv ffmpeg
uv sync
```

然后按需运行：

```bash
# 网页 GUI
uv run python webui_interface.py

# 统一 CLI（主推）：tty 下 Textual 框架 TUI，非 tty（如管道/CI）自动降级 stdin
uv run python main.py 40524
# 不传 courseID 也会在 TUI/stdin 里提示输入
```

`uv run python gui.py` 仍可用，已重定向到 `main.py`（兼容旧入口，行为一致）。

`main.py` 启动 Textual TUI 后会按顺序走三个阶段：

1. **选择课程**：三选一
   - 输入课程号（`yanhekt.cn/course/` 后的 5 位 ID）
   - 关键词搜索（先可选学期多选 / 全不选=不筛选，再选课程）
   - 我的课程（拉取当前账号已选课程）
2. **选择节数**：单节 / 多节（≥1）/ 全选
3. **选择下载轨道**：自由组合
   - 视频轨（≥1）：摄像头（main）/ 屏幕（vga）
   - 音频轨（可空）：蓝牙话筒 / 摄像头内嵌音频 / 屏幕内嵌音频

非 tty 环境（管道 / CI / systemd）自动降级到 stdin 文本交互，传入 `courseID` 时跳过阶段 1 第 1 步提示，下载选项默认全选 + 双轨合并。

程序会优先查找项目目录、打包目录、`/opt/homebrew/bin/ffmpeg`、`/usr/local/bin/ffmpeg` 和 PATH 中的 `ffmpeg`。如果你的 `ffmpeg` 在其他位置，可以通过环境变量指定：

```bash
FFMPEG_BINARY=/path/to/ffmpeg uv run python webui_interface.py
```

下载类型可选摄像头（即教室后的摄像头录像）、电脑屏幕（即教室电脑的屏幕信号）或双轨合并（摄像头 + 屏幕 + 蓝牙话筒，单 mkv）。

可以选择是否下载教室蓝牙话筒信号（该课程有蓝牙话筒信号时有效），若老师未使用蓝牙话筒则该信号没有声音。

![image-20240529171709402](md/README/image-20240529171709402.png)

首次使用或之前的登录失效时，需要输入上述获取的身份认证码。

若之前使用过本工具（包括其他交互方式），登录未失效，身份认证码会自动保存，无需每次都填写。

![image-20240809182420653](md/README/image-20240809182420653.png)

下载完成的文件在 `output/`目录下以 `课程名-video/screen`格式命名的文件夹中。若下载了蓝牙音频则保存在和视频同目录同名的 `.aac`文件中。

![image-20230926124922726](md/README/image-20230926124922726.png)

### Linux 运行

Linux 同样可以从源码运行。建议先安装 `uv` 和 `ffmpeg`：

Debian / Ubuntu 系：

```bash
sudo apt update
sudo apt install -y ffmpeg
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Fedora / RHEL 系：

```bash
sudo dnf install -y ffmpeg
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Snap 用户：

```bash
sudo snap install ffmpeg
```

然后在项目目录：

```bash
uv sync
```

按需运行：

```bash
# 网页 GUI
uv run python webui_interface.py

# 统一 CLI（主推）：tty 下 Textual 框架 TUI，非 tty（如管道/CI）自动降级 stdin
uv run python main.py 40524
# 不传 courseID 也会在 TUI/stdin 里提示输入
```

`uv run python gui.py` 仍可用，已重定向到 `main.py`（兼容旧入口，行为一致）。

`main.py` 启动 Textual TUI 后会按顺序走三个阶段：

1. **选择课程**：三选一
   - 输入课程号（`yanhekt.cn/course/` 后的 5 位 ID）
   - 关键词搜索（先可选学期多选 / 全不选=不筛选，再选课程）
   - 我的课程（拉取当前账号已选课程）
2. **选择节数**：单节 / 多节（≥1）/ 全选
3. **选择下载轨道**：自由组合
   - 视频轨（≥1）：摄像头（main）/ 屏幕（vga）
   - 音频轨（可空）：蓝牙话筒 / 摄像头内嵌音频 / 屏幕内嵌音频

非 tty 环境（管道 / CI / systemd）自动降级到 stdin 文本交互，传入 `courseID` 时跳过阶段 1 第 1 步提示，下载选项默认全选 + 双轨合并。

程序会按 `FFMPEG_BINARY` 环境变量 > 当前工作目录 > `/usr/bin/ffmpeg` > `/snap/bin/ffmpeg` > `PATH` 中的 `ffmpeg` 顺序查找。如果你的 `ffmpeg` 在其他位置，可以通过环境变量指定：

```bash
FFMPEG_BINARY=/path/to/ffmpeg uv run python webui_interface.py
```

`main.py` 启动 Textual TUI 不依赖系统 curses 库，依赖通过 `uv sync` 自动装（`textual>=8.2.8`）。当终端不是 tty（如 systemd / nohup / CI 重定向）时，main.py 会自动降级到 stdin 文本交互，不会因 TUI 渲染失败而退出。

### 命令行 GUI 交互

打开命令行（在 `release_downloader.zip `解压的文件夹地址栏中搜索 cmd），在命令行中输入 `gui.exe` 文件运行。直接双击运行可能会有字符对不齐的问题，导致难以识别文字。最好将命令行窗口最大化以免字符显示不全。

如果使用 Python 环境启动，运行：

```bash
uv run python gui.py
```

![image-20240413001454717](md/README/image-20240413001454717.png)

首先输入你想下载的课程编号(40524)，回车（小键盘的回车似乎不能用），获取课程视频列表：

![image-20240413001734218](md/README/image-20240413001734218.png)

同样，首次使用或之前的登录失效时，需要输入上述获取的身份认证码；登录未失效则不用。

![image-20240809183350633](md/README/image-20240809183350633.png)

<img src="md/README/image-20240413002004628.png" alt="image-20240413002004628" style="zoom:80%;" />

按键盘上下键移动光标，按空格选择/取消选择，至少需要选择一个视频。选择完成后按回车确认。若想退出按 q 键即可。

确认后，选择要下载的信号，同样至少需要选择一个信号，选择完成后按回车确认。

![image-20240413002242979](md/README/image-20240413002242979.png)

而后选择是否下载教室蓝牙话筒信号，选择完成后按回车确认。开始下载。按 `ctrl+c`停止。

![image-20240529171253980](md/README/image-20240529171253980.png)

### 原始交互方式

若使用上述 GUI 显示有问题，可直接使用原始交互方式。双击运行 `main.exe` 文件，并输入你想下载的课程编号(40524)和身份认证码（如果需要）。输出课程视频列表：

![image-20240529171540279](md/README/image-20240529171540279.png)

输入想下载的视频编号，用英文逗号(,)分隔，回车。接着输入数字选择下载摄像头信号还是下载屏幕信号，默认为摄像头信号。而后选择是否下载蓝牙话筒信号。回车即开始下载。

## 自动生成字幕

本项目提供自动生成字幕功能，使用 MLX Audio 的 Qwen3-ASR 模型在本地进行语音转文字生成字幕。

该功能更适合在 Apple Silicon Mac 上运行，依赖见[下文](#依赖)。

下载[字幕生成程序 gen_caption](https://github.com/AuYang261/BIT_yanhe_download/releases/tag/v2.0)（upstream release，使用原版 whisper 字幕模型，**不含本 fork 的 MLX Qwen3-ASR 增强**），由于程序比较大，采用了分卷压缩发布。全部下载并解压，得到一个 `gen_caption.exe `可执行文件，保存在上述 `release_downloader.zip `解压的目录中，和保存视频的目录 `output/`同级，如下所示：

![image-20240409105228362](md/README/image-20240409105228362.png)

下载完视频后，双击运行 `gen_caption.exe`（文件较大，需要等一会），输入数字选择视频，回车。再输入数字选择 Qwen3-ASR 模型，默认使用 `mlx-community/Qwen3-ASR-1.7B-bf16`。第一次使用会自动下载模型，请耐心等待。如下所示：

![image-20240409131033038](md/README/image-20240409131033038.png)

> 本 fork 的字幕功能基于 MLX Qwen3-ASR（更准确、更快），仅在 Apple Silicon Mac 上从源码运行时可用：
>
> ```bash
> uv sync --extra asr
> uv run python gen_caption.py <下载的视频或音频文件路径>
> ```

等待程序运行完成，生成的字幕文件为 `.srt`格式，与视频文件在同级目录下，用支持字幕的播放器（如 potplayer）打开视频即可看到带字幕的视频。

_tips: 语音转文字所需的时间较长，可以先观看视频，字幕生成好了再重新打开视频享受字幕。若显存/内存压力较大，可选择 8bit、6bit 或 4bit 量化模型。_

## 依赖

- ffmpeg，已在 Release 中提供。若在 Linux 环境下运行，需手动安装 ffmpeg：

```bash
sudo apt update
sudo apt install ffmpeg
```

_若想用 python 环境运行，先安装基础依赖；如果需要字幕转写，再安装可选依赖_

- python，[下载](https://www.python.org/ftp/python/3.9.4/python-3.9.4-amd64.exe)并安装
- 基础依赖。打开命令行，运行如下命令安装：

```bash
uv sync
```

- 如果需要自动生成字幕，再安装语音转文字的可选依赖：

```bash
uv sync --extra asr
```

旧命令 `uv sync --extra whisper` 仍然可用，作用与 `asr` 相同。

## 注意

- 需要关闭本机上的代理，否则会提示类似 `check_hostname requires server_hostname`的报错信息。
- 可以下载无权限的课程，只要知道课程链接（中的课程编号）就行。

## 打包（仅开发者需要）

如果想要运行时不依赖 python 环境，可将 python 程序打包成可执行文件。Release 中已打包。

使用如下命令打包：

```bat
uv add --dev pyinstaller
REM Windows 打包
uv run pyinstaller -F main.py -i yhkt.ico
uv run pyinstaller -F gui.py -i yhkt.ico
uv run pyinstaller -F webui_interface.py --add-data webui;webui --add-data templates;templates -i yhkt.ico
uv run pyinstaller -F auth_patchright.py -i yhkt.ico
uv run pyinstaller -F gen_caption.py -i yhkt.ico
```

macOS / Linux 打包时不使用 `.ico`，且 `--add-data` 使用冒号分隔：

```bash
uv add --dev pyinstaller
uv run pyinstaller -F main.py
uv run pyinstaller -F gui.py
uv run pyinstaller -F webui_interface.py --add-data webui:webui --add-data templates:templates
uv run pyinstaller -F auth_patchright.py
uv run pyinstaller -F gen_caption.py
```

打包 `gen_caption.py`时可能会失败，提示递归过深：

<img src="md/README/image-20240409095211597.png" alt="image-20240409095211597" style="zoom:50%;" />

解决方法参考[这里](https://zhuanlan.zhihu.com/p/661325305)，需要修改项目根目录下的 `gen_caption.spec`配置文件，在文件开始处加上以下代码：

```python
import sys ; sys.setrecursionlimit(sys.getrecursionlimit() * 5)
```

再使用如下命令打包：

```bash
uv run pyinstaller --clean .\gen_caption.spec
```

打包完成后运行若出现 Temp 目录下的文件未找到：

![image-20240409095831766](md/README/image-20240409095831766.png)

解决方法参考[这个](https://blog.csdn.net/qq_42324086/article/details/118280341)，将项目 `hooks`目录下的 `hook-mlx_audio.py`和 `hook-zhconv.py`文件复制到 pyinstaller 的 hook 目录下（通常在 `python根目录\Lib\site-packages\PyInstaller\hooks`）。
