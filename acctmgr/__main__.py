import sys

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication

from . import logsetup, selfname
from .db import Repository
from .version import __version__
from .ui.common import app_icon, apply_appearance, apply_native_icon, refresh_shell_icons_once
from .ui.connect import settings, start_repository
from .ui.main_window import MainWindow
from .ui.update_ui import startup_check


def _set_app_id() -> None:
    """작업표시줄에 프로그램 아이콘이 나오도록 Windows 앱 ID를 정한다 (창을 만들기 전에 호출)."""
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AccountManagement.App")
    except Exception:
        pass


class _NativeIcons(QObject):
    """창(로그인 창, 메인 창, 대화상자)이 처음 뜰 때 exe에 든 아이콘을 Windows에 직접 붙인다.
    (Qt 아이콘만으로는 일부 PC의 작업표시줄에 기본 아이콘이 보이는 경우가 있었음)"""

    def __init__(self):
        super().__init__()
        self.done = set()

    def eventFilter(self, obj, ev) -> bool:
        if ev.type() == QEvent.Show and getattr(obj, "isWindow", None) and obj.isWindow():
            key = id(obj)
            if key not in self.done:
                self.done.add(key)
                apply_native_icon(obj)
        return False


def main() -> None:
    logsetup.setup()
    _set_app_id()
    logsetup.log.info("시작 v%s", __version__)
    selfname.migrate()   # 예전 이름(AccountManagement.exe)이면 AM.exe로 바꾸고 바로가기 고치기
    app = QApplication(sys.argv)
    app.setApplicationName("AccountManagement")   # 설정 저장 위치가 바뀌지 않게 내부 이름은 그대로
    app.setApplicationDisplayName("AM")
    app.setWindowIcon(app_icon())
    icons = _NativeIcons()
    app.installEventFilter(icons)
    refresh_shell_icons_once(__version__)
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
