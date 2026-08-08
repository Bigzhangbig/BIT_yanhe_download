# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is a Python tool for downloading course videos from Beijing Institute of Technology's Yanhe Classroom (yanhekt.cn). It supports downloading camera feed, screen capture, and classroom Bluetooth audio via m3u8 streams.

## Dependency Management

This project uses `uv` for Python dependency management, not pip.

- Install base dependencies: `uv sync`
- Install with optional subtitle generation (MLX Qwen3-ASR): `uv sync --extra asr`
- Run any script: `uv run python <script>.py`

Requires Python >=3.14 (per `pyproject.toml`) and ffmpeg installed and available on PATH.

## Running the Application

There are two CLI entry points plus a Web GUI:

- **Unified CLI**: `uv run python main.py [courseID]` — `main()` 根据 `sys.stdout.isatty()` 分流：tty 走 `main_tui()`（curses TUI，箭头 + 空格多选，q 退出），非 tty 或 curses 异常自动降级到 `main_plain()`（stdin 文本交互，可传 `courseID`）。TUI 走三阶段流程：①选课（输入课程号 / 关键词搜索含学期筛选 / 我的课程）→ ②选节数（单节 / 多节 / 全选）→ ③下载自由组合（2 视频 + 3 音频 multi_select）。下载逻辑在 `_do_download` / `_download_one`，按轨组合走合并 mkv（vga_offset=-0.5，可选是否 map 内嵌音频）或单路 mp4 + 蓝牙 `.aac`，加 `utils.ensure_auth` SSO 3层 fallback。
- **Thin redirect**: `uv run python gui.py` — 已重定向到 `main.main()`，保留兼容旧入口。
- **Web GUI**: `uv run python webui_interface.py` — starts a Flask server on `http://0.0.0.0:5001/`, auto-opens browser. Serves static files from `webui/` and templates from `templates/`.

curses 交互层抽离在 `tui.py`（`multi_select` / `single_select` / `config_tui`）。

Optional subtitle generation (after downloading videos):
- `uv run python gen_caption.py [media_path]` — uses MLX Qwen3-ASR locally. Prompts for model selection if no path is given.

## Architecture

### Module Responsibilities

- `utils.py` — Shared logic for all entry points. Handles HTTP headers, Bearer auth (read/write `auth.txt`), Yanhe API communication (`cbiz.yanhekt.cn`), URL signing with MD5 timestamps, and audio URL fetching.
- `m3u8dl.py` — Core downloader. Downloads m3u8 streams in parallel (32 threads by default) with bounded queue, handles nested m3u8 playlists, AES key download, periodic signature refresh in a background thread, and merges `.ts` segments into `.mp4` via ffmpeg.
- `main.py` — 统一 CLI 入口。`main()` 按 `sys.stdout.isatty()` 分流 tty/curses TUI（`main_tui`）与非 tty stdin 降级（`main_plain`）；curses 异常也降级 stdin。共享下载逻辑在 `_do_download` / `_download_one`，按 `_TRACKS` 自由组合走双轨 mkv（vga_offset=-0.5，可选 map 内嵌音频）或单路 mp4 + 蓝牙 `.aac`；蓝牙命名在合并模式用 `name+'-main'` 与历史兼容，单视频模式用 `name`。模块级状态 `_VIDEO_LIST` / `_COURSE_NAME` / `_PROFESSOR` / `_SELECTED_VIDEOS` / `_TRACKS` 跨 `_run_tui` → `_do_download` 传递（单进程单用户 CLI 够用）。
- `tui.py` — curses 交互层。提供 `multi_select` / `single_select` / `Row` / `draw_line` / `draw_menu` / `draw_multi_select` 等渲染工具，以及三阶段流程 `config_tui`：`_select_course_id`（输入号 / 搜索含学期筛选 / 我的课程）→ `_select_videos`（单节 / 多节 ≥1 / 全选）→ `_select_tracks`（视频轨 ≥1 + 音频轨可空）。
- `gui.py` — 5 行薄重定向，`from main import main`，保留兼容旧入口。
- `webui_interface.py` — Web GUI，Flask + 多进程 + 线程，独立于 CLI。
- `gen_caption.py` — Standalone script. Extracts audio with ffmpeg, transcribes with MLX Qwen3-ASR, and writes `.srt` subtitles (simplified Chinese via `zhconv`).

### Login Modules (SSO 3-layer fallback)

- `login_sso_unified.py` - Main entry point. Orchestrates 3-layer fallback: Tier 1 `login_sso_requests.py` -> Tier 2 `headless_login.py` -> Tier 3 `auth_patchright.py`.
- `login_sso_requests.py` - Tier 1. Pure-requests CAS 3.0 login against `sso.bit.edu.cn`, no browser. Handles 4 captcha types (image/SMS/email/invisible).
- `headless_login.py` - Tier 2. Headless Patchright with persistent profile, reuses TGC cookie. Used when Tier 1 hits a non-interactive captcha.
- `auth_patchright.py` - Tier 3. 自动启动有头 Patchright 浏览器(headful_login), 用户在弹窗完成交互式 captcha, 不需终端跑脚本。
- `capture_sso_flow.py` / `capture_sso_fresh.py` - SSO flow capture/debugging utilities.

### Authentication Flow

1. **Token acquisition** — `main.py` / `webui_interface.py` 在 auth.txt 失效时自动调用 `login_sso_unified` 走 3 层 fallback (see Login Modules above). 也可单独跑 `uv run python login_sso_unified.py`:
   - **`login_sso_requests.py` (recommended)**: pure-requests CAS 3.0 login against `sso.bit.edu.cn`. Reads `STUDENT_ID` + `PASSWORD` from `.env`, no browser needed. N100 24/7 friendly.
   - **`auth_patchright.py` (fallback)**: Patchright-driven browser session. Use only when `login_sso_requests.py` can't bypass an SSO challenge (e.g. hard captcha). Browser profile is persistent at `~/Library/Application Support/BIT_yanhe_download/patchright-profile/`.
2. The Bearer token is extracted (either from CAS callback URL `?token=` or from `localStorage.auth`), saved to `auth.txt` and injected into the `Authorization` header in `utils.py`.
3. `utils.test_token_valid()` validates the token against `/v2/course/private/list` (real course count) before proceeding.
4. `utils.getToken()` fetches a short-lived video token from `cbiz.yanhekt.cn/v1/auth/video/token`.
5. Every m3u8 URL and `.ts` segment URL is signed with the token and an MD5 timestamp/signature pair (`utils.add_signature_for_url()`).
6. `m3u8dl.py` spawns a background thread (`updateSignatureLoop`) to refresh the timestamp/signature every 10 seconds while downloading.

### WebUI Concurrency Model

`webui_interface.py` uses a multi-process + threading architecture:
- A Flask HTTP server handles UI requests on the main thread.
- A background `threading.Thread` consumes `task_queue`.
- Each download task is executed in a separate `multiprocessing.Process` so cancellation (`kill_task`) can terminate the worker forcefully.
- Progress updates are sent back from the child process to the parent via `multiprocessing.Queue`.

### URL Encryption

Video stream URLs are not directly accessible. `utils.encryptURL()` inserts an MD5-derived path segment into the URL before requesting the m3u8 manifest. This magic string and signing scheme are hardcoded in `utils.py` based on the Yanhe frontend.

## Packaging

Release executables are built with PyInstaller. See `README.md` for full details. Key points:
- `uv add --dev pyinstaller` to add the build tool.
- `webui_interface.py` requires `--add-data webui:webui --add-data templates:templates`.
- `gen_caption.py` may hit recursion depth during PyInstaller analysis; fix by adding `import sys; sys.setrecursionlimit(sys.getrecursionlimit() * 5)` to the generated `.spec` file.
- PyInstaller hook files in `hooks/` (`hook-mlx_audio.py`, `hook-zhconv.py`) may need to be copied to PyInstaller's hooks directory.

## Important Notes

- Course IDs are 5-digit numbers from `yanhekt.cn/course/XXXXX`, not the 6-digit session IDs from the player page.
- Proxies/VPN must be disabled or requests will fail with `check_hostname requires server_hostname`.
- Downloaded files are saved under `output/<course_name>-video/` or `output/<course_name>-screen/`.
- `auth.txt` stores the user's Bearer token in plaintext. It is created automatically on first login and reused until it expires.
