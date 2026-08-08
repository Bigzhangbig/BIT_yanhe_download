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


def _prompt_text(stdscr, prompt):
    """TUI 内单行文本输入 (回车确认)。空回车返回 None。"""
    stdscr.clear()
    draw_line(stdscr, prompt, 0)
    stdscr.refresh()
    return stdscr.getstr().decode("utf-8").strip() or None


def _ensure_at_least_one(stdscr, options, title, subtitle="", checked=None):
    """multi_select 但强制至少选一个。"""
    while True:
        result = multi_select(stdscr, options, title, subtitle, checked=checked)
        if not result:
            stdscr.clear()
            draw_line(stdscr, "请至少选择一个，按回车继续", 0)
            stdscr.getch()
        else:
            return result


def _show_message(stdscr, message):
    """显示一行消息并等待回车。"""
    stdscr.clear()
    draw_line(stdscr, message, 0)
    stdscr.refresh()
    stdscr.getch()


def _pick_course(stdscr, label, fetch):
    """通用课程挑选流程：fetch() 返回 {"data":[...],"total":N,...}；多选课程表 → 返回 5 位 courseID。无结果允许返回上一层重选。"""
    try:
        result = fetch()
    except Exception as e:
        _show_message(stdscr, f"获取课程失败: {e}")
        return None
    courses = result.get("data", [])
    if not courses:
        _show_message(stdscr, "未找到任何课程，按回车返回")
        return None
    labels = [
        f"{c['id']} - {c.get('name_zh') or c.get('name') or '?'}"
        for c in courses
    ]
    idx = single_select(
        stdscr,
        labels,
        label,
        f"共 {result.get('total', len(courses))} 门课程",
        default_index=0,
    )
    return str(courses[idx]["id"])


def _select_course_id(stdscr):
    """阶段1: 选课方式 (输入 / 搜索 / 我的课程) → 返回 5 位 courseID。

    搜索流程额外支持学期筛选：先取学期列表，multi_select 多选（可全不选=不过滤）。
    """
    while True:
        choice = single_select(
            stdscr,
            [
                "1. 输入课程号 (yanhekt.cn/course/XXXXX)",
                "2. 搜索课程",
                "3. 查询我的课程",
            ],
            "选择获取课程的方式",
            "↑↓ 选择，回车确认",
            default_index=0,
        )
        if choice == 0:
            courseID = _prompt_course_id(stdscr)
            if not courseID:
                sys.exit()
            return courseID
        if choice == 1:
            keyword = _prompt_text(stdscr, "输入搜索关键词 (回车=全部):")
            # 学期筛选 (可全不选=不筛选)
            semester_ids = None
            try:
                semesters = utils.get_semesters()
            except Exception as e:
                _show_message(stdscr, f"获取学期列表失败: {e}")
                semesters = []
            if semesters:
                sel = multi_select(
                    stdscr,
                    [s["name"] for s in semesters],
                    "选择学期 (可多选, 全不选=不筛选)",
                    "↑↓+空格多选, 回车确认",
                    checked=[False] * len(semesters),
                )
                if sel:
                    semester_ids = [semesters[i]["id"] for i in sel]
            courseID = _pick_course(
                stdscr,
                "搜索结果 — 请选择课程",
                lambda: utils.search_courses(
                    keyword=keyword or "",
                    page=1,
                    page_size=16,
                    semesters=semester_ids,
                ),
            )
            if courseID:
                return courseID
            continue
        # 我的课程: 不支持学期筛选
        courseID = _pick_course(
            stdscr,
            "我的课程 — 请选择课程",
            lambda: utils.get_my_courses(page=1, page_size=16),
        )
        if courseID:
            return courseID


def _select_videos(stdscr, videoList, courseName):
    """阶段2: 选节数 (单节 / 多节 / 全选)。返回 [index, ...]。"""
    if not videoList:
        _show_message(stdscr, "该课程没有视频，按任意键退出")
        stdscr.getch()
        sys.exit()
    while True:
        mode = single_select(
            stdscr,
            ["1. 单节", "2. 多节", "3. 全选"],
            f"课程名: {courseName} ({len(videoList)} 节)",
            "请选择节数范围",
            default_index=2,
        )
        if mode == 0:
            idx = single_select(
                stdscr,
                [v["title"] for v in videoList],
                f"课程名: {courseName}",
                "请选择单节视频",
                default_index=0,
            )
            return [idx]
        if mode == 1:
            return _ensure_at_least_one(
                stdscr,
                [v["title"] for v in videoList],
                f"课程名: {courseName}",
                "请选择要下载的视频 (≥1)",
            )
        return list(range(len(videoList)))


def _select_tracks(stdscr, courseName):
    """阶段3: 选视频轨 + 音频轨。返回 tracks dict。"""
    video_indices = _ensure_at_least_one(
        stdscr,
        ["摄像头视频 (main)", "屏幕视频 (vga)"],
        f"课程名: {courseName}",
        "选择视频轨 (≥1)",
        checked=[True, True],
    )
    audio_indices = multi_select(
        stdscr,
        ["蓝牙话筒音频", "摄像头内嵌音频", "屏幕内嵌音频"],
        f"课程名: {courseName}",
        "选择音频轨 (可空)",
        checked=[True, True, True],
    )
    return {
        "want_main": 0 in video_indices,
        "want_vga": 1 in video_indices,
        "want_bluetooth": 0 in audio_indices,
        "want_main_audio": 1 in audio_indices,
        "want_vga_audio": 2 in audio_indices,
    }


def config_tui(stdscr):
    """三阶段 TUI 流程。
    返回 (videoList, courseName, professor, selected_videos, tracks_dict)。
    tracks_dict: {want_main, want_vga, want_bluetooth, want_main_audio, want_vga_audio}。
    """
    curses.echo()
    curses.start_color()
    curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_WHITE)
    stdscr.clear()
    stdscr.refresh()

    # 阶段1: 选课方式 → courseID
    courseID = _select_course_id(stdscr)

    if not utils.ensure_auth(courseID=courseID):
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

    # 阶段2: 选节数
    selected_videos = _select_videos(stdscr, videoList, courseName)

    # 阶段3: 选视频轨 + 音频轨
    tracks = _select_tracks(stdscr, courseName)

    stdscr.clear()
    return videoList, courseName, professor, selected_videos, tracks
