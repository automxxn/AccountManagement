from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from ..db import RepoError
from ..models import STATUS_AVAILABLE, STATUS_BANNED, STATUS_IN_USE, STATUS_WITHDRAWN

# ---------------------------------------------------------------- 색
INK = "#1F2328"
MUTED = "#6B7280"
LINE = "#E4E6EA"
BG = "#F4F5F7"
ACCENT = "#2563EB"

# 상태별 (배경, 글자)
COLORS = {
    STATUS_AVAILABLE: ("#E7F6EC", "#1A7F37"),
    STATUS_IN_USE: ("#E8F0FE", "#1D4ED8"),
    STATUS_BANNED: ("#FDECEC", "#B42318"),
    STATUS_WITHDRAWN: ("#EEEFF1", "#57606A"),
    "ban": ("#FDECEC", "#B42318"),
    "info": ("#EEEFF1", "#3D4450"),
    "worker": ("#F3EEFE", "#6D28D9"),
}

APP_STYLE = f"""
QWidget {{ font-family: "Malgun Gothic"; font-size: 13px; color: {INK}; }}
QMainWindow, QWidget#page, QDialog {{ background: {BG}; }}
QToolTip {{ background: {INK}; color: white; border: none; padding: 4px 8px; }}

/* 사이드바 */
QFrame#sidebar {{ background: #FFFFFF; border-right: 1px solid {LINE}; }}
QLabel#appTitle {{ font-size: 16px; font-weight: bold; }}
QLabel#appVersion {{ color: {MUTED}; font-size: 11px; }}
QListWidget#nav {{ border: none; background: transparent; outline: 0; }}
QListWidget#nav::item {{ padding: 10px 12px; margin: 1px 0; border-radius: 8px; color: #3D4450; }}
QListWidget#nav::item:selected {{ background: #E8F0FE; color: #1D4ED8; font-weight: bold; }}
QListWidget#nav::item:hover:!selected {{ background: #F2F3F5; }}
QFrame#userBox {{ background: #F7F8FA; border: 1px solid {LINE}; border-radius: 10px; }}

/* 페이지 머리 */
QLabel#pageTitle {{ font-size: 22px; font-weight: bold; }}
QLabel#pageSub {{ color: {MUTED}; }}
QLabel#sectionTitle {{ color: {MUTED}; font-size: 12px; font-weight: bold; padding-top: 6px; }}
QLabel#muted {{ color: {MUTED}; font-size: 12px; }}
QLabel#title {{ font-size: 15px; font-weight: bold; }}

/* 버튼 */
QPushButton, QToolButton {{ background: #FFFFFF; border: 1px solid #D0D5DD; border-radius: 7px; padding: 6px 12px; }}
QPushButton:hover, QToolButton:hover {{ background: #F3F4F6; }}
QPushButton:pressed {{ background: #E9EBEF; }}
QPushButton:disabled {{ color: #A0A6AF; background: #F5F6F8; border-color: {LINE}; }}
QPushButton#primary {{ background: {ACCENT}; border-color: {ACCENT}; color: white; font-weight: bold; }}
QPushButton#primary:hover {{ background: #1D4ED8; }}
QPushButton#primary:disabled {{ background: #A9C0F5; border-color: #A9C0F5; }}
QPushButton#danger {{ color: #B42318; }}
QPushButton#danger:hover {{ background: #FEF3F2; border-color: #F5B5B0; }}
QPushButton#ghost {{ border: none; background: transparent; color: {MUTED}; padding: 4px 8px; }}
QPushButton#ghost:hover {{ background: #F2F3F5; color: {INK}; }}
QPushButton#chip {{ border-radius: 15px; padding: 5px 14px; color: #3D4450; }}
QPushButton#chip:checked {{ background: {INK}; border-color: {INK}; color: white; font-weight: bold; }}
QToolButton::menu-indicator {{ image: none; }}

/* 입력칸 */
QLineEdit, QComboBox, QSpinBox, QPlainTextEdit {{
    background: #FFFFFF; border: 1px solid #D0D5DD; border-radius: 7px; padding: 6px 8px;
    selection-background-color: #C9DAFB; selection-color: {INK}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPlainTextEdit:focus {{ border: 1px solid {ACCENT}; }}
QLineEdit:disabled {{ background: #F5F6F8; color: #9AA0A8; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ border: 1px solid {LINE}; background: white; selection-background-color: #E8F0FE; selection-color: {INK}; }}
QCheckBox {{ spacing: 6px; }}

/* 표 */
QTableWidget {{ background: #FFFFFF; border: 1px solid {LINE}; border-radius: 10px; gridline-color: #F0F1F3;
    alternate-background-color: #FAFBFC; selection-background-color: #E8F0FE; selection-color: {INK}; }}
QHeaderView::section {{ background: #F7F8FA; border: none; border-bottom: 1px solid {LINE};
    border-right: 1px solid #F0F1F3; padding: 8px 6px; font-weight: bold; color: #4B5563; }}
QTableCornerButton::section {{ background: #F7F8FA; border: none; }}

/* 카드 */
QFrame#card, QFrame#panel {{ background: #FFFFFF; border: 1px solid {LINE}; border-radius: 12px; }}
QFrame#statCard {{ background: #FFFFFF; border: 1px solid {LINE}; border-radius: 12px; }}
QLabel#statLabel {{ color: {MUTED}; font-size: 12px; }}
QLabel#statValue {{ font-size: 24px; font-weight: bold; }}
QFrame#panelHead {{ border: none; border-bottom: 1px solid #EEF0F3; }}
QFrame#vline {{ background: #EEF0F3; max-width: 1px; min-width: 1px; border: none; }}

/* 작업장 */
QFrame#pcRow {{ background: #FFFFFF; border: 1px solid {LINE}; border-radius: 12px; }}
QFrame#pcRow[active="true"] {{ border: 1px solid #93B4F8; }}
QLabel#pcNo {{ font-size: 18px; font-weight: bold; color: {ACCENT}; }}
QLabel#pcName {{ font-size: 15px; font-weight: bold; }}
QFrame#slot {{ background: #FFFFFF; border: 1px solid {LINE}; border-radius: 9px; }}
QFrame#slot:hover {{ border-color: #9CA3AF; }}
QFrame#slot[empty="true"] {{ background: #F9FAFB; border: 1px dashed #C4C9D1; }}
QFrame#slot[empty="true"]:hover {{ border-color: {ACCENT}; background: #F5F9FF; }}
QFrame#slot[locked="true"] {{ background: #F3F4F6; border: 1px solid {LINE}; }}
QFrame#slot[selected="true"] {{ border: 2px solid {ACCENT}; background: #F5F9FF; }}
QLabel#slotNo {{ background: #EEF0F3; color: #4B5563; border-radius: 9px; font-size: 11px; font-weight: bold;
    min-width: 18px; max-width: 18px; min-height: 18px; max-height: 18px; qproperty-alignment: AlignCenter; }}
QLabel#owner {{ font-size: 14px; font-weight: bold; }}
QListWidget#pickList {{ background: #FFFFFF; border: 1px solid {LINE}; border-radius: 10px; outline: 0; }}
QListWidget#pickList::item {{ padding: 8px 10px; border-bottom: 1px solid #F0F1F3; }}
QListWidget#pickList::item:selected {{ background: #E8F0FE; color: {INK}; }}
QListWidget#pickList::item:hover:!selected {{ background: #F7F8FA; }}

QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget#scrollHost {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #C9CDD4; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #A9AFB8; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QStatusBar {{ background: #FFFFFF; border-top: 1px solid {LINE}; color: {MUTED}; }}
QMenu {{ background: #FFFFFF; border: 1px solid {LINE}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 7px 16px; border-radius: 6px; }}
QMenu::item:selected {{ background: #E8F0FE; color: {INK}; }}
QMenu::separator {{ height: 1px; background: {LINE}; margin: 4px 6px; }}
QProgressDialog, QMessageBox, QInputDialog {{ background: #FFFFFF; }}
"""


# ---------------------------------------------------------------- 작은 부품
def badge(text: str, kind: str) -> QLabel:
    bg, fg = COLORS.get(kind, COLORS["info"])
    lab = QLabel(text)
    lab.setStyleSheet(f"background:{bg}; color:{fg}; border-radius:5px; padding:2px 7px; font-size:11px; font-weight:bold;")
    lab.setAlignment(Qt.AlignCenter)
    return lab


def muted(text: str = "") -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("muted")
    return lab


def label(text: str, name: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName(name)
    return lab


def button(text: str, kind: str = "", slot=None, tip: str = "") -> QPushButton:
    b = QPushButton(text)
    if kind:
        b.setObjectName(kind)
    if slot:
        b.clicked.connect(slot)
    if tip:
        b.setToolTip(tip)
    b.setCursor(Qt.PointingHandCursor)
    return b


def vline() -> QFrame:
    f = QFrame()
    f.setObjectName("vline")
    return f


def page_header(title: str, subtitle: str = "", right: list[QWidget] | None = None) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    col = QVBoxLayout()
    col.setSpacing(2)
    col.addWidget(label(title, "pageTitle"))
    if subtitle:
        col.addWidget(label(subtitle, "pageSub"))
    lay.addLayout(col)
    lay.addStretch(1)
    for r in right or []:
        lay.addWidget(r, 0, Qt.AlignBottom)
    return w


class StatCard(QFrame):
    def __init__(self, title: str, color: str = INK):
        super().__init__()
        self.setObjectName("statCard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(2)
        lay.addWidget(label(title, "statLabel"))
        self.value = label("0", "statValue")
        self.value.setStyleSheet(f"color:{color};")
        lay.addWidget(self.value)

    def set(self, n: int) -> None:
        self.value.setText(f"{n:,}")


def page() -> tuple[QWidget, QVBoxLayout]:
    w = QWidget()
    w.setObjectName("page")
    lay = QVBoxLayout(w)
    lay.setContentsMargins(28, 24, 28, 20)
    lay.setSpacing(16)
    return w, lay


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
