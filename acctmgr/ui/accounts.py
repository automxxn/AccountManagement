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
from .dialogs import AccountDialog

COLUMNS = ["상태", "명의자", "연락처", "유형", "아이디", "비밀번호", "메월닉", "메랜 캐릭터", "플래닛 캐릭터",
           "정지", "위치", "담당", "비고"]
COL_WORKER = 11
FILTERS = ["전체", STATUS_AVAILABLE, STATUS_IN_USE, "정지 있음", STATUS_WITHDRAWN, "중복 의심"]


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
        self.table.doubleClicked.connect(lambda _: self._edit())

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
        counts = Counter(a.status for a in self.accs)
        self.filter_btns["전체"].setText(f"전체 {len(self.accs)}")
        for st in (STATUS_AVAILABLE, STATUS_IN_USE, STATUS_WITHDRAWN):
            self.filter_btns[st].setText(f"{st} {counts[st]}")
        self.filter_btns["정지 있음"].setText(f"정지 있음 {sum(1 for a in self.accs if a.ban_labels())}")
        self.filter_btns["중복 의심"].setText(f"중복 의심 {len(self.dups)}")
        self._render()

    def _visible(self) -> list[Account]:
        f = FILTERS[self.filter_group.checkedId()]
        q = self.search.text().strip().lower()
        out = []
        for a in self.accs:
            if f in (STATUS_AVAILABLE, STATUS_IN_USE, STATUS_WITHDRAWN) and a.status != f:
                continue
            if f == "정지 있음" and not a.ban_labels():
                continue
            if f == "중복 의심" and a.id not in self.dups:
                continue
            if q and q not in a.search_text():
                continue
            out.append(a)
        order = {STATUS_IN_USE: 0, STATUS_AVAILABLE: 1, STATUS_BANNED: 2, STATUS_WITHDRAWN: 3}
        out.sort(key=lambda a: (order.get(a.status, 9), a.owner, a.login_id))
        return out

    def _render(self) -> None:
        rows = self._visible()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for r, a in enumerate(rows):
            vals = [a.status, a.owner, a.contact, a.provider, a.login_id,
                    a.password if self.show_pw else ("●" * 6 if a.password else ""),
                    a.tag, a.char_summary("메랜"), a.char_summary("플래닛"), ", ".join(a.ban_labels()),
                    a.location.text() if a.location else "",
                    self.worker_names.get(a.worker_id, "") if a.worker_id else "",
                    a.note.replace("\n", " / ")]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(("● " + v) if c == 0 else v)
                it.setData(Qt.UserRole, a.id)
                if c == 0:
                    it.setForeground(QColor(COLORS.get(a.status, COLORS[STATUS_WITHDRAWN])[1]))
                    f = it.font()
                    f.setBold(True)
                    it.setFont(f)
                if c == 9 and v:
                    it.setForeground(QColor(COLORS[STATUS_BANNED][1]))
                self.table.setItem(r, c, it)
        self.table.setSortingEnabled(True)
        self.table.resizeColumnsToContents()
        for c in (7, 8, 12):
            self.table.setColumnWidth(c, min(self.table.columnWidth(c), 240))
        self.count_label.setText(f"{len(rows)}개 표시")

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
