import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

import utils


DEFAULT_URL = "https://www.yanhekt.cn/recordCourse"
JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
TOKEN_RE = re.compile(r'"token"\s*:\s*"([^"]+)"')
ESCAPED_TOKEN_RE = re.compile(r'\\"token\\"\s*:\s*\\"([^"\\]+)\\"')


def default_profile_dir():
    if sys.platform == "darwin":
        base_dir = Path.home() / "Library" / "Application Support"
    elif os.name == "nt":
        base_dir = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base_dir = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base_dir / "BIT_yanhe_download" / "patchright-profile"


def default_state_file(profile_dir=None):
    profile = Path(profile_dir).expanduser() if profile_dir else default_profile_dir()
    return profile.parent / "patchright-storage-state.json"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Open YanheKT with patchright and save localStorage.auth.token to auth.txt."
    )
    parser.add_argument("--url", default=DEFAULT_URL, help="YanheKT page to open.")
    parser.add_argument(
        "--profile",
        default=str(default_profile_dir()),
        help="Persistent browser profile directory.",
    )
    parser.add_argument(
        "--state-file",
        default="",
        help="Storage state JSON saved by patchright. Defaults next to --profile.",
    )
    parser.add_argument(
        "--browser",
        default="chromium",
        help="Browser passed to patchright open --browser.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Seconds to wait for login and auth extraction. 0 means no limit.",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=2.0,
        help="Polling interval in seconds.",
    )
    parser.add_argument("--auth-file", default="auth.txt", help="File used by downloader auth.")
    parser.add_argument("--course-id", default="", help="Optional course id used to verify auth.")
    parser.add_argument(
        "--skip-open",
        action="store_true",
        help="Only extract auth from --state-file saved by a previous patchright run.",
    )
    parser.add_argument(
        "--print-token",
        action="store_true",
        help="Print the extracted token after writing auth file.",
    )
    parser.add_argument(
        "--auth-only",
        action="store_true",
        help="Only write auth file and exit instead of entering downloader main flow.",
    )
    return parser.parse_args()


def patchright_executable():
    executable = shutil.which("patchright")
    if not executable:
        raise RuntimeError(
            "未找到 patchright。请先安装 patchright，并确认该命令在 PATH 中可用。"
        )
    return executable


def build_open_command(args):
    profile = Path(args.profile).expanduser()
    profile.mkdir(parents=True, exist_ok=True)
    state_file = get_state_file(args)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    return [
        "open",
        "--browser",
        args.browser,
        "--user-data-dir",
        str(profile),
        "--save-storage",
        str(state_file),
        args.url,
    ]


def get_state_file(args):
    if args.state_file:
        return Path(args.state_file).expanduser()
    return default_state_file(args.profile)


def extract_from_json(value):
    if isinstance(value, dict):
        token = value.get("token")
        if isinstance(token, str) and token.strip():
            return token.strip()
        for item in value.values():
            token = extract_from_json(item)
            if token:
                return token
    elif isinstance(value, list):
        for item in value:
            token = extract_from_json(item)
            if token:
                return token
    elif isinstance(value, str):
        return extract_auth_token(value)
    return ""


def extract_auth_token(raw):
    text = raw.strip()
    if not text or text in {"null", "undefined", "None"}:
        return ""

    for regex in (TOKEN_RE, ESCAPED_TOKEN_RE, JWT_RE):
        match = regex.search(text)
        if match:
            return match.group(1) if match.lastindex else match.group(0)

    candidates = [text]
    candidates.extend(line.strip() for line in text.splitlines() if line.strip())
    if ":" in text:
        candidates.append(text.split(":", 1)[1].strip())
    if "=" in text:
        candidates.append(text.split("=", 1)[1].strip())

    for candidate in candidates:
        candidate = candidate.strip().strip("'")
        try:
            return extract_from_json(json.loads(candidate))
        except json.JSONDecodeError:
            continue
    return ""


def write_auth_file(token, auth_file):
    path = Path(auth_file).expanduser()
    if path.parent != Path("."):
        path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token, encoding="utf-8")
    utils.headers["Authorization"] = "Bearer " + token


def extract_auth_from_storage_state(state_file):
    if not state_file.exists():
        raise FileNotFoundError(f"未找到 Patchright storage state 文件: {state_file}")
    state = json.loads(state_file.read_text(encoding="utf-8"))
    for origin in state.get("origins", []):
        for item in origin.get("localStorage", []):
            if item.get("name") == "auth":
                token = extract_auth_token(item.get("value", ""))
                if token:
                    return token
    raise RuntimeError("未能从 Patchright storage state 的 localStorage.auth 中提取 token。")


def iter_profile_storage_files(profile):
    profile = Path(profile).expanduser()
    for local_storage_dir in profile.glob("*/Local Storage/leveldb"):
        if local_storage_dir.is_dir():
            for path in local_storage_dir.iterdir():
                if path.is_file() and path.suffix in {".log", ".ldb"}:
                    yield path


def extract_auth_from_profile(profile):
    candidates = []
    for path in iter_profile_storage_files(profile):
        text = path.read_bytes().decode("utf-8", errors="ignore")
        for match in TOKEN_RE.finditer(text):
            token = match.group(1).strip()
            if token:
                candidates.append((path.stat().st_mtime, match.start(), token))
        for match in ESCAPED_TOKEN_RE.finditer(text):
            token = match.group(1).strip()
            if token:
                candidates.append((path.stat().st_mtime, match.start(), token))
    if candidates:
        candidates.sort(key=lambda item: (item[0], item[1]))
        return candidates[-1][2]
    raise RuntimeError("未能从 Patchright profile 的 Local Storage 中提取 token。")


def extract_auth(args):
    state_file = get_state_file(args)
    try:
        return extract_auth_from_storage_state(state_file)
    except FileNotFoundError:
        print(f"未找到 Patchright storage state 文件，改为读取浏览器 profile: {args.profile}")
        return extract_auth_from_profile(args.profile)


def wait_for_valid_auth(args):
    deadline = None if args.timeout == 0 else time.monotonic() + args.timeout
    last_error = ""
    while deadline is None or time.monotonic() < deadline:
        try:
            token = extract_auth(args)
            utils.headers["Authorization"] = "Bearer " + token
            if args.course_id and not utils.test_auth(args.course_id):
                raise RuntimeError("已读取到 token，但课程鉴权验证失败。")
            return token
        except Exception as exc:
            message = str(exc)
            if message != last_error:
                print(f"等待登录完成: {message}")
                last_error = message
            time.sleep(args.interval)
    raise TimeoutError("等待登录超时，未能提取并验证鉴权。")


def stop_browser(process):
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def open_browser_and_wait_for_auth(args):
    command = build_open_command(args)
    print("正在打开浏览器，请在弹出的窗口中完成延河课堂登录...")
    print("检测到登录成功后会自动关闭浏览器并继续。")
    print("运行命令: " + shlex.join(["patchright", *command]))
    process = subprocess.Popen(
        [patchright_executable(), *command],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        token = wait_for_valid_auth(args)
    except Exception:
        if process.poll() is not None:
            _, stderr = process.communicate()
            if stderr.strip():
                print(stderr.strip())
        raise
    finally:
        stop_browser(process)
    return token


def run_downloader_main(args):
    import main as downloader_main

    original_argv = sys.argv[:]
    try:
        sys.argv = ["main.py"]
        if args.course_id:
            sys.argv.append(args.course_id)
        downloader_main.main()
    finally:
        sys.argv = original_argv


def main():
    args = parse_args()
    try:
        if not args.skip_open:
            token = open_browser_and_wait_for_auth(args)
        else:
            token = wait_for_valid_auth(args)
        write_auth_file(token, args.auth_file)
        print(f"鉴权已写入 {args.auth_file}，可以继续运行下载器。")
        if args.print_token:
            print(token)
        if not args.auth_only:
            print("正在进入下载主流程...")
            run_downloader_main(args)
    except Exception as exc:
        print(exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
