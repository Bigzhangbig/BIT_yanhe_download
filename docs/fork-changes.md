# 本 Fork 改动说明

## 概述

本仓库 fork 自 [BITNP/BIT_yanhe_download](https://github.com/BITNP/BIT_yanhe_download)（更早源头 [AuYang261/BIT_yanhe_download](https://github.com/AuYang261/BIT_yanhe_download)）。

- **Fork 点**：`4f6eaf9`（2026-04-13，upstream 合并 PR #20 "支持直接从下载的音频（.aac）生成字幕"）
- **Fork 后的变更规模**：自 fork 点起 25 个 commit、约 3925 行新增 / 572 行删除、26 个文件变动
- **Upstream 状态**：自 fork 点起 upstream 0 commit，本 fork 完全独立演进

本 fork 系 vibe coding 产物，所有改动以可运行、文档可查证为前提。下文按 7 大类列出相对 upstream 的增强。

## 改动详清单

### A. SSO 登录系统（13 项）

upstream 原采用 Patchright 半自动登录；本 fork 重写为 3 层 fallback 编排，无浏览器优先，必要时降级到有头浏览器。

| 项 | 关键文件 / 位置 |
| --- | --- |
| 3 层 fallback 编排 | `login_sso_unified.py:31` `run_unified_login()` |
| Tier 1 纯 requests CAS 3.0 登录 | `login_sso_requests.py` |
| Tier 2 headless Patchright 自动填表 | `headless_login.py` |
| Tier 3 有头浏览器自动启动 | `auth_patchright.py:321` `headful_login()` |
| 4 种非交互 captcha 自动识别 | 图形图片（macOS Preview 弹窗）/ SMS / 邮件 / 隐形 reCAPTCHA |
| 6 种交互 captcha 降级到 Tier 3 | 网易易盾滑块 / reCAPTCHA / hCaptcha / WebAuthn / i北理扫码 等 |
| 自动鉴权 | `utils.py:95` `ensure_auth()` 接入 main.py / webui 的 `/get_course` `/search_courses` `/my_courses` |
| WebUI SSO 入口 | `/sso_login` + `/sso_config` 端点（`webui_interface.py`） |
| Token 格式修正 | 32 hex session id（25beb24）—— 延河 token 不是 JWT |
| 旧 TGT 流程 | 删除 |
| 退出码 | 0/1/2/4 标准化；`EXIT_HEADLESS_INTERACTIVE=3` 是死代码，不再返回 |
| Tier 3 体验 | 自动启动有头浏览器，用户在弹窗完成交互，**不需终端跑脚本** |
| 流程抓取调试 | `capture_sso_flow.py` / `capture_sso_fresh.py` |

### B. 多路 / 音画合并（8 项）

upstream 只能下载单个信号；本 fork 支持双路视频 + 多路音频合并到单 mkv 文件。

| 项 | 关键文件 / 位置 |
| --- | --- |
| ffmpeg 合并入口 | `m3u8dl.py:289` `merge_to_mkv()`，`-c copy` 不重编码 |
| 输出规格 | 2 video + 3 audio，5 stream metadata（`m3u8dl.py:315-327`） |
| 默认音轨 | 蓝牙话筒作 track 0 |
| 画面同步 | `-itsoffset -0.5` 提前 vga 对齐 main（实测 vga 晚 0.5s） |
| 退化路径 | 无蓝牙时 2v+2a |
| 入口 | CLI 选项 3（`main.py:52`）+ WebUI 下载类型下拉（`templates/index.html:73`） |
| 清理 | 中间文件自动清理 |
| 设计文档 | `docs/multitrack-merge-plan.md` |

### C. MLX Qwen3-ASR 字幕（7 项）

upstream 用 `openai-whisper`；本 fork 替换为 MLX Qwen3-ASR，量化可选，命令行更友好。

| 项 | 关键文件 / 位置 |
| --- | --- |
| 替换 ASR 引擎 | `gen_caption.py`，whisper 整段替换为 MLX Qwen3-ASR（265 行） |
| 模型 ID | `mlx-community/Qwen3-ASR-1.7B-bf16` / `8bit` / `6bit` / `4bit`（`gen_caption.py:9-12`） |
| CLI 化 | argparse 替代原 `sys.argv + input()` |
| 临时音频 | 自动 ffmpeg 转换 16kHz 单声道 wav + 清理 |
| 依赖 | `openai-whisper` -> `mlx-audio>=0.4.3` |
| PyInstaller | hook 改名 `hook-whisper.py` -> `hooks/hook-mlx_audio.py` |
| 修复 | SRT 时间格式 |

> 可查证的真实模型 ID 直接来自 `gen_caption.py` 常量定义。

### D. macOS / 跨平台（5 项）

| 项 | 关键文件 / 位置 |
| --- | --- |
| ffmpeg 智能查找 | `utils.py:305` `get_ffmpeg_command()`：env `FFMPEG_BINARY` > cwd/app_dir/bundle_dir > `/opt/homebrew/bin` > `/usr/local/bin` > PATH |
| PyInstaller frozen 路径 | `sys.frozen` / `sys._MEIPASS` 处理 |
| 下载器 ffmpeg 调用 | `m3u8dl.py` 改用 `get_ffmpeg_command()` 替代硬编码 `ffmpeg` |
| Patchright profile 路径 | `auth_patchright.py:50` `default_profile_dir()` 跨平台（darwin / nt / xdg） |
| 测试 | macOS Apple Silicon 端到端验证 |

### E. WebUI 课程搜索面板（7 项）

| 项 | 关键文件 / 位置 |
| --- | --- |
| 搜索端点 | `/search_courses` keyword + 学期 + 分页（`webui_interface.py:311`） |
| 我的课程 | `/my_courses`（`webui_interface.py:328`） |
| 学期下拉 | `/semesters`（`webui_interface.py:342`） |
| 前端 Tab | 搜索 / 我的课程切换（`webui/script.js`） |
| 分页 UI | `webui/script.js` + `webui/styles.css` |
| 学期下拉 | `webui/script.js` + `templates/index.html` |
| 样式 | `webui/styles.css` +126 行 |

### F. 安全 / 工程化（6 项）

| 项 | 关键文件 / 位置 |
| --- | --- |
| 依赖升级 | idna / urllib3 / soupsieve 修复 4 high + 1 medium 漏洞（edcee9a） |
| Flask 并发 | `threaded=True`，SSO 登录不阻塞其他请求 |
| 凭据脱敏 | .env 读取不打印明文密码 |
| `.gitignore` | 加 `.env` / `.qoder/` / 本地实验脚本 |
| gitleaks | `utils.py` token URL 解析误报加 `# gitleaks:ignore` |
| 新依赖 | `python-dotenv` / `pycryptodome` / `beautifulsoup4` |

### G. 文档 / 调试（5 项）

| 项 | 关键文件 / 位置 |
| --- | --- |
| 项目规范 | `CLAUDE.md` / `AGENTS.md` |
| SSO 流程抓取 | `capture_sso_flow.py` / `capture_sso_fresh.py` |
| 项目详解 | `项目详解.md` 加 fork 来源说明 |
| 配置模板 | `.env.example`（`STUDENT_ID` / `PASSWORD` 命名） |
| 本文件 | `docs/fork-changes.md`（本文档） |

### H. 统一 CLI 入口（8 项）

upstream 把"原始交互方式"（main.py，stdin）和"命令行 GUI"（gui.py，curses）拆成两个独立入口，逻辑分散、传参靠 global state；本 fork 收敛到 `main.py` 一个入口，`gui.py` 退化为薄重定向。

| 项 | 关键文件 / 位置 |
| --- | --- |
| 统一入口 | `main.py` `main()` 按 `sys.stdout.isatty()` 分流 tty → `main_tui()`（Textual TUI）/ 非 tty → `main_plain()`（stdin 文本交互，可传 `sys.argv[1]` 作 courseID）；Textual 渲染异常时也降级 stdin |
| 共享下载 | `main.py` `_do_download` / `_download_one`，按 `_TRACKS` 自由组合走双轨 mkv（vga_offset=-0.5）或单路 mp4 + 蓝牙 `.aac` + `utils.ensure_auth` SSO 3层 fallback |
| TUI 抽离 | `tui.py`：Textual `CourseApp` + 10 个 `ModalScreen` 子类（详见 I 节） |
| 三阶段 TUI 流程 | `tui.config_tui`：阶段 1 `_select_course_id`（输入课程号 / 关键词搜索含学期筛选 / 我的课程）→ 阶段 2 `_select_videos`（单节 / 多节 ≥1 / 全选）→ 阶段 3 `_select_tracks`（视频轨 ≥1 + 音频轨可空） |
| 下载自由组合 | 阶段 3 视频 multi_select（摄像头 main / 屏幕 vga，≥1）+ 音频 multi_select（蓝牙话筒 / 摄像头内嵌 / 屏幕内嵌，可空），组合成 5 个 bool 传给 `_download_one` |
| 学期筛选 | `utils.search_courses(semesters=...)` 支持多选学期参数（`tests/test_refactor.py::SearchCoursesSemestersTest` 验证 `semesters[]=` 列表展开） |
| `merge_to_mkv` 选择性音频 map | `m3u8dl.merge_to_mkv` 新增 `include_main_audio` / `include_vga_audio` 参数，控制是否 map 内嵌音频轨（默认 True） |
| 回归测试 | `tests/test_refactor.py`（18 个 unittest case 覆盖 `merge_to_mkv` 5 种音频组合 / `_download_one` 5 种视频组合 / `search_courses` 学期参数 / 主流程模块 import） |
| 兼容保留 | `gui.py` 5 行重定向 `from main import main`，旧脚本/旧文档引用继续可用 |
| 反模式清理 | 移除 `gui.py` 旧有 global 跨函数传参（被模块级 `_VIDEO_LIST` / `_COURSE_NAME` / `_PROFESSOR` / `_SELECTED_VIDEOS` / `_TRACKS` 替代，单进程单用户 CLI 够用） |

### I. Textual 框架重构 TUI（6 项）

H 节的初版 TUI 用 Python 标准库 curses 手写：自管 `Row` / `draw_line` / `draw_menu` / `draw_multi_select` 等渲染工具，靠 ANSI 转义 + 键盘 raw 模式实现。本节用 [Textual](https://textual.textualize.io/) 8.x 框架替换手写 curses，对外接口不变（`app.result` 仍返回 `(videoList, courseName, professor, selected_videos, tracks_dict)`），`main.main_tui()` 无需感知 TUI 实现细节。

| 项 | 关键文件 / 位置 |
| --- | --- |
| TUI 框架 | `tui.py`：`CourseApp(App)` 主类 + 10 个 `ModalScreen` 子类（`ChooseCourseScreen` / `InputCourseIdScreen` / `SearchCourseScreen` / `PickOneScreen` / `ChooseVideosScreen` / `SingleVideoScreen` / `MultiVideoScreen` / `ChooseTracksScreen` / `AuthTokenScreen` / `MessageScreen`），每阶段一个屏 |
| 控件 | `SelectionList`（多选：视频轨 / 音频轨 / 学期筛选 / 多节视频）、`OptionList`（单选：搜索结果课程 / 单节视频）、`Input`（文本输入：课程号 / 搜索关键词 / token）、`Button`（动作按钮）、`Label` / `Static`（标题 / 状态栏） |
| CSS 样式 | `tui.tcss`（93 行）：配色变量、圆角边框 `$primary`、状态栏 `dock: bottom`、按钮居中、警告色 `#msg`；由 `CourseApp.CSS_PATH` 加载 |
| PyInstaller hook | `hooks/hook-textual.py`：`collect_submodules('textual'/'textual.widgets'/'rich'/'rich.jupyter')` + `collect_data_files('textual'/'textual.widgets')` + 项目自带 `tui.tcss` 数据文件；打包时需 `--additional-hooks-dir hooks` |
| 依赖 | `pyproject.toml` 删 `windows-curses`（Textual 不依赖 curses），加 `textual>=8.2.8`；`uv sync` 自动装 |
| Frozen 兼容 | `tui.py` 中 `_CSS_PATH` 用 `sys._MEIPASS` 解析（`getattr(sys, 'frozen', False)` 分支），PyInstaller 打包后 CSS 自动定位 |

**对外接口**（与 H 节兼容）：

```python
import tui
app = tui.CourseApp()
app.run()
# 成功：app.result = (videoList, courseName, professor, selected_videos, tracks_dict)
# 取消：app.result is None
```

**遗留风险**：Textual 在 Windows 控制台的渲染有已知问题（[Textual issue #5162](https://github.com/Textualize/textual/issues/5162)），macOS / Linux 已通过 Pilot 模拟 + PyInstaller 抓屏验证（终端内 CSS 边框 / 按钮 / 状态栏全部应用），Windows 打包后渲染待 Windows 环境用户验证。

## 用法

本节只覆盖本 fork 新增或变更的功能。原有用法（m3u8 下载、token 刷新等）见 `README.md` / `项目详解.md`。

### 1. SSO 3 层 fallback 登录

**前置**：`.env` 配学号密码。

```bash
# 项目根目录
cp .env.example .env
# 编辑 .env，填入学号和密码
# STUDENT_ID=your_student_id
# PASSWORD=your_password

# 一键登录（自动走 3 层 fallback）
uv run python login_sso_unified.py

# 单独跑 Tier 1（最快，纯 requests）
uv run python login_sso_requests.py

# 单独跑 Tier 3（强制有头浏览器，交互式 captcha）
uv run python auth_patchright.py
```

成功登录后 Bearer token 写入 `auth.txt`，所有下载入口（`main.py` 统一 CLI / `webui_interface.py` WebUI）自动复用；`gui.py` 作为旧入口重定向到 `main.py`，行为一致。token 失效时会再次自动调用 3 层 fallback 续期。

**WebUI 端**：启动 webui 后，登录页有专门的 SSO 配置入口。

### 2. 双轨 mkv 合并

下载摄像头 + 屏幕画面 + 蓝牙话筒，最终合成 5 stream 的单 mkv。

**CLI（main.py 选项 3）**：

```bash
uv run python main.py
# 提示输入：courseID -> 选视频 -> 信号类型选 3 -> 音频默认下载
# 提示输入 vga 类型时输入 3 走双轨合并
```

**WebUI**：下载类型下拉选 "双轨合并(摄像头+屏幕+蓝牙)"。

输出路径：`output/<课程名>-merged/<课次>.mkv`，同时保留 main / vga / 蓝牙原始文件作为中间产物（可配置清理）。

### 3. MLX Qwen3-ASR 字幕

为已下载视频生成 SRT 字幕（macOS Apple Silicon，MLX 加速）。

```bash
# 装 ASR 依赖
uv sync --extra asr

# 生成字幕：传本地媒体路径
uv run python gen_caption.py /path/to/video.mp4

# 不传路径则交互式选择模型（4 个量化档位可选）
uv run python gen_caption.py
```

可选模型（在 `gen_caption.py` 定义）：

- `mlx-community/Qwen3-ASR-1.7B-bf16`（满精度，最慢）
- `mlx-community/Qwen3-ASR-1.7B-8bit`
- `mlx-community/Qwen3-ASR-1.7B-6bit`
- `mlx-community/Qwen3-ASR-1.7B-4bit`（最小，最快）

字幕文件落在媒体同目录，文件名 `<media>.srt`。字幕文本走 `zhconv` 转为简体中文。

### 4. WebUI 课程搜索

```bash
uv run python webui_interface.py
# 浏览器自动打开 http://0.0.0.0:5001/
```

- **搜索 Tab**：按关键词 + 学期分页搜索全校课程
- **我的课程 Tab**：拉取当前账号已选课程列表
- 学期下拉从 `/semesters` 端点拉取

## 已知差异（与 upstream 对照）

- upstream `login_sso_*` 系列文件在本 fork 中全部重写或替换，不要尝试 cherry-pick upstream 的 Patchright 登录改动
- `gen_caption.py` 已切到 MLX Qwen3-ASR，回到原 whisper 需要回滚 `pyproject.toml` 依赖 + 还原 `hooks/hook-whisper.py`
- `pyproject.toml` 新增 `python-dotenv` / `pycryptodome` / `beautifulsoup4` / `mlx-audio`（asr extra），打包 PyInstaller 时注意 `hooks/hook-mlx_audio.py` 和 `hooks/hook-zhconv.py`
