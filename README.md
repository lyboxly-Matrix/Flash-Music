# ⚡ Flash Music

简洁的 **Windows 本地音乐播放器**，面向日常听歌：打开文件夹、播放列表、随机/循环，导入时自动轻量整理。

- 完全本地，不上传任何文件
- Python 3.11 + PySide6 + Windows Media Foundation（WinRT MediaPlayer）
- 深色霓虹界面（青 → 紫）

## 功能

| 功能 | 说明 |
|------|------|
| 打开文件夹 / 添加文件 | 支持 mp3、flac、wav、m4a、ogg、aac、wma（取决于系统编解码器） |
| 播放列表 | 侧边栏点击跳转，上一首 / 下一首 |
| 进度条 + 音量 | 可拖动定位 |
| 随机 / 循环 | 循环：关 → 全部 → 单曲 |
| 自动优化 | 导入时按标题/艺术家（有元数据时）或文件名自然排序，并按路径去重 |
| CUE 分轨 | 整轨 FLAC/WAV + .cue 会展开为多首进入播放列表 |
| 导出分轨 FLAC（无损） | 检测到 CUE 时显示按钮，一键按采样精确切成每曲 FLAC（保留原采样率/位深/声道），写入标签并嵌入封面（需系统 ffmpeg） |
| 记忆 | 上次播放列表、音量、窗口位置、随机/循环模式 |

**不做：** 均衡器、云同步、歌词抓取、复杂设置页。

## 环境要求

- Windows 10/11
- Python **3.11**（推荐路径示例：D:\Python311\python.exe）
- 依赖见 `requirements.txt`

### 播放后端说明

Flash Music 使用 **Windows Media Foundation**（WinRT `Windows.Media.Playback.MediaPlayer`，与 Windows 媒体播放器相同的引擎）播放，由 `源代码/mf_backend.py` 封装。

- 自动跟随系统默认输出设备；蓝牙音箱被其它程序（如浏览器）占用后再恢复播放，音频流由系统自动重建，用于改善蓝牙输出恢复；仍需按实际设备验证。
- 支持 Windows 自带解码的格式：MP3 / FLAC / WAV / M4A / AAC / WMA 等（OGG 需系统已装相应扩展）。
- 频谱可视化：后台另行解码当前曲目（不占用声卡）按播放位置驱动。
- 依赖 `winrt-*` 包（见 `requirements.txt`），`build.bat` 会自动安装并打包进 exe。

## 安装与运行

在项目根目录下安装依赖，再用 源代码 里的入口启动：

`at
cd /d "F:\Vibe Coding\Flash Music"
D:\Python311\python.exe -m pip install -r requirements.txt
D:\Python311\python.exe 源代码\main.py
```

或（若 python 已指向 3.11）：

`at
pip install -r requirements.txt
python 源代码\main.py
```

也可先进入源码目录再运行（相对导入同样可用）：

`at
cd /d "F:\Vibe Coding\Flash Music\源代码"
python main.py
```

**已打包用户：** 直接双击项目根目录的 FlashMusic.exe 即可，无需安装 Python。

### 自检（可选）

`at
cd /d "F:\Vibe Coding\Flash Music"
D:\Python311\python.exe 源代码\selftest.py
```

## 打包（PyInstaller）

在项目根目录执行（会读取 FlashMusic.spec，入口为 源代码\main.py）：

`at
build.bat
```

成功后：

- dist\FlashMusic.exe（构建产物）
- 根目录 FlashMusic.exe（uild.bat 会自动复制一份）

也可：

`at
D:\Python311\python.exe -m PyInstaller FlashMusic.spec
```

## 配置位置

设置保存在用户目录（不写入项目文件夹）：

- Windows：%LOCALAPPDATA%\FlashMusic\config.json
- 其他平台：~/.flash_music/config.json

内容包括：播放列表（含 CUE 分轨起止时间）、播放位置、音量、上次曲目索引、随机/循环、窗口几何、最近打开、上次导出文件夹。

## 项目结构

`````
Flash Music/
  FlashMusic.exe      # 单文件可执行（可选，双击即用）
  README.md
  requirements.txt
  FlashMusic.spec     # PyInstaller onefile
  build.bat
  源代码/
    main.py           # 入口
    app.py            # 主窗口 UI
    theme.py          # 深色霓虹主题
    player_core.py    # 播放列表 + 播放控制
    mf_backend.py     # Media Foundation 播放后端 + 可视化解码
    config.py         # 配置读写（原子写入 + .bak）
    title_bar.py      # 自定义深色标题栏
    glass_button.py   # 液态玻璃矢量按钮
    transport_bar.py  # 控制栏布局（居中、防重叠）
    fluid_visual.py   # GPU 流体可视化（CPU 降级）
    toast.py          # 非阻塞提示卡 / 菜单矢量图标
    cue_export.py     # 无损导出（FLAC / 有损原格式拷贝）
    selftest.py       # 轻量自检
    verify_restore.py # 播放列表恢复端到端测试
    layout_check.py   # 控制栏布局检查
```

## 快捷键

| 快捷键 | 作用 |
|--------|------|
| Space | 播放 / 暂停 |
| Ctrl+O | 打开文件夹 |
| Ctrl+Shift+O | 添加文件 |
| Ctrl+← / Ctrl+→ | 上一首 / 下一首 |
| Ctrl+Q | 退出 |

## 许可与隐私

本地工具，音乐文件仅在本机读取播放，**不会上传**。请自行确保你对播放的音频拥有合法使用权。


## 导出分轨 FLAC（无损，CUE + 整轨）

当播放列表来自 **CUE + 单文件 FLAC/WAV** 时，侧栏会出现 **「导出分轨 FLAC（无损）」**：

1. 使用系统 **ffmpeg** 按 CUE 帧边界做**采样级精确**切割（不是按毫秒近似）
2. 编码为 **FLAC**（压缩等级 5），**保留原采样率 / 位深 / 声道**，不重采样
3. 用 mutagen 写入 Vorbis 标签：**TITLE / ARTIST / ALBUM / TRACKNUMBER / TOTALTRACKS**，
   若 CUE 或源文件中有则同时写入 **ALBUMARTIST / DATE / GENRE**
4. 源文件旁若有 `cover.*` / `folder.jpg` / `front.*` 封面图片，会自动嵌入
5. 默认输出到源文件旁的 `*_FLAC` 文件夹，也可「选择文件夹…」（会记住上次选择）
6. 后台线程导出，右下角提示进度，完成后可一键「打开文件夹」

### 关于有损来源（MP3 / AAC / OGG）

有损文件转成 FLAC **无法找回已经丢失的音质**，只会让文件变大并“伪装”成无损。
因此对有损来源，Flash Music **不会转成 FLAC**，而是按原格式直接拷贝音频流（不重新编码、不再损失音质）并写入标签；
完成提示中会说明有几首是“有损来源已按原格式拷贝”。若 CUE 指向有损整轨，切割点只能精确到音频帧。

### ffmpeg 要求

本功能**不捆绑** ffmpeg，需本机已安装并可在 PATH 中调用 `ffmpeg`。

Windows 示例：

```bat
winget install Gyan.FFmpeg
```

安装后重新打开 Flash Music。若未检测到 ffmpeg，点击导出时会提示安装说明。

## 验证与调试

- 播放列表恢复端到端测试（使用独立配置目录，不会改动真实的 `%LOCALAPPDATA%\FlashMusic\config.json`）：

  ```
  python 源代码\verify_restore.py "D:\音乐\某专辑"
  python 源代码\verify_restore.py "D:\音乐\某专辑" --exe FlashMusic.exe
  ```

  流程：启动 → 载入文件夹 → 点击标题栏 ✕ 关闭 → 重新启动两次，确认曲目数一致（输出 `RESULT: PASS`）。
- 流体可视化默认使用 GPU（OpenGL 3.3）；OpenGL 不可用时自动降级为 numpy CPU 低分辨率流体。
  强制使用 CPU 版本测试：`set FLASHMUSIC_FLUID=cpu` 后再启动。
- `FLASHMUSIC_CONFIG_DIR=<目录>` 可让程序使用独立配置目录（测试用）。

## 右键导出单曲 FLAC（无损）

在播放列表中右键曲目 → **导出为 FLAC（无损）**；Ctrl/Shift 多选后显示 **导出所选 N 首为 FLAC（无损）**。
CUE 分轨按采样精确切割，普通无损文件整首转为 FLAC，规则与上面的整张专辑导出相同（标签、封面、`*_FLAC` 默认文件夹、记住上次文件夹、有损来源按原格式拷贝）。需要系统 ffmpeg。
