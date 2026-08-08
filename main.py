"""BIT 延河课堂下载 CLI — 统一入口 (TUI 优先，stdin 降级)。"""
import os
import sys

import m3u8dl
import utils

# 选择结果在 main_plain / _run_tui → _do_download 间传递 (无 tty 走 plain，tty 走 TUI)。
# 保留模块级状态而非 threading.local，单进程单用户 CLI 够用，且调用顺序固定。
_SELECTED_VIDEOS: list = []
_DOWNLOAD_MODE: int = 0  # 0=main, 1=vga, 2=merge
_DOWNLOAD_AUDIO: list = []
_VIDEO_LIST: list = []
_COURSE_NAME: str = ""
_PROFESSOR: str = ""


@utils.print_help
def main_tui():
    """curses TUI 入口。"""
    import curses
    import tui

    curses.wrapper(_run_tui)


def _run_tui(stdscr):
    import tui

    global _VIDEO_LIST, _COURSE_NAME, _PROFESSOR
    global _SELECTED_VIDEOS, _DOWNLOAD_MODE, _DOWNLOAD_AUDIO

    (
        _VIDEO_LIST,
        _COURSE_NAME,
        _PROFESSOR,
        _SELECTED_VIDEOS,
        _DOWNLOAD_MODE,
        _DOWNLOAD_AUDIO,
    ) = tui.config_tui(stdscr)
    _do_download()


@utils.print_help
def main_plain():
    """stdin 文本交互 (无 tty 时降级用)。"""
    global _SELECTED_VIDEOS, _DOWNLOAD_MODE, _DOWNLOAD_AUDIO
    global _VIDEO_LIST, _COURSE_NAME, _PROFESSOR

    if len(sys.argv) == 1:
        courseID = input("输 入 课 程 ID: ")
    else:
        courseID = sys.argv[1]

    if not utils.ensure_auth(courseID=courseID):
        auth = input("。".join(utils.auth_prompt()))
        utils.write_auth(auth)
        if not utils.test_auth(courseID=courseID):
            print("身份验证失败")
            sys.exit()

    _VIDEO_LIST, _COURSE_NAME, _PROFESSOR = utils.get_course_info(courseID=courseID)
    print(f"课 程 名: {_COURSE_NAME}")
    for i, c in enumerate(_VIDEO_LIST):
        print(f"[{i}]: ", c["title"])

    _SELECTED_VIDEOS = eval(
        "["
        + input(
            "选 择 课 程 编 号 (用 英 文 逗 号 ','分 隔, 例 如: 0,2,4): "
        )
        + "]"
    )
    vga = input(
        "选 择 下 载: 1.摄 像 头 2.电 脑 屏 幕 3.双 轨 合 并"
        "(摄 像 头+屏 幕+蓝 牙)?(输 入 1/2/3, 默 认 1):"
    )
    audio = ""
    if vga != "3":
        audio = input(
            "是 否 下 载 教 室 蓝 牙 话 筒 的 音 频 ?若 教 师 未 使 用 蓝 牙 话 筒"
            " 则 该 音 频 无 声 音 (输 入 1不 下 载, 默 认 下 载):"
        )
    _DOWNLOAD_MODE = {"1": 0, "2": 1, "3": 2}.get(vga, 0)
    _DOWNLOAD_AUDIO = [0] if (vga != "3" and audio == "") else []
    _do_download()


def _do_download():
    """共享下载逻辑：根据 _SELECTED_VIDEOS / _DOWNLOAD_MODE / _DOWNLOAD_AUDIO 执行。"""
    if not os.path.exists("output/"):
        os.mkdir("output/")

    fail = []
    for i in _SELECTED_VIDEOS:
        c = _VIDEO_LIST[i]
        name = f"{_COURSE_NAME}-{_PROFESSOR}-{c['title']}"
        print(name)
        try:
            _download_one(c, name)
        except Exception as e:
            print(e)
            fail.append(name)
            input(f"下载 {name} 失败，按回车键开始下一个")

    if fail:
        print("以下视频下载失败:")
        for f in fail:
            print(f)
    else:
        print("下载结束")


def _download_one(c, name):
    """单条视频下载 — 模式 0=main / 1=vga / 2=merge。"""
    if _DOWNLOAD_MODE == 2:
        # 双轨合并
        path = f"output/{_COURSE_NAME}-merged"
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
        return

    # 单路下载
    if _DOWNLOAD_MODE == 1:
        path = f"output/{_COURSE_NAME}-screen"
        print("Downloading screen...")
        m3u8dl.M3u8Download(c["videos"][0]["vga"], path, name)
    else:
        path = f"output/{_COURSE_NAME}-video"
        print("Downloading video...")
        m3u8dl.M3u8Download(c["videos"][0]["main"], path, name)

    if _DOWNLOAD_AUDIO and c["video_ids"]:
        audio_url = utils.get_audio_url(c["video_ids"][0])
        if audio_url:
            print("Downloading audio...")
            utils.download_audio(audio_url, path, name)
            print("Download audio successfully.")


def main():
    """统一入口：优先 curses TUI，非 tty 降级到 stdin 交互。"""
    import curses

    if not sys.stdout.isatty():
        main_plain()
        return
    try:
        main_tui()
    except Exception as e:
        msg = repr(e).lower()
        if "initscr" in msg or "tty" in msg or "curses" in msg:
            main_plain()
        else:
            raise


if __name__ == "__main__":
    main()
