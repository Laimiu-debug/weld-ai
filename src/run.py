"""weldAI 顶层启动入口（打包用）。

PyInstaller 打包后，包内相对导入(from .x import y)在直接作为脚本执行时会失败。
本文件作为打包入口，先确保包可被导入，再调用真正的 main。
"""
import sys
from pathlib import Path

# 打包模式：把 _MEIPASS 加入 sys.path，使 weldai 包可被导入
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    sys.path.insert(0, sys._MEIPASS)
else:
    # 开发模式：把 src 加入 path
    src_dir = str(Path(__file__).resolve().parent)
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)

from weldai.main import main

if __name__ == "__main__":
    raise SystemExit(main())
