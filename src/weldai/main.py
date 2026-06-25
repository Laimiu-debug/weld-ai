"""weldAI 应用入口。"""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .persistence import close_session
from .ui import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("weldAI")
    window = MainWindow()
    window.show()
    exit_code = app.exec()
    # 应用退出时关闭数据库会话，释放 WAL 连接
    close_session()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
