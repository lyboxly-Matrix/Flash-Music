# -*- mode: python ; coding: utf-8 -*-
# PyInstaller onefile spec for Flash Music

block_cipher = None

from PyInstaller.utils.hooks import collect_all
# Media Foundation playback (WinRT MediaPlayer): bundle the winrt projection packages.
_winrt_datas, _winrt_bins, _winrt_hidden = collect_all('winrt')

a = Analysis(
    ['源代码/main.py'],
    pathex=['源代码'],
    binaries=_winrt_bins,
    datas=_winrt_datas,
    hiddenimports=_winrt_hidden + [
        'mutagen',
        'mutagen.id3',
        'mutagen.mp3',
        'mutagen.flac',
        'mutagen.mp4',
        'mutagen.oggvorbis',
        'mutagen.wave',
        'app',
        'theme',
        'player_core',
        'mf_backend',
        'config',
        'title_bar',
        'cue_export',
        'fluid_visual',
        'glass_button',
        'transport_bar',
        'toast',
        'PySide6.QtNetwork',
        'PySide6.QtOpenGL',
        'PySide6.QtOpenGLWidgets',
        'numpy',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='FlashMusic',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
