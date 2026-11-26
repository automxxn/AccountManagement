"""공통 디자인: 테마(라이트/다크), 화면 배율, 스타일시트, 작은 부품들."""
from __future__ import annotations

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPalette
from PySide6.QtWidgets import (
    QAbstractButton, QApplication, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton, QStyledItemDelegate,
    QTableWidget, QVBoxLayout, QWidget,
)

from ..db import RepoError

# ---------------------------------------------------------------- 테마
THEMES = {
    "light": {
        "bg": "#F4F5F7", "surface": "#FFFFFF", "surface2": "#F7F8FA", "hover": "#F2F3F5", "pressed": "#E9EBEF",
        "line": "#E4E6EA", "grid": "#ECEEF1", "input_border": "#D0D5DD",
        "ink": "#1F2328", "ink2": "#3D4450", "muted": "#6B7280", "faint": "#9AA0A8",
        "accent": "#2563EB", "accent_hover": "#1D4ED8", "accent_text": "#1D4ED8", "accent_soft": "#E8F0FE",
        "accent_soft2": "#F5F9FF", "accent_line": "#93B4F8", "disabled_accent": "#A9C0F5",
        "danger": "#B42318", "danger_soft": "#FEF3F2", "danger_line": "#F5B5B0",
        "success": "#1A7F37", "chip_on_bg": "#1F2328", "chip_on_fg": "#FFFFFF",
        "slot_empty": "#F9FAFB", "slot_empty_line": "#C4C9D1", "slot_locked": "#F3F4F6", "slotno_bg": "#EEF0F3",
        "scroll": "#C9CDD4", "scroll_hover": "#A9AFB8", "alt_row": "#FAFBFC", "header": "#F7F8FA",
        "header_ink": "#4B5563", "selection": "#C9DAFB",
        "table_bg": "#F1F3F6", "row_line": "#CDD2DA", "col_line": "#E0E3E8",
        "badge": {"ban": ("#FDECEC", "#B42318"), "info": ("#EEEFF1", "#3D4450"),
                  "worker": ("#F3EEFE", "#6D28D9")},
        "status": {"사용가능": "#1A7F37", "사용중": "#1D4ED8", "탈퇴": "#B42318"},
    },
    "dark": {
        "bg": "#15171B", "surface": "#1E2127", "surface2": "#23272E", "hover": "#2A2F37", "pressed": "#323842",
        "line": "#2E333B", "grid": "#2A2E35", "input_border": "#3A404A",
        "ink": "#E6E8EB", "ink2": "#C3C8CF", "muted": "#98A0AB", "faint": "#6E7681",
        "accent": "#3B82F6", "accent_hover": "#2563EB", "accent_text": "#7AA7FA", "accent_soft": "#1E2B45",
        "accent_soft2": "#1B2436", "accent_line": "#3B5A92", "disabled_accent": "#2C3E63",
        "danger": "#F87171", "danger_soft": "#3A1F22", "danger_line": "#7F3A3A",
        "success": "#4ADE80", "chip_on_bg": "#E6E8EB", "chip_on_fg": "#15171B",
        "slot_empty": "#1A1D22", "slot_empty_line": "#3F4650", "slot_locked": "#22262C", "slotno_bg": "#2E333B",
        "scroll": "#3A404A", "scroll_hover": "#4C535E", "alt_row": "#22252B", "header": "#23272E",
        "header_ink": "#B4BBC4", "selection": "#2C4A80",
        "table_bg": "#181B20", "row_line": "#3A404A", "col_line": "#272B32",
        "badge": {"ban": ("#3A1F22", "#F87171"), "info": ("#2A2F37", "#C3C8CF"),
                  "worker": ("#2E2546", "#C4B5FD")},
        "status": {"사용가능": "#4ADE80", "사용중": "#7AA7FA", "탈퇴": "#F87171"},
    },
}

_state = {"theme": "light", "scale": 1.0}
ZOOM_MIN, ZOOM_MAX, ZOOM_STEP = 0.7, 1.6, 0.1


def T(key: str) -> str:
    """지금 테마의 색."""
    return THEMES[_state["theme"]][key]


def theme() -> str:
    return _state["theme"]


def scale() -> float:
    return _state["scale"]


def px(n: float) -> int:
    """배율을 적용한 픽셀 크기."""
    return max(1, round(n * _state["scale"]))


def status_color(status: str) -> str:
    return THEMES[_state["theme"]]["status"].get(status, T("muted"))


def build_style() -> str:
    c = THEMES[_state["theme"]]
    p = px
    return f"""
QWidget {{ font-family: "Malgun Gothic"; font-size: {p(13)}px; color: {c['ink']}; }}
QMainWindow, QWidget#page, QDialog {{ background: {c['bg']}; }}
QToolTip {{ background: {c['ink']}; color: {c['bg']}; border: none; padding: 4px 8px; }}

QFrame#sidebar {{ background: {c['surface']}; border-right: 1px solid {c['line']}; }}
QLabel#appTitle {{ font-size: {p(16)}px; font-weight: bold; }}
QLabel#appVersion {{ color: {c['muted']}; font-size: {p(11)}px; }}
QListWidget#nav {{ border: none; background: transparent; outline: 0; }}
QListWidget#nav::item {{ padding: {p(10)}px {p(12)}px; margin: 1px 0; border-radius: 8px; color: {c['ink2']}; }}
QListWidget#nav::item:selected {{ background: {c['accent_soft']}; color: {c['accent_text']}; font-weight: bold; }}
QListWidget#nav::item:hover:!selected {{ background: {c['hover']}; }}
QFrame#userBox, QFrame#prefBox {{ background: {c['surface2']}; border: 1px solid {c['line']}; border-radius: 10px; }}

QLabel#pageTitle {{ font-size: {p(22)}px; font-weight: bold; }}
QLabel#pageSub {{ color: {c['muted']}; }}
QLabel#sectionTitle {{ color: {c['muted']}; font-size: {p(12)}px; font-weight: bold; padding-top: 6px; }}
QLabel#muted {{ color: {c['muted']}; font-size: {p(12)}px; }}
QLabel#faint {{ color: {c['faint']}; font-size: {p(12)}px; }}
QLabel#help {{ color: {c['ink2']}; }}
QLabel#title {{ font-size: {p(15)}px; font-weight: bold; }}
QLabel#hintBox {{ background: {c['surface']}; border: 1px solid {c['line']}; border-radius: 10px;
    padding: {p(12)}px {p(14)}px; color: {c['ink2']}; }}
QLabel#emptyText {{ color: {c['muted']}; font-size: {p(14)}px; padding: {p(40)}px; }}

QPushButton, QToolButton {{ background: {c['surface']}; border: 1px solid {c['input_border']}; border-radius: 7px;
    padding: {p(6)}px {p(12)}px; color: {c['ink']}; }}
QPushButton:hover, QToolButton:hover {{ background: {c['hover']}; }}
QPushButton:pressed {{ background: {c['pressed']}; }}
QPushButton:disabled {{ color: {c['faint']}; background: {c['surface2']}; border-color: {c['line']}; }}
QPushButton#primary {{ background: {c['accent']}; border-color: {c['accent']}; color: white; font-weight: bold; }}
QPushButton#primary:hover {{ background: {c['accent_hover']}; }}
QPushButton#primary:disabled {{ background: {c['disabled_accent']}; border-color: {c['disabled_accent']}; color: #E8EEFB; }}
QPushButton#danger {{ color: {c['danger']}; }}
QPushButton#danger:hover {{ background: {c['danger_soft']}; border-color: {c['danger_line']}; }}
QPushButton#ghost {{ border: none; background: transparent; color: {c['muted']}; padding: {p(4)}px {p(8)}px; }}
QPushButton#ghost:hover {{ background: {c['hover']}; color: {c['ink']}; }}
QPushButton#chip {{ border-radius: {p(15)}px; padding: {p(5)}px {p(14)}px; color: {c['ink2']}; }}
QPushButton#chip:checked {{ background: {c['chip_on_bg']}; border-color: {c['chip_on_bg']}; color: {c['chip_on_fg']}; font-weight: bold; }}
QPushButton#zoom {{ padding: {p(2)}px {p(8)}px; min-width: {p(22)}px; }}
QToolButton::menu-indicator {{ image: none; }}

QLineEdit, QComboBox, QSpinBox, QPlainTextEdit {{
    background: {c['surface']}; border: 1px solid {c['input_border']}; border-radius: 7px; padding: {p(6)}px {p(8)}px;
    color: {c['ink']}; selection-background-color: {c['selection']}; selection-color: {c['ink']}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPlainTextEdit:focus {{ border: 1px solid {c['accent']}; }}
QLineEdit:disabled {{ background: {c['surface2']}; color: {c['faint']}; }}
QComboBox::drop-down {{ border: none; width: {p(22)}px; }}
QComboBox QAbstractItemView {{ border: 1px solid {c['line']}; background: {c['surface']}; color: {c['ink']};
    selection-background-color: {c['accent_soft']}; selection-color: {c['ink']}; }}
QCheckBox {{ spacing: 6px; }}

QTableWidget {{ background: {c['table_bg']}; border: 1px solid {c['line']}; border-radius: 10px; gridline-color: {c['grid']};
    alternate-background-color: {c['table_bg']}; selection-background-color: {c['accent_soft']}; selection-color: {c['ink']};
    color: {c['ink']}; }}
QTableWidget QLineEdit {{ padding: 0 4px; border-radius: 0; }}
QHeaderView::section {{ background: {c['header']}; border: none; border-bottom: 1px solid {c['line']};
    border-right: 1px solid {c['grid']}; padding: {p(8)}px {p(6)}px; font-weight: bold; color: {c['header_ink']}; }}
QTableCornerButton::section {{ background: {c['header']}; border: none; }}

QFrame#card, QFrame#panel, QFrame#statCard {{ background: {c['surface']}; border: 1px solid {c['line']}; border-radius: 12px; }}
QLabel#statLabel {{ color: {c['muted']}; font-size: {p(12)}px; }}
QLabel#statValue {{ font-size: {p(24)}px; font-weight: bold; }}
QLabel#statValue[tone="accent"] {{ color: {c['accent_text']}; }}
QLabel#statValue[tone="success"] {{ color: {c['success']}; }}
QLabel#statValue[tone="danger"] {{ color: {c['danger']}; }}
QFrame#panelHead {{ border: none; border-bottom: 1px solid {c['line']}; }}
QFrame#vline {{ background: {c['line']}; max-width: 1px; min-width: 1px; border: none; }}

QFrame#pcRow {{ background: {c['surface']}; border: 1px solid {c['line']}; border-radius: 12px; }}
QFrame#pcRow[active="true"] {{ border: 1px solid {c['accent_line']}; }}
QLabel#pcNo {{ font-size: {p(18)}px; font-weight: bold; color: {c['accent_text']}; }}
QLabel#pcName {{ font-size: {p(15)}px; font-weight: bold; }}
QFrame#slot {{ background: {c['surface']}; border: 1px solid {c['line']}; border-radius: 9px; }}
QFrame#slot:hover {{ border-color: {c['faint']}; }}
QFrame#slot[empty="true"] {{ background: {c['slot_empty']}; border: 1px dashed {c['slot_empty_line']}; }}
QFrame#slot[empty="true"]:hover {{ border-color: {c['accent']}; background: {c['accent_soft2']}; }}
QFrame#slot[locked="true"] {{ background: {c['slot_locked']}; border: 1px solid {c['line']}; }}
QFrame#slot[selected="true"] {{ border: 2px solid {c['accent']}; background: {c['accent_soft2']}; }}
QLabel#slotNo {{ background: {c['slotno_bg']}; color: {c['header_ink']}; border-radius: {p(9)}px; font-size: {p(11)}px;
    font-weight: bold; min-width: {p(18)}px; max-width: {p(18)}px; min-height: {p(18)}px; max-height: {p(18)}px;
    qproperty-alignment: AlignCenter; }}
QLabel#owner {{ font-size: {p(14)}px; font-weight: bold; }}
QLabel#slotHint {{ color: {c['accent_text']}; font-size: {p(13)}px; }}
QLabel#slotLocked {{ color: {c['muted']}; font-size: {p(13)}px; }}
QLabel#slotChars {{ font-size: {p(12)}px; }}
QLabel#slotChars[empty="true"] {{ color: {c['faint']}; }}
QListWidget#pickList {{ background: {c['surface']}; border: 1px solid {c['line']}; border-radius: 10px; outline: 0; color: {c['ink']}; }}
QListWidget#pickList::item {{ padding: {p(8)}px {p(10)}px; border-bottom: 1px solid {c['grid']}; }}
QListWidget#pickList::item:selected {{ background: {c['accent_soft']}; color: {c['ink']}; }}
QListWidget#pickList::item:hover:!selected {{ background: {c['hover']}; }}

QScrollArea {{ border: none; background: transparent; }}
QWidget#scrollHost {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: {p(10)}px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: {p(10)}px; margin: 2px; }}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{ background: {c['scroll']}; border-radius: 4px; min-height: 30px; min-width: 30px; }}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{ background: {c['scroll_hover']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QStatusBar {{ background: {c['surface']}; border-top: 1px solid {c['line']}; color: {c['muted']}; }}
QMenu {{ background: {c['surface']}; border: 1px solid {c['line']}; border-radius: 8px; padding: 4px; color: {c['ink']}; }}
QMenu::item {{ padding: {p(7)}px {p(16)}px; border-radius: 6px; }}
QMenu::item:selected {{ background: {c['accent_soft']}; color: {c['ink']}; }}
QMenu::separator {{ height: 1px; background: {c['line']}; margin: 4px 6px; }}
QMessageBox, QInputDialog, QProgressDialog {{ background: {c['surface']}; }}
"""


def _palette() -> QPalette:
    c = THEMES[_state["theme"]]
    pal = QPalette()
    for role, key in ((QPalette.Window, "bg"), (QPalette.Base, "surface"), (QPalette.AlternateBase, "alt_row"),
                      (QPalette.Button, "surface"), (QPalette.WindowText, "ink"), (QPalette.Text, "ink"),
                      (QPalette.ButtonText, "ink"), (QPalette.ToolTipBase, "ink"), (QPalette.ToolTipText, "bg"),
                      (QPalette.Highlight, "accent"), (QPalette.PlaceholderText, "faint"), (QPalette.Mid, "line")):
        pal.setColor(role, QColor(c[key]))
    pal.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor(c["faint"]))
    pal.setColor(QPalette.Disabled, QPalette.WindowText, QColor(c["faint"]))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(c["faint"]))
    return pal


def apply_appearance(theme_name: str | None = None, zoom: float | None = None) -> None:
    """테마/배율을 바꾸고 앱 전체 스타일을 다시 입힌다. 화면 내용은 호출한 쪽이 다시 그린다."""
    if theme_name in THEMES:
        _state["theme"] = theme_name
    if zoom is not None:
        _state["scale"] = round(min(ZOOM_MAX, max(ZOOM_MIN, zoom)), 2)
    app = QApplication.instance()
    if not app:
        return
    app.setPalette(_palette())
    app.setFont(QFont("Malgun Gothic", 10 * _state["scale"]))
    app.setStyleSheet(build_style())


# ---------------------------------------------------------------- 작은 부품
def badge(text: str, kind: str) -> QLabel:
    bg, fg = THEMES[_state["theme"]]["badge"].get(kind, THEMES[_state["theme"]]["badge"]["info"])
    lab = QLabel(text)
    lab.setStyleSheet(f"background:{bg}; color:{fg}; border-radius:5px; padding:{px(2)}px {px(7)}px; "
                      f"font-size:{px(11)}px; font-weight:bold;")
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
    def __init__(self, title: str, tone: str = ""):
        super().__init__()
        self.setObjectName("statCard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(2)
        lay.addWidget(label(title, "statLabel"))
        self.value = label("0", "statValue")
        self.value.setProperty("tone", tone)
        lay.addWidget(self.value)

    def set(self, n: int) -> None:
        self.value.setText(f"{n:,}")


class ToggleSwitch(QAbstractButton):
    """밀어서 켜고 끄는 스위치."""

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self._pos = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.InOutCubic)
        self.toggled.connect(self._start)

    def sizeHint(self) -> QSize:
        return QSize(px(42), px(24))

    def _start(self, on: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def _get(self) -> float:
        return self._pos

    def _set(self, v: float) -> None:
        self._pos = v
        self.update()

    knob = Property(float, _get, _set)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        off, on = QColor(T("input_border")), QColor(T("accent"))
        track = QColor(
            round(off.red() + (on.red() - off.red()) * self._pos),
            round(off.green() + (on.green() - off.green()) * self._pos),
            round(off.blue() + (on.blue() - off.blue()) * self._pos))
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, 0, w, h), h / 2, h / 2)
        d = h - 6
        x = 3 + (w - d - 6) * self._pos
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QRectF(x, 3, d, d))


class GridDelegate(QStyledItemDelegate):
    """표 칸 그리기: 세로(열) 구분선은 가늘게, 가로(행) 구분선은 굵게 해서 계정끼리 확실히 나뉘어 보이게."""

    def paint(self, painter, option, index) -> None:
        super().paint(painter, option, index)
        r = option.rect
        painter.save()
        painter.fillRect(r.right(), r.top(), 1, r.height(), QColor(T("col_line")))
        painter.fillRect(r.left(), r.bottom() - 1, r.width(), 2, QColor(T("row_line")))
        painter.restore()


def style_table(table: QTableWidget) -> None:
    """모든 표에 같은 모양: 단색 배경 + 직접 그리는 구분선."""
    table.setShowGrid(False)
    table.setAlternatingRowColors(False)
    table.setItemDelegate(GridDelegate(table))


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
