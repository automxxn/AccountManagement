import sys

from PySide6.QtWidgets import QApplication

from . import logsetup
from .db import Repository
from .version import __version__
from .ui.common import app_icon, apply_appearance
from .ui.connect import settings, start_repository
from .ui.main_window import MainWindow
from .ui.update_ui import startup_check


def main() -> None:
    logsetup.setup()
    logsetup.log.info("시작 v%s", __version__)
    app = QApplication(sys.argv)
    app.setApplicationName("AccountManagement")
    app.setWindowIcon(app_icon())
    app.setStyle("Fusion")
    s = settings()
    apply_appearance(s.value("theme", "light"), float(s.value("zoom", 1.0)))
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
