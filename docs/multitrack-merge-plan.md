# 多路/音画合并线路图

## 目标

下载两路视频 + 蓝牙音频，合并成单个 mkv 文件（双轨 video + 多轨 audio），`-c copy` 不重编码，播放器手动切换 track。

## 决策（已确认）

- **合并布局**：双轨 mkv（不重编码）
- **音频策略**：多音轨（蓝牙 + main 内嵌 + vga 内嵌都保留）

## 当前状态

- `main.py:46-63`：用户单选 main 或 vga，`m3u8dl.M3u8Download` 下载一路 -> .mp4
- `utils.download_audio`：可选下载蓝牙 -> .aac
- 视频 .mp4 + 音频 .aac 独立存放，无合并

## 合并命令（核心）

```bash
ffmpeg -i main.mp4 -i vga.mp4 -i bluetooth.aac \
  -map 0:v -map 0:a -map 1:v -map 1:a -map 2:a \
  -c copy \
  -metadata:s:v:0 title="摄像头" \
  -metadata:s:v:1 title="屏幕" \
  -metadata:s:a:0 title="蓝牙话筒" \
  -metadata:s:a:1 title="摄像头内嵌" \
  -metadata:s:a:2 title="屏幕内嵌" \
  output.mkv
```

- `-c copy`：不重编码，速度最快（合并一节课 < 10s）
- `-map 0:v -map 0:a`：main 的视频+内嵌音频
- `-map 1:v -map 1:a`：vga 的视频+内嵌音频
- `-map 2:a`：蓝牙音频
- `metadata`：track 名称，播放器显示

## 音画同步（signal-prober 实测）

| 组合 | 时延 | 处理 |
|---|---|---|
| main video + main 内嵌 audio | 0（天然同步） | 无需处理 |
| vga video + vga 内嵌 audio | 0（天然同步） | 无需处理 |
| 蓝牙 audio + main video | +20ms | 可忽略 |
| 蓝牙 audio + vga video | -0.46s | 已知偏移，YAGNI 先不校准 |

用户播放器切换：看摄像头用蓝牙音轨（近同步），看屏幕用 vga 内嵌音轨（天然同步）。

## 实施步骤

### 阶段 1：新增 merge_to_mkv 函数

**位置**：`m3u8dl.py`（下载器同文件，或新建 `merge.py`）

```python
def merge_to_mkv(main_mp4, vga_mp4, audio_aac, output_mkv):
    """合并两路视频+蓝牙音频成双轨 mkv (-c copy)。"""
    cmd = [
        utils.get_ffmpeg_command(),
        "-i", main_mp4, "-i", vga_mp4, "-i", audio_aac,
        "-map", "0:v", "-map", "0:a", "-map", "1:v", "-map", "1:a", "-map", "2:a",
        "-c", "copy",
        "-metadata:s:v:0", "title=摄像头",
        "-metadata:s:v:1", "title=屏幕",
        "-metadata:s:a:0", "title=蓝牙话筒",
        "-metadata:s:a:1", "title=摄像头内嵌",
        "-metadata:s:a:2", "title=屏幕内嵌",
        output_mkv,
    ]
    run(cmd, check=True)
```

**注意**：蓝牙音频可选（有的课没有蓝牙话筒）。无蓝牙时退化为 2 video + 2 audio（各内嵌）。

### 阶段 2：main.py 双轨下载编排

当前 `main.py:38-42` 下载选项：
```
选择下载摄像头(1)还是电脑屏幕(2)?
```

改为：
```
选择下载: 1.摄像头 2.屏幕 3.双轨合并(摄像头+屏幕+蓝牙)
```

选 3 时：
1. 下载 main.mp4（`M3u8Download(c["videos"][0]["main"], path, name)`）
2. 下载 vga.mp4（`M3u8Download(c["videos"][0]["vga"], path, name+"-screen")`）
3. 下载蓝牙 .aac（`utils.download_audio`）
4. `merge_to_mkv(main.mp4, vga.mp4, bluetooth.aac, name+".mkv")`
5. 清理中间文件（main.mp4 / vga.mp4 / bluetooth.aac / 临时 .ts 目录）

输出：`output/<课程名>-merged/<name>.mkv`

### 阶段 3：webui 双轨任务

**后端** `webui_interface.py:81-96` `execute_one_download_task_worker`：
- 当前下载单路。扩展支持 `download_mode = "merge"` 时下载两路 + 合并。
- 下载两路可顺序（简单）或并发（快，但签名刷新线程冲突需注意，先顺序）。

**前端** `templates/index.html` + `webui/script.js`：
- 下载类型下拉加"双轨合并"选项
- 提交时带 `download_mode=merge`

### 阶段 4：清理与验证

- 合并后默认删除中间 .mp4/.aac（可加保留选项，YAGNI 先默认删）
- `ffprobe output.mkv` 验证 track 结构（2 video + 3 audio）
- 播放器（VLC/IINA）测试切换 track

## 代码改动点

| 文件 | 改动 |
|---|---|
| `m3u8dl.py` | 加 `merge_to_mkv` 函数 |
| `main.py` | 下载选项加"双轨合并"，编排下载两路+合并+清理 |
| `webui_interface.py` | `execute_one_download_task_worker` 支持双轨模式 |
| `templates/index.html` | 下载类型加"双轨合并"选项 |
| `webui/script.js` | 提交 `download_mode=merge` |
| `utils.py` | 无需改（`download_audio` 已有） |

## 风险与注意

1. **签名刷新冲突**：两路 m3u8 下载各起 `updateSignatureLoop` 线程，token 共享但签名独立。顺序下载避免并发冲突；若并发需确认 `utils.getSignature()` 线程安全。
2. **蓝牙音频缺失**：部分课程无蓝牙话筒。`merge_to_mkv` 需处理 audio_aac=None 情况（退化为 2 video + 2 audio）。
3. **mkv 兼容性**：mkv 多轨在 VLC/IINA/mpv 支持；QuickTime 不支持 mkv。文档提示用户用 VLC/IINA。
4. **磁盘空间**：下载两路中间 .mp4 临时占双倍空间，合并后删除。长课程需确认磁盘足够。
5. **vga 0.46s 偏移**：蓝牙与 vga 有偏移，YAGNI 先不校准。若用户反馈需要，后续加 `-itsoffset` 选项。

## 后续可选优化（YAGNI，先不做）

- 并发下载两路（速度提升 ~2x）
- itsoffset 校准蓝牙与 vga 偏移
- 保留中间文件选项
- 内网模式（校园网 110MB/s，github-researcher 建议）
