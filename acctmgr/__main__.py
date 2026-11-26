import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from .db import Repository
from .ui.common import APP_STYLE
from .ui.connect import start_repository
from .ui.main_window import MainWindow
from .ui.update_ui import startup_check


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("AccountManagement")
    app.setStyle("Fusion")
    app.setFont(QFont("Malgun Gothic", 10))
    app.setStyleSheet(APP_STYLE)
    if startup_check():  # 새 버전을 설치하고 다시 시작하는 중
        return
    if len(sys.argv) > 1:  # 개발/테스트용: 로컬 DB 파일 지정
        repo = Repository(sys.argv[1])
    else:
        repo = start_repository()
        if repo is None:
            return
    win = MainWindow(repo)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
