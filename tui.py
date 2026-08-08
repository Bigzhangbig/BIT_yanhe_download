"""curses TUI helpers + 交互流程 — 与 main.py 配套使用。"""
import curses
import sys

import utils

# 全局对齐偏移 (从 gui.py 保留)
ALIGN = 25


class Row:
    def __init__(self, text, highlighted=False):
        self.text = text
        self.highlighted = highlighted


def get_cmd_window_size(stdscr):
    return stdscr.getmaxyx()


def draw_line(stdscr, text, row):
    """绘制一行文本，自动处理中文字符宽度（每个汉字后补一个空格）。"""
    new_text = ""
    for c in text:
        new_text += c
        if ord(c) > 127:
            new_text += " "
    stdscr.addnstr(row, ALIGN, new_text, get_cmd_window_size(stdscr)[1])


def draw_multi_select(stdscr, messages: list, center_row):
    height, _ = get_cmd_window_size(stdscr)
    total = len(messages)
    visible = min(height - 5, total)
    start_row = max(2, (height // 2) - (visible // 2))
    start_index = min(
        max(0, center_row - (visible // 2)), total - visible
    )
    end_index = min(total, start_index + visible)
    for i in range(start_index, end_index):
        message = messages[i]
        draw_line(
            stdscr,
            message.text + (" <=" if message.highlighted else ""),
            start_row + (i - start_index),
        )


def draw_menu(stdscr, options, checked, title, subtitle, current_row):
    stdscr.clear()
    height, _ = get_cmd_window_size(stdscr)
    draw_line(stdscr, title, 0)
    draw_line(stdscr, subtitle, 1)
    msg = []
    for idx, option in enumerate(options):
        checkmark = "[X]" if checked[idx] else "[ ]"
        msg.append(Row(f"{checkmark} {option}", idx == current_row))
    draw_multi_select(stdscr, msg, current_row)
    draw_line(stdscr, "按上下键移动，按空格键选择/取消选择", height - 2)
    draw_line(stdscr, "按回车键确认，按q键退出", height - 1)
    stdscr.refresh()


def multi_select(stdscr, options, title, subtitle="", checked=None):
    if checked is None:
        checked = [False] * len(options)
    else:
        checked = [bool(c) for c in checked]
    current_row = 0
    while True:
        draw_menu(stdscr, options, checked, title, subtitle, current_row)
        key = stdscr.getch()
        if key == curses.KEY_DOWN:
            current_row = (current_row + 1) % len(options)
        elif key == curses.KEY_UP:
            current_row = (current_row - 1) % len(options)
        elif key == ord("q"):
            sys.exit()
        elif key == ord(" "):
            checked[current_row] = not checked[current_row]
        elif key == curses.KEY_ENTER or key in [10, 13]:
            break
    return [i for i, c in enumerate(checked) if c]


def single_select(stdscr, options, title, subtitle="", default_index=0):
    """单选：箭头移动 + 回车确认，q 退出。返回选中索引。"""
    checked = [False] * len(options)
    checked[default_index] = True
    current_row = default_index
    while True:
        draw_menu(stdscr, options, checked, title, subtitle, current_row)
        key = stdscr.getch()
        if key == curses.KEY_DOWN:
            current_row = (current_row + 1) % len(options)
        elif key == curses.KEY_UP:
            current_row = (current_row - 1) % len(options)
        elif key == ord("q"):
            sys.exit()
        elif key == ord(" "):
            # 单选模式：空格直接确认当前高亮项
            return current_row
        elif key == curses.KEY_ENTER or key in [10, 13]:
            return current_row


def _prompt_course_id(stdscr):
    """TUI 内输入课程 ID。空回车退出。"""
    height, _ = get_cmd_window_size(stdscr)
    stdscr.clear()
    draw_line(stdscr, "请输入课程编号(回车退出):", 0)
    draw_line(stdscr, "https://www.yanhekt.cn/course/", 1)
    stdscr.refresh()
    return stdscr.getstr().decode("utf-8").strip()


def _ensure_at_least_one(stdscr, options, title, subtitle=""):
    """multi_select 但强制至少选一个。"""
    while True:
        result = multi_select(stdscr, options, title, subtitle)
        if not result:
            stdscr.clear()
            draw_line(stdscr, "请至少选择一个，按回车继续", 0)
            stdscr.getch()
        else:
            return result


def config_tui(stdscr):
    """TUI 交互流程。返回 (videoList, courseName, professor, selected_videos, download_mode, download_audio)"""
    curses.echo()
    curses.start_color()
    curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_WHITE)
    stdscr.clear()
    stdscr.refresh()

    courseID = _prompt_course_id(stdscr)
    if not courseID:
        sys.exit()

    if not utils.ensure_auth(courseID=courseID):
        # SSO 失败 → 让用户手动粘贴 token
        stdscr.clear()
        for i, line in enumerate(utils.auth_prompt()):
            draw_line(stdscr, line, i)
        stdscr.refresh()
        auth = stdscr.getstr().decode("utf-8").strip()
        utils.write_auth(auth)
        if not utils.test_auth(courseID=courseID):
            stdscr.clear()
            draw_line(stdscr, "身份验证失败，按任意键退出", 0)
            stdscr.getch()
            sys.exit()

    videoList, courseName, professor = utils.get_course_info(courseID=courseID)

    # 视频选择 (≥1)
    selected_videos = _ensure_at_least_one(
        stdscr,
        [v["title"] for v in videoList],
        f"课程名: {courseName}",
        "请选择要下载的视频:",
    )

    # 下载模式 (三选一): 1=摄像头 2=电脑屏幕 3=双轨合并
    download_mode = single_select(
        stdscr,
        [
            "1. 摄像头 (camera/main)",
            "2. 电脑屏幕 (screen/vga)",
            "3. 双轨合并 (camera+screen+蓝牙音频, mkv)",
        ],
        f"课程名: {courseName}",
        "选择下载模式:",
        default_index=2,
    )

    # 音频: 仅模式非 3 时询问
    if download_mode != 2:
        download_audio = multi_select(
            stdscr,
            ["下载教室蓝牙话筒音频"],
            f"课程名: {courseName}",
            "若教师未使用蓝牙话筒则该音频无声音",
            checked=[True],
        )
    else:
        download_audio = []

    stdscr.clear()
    return videoList, courseName, professor, selected_videos, download_mode, download_audio
