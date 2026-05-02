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


DEFAULT_SESSION = "yanhe-auth"
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


def parse_args():
    parser = argparse.ArgumentParser(
        description="Open YanheKT in patchright-cli and save localStorage.auth.token to auth.txt."
    )
    parser.add_argument("--url", default=DEFAULT_URL, help="YanheKT page to open.")
    parser.add_argument("--session", default=DEFAULT_SESSION, help="patchright-cli session name.")
    parser.add_argument(
        "--profile",
        default=str(default_profile_dir()),
        help="Persistent browser profile directory.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Seconds to wait for login and auth extraction.",
    )
    parser.add_argument("--interval", type=float, default=2.0, help="Polling interval in seconds.")
    parser.add_argument("--auth-file", default="auth.txt", help="File used by downloader auth.")
    parser.add_argument("--course-id", default="", help="Optional course id used to verify auth.")
    parser.add_argument(
        "--skip-open",
        action="store_true",
        help="Only extract auth from an existing patchright-cli session.",
    )
    parser.add_argument(
        "--print-token",
        action="store_true",
        help="Print the extracted token after writing auth file.",
    )
    return parser.parse_args()


def patchright_command(args):
    executable = shutil.which("patchright-cli")
    if not executable:
        raise RuntimeError(
            "未找到 patchright-cli。请先安装 patchright-cli，并确认该命令在 PATH 中可用。"
        )
    completed = subprocess.run(
        [executable, *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode, completed.stdout.strip(), completed.stderr.strip()


def open_browser(args):
    profile = Path(args.profile).expanduser()
    profile.mkdir(parents=True, exist_ok=True)
    command = [
        f"-s={args.session}",
        "open",
        args.url,
        "--persistent",
        f"--profile={profile}",
    ]
    print("正在打开浏览器，请在弹出的窗口中完成延河课堂登录...")
    print("运行命令: " + shlex.join(["patchright-cli", *command]))
    code, stdout, stderr = patchright_command(command)
    if code != 0:
        raise RuntimeError(stderr or stdout or "patchright-cli open 失败")


def read_localstorage_auth(session):
    code, stdout, stderr = patchright_command([f"-s={session}", "localstorage-get", "auth"])
    if code != 0:
        return stderr or stdout
    return stdout


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


def wait_for_auth(args):
    deadline = time.monotonic() + args.timeout
    last_raw = ""
    while time.monotonic() < deadline:
        raw = read_localstorage_auth(args.session)
        token = extract_auth_token(raw)
        if token:
            return token
        if raw != last_raw:
            print("尚未读取到鉴权信息，请确认登录完成后页面已回到 yanhekt.cn。")
            last_raw = raw
        time.sleep(args.interval)
    raise TimeoutError("等待登录超时，未能从 localStorage.auth 中提取 token。")


def main():
    args = parse_args()
    try:
        if not args.skip_open:
            open_browser(args)
        token = wait_for_auth(args)
        write_auth_file(token, args.auth_file)
        if args.course_id and not utils.test_auth(args.course_id):
            raise RuntimeError("已提取 token，但课程鉴权验证失败，请重新登录后再试。")
        print(f"鉴权已写入 {args.auth_file}，可以继续运行下载器。")
        if args.print_token:
            print(token)
    except Exception as exc:
        print(exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
