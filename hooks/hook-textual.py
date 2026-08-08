"""PyInstaller hook for Textual.

打包时兜底: 显式收集 textual / rich 子模块 + textual 自带 .tcss 数据文件,
并把项目自带的 tui.tcss 一并打包。

PyInstaller 调用时, 在 hooks 目录里扫描所有 hook-*.py, 需 --additional-hooks-dir
指向本目录才会加载。本仓库的 webui_interface.spec 默认没指定, 见 README 打包章节。
"""
import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = []
hiddenimports = []

# 1) textual 自带的 .tcss (各 Widget 的 DEFAULT_CSS 在源码里, 不需要单独打包)
#    但 textual 包内有部分 .tcss 资源, 走 collect_data_files 兜底
datas += collect_data_files("textual")
datas += collect_data_files("textual.widgets")

# 2) 显式枚举子模块, 防止 PyInstaller 静态分析漏掉动态加载
hiddenimports += collect_submodules("textual")
hiddenimports += collect_submodules("textual.widgets")
hiddenimports += collect_submodules("rich")
hiddenimports += collect_submodules("rich.jupyter")  # textual 内部偶尔用

# 3) 项目自带的 tui.tcss — 放项目根目录, 相对 hooks 目录的 ../tui.tcss
_here = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_here)
_tcss = os.path.join(_project_root, "tui.tcss")
if os.path.isfile(_tcss):
    datas.append((_tcss, "."))
