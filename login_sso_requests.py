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
        # 可能是风控拦截、密码错、或表单错误
        raise RuntimeError(
            f"POST 登录未返 302: status={r2.status_code} body[:300]={r2.text[:300]}"
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
