import os
import sys

import m3u8dl
import utils

headers = {
    "Origin": "https://www.yanhekt.cn",
    "xdomain-client": "web_user",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36 Edg/107.0.1418.26",
}


@utils.print_help
def main():
    if len(sys.argv) == 1:
        courseID = input("输 入 课 程 ID: ")
    else:
        courseID = sys.argv[1]

    if not utils.ensure_auth(courseID=courseID):
        # SSO 3 层 fallback 失败, fallback 到手动输入 token
        auth = input("。".join(utils.auth_prompt()))
        utils.write_auth(auth)
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
        "选 择 下 载: 1.摄 像 头 2.电 脑 屏 幕 3.双 轨 合 并(摄 像 头+屏 幕+蓝 牙)?(输 入 1/2/3, 默 认 1):"
    )
    audio = ""
    if vga != "3":
        audio = input(
            "是 否 下 载 教 室 蓝 牙 话 筒 的 音 频 ?若 教 师 未 使 用 蓝 牙 话 筒 则 该 音 频 无 声 音 (输 入 1不 下 载, 默 认 下 载):"
        )
    if not os.path.exists("output/"):
        os.mkdir("output/")
    for i in index:
        c = videoList[i]
        name = courseName + "-" + professor + "-" + c["title"]
        print(name)
        if vga == "3":
            # 双轨合并: 下载 main + vga + 蓝牙 -> mkv
            path = f"output/{courseName}-merged"
            os.makedirs(path, exist_ok=True)
            print("Downloading camera (main)...")
            m3u8dl.M3u8Download(c["videos"][0]["main"], path, name + "-main")
            print("Downloading screen (vga)...")
            m3u8dl.M3u8Download(c["videos"][0]["vga"], path, name + "-vga")
            audio_aac = None
            if c["video_ids"]:
                audio_url = utils.get_audio_url(c["video_ids"][0])
                if audio_url:
                    print("Downloading bluetooth audio...")
                    utils.download_audio(audio_url, path, name + "-main")
                    audio_aac = os.path.join(path, name + "-main.aac")
            mkv_path = os.path.join(path, name + ".mkv")
            print("Merging to mkv...")
            m3u8dl.merge_to_mkv(
                os.path.join(path, name + "-main.mp4"),
                os.path.join(path, name + "-vga.mp4"),
                audio_aac,
                mkv_path,
                vga_offset=-0.5,
            )
            print(f"Merged: {mkv_path}")
        elif vga == "2":
            path = f"output/{courseName}-screen"
            print("Downloading screen...")
            m3u8dl.M3u8Download(c["videos"][0]["vga"], path, name)
        else:
            path = f"output/{courseName}-video"
            print("Downloading video...")
            m3u8dl.M3u8Download(c["videos"][0]["main"], path, name)
        if vga != "3" and audio == "" and c["video_ids"]:
            audio_url = utils.get_audio_url(c["video_ids"][0])
            if audio_url:
                print("Downloading audio...")
                utils.download_audio(audio_url, path, name)
                print("Download audio successfully.")


if __name__ == "__main__":
    main()
