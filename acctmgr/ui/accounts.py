"""계정 화면: 전체 계정 표, 상태별 필터, 추가/수정/삭제."""
from __future__ import annotations

from collections import Counter

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..db import Repository
from ..models import STATUS_AVAILABLE, STATUS_IN_USE, Account, norm_login
from .common import button, copy_text, muted, page_header, px, run_safely, style_table
from .dialogs import AccountDialog, CharacterDialog
from .sheet import ACC_CHAR, ACC_WORKER, ACCOUNT_COLUMNS, ID_ROLE, SheetNav, cap_widths, fill_account_cells

COLUMNS = ACCOUNT_COLUMNS
COL_WORKER = ACC_WORKER  # 담당은 맨 오른쪽
CHAR_COLS = ACC_CHAR     # 누르면 캐릭터 창
FILTERS = ["전체", STATUS_AVAILABLE, STATUS_IN_USE, "메랜정지", "플래닛정지", "탈퇴", "중복 의심", "삭제 요청"]


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
        # 관리자: 근무자의 삭제 요청 알림
        self.req_banner = QLabel()
        self.req_banner.setObjectName("hintBox")
        self.req_banner.setTextFormat(Qt.RichText)
        self.req_banner.setCursor(Qt.PointingHandCursor)
        self.req_banner.setVisible(False)
        self.req_banner.mousePressEvent = lambda e: self.filter_btns["삭제 요청"].click()

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

        style_table(self.table)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(px(36))
        self.table.horizontalHeader().setSortIndicator(-1, Qt.AscendingOrder)  # 처음엔 상태순(사용중 → 사용가능 → 정지 → 탈퇴)
        self.table.setSortingEnabled(True)
        self.table.setWordWrap(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setStretchLastSection(True)
        hh.setDefaultAlignment(Qt.AlignCenter)  # 열 제목은 가운데
        self.table.cellClicked.connect(self._cell_clicked)
        self.table.cellDoubleClicked.connect(lambda r, c: None if c in CHAR_COLS else self._edit())
        self.table.setMouseTracking(True)
        self.table.cellEntered.connect(
            lambda r, c: None if self.nav.drag else
            self.table.viewport().setCursor(Qt.PointingHandCursor if c in CHAR_COLS else Qt.ArrowCursor))
        self.nav = SheetNav(self.table, "table_zoom", self._render)  # Ctrl+휠 = 표 크기, 휠 누르고 끌기 = 이동

        brow = QHBoxLayout()
        brow.setSpacing(6)
        self.count_label = muted()
        brow.addWidget(self.count_label)
        brow.addSpacing(10)
        self.tzoom_btn = button("", "ghost", lambda: self.nav.set(1.0), "누르면 100%로")
        brow.addWidget(self.tzoom_btn)
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
            brow.addWidget(button("삭제" if me.is_admin else "삭제 요청", "danger", self._delete))
        if me.is_admin and repo.is_cloud:
            self.approve_btn = button("삭제 승인", "danger", self._approve, "근무자가 요청한 삭제를 확정해요 (되돌릴 수 없음)")
            self.reject_btn = button("삭제 거절", "", self._reject, "요청을 취소해서 근무자 화면에 다시 보이게 해요")
            brow.addWidget(self.approve_btn)
            brow.addWidget(self.reject_btn)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        lay.setSpacing(14)
        lay.addWidget(header)
        lay.addWidget(self.req_banner)
        lay.addLayout(frow)
        lay.addWidget(self.table, 1)
        lay.addLayout(brow)
        self.dups: set = set()
        self.nav.apply()

    def restyle(self) -> None:
        self.nav.apply()

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
            "삭제 요청": sum(1 for a in self.accs if a.delete_requested),
        }
        self.filter_btns["삭제 요청"].setVisible(self.repo.me.is_admin and self.repo.is_cloud)
        req = n["삭제 요청"]
        self.req_banner.setVisible(bool(req) and self.repo.me.is_admin)
        self.req_banner.setText(f"<b>근무자가 삭제를 요청한 계정이 {req}개 있어요.</b> "
                                f"눌러서 확인하고, 계정을 고른 뒤 아래 <b>삭제 승인</b> 또는 <b>삭제 거절</b>을 누르세요.")
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
            "삭제 요청": lambda a: a.delete_requested,
        }.get(f, lambda a: True)
        out = [a for a in self.accs if test(a) and (not q or q in a.search_text())]
        # 사용중 → 사용가능 → 탈퇴 순, 그 안에서는 명의자순
        out.sort(key=lambda a: (0 if a.location else (2 if a.withdrawn else 1), a.owner, a.login_id))
        return out

    def _render(self) -> None:
        rows = self._visible()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        bold = self.nav.bold_font()
        for r, a in enumerate(rows):
            fill_account_cells(self.table, r, 0, a, self.show_pw, self.worker_names, bold)
        self.table.setSortingEnabled(True)
        cap_widths(self.table, 0, self.nav.zoom)
        self.tzoom_btn.setText(self.nav.label())
        self.count_label.setText(f"{len(rows)}개 표시 · 캐릭터 칸을 누르면 캐릭터 창이 열려요")

    def _cell_clicked(self, r: int, c: int) -> None:
        if c not in CHAR_COLS:
            return
        it = self.table.item(r, 0)
        a = next((x for x in self.accs if it and x.id == it.data(ID_ROLE)), None)
        if a and CharacterDialog(self.repo, a, CHAR_COLS[c], self).exec():
            self.refresh()
            self.changed.emit()

    def _current(self) -> Account | None:
        r = self.table.currentRow()
        if r < 0:
            return None
        it = self.table.item(r, 0)
        aid = it.data(ID_ROLE) if it else None
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
        if self.repo.is_cloud and not self.repo.me.is_admin:
            msg = (f"[{a.provider}] {a.login_id} ({a.owner}) 계정 삭제를 요청할까요?\n"
                   "목록에서는 바로 사라지고, 관리자가 승인하면 완전히 지워져요.\n"
                   "관리자가 거절하면 다시 나타나요.")
            if QMessageBox.question(self, "삭제 요청", msg) == QMessageBox.Yes:
                if run_safely(self, self.repo.delete_account, a.id):
                    self.refresh()
                    self.changed.emit()
            return
        msg = f"[{a.provider}] {a.login_id} ({a.owner}) 계정을 삭제할까요?\n삭제하면 되돌릴 수 없어요."
        if a.location:
            msg += f"\n{a.location.text()}에서도 빠져요."
        msg += "\n\n그만 쓰는 계정이면 삭제 대신 '탈퇴'로 표시하는 방법도 있어요."
        if QMessageBox.question(self, "계정 삭제", msg) == QMessageBox.Yes:
            if run_safely(self, self.repo.delete_account, a.id):
                self.refresh()
                self.changed.emit()

    def _approve(self) -> None:
        a = self._current()
        if not a or not a.delete_requested:
            QMessageBox.information(self, "삭제 승인", "'삭제 요청' 상태인 계정을 고르세요.")
            return
        if QMessageBox.question(self, "삭제 승인",
                                f"[{a.provider}] {a.login_id} ({a.owner}) 계정을 완전히 삭제할까요?\n되돌릴 수 없어요.") \
                == QMessageBox.Yes and run_safely(self, self.repo.approve_delete, a.id):
            self.refresh()
            self.changed.emit()

    def _reject(self) -> None:
        a = self._current()
        if not a or not a.delete_requested:
            QMessageBox.information(self, "삭제 거절", "'삭제 요청' 상태인 계정을 고르세요.")
            return
        if run_safely(self, self.repo.reject_delete, a.id):
            QMessageBox.information(self, "삭제 거절",
                                    "삭제 요청을 거절했어요. 근무자 화면에 다시 보여요.\n"
                                    "원래 들어 있던 자리가 비어 있으면 그 자리로 되돌려 놓았어요.")
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
