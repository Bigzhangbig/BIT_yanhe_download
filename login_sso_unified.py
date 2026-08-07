"""
3 层 fallback 延河课堂 SSO 登录。

Tier 1: login_sso_requests (纯 requests) - 无浏览器, 最快
Tier 2: headless_login (无头 patchright)  - 浏览器但不显示窗口, 自动填表
Tier 3: auth_patchright (有头 patchright)  - 浏览器+UI, 用户手动做 captcha

调用 `uv run python login_sso_unified.py` 一条命令走完全部 fallback,
只在真的撞到必须人来交互的 captcha(滑块/勾选/扫码)时提示手动跑有头版本.
"""
import argparse
import sys
import time
from pathlib import Path

import utils
from login_sso_requests import (
    _load_env_creds,
    _mask,
    login_sso_requests,
)


EXIT_OK = 0
EXIT_REQUESTS_FAILED = 1
EXIT_HEADLESS_FAILED = 2
EXIT_HEADLESS_INTERACTIVE = 3  # 撞到必须人交互的 captcha, 提示降级
EXIT_PASSWORD_WRONG = 4


def run_unified_login(
    env_file: str = ".env",
    username: str = None,
    password: str = None,
    auth_file: str = "auth.txt",
    skip_tier1: bool = False,
    skip_tier2: bool = False,
    quiet: bool = False,
) -> int:
    """跑完 3 层 fallback SSO 登录, 成功时 token 已写入 auth_file。

    返回 EXIT_* 退出码。可被 main.py / webui 等 import 调用,
    无需走 CLI argparse。默认顺序: requests -> headless -> headful 提示。
    """
    # 拿凭据
    if username and password:
        sid, pwd = username, password
    else:
        try:
            sid, pwd = _load_env_creds(Path(env_file))
        except Exception as e:
            print(f"[unified] FAILED: {e}", file=sys.stderr)
            return EXIT_REQUESTS_FAILED
    if not quiet:
        print(f"[unified] user={_mask(sid)} (凭据来源: {env_file})")

    # ===== Tier 1: 纯 requests =====
    if not skip_tier1:
        if not quiet:
            print("[unified] === Tier 1: 纯 requests (无浏览器, 最快) ===")
        t0 = time.monotonic()
        try:
            token = login_sso_requests(sid, pwd, verbose=not quiet)
            if not quiet:
                print(f"[unified] Tier 1 成功 ({time.monotonic() - t0:.1f}s)")
            return _write_and_verify(token, auth_file, "tier1")
        except RuntimeError as e:
            err = str(e)
            if "密码" in err or "账号" in err or "错误" in err or "401" in err:
                print(f"[unified] Tier 1 失败: {err[:200]}")
                return EXIT_PASSWORD_WRONG
            if "需要" in err and ("captcha" in err.lower() or "图形" in err or "短信" in err or "邮件" in err or "通行密钥" in err or "扫码" in err):
                print(f"[unified] Tier 1 失败: {err.splitlines()[0]}")
                print("[unified] -> 降级到 Tier 2 (headless patchright)")
                # 走 tier 2
            else:
                print(f"[unified] Tier 1 失败: {err[:200]}")
                print("[unified] -> 降级到 Tier 2 (headless patchright) 兜底")
        except Exception as e:
            print(f"[unified] Tier 1 异常: {e}")
            print("[unified] -> 降级到 Tier 2 (headless patchright) 兜底")
    else:
        if not quiet:
            print("[unified] 跳过 Tier 1 (--skip-tier1)")

    # ===== Tier 2: headless patchright =====
    if not skip_tier2:
        if not quiet:
            print("[unified] === Tier 2: headless patchright (浏览器无 UI, 自动填表) ===")
        t0 = time.monotonic()
        try:
            from headless_login import (
                headless_login_and_extract_token,
                BrowserInteractionRequired,
            )
            import asyncio
            token = asyncio.run(
                headless_login_and_extract_token(
                    sid, pwd, verbose=not quiet,
                )
            )
            if not quiet:
                print(f"[unified] Tier 2 成功 ({time.monotonic() - t0:.1f}s)")
            return _write_and_verify(token, auth_file, "tier2")
        except Exception as e:
            if _is_browser_interaction_error(e):
                print(f"[unified] Tier 2 撞到必须人交互的 captcha, 降级到 Tier 3 有头: {e}")
            else:
                print(f"[unified] Tier 2 失败, 降级到 Tier 3 有头: {e}")
            # 走 Tier 3, 不 return
    else:
        if not quiet:
            print("[unified] 跳过 Tier 2 (--skip-tier2)")

    # ===== Tier 3: 有头 patchright (自动启动浏览器, 不需用户终端跑脚本) =====
    if not quiet:
        print("[unified] === Tier 3: 有头 patchright (自动启动浏览器, 请在弹窗中完成登录) ===")
    try:
        from auth_patchright import headful_login
        token = headful_login(timeout=300, auth_file=auth_file)
        if token:
            return _write_and_verify(token, auth_file, "tier3")
        return EXIT_HEADLESS_FAILED
    except Exception as e:
        print(f"[unified] Tier 3 失败: {e}")
        return EXIT_HEADLESS_FAILED


def _is_browser_interaction_error(e: Exception) -> bool:
    """识别 BrowserInteractionRequired 异常(可来自 requests 也可来自 headless)。"""
    name = type(e).__name__
    return name == "BrowserInteractionRequired" or "交互" in str(e) or "captcha" in str(e).lower()


def _write_and_verify(token: str, auth_file: str, tier_label: str) -> int:
    """写 auth.txt + 端到端验证。"""
    utils.headers["Authorization"] = "Bearer " + token
    if not utils.test_token_valid():
        print(f"[unified] {tier_label} 拿到 token 但 test_token_valid 失败", file=sys.stderr)
        return EXIT_REQUESTS_FAILED
    courses = utils.get_my_courses()
    n = courses.get("total", len(courses.get("data", []))) if isinstance(courses, dict) else len(courses)
    print(f"[unified] {tier_label} 验证通过: {n} 门课")
    Path(auth_file).write_text(token, encoding="utf-8")
    print(f"[unified] {tier_label} token 已写入 {auth_file}")
    return EXIT_OK


def _print_headful_prompt():
    print()
    print("=" * 60)
    print("[unified] Tier 3 兜底: 请手动跑有头浏览器完成登录")
    print("=" * 60)
    print("  uv run python auth_patchright.py")
    print()
    print("说明: 浏览器会弹窗, 自动读 .env 里的 STUDENT_ID + PASSWORD")
    print("      (TODO 当前版本仍是手输, 升级后才会自动填)")
    print("      登录成功后脚本自动从 localStorage 拿 token 写 auth.txt,")
    print("      然后这个统一脚本也直接退 (auth.txt 已有 token).")
    print()


def main():
    ap = argparse.ArgumentParser(
        description="3 层 fallback SSO 登录 (requests -> headless -> headful)"
    )
    ap.add_argument("--env-file", default=".env", help="从该文件读 STUDENT_ID + PASSWORD")
    ap.add_argument("--username", help="覆盖 .env 里的 STUDENT_ID")
    ap.add_argument("--password", help="覆盖 .env 里的 PASSWORD")
    ap.add_argument("--auth-file", default="auth.txt", help="输出文件")
    ap.add_argument("--skip-tier1", action="store_true", help="跳过纯 requests, 直接 headless")
    ap.add_argument("--skip-tier2", action="store_true", help="跳过 headless patchright, 直接提示 headful")
    ap.add_argument("--quiet", action="store_true", help="只打必要输出")
    args = ap.parse_args()
    return run_unified_login(
        env_file=args.env_file,
        username=args.username,
        password=args.password,
        auth_file=args.auth_file,
        skip_tier1=args.skip_tier1,
        skip_tier2=args.skip_tier2,
        quiet=args.quiet,
    )


if __name__ == "__main__":
    sys.exit(main())
