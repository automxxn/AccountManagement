"""공통 디자인: 테마(라이트/다크), 화면 배율, 스타일시트, 작은 부품들."""
from __future__ import annotations

from PySide6.QtCore import Property, QEasingCurve, QEvent, QObject, QPropertyAnimation, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPalette
from PySide6.QtWidgets import (
    QAbstractButton, QApplication, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton, QStyle,
    QStyledItemDelegate, QStyleOptionViewItem, QTableWidget, QVBoxLayout, QWidget,
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
        "table_bg": "#F1F3F6", "row_line": "#CDD2DA", "col_line": "#E0E3E8", "group_line": "#8E97A5", "gap": "#FFFFFF",
        "check_border": "#8E97A5",
        "badge": {"ban": ("#FDECEC", "#B42318"), "info": ("#EEEFF1", "#3D4450"),
                  "worker": ("#F3EEFE", "#6D28D9")},
        "status": {"사용가능": "#1A7F37", "사용중": "#1D4ED8", "탈퇴": "#B42318", "정지": "#B42318", "인증불가": "#B54708"},
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
        "table_bg": "#181B20", "row_line": "#3A404A", "col_line": "#272B32", "group_line": "#5E6878", "gap": "#0F1114",
        "check_border": "#8B94A1",
        "badge": {"ban": ("#3A1F22", "#F87171"), "info": ("#2A2F37", "#C3C8CF"),
                  "worker": ("#2E2546", "#C4B5FD")},
        "status": {"사용가능": "#4ADE80", "사용중": "#7AA7FA", "탈퇴": "#F87171", "정지": "#F87171", "인증불가": "#FDB022"},
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


def _icon(name: str, svg: str) -> str:
    """스타일시트에 쓸 작은 그림 파일을 만들어 두고 경로를 돌려준다 (스타일시트는 파일 경로만 받음)."""
    import os
    from pathlib import Path
    d = Path(os.environ.get("APPDATA") or str(Path.home())) / "AccountManagement" / "ui"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{name}.svg"
    if not f.exists() or f.read_text(encoding="utf-8") != svg:
        f.write_text(svg, encoding="utf-8")
    return str(f).replace(chr(92), "/")


def _check_icon() -> str:
    return _icon("check", '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
                          '<path d="M3.5 8.5l3 3 6-7" fill="none" stroke="#FFFFFF" stroke-width="2.2" '
                          'stroke-linecap="round" stroke-linejoin="round"/></svg>')


def _chevron_icon(color: str) -> str:
    return _icon("chevron_" + color.strip("#"), '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
                 f'<path d="M4 6l4 4 4-4" fill="none" stroke="{color}" stroke-width="1.8" '
                 'stroke-linecap="round" stroke-linejoin="round"/></svg>')


def _chevron_up_icon(color: str) -> str:
    return _icon("chevron_up_" + color.strip("#"), '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
                 f'<path d="M4 10l4-4 4 4" fill="none" stroke="{color}" stroke-width="1.8" '
                 'stroke-linecap="round" stroke-linejoin="round"/></svg>')


def _calendar_icon(color: str) -> str:
    return _icon("calendar_" + color.strip("#"), '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
                 f'<rect x="2" y="3" width="12" height="11" rx="2" fill="none" stroke="{color}" stroke-width="1.5"/>'
                 f'<path d="M2 6.5h12M5 1.5v3M11 1.5v3" stroke="{color}" stroke-width="1.5" stroke-linecap="round"/>'
                 f'<rect x="4.5" y="8.5" width="2" height="2" fill="{color}"/>'
                 f'<rect x="9" y="8.5" width="2" height="2" fill="{color}"/></svg>')


def build_style() -> str:
    c = THEMES[_state["theme"]]
    p = px
    check = _check_icon()
    chevron = _chevron_icon(c["muted"])
    chevron_up = _chevron_up_icon(c["muted"])
    calendar = _calendar_icon(c["muted"])
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

QLineEdit, QComboBox, QSpinBox, QDateTimeEdit, QPlainTextEdit {{
    background: {c['surface']}; border: 1px solid {c['input_border']}; border-radius: 7px; padding: {p(6)}px {p(8)}px;
    color: {c['ink']}; selection-background-color: {c['selection']}; selection-color: {c['ink']}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDateTimeEdit:focus, QPlainTextEdit:focus {{ border: 1px solid {c['accent']}; }}
QLineEdit:disabled, QDateTimeEdit:disabled {{ background: {c['surface2']}; color: {c['faint']}; }}
QComboBox::drop-down, QDateTimeEdit::drop-down {{ border: none; width: {p(26)}px; }}
QComboBox::down-arrow {{ image: url({chevron}); width: {p(12)}px; height: {p(12)}px; }}
QSpinBox {{ padding: {p(2)}px {p(6)}px; padding-right: {p(26)}px; min-height: {p(30)}px; }}
QSpinBox::up-button, QSpinBox::down-button {{ subcontrol-origin: border; width: {p(24)}px; border: none;
    border-left: 1px solid {c['input_border']}; background: transparent; }}
QSpinBox::up-button {{ subcontrol-position: top right; border-top-right-radius: 7px; }}
QSpinBox::down-button {{ subcontrol-position: bottom right; border-bottom-right-radius: 7px;
    border-top: 1px solid {c['input_border']}; }}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: {c['hover']}; }}
QSpinBox::up-arrow {{ image: url({chevron_up}); width: {p(10)}px; height: {p(10)}px; }}
QSpinBox::down-arrow {{ image: url({chevron}); width: {p(10)}px; height: {p(10)}px; }}
QDateTimeEdit::down-arrow {{ image: url({calendar}); width: {p(16)}px; height: {p(16)}px; }}
QDateTimeEdit::down-arrow:disabled {{ image: none; }}
QCalendarWidget QWidget#qt_calendar_navigationbar {{ background: {c['surface2']}; }}
QCalendarWidget QToolButton {{ background: transparent; border: none; color: {c['ink']}; padding: {p(4)}px {p(8)}px;
    font-weight: bold; }}
QCalendarWidget QToolButton:hover {{ background: {c['hover']}; }}
QCalendarWidget QMenu {{ background: {c['surface']}; color: {c['ink']}; }}
QCalendarWidget QSpinBox {{ padding: 0 {p(4)}px; }}
QCalendarWidget QAbstractItemView {{ background: {c['surface']}; color: {c['ink']}; outline: 0;
    selection-background-color: {c['accent']}; selection-color: #FFFFFF; }}
QCalendarWidget QAbstractItemView:disabled {{ color: {c['faint']}; }}
QComboBox QAbstractItemView {{ border: 1px solid {c['line']}; background: {c['surface']}; color: {c['ink']};
    selection-background-color: {c['accent_soft']}; selection-color: {c['ink']}; }}
QCheckBox {{ spacing: {p(8)}px; }}
QCheckBox::indicator {{ width: {p(16)}px; height: {p(16)}px; border: 2px solid {c['check_border']}; border-radius: 4px;
    background: {c['surface']}; }}
QCheckBox::indicator:hover {{ border-color: {c['accent']}; }}
QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; image: url({check}); }}
QCheckBox::indicator:disabled {{ background: {c['surface2']}; border-color: {c['line']}; }}
QCheckBox::indicator:checked:disabled {{ background: {c['disabled_accent']}; border-color: {c['disabled_accent']}; }}
QCheckBox#checkButton {{ background: {c['surface']}; border: 1px solid {c['input_border']}; border-radius: 7px;
    padding: {p(6)}px {p(12)}px; color: {c['ink']}; }}
QCheckBox#checkButton:hover {{ background: {c['hover']}; }}
QCheckBox#checkButton:checked {{ background: {c['accent_soft']}; border-color: {c['accent']}; color: {c['accent_text']};
    font-weight: bold; }}

QTableWidget {{ background: {c['table_bg']}; border: 1px solid {c['line']}; border-radius: 10px; gridline-color: {c['grid']};
    alternate-background-color: {c['table_bg']}; selection-background-color: {c['accent_soft']}; selection-color: {c['ink']};
    color: {c['ink']}; }}
QTableWidget QLineEdit {{ padding: 0 4px; border-radius: 0; }}
QHeaderView::section {{ background: {c['header']}; border: none; border-bottom: 1px solid {c['line']};
    border-right: 1px solid {c['grid']}; padding: {p(8)}px {p(14)}px; font-weight: bold; color: {c['header_ink']}; }}
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
    """표 칸 그리기: 칸 안쪽 좌우 여백, 세로(열) 구분선은 가늘게, 가로(행) 구분선은 굵게."""

    PAD = 12  # 칸 안쪽 좌우 여백 (배율 적용 전)

    def sizeHint(self, option, index):
        s = super().sizeHint(option, index)
        s.setWidth(s.width() + 2 * px(self.PAD))
        return s

    def paint(self, painter, option, index) -> None:
        r = option.rect
        opt = QStyleOptionViewItem(option)
        if opt.state & QStyle.State_Selected:  # 선택 배경은 여백까지 칸 전체에
            painter.fillRect(r, QColor(T("accent_soft")))
            opt.state &= ~QStyle.State_Selected
        opt.state &= ~QStyle.State_HasFocus
        pad = px(self.PAD)
        opt.rect = r.adjusted(pad, 0, -pad, 0)
        super().paint(painter, opt, index)
        painter.save()
        painter.fillRect(r.right(), r.top(), 1, r.height(), QColor(T("col_line")))
        if index.data(Qt.UserRole + 1):  # 묶음(컴퓨터)의 마지막 줄 → 더 굵고 진하게
            painter.fillRect(r.left(), r.bottom() - 2, r.width(), 3, QColor(T("group_line")))
        else:
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


def app_icon():
    """프로그램 아이콘 (창 제목줄/작업표시줄)."""
    import base64
    from PySide6.QtGui import QIcon, QPixmap
    from .icon_data import ICON_PNG_B64
    pm = QPixmap()
    pm.loadFromData(base64.b64decode("".join(ICON_PNG_B64)), "PNG")
    return QIcon(pm)


def apply_native_icon(widget, exe_path: str | None = None) -> bool:
    """작업표시줄/제목줄 아이콘을 exe 안에 든 아이콘으로 직접 정한다 (Windows가 원하는 크기로).
    exe로 실행할 때만 (개발용 실행은 python.exe 아이콘이라 건너뜀). 성공하면 True."""
    import sys
    if sys.platform != "win32":
        return False
    from ..selfname import current_exe
    path = exe_path or (str(current_exe()) if getattr(sys, "frozen", False) else None)
    if not path:
        return False
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        user32.PrivateExtractIconsW.argtypes = [wintypes.LPCWSTR, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                                ctypes.POINTER(wintypes.HICON), ctypes.POINTER(wintypes.UINT),
                                                wintypes.UINT, wintypes.UINT]
        user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.SendMessageW.restype = wintypes.LPARAM
        hwnd = int(widget.winId())
        ok = False
        # ICON_BIG(1) = 작업표시줄/Alt+Tab, ICON_SMALL(0) = 제목줄. 크기는 지금 화면 배율 기준 시스템 값
        for which, metric in ((1, 11), (0, 49)):   # SM_CXICON, SM_CXSMICON
            size = user32.GetSystemMetricsForDpi(metric, user32.GetDpiForWindow(hwnd)) \
                if hasattr(user32, "GetDpiForWindow") else user32.GetSystemMetrics(metric)
            hicon = wintypes.HICON()
            if user32.PrivateExtractIconsW(path, 0, size, size, ctypes.byref(hicon), None, 1, 0) == 1 and hicon:
                user32.SendMessageW(hwnd, 0x0080, which, ctypes.cast(hicon, ctypes.c_void_p).value)  # WM_SETICON
                ok = True
        return ok
    except Exception:
        return False


def refresh_shell_icons_once(version: str) -> None:
    """새 버전으로 처음 켰을 때 한 번만 Windows 아이콘 캐시를 새로 고친다
    (아이콘이 없던 예전 버전 exe의 빈 아이콘이 작업표시줄에 남아 있는 경우)."""
    import sys
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    try:
        from .connect import settings
        s = settings()
        if s.value("icon_refreshed_for", "") == version:
            return
        import ctypes
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)   # SHCNE_ASSOCCHANGED
        s.setValue("icon_refreshed_for", version)
    except Exception:
        pass


def copy_text(text: str) -> None:
    QApplication.clipboard().setText(text)


def zoom_rows(nav, base: int) -> int:
    """표 확대에 맞춘 줄 높이 (칸 안 버튼·상자가 들어가게 너무 작아지지는 않게)."""
    return px(base * max(nav.zoom if nav else 1.0, 0.85))


def fit_columns(table, mins: dict | None = None, caps: dict | None = None) -> None:
    """열 너비를 제목과 내용이 잘리지 않게 맞춘다.

    제목(굵은 글씨 + 좌우 여백)과 각 칸의 글자(여러 줄이면 가장 긴 줄)·칸 안 위젯의 크기 중 가장 큰 값.
    mins/caps = {열 번호: 최소/최대 px(배율 전)} — 아주 긴 글(결과, 로그 등)은 caps로 막고 툴팁으로 보이게 한다.
    """
    from PySide6.QtGui import QFont, QFontMetrics
    hdr = table.horizontalHeader()
    table.ensurePolished()   # 확대/축소로 바뀐 글자 크기를 반영
    hf = QFont(table.font())
    hf.setBold(True)
    hfm = QFontMetrics(hf)
    cfm = QFontMetrics(table.font())
    for c in range(table.columnCount()):
        if table.isColumnHidden(c):
            continue
        head = table.horizontalHeaderItem(c)
        w = max(hfm.horizontalAdvance(line) for line in (head.text() if head else "").split("\n")) + px(34)
        for r in range(table.rowCount()):
            it = table.item(r, c)
            if it is not None and it.text():
                w = max(w, max(cfm.horizontalAdvance(line) for line in it.text().split("\n")) + px(40))
            cw = table.cellWidget(r, c)
            if cw is not None:
                w = max(w, cw.sizeHint().width() + px(6))
        zoom = getattr(table, "_zoom", 1.0)
        if mins and c in mins:
            w = max(w, px(mins[c] * zoom))
        if caps and c in caps:
            w = min(w, px(caps[c] * zoom))
        table.setColumnWidth(c, w)
    hdr.setMinimumSectionSize(px(36))


class _WheelGuard(QObject):
    """마우스가 지나가다 휠을 굴려도 값이 바뀌지 않게: 칸을 눌러서 선택(포커스)했을 때만 휠이 먹힌다."""

    def eventFilter(self, obj, ev) -> bool:
        if ev.type() == QEvent.Wheel and not obj.hasFocus():
            ev.ignore()
            return True
        return False


_wheel_guard = _WheelGuard()


def wheel_only_when_focused(*widgets) -> None:
    for w in widgets:
        w.setFocusPolicy(Qt.StrongFocus)
        w.installEventFilter(_wheel_guard)


def run_safely(parent: QWidget, fn, *args) -> bool:
    """저장소 작업을 실행하고, 오류가 나면 알림창을 띄운다. 성공하면 True."""
    try:
        fn(*args)
        return True
    except RepoError as e:
        QMessageBox.warning(parent, "확인 필요", str(e))
        return False
