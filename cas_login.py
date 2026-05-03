"""
延河课堂 CAS 登录模块
复用 course 项目的 CAS 登录逻辑，适配 yanhekt 的 callback
"""
import os
import sys
import ssl
import time
import base64
from urllib.parse import urlencode, parse_qs, urlparse

import requests
from bs4 import BeautifulSoup
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad


class CustomHttpAdapter(requests.adapters.HTTPAdapter):
    """自定义 HTTP Adapter，禁用 SSL 验证和兼容老旧服务器"""
    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.set_ciphers('DEFAULT@SECLEVEL=0')
        ctx.options |= 0x4
        pool_kwargs['ssl_context'] = ctx
        return super().init_poolmanager(connections, maxsize, block, **pool_kwargs)


def encrypt_password(password: str, salt: str) -> str:
    """AES-ECB 加密密码，与 course 项目一致

    salt: 从 CAS 页面提取的 base64 编码的 AES 密钥
    返回: base64 编码的加密密码
    """
    key_bytes = base64.b64decode(salt)
    cipher = AES.new(key_bytes, AES.MODE_ECB)
    password_bytes = password.encode('utf-8')
    padded_password = pad(password_bytes, AES.block_size)
    encrypted_bytes = cipher.encrypt(padded_password)
    return base64.b64encode(encrypted_bytes).decode('utf-8')


def verify_cas(sid: str, pwd0: str, service: str = None) -> str:
    """
    CAS 统一身份认证

    sid: 学号
    pwd0: 原始密码
    service: 回调 service URL，默认是延河课堂的 callback

    返回: JWT token (写入 auth.txt 的格式)
    """
    if service is None:
        service = "https%3A%2F%2Fcbiz.yanhekt.cn%2Fv1%2Fcas%2Fcallback"

    cas_url = f"https://sso.bit.edu.cn/cas/login?service={service}"

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }

    session = requests.Session()
    session.trust_env = False

    # 禁用 SSL 警告
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    session.mount("https://", CustomHttpAdapter())

    try:
        # 1. 获取登录参数 (salt 和 execution)
        res = session.get(cas_url, headers=headers, verify=False, timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')

        salt = soup.find('p', id="login-croypto").get_text()
        execution = soup.find('p', id="login-page-flowkey").get_text()

        # 2. AES 加密密码
        encrypted_pwd = encrypt_password(pwd0, salt)

        # 3. 提交登录
        login_data = {
            "username": sid,
            "password": encrypted_pwd,
            "execution": execution,
            "_eventId": "submit",
            "type": "UsernamePassword",
            'geolocation': '',
            'croypto': salt,
            'Captcha_payload': '',
        }

        headers['Content-Type'] = 'application/x-www-form-urlencoded'
        login = session.post(cas_url, headers=headers, data=urlencode(login_data), verify=False, timeout=15)

        if login.status_code != 200:
            raise Exception(f"CAS 登录失败，状态码: {login.status_code}")

        # 4. 检查是否登录成功 (回调 URL 应包含 ticket)
        final_url = login.url
        params = parse_qs(urlparse(final_url).query)

        if 'ticket' not in params:
            raise Exception(f"CAS 登录未返回 ticket，URL: {final_url[:200]}")

        ticket = params['ticket'][0]

        # 5. 延河课堂使用 ticket 换取 token
        callback_url = "https://cbiz.yanhekt.cn/v1/cas/callback"
        callback_res = session.get(
            callback_url,
            params={'ticket': ticket},
            headers=headers,
            verify=False,
            timeout=15
        )

        callback_data = callback_res.json()

        if callback_data.get('code') != 0:
            raise Exception(f"Callback 失败: {callback_data.get('message')}")

        # 获取 token
        data = callback_data.get('data', {})
        token = data.get('token') or data.get('access_token') or callback_data.get('token')
        if not token:
            raise Exception(f"未从 callback 获取到 token: {callback_data}")

        return token

    except Exception as e:
        raise


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="延河课堂 CAS 登录")
    parser.add_argument("sid", help="学号")
    parser.add_argument("pwd", help="密码")
    parser.add_argument("--output", default="auth.txt", help="输出 token 文件")
    args = parser.parse_args()

    token = verify_cas(args.sid, args.pwd)
    with open(args.output, "w") as f:
        f.write(token)
    print(f"Token 已写入 {args.output}")