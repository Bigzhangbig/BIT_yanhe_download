# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Overview

This is a Python tool for downloading course videos from Beijing Institute of Technology's Yanhe Classroom (yanhekt.cn). It supports downloading camera feed, screen capture, and classroom Bluetooth audio via m3u8 streams.

## Dependency Management

This project uses `uv` for Python dependency management, not pip.

- Install base dependencies: `uv sync`
- Install with optional subtitle generation (Whisper): `uv sync --extra whisper`
- Run any script: `uv run python <script>.py`

Requires Python >=3.14 (per `pyproject.toml`) and ffmpeg installed and available on PATH.

## Running the Application

There are two CLI entry points plus a Web GUI:

- **Unified CLI**: `uv run python main.py [courseID]` — `main()` 根据 `sys.stdout.isatty()` 分流：tty 走 `main_tui()`（curses TUI，箭头 + 空格多选，q 退出），非 tty 或 curses 异常自动降级到 `main_plain()`（stdin 文本交互，可传 `courseID`）。功能完整：下载模式三选一（摄像头 / 屏幕 / 双轨合并 `merge_to_mkv` vga_offset=-0.5）+ 蓝牙音频条件下载 + `utils.ensure_auth` SSO 3层 fallback。
- **Thin redirect**: `uv run python gui.py` — 已重定向到 `main.main()`，保留兼容旧入口。
- **Web GUI**: `uv run python webui_interface.py` — starts a Flask server on `http://0.0.0.0:5001/`, auto-opens browser. Serves static files from `webui/` and templates from `templates/`.

curses 交互层抽离在 `tui.py`（`multi_select` / `single_select` / `config_tui`）。

Optional subtitle generation (after downloading videos):
- `uv run python gen_caption.py [media_path]` — uses OpenAI Whisper locally. Prompts for model selection if no path is given.

## Architecture

### Module Responsibilities

- `utils.py` — Shared logic for all entry points. Handles HTTP headers, Bearer auth (read/write `auth.txt`), Yanhe API communication (`cbiz.yanhekt.cn`), URL signing with MD5 timestamps, and audio URL fetching.
- `m3u8dl.py` — Core downloader. Downloads m3u8 streams in parallel (32 threads by default) with bounded queue, handles nested m3u8 playlists, AES key download, periodic signature refresh in a background thread, and merges `.ts` segments into `.mp4` via ffmpeg.
- `main.py` — 统一 CLI 入口。`main()` 按 `sys.stdout.isatty()` 分流 tty/curses TUI（`main_tui`）与非 tty stdin 降级（`main_plain`）；curses 异常也降级 stdin。共享下载逻辑在 `_do_download` / `_download_one`，支持 0=main / 1=vga / 2=merge 三种下载模式 + 蓝牙音频条件下载 + `utils.ensure_auth` SSO 3层 fallback。
- `tui.py` — curses 交互层。提供 `multi_select` / `single_select` / `config_tui`（TUI 完整流程：课程ID -> ensure_auth -> 视频多选 -> 下载模式单选 -> 蓝牙音频多选），以及 `Row` / `draw_line` / `draw_menu` / `draw_multi_select` 等渲染工具。
- `gui.py` — 5 行薄重定向，`from main import main`，保留兼容旧入口。
- `webui_interface.py` — Web GUI，Flask + 多进程 + 线程，独立于 CLI。
- `gen_caption.py` — Standalone script. Extracts audio from `.mp4` with ffmpeg, transcribes with Whisper, and writes `.srt` subtitles (simplified Chinese via `zhconv`).

### Authentication Flow

1. The user copies their Bearer token from Yanhe Classroom browser localStorage (`localStorage.auth`).
2. The token is saved to `auth.txt` and injected into the `Authorization` header in `utils.py`.
3. `utils.test_auth()` validates the token against the course session list API before proceeding.
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
- PyInstaller hook files in `hooks/` (`hook-whisper.py`, `hook-zhconv.py`) may need to be copied to PyInstaller's hooks directory.

## Important Notes

- Course IDs are 5-digit numbers from `yanhekt.cn/course/XXXXX`, not the 6-digit session IDs from the player page.
- Proxies/VPN must be disabled or requests will fail with `check_hostname requires server_hostname`.
- Downloaded files are saved under `output/<course_name>-video/` or `output/<course_name>-screen/`.
- `auth.txt` stores the user's Bearer token in plaintext. It is created automatically on first login and reused until it expires.
