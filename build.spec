# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（单文件 exe）。

用法：pyinstaller build.spec
产物：dist/weldAI.exe
"""
from pathlib import Path

block_cipher = None

# 项目根目录
ROOT = Path(SPECPATH).resolve()
SRC = ROOT / "src" / "weldai"

a = Analysis(
    [str(ROOT / "src" / "run.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=[
        # YAML 规则数据（打包到 weldai/standards/data）
        (str(SRC / "standards" / "data"), "weldai/standards/data"),
        # 内嵌中文字体
        (str(SRC / "assets" / "fonts"), "weldai/assets/fonts"),
    ],
    hiddenimports=[
        # matplotlib 后端（Agg 无GUI）
        "matplotlib.backends.backend_agg",
        # SQLAlchemy
        "sqlalchemy.dialects.sqlite",
        "sqlalchemy.sql.default_comparator",
        # PySide6 插件
        "PySide6.QtCore",
        "PySide6.QtWidgets",
        "PySide6.QtGui",
        # python-docx
        "docx",
        # openpyxl
        "openpyxl",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 排除不需要的大模块减小体积
        # 注意：unittest 不可排除——pyparsing.testing（matplotlib 依赖）在导入时即引用 unittest
        "tkinter",
        "pydoc",
        "test",
        "tests",
    ],
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
    name="weldAI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    # GUI 应用，无控制台窗口
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon=str(ROOT / "assets" / "weldai.ico"),  # 可选图标
)
