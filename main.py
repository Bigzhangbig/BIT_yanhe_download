"""BIT 延河课堂下载 CLI — 统一入口 (TUI 优先，stdin 降级)。"""
import os
import sys

import m3u8dl
import utils

# 选择结果在 main_plain / _run_tui → _do_download 间传递 (无 tty 走 plain，tty 走 TUI)。
# 保留模块级状态而非 threading.local，单进程单用户 CLI 够用，且调用顺序固定。
_VIDEO_LIST: list = []
_COURSE_NAME: str = ""
_PROFESSOR: str = ""
_SELECTED_VIDEOS: list = []
_TRACKS: dict = {}  # {want_main, want_vga, want_bluetooth, want_main_audio, want_vga_audio}


@utils.print_help
def main_tui():
    """curses TUI 入口。"""
    import curses
    import tui

    curses.wrapper(_run_tui)


def _run_tui(stdscr):
    import tui

    global _VIDEO_LIST, _COURSE_NAME, _PROFESSOR
    global _SELECTED_VIDEOS, _TRACKS

    (
        _VIDEO_LIST,
        _COURSE_NAME,
        _PROFESSOR,
        _SELECTED_VIDEOS,
        _TRACKS,
    ) = tui.config_tui(stdscr)
    _do_download()


@utils.print_help
def main_plain():
    """stdin 文本交互 (无 tty 时降级用) — 简化为全选模式。"""
    global _VIDEO_LIST, _COURSE_NAME, _PROFESSOR
    global _SELECTED_VIDEOS, _TRACKS

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
    print(f"课 程 名: {_COURSE_NAME} ({len(_VIDEO_LIST)} 节)")
    for i, c in enumerate(_VIDEO_LIST):
        print(f"[{i}]: ", c["title"])

    # stdin 降级: 默认全选视频 + 全选轨 (双轨合并)
    sel = input(
        "选 择 课 程 编 号 (默 认 全 选, 用 逗 号 分 隔, 例 如: 0,2,4): "
    ).strip()
    if sel:
        _SELECTED_VIDEOS = [int(x) for x in sel.split(",") if x.strip()]
    else:
        _SELECTED_VIDEOS = list(range(len(_VIDEO_LIST)))
    _TRACKS = {
        "want_main": True,
        "want_vga": True,
        "want_bluetooth": True,
        "want_main_audio": True,
        "want_vga_audio": True,
    }
    _do_download()


def _do_download():
    """共享下载逻辑：根据 _SELECTED_VIDEOS / _TRACKS 执行。"""
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
    """单条视频下载 — 自由组合 want_main/want_vga/want_bluetooth/want_main_audio/want_vga_audio。

    - 双视频 (want_main and want_vga) → 合并 mkv 到 output/<课程名>-merged/
    - 单视频 (仅 main 或仅 vga) → 不合并，mp4 独立
      - 仅 main → output/<课程名>-video/
      - 仅 vga → output/<课程名>-screen/
    - 蓝牙 .aac 跟随: 合并时用 name+"-main" 命名 (与历史兼容)，单视频时用 name 命名
    - 音频轨 want_main_audio / want_vga_audio 只在合并 mkv 时生效 (控制是否 map 内嵌轨)
    """
    want_main = _TRACKS["want_main"]
    want_vga = _TRACKS["want_vga"]
    want_bluetooth = _TRACKS["want_bluetooth"]
    want_main_audio = _TRACKS["want_main_audio"]
    want_vga_audio = _TRACKS["want_vga_audio"]

    if want_main and want_vga:
        # 双轨 → 合并 mkv
        path = f"output/{_COURSE_NAME}-merged"
        os.makedirs(path, exist_ok=True)
        main_mp4 = vga_mp4 = audio_aac = None
        if want_main:
            print("Downloading camera (main)...")
            m3u8dl.M3u8Download(c["videos"][0]["main"], path, name + "-main")
            main_mp4 = os.path.join(path, name + "-main.mp4")
        if want_vga:
            print("Downloading screen (vga)...")
            m3u8dl.M3u8Download(c["videos"][0]["vga"], path, name + "-vga")
            vga_mp4 = os.path.join(path, name + "-vga.mp4")
        if want_bluetooth and c["video_ids"]:
            audio_url = utils.get_audio_url(c["video_ids"][0])
            if audio_url:
                print("Downloading bluetooth audio...")
                utils.download_audio(audio_url, path, name + "-main")
                audio_aac = os.path.join(path, name + "-main.aac")
        mkv_path = os.path.join(path, name + ".mkv")
        print("Merging to mkv...")
        m3u8dl.merge_to_mkv(
            main_mp4,
            vga_mp4,
            audio_aac,
            mkv_path,
            vga_offset=-0.5,
            include_main_audio=want_main_audio,
            include_vga_audio=want_vga_audio,
        )
        print(f"Merged: {mkv_path}")
        return

    # 单路视频: 不合并
    if want_vga:
        path = f"output/{_COURSE_NAME}-screen"
        print("Downloading screen...")
        m3u8dl.M3u8Download(c["videos"][0]["vga"], path, name)
    else:
        path = f"output/{_COURSE_NAME}-video"
        print("Downloading video...")
        m3u8dl.M3u8Download(c["videos"][0]["main"], path, name)

    if want_bluetooth and c["video_ids"]:
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
