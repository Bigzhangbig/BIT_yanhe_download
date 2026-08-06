"""
完整抓延河 SSO 登录 CAS 流程 (clean profile,无 TGC 残留)。
抓: 隐藏 fields / cookie / POST body / redirect location。
"""
import asyncio
import base64
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from patchright.async_api import async_playwright

import utils


CAPTURE_FILE = Path(__file__).parent / "sso_capture_fresh.json"
TRIGGER_URL = "https://www.yanhekt.cn/recordCourse"


def sanitize(headers):
    if not headers:
        return {}
    return {k: v for k, v in headers.items() if k.lower() not in {"host", "content-length"}}


async def main():
    capture = {
        "started_at": time.time(),
        "trigger_url": TRIGGER_URL,
        "requests": [],
        "set_cookies_seen": [],
    }
    req_counter = [0]
    # pending: 用 Request 对象作 key,直接拿对应 rec;响应回来时 pop
    pending = {}

    async with async_playwright() as p:
        print("[capture] 启动 fresh chromium (clean profile, no TGC)...")
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context(
            ignore_https_errors=True,
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        # 用 on() 注册(不是 on_request lambda 接受 coroutine)
        ctx.on("request", lambda req: asyncio.create_task(_on_request_async(req, capture, req_counter, pending, ctx)))
        ctx.on("response", lambda resp: asyncio.create_task(_on_response_async(resp, capture, pending)))

        page = await ctx.new_page()

        # 在 page load 之前注入 fetch + XHR 拦截器,抓所有 body
        await page.add_init_script("""
            (() => {
                window.__capturedRequests = [];
                const origFetch = window.fetch;
                window.fetch = function(...args) {
                    try {
                        const [url, opts] = args;
                        const body = opts?.body ? String(opts.body) : null;
                        window.__capturedRequests.push({
                            type: 'fetch', url: String(url), method: opts?.method || 'GET',
                            body: body ? body.slice(0, 5000) : null,
                            headers: opts?.headers || null,
                            ts: Date.now()
                        });
                    } catch(e) {}
                    return origFetch.apply(this, args);
                };
                const origXHR = window.XMLHttpRequest.prototype.open;
                const origSend = window.XMLHttpRequest.prototype.send;
                window.XMLHttpRequest.prototype.open = function(method, url, ...rest) {
                    this.__xhr = {method, url: String(url)};
                    return origXHR.apply(this, [method, url, ...rest]);
                };
                window.XMLHttpRequest.prototype.send = function(body) {
                    try {
                        if (this.__xhr) {
                            window.__capturedRequests.push({
                                type: 'xhr', url: this.__xhr.url, method: this.__xhr.method,
                                body: body ? String(body).slice(0, 5000) : null,
                                headers: null, ts: Date.now()
                            });
                        }
                    } catch(e) {}
                    return origSend.apply(this, [body]);
                };
            })();
        """)

        print(f"[capture] 访问触发端点: {TRIGGER_URL}")
        await page.goto(TRIGGER_URL, wait_until="domcontentloaded", timeout=30000)
        # recordCourse 是公开页,登录按钮在右上角,先点它才弹模态框
        await asyncio.sleep(1)
        try:
            await page.click("button:has-text('登 录')", timeout=5000)
            print("[capture] 已点 '登 录' 按钮")
        except Exception as e:
            print(f"[capture] 找不到 '登 录' 按钮(可能已登录),继续: {e}")

        print("[capture] 等登录弹窗...")
        await page.wait_for_selector(".ant-modal", timeout=10000)
        # 选"北京理工大学"
        try:
            await page.click("#rc_select_0", timeout=3000)
            print("[capture] 已点学校下拉")
        except Exception as e:
            print(f"[capture] 没找到 #rc_select_0,试 text=: {e}")
            await page.click("text=学校", timeout=3000)
        # 等下拉选项渲染,直接用 text 定位(force 点击防 z-index 问题)
        await asyncio.sleep(1.5)
        try:
            await page.get_by_text("北京理工大学", exact=True).first.click(force=True, timeout=5000)
            print("[capture] 已选 北京理工大学")
        except Exception as e:
            print(f"[capture] 选学校失败: {e}")
            # 兜底:等所有 [role=option] 然后取 bit 对应的那行
            await page.wait_for_selector("[role=option]", timeout=5000)
            options = await page.query_selector_all("[role=option]")
            for opt in options:
                txt = (await opt.inner_text() or "").strip()
                if "北京理工大学" in txt:
                    await opt.click(force=True)
                    print(f"[capture] 兜底点击: {txt}")
                    break
        await asyncio.sleep(0.5)

        # 点"登录"按钮 -> 跳 sso
        print("[capture] 点登录,等跳转到 sso.bit.edu.cn...")
        async with page.expect_navigation(wait_until="domcontentloaded", timeout=15000):
            await page.click(".ant-modal button:has-text('登 录')")
        # 现在应该在 sso login page
        cur = page.url
        print(f"[capture] 当前 URL: {cur}")
        if "sso.bit.edu.cn" not in cur:
            print(f"[capture] WARN: 没跳到 sso,在 {cur}")

        # 抓 sso login form fields + cookies
        sso_info = await page.evaluate("""() => {
            const inputs = [...document.querySelectorAll('input')].map(i => ({
                name: i.name, type: i.type, value: i.value?.slice(0,200),
                id: i.id, placeholder: i.placeholder
            }));
            const forms = [...document.forms].map(f => ({
                action: f.action, method: f.method,
                inputs: [...f.elements].map(e => ({tag: e.tagName, name: e.name, type: e.type, value: e.value?.slice(0,200)}))
            }));
            const scripts = [...document.scripts].filter(s => s.src).map(s => s.src);
            return {
                url: location.href,
                title: document.title,
                forms, inputs, scripts,
                cookies: document.cookie,
                htmlSnippet: document.documentElement.outerHTML.slice(0, 30000)
            };
        }""")
        capture["sso_login_page"] = sso_info
        # 抓所有 cookie
        all_cookies = await ctx.cookies()
        capture["all_cookies_after_sso_load"] = all_cookies

        # 写 capture (阶段一,等用户输密码)
        CAPTURE_FILE.write_text(json.dumps(capture, indent=2, ensure_ascii=False))
        print(f"[capture] 阶段一写完,等用户输密码. 文件: {CAPTURE_FILE}")
        print(f"[capture] SSO form fields: {json.dumps(sso_info.get('inputs', []), ensure_ascii=False)[:500]}")
        print(f"[capture] SSO cookies: {all_cookies}")
        print(f"[capture] 浏览器已停在 sso login 页面. 请在浏览器里输账号密码点 '立即登录'.")

        # 等用户登录成功(URL 跳到 cbiz callback)
        try:
            await page.wait_for_url("**/cbiz.yanhekt.cn/**", timeout=300000)  # 5 分钟
            print(f"[capture] 跳到 cbiz! URL: {page.url}")
        except Exception as e:
            print(f"[capture] 等 cbiz 跳转超时: {e}")

        # 再等几秒让 www 域 token 落地
        await asyncio.sleep(3)

        # 抓 localStorage + cookie + token URL
        final_info = await page.evaluate("""() => {
            const auth = localStorage.getItem('auth');
            return { url: location.href, title: document.title, auth, cookies: document.cookie };
        }""")
        capture["final_state"] = final_info
        all_cookies_final = await ctx.cookies()
        capture["all_cookies_final"] = all_cookies_final

        # 读 page-side 拦截器
        captured_reqs = await page.evaluate("() => window.__capturedRequests || []")
        capture["page_side_captured_requests"] = captured_reqs

        CAPTURE_FILE.write_text(json.dumps(capture, indent=2, ensure_ascii=False))
        print(f"[capture] 写完. 总请求数: {len(capture['requests'])}, page-side 抓: {len(captured_reqs)}")

        # 端到端验证
        if final_info.get("auth"):
            try:
                import re
                m = re.search(r'"token":"([0-9a-f]{32})"', final_info["auth"])
                if m:
                    token = m.group(1)
                    print(f"[capture] 拿到 token: {token}")
                    utils.headers["Authorization"] = "Bearer " + token
                    data = utils.get_my_courses()
                    if isinstance(data, dict):
                        n = data.get("total", len(data.get("data", [])))
                    else:
                        n = len(data)
                    print(f"[capture] 验证: 拿到 {n} 门课")
            except Exception as e:
                print(f"[capture] 端到端验证失败: {e}")

        await ctx.close()
        await browser.close()

    capture["ended_at"] = time.time()
    capture["duration_sec"] = capture["ended_at"] - capture["started_at"]
    CAPTURE_FILE.write_text(json.dumps(capture, indent=2, ensure_ascii=False))
    print(f"[capture] DONE. {CAPTURE_FILE}")


# 包装 sync on_request/on_response 为 async (因为 patchright async API)
async def _on_request_async(req, capture, req_counter, pending, ctx):
    req_counter[0] += 1
    rid = f"r{req_counter[0]}"
    try:
        post_data = req.post_data
    except Exception:
        post_data = None
    try:
        cookies = await ctx.cookies(req.url)
    except Exception:
        cookies = []
    rec = {
        "id": rid,
        "url": req.url,
        "method": req.method,
        "resource_type": req.resource_type,
        "headers": sanitize(req.headers or {}),
        "cookies_at_send": [{"name": c["name"], "value": c["value"][:200]} for c in cookies],
    }
    if post_data:
        rec["post_data"] = post_data[:3000]
    capture["requests"].append(rec)
    # 关键:把 rec 写到 pending[req],响应回来时能找回
    pending[req] = rec


async def _on_response_async(resp, capture, pending):
    try:
        req = resp.request
    except Exception:
        return
    rec = pending.pop(req, None)
    if rec is None:
        return
    rec["status"] = resp.status
    rec["response_headers"] = sanitize(resp.headers or {})
    rec["response_url"] = resp.url
    ctype = (resp.headers or {}).get("content-type", "")
    if "text/html" in ctype or "application/json" in ctype:
        try:
            body = await resp.body()
            rec["response_body_b64"] = base64.b64encode(body).decode("ascii")
            rec["response_body_size"] = len(body)
        except Exception as e:
            rec["response_body_err"] = str(e)
    for k, v in (resp.headers or {}).items():
        if k.lower() == "set-cookie":
            capture["set_cookies_seen"].append({"from_url": resp.url, "cookie": v[:500]})
    loc = (resp.headers or {}).get("location")
    if loc:
        rec["location"] = loc


asyncio.run(main())
