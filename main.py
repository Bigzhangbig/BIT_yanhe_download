import os
import sys

import m3u8dl
import utils
import cas_login

# 尝试加载 .env 配置
def load_env():
    env_file = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip().strip('"').strip("'")


load_env()


def ensure_auth():
    """确保有有效的 auth token，优先从 .env 读取，也可以手动输入"""
    # 尝试从 auth.txt 读取并验证
    if utils.read_auth():
        # 先尝试用现有 token
        course_id = os.environ.get('YANHE_COURSE_ID', '10001')  # 默认课程ID用于测试
        if utils.test_auth(courseID=course_id):
            return True

    # 检查 .env 是否有 credentials
    sid = os.environ.get('YANHE_SID')
    pwd = os.environ.get('YANHE_PASSWORD')

    if sid and pwd:
        print(f"尝试使用 .env 中的账号登录...")
        try:
            token = cas_login.verify_cas(sid, pwd)
            utils.write_auth(token)
            if utils.test_auth(courseID=course_id):
                print("登录成功！")
                return True
        except Exception as e:
            print(f".env 登录失败: {e}")

    # 交互式输入
    print("请选择登录方式:")
    print("1. 输入身份认证码（从浏览器复制）")
    print("2. 输入学号和密码")

    choice = input("选择 (1/2): ").strip()

    if choice == '2':
        sid = input("学号: ").strip()
        pwd = input("密码: ").strip()
        if not sid or not pwd:
            print("学号和密码不能为空")
            sys.exit(1)
        try:
            token = cas_login.verify_cas(sid, pwd)
            utils.write_auth(token)
            print("登录成功！")
        except Exception as e:
            print(f"登录失败: {e}")
            sys.exit(1)
    else:
        # 旧方式：手动输入 token
        auth = input("。".join(utils.auth_prompt()))
        utils.write_auth(auth)
        if not utils.test_auth(courseID=os.environ.get('YANHE_COURSE_ID', '10001')):
            print("身份验证失败")
            sys.exit(1)


@utils.print_help
def main():
    if len(sys.argv) == 1:
        courseID = input("输 入 课 程 ID: ")
    else:
        courseID = sys.argv[1]

    # 确保有有效的 auth
    ensure_auth()

    if not utils.test_auth(courseID=courseID):
        print("身份验证失败")
        sys.exit()

    videoList, courseName, professor = utils.get_course_info(courseID=courseID)

    print(f"课 程 名: {courseName}")

    for i, c in enumerate(videoList):
        print(f"[{i}]: ", c["title"])

    index = eval(
        "[" + input("选 择 课 程 编 号 (用 英 文 逗 号 ','分 隔, 例 如: 0,2,4): ") + "]"
    )
    vga = input(
        "选 择 下 载 摄 像 头 (1) 还 是 电 脑 屏 幕 (2)?(输 入 1 或 2, 默 认 摄 像 头):"
    )
    audio = input(
        "是 否 下 载 教 室 蓝 牙 话 筒 的 音 频 ?若 教 师 未 使 用 蓝 牙 话 筒 则 该 音 频 无 声 音 (输 入 1不 下 载, 默 认 下 载):"
    )
    if not os.path.exists("output/"):
        os.mkdir("output/")
    for i in index:
        c = videoList[i]
        name = courseName + "-" + professor + "-" + c["title"]
        print(name)
        if vga == "2":
            path = f"output/{courseName}-screen"
            print("Downloading screen...")
            m3u8dl.M3u8Download(c["videos"][0]["vga"], path, name)
        else:
            path = f"output/{courseName}-video"
            print("Downloading video...")
            m3u8dl.M3u8Download(c["videos"][0]["main"], path, name)
        if audio == "" and c["video_ids"]:
            audio_url = utils.get_audio_url(c["video_ids"][0])
            if audio_url:
                print("Downloading audio...")
                utils.download_audio(audio_url, path, name)
                print("Download audio successfully.")


if __name__ == "__main__":
    main()