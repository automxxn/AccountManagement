"""계정 화면: 전체 계정 표, 상태별 필터, 추가/수정/삭제."""
from __future__ import annotations

from collections import Counter

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QHBoxLayout, QHeaderView, QLineEdit, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..db import Repository
from ..models import STATUS_AVAILABLE, STATUS_BANNED, STATUS_IN_USE, STATUS_WITHDRAWN, Account, norm_login
from .common import COLORS, button, copy_text, muted, page_header, run_safely
from .dialogs import AccountDialog, CharacterDialog

COLUMNS = ["상태", "명의자", "연락처", "유형", "아이디", "비밀번호", "메월코드",
           "메랜닉", "메랜 레벨/직업", "플래닛닉", "플래닛 레벨/직업", "메랜정지", "플래닛정지",
           "위치", "담당", "비고"]
COL_WORKER = 14
CHAR_COLS = {7: "메랜", 8: "메랜", 9: "플래닛", 10: "플래닛"}  # 누르면 캐릭터 창
WIDE_COLS = (7, 8, 9, 10, 15)
FILTERS = ["전체", STATUS_AVAILABLE, STATUS_IN_USE, "메랜정지", "플래닛정지", "탈퇴", "중복 의심"]
GREY = "#9AA0A8"
RED = "#B42318"
BLUE = "#1D4ED8"


def ban_text(ban) -> str:
    if not ban.active():
        return ""
    return f"정지 ~{ban.until}" if ban.until else "정지 (기한 없음)"


class AccountsTab(QWidget):
    changed = Signal()

    def __init__(self, repo: Repository):
        super().__init__()
        self.setObjectName("page")
        self.repo = repo
        self.accs: list[Account] = []
        self.show_pw = False
        me = repo.me

        right = []
        if me.can("can_add_account"):
            right.append(button("+ 계정 추가", "primary", self._add))
        header = page_header("계정", "가지고 있는 모든 계정과 지금 어디에 들어 있는지 보여줘요", right)

        self.filter_group = QButtonGroup(self)
        self.filter_btns: dict[str, QPushButton] = {}
        frow = QHBoxLayout()
        frow.setSpacing(6)
        for i, name in enumerate(FILTERS):
            b = button(name, "chip")
            b.setCheckable(True)
            if i == 0:
                b.setChecked(True)
            self.filter_group.addButton(b, i)
            self.filter_btns[name] = b
            frow.addWidget(b)
        self.filter_group.idClicked.connect(lambda _: self._render())
        frow.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("명의자, 아이디, 닉네임, 비고로 찾기")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(300)
        self.search.textChanged.connect(self._render)
        frow.addWidget(self.search)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.horizontalHeader().setSortIndicator(-1, Qt.AscendingOrder)  # 처음엔 상태순(사용중 → 사용가능 → 정지 → 탈퇴)
        self.table.setSortingEnabled(True)
        self.table.setWordWrap(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setStretchLastSection(True)
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.cellClicked.connect(self._cell_clicked)
        self.table.cellDoubleClicked.connect(lambda r, c: None if c in CHAR_COLS else self._edit())
        self.table.setMouseTracking(True)
        self.table.cellEntered.connect(
            lambda r, c: self.table.viewport().setCursor(Qt.PointingHandCursor if c in CHAR_COLS else Qt.ArrowCursor))

        brow = QHBoxLayout()
        brow.setSpacing(6)
        self.count_label = muted()
        brow.addWidget(self.count_label)
        brow.addStretch(1)
        self.worker_names: dict = {}
        self.show_worker = repo.is_cloud and me.is_admin
        self.table.setColumnHidden(COL_WORKER, not self.show_worker)
        brow.addWidget(button("아이디 복사", "", lambda: self._copy("id")))
        brow.addWidget(button("비번 복사", "", lambda: self._copy("pw")))
        self.pw_btn = button("비번 보기")
        self.pw_btn.setCheckable(True)
        self.pw_btn.toggled.connect(self._toggle_pw)
        brow.addWidget(self.pw_btn)
        brow.addSpacing(12)
        brow.addWidget(button("수정" if me.can("can_edit_account") else "정보 보기", "", self._edit))
        if me.can("can_delete_account"):
            brow.addWidget(button("삭제", "danger", self._delete))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        lay.setSpacing(14)
        lay.addWidget(header)
        lay.addLayout(frow)
        lay.addWidget(self.table, 1)
        lay.addLayout(brow)

    def refresh(self) -> None:
        self.accs = self.repo.list_accounts()
        if self.show_worker:
            self.worker_names = {w.id: w.display_name for w in self.repo.list_workers()}
        keys = Counter(norm_login(a.login_id) for a in self.accs)
        self.dups = {a.id for a in self.accs if keys[norm_login(a.login_id)] > 1}
        n = {
            "전체": len(self.accs),
            STATUS_AVAILABLE: sum(1 for a in self.accs if a.assignable),
            STATUS_IN_USE: sum(1 for a in self.accs if a.location),
            "메랜정지": sum(1 for a in self.accs if a.mr_ban.active()),
            "플래닛정지": sum(1 for a in self.accs if a.pl_ban.active()),
            "탈퇴": sum(1 for a in self.accs if a.withdrawn),
            "중복 의심": len(self.dups),
        }
        for name, b in self.filter_btns.items():
            b.setText(f"{name} {n[name]}")
        self._render()

    def _visible(self) -> list[Account]:
        f = FILTERS[self.filter_group.checkedId()]
        q = self.search.text().strip().lower()
        test = {
            STATUS_AVAILABLE: lambda a: a.assignable,
            STATUS_IN_USE: lambda a: bool(a.location),
            "메랜정지": lambda a: a.mr_ban.active(),
            "플래닛정지": lambda a: a.pl_ban.active(),
            "탈퇴": lambda a: a.withdrawn,
            "중복 의심": lambda a: a.id in self.dups,
        }.get(f, lambda a: True)
        out = [a for a in self.accs if test(a) and (not q or q in a.search_text())]
        # 사용중 → 사용가능 → 탈퇴 순, 그 안에서는 명의자순
        out.sort(key=lambda a: (0 if a.location else (2 if a.withdrawn else 1), a.owner, a.login_id))
        return out

    def _render(self) -> None:
        rows = self._visible()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for r, a in enumerate(rows):
            status = "-" if a.withdrawn else ("● " + a.status)
            mr, pl = a.chars("메랜"), a.chars("플래닛")

            def nick(cs):
                if not cs:
                    return ""
                return cs[0].nickname + (f"  (대표 · 외 {len(cs) - 1})" if len(cs) > 1 else "")

            vals = [status, a.owner, a.contact, a.provider, a.login_id,
                    a.password if self.show_pw else ("●" * 6 if a.password else ""), a.tag,
                    nick(mr), mr[0].level_job if mr else "", nick(pl), pl[0].level_job if pl else "",
                    ban_text(a.mr_ban), ban_text(a.pl_ban),
                    a.location.text() if a.location else "",
                    self.worker_names.get(a.worker_id, "") if a.worker_id else "",
                    ("[탈퇴] " if a.withdrawn else "") + a.note.replace("\n", " / ")]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                it.setData(Qt.UserRole, a.id)
                color = None
                if a.withdrawn:
                    color = GREY
                elif c == 0:
                    color = COLORS[a.status][1]
                    f = it.font()
                    f.setBold(True)
                    it.setFont(f)
                elif c in (11, 12) and v:
                    color = RED
                elif c in CHAR_COLS:
                    cs = mr if CHAR_COLS[c] == "메랜" else pl
                    if len(cs) > 1:
                        color = BLUE
                    it.setToolTip("\n".join(("★ " if i == 0 else "   ") + ch.text() for i, ch in enumerate(cs))
                                  + ("\n\n눌러서 캐릭터 추가/수정/대표 변경" if cs else "눌러서 캐릭터 추가"))
                if color:
                    it.setForeground(QColor(color))
                if a.withdrawn:
                    it.setToolTip("탈퇴한 계정 (작업장에 넣을 수 없어요)")
                self.table.setItem(r, c, it)
        self.table.setSortingEnabled(True)
        self.table.resizeColumnsToContents()
        for c in WIDE_COLS:
            self.table.setColumnWidth(c, min(self.table.columnWidth(c) + 8, 220))
        self.count_label.setText(f"{len(rows)}개 표시 · 캐릭터 칸을 누르면 캐릭터 창이 열려요")

    def _cell_clicked(self, r: int, c: int) -> None:
        if c not in CHAR_COLS:
            return
        it = self.table.item(r, 0)
        a = next((x for x in self.accs if it and x.id == it.data(Qt.UserRole)), None)
        if a and CharacterDialog(self.repo, a, CHAR_COLS[c], self).exec():
            self.refresh()
            self.changed.emit()

    def _current(self) -> Account | None:
        r = self.table.currentRow()
        if r < 0:
            return None
        it = self.table.item(r, 0)
        aid = it.data(Qt.UserRole) if it else None
        return next((a for a in self.accs if a.id == aid), None)

    def _add(self) -> None:
        if AccountDialog(self.repo, None, self).exec():
            self.refresh()
            self.changed.emit()

    def _edit(self) -> None:
        a = self._current()
        if not a:
            return
        if AccountDialog(self.repo, a, self).exec():
            self.refresh()
            self.changed.emit()

    def _delete(self) -> None:
        a = self._current()
        if not a:
            return
        msg = f"[{a.provider}] {a.login_id} ({a.owner}) 계정을 삭제할까요?\n삭제하면 되돌릴 수 없어요."
        if a.location:
            msg += f"\n{a.location.text()}에서도 빠져요."
        msg += "\n\n그만 쓰는 계정이면 삭제 대신 '탈퇴'로 표시하는 방법도 있어요."
        if QMessageBox.question(self, "계정 삭제", msg) == QMessageBox.Yes:
            if run_safely(self, self.repo.delete_account, a.id):
                self.refresh()
                self.changed.emit()

    def _copy(self, what: str) -> None:
        a = self._current()
        if a:
            copy_text(a.login_id if what == "id" else a.password)

    def _toggle_pw(self, on: bool) -> None:
        self.show_pw = on
        self.pw_btn.setText("비번 가리기" if on else "비번 보기")
        self._render()
