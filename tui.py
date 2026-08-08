"""Textual TUI — 三阶段流程 (选课 / 选节 / 选轨)。

对外接口：`CourseApp` 继承自 `textual.app.App`。
- `app = CourseApp(); app.run()` 跑完整流程
- 跑完后从 `app.result` 读 `(videoList, courseName, professor, selected_videos, tracks_dict)`
  失败时 `app.result is None`。
- `tracks_dict` keys: want_main, want_vga, want_bluetooth, want_main_audio, want_vga_audio
"""
import os
import sys
from typing import Any

import utils
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Input,
    Label,
    OptionList,
    Select,
    SelectionList,
    Static,
)
from textual.widgets.option_list import Option
from textual.widgets.selection_list import Selection


# CSS 路径 — 兼容 PyInstaller frozen 环境
if getattr(sys, "frozen", False):
    _BASE_DIR = sys._MEIPASS  # type: ignore[attr-defined]
else:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_CSS_PATH = os.path.join(_BASE_DIR, "tui.tcss")


def _format_course(c: dict) -> str:
    """课程对象 → OptionList 多行展示。字段缺失走兜底。"""
    name = c.get("name_zh") or c.get("name") or "未知课程"
    profs = c.get("professors") or []
    prof_str = "/".join(profs) if profs else "未知教师"
    rooms = c.get("classrooms") or []
    room_names = [r.get("name", "") for r in rooms if r.get("name")]
    room_str = "/".join(room_names) if room_names else "未知教室"
    college = c.get("college_name") or "未知学院"
    count = c.get("participant_count", "?")
    year = c.get("school_year") or "未知学年"
    semester = c.get("semester", "?")
    return (
        f"{name}\n"
        f"{prof_str}\n"
        f"{room_str}\n"
        f"{college} {count}人感兴趣\n"
        f"学期: {year} 第{semester}学期\n"
        f"{'─' * 40}"
    )


def _semester_label(c: dict) -> str:
    """课程 → 学期标签 e.g. '2024-2025 第1学期' (用于结果页筛选)。"""
    sy = c.get("school_year") or ""
    sm = c.get("semester")
    if sy and sm:
        return f"{sy} 第{sm}学期"
    return sy or (str(sm) if sm else "") or "未知"


def _fmt_duration(seconds) -> str:
    """秒数 → M:SS / H:MM:SS。无效输入返回 '?'。"""
    try:
        s = int(seconds)
    except (ValueError, TypeError):
        return "?"
    if s < 0:
        return "?"
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def _fmt_video(v: dict, idx: int, classroom_map: dict | None = None,
                professor: str = "") -> str:
    """节(v session 对象) → 多行 label: 序号/标题/日期/时长/教室/教师。"""
    lines = [f"[{idx + 1:02d}] {v.get('title', '?')}"]

    started_at = v.get("started_at") or ""
    if started_at:
        date_part = started_at.split(" ")[0] if " " in started_at else started_at
        lines.append(f"     日期: {date_part}")

    videos = v.get("videos") or []
    if videos and videos[0].get("duration"):
        lines.append(f"     时长: {_fmt_duration(videos[0]['duration'])}")

    location = v.get("location") or ""
    if location:
        room_name = (classroom_map or {}).get(location, "")
        if room_name and room_name != location:
            lines.append(f"     教室: {room_name} ({location})")
        else:
            lines.append(f"     教室: {location}")

    if professor:
        lines.append(f"     教师: {professor}")

    return "\n".join(lines)


# ---------- 阶段1: 选课 ----------

class ChooseCourseScreen(ModalScreen[str]):
    """阶段1: 选课方式 → 返回 5 位 courseID (空串表示取消)。"""

    BINDINGS = [
        Binding("escape", "cancel", "取消"),
        Binding("enter", "select", "确认"),
    ]

    def compose(self) -> ComposeResult:
        yield Static("BIT 延河课堂 — 选择获取课程的方式", id="title")
        yield Static("↑↓ 移动 · Enter 确认 · Esc 取消", id="subtitle")
        with Vertical(id="stage"):
            ol = OptionList(id="course-actions")
            ol.add_option(Option("输入课程号", id="by-id"))
            ol.add_option(Option("搜索课程", id="by-search"))
            ol.add_option(Option("我的课程", id="by-mine"))
            yield ol
        yield Static("Textual TUI · BIT 延河课堂", id="status")

    def on_mount(self) -> None:
        self.query_one("#course-actions", OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        # OptionList 双击/Enter 都触发，这里统一处理
        self._dispatch(event.option.id)

    def action_select(self) -> None:
        ol = self.query_one("#course-actions", OptionList)
        if ol.highlighted is not None:
            opt = ol.get_option_at_index(ol.highlighted)
            self._dispatch(opt.id)

    def _dispatch(self, option_id: str | None) -> None:
        if option_id == "by-id":
            self.app.push_screen(InputCourseIdScreen(), self._on_result)
        elif option_id == "by-search":
            self.app.push_screen(SearchCourseScreen(), self._on_result)
        elif option_id == "by-mine":
            if not utils.read_auth():
                self.app.push_screen(
                    MessageScreen("请先登录 (输入课程号走 SSO 后再来)", back=True)
                )
                return
            self._fetch_and_pick("我的课程", lambda: utils.get_my_courses(page=1, page_size=16))

    def _fetch_and_pick(self, label: str, fetch):
        try:
            result = fetch()
        except Exception as e:
            self.app.push_screen(MessageScreen(f"获取课程失败: {e}", back=True))
            return
        courses = result if isinstance(result, list) else result.get("data", [])
        if not courses:
            self.app.push_screen(MessageScreen("未找到任何课程", back=True))
            return
        labels = [(_format_course(c), str(c["id"])) for c in courses]
        self.app.push_screen(
            PickOneScreen(
                f"{label} — 请选择课程", labels,
                f"共 {len(courses)} 门", courses=courses,
            ),
            self._on_result,
        )

    def _on_result(self, courseID: str | None) -> None:
        if courseID:
            self.dismiss(courseID)

    def action_cancel(self) -> None:
        self.dismiss("")


class InputCourseIdScreen(ModalScreen[str]):
    """输入课程号 — Enter 提交。"""

    BINDINGS = [Binding("escape", "cancel", "返回")]

    def compose(self) -> ComposeResult:
        yield Static("输入课程编号", id="title")
        yield Static("从 yanhekt.cn/course/XXXXX 链接获取 (5 位数字)", id="subtitle")
        with Vertical(id="stage"):
            yield Label("课程编号：")
            yield Input(placeholder="例如 12345", id="course-id")
        yield Static("Enter 提交 · Esc 返回", id="status")

    def on_mount(self) -> None:
        self.query_one("#course-id", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        v = event.value.strip()
        if v:
            self.dismiss(v)

    def action_cancel(self) -> None:
        self.dismiss("")


class SearchCourseScreen(ModalScreen[str]):
    """搜索课程 — 关键词 + 学期筛选 + 搜索按钮 (焦点在学期时也能提交)。"""

    BINDINGS = [
        Binding("escape", "cancel", "返回"),
        Binding("ctrl+enter", "do_search", "搜索"),
    ]

    def compose(self) -> ComposeResult:
        yield Static("搜索课程", id="title")
        yield Static("关键词 (可空) + 学期 (可空=不过滤)", id="subtitle")
        with Vertical(id="stage"):
            yield Label("搜索关键词 (中文点下方按钮, 英文可直接输 / ⌘V 粘贴):")
            yield Input(placeholder="例如 数据结构 (回车到下一步)", id="keyword")
            yield Button("输入关键词（中文对话框）", id="kw-dialog")
            yield Label("学期 (空格多选, 全不选=不筛选)：")
            yield SelectionList(id="semesters")
            with Horizontal(id="button-row"):
                yield Button("搜索", id="search-btn", variant="primary")
        yield Static("Enter / Ctrl+Enter 搜索 · Esc 返回", id="status")

    def on_mount(self) -> None:
        try:
            semesters = utils.get_semesters()
        except Exception as e:
            self.app.push_screen(MessageScreen(f"获取学期列表失败: {e}", back=True))
            semesters = []
        sl: SelectionList = self.query_one("#semesters", SelectionList)
        for s in semesters:
            sl.add_option(Selection(s["name"], s["id"]))
        self.query_one("#keyword", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "kw-dialog":
            keyword = utils.prompt_external("输入搜索关键词")
            if keyword:
                self.query_one("#keyword", Input).value = keyword
        elif event.button.id == "search-btn":
            self._do_search()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._do_search()

    def action_do_search(self) -> None:
        self._do_search()

    def _do_search(self) -> None:
        keyword = self.query_one("#keyword", Input).value.strip()
        sl: SelectionList = self.query_one("#semesters", SelectionList)
        semester_ids = list(sl.selected) if sl.selected else None
        try:
            result = utils.search_courses(
                keyword=keyword, page=1, page_size=16, semesters=semester_ids
            )
        except Exception as e:
            self.app.push_screen(MessageScreen(f"搜索课程失败: {e}", back=True))
            return
        courses = result if isinstance(result, list) else result.get("data", [])
        if not courses:
            self.app.push_screen(MessageScreen("未找到任何课程", back=True))
            return
        labels = [(_format_course(c), str(c["id"])) for c in courses]
        self.app.push_screen(
            PickOneScreen(
                "搜索结果 — 请选择课程", labels,
                f"共 {len(courses)} 门", courses=courses,
            ),
            self._on_pick,
        )

    def _on_pick(self, courseID: str | None) -> None:
        if courseID:
            self.dismiss(courseID)

    def action_cancel(self) -> None:
        self.dismiss("")


class PickOneScreen(ModalScreen[str]):
    """单选课程列表。带可选学期筛选 (传入 courses 时启用)。"""

    BINDINGS = [Binding("escape", "cancel", "返回")]

    def __init__(
        self,
        title: str,
        items: list[tuple[str, str]],
        subtitle: str = "",
        courses: list[dict] | None = None,
    ) -> None:
        super().__init__()
        self._title = title
        self._items = items
        self._subtitle = subtitle
        # value (course id) → 学期标签; 用于结果页筛学期
        self._item_semester: dict[str, str] = {}
        if courses:
            for c, (_label, value) in zip(courses, items):
                self._item_semester[value] = _semester_label(c)
        self._filter = "全部"
        self._filter_options: list[tuple[str, str]] = []  # (显示, 值)

    def compose(self) -> ComposeResult:
        yield Static(self._title, id="title")
        yield Static(self._subtitle, id="subtitle")
        with Vertical(id="stage"):
            if self._item_semester:
                unique = sorted(set(self._item_semester.values()))
                self._filter_options = [("全部", "全部")] + [(s, s) for s in unique]
                yield Label("按学期筛选:")
                yield Select(
                    options=self._filter_options,
                    value="全部",
                    allow_blank=False,
                    id="semester-filter",
                )
            ol = OptionList(id="pick")
            for label, _ in self._items:
                ol.add_option(Option(label, id=label))
            yield ol
        yield Static("Enter 确认 · Esc 返回", id="status")

    def on_mount(self) -> None:
        self.query_one("#pick", OptionList).focus()

    def on_select_changed(self, event: Select.Changed) -> None:
        self._filter = str(event.value)
        self._rebuild_options()

    def _rebuild_options(self) -> None:
        ol = self.query_one("#pick", OptionList)
        ol.clear_options()
        for label, value in self._items:
            semester = self._item_semester.get(value, "全部")
            if self._filter == "全部" or semester == self._filter:
                ol.add_option(Option(label, id=label))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id is None:
            return
        for label, value in self._items:
            if label == event.option.id:
                self.dismiss(value)
                return

    def action_cancel(self) -> None:
        self.dismiss("")


# ---------- 阶段2: 选节 ----------

class MultiVideoScreen(ModalScreen[list[int]]):
    """多选视频 (≥1)。每节展示序号/标题/日期/时长/教室/教师。"""

    BINDINGS = [
        Binding("escape", "cancel", "返回"),
        Binding("ctrl+a", "toggle_all", "全选"),
        Binding("enter", "submit", "确认"),
    ]

    def __init__(
        self,
        videoList: list,
        courseName: str,
        professor: str = "",
        classrooms: list | None = None,
    ) -> None:
        super().__init__()
        self._videoList = videoList
        self._courseName = courseName
        self._professor = professor
        self._classroom_map = {c.get("number", ""): c.get("name", "")
                               for c in (classrooms or []) if c.get("number")}

    def compose(self) -> ComposeResult:
        yield Static(f"课程：{self._courseName}", id="title")
        yield Static("多选视频 (≥1, 空格切换)", id="subtitle")
        with Vertical(id="stage"):
            sl = SelectionList(id="videos")
            for i, v in enumerate(self._videoList):
                sl.add_option(Selection(
                    _fmt_video(v, i, self._classroom_map, self._professor),
                    v.get("id", v["title"]),
                ))
            yield sl
            yield Static("", id="msg")
            with Horizontal(id="button-row"):
                yield Button("确认", id="ok", variant="primary")
                yield Button("全选", id="all")
        yield Static("空格切换 · Ctrl+A 全选 · Enter 确认", id="status")

    def on_mount(self) -> None:
        self.query_one("#videos", SelectionList).focus()
        self._update_count()
        self._update_all_button()

    def on_selection_list_selection_toggled(
        self, event: SelectionList.SelectionToggled,
    ) -> None:
        self._update_count()
        self._update_all_button()

    def _update_count(self) -> None:
        try:
            sl = self.query_one("#videos", SelectionList)
            msg = self.query_one("#msg", Static)
        except Exception:
            return
        msg.update(f"已选 {len(sl.selected)}/{len(self._videoList)}")

    def _update_all_button(self) -> None:
        try:
            sl = self.query_one("#videos", SelectionList)
            btn = self.query_one("#all", Button)
        except Exception:
            return
        btn.label = "取消全选" if len(sl.selected) >= len(self._videoList) else "全选"

    def action_toggle_all(self) -> None:
        sl: SelectionList = self.query_one("#videos", SelectionList)
        if len(sl.selected) >= len(self._videoList):
            sl.deselect_all()
        else:
            sl.select_all()

    def _confirm(self) -> None:
        sl: SelectionList = self.query_one("#videos", SelectionList)
        sel = list(sl.selected)
        if not sel:
            self.query_one("#msg", Static).update("请至少选择一个")
            return
        ids = [v.get("id", v["title"]) for v in self._videoList]
        indices = [i for i, vid in enumerate(ids) if vid in sel]
        self.dismiss(indices)

    def action_submit(self) -> None:
        self._confirm()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "all":
            self.action_toggle_all()
            return
        if event.button.id == "ok":
            self._confirm()

    def action_cancel(self) -> None:
        self.dismiss([])


# ---------- 阶段3: 选轨 ----------

class ChooseTracksScreen(ModalScreen[dict | None]):
    """阶段3: 选视频轨 + 音频轨。返回 tracks dict 或 None (取消)。"""

    BINDINGS = [
        Binding("escape", "cancel", "取消"),
        Binding("enter", "submit", "确认"),
    ]

    def __init__(self, courseName: str) -> None:
        super().__init__()
        self._courseName = courseName

    def compose(self) -> ComposeResult:
        yield Static(f"课程：{self._courseName}", id="title")
        yield Static("选择视频轨 (可空) + 音频轨 (可空, 但两者至少 1 个)", id="subtitle")
        with Vertical(id="stage"):
            yield Label("视频轨 (可空)：")
            yield SelectionList(
                Selection("摄像头视频 (main)", "main", True),
                Selection("屏幕视频 (vga)", "vga", True),
                id="video-tracks",
            )
            yield Label("音频轨 (可空)：")
            yield SelectionList(
                Selection("蓝牙话筒音频", "bluetooth", True),
                Selection("摄像头内嵌音频", "main_audio", True),
                Selection("屏幕内嵌音频", "vga_audio", True),
                id="audio-tracks",
            )
            yield Static(
                "蓝牙=教师随身麦音质稳；摄像头=摄像机自带mic；屏幕=电脑/大屏mic",
                id="audio-help",
            )
            yield Static("", id="msg")
            with Horizontal(id="button-row"):
                yield Button("开始下载", id="ok", variant="primary")
        yield Static("Enter 确认 · Esc 取消", id="status")

    def on_mount(self) -> None:
        self.query_one("#video-tracks", SelectionList).focus()
        self._update_count()

    def on_selection_list_selection_toggled(
        self, event: SelectionList.SelectionToggled,
    ) -> None:
        # 选视频轨时默认勾上对应内嵌音频 (main->main_audio, vga->vga_audio)
        if event.selection_list.id == "video-tracks" and event.value in event.selection_list.selected:
            audio_sl = self.query_one("#audio-tracks", SelectionList)
            if event.value == "main":
                audio_sl.select("main_audio")
            elif event.value == "vga":
                audio_sl.select("vga_audio")
        self._update_count()

    def _update_count(self) -> None:
        try:
            v = self.query_one("#video-tracks", SelectionList)
            a = self.query_one("#audio-tracks", SelectionList)
            msg = self.query_one("#msg", Static)
        except Exception:
            return
        msg.update(f"视频 {len(v.selected)} 项 + 音频 {len(a.selected)} 项")

    def _confirm(self) -> None:
        v: SelectionList = self.query_one("#video-tracks", SelectionList)
        a: SelectionList = self.query_one("#audio-tracks", SelectionList)
        vsel = set(v.selected)
        asel = set(a.selected)
        if not vsel and not asel:
            self.query_one("#msg", Static).update("请至少选择一个轨道（视频或音频）")
            return
        self.dismiss({
            "want_main": "main" in vsel,
            "want_vga": "vga" in vsel,
            "want_bluetooth": "bluetooth" in asel,
            "want_main_audio": "main_audio" in asel,
            "want_vga_audio": "vga_audio" in asel,
        })

    def action_submit(self) -> None:
        self._confirm()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ok":
            self._confirm()

    def action_cancel(self) -> None:
        self.dismiss(None)


# ---------- 认证 / 通用 ----------

class AuthTokenScreen(ModalScreen[str]):
    """手动粘贴 token (ensure_auth 失败时)。"""

    BINDINGS = [Binding("escape", "cancel", "取消")]

    def compose(self) -> ComposeResult:
        yield Static("身份验证失败", id="title")
        yield Static("请粘贴 Bearer token (32 位 hex)", id="subtitle")
        with VerticalScroll(id="stage"):
            for line in utils.auth_prompt():
                yield Static(line, classes="footer-hint")
            yield Label("Token：")
            yield Input(placeholder="32 位 hex 字符串", id="token")
        yield Static("Enter 提交 · Esc 取消", id="status")

    def on_mount(self) -> None:
        self.query_one("#token", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        v = event.value.strip()
        if v:
            self.dismiss(v)

    def action_cancel(self) -> None:
        self.dismiss("")


class MessageScreen(ModalScreen[None]):
    """显示一行消息，回车或 Esc 返回。"""

    BINDINGS = [Binding("escape", "back", "返回"), Binding("enter", "back", "返回")]

    def __init__(self, message: str, back: bool = True) -> None:
        super().__init__()
        self._message = message
        self._back = back  # True=返回上一层 (pop_screen), False=退出 App

    def compose(self) -> ComposeResult:
        yield Static("提示", id="title")
        with Vertical(id="stage"):
            yield Static(self._message, id="info")
            with Horizontal(id="button-row"):
                yield Button("确定", id="ok", variant="primary")
        yield Static("Enter / Esc 返回", id="status")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.action_back()

    def action_back(self) -> None:
        self.dismiss(None)


# ---------- App 主类 ----------

class CourseApp(App):
    """三阶段 TUI 主应用。"""

    CSS_PATH = _CSS_PATH
    TITLE = "BIT 延河课堂下载器"

    def __init__(self) -> None:
        super().__init__()
        self.result: tuple | None = None

    def on_mount(self) -> None:
        # 提前读 auth.txt 设置 Bearer — 这样阶段1的"我的课程"按钮(走私有 API
        # /v2/course/private/list)能直接用现有 token 拿到 16 门课;
        # 搜索公开 API 无需 token, 也不影响。token 过期会在 _on_course_id ->
        # ensure_auth 走 SSO 重试; 若"我的课程"点了发现 token 失效, _fetch_and_pick
        # 的 try/except 会显示服务端错误。
        utils.read_auth()
        self.push_screen(ChooseCourseScreen(), self._on_course_id)

    def _on_course_id(self, courseID: str | None) -> None:
        if not courseID:
            self.exit()
            return
        if not utils.ensure_auth(courseID=courseID):
            self.push_screen(AuthTokenScreen(), lambda token: self._on_token(courseID, token))
            return
        self._after_auth(courseID)

    def _on_token(self, courseID: str, token: str | None) -> None:
        if not token:
            self.push_screen(MessageScreen("已取消认证", back=False))
            return
        utils.write_auth(token)
        if not utils.test_auth(courseID=courseID):
            self.push_screen(MessageScreen("身份验证失败，token 无效", back=False))
            return
        self._after_auth(courseID)

    def _after_auth(self, courseID: str) -> None:
        try:
            videoList, courseName, professor = utils.get_course_info(courseID=courseID)
        except Exception as e:
            self.push_screen(MessageScreen(f"获取课程信息失败: {e}", back=False))
            return
        if not videoList:
            self.push_screen(MessageScreen("该课程没有视频", back=False))
            return
        # 课程级 classrooms 用于按 location 编号反查教室名 (silently best-effort)
        classrooms: list = []
        try:
            import requests
            r = requests.get(
                f"https://cbiz.yanhekt.cn/v1/course?id={courseID}&with_professor_badges=true",
                headers=utils.headers,
            )
            if r.json().get("code") in (0, "0"):
                classrooms = r.json().get("data", {}).get("classrooms") or []
        except Exception:
            pass
        self.push_screen(
            MultiVideoScreen(videoList, courseName,
                             professor=professor, classrooms=classrooms),
            lambda sel: self._on_videos(videoList, courseName, professor, sel),
        )

    def _on_videos(self, videoList, courseName, professor, selected: list[int] | None) -> None:
        if not selected:
            self.exit()
            return
        self.push_screen(
            ChooseTracksScreen(courseName),
            lambda tracks: self._on_tracks(videoList, courseName, professor, selected, tracks),
        )

    def _on_tracks(self, videoList, courseName, professor, selected, tracks) -> None:
        if tracks is None:
            self.exit()
            return
        self.result = (videoList, courseName, professor, selected, tracks)
        self.exit()


# 向后兼容: tests/test_refactor.py 有 `import tui`。保留 config_tui 名称。
def config_tui(*args, **kwargs) -> Any:  # pragma: no cover - 兼容旧调用
    raise RuntimeError(
        "tui.config_tui 已废弃，请使用 CourseApp() / app.run() 模式。"
        "main.main_tui 是新入口。"
    )
