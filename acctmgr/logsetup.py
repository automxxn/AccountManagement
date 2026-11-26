"""오류 기록: %APPDATA%\\AccountManagement\\logs\\app.log 에 남긴다 (콘솔 창 없이 실행되므로)."""
from __future__ import annotations

import logging
import os
import sys
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

log = logging.getLogger("acctmgr")


def log_dir() -> Path:
    base = Path(os.environ.get("APPDATA") or str(Path.home()))
    p = base / "AccountManagement" / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


class _ToLog:
    """콘솔이 없을 때 print/경고 출력을 로그로 보낸다."""

    def __init__(self, level):
        self.level = level

    def write(self, msg):
        msg = msg.strip()
        if msg:
            log.log(self.level, msg)

    def flush(self):
        pass


def setup() -> None:
    handler = RotatingFileHandler(log_dir() / "app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if sys.stdout is None:
        sys.stdout = _ToLog(logging.INFO)
    if sys.stderr is None:
        sys.stderr = _ToLog(logging.ERROR)

    def hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        log.error("처리되지 않은 오류\n%s", text)
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox
            if QApplication.instance():
                box = QMessageBox(QMessageBox.Critical, "오류",
                                  f"예상하지 못한 오류가 났어요.\n{exc_type.__name__}: {exc}\n\n"
                                  f"자세한 내용은 로그 파일에 저장됐어요:\n{log_dir() / 'app.log'}")
                open_btn = box.addButton("로그 폴더 열기", QMessageBox.ActionRole)
                box.addButton("확인", QMessageBox.AcceptRole)
                box.exec()
                if box.clickedButton() is open_btn:
                    open_log_folder()
        except Exception:
            pass

    sys.excepthook = hook


def open_log_folder() -> None:
    os.startfile(str(log_dir()))  # type: ignore[attr-defined]
