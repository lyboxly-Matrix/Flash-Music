# 当前发布快照

源码及 EXE 来自现有 Flash Music 项目，上传日期为 2026-10-16。
EXE 构建文件时间为 2026-10-13 15:32，未在本次上传中重新构建。

## 当前架构

- Python / PySide6 桌面界面。
- Windows Media Foundation / WinRT MediaPlayer 负责音频播放。
- Qt QAudioDecoder 单独解码以驱动流体可视化。
- CUE 分轨、FLAC 导出及播放列表恢复保留。

## 已知情况

2026-10-16 的本机运行日志出现过 MediaPlayerError.SOURCE_NOT_SUPPORTED（错误码 4）。日志未包含失败曲目，因此尚未确认具体音源或格式。不能据此保证所有音频格式及蓝牙场景均已修复。

本次上传核对了 EXE 内包含 mf_backend 和 WinRT 依赖；未重新执行完整播放、导出或回归测试。

个人播放记录、配置、音频文件和运行日志不包含在仓库中。Windows 配置默认位于 `%LOCALAPPDATA%/FlashMusic`。

## 下载与构建

直接使用 Releases 中的 FlashMusic.exe，无需安装 Python。
从源码构建请使用 Python 3.11，安装 requirements.txt 中的依赖及 PyInstaller 后，在仓库根目录执行：

```powershell
python -m PyInstaller --noconfirm FlashMusic.spec
```

产物位于 dist/FlashMusic.exe。源码依赖没有完全锁定版本，未来重新构建的结果可能与本次上传的现有 EXE 不同。
