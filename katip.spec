# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from pathlib import Path

block_cipher = None
project_root = Path(os.path.abspath(".")).resolve()
sys.path.insert(0, str(project_root))
from katip import __version__

windows_icon = project_root / "assets" / "katip.ico"
macos_icon = project_root / "assets" / "katip.icns"

# Collect assets
datas = [
    (str(project_root / "assets"), "assets"),
]

hiddenimports = [
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "pyaudio",
    "webrtcvad",
    "pynput",
    "pynput.keyboard",
    "pynput.mouse",
    "requests",
    "ctypes",
]

if sys.platform.startswith("win"):
    hiddenimports += [
        "pynput.keyboard._win32",
        "pynput.mouse._win32",
        "winsound",
        "ctypes.wintypes",
    ]
elif sys.platform == "darwin":
    hiddenimports += [
        "pynput.keyboard._darwin",
        "pynput.mouse._darwin",
    ]

a = Analysis(
    [str(project_root / "run_katip.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(project_root / "pyinstaller_hooks")],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "scipy", "pandas"],
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
    name="Katip",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=(
        str(windows_icon) if sys.platform.startswith("win") and windows_icon.exists()
        else str(macos_icon) if sys.platform == "darwin" and macos_icon.exists()
        else None
    ),
)

if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name="Katip.app",
        icon=str(macos_icon) if macos_icon.exists() else None,
        bundle_identifier="com.talktowrite.katip",
        version=__version__,
        info_plist={
            "CFBundleDisplayName": "Katip",
            "LSUIElement": True,
            "NSPrincipalClass": "NSApplication",
            "NSMicrophoneUsageDescription": (
                "Katip records audio when you start dictation."
            ),
            "NSAppleEventsUsageDescription": (
                "Katip uses a paste shortcut to insert dictated text into the active app."
            ),
        },
    )
