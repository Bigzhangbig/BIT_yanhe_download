"""
无头 Patchright 自动登录延河课堂。

跟 auth_patchright.py 的区别:
- 不调 `patchright open` CLI,直接用 Patchright Python API
- 从 .env 读 STUDENT_ID + PASSWORD,自动填表 + 点登录
- 浏览器**不显示窗口**(headless=True),适合 N100 24/7 跑
- 仍走 persistent profile(保留 TGC,后续可能免触发 captcha)
- 如果中途检测到滑块/reCAPTCHA(必须人来),抛 BrowserInteractionRequired 错误
  让上层(fallback 链)决定是否启动有头浏览器让用户来

不需要 Patchright CLI,但需要 .venv 里有 patchright + chromium (uv pip install patchright; patchright install chromium).
"""
import argparse
import re
import sys
import time
from pathlib import Path

from patchright.async_api import async_playwright, TimeoutError as PWTimeout

import utils
from auth_patchright import (
    default_profile_dir,
)
from login_sso_requests import (
    _load_env_creds,
    _mask,
)


RECORDCOURSE_URL = "https://www.yanhekt.cn/recordCourse"


class BrowserInteractionRequired(Exception):
    """无头模式撞到必须用户交互的环节(滑块/reCAPTCHA/WebAuthn/QR),
    调用方应降级到有头浏览器。"""


async def headless_login_and_extract_token(
    username: str,
    password: str,
    *,
    profile_dir: str = None,
    timeout_sec: int = 90,
    verbose: bool = True,
) -> str:
    """在 headless 浏览器里自动填表登录,等 token 出现后写 auth.txt 并返回。

    Raises:
        BrowserInteractionRequired: 检测到必须人来交互的 captcha。
        RuntimeError: 其它登录失败(密码错/网络错/超时等)。
    """
    profile = Path(profile_dir).expanduser() if profile_dir else default_profile_dir()
    profile.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        if verbose:
            print(f"[headless] 启动 chromium (headless, profile={profile})...")
        browser = await p.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            headless=True,
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            ignore_https_errors=True,
        )
        # launch_persistent_context 直接返回 context,可能已有 page
        if browser.pages:
            page = browser.pages[0]
        else:
            page = await browser.new_page()
        try:
            if verbose:
                print(f"[headless] goto {RECORDCOURSE_URL}")
            await page.goto(RECORDCOURSE_URL, wait_until="domcontentloaded", timeout=20000)

            # 短轮询:看是否已登录(profile 里有 TGC 会自动跳到主页)
            for _ in range(20):
                existing = await page.evaluate(
                    "() => { const a = localStorage.getItem('auth'); return a ? JSON.parse(a).token : null; }"
                )
                if existing:
                    if verbose:
                        print(f"[headless] 已在登录态,直接拿 token: {existing}")
                    return existing
                # URL 上也有可能带着 token 落地,等 SPA 跑
                if "yanhekt.cn" in page.url and "cas/login" not in page.url:
                    await asyncio_sleep(0.5)
                    continue
                break

            # 需要登录 — 点登 录按钮 → 弹模态框
            try:
                await page.click("button:has-text('登 录')", timeout=5000)
            except PWTimeout:
                # 可能 modal 已显示,继续
                pass
            await page.wait_for_selector(".ant-modal", timeout=10000)
            # 选学校
            await page.click("#rc_select_0", timeout=5000)
            await asyncio_sleep(1.0)
            try:
                await page.get_by_text("北京理工大学", exact=True).first.click(force=True, timeout=5000)
            except Exception:
                opts = await page.query_selector_all(".ant-select-item-option")
                for opt in opts:
                    txt = (await opt.inner_text() or "").strip()
                    if "北京理工大学" in txt:
                        await opt.click(force=True)
                        break
            await asyncio_sleep(0.5)
            # 填表 (账号密码字段,容错)
            await fill_input(page, ["#nameInput", "input[name=username]", "input[placeholder*='账号']"], username)
            await fill_input(page, ["input[type=password]"], password)
            # 点登录 (modal 内的 登 录 按钮 — 注意不是顶部那个)
            if verbose:
                print(f"[headless] 提交登录 (user={_mask(username)})")
            await page.click(".ant-modal .ant-btn-primary", timeout=10000)
            # 等结果:三种情况
            #   1. 成功 → 跳 www.yanhekt.cn 并 localStorage.auth 有 token
            #   2. 撞 captcha(滑块/reCAPTCHA) → 卡在 sso/bit/edu/cn 的 captcha iframe
            #   3. 密码错 → 留在 sso 登录页 + showErrorTip
            deadline = time.monotonic() + timeout_sec
            captcha_checked = False
            while time.monotonic() < deadline:
                cur_url = page.url
                # 成功?
                if "yanhekt.cn" in cur_url and "cas/login" not in cur_url:
                    token = await page.evaluate("() => { const a = localStorage.getItem('auth'); return a ? JSON.parse(a).token : null; }")
                    if token:
                        return token
                # 撞 captcha?
                if not captcha_checked and "sso.bit.edu.cn" in cur_url:
                    captcha_checked = True
                    html = await page.content()
                    if _detect_interactive_captcha(html):
                        raise BrowserInteractionRequired(
                            "检测到必须用户交互的 captcha(滑块/reCAPTCHA/WebAuthn/i北理扫码). "
                            "无头模式无法解决,请降级到有头浏览器: "
                            f"uv run python auth_patchright.py"
                        )
                # 密码错?
                if "cas/login" in cur_url and "cas/login" == cur_url.split("/")[-1]:
                    # 可能还在 sso 登录页,看 error tip
                    err = await page.evaluate(
                        "() => { const e = document.getElementById('showErrorTip'); return e ? e.innerText : null; }"
                    )
                    if err and err.strip():
                        raise RuntimeError(f"登录失败(无头): {err.strip()[:200]}")
                await asyncio_sleep(1.0)
            raise RuntimeError(f"无头登录超时 ({timeout_sec}s) — 没拿到 token,URL 最后是: {page.url}")
        finally:
            try:
                await browser.close()
            except Exception:
                pass


def _detect_interactive_captcha(html: str) -> bool:
    """检测 SSO 页面是否出现需要用户交互的 captcha。"""
    indicators = [
        "netEaseCaptchaId",       # 网易滑块
        "nc-container",           # 网易滑块 DOM class
        "g-recaptcha",            # Google reCAPTCHA
        "h-captcha",              # hCaptcha
        "cf-turnstile",           # Cloudflare
        # 注意:不查 recaptchaVendor=system(默认无 captcha 时这字段也在)
    ]
    for kw in indicators:
        if kw in html:
            return True
    return False


async def fill_input(page, selectors: list, value: str):
    """按 selector 列表依次尝试,直到找到能 fill 的。"""
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if await el.count() > 0:
                await el.fill(value, timeout=3000)
                return
        except Exception:
            continue
    raise RuntimeError(f"fill_input 失败,所有 selector 都没匹配到: {selectors}")


async def asyncio_sleep(sec: float):
    """包装 asyncio.sleep,跟其它 async 函数一起用。"""
    import asyncio
    await asyncio.sleep(sec)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", default=".env", help="从该文件读 STUDENT_ID + PASSWORD")
    ap.add_argument("--username", help="覆盖 .env 里的 STUDENT_ID")
    ap.add_argument("--password", help="覆盖 .env 里的 PASSWORD")
    ap.add_argument("--profile", help="Patchright persistent profile 目录")
    ap.add_argument("--auth-file", default="auth.txt", help="输出文件")
    ap.add_argument("--timeout", type=int, default=90, help="登录超时(秒)")
    ap.add_argument("--quiet", action="store_true", help="只打必要输出")
    args = ap.parse_args()

    if args.username and args.password:
        sid, pwd = args.username, args.password
    else:
        try:
            sid, pwd = _load_env_creds(Path(args.env_file))
        except Exception as e:
            print(f"[headless] FAILED: {e}", file=sys.stderr)
            sys.exit(1)
    print(f"[headless] user={_mask(sid)} (凭据来源: {args.env_file})")

    import asyncio
    try:
        token = asyncio.run(
            headless_login_and_extract_token(
                sid, pwd,
                profile_dir=args.profile,
                timeout_sec=args.timeout,
                verbose=not args.quiet,
            )
        )
    except BrowserInteractionRequired as e:
        print(f"[headless] {e}", file=sys.stderr)
        sys.exit(3)
    except Exception as e:
        print(f"[headless] FAILED: {e}", file=sys.stderr)
        sys.exit(1)

    # 端到端验证
    utils.headers["Authorization"] = "Bearer " + token
    if not utils.test_token_valid():
        print("[headless] 拿到 token 但 test_token_valid 失败", file=sys.stderr)
        sys.exit(2)
    courses = utils.get_my_courses()
    n = courses.get("total", len(courses.get("data", []))) if isinstance(courses, dict) else len(courses)
    print(f"[headless] 验证通过: {n} 门课")

    Path(args.auth_file).write_text(token, encoding="utf-8")
    print(f"[headless] token 已写入 {args.auth_file}")


if __name__ == "__main__":
    main()
