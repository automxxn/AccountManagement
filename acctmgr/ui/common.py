from __future__ import annotations

from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QWidget

from ..db import RepoError
from ..models import STATUS_AVAILABLE, STATUS_BANNED, STATUS_IN_USE, STATUS_WITHDRAWN

COLORS = {
    STATUS_AVAILABLE: ("#E8F4E1", "#2F6410"),
    STATUS_IN_USE: ("#E3EEFB", "#0C447C"),
    STATUS_BANNED: ("#FCE9E9", "#8A2323"),
    STATUS_WITHDRAWN: ("#EEEDEA", "#55544F"),
    "ban": ("#FCE9E9", "#8A2323"),
}

APP_STYLE = """
QWidget { font-size: 13px; }
QFrame#pcCard { background: #FFFFFF; border: 1px solid #DDDBD3; border-radius: 10px; }
QFrame#slot { background: #FFFFFF; border: 1px solid #DDDBD3; border-radius: 6px; }
QFrame#slot:hover { border-color: #9C9A92; }
QFrame#slot[empty="true"] { border: 1px dashed #B4B2A9; background: #FAFAF7; }
QFrame#slot[selected="true"] { border: 2px solid #378ADD; }
QFrame#panel { background: #FFFFFF; border: 1px solid #DDDBD3; border-radius: 10px; }
QLabel#muted { color: #6B6A64; font-size: 12px; }
QLabel#title { font-size: 14px; font-weight: 600; }
QLabel#metric { font-size: 20px; font-weight: 600; }
QFrame#metricBox { background: #F1EFE8; border-radius: 8px; }
"""


def badge(text: str, kind: str) -> QLabel:
    bg, fg = COLORS.get(kind, COLORS[STATUS_WITHDRAWN])
    lab = QLabel(text)
    lab.setStyleSheet(f"background:{bg}; color:{fg}; border-radius:4px; padding:1px 6px; font-size:11px;")
    return lab


def muted(text: str = "") -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("muted")
    return lab


def copy_text(text: str) -> None:
    QApplication.clipboard().setText(text)


def run_safely(parent: QWidget, fn, *args) -> bool:
    """저장소 작업을 실행하고, 오류가 나면 알림창을 띄운다. 성공하면 True."""
    try:
        fn(*args)
        return True
    except RepoError as e:
        QMessageBox.warning(parent, "확인 필요", str(e))
        return False
