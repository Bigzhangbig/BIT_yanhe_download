"""
纯 requests 实现延河课堂 SSO 自动登录。

从 js-reverse MCP 抓包得到的关键信息:
- 入口 GET: https://sso.bit.edu.cn/cas/login?service=https%3A%2F%2Fcbiz.yanhekt.cn%2Fv1%2Fcas%2Fcallback
  返回 HTML,form 含 execution 隐藏字段(per-session token,服务器端渲染在
  <p id="login-page-flowkey"> 里,SPA 加载后会再渲染到 form 里)
- 提交 POST: https://sso.bit.edu.cn/cas/login (无 query)
  fields: username / password / type=UsernamePassword / _eventId=submit /
          geolocation / execution / captcha_code
- 成功后 302 -> https://cbiz.yanhekt.cn/v1/cas/callback?ticket=ST-...
  再 302 -> https://www.yanhekt.cn/login?token=<32 hex>&type=Bearer&expired_at=<ts>
- RBA 风控: POST https://sso.bit.edu.cn/ustc-rba-front/fp
  浏览器先调用一次,纯 requests 可以试跳过

凭据从 .env 读 (STUDENT_ID + PASSWORD),默认不打账号密码。
"""
import argparse
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs, quote

import requests
import utils
from dotenv import dotenv_values


SERVICE_URL = "https://cbiz.yanhekt.cn/v1/cas/callback"
LOGIN_PAGE_URL = f"https://sso.bit.edu.cn/cas/login?service={quote(SERVICE_URL, safe='')}"
LOGIN_POST_URL = "https://sso.bit.edu.cn/cas/login"
RBA_URL = "https://sso.bit.edu.cn/ustc-rba-front/fp"
TOKEN_RE = re.compile(r'[?&]token=([0-9a-f]{32})')


def _mask(value: str) -> str:
    """脱敏:账号留前4后2,密码全打 *。"""
    if not value:
        return "<empty>"
    if len(value) <= 6:
        return "***"
    return f"{value[:4]}{'*' * (len(value) - 6)}{value[-2:]}"


def _load_env_creds(env_file: Path) -> tuple[str, str]:
    """从 .env 读 STUDENT_ID + PASSWORD,缺一就抛错。"""
    if not env_file.exists():
        raise FileNotFoundError(
            f"未找到 {env_file},请创建并填入 STUDENT_ID + PASSWORD"
        )
    cfg = dotenv_values(env_file)
    sid = (cfg.get("STUDENT_ID") or "").strip()
    pwd = (cfg.get("PASSWORD") or "").strip()
    if not sid or not pwd:
        raise RuntimeError(
            f"{env_file} 缺少 STUDENT_ID 或 PASSWORD"
        )
    return sid, pwd


def _extract_token_from_url(url: str) -> str:
    """从 /login?token=... URL 提取 32 hex token。"""
    m = TOKEN_RE.search(url)
    if m:
        return m.group(1)
    # 兜底:任何位置扫 32 hex
    m = re.search(r'\b([0-9a-f]{32})\b', url)
    if m:
        return m.group(1)
    raise RuntimeError(f"未从 URL 提取到 token: {url}")


def _detect_2fa_requirement(html: str) -> dict:
    """解析 SSO 登录页(POST 失败后)/cas/login HTML,判断需要什么二次验证。

    返回 dict:
      {
        "type": "none" | "captcha" | "slider" | "recaptcha" | "sms" | "email"
              | "webauthn" | "qr" | "unknown",
        "captcha_url": str | None,
        "prompt": str,  # 给用户看的提示
        "error_msg": str,  # 服务器返回的错误信息
        "browser_required": bool,  # True = 纯 requests 搞不定,需要降级 patchright
      }
    """
    info = {
        "type": "none", "captcha_url": None, "prompt": "", "error_msg": "",
        "browser_required": False,
    }

    # 错误信息: <span id="showErrorTip">...</span> 或 通用错误
    m = re.search(r'<span id="showErrorTip"[^>]*>(.*?)</span>', html, re.DOTALL)
    if m:
        info["error_msg"] = re.sub(r'<[^>]+>', '', m.group(1)).strip()

    # ===== 4 种 captcha 标识识别 (从 SSO login-page-flowkey 同页抓的隐藏 p) =====
    # 1) 网易易盾滑块
    m = re.search(r'<p id="netEaseCaptchaId"[^>]*>([^<]+)</p>', html)
    if m and m.group(1).strip():
        info["type"] = "slider"
        info["prompt"] = "网易易盾滑块验证码(需拖动)"
        info["browser_required"] = True
        return info
    # 2) Google reCAPTCHA / hCaptcha (siteKey 非空)
    m = re.search(r'<p id="siteKey"[^>]*>([^<]+)</p>', html)
    if m and m.group(1).strip():
        info["type"] = "recaptcha"
        info["prompt"] = f"reCAPTCHA / hCaptcha(siteKey={m.group(1).strip()[:12]}...)"
        info["browser_required"] = True
        return info
    # 3) 隐形 reCAPTCHA
    m = re.search(r'<p id="recaptcha-invisible"[^>]*>([^<]+)</p>', html)
    if m and m.group(1).strip() and m.group(1).strip().lower() not in ("false", "0", ""):
        info["type"] = "recaptcha_invisible"
        info["prompt"] = "隐形 reCAPTCHA v3(行为指纹)"
        info["browser_required"] = True
        return info
    # 4) 自定义文本型 captcha(captchaId + captchaImg 都有)
    m = re.search(r'<img[^>]*id="captchaImg"[^>]*src="([^"]+)"', html)
    if m:
        info["captcha_url"] = m.group(1)
        info["type"] = "captcha"
        info["prompt"] = "图形验证码(文本型,直接输入)"
        return info
    m = re.search(r'<p id="captcha-url"[^>]*>([^<]+)</p>', html)
    if m and m.group(1).strip():
        info["captcha_url"] = m.group(1).strip()
        info["type"] = "captcha"
        info["prompt"] = "图形验证码(文本型,直接输入)"
        return info
    # 兜底: <p id="captchaId"> 非空
    m = re.search(r'<p id="captchaId"[^>]*>([^<]+)</p>', html)
    if m and m.group(1).strip():
        # 这是文本 captcha 标识,具体图片 URL 还得在 form 里找;若找不到就先报错
        info["type"] = "captcha"
        info["prompt"] = "图形验证码(需带 session 拉图片)"
        # 兜底 URL
        info["captcha_url"] = "https://sso.bit.edu.cn/cas/captcha"
        return info

    # ===== 二次验证类型 =====
    # 短信 / 邮件: form 切换到 smsLogin / mailLogin tab
    if 'id="current-login-type">smsLogin' in html or 'class="code">smsLogin' in html:
        info["type"] = "sms"
        info["prompt"] = "短信验证码(终端输入 6 位)"
        return info
    if 'id="current-login-type">mailLogin' in html or 'class="code">mailLogin' in html:
        info["type"] = "email"
        info["prompt"] = "邮件验证码(终端输入 6 位)"
        return info

    # 通行密钥: webauthn
    if 'id="current-login-type">webauthn' in html:
        info["type"] = "webauthn"
        info["prompt"] = "通行密钥(WebAuthn,需物理设备/Face ID/Touch ID)"
        info["browser_required"] = True
        return info
    # i北理扫码
    if 'id="current-login-type">shuxiQr' in html:
        info["type"] = "qr"
        info["prompt"] = "i北理扫码(需 i北理 APP)"
        info["browser_required"] = True
        return info

    if info["error_msg"]:
        info["type"] = "unknown"
        info["prompt"] = f"未知(服务器错误: {info['error_msg']})"
    return info


def _prompt_user_for_code(prompt_text: str, *, allow_empty: bool = False) -> str:
    """阻塞等用户在终端输入验证码。空输入(直接回车)除非 allow_empty 否则重试。"""
    while True:
        try:
            code = input(f"\n[prompt] {prompt_text}: ").strip()
        except EOFError:
            raise RuntimeError("用户中断输入 (EOF)")
        if code or allow_empty:
            return code
        print("[prompt] 不能为空,请重新输入")


def _fetch_captcha_image(url: str, session: requests.Session) -> str:
    """下载 captcha 图片到 /tmp/yhe_captcha.<ext>,返回本地路径(同时尝试 macOS open)。"""
    r = session.get(url, timeout=10)
    r.raise_for_status()
    # 推断扩展名
    ctype = r.headers.get("content-type", "")
    ext = ".jpg"
    if "png" in ctype:
        ext = ".png"
    elif "gif" in ctype:
        ext = ".gif"
    elif "jpeg" in ctype:
        ext = ".jpg"
    out = Path("/tmp") / f"yhe_captcha{ext}"
    out.write_bytes(r.content)
    # macOS 弹 Preview
    try:
        import subprocess
        subprocess.Popen(["open", str(out)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
    return str(out)


def login_sso_requests(username: str, password: str, *, skip_rba: bool = False, verbose: bool = True) -> str:
    """纯 requests 跑 CAS 登录,返回 32 hex token。

    skip_rba: 跳过 RBA 指纹(默认不跳,有些网络/会话需要)。
    """
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    })

    # Step 1: GET 登录页,拿 JSESSIONID + execution
    if verbose:
        print(f"[login] GET {LOGIN_PAGE_URL}")
    r1 = s.get(LOGIN_PAGE_URL, allow_redirects=True, timeout=15)
    if verbose:
        print(f"[login] status={r1.status_code} url={r1.url}")
        print(f"[login] cookies: {dict(s.cookies)}")
    if r1.status_code != 200:
        raise RuntimeError(f"GET 登录页失败: {r1.status_code}")

    # 抓 execution 字段
    # 优先: hidden input (Angular SPA 渲染后)
    m = re.search(r'name="execution" value="([^"]+)"', r1.text)
    if not m:
        # 兜底: <p id="login-page-flowkey"> 里的 server-side execution
        m = re.search(r'id="login-page-flowkey"[^>]*>([^<]+)<', r1.text)
    if not m:
        raise RuntimeError("未在登录页找到 execution 字段(可能被反爬)。")
    execution = m.group(1)
    if verbose:
        print(f"[login] execution = {execution[:60]}...")

    # Step 1.5: (可选) RBA 指纹上报
    if not skip_rba:
        # RBA 期望 clientData + fingerprint 等字段,这里用一个空 payload
        # 如果不传,后端可能放行(只对高风险 IP 强制)。失败的 RBA 不会阻塞登录。
        rba_payload = {
            "clientData": "",
            "fingerprint": "",
        }
        try:
            r_rba = s.post(RBA_URL, data=rba_payload, timeout=10)
            if verbose:
                print(f"[login] RBA POST status={r_rba.status_code}")
        except Exception as e:
            if verbose:
                print(f"[login] RBA 失败(忽略): {e}")

    # Step 2: POST 凭据
    form_data = {
        "username": username,
        "password": password,
        "type": "UsernamePassword",
        "_eventId": "submit",
        "geolocation": "",
        "execution": execution,
        "captcha_code": "",
    }
    if verbose:
        print(f"[login] POST {LOGIN_POST_URL} (user={_mask(username)})")
    r2 = s.post(LOGIN_POST_URL, data=form_data, allow_redirects=False, timeout=15)
    if verbose:
        print(f"[login] status={r2.status_code} location={r2.headers.get('Location', '<none>')}")
        print(f"[login] cookies after POST: {dict(s.cookies)}")
        # 打印响应 body 的前 500 字符(注意:可能含 form 状态/error,不含账号密码)
        print(f"[login] body[:500]: {r2.text[:500]}")

    if r2.status_code not in (301, 302):
        # 二次验证 / 风控 / 密码错
        two_fa = _detect_2fa_requirement(r2.text)
        if two_fa["type"] == "captcha":
            # 下载 captcha,让用户看图输入
            if not two_fa["captcha_url"]:
                # 兜底:常见 CAS captcha 路径
                two_fa["captcha_url"] = "https://sso.bit.edu.cn/cas/captcha"
            if verbose:
                print(f"[login] 需要图形验证码: {two_fa['captcha_url']}")
            captcha_path = _fetch_captcha_image(two_fa["captcha_url"], s)
            print(f"[login] 验证码图片已存: {captcha_path} (macOS 会自动用 Preview 打开)")
            # 拿新 execution(captcha 流程通常需要刷新 form)
            r1b = s.get(LOGIN_PAGE_URL, allow_redirects=True, timeout=15)
            m = re.search(r'id="login-page-flowkey"[^>]*>([^<]+)<', r1b.text)
            if m:
                execution = m.group(1)
            captcha_code = _prompt_user_for_code("请输入图中验证码")
            # 重新 POST 加 captcha
            form_data["captcha_code"] = captcha_code
            form_data["execution"] = execution
            if verbose:
                print(f"[login] 重 POST (with captcha)")
            r2 = s.post(LOGIN_POST_URL, data=form_data, allow_redirects=False, timeout=15)
            if verbose:
                print(f"[login] status={r2.status_code} location={r2.headers.get('Location', '<none>')}")
            if r2.status_code not in (301, 302):
                # 二次 captcha 还失败(或别的 2FA)
                two_fa2 = _detect_2fa_requirement(r2.text)
                raise RuntimeError(
                    f"captcha 后仍失败: type={two_fa2['type']} err={two_fa2['error_msg']!r} "
                    f"body[:300]={r2.text[:300]}"
                )
        elif two_fa.get("browser_required"):
            # slider / reCAPTCHA / WebAuthn / QR — 纯 requests 搞不定
            # 给出降级到 patchright 的清晰指令
            fallback_cmd = "uv run python auth_patchright.py"
            if two_fa["type"] == "slider":
                detail = "网易易盾滑块需拖动匹配拼图"
            elif two_fa["type"] == "recaptcha":
                detail = "Google reCAPTCHA 需勾选 '我不是机器人' / 选图"
            elif two_fa["type"] == "recaptcha_invisible":
                detail = "隐形 reCAPTCHA v3 分析行为指纹,纯 requests 无法模拟"
            elif two_fa["type"] == "webauthn":
                detail = "WebAuthn 需 Touch ID / Face ID / 物理密钥"
            elif two_fa["type"] == "qr":
                detail = "i北理扫码需打开 i北理 APP 扫码"
            else:
                detail = "未知浏览器交互"
            raise RuntimeError(
                f"需要 {two_fa['prompt']}\n"
                f"  原因: {detail}\n"
                f"  修法: 降级到 patchright 跑浏览器(用户手输完拿到 token 后,"
                f"auth.txt 仍可被 N100 scheduler 用):\n"
                f"    {fallback_cmd}\n"
                f"  修法 2: 对接打码平台(2Captcha / 超级鹰 / yescaptcha) - 需付费,"
                f"复杂 captcha 也不一定能解"
            )
        elif two_fa["type"] in ("sms", "email"):
            # 二次验证需要手机/邮件验证码
            if verbose:
                print(f"[login] 需要{two_fa['prompt']}")
            code = _prompt_user_for_code(f"请输入{two_fa['prompt']}(6 位数字)")
            # 重新 POST 切到 smsLogin/mailLogin tab 提交
            form_data["type"] = "smsLogin" if two_fa["type"] == "sms" else "mailLogin"
            form_data["captcha_code"] = code
            r1b = s.get(LOGIN_PAGE_URL, allow_redirects=True, timeout=15)
            m = re.search(r'id="login-page-flowkey"[^>]*>([^<]+)<', r1b.text)
            if m:
                execution = m.group(1)
            form_data["execution"] = execution
            if verbose:
                print(f"[login] 重 POST (with {two_fa['type']} code)")
            r2 = s.post(LOGIN_POST_URL, data=form_data, allow_redirects=False, timeout=15)
            if r2.status_code not in (301, 302):
                two_fa2 = _detect_2fa_requirement(r2.text)
                raise RuntimeError(
                    f"{two_fa['prompt']} 后仍失败: type={two_fa2['type']} "
                    f"err={two_fa2['error_msg']!r} body[:300]={r2.text[:300]}"
                )
        else:
            # 未知 / 密码错 / 其它错误
            err = two_fa["error_msg"] or r2.text[:200]
            raise RuntimeError(
                f"POST 登录未返 302: status={r2.status_code} "
                f"2fa={two_fa['type']} err={err!r}"
            )

    # Step 3: 跟 302 -> cbiz callback
    ticket_url = r2.headers["Location"]
    if verbose:
        print(f"[login] GET {ticket_url}")
    r3 = s.get(ticket_url, allow_redirects=False, timeout=15)
    if verbose:
        print(f"[login] status={r3.status_code} location={r3.headers.get('Location', '<none>')}")
    if r3.status_code not in (301, 302):
        raise RuntimeError(f"cbiz callback 未返 302: status={r3.status_code}")

    # Step 4: 跟 302 -> www /login?token=...
    final_url = r3.headers["Location"]
    if verbose:
        print(f"[login] GET {final_url}")
    r4 = s.get(final_url, allow_redirects=True, timeout=15)
    if verbose:
        print(f"[login] final status={r4.status_code} url={r4.url}")

    # token 在 URL 里
    token = _extract_token_from_url(r4.url)
    if verbose:
        print(f"[login] 拿到 token: {token}")
    return token


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", default=".env", help="从该文件读 STUDENT_ID + PASSWORD")
    ap.add_argument("--username", help="覆盖 .env 里的 STUDENT_ID")
    ap.add_argument("--password", help="覆盖 .env 里的 PASSWORD(慎用,会留在 shell history)")
    ap.add_argument("--auth-file", default="auth.txt", help="输出文件(默认 auth.txt)")
    ap.add_argument("--skip-rba", action="store_true", help="跳过 RBA 指纹上报")
    ap.add_argument("--quiet", action="store_true", help="只打必要输出")
    args = ap.parse_args()

    # 拿凭据
    if args.username and args.password:
        username, password = args.username, args.password
    else:
        try:
            username, password = _load_env_creds(Path(args.env_file))
        except Exception as e:
            print(f"[login] FAILED: {e}", file=sys.stderr)
            sys.exit(1)
    print(f"[login] user={_mask(username)} (凭据来源: {args.env_file if not (args.username and args.password) else 'CLI override'})")

    try:
        token = login_sso_requests(
            username, password, skip_rba=args.skip_rba, verbose=not args.quiet,
        )
    except Exception as e:
        print(f"[login] FAILED: {e}", file=sys.stderr)
        sys.exit(1)

    # 端到端验证
    utils.headers["Authorization"] = "Bearer " + token
    if not utils.test_token_valid():
        print("[login] 拿到 token 但 test_token_valid 失败", file=sys.stderr)
        sys.exit(2)
    courses = utils.get_my_courses()
    n = courses.get("total", len(courses.get("data", []))) if isinstance(courses, dict) else len(courses)
    print(f"[login] 验证通过: {n} 门课")

    Path(args.auth_file).write_text(token, encoding="utf-8")
    print(f"[login] token 已写入 {args.auth_file}")


if __name__ == "__main__":
    main()
