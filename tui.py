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


# ---------- 阶段1: 选课 ----------

class ChooseCourseScreen(ModalScreen[str]):
    """阶段1: 选课方式 → 返回 5 位 courseID (空串表示取消)。"""

    BINDINGS = [
        Binding("escape", "cancel", "取消"),
    ]

    def compose(self) -> ComposeResult:
        yield Static("BIT 延河课堂 — 选择获取课程的方式", id="title")
        yield Static("↑↓ 移动 · Enter 确认 · Esc 取消", id="subtitle")
        with Vertical(id="stage"):
            with Horizontal(id="button-row"):
                yield Button("输入课程号", id="by-id", variant="primary")
                yield Button("搜索课程", id="by-search")
                yield Button("我的课程", id="by-mine")
        yield Static("Textual TUI · BIT 延河课堂", id="status")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "by-id":
            self.app.push_screen(InputCourseIdScreen(), self._on_result)
        elif event.button.id == "by-search":
            self.app.push_screen(SearchCourseScreen(), self._on_result)
        elif event.button.id == "by-mine":
            self._fetch_and_pick("我的课程", lambda: utils.get_my_courses(page=1, page_size=16))

    def _fetch_and_pick(self, label: str, fetch):
        try:
            result = fetch()
        except Exception as e:
            self.app.push_screen(MessageScreen(f"获取课程失败: {e}", back=True))
            return
        courses = result.get("data", [])
        if not courses:
            self.app.push_screen(MessageScreen("未找到任何课程", back=True))
            return
        labels = [
            (f"{c['id']} - {c.get('name_zh') or c.get('name') or '?'}", str(c["id"]))
            for c in courses
        ]
        self.app.push_screen(
            PickOneScreen(f"{label} — 请选择课程", labels, f"共 {result.get('total', len(courses))} 门"),
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
    """搜索课程 — 关键词 + 学期筛选。"""

    BINDINGS = [Binding("escape", "cancel", "返回")]

    def compose(self) -> ComposeResult:
        yield Static("搜索课程", id="title")
        yield Static("关键词 (可空) + 学期 (可空=不过滤)", id="subtitle")
        with Vertical(id="stage"):
            yield Label("搜索关键词：")
            yield Input(placeholder="例如 数据结构 (回车到下一步)", id="keyword")
            yield Label("学期 (空格多选, 全不选=不筛选)：")
            yield SelectionList(id="semesters")
        yield Static("Enter 搜索 · Esc 返回", id="status")

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

    def on_input_submitted(self, event: Input.Submitted) -> None:
        keyword = event.value.strip()
        sl: SelectionList = self.query_one("#semesters", SelectionList)
        semester_ids = list(sl.selected) if sl.selected else None
        try:
            result = utils.search_courses(
                keyword=keyword, page=1, page_size=16, semesters=semester_ids
            )
        except Exception as e:
            self.app.push_screen(MessageScreen(f"搜索课程失败: {e}", back=True))
            return
        courses = result.get("data", [])
        if not courses:
            self.app.push_screen(MessageScreen("未找到任何课程", back=True))
            return
        labels = [
            (f"{c['id']} - {c.get('name_zh') or c.get('name') or '?'}", str(c["id"]))
            for c in courses
        ]
        self.app.push_screen(
            PickOneScreen("搜索结果 — 请选择课程", labels, f"共 {result.get('total', len(courses))} 门"),
            self._on_pick,
        )

    def _on_pick(self, courseID: str | None) -> None:
        if courseID:
            self.dismiss(courseID)

    def action_cancel(self) -> None:
        self.dismiss("")


class PickOneScreen(ModalScreen[str]):
    """单选课程列表。"""

    BINDINGS = [Binding("escape", "cancel", "返回")]

    def __init__(self, title: str, items: list[tuple[str, str]], subtitle: str = "") -> None:
        super().__init__()
        self._title = title
        self._items = items
        self._subtitle = subtitle

    def compose(self) -> ComposeResult:
        yield Static(self._title, id="title")
        yield Static(self._subtitle, id="subtitle")
        with Vertical(id="stage"):
            ol = OptionList(id="pick")
            for label, _ in self._items:
                ol.add_option(Option(label, id=label))
            yield ol
        yield Static("Enter 确认 · Esc 返回", id="status")

    def on_mount(self) -> None:
        self.query_one("#pick", OptionList).focus()

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

class ChooseVideosScreen(ModalScreen[list[int] | None]):
    """阶段2: 选节数。返回 [index, ...]，None 表示取消。"""

    BINDINGS = [Binding("escape", "cancel", "取消")]

    def __init__(self, videoList: list, courseName: str) -> None:
        super().__init__()
        self._videoList = videoList
        self._courseName = courseName

    def compose(self) -> ComposeResult:
        yield Static(f"课程：{self._courseName} ({len(self._videoList)} 节)", id="title")
        yield Static("选择节数范围", id="subtitle")
        with Vertical(id="stage"):
            with Horizontal(id="button-row"):
                yield Button("单节", id="single", variant="primary")
                yield Button("多节", id="multi")
                yield Button("全选", id="all")
        yield Static("Esc 取消", id="status")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "single":
            self.app.push_screen(
                SingleVideoScreen(self._videoList, self._courseName), self._on_pick
            )
        elif event.button.id == "multi":
            self.app.push_screen(
                MultiVideoScreen(self._videoList, self._courseName), self._on_pick
            )
        elif event.button.id == "all":
            self.dismiss(list(range(len(self._videoList))))

    def _on_pick(self, result: list[int] | None) -> None:
        if result is not None:
            self.dismiss(result)

    def action_cancel(self) -> None:
        self.dismiss(None)


class SingleVideoScreen(ModalScreen[list[int]]):
    """单选一节视频。"""

    BINDINGS = [Binding("escape", "cancel", "返回")]

    def __init__(self, videoList: list, courseName: str) -> None:
        super().__init__()
        self._videoList = videoList
        self._courseName = courseName

    def compose(self) -> ComposeResult:
        yield Static(f"课程：{self._courseName}", id="title")
        yield Static("请选择单节视频", id="subtitle")
        with Vertical(id="stage"):
            ol = OptionList(id="videos")
            for v in self._videoList:
                ol.add_option(Option(v["title"], id=str(v.get("id", v["title"]))))
            yield ol
        yield Static("Enter 确认 · Esc 返回", id="status")

    def on_mount(self) -> None:
        self.query_one("#videos", OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id is None:
            return
        for i, v in enumerate(self._videoList):
            if str(v.get("id", v["title"])) == event.option.id:
                self.dismiss([i])
                return

    def action_cancel(self) -> None:
        self.dismiss([])


class MultiVideoScreen(ModalScreen[list[int]]):
    """多选视频 (≥1)。"""

    BINDINGS = [
        Binding("escape", "cancel", "返回"),
        Binding("ctrl+a", "select_all", "全选"),
    ]

    def __init__(self, videoList: list, courseName: str) -> None:
        super().__init__()
        self._videoList = videoList
        self._courseName = courseName

    def compose(self) -> ComposeResult:
        yield Static(f"课程：{self._courseName}", id="title")
        yield Static("多选视频 (≥1, 空格切换)", id="subtitle")
        with Vertical(id="stage"):
            sl = SelectionList(id="videos")
            for v in self._videoList:
                sl.add_option(Selection(v["title"], v.get("id", v["title"])))
            yield sl
            yield Static("", id="msg")
            with Horizontal(id="button-row"):
                yield Button("确认", id="ok", variant="primary")
                yield Button("全选", id="all")
        yield Static("空格切换 · Ctrl+A 全选 · Enter 确认", id="status")

    def on_mount(self) -> None:
        self.query_one("#videos", SelectionList).focus()

    def action_select_all(self) -> None:
        sl: SelectionList = self.query_one("#videos", SelectionList)
        sl.select_all()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "all":
            self.action_select_all()
            return
        if event.button.id == "ok":
            sl: SelectionList = self.query_one("#videos", SelectionList)
            sel = list(sl.selected)
            if not sel:
                self.query_one("#msg", Static).update("请至少选择一个")
                return
            ids = [v.get("id", v["title"]) for v in self._videoList]
            indices = [i for i, vid in enumerate(ids) if vid in sel]
            self.dismiss(indices)

    def action_cancel(self) -> None:
        self.dismiss([])


# ---------- 阶段3: 选轨 ----------

class ChooseTracksScreen(ModalScreen[dict | None]):
    """阶段3: 选视频轨 + 音频轨。返回 tracks dict 或 None (取消)。"""

    BINDINGS = [Binding("escape", "cancel", "取消")]

    def __init__(self, courseName: str) -> None:
        super().__init__()
        self._courseName = courseName

    def compose(self) -> ComposeResult:
        yield Static(f"课程：{self._courseName}", id="title")
        yield Static("选择视频轨 (≥1) + 音频轨 (可空)", id="subtitle")
        with Vertical(id="stage"):
            yield Label("视频轨 (≥1)：")
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
            yield Static("", id="msg")
            with Horizontal(id="button-row"):
                yield Button("开始下载", id="ok", variant="primary")
        yield Static("Enter 确认 · Esc 取消", id="status")

    def on_mount(self) -> None:
        self.query_one("#video-tracks", SelectionList).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ok":
            v: SelectionList = self.query_one("#video-tracks", SelectionList)
            a: SelectionList = self.query_one("#audio-tracks", SelectionList)
            vsel = set(v.selected)
            asel = set(a.selected)
            if not vsel:
                self.query_one("#msg", Static).update("请至少选择一个视频轨")
                return
            self.dismiss({
                "want_main": "main" in vsel,
                "want_vga": "vga" in vsel,
                "want_bluetooth": "bluetooth" in asel,
                "want_main_audio": "main_audio" in asel,
                "want_vga_audio": "vga_audio" in asel,
            })

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
        self.push_screen(
            ChooseVideosScreen(videoList, courseName),
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
