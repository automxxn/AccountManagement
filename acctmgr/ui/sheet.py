"""계정 화면과 작업장이 같이 쓰는 시트(표) 부품.

- ACCOUNT_COLUMNS: 계정 정보 열 (두 화면이 같은 순서로 보여준다, 게임 목록에 따라 바뀜)
- fill_account_cells: 한 줄에 계정 정보를 채운다
- SheetNav: Ctrl + 휠 = 표 크기, 휠 버튼 누르고 끌기 = 보는 위치 이동
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QAbstractItemView, QTableWidget, QTableWidgetItem

from ..models import GAMES, Account
from .common import T, px, status_color
from .connect import settings

# 계정 정보 열은 게임 목록(GAMES)에 따라 달라진다. 다른 화면이 같은 객체를 보고 있으므로 내용만 바꾼다.
ACCOUNT_COLUMNS: list[str] = []
ACC_CHAR: dict[int, str] = {}   # 열 번호 → 게임 (닉/레벨직업 칸, 누르면 캐릭터 창)
ACC_BAN: dict[int, str] = {}    # 열 번호 → 게임 (정지 칸)
ACC_WIDE: list[int] = []        # 너무 넓어지지 않게 자를 열


def rebuild_columns() -> None:
    """게임 목록이 바뀌면 다시 계산: 상태 … 메월코드 | 게임별 닉, 레벨/직업 | 게임별 정지 | 위치 | 비고"""
    cols = ["상태", "명의자", "연락처", "유형", "아이디", "비밀번호", "메월코드"]
    ACC_CHAR.clear()
    ACC_BAN.clear()
    for g in GAMES:
        ACC_CHAR[len(cols)] = g
        cols.append(f"{g}닉")
        ACC_CHAR[len(cols)] = g
        cols.append(f"{g} 레벨/직업")
    for g in GAMES:
        ACC_BAN[len(cols)] = g
        cols.append(f"{g}정지")
    cols += ["위치", "비고"]
    ACCOUNT_COLUMNS[:] = cols
    ACC_WIDE[:] = list(ACC_CHAR) + [len(cols) - 1]


rebuild_columns()

ID_ROLE = Qt.UserRole          # 칸에 붙여 두는 계정 id
GROUP_END_ROLE = Qt.UserRole + 1  # 이 줄 아래에 묶음(컴퓨터) 구분선을 굵게


def ban_text(ban) -> str:
    if not ban.active():
        return ""
    return f"정지 ~{ban.until}" if ban.until else "정지 (기한 없음)"


def _nick(cs) -> str:
    if not cs:
        return ""
    return cs[0].nickname + (f"  (대표 · 외 {len(cs) - 1})" if len(cs) > 1 else "")


def status_text(a: Account) -> str:
    return "삭제 요청" if a.delete_requested else a.status


def account_values(a: Account, show_pw: bool, worker_names: dict) -> list[str]:
    vals = ["● " + status_text(a), a.owner, a.contact, a.provider, a.login_id,
            a.password if show_pw else ("●" * 6 if a.password else ""), a.tag]
    for g in GAMES:
        cs = a.chars(g)
        vals += [_nick(cs), cs[0].lj if cs else ""]
    for g in GAMES:
        vals.append(ban_text(a.ban(g)))
    vals += [a.location.text() if a.location else "", a.note.replace("\n", " / ")]
    assert len(vals) == len(ACCOUNT_COLUMNS)
    return vals


def fill_account_cells(table: QTableWidget, row: int, offset: int, a: Account, show_pw: bool,
                       worker_names: dict, bold: QFont, extra_role: dict | None = None) -> None:
    """row 줄의 offset 열부터 계정 정보를 채운다."""
    unusable = a.withdrawn or a.auth_blocked or a.delete_requested
    for i, v in enumerate(account_values(a, show_pw, worker_names)):
        it = QTableWidgetItem(v)
        it.setData(ID_ROLE, a.id)
        for role, val in (extra_role or {}).items():
            it.setData(role, val)
        color = None
        if i == 0:
            color = T("danger") if a.delete_requested else status_color(a.status)
            it.setFont(bold)
        elif unusable:
            color = T("faint")
        elif i in ACC_BAN and v:
            color = T("danger")
        elif i in ACC_CHAR:
            cs = a.chars(ACC_CHAR[i])
            if len(cs) > 1:
                color = T("accent_text")
            it.setToolTip("\n".join(("★ " if k == 0 else "   ") + ch.text() for k, ch in enumerate(cs))
                          + ("\n\n눌러서 캐릭터 추가/수정/대표 변경" if cs else "눌러서 캐릭터 추가"))
        if color:
            it.setForeground(QColor(color))
        if a.withdrawn:
            it.setToolTip("탈퇴한 계정 (작업장에 넣을 수 없어요)")
        elif a.auth_blocked:
            it.setToolTip("인증불가 계정 (인증이 다시 되면 수정 창에서 '인증불가'를 풀어 주세요)")
        elif a.all_banned and i == 0:
            it.setToolTip("모든 게임이 정지된 계정")
        if a.delete_requested:
            it.setToolTip(f"근무자가 삭제를 요청했어요 ({a.delete_requested_at}). 아래 '삭제 승인'/'삭제 거절'로 처리하세요.")
        table.setItem(row, offset + i, it)


class SheetNav(QObject):
    """표 전용 조작. Ctrl + 휠 = 표 크기(따로 저장), 휠 버튼 누른 채 움직이기 = 보는 위치 이동."""

    MIN, MAX, STEP = 0.6, 2.0, 0.1

    def __init__(self, table: QTableWidget, settings_key: str, on_change, extra_css: str = ""):
        super().__init__(table)
        self.table = table
        self.extra_css = extra_css
        self.key = settings_key
        self.on_change = on_change
        self.drag = None
        try:
            self.zoom = float(settings().value(settings_key, 1.0))
        except (TypeError, ValueError):
            self.zoom = 1.0
        table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        vp = table.viewport()
        vp.installEventFilter(self)
        table.destroyed.connect(lambda *_: self.__dict__.pop("table", None))
        self._style()   # 저장해 둔 표 크기를 바로 적용 (줄 높이·열 너비는 표를 그릴 때 맞춤)

    def font_px(self) -> int:
        return px(13 * self.zoom)

    def bold_font(self) -> QFont:
        f = QFont(self.table.font())
        f.setPixelSize(self.font_px())
        f.setBold(True)
        return f

    def label(self) -> str:
        return f"표 크기 {round(self.zoom * 100)}%  ·  Ctrl+휠로 조절, 휠 누르고 끌면 이동"

    def _style(self) -> None:
        self.table._zoom = self.zoom
        fs = self.font_px()
        self.table.setStyleSheet(f"QTableWidget {{ font-size: {fs}px; }} QHeaderView::section {{ font-size: {fs}px; }}"
                                 + self.extra_css)

    def apply(self) -> None:
        self._style()
        self.table.verticalHeader().setDefaultSectionSize(px(36 * self.zoom))
        self.on_change()

    def set(self, z: float) -> None:
        self.zoom = round(min(self.MAX, max(self.MIN, z)), 2)
        settings().setValue(self.key, self.zoom)
        self.apply()

    def eventFilter(self, obj, ev) -> bool:
        # 창을 닫거나 프로그램을 끄는 중에는 표(또는 이 객체의 파이썬 쪽 정보)가 먼저 없어진 채로
        # 이벤트가 올 수 있다 → 그때는 아무것도 하지 않는다
        table = self.__dict__.get("table")
        if table is None:
            return False
        try:
            if obj is not table.viewport():
                return False
            return self._handle(obj, ev)
        except (RuntimeError, AttributeError):
            return False

    def _handle(self, obj, ev) -> bool:
        t = ev.type()
        if t == QEvent.Wheel and ev.modifiers() & Qt.ControlModifier:
            self.set(self.zoom + (self.STEP if ev.angleDelta().y() > 0 else -self.STEP))
            return True
        # 휠 버튼을 꾹 누른 채 움직이면 보는 위치를 상하좌우로 옮긴다 (표 밖으로 나가도 계속)
        if t == QEvent.MouseButtonPress and ev.button() == Qt.MiddleButton:
            self.drag = (ev.globalPosition().toPoint(), self.table.horizontalScrollBar().value(),
                         self.table.verticalScrollBar().value())
            obj.setCursor(Qt.SizeAllCursor)
            obj.grabMouse()
            return True
        if t == QEvent.MouseMove and self.drag:
            if not (ev.buttons() & Qt.MiddleButton):  # 버튼 뗀 신호를 놓친 경우
                self._end(obj)
                return False
            start, h0, v0 = self.drag
            d = ev.globalPosition().toPoint() - start
            self.table.horizontalScrollBar().setValue(h0 - d.x())
            self.table.verticalScrollBar().setValue(v0 - d.y())
            return True
        if t == QEvent.MouseButtonRelease and ev.button() == Qt.MiddleButton and self.drag:
            self._end(obj)
            return True
        return False

    def _end(self, obj) -> None:
        self.drag = None
        obj.releaseMouse()
        obj.setCursor(Qt.ArrowCursor)


def cap_widths(table: QTableWidget, offset: int, zoom: float) -> None:
    """내용에 맞춰 너비를 정하되 긴 열(캐릭터, 비고)은 너무 넓어지지 않게."""
    table.resizeColumnsToContents()
    for c in ACC_WIDE:
        table.setColumnWidth(offset + c, min(table.columnWidth(offset + c) + 8, px(220 * zoom)))
