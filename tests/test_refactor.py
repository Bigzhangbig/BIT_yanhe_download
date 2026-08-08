"""重构回归测试 — 三阶段 TUI + 下载自由组合。

使用 stdlib unittest, 无额外依赖。
运行: uv run python -m unittest tests.test_refactor -v
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import patch

# 允许从项目根 import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import m3u8dl
import main  # noqa: E402
import utils  # noqa: E402


class MergeToMkvTest(unittest.TestCase):
    """验证 merge_to_mkv 音频 map 与 metadata 逻辑。"""

    def _run_merge(self, **kwargs):
        """运行 merge_to_mkv 并捕获 ffmpeg 命令。"""
        with patch("m3u8dl.run") as mock_run:
            defaults = {
                "main_mp4": "/tmp/main.mp4",
                "vga_mp4": "/tmp/vga.mp4",
                "audio_aac": None,
                "output_mkv": "/tmp/out.mkv",
                "vga_offset": 0.0,
                "include_main_audio": True,
                "include_vga_audio": True,
            }
            defaults.update(kwargs)
            m3u8dl.merge_to_mkv(**defaults)
            return mock_run.call_args[0][0]

    def test_all_audio_default(self):
        """无蓝牙 + 双内嵌 → map 0:a + 1:a, 顺序: 摄像头内嵌 / 屏幕内嵌"""
        cmd = self._run_merge()
        self.assertIn("0:v", cmd)
        self.assertIn("1:v", cmd)
        self.assertIn("0:a", cmd)
        self.assertIn("1:a", cmd)
        self.assertNotIn("2:a", cmd)
        main_idx = cmd.index("title=摄像头内嵌")
        vga_idx = cmd.index("title=屏幕内嵌")
        self.assertLess(main_idx, vga_idx)
        self.assertNotIn("title=蓝牙话筒", cmd)

    def test_with_bluetooth(self):
        """有蓝牙 + 双内嵌 → 蓝牙 track 0, 然后 main, vga"""
        cmd = self._run_merge(audio_aac="/tmp/bt.aac")
        self.assertIn("2:a", cmd)
        self.assertIn("0:a", cmd)
        self.assertIn("1:a", cmd)
        bt_idx = cmd.index("title=蓝牙话筒")
        main_idx = cmd.index("title=摄像头内嵌")
        vga_idx = cmd.index("title=屏幕内嵌")
        self.assertLess(bt_idx, main_idx)
        self.assertLess(main_idx, vga_idx)

    def test_no_main_audio(self):
        """include_main_audio=False → 不 map 0:a, metadata 跳过摄像头内嵌"""
        cmd = self._run_merge(audio_aac="/tmp/bt.aac", include_main_audio=False)
        self.assertIn("2:a", cmd)
        self.assertIn("1:a", cmd)
        self.assertNotIn("0:a", cmd)
        self.assertIn("title=蓝牙话筒", cmd)
        self.assertIn("title=屏幕内嵌", cmd)
        self.assertNotIn("title=摄像头内嵌", cmd)
        bt_idx = cmd.index("title=蓝牙话筒")
        vga_idx = cmd.index("title=屏幕内嵌")
        self.assertLess(bt_idx, vga_idx)

    def test_no_vga_audio(self):
        """include_vga_audio=False → 不 map 1:a"""
        cmd = self._run_merge(include_vga_audio=False)
        self.assertIn("0:a", cmd)
        self.assertNotIn("1:a", cmd)
        self.assertNotIn("2:a", cmd)
        self.assertNotIn("title=屏幕内嵌", cmd)
        self.assertIn("title=摄像头内嵌", cmd)

    def test_no_audio_at_all(self):
        """蓝牙无 + 内嵌全关 → 不 map 任何音频"""
        cmd = self._run_merge(include_main_audio=False, include_vga_audio=False)
        for a in ("0:a", "1:a", "2:a"):
            self.assertNotIn(a, cmd)
        for t in ("title=摄像头内嵌", "title=屏幕内嵌", "title=蓝牙话筒"):
            self.assertNotIn(t, cmd)

    def test_vga_offset(self):
        """vga_offset=-0.5 → 加 -itsoffset"""
        cmd = self._run_merge(vga_offset=-0.5)
        self.assertIn("-itsoffset", cmd)
        self.assertIn("-0.5", cmd)

    def test_vga_offset_zero(self):
        """vga_offset=0 → 不加 -itsoffset"""
        cmd = self._run_merge(vga_offset=0.0)
        self.assertNotIn("-itsoffset", cmd)

    def test_cleanup_skips_none(self):
        """main/vga 路径为 None 时 cleanup 不应崩 (实际合并通常不会 None, 但容错)"""
        with patch("m3u8dl.run"), patch("m3u8dl.os.path.exists", return_value=False), \
             patch("m3u8dl.os.remove") as rm:
            m3u8dl.merge_to_mkv(
                "/tmp/main.mp4", None, None, "/tmp/out.mkv",
                keep_intermediate=False,
            )
            for call in rm.call_args_list:
                self.assertNotIn(None, call.args)


class DownloadOneTest(unittest.TestCase):
    """验证 _download_one 自由组合逻辑。"""

    def setUp(self):
        self._video = {
            "title": "T1",
            "videos": [{"main": "u_main", "vga": "u_vga"}],
            "video_ids": ["vid1"],
        }
        main._VIDEO_LIST = [self._video]
        main._COURSE_NAME = "课程"
        main._PROFESSOR = "教师"
        main._SELECTED_VIDEOS = [0]
        self._name = "课程-教师-T1"

    def _ctx(self):
        """返回公共 patch 上下文集合 (caller 负责 with 进入)。"""
        from contextlib import ExitStack
        s = ExitStack()
        s.enter_context(patch("main.m3u8dl.M3u8Download"))
        s.enter_context(patch("main.m3u8dl.merge_to_mkv"))
        s.enter_context(patch("main.m3u8dl.extract_audio"))
        s.enter_context(patch("main.m3u8dl.os.remove"))
        s.enter_context(patch("main.utils.get_audio_url", return_value="audio_url"))
        s.enter_context(patch("main.utils.download_audio"))
        return s

    def test_both_videos_merge(self):
        main._TRACKS = {
            "want_main": True, "want_vga": True,
            "want_bluetooth": True, "want_main_audio": True, "want_vga_audio": True,
        }
        with self._ctx():
            dl = main.m3u8dl.M3u8Download
            merge = main.m3u8dl.merge_to_mkv
            da = main.utils.download_audio
            main._download_one(self._video, self._name)
        self.assertEqual(dl.call_count, 2)
        merge.assert_called_once()
        self.assertIn("merged", merge.call_args[0][3])
        da.assert_called_once()
        # merge_to_mkv 应传 include_main_audio=True
        _, kwargs = merge.call_args
        self.assertTrue(kwargs.get("include_main_audio"))

    def test_main_only_no_merge(self):
        main._TRACKS = {
            "want_main": True, "want_vga": False,
            "want_bluetooth": False, "want_main_audio": False, "want_vga_audio": False,
        }
        with self._ctx():
            dl = main.m3u8dl.M3u8Download
            merge = main.m3u8dl.merge_to_mkv
            main._download_one(self._video, self._name)
        self.assertEqual(dl.call_count, 1)
        merge.assert_not_called()
        self.assertIn("-video", dl.call_args[0][1])
        self.assertEqual(dl.call_args[0][2], self._name)

    def test_vga_only_no_merge(self):
        main._TRACKS = {
            "want_main": False, "want_vga": True,
            "want_bluetooth": False, "want_main_audio": False, "want_vga_audio": False,
        }
        with self._ctx():
            dl = main.m3u8dl.M3u8Download
            merge = main.m3u8dl.merge_to_mkv
            main._download_one(self._video, self._name)
        self.assertEqual(dl.call_count, 1)
        merge.assert_not_called()
        self.assertIn("-screen", dl.call_args[0][1])

    def test_merge_no_bluetooth(self):
        main._TRACKS = {
            "want_main": True, "want_vga": True,
            "want_bluetooth": False, "want_main_audio": True, "want_vga_audio": True,
        }
        with self._ctx():
            da = main.utils.download_audio
            ga = main.utils.get_audio_url
            merge = main.m3u8dl.merge_to_mkv
            main._download_one(self._video, self._name)
        da.assert_not_called()
        ga.assert_not_called()
        self.assertIsNone(merge.call_args[0][2])

    def test_bluetooth_with_single_video(self):
        """单视频 + 选蓝牙 → download_audio 走单视频分支 (用 name 不用 name+'-main')"""
        main._TRACKS = {
            "want_main": True, "want_vga": False,
            "want_bluetooth": True, "want_main_audio": False, "want_vga_audio": False,
        }
        with self._ctx():
            da = main.utils.download_audio
            merge = main.m3u8dl.merge_to_mkv
            main._download_one(self._video, self._name)
        da.assert_called_once()
        merge.assert_not_called()
        # name 传入, 不带 -main 后缀
        self.assertEqual(da.call_args[0][2], self._name)

    def test_merge_passes_audio_flags(self):
        main._TRACKS = {
            "want_main": True, "want_vga": True,
            "want_bluetooth": True, "want_main_audio": False, "want_vga_audio": True,
        }
        with self._ctx():
            merge = main.m3u8dl.merge_to_mkv
            main._download_one(self._video, self._name)
        self.assertFalse(merge.call_args.kwargs["include_main_audio"])
        self.assertTrue(merge.call_args.kwargs["include_vga_audio"])
        self.assertEqual(merge.call_args.kwargs["vga_offset"], -0.5)

    def test_merge_bluetooth_filename(self):
        """合并模式 + 蓝牙 → download_audio 用 name+'-main' (与历史命名兼容)"""
        main._TRACKS = {
            "want_main": True, "want_vga": True,
            "want_bluetooth": True, "want_main_audio": True, "want_vga_audio": True,
        }
        with self._ctx():
            da = main.utils.download_audio
            main._download_one(self._video, self._name)
        # 第二位置参数 (name) 应该是 self._name + "-main"
        self.assertEqual(da.call_args[0][2], self._name + "-main")

    def test_audio_only_bluetooth(self):
        """0 视频 + 仅蓝牙 → 1 个 .aac, 走 utils.download_audio"""
        main._TRACKS = {
            "want_main": False, "want_vga": False,
            "want_bluetooth": True, "want_main_audio": False, "want_vga_audio": False,
        }
        with self._ctx():
            dl = main.m3u8dl.M3u8Download
            da = main.utils.download_audio
            exa = main.m3u8dl.extract_audio
            main._download_one(self._video, self._name)
        dl.assert_not_called()
        exa.assert_not_called()
        da.assert_called_once()
        # 下载路径应是 audio 子目录, name 带 -bluetooth 后缀
        self.assertIn("-audio", da.call_args[0][1])
        self.assertEqual(da.call_args[0][2], self._name + "-bluetooth")

    def test_audio_only_bluetooth_plus_main_audio(self):
        """0 视频 + 蓝牙 + 摄像头内嵌 → 2 个文件 (1 直接 aac + 1 提取)"""
        main._TRACKS = {
            "want_main": False, "want_vga": False,
            "want_bluetooth": True, "want_main_audio": True, "want_vga_audio": False,
        }
        with self._ctx():
            dl = main.m3u8dl.M3u8Download
            da = main.utils.download_audio
            exa = main.m3u8dl.extract_audio
            main._download_one(self._video, self._name)
        # 只下 main 流一次 (为了提取音频), 不下 vga
        self.assertEqual(dl.call_count, 1)
        # 蓝牙 + extract 各一次
        da.assert_called_once()
        exa.assert_called_once()
        # 提取的源文件是 main.mp4, 目标是 main-audio.aac
        self.assertTrue(exa.call_args[0][0].endswith("-main.mp4"))
        self.assertTrue(exa.call_args[0][1].endswith("-main-audio.aac"))

    def test_audio_only_three_streams(self):
        """0 视频 + 蓝牙 + 摄像头内嵌 + 屏幕内嵌 → 3 个文件"""
        main._TRACKS = {
            "want_main": False, "want_vga": False,
            "want_bluetooth": True, "want_main_audio": True, "want_vga_audio": True,
        }
        with self._ctx():
            dl = main.m3u8dl.M3u8Download
            da = main.utils.download_audio
            exa = main.m3u8dl.extract_audio
            main._download_one(self._video, self._name)
        # 下 main 和 vga 各一次, 共 2 次
        self.assertEqual(dl.call_count, 2)
        # 蓝牙 aac + 两次 extract = 3 个输出文件
        self.assertEqual(da.call_count + exa.call_count, 3)

    def test_audio_only_uses_audio_dir(self):
        """0 视频分支使用 output/<课程名>-audio/ 目录"""
        main._TRACKS = {
            "want_main": False, "want_vga": False,
            "want_bluetooth": True, "want_main_audio": False, "want_vga_audio": False,
        }
        with self._ctx():
            da = main.utils.download_audio
            main._download_one(self._video, self._name)
        self.assertIn("课程-audio", da.call_args[0][1])


class ExtractAudioTest(unittest.TestCase):
    """验证 extract_audio 命令构造 (-vn -acodec copy, 不重编码)。"""

    def test_command(self):
        with patch("m3u8dl.run") as mock_run:
            m3u8dl.extract_audio("/tmp/in.mp4", "/tmp/out.aac")
        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd[0], m3u8dl.utils.get_ffmpeg_command())
        self.assertIn("-i", cmd)
        self.assertIn("/tmp/in.mp4", cmd)
        self.assertIn("-vn", cmd)
        self.assertIn("-acodec", cmd)
        self.assertIn("copy", cmd)
        self.assertIn("/tmp/out.aac", cmd)
        # 不应重编码视频
        self.assertNotIn("-vcodec", cmd)
        # check=True
        self.assertTrue(mock_run.call_args.kwargs.get("check"))


class SearchCoursesSemestersTest(unittest.TestCase):
    """验证 utils.search_courses 对 semesters 参数的展开行为。"""

    def test_no_semesters_uses_dict_params(self):
        with patch("utils.requests.get") as g:
            g.return_value.json.return_value = {"code": 0, "data": {"data": [], "total": 0}}
            utils.search_courses(keyword="测试", page=1, page_size=16)
            params = g.call_args.kwargs["params"]
            self.assertIn("keyword", params)
            self.assertEqual(params["keyword"], "测试")
            self.assertNotIn("semesters[]", params)

    def test_with_semesters_uses_list_params(self):
        with patch("utils.requests.get") as g:
            g.return_value.json.return_value = {"code": 0, "data": {"data": [], "total": 0}}
            utils.search_courses(keyword="测试", page=1, page_size=16, semesters=["100", "96"])
            params_list = g.call_args.kwargs["params"]
            self.assertIsInstance(params_list, list)
            keys = [p[0] for p in params_list]
            self.assertEqual(keys.count("semesters[]"), 2)
            self.assertIn(("semesters[]", "100"), params_list)
            self.assertIn(("semesters[]", "96"), params_list)


class ImportSmokeTest(unittest.TestCase):
    """主流程模块可正常 import。"""

    def test_imports(self):
        import tui  # noqa: F401
        self.assertTrue(callable(main.main))


class ChooseTracksScreenTest(unittest.IsolatedAsyncioTestCase):
    """验证 ChooseTracksScreen 允许 0 视频 + 至少 1 个轨道才提交。"""

    async def _run_screen(self, unselect_videos=(), unselect_audios=()):
        """启动一个最小 App + push ChooseTracksScreen, 取消指定项, 模拟点 OK, 返回 (dismissed, msg_before_dismiss)。"""
        from textual.app import App
        from textual.widgets import Button, Static
        from tui import ChooseTracksScreen

        captured = {"msg": None, "value": None}

        class _MiniApp(App):
            async def on_mount(self):
                screen = ChooseTracksScreen("测试课")
                self._screen = screen
                orig_dismiss = screen.dismiss
                def cap_dismiss(value):
                    captured["value"] = value
                    orig_dismiss(value)
                # snapshot msg 在 on_button_pressed 调完原方法后 (dismiss 之前 msg 已 update)
                orig_on_btn = ChooseTracksScreen.on_button_pressed
                def wrapped_on_btn(self_, event):
                    orig_on_btn(self_, event)
                    if captured["msg"] is None:
                        try:
                            w = self_.query_one("#msg", Static)
                            captured["msg"] = getattr(w, "_Static__content", "")
                        except Exception:
                            pass
                import types
                screen.on_button_pressed = types.MethodType(wrapped_on_btn, screen)
                screen.dismiss = cap_dismiss
                await self.push_screen(screen)

        app = _MiniApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app._screen
            v = screen.query_one("#video-tracks")
            a = screen.query_one("#audio-tracks")
            for opt_id in unselect_videos:
                v.deselect(opt_id)
            for opt_id in unselect_audios:
                a.deselect(opt_id)
            screen.on_button_pressed(
                Button.Pressed(screen.query_one("#ok"))
            )
            await pilot.pause()

        return captured.get("value"), captured.get("msg") or ""

    def test_default_submit_all_tracks(self):
        """默认全选 → dismiss tracks_dict 含全部 5 个 True"""
        v, _ = asyncio.run(self._run_screen())
        self.assertIsInstance(v, dict)
        self.assertTrue(all(v.values()))

    def test_unselect_videos_only_audio(self):
        """取消所有视频 → 仅音频, 仍可提交"""
        v, _ = asyncio.run(self._run_screen(unselect_videos=("main", "vga")))
        self.assertFalse(v["want_main"])
        self.assertFalse(v["want_vga"])
        self.assertTrue(v["want_bluetooth"])
        self.assertTrue(v["want_main_audio"])
        self.assertTrue(v["want_vga_audio"])

    def test_unselect_audios_only_video(self):
        """取消所有音频 → 仅视频, 仍可提交"""
        v, _ = asyncio.run(self._run_screen(unselect_audios=("bluetooth", "main_audio", "vga_audio")))
        self.assertTrue(v["want_main"])
        self.assertTrue(v["want_vga"])
        self.assertFalse(v["want_bluetooth"])
        self.assertFalse(v["want_main_audio"])
        self.assertFalse(v["want_vga_audio"])

    def test_unselect_all_blocked(self):
        """全空 → 提示'请至少选择一个轨道', 不 dismiss"""
        v, msg = asyncio.run(self._run_screen(
            unselect_videos=("main", "vga"),
            unselect_audios=("bluetooth", "main_audio", "vga_audio"),
        ))
        self.assertIsNone(v)
        self.assertIn("至少选择一个", str(msg))


if __name__ == "__main__":
    unittest.main()
