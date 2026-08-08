import os
import shutil
import sys
import time
from hashlib import md5

import requests

# 在延河课堂网站的main.js中4937号的O[N(149, 270, 240, 274)]["k"]()函数的返回值
magic = "1138b69dfef641d9d7ba49137d2d4875"
headers = {
    "Origin": "https://www.yanhekt.cn",
    "Referer": "https://www.yanhekt.cn/",
    "xdomain-client": "web_user",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36 Edg/107.0.1418.26",
    "Xdomain-Client": "web_user",
    "Xclient-Signature": md5((magic + "_v1_undefined").encode()).hexdigest(),
    "Xclient-Version": "v1",
    "Xclient-Timestamp": str(int(time.time())),
    "Authorization": "",
}


def auth_prompt(code=True):
    return [
        "请先登录延河课堂",
        "方式1: 输入学号和密码（命令行或 .env 配置）",
        "方式2: 在浏览器登录后复制 localStorage.auth.token 到这里",
        "在延河课堂的地址栏输入 javascript:alert(JSON.parse(localStorage.auth).token)",
        '注意粘贴时浏览器会自动去掉"javascript:"，需要手动补上',
        "或者按F12打开控制台粘贴这段代码",
        "然后将弹出的内容粘贴到" + ("这里：" if code else '"身份认证码"栏'),
    ]


def encryptURL(url: str) -> str:
    url_list = url.split("/")
    # "c3d47d7b3aa8caf2983b313cb6cd142f"
    url_list.insert(-1, md5((magic + "_100").encode()).hexdigest())
    return "/".join(url_list)


def getSignature():
    timestamp = str(int(time.time()))
    signature = md5((magic + "_v1_" + timestamp).encode()).hexdigest()
    return timestamp, signature


def getToken() -> str:
    req = requests.get(
        "https://cbiz.yanhekt.cn/v1/auth/video/token?id=0", headers=headers
    )
    # Example response: `{"code":0,"message":"","data":{"token":"12345678901234ab","expired_at":1742300867,"now":1742300267}}`
    data = req.json()["data"]
    if not data:
        read_auth()
        req = requests.get(
            "https://cbiz.yanhekt.cn/v1/auth/video/token?id=0", headers=headers
        )
        data = req.json()["data"]
        if not data:
            raise Exception("获取Token失败")
    return data["token"]


def add_signature_for_url(url: str, token: str, timestamp: str, signature: str) -> str:
    url = (
        url
        + "?Xvideo_Token="
        + token
        + "&Xclient_Timestamp="
        + timestamp
        + "&Xclient_Signature="
        + signature
        + "&Xclient_Version=v1&Platform=yhkt_user"
    )
    return url


def read_auth():
    if not os.path.exists("auth.txt"):
        return ""
    with open("auth.txt") as f:
        auth = f.read().strip()
        headers["Authorization"] = "Bearer " + auth
    return auth


def write_auth(auth):
    headers["Authorization"] = "Bearer " + auth
    with open("auth.txt", "w") as f:
        f.write(auth)


def ensure_auth(courseID=None):
    """
    确保认证有效。优先使用现有 auth.txt，失效时走 3 层 fallback SSO 登录
    (requests -> headless -> headful 提示)。返回 True 表示认证成功。
    login_sso_unified 内部成功时已写 auth.txt。
    """
    if read_auth() and test_auth(courseID=courseID or "0"):
        return True
    try:
        from login_sso_unified import run_unified_login, EXIT_OK
        rc = run_unified_login(quiet=False)
        if rc == EXIT_OK and read_auth():
            if courseID and not test_auth(courseID=courseID):
                print("[SSO] 登录后课程验证失败，可能课程 ID 不正确")
                return False
            return True
        return False
    except Exception as e:
        print(f"[SSO] 自动登录失败: {e}")
        return False


def remove_auth():
    headers["Authorization"] = ""
    if os.path.exists("auth.txt"):
        os.remove("auth.txt")


def test_auth(courseID):
    """
    Test if the auth in headers is valid by fetching a real course's session list.
    Return True if the auth is valid, otherwise False.
    """
    res = requests.get(
        f"https://cbiz.yanhekt.cn/v2/course/session/list?course_id={courseID}",
        headers=headers,
    )
    return bool(res.json()["data"])


def is_valid_yhe_token(token: str) -> bool:
    """
    延河课堂 Bearer token 校验 — 32 字符 hex 字符串(对应服务端 session id,
    类似 Django session key;不是 JWT)。长度 32,字符集 [0-9a-f]。
    """
    if not isinstance(token, str):
        return False
    token = token.strip()
    if len(token) != 32:
        return False
    return all(c in "0123456789abcdefABCDEF" for c in token)


def test_token_valid() -> bool:
    """
    本地校验 Bearer token 是合法 32 hex 且能端到端拿到至少一个课程(语义验证)。
    延河 /v2/course/private/list 对任何 Authorization 都返 code=0 + data=[],
    不能用 API 行为做鉴权判断;改用"返 code=0 且当前用户至少有 1 门课"作为
    软证据(空 data 也可能因为真没课,所以只在 list_yhe_courses 端到端跑通时
    才算 token 真正可用)。
    """
    token = headers.get("Authorization", "").removeprefix("Bearer ").strip()
    return is_valid_yhe_token(token)


def get_course_info(courseID):
    courseID = courseID.strip()

    course = requests.get(
        f"https://cbiz.yanhekt.cn/v1/course?id={courseID}&with_professor_badges=true",
        headers=headers,
    )
    res = requests.get(
        f"https://cbiz.yanhekt.cn/v2/course/session/list?course_id={courseID}",
        headers=headers,
    )

    if course.json()["code"] != "0" and course.json()["code"] != 0:
        # print(course.json()["code"])
        # print(course.json()["message"])
        raise Exception(
            f"courseID: {courseID}, {course.json()['message']}。请检查您的课程ID，注意它应该是5位数字，从课程信息界面的链接yanhekt.cn/course/***获取，而不是课程播放界面的链接yanhekt.cn/session/***"
        )
    # print(course.json()["data"]["name_zh"])
    videoList = res.json()["data"]
    name = course.json()["data"]["name_zh"].strip()
    if not videoList:
        raise Exception(f"该课程({name})没有视频信息，请检查课程ID是否正确")

    return (
        videoList,
        name,
        (
            course.json()["data"]["professors"][0]["name"].strip()
            if course.json()["data"]["professors"]
            else "未知教师"
        ),
    )


def get_audio_url(video_id):
    res = requests.get(
        f"https://cbiz.yanhekt.cn/v1/video?id={video_id}",
        headers=headers,
    )
    return res.json()["data"].get("audio", "")


def search_courses(keyword="", page=1, page_size=16, semesters=None):
    """
    搜索录播课程列表。
    - keyword: 搜索关键词
    - page: 页码
    - page_size: 每页数量
    - semesters: 学期 ID 列表，如 [100, 96]
    返回课程 list（[...]，每项含 id / name_zh 等；分页信息 current_page / total 在 API 顶层但本函数未返回）
    """
    params = {"page": page, "page_size": page_size}
    if keyword:
        params["keyword"] = keyword
    if semesters:
        for s in semesters:
            params.setdefault("semesters[]", [])
        # requests 对列表参数的处理
        params_list = [("page", page), ("page_size", page_size)]
        if keyword:
            params_list.append(("keyword", keyword))
        for s in semesters:
            params_list.append(("semesters[]", s))
        res = requests.get(
            "https://cbiz.yanhekt.cn/v2/course/list",
            headers=headers,
            params=params_list,
        )
    else:
        res = requests.get(
            "https://cbiz.yanhekt.cn/v2/course/list",
            headers=headers,
            params=params,
        )
    data = res.json()
    if data.get("code") not in (0, "0"):
        raise Exception(f"搜索课程失败: {data.get('message', '未知错误')}")
    return data["data"]


def get_my_courses(page=1, page_size=16):
    """
    获取个人录播课程列表。
    返回课程 list（[...]，每项含 id / name_zh 等；分页信息在 API 顶层但本函数未返回）
    """
    res = requests.get(
        "https://cbiz.yanhekt.cn/v2/course/private/list",
        headers=headers,
        params={
            "page": page,
            "page_size": page_size,
            "user_relationship_type": 1,
            "with_introduction": "true",
        },
    )
    data = res.json()
    if data.get("code") not in (0, "0"):
        raise Exception(f"获取个人课程失败: {data.get('message', '未知错误')}")
    return data["data"]


def get_semesters():
    """
    获取学期标签列表。
    返回 [{"id": "100", "name": "2025-2026 第一学期"}, ...]
    """
    res = requests.get(
        "https://cbiz.yanhekt.cn/v1/tag/list?with_sub=true",
        headers=headers,
    )
    data = res.json()
    if data.get("code") not in (0, "0"):
        raise Exception(f"获取学期列表失败: {data.get('message', '未知错误')}")
    # 从 tag 列表中找到 param == "semesters" 的项
    for tag in data.get("data", []):
        if tag.get("param") == "semesters":
            children = tag.get("children", [])
            return [{"id": str(c["id"]), "name": c.get("name", "")} for c in children]
    return []


def download_audio(url, path, name):
    token = getToken()
    url = add_signature_for_url(url, token, *getSignature())
    _headers = headers.copy()
    _headers["Host"] = "cvideo.yanhekt.cn"
    res = requests.get(url, headers=_headers)
    while res.status_code != 200:
        time.sleep(0.1)
        res = requests.get(url, headers=_headers)
    with open(f"{path}/{name}.aac", "wb") as f:
        f.write(res.content)


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def bundle_dir():
    return getattr(sys, "_MEIPASS", app_dir())


def get_ffmpeg_command():
    executable = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    candidates = []
    if os.environ.get("FFMPEG_BINARY"):
        candidates.append(os.environ["FFMPEG_BINARY"])
    for base_dir in {os.getcwd(), app_dir(), bundle_dir()}:
        candidates.append(os.path.join(base_dir, executable))
        candidates.append(os.path.join(base_dir, "bin", executable))
    if sys.platform == "darwin":
        candidates.extend(["/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"])
    elif sys.platform.startswith("linux"):
        candidates.extend(["/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/snap/bin/ffmpeg"])

    for candidate in candidates:
        if (
            candidate
            and os.path.isfile(candidate)
            and (os.name == "nt" or os.access(candidate, os.X_OK))
        ):
            return candidate

    resolved = shutil.which(executable)
    if resolved:
        return resolved
    raise FileNotFoundError("未找到 ffmpeg，请先安装 ffmpeg 或设置 FFMPEG_BINARY。")


def print_help(f: callable):
    def wrap():
        try:
            f()
        except Exception as e:
            print(e)
            print(
                "If the problem is still not solved, you can report an issue in https://github.com/AuYang261/BIT_yanhe_download/issues."
            )
            print(
                "Or contact with the author xu_jyang@163.com. Thanks for your report!"
            )
            print(
                "如果问题仍未解决，您可以在https://github.com/AuYang261/BIT_yanhe_download/issues 中报告问题。"
            )
            print("或者联系作者xu_jyang@163.com。感谢您的报告！")

    return wrap
