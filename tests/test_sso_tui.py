"""Curses login behavior without a terminal, credentials or network."""

import os
import unittest
from collections import deque
from contextlib import ExitStack
from unittest.mock import Mock, patch

import gui
import sso_login


TOKEN = "0123456789abcdef0123456789abcdef"  # gitleaks:allow -- synthetic token
PASSWORD = "tui-test-password"  # gitleaks:allow -- synthetic test credential
SMS_CODE = "123456"


class Window:
    def __init__(self, owner, entries=(), keys=()):
        self.owner = owner
        self.entries = deque(entries)
        self.keys = deque(keys)
        self.read_echo = []
        self.display = []
        self.refreshes = 0

    def getmaxyx(self):
        return 30, 120

    def clear(self):
        pass

    def refresh(self):
        self.refreshes += 1

    def addnstr(self, row, column, text, width):
        self.display.append(text)

    def getstr(self, *args):
        self.read_echo.append(self.owner.echoing)
        value = self.entries.popleft()
        if isinstance(value, BaseException):
            raise value
        return value.encode("utf-8")

    def getch(self):
        return self.keys.popleft()


class SsoTuiTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.echoing = False
        self.stack.enter_context(patch.dict(os.environ, {}, clear=True))
        self.stack.enter_context(patch("curses.echo", side_effect=self.echo))
        self.stack.enter_context(patch("curses.noecho", side_effect=self.noecho))
        self.stack.enter_context(patch("curses.start_color"))
        self.stack.enter_context(patch("curses.init_pair"))
        self.stack.enter_context(patch("builtins.input", side_effect=AssertionError("terminal input")))
        self.stack.enter_context(patch("getpass.getpass", side_effect=AssertionError("terminal getpass")))
        self.stack.enter_context(patch("builtins.print", side_effect=AssertionError("terminal print")))
        self.stack.enter_context(patch("socket.socket.connect", side_effect=AssertionError("network")))
        self.stack.enter_context(patch.object(gui.utils, "read_auth",
                                             side_effect=AssertionError("legacy token prompt")))
        self.stack.enter_context(patch.object(gui.utils, "write_auth",
                                             side_effect=AssertionError("TUI must delegate token storage")))
        self.stack.enter_context(patch("requests.Session.request",
                                      side_effect=AssertionError("network")))
        self.login = self.stack.enter_context(patch("sso_login.login", return_value=TOKEN))
        for name in ("videoList", "courseName", "professor", "selected_videos",
                     "selected_signal", "download_audio", "align"):
            self.stack.enter_context(patch.object(gui, name, getattr(gui, name)))

    def echo(self):
        self.echoing = True

    def noecho(self):
        self.echoing = False

    def assert_hidden(self, window):
        shown = "\n".join(window.display)
        for secret in (PASSWORD, SMS_CODE, TOKEN):
            self.assertNotIn(secret, shown)
        self.assertFalse(self.echoing)

    def test_credentials_and_sms_are_read_inside_one_login_with_correct_echo(self):
        window = Window(self, ["student", PASSWORD, SMS_CODE])

        def login(username, password, *, sms_code=None, code_provider=None, timeout=15):
            self.assertEqual((username, password), ("student", PASSWORD))
            self.assertIsNone(sms_code)
            self.assertIn("正在登录", "".join(window.display).replace(" ", ""))
            self.assertGreater(window.refreshes, 0)
            self.assertFalse(self.echoing)
            self.assertEqual(code_provider(), SMS_CODE)
            self.assertFalse(self.echoing)
            return TOKEN

        self.login.side_effect = login
        self.assertEqual(gui.login_tui(window), TOKEN)
        self.login.assert_called_once()
        self.assertEqual(window.read_echo, [True, False, False])
        self.assertFalse(window.entries)
        self.assert_hidden(window)

    def test_environment_credentials_and_sms_do_not_prompt(self):
        os.environ.update(STUDENT_ID="student", PASSWORD=PASSWORD, SMS_CODE=SMS_CODE)
        window = Window(self)

        def login(username, password, *, sms_code=None, code_provider=None, timeout=15):
            self.assertEqual((username, password, sms_code), ("student", PASSWORD, SMS_CODE))
            return TOKEN

        self.login.side_effect = login
        self.assertEqual(gui.login_tui(window), TOKEN)
        self.assertEqual(window.read_echo, [])
        self.assert_hidden(window)

    def test_only_missing_password_is_prompted_and_whitespace_is_preserved(self):
        os.environ["STUDENT_ID"] = "student"
        window = Window(self, [" " + PASSWORD + " "])
        self.assertEqual(gui.login_tui(window), TOKEN)
        self.assertEqual(self.login.call_args.args, ("student", " " + PASSWORD + " "))
        self.assertEqual(window.read_echo, [False])
        self.assert_hidden(window)

    def test_only_missing_username_is_echoed(self):
        os.environ["PASSWORD"] = PASSWORD
        window = Window(self, ["student"])
        self.assertEqual(gui.login_tui(window), TOKEN)
        self.assertEqual(self.login.call_args.args, ("student", PASSWORD))
        self.assertEqual(window.read_echo, [True])
        self.assert_hidden(window)

    def test_empty_or_interrupted_credentials_cancel_and_restore_noecho(self):
        for entries in ([""], [KeyboardInterrupt()], [EOFError()], ["\x03"],
                        ["student", ""], ["student", KeyboardInterrupt()]):
            with self.subTest(entries_kind=[type(value).__name__ for value in entries]):
                self.login.reset_mock()
                window = Window(self, entries)
                with self.assertRaises((sso_login.LoginError, KeyboardInterrupt, EOFError)):
                    gui.login_tui(window)
                self.login.assert_not_called()
                self.assert_hidden(window)

    def test_empty_or_interrupted_sms_cancels_without_second_login(self):
        os.environ.update(STUDENT_ID="student", PASSWORD=PASSWORD)
        for answer in ("", KeyboardInterrupt(), EOFError(), "\x03"):
            with self.subTest(answer_kind=type(answer).__name__):
                self.login.reset_mock()
                window = Window(self, [answer])

                def login(username, password, *, sms_code=None, code_provider=None, timeout=15):
                    code_provider()
                    self.fail("Canceled SMS must not complete login")

                self.login.side_effect = login
                with self.assertRaises((sso_login.LoginError, KeyboardInterrupt, EOFError)):
                    gui.login_tui(window)
                self.login.assert_called_once()
                self.assertEqual(window.read_echo, [False])
                self.assert_hidden(window)

    def course_fixture(self):
        return self.stack.enter_context(patch.object(gui.utils, "get_course_info", return_value=(
            [{"title": "lesson"}], "course", "teacher",
        )))

    def test_config_reuses_valid_auth_without_prompting_and_keeps_menu_choices(self):
        window = Window(self, ["12345"], [ord(" "), 10, ord(" "), 10, 10])
        info = self.course_fixture()
        ensure = self.stack.enter_context(patch.object(gui.utils, "ensure_auth", create=True,
                                                       return_value=True))
        gui.config(window)
        ensure.assert_called_once()
        self.assertEqual(len(ensure.call_args.args), 1)
        self.assertTrue(callable(ensure.call_args.args[0]))
        self.login.assert_not_called()
        info.assert_called_once_with(courseID="12345")
        self.assertEqual(gui.selected_videos, [0])
        self.assertEqual(gui.selected_signal, [0])
        self.assertEqual(gui.download_audio, [0])
        self.assertEqual(window.read_echo, [True])
        self.assert_hidden(window)

    def test_config_passes_credential_prompt_to_ensure_auth_after_course_id(self):
        window = Window(self, ["12345", "student", PASSWORD],
                        [ord(" "), 10, ord(" "), 10, 10])
        info = self.course_fixture()

        def ensure(login_prompt):
            self.assertEqual(window.read_echo, [True])
            self.assertEqual(login_prompt(), TOKEN)
            return True

        self.stack.enter_context(patch.object(gui.utils, "ensure_auth", create=True,
                                              side_effect=ensure))
        gui.config(window)
        info.assert_called_once_with(courseID="12345")
        self.assertEqual(window.read_echo, [True, True, False])
        self.assert_hidden(window)

    def test_login_failure_exits_before_course_selection_or_download(self):
        window = Window(self, ["12345"], [10])
        info = self.course_fixture()
        self.stack.enter_context(patch.object(gui.utils, "ensure_auth", create=True,
                                              side_effect=sso_login.LoginError("登录失败")))
        download = self.stack.enter_context(patch.object(gui.m3u8dl, "M3u8Download"))
        wrapper = self.stack.enter_context(patch("curses.wrapper", side_effect=lambda fn: fn(window)))
        with self.assertRaises(SystemExit):
            gui.main()
        wrapper.assert_called_once_with(gui.config)
        info.assert_not_called()
        download.assert_not_called()
        self.assertTrue(window.display)
        self.assert_hidden(window)

    def test_cancel_in_config_shows_safe_message_and_does_not_select_course(self):
        for entries in (["12345", ""], ["12345", KeyboardInterrupt()],
                        ["12345", "student", KeyboardInterrupt()]):
            with self.subTest(stage=len(entries)):
                window = Window(self, entries, [10])
                with patch.object(gui.utils, "ensure_auth", create=True,
                                  side_effect=lambda login_prompt: bool(login_prompt())), \
                        patch.object(gui.utils, "get_course_info") as info:
                    with self.assertRaises(SystemExit):
                        gui.config(window)
                info.assert_not_called()
                self.assert_hidden(window)


if __name__ == "__main__":
    unittest.main()
