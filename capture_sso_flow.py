"""
抓 sso.bit.edu.cn 的完整 CAS 登录流程,用于逆向纯 requests 自动登录。

策略:
  1. **不加载 patchright profile**(让 cbiz.yanhekt.cn 的 cookie 强制过期)
  2. 访问一个会触发 SSO 重定向的 cbiz 端点
  3. patchright 被踢到 sso.bit.edu.cn/login,用户输密码
  4. 登录成功跳回 cbiz 域,localStorage 写入 auth token
  5. 把所有 network 请求 + 响应序列化成 JSON
  6. 端到端验证:从 capture 里提取 cbiz session,直接调 /v2/course/private/list

输出: ./sso_capture.json
"""
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from patchright.sync_api import sync_playwright

import utils


CAPTURE_FILE = Path(__file__).parent / "sso_capture.json"
DEFAULT_TRIGGER_URL = "https://cbiz.yanhekt.cn/v2/course/private/list"
LOGIN_WAIT_SECONDS = 300  # 用户输密码最长等 5 分钟


def sanitize_headers(headers: dict) -> dict:
    """去掉一些无关/敏感 header 减少 noise。"""
    if not headers:
        return {}
    skip = {"host", "content-length"}
    out = {}
    for k, v in headers.items():
        kl = k.lower()
        if kl in skip:
            continue
        out[k] = v
    return out


def extract_form_inputs(html: str) -> dict:
    """从 HTML 抽所有 <input> 字段(主要找 hidden form fields like execution / lt)。"""
    import re
    inputs = {}
    for m in re.finditer(r'<input\b([^>]*)/?>', html, flags=re.IGNORECASE | re.DOTALL):
        attrs = m.group(1)
        name_m = re.search(r'\bname=["\']([^"\']+)["\']', attrs)
        value_m = re.search(r'\bvalue=["\']([^"\']*)["\']', attrs)
        type_m = re.search(r'\btype=["\']([^"\']+)["\']', attrs)
        if not name_m:
            continue
        inputs[name_m.group(1)] = {
            "value": value_m.group(1) if value_m else "",
            "type": type_m.group(1) if type_m else "",
        }
    # 抽 form action + method
    form_action = re.search(r'<form\b[^>]*action=["\']([^"\']+)["\']', html, flags=re.IGNORECASE)
    form_method = re.search(r'<form\b[^>]*method=["\']([^"\']+)["\']', html, flags=re.IGNORECASE)
    if form_action:
        inputs["__form_action__"] = form_action.group(1)
    if form_method:
        inputs["__form_method__"] = form_method.group(1)
    return inputs


def main():
    capture = {
        "started_at": time.time(),
        "trigger_url": DEFAULT_TRIGGER_URL,
        "requests": [],   # 顺序排:request 紧跟其 response
    }
    pending_response = {}  # request_id -> request record
    req_counter = [0]
    cbiz_cookie_seen = set()
    sso_cookie_seen = set()

    def on_request(req):
        req_counter[0] += 1
        rid = f"r{req_counter[0]}"
        try:
            post_data = req.post_data
        except Exception:
            post_data = None
        rec = {
            "id": rid,
            "url": req.url,
            "method": req.method,
            "resource_type": req.resource_type,
            "headers": sanitize_headers(req.headers or {}),
        }
        if post_data:
            rec["post_data"] = post_data[:2000]  # 截断
        # 抓 cookie(playwright 不会直接给,我们从 cookie store 读)
        try:
            cookies = ctx.cookies(req.url)
            rec["cookies_at_send"] = [
                {"name": c["name"], "domain": c["domain"], "value": c["value"][:300]}
                for c in cookies
            ]
        except Exception:
            rec["cookies_at_send"] = []
        # 记录哪些域的 cookie 出现过
        host = urlparse(req.url).netloc
        if "cbiz.yanhekt.cn" in host or "www.yanhekt.cn" in host:
            for c in rec["cookies_at_send"]:
                cbiz_cookie_seen.add(c["name"])
        if "sso.bit.edu.cn" in host:
            for c in rec["cookies_at_send"]:
                sso_cookie_seen.add(c["name"])
        capture["requests"].append(rec)
        pending_response[rid] = (len(capture["requests"]) - 1, req)

    def on_response(resp):
        try:
            req = resp.request
        except Exception:
            return
        # 找对应的 request record(用 url + method 匹配最近的)
        # 简单起见:扫描 pending 找匹配的
        for rid, (idx, preq) in list(pending_response.items()):
            if preq is req:
                rec = capture["requests"][idx]
                rec["status"] = resp.status
                rec["response_headers"] = sanitize_headers(resp.headers or {})
                rec["response_url"] = resp.url
                # 抓 response body (只抓 HTML / JSON / form 提交后的页面,其他跳过省内存)
                ctype = (resp.headers or {}).get("content-type", "")
                if (
                    "text/html" in ctype
                    or "application/json" in ctype
                    or "application/x-www-form-urlencoded" in ctype
                ):
                    try:
                        body_bytes = resp.body()
                        rec["response_body_b64"] = __import__("base64").b64encode(body_bytes).decode("ascii")
                        rec["response_body_size"] = len(body_bytes)
                        if "text/html" in ctype:
                            try:
                                html = body_bytes.decode("utf-8", errors="ignore")
                                rec["form_inputs"] = extract_form_inputs(html)
                            except Exception as e:
                                rec["form_inputs_err"] = str(e)
                    except Exception as e:
                        rec["response_body_err"] = str(e)
                # Set-Cookie 头
                sc = []
                # resp.headers 是 case-insensitive dict, 但 set-cookie 可能多个
                for k, v in (resp.headers_all or {}).items() if hasattr(resp, "headers_all") else []:
                    if k.lower() == "set-cookie":
                        sc.append(v)
                # 单值版本
                if not sc:
                    for k, v in (resp.headers or {}).items():
                        if k.lower() == "set-cookie":
                            sc.append(v)
                if sc:
                    rec["set_cookie"] = sc[:20]  # 截断
                # Location (重定向)
                loc = (resp.headers or {}).get("location") or (resp.headers or {}).get("Location")
                if loc:
                    rec["location"] = loc
                del pending_response[rid]
                break

    with sync_playwright() as p:
        print("[capture] 启动 patchright (clean profile, 强制走完整 SSO flow)...")
        browser = p.chromium.launch(headless=False, channel="chrome")
        ctx = browser.new_context(
            ignore_https_errors=True,
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        ctx.on("request", on_request)
        ctx.on("response", on_response)
        page = ctx.new_page()

        print(f"[capture] 访问触发端点: {DEFAULT_TRIGGER_URL}")
        page.goto(DEFAULT_TRIGGER_URL, wait_until="domcontentloaded", timeout=30000)
        # 此时应该跳到 sso.bit.edu.cn 了

        # 等用户输完密码 — 表现为 URL 跳回 cbiz 或 www.yanhekt.cn
        deadline = time.monotonic() + LOGIN_WAIT_SECONDS
        logged_in = False
        while time.monotonic() < deadline:
            cur = page.url
            host = urlparse(cur).netloc
            if "yanhekt.cn" in host and "sso." not in host:
                # 看 localStorage 有没有 auth token
                try:
                    auth_raw = page.evaluate("() => localStorage.getItem('auth')")
                except Exception:
                    auth_raw = None
                if auth_raw:
                    import re as _re
                    m = _re.search(r'"token"\s*:\s*"([0-9a-f]{32})"', auth_raw)
                    if m:
                        token = m.group(1)
                        print(f"[capture] 登录成功! token = {token[:8]}...")
                        capture["extracted_token"] = token
                        logged_in = True
                        break
            time.sleep(1.0)
        if not logged_in:
            print(f"[capture] 等待登录超时 ({LOGIN_WAIT_SECONDS}s)")
            capture["timeout"] = True

        # 再等 3 秒,让 cbiz 域相关 API 请求都飞完
        if logged_in:
            print("[capture] 等 cbiz session 续 3s,让后续 API 请求完成...")
            time.sleep(3.0)
            # 主动触发一次 /v2/course/private/list 看看
            try:
                page.goto("https://cbiz.yanhekt.cn/v2/course/private/list", wait_until="domcontentloaded", timeout=15000)
                time.sleep(1.0)
            except Exception as e:
                print(f"[capture] 触发 API 调用失败: {e}")

        # 收集所有 cbiz + sso cookie store
        capture["final_cookies"] = {
            "yanhekt": [
                {"name": c["name"], "value": c["value"][:200], "domain": c["domain"], "path": c["path"]}
                for c in ctx.cookies("https://yanhekt.cn")
            ],
            "sso.bit.edu.cn": [
                {"name": c["name"], "value": c["value"][:200], "domain": c["domain"], "path": c["path"]}
                for c in ctx.cookies("https://sso.bit.edu.cn")
            ],
        }
        capture["cbiz_cookie_seen_during_flow"] = sorted(cbiz_cookie_seen)
        capture["sso_cookie_seen_during_flow"] = sorted(sso_cookie_seen)

        ctx.close()
        browser.close()

    capture["ended_at"] = time.time()
    capture["duration_sec"] = capture["ended_at"] - capture["started_at"]
    capture["request_count"] = len(capture["requests"])

    CAPTURE_FILE.write_text(json.dumps(capture, indent=2, ensure_ascii=False))
    print(f"[capture] 写入 {CAPTURE_FILE} ({CAPTURE_FILE.stat().st_size} bytes, {len(capture['requests'])} requests)")

    # 端到端验证:用 extracted_token 调 /v2/course/private/list
    if "extracted_token" in capture:
        token = capture["extracted_token"]
        utils.headers["Authorization"] = "Bearer " + token
        try:
            data = utils.get_my_courses()
            if isinstance(data, list) and len(data) > 0:
                print(f"[verify] ✅ 抓到 token 后,纯 requests 调 /v2/course/private/list 返 {len(data)} 门课")
                print(f"[verify] 第 1 门: {data[0].get('title', '?')}")
            else:
                print(f"[verify] ❌ token 似乎无效, 返 {len(data) if isinstance(data, list) else '?'} 门课")
        except Exception as e:
            print(f"[verify] ❌ 端到端失败: {e}")


if __name__ == "__main__":
    main()
