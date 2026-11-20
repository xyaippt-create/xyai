# -*- mode: python ; coding: utf-8 -*-

import runpy
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


PROJECT_ROOT = Path(SPECPATH).resolve().parents[1]
RESOURCE_CONTRACT = runpy.run_path(str(Path(SPECPATH) / "program_resources.py"))
datas = RESOURCE_CONTRACT["build_pyinstaller_datas"](PROJECT_ROOT)
# OpenCV face cascades read through cv2.data.haarcascades by colour correction (level pick,
# reference level pick, automatic correction). The cv2 hook does not collect them.
OPENCV_FACE_CASCADES = (
    "haarcascade_frontalface_default.xml",
    "haarcascade_frontalface_alt2.xml",
    "haarcascade_profileface.xml",
)
datas += collect_data_files("cv2", subdir="data", includes=list(OPENCV_FACE_CASCADES))

hiddenimports = collect_submodules("uvicorn") + collect_submodules("multipart") + [
    "clr",
    "webview.platforms.edgechromium",
    "webview.platforms.winforms",
]

a = Analysis(
    [str(PROJECT_ROOT / "packaged_main.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(Path(SPECPATH) / "hooks")],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "torch",
        "torchvision",
        "transformers",
        "timm",
        "gui",
        "tkinter",
        "webview.platforms.android",
        "webview.platforms.cef",
        "webview.platforms.cocoa",
        "webview.platforms.gtk",
        "webview.platforms.qt",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="HDDE",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    icon=str(PROJECT_ROOT / "public" / "branding" / "hdde" / "hdde.ico"),
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="HDDE",
)
