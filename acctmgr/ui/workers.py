"""근무자 관리 탭 (클라우드, 총관리자와 관리자): 가입 승인, 역할, 팀, 권한 켜고 끄기.

- 총관리자: 모든 사람의 역할(관리자/근무자/승인 대기), 팀, 권한, 관리자의 '팀 배정' 권한을 정한다.
- 관리자: 맡은 팀의 근무자만. 자기가 가진 권한까지만 켜고 끌 수 있다.
          가입 승인과 팀 바꾸기는 '팀 배정' 권한이 있을 때, 맡은 팀으로만.
"""
from __future__ import annotations

import copy

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView,
    QLabel, QMessageBox, QPushButton, QRadioButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..cloud import LOGIN_DOMAIN
from ..db import RepoError
from ..models import PERMS, ROLES, Profile
from .common import button, muted, page_header, px, run_safely, style_table

ASSIGN_COL_LABEL = "팀 배정"
COLS = ["이름", "아이디", "역할", "팀"] + [label for _, label in PERMS] + [ASSIGN_COL_LABEL, ""]
FIRST_PERM_COL = 4


def _padded(w: QWidget) -> QWidget:
    box = QWidget()
    lay = QHBoxLayout(box)
    lay.setContentsMargins(6, 4, 6, 4)
    lay.addWidget(w)
    return box


def _centered(w: QWidget) -> QWidget:
    box = QWidget()
    lay = QHBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setAlignment(Qt.AlignCenter)
    lay.addWidget(w)
    return box


def short_login(login: str) -> str:
    suffix = "@" + LOGIN_DOMAIN
    return login[: -len(suffix)] if login.endswith(suffix) else login


class TeamPickDialog(QDialog):
    """팀 고르기: 근무자는 하나, 관리자는 여러 개."""

    def __init__(self, teams, chosen: list[int], multi: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("맡을 팀 고르기" if multi else "팀 고르기")
        self.resize(px(320), px(120 + 34 * len(teams)))
        lay = QVBoxLayout(self)
        lay.addWidget(muted("관리자는 여러 팀을 맡을 수 있어요." if multi else "근무자는 팀 하나에만 속해요."))
        self.boxes = []
        group = None if multi else QButtonGroup(self)
        for t in teams:
            b = QCheckBox(t.name) if multi else QRadioButton(t.name)
            b.setChecked(t.id in chosen)
            b.team_id = t.id
            if group:
                group.addButton(b)
            self.boxes.append(b)
            lay.addWidget(b)
        lay.addStretch(1)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.button(QDialogButtonBox.Ok).setText("확인")
        box.button(QDialogButtonBox.Cancel).setText("취소")
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)

    def value(self) -> list[int]:
        return sorted(b.team_id for b in self.boxes if b.isChecked())


class _Row:
    """표의 한 줄에서 고친 값들."""

    def __init__(self, p: Profile):
        self.p = p
        self.teams = list(p.teams)
        self.role: QComboBox | None = None
        self.team_btn: QPushButton | None = None
        self.checks: list[QCheckBox] = []
        self.assign: QCheckBox | None = None


class WorkersTab(QWidget):
    changed = Signal()

    def __init__(self, repo):
        super().__init__()
        self.setObjectName("page")
        self.repo = repo
        self.workers: list[Profile] = []
        me = repo.me
        lines = ["① 근무자가 로그인 창에서 '가입 요청'을 체크하고 가입하면 여기에 '승인 대기'로 나타나요.",
                 "② 역할과 팀을 정하고 권한을 체크한 뒤 저장하세요. 팀 열쇠는 저장하면 자동으로 넘겨줘요.",
                 "③ '작업장 보기'/'계정 보기'를 끄면 그 메뉴가 사라져요. (계정 보기를 꺼도 작업장 안의 계정 정보는 보여요)"]
        if me.is_super:
            lines.append("④ 관리자는 맡은 팀의 근무자를 관리해요. 관리자 권한 칸은 관리자 본인이 쓸 수 있는 기능이고, "
                         "'팀 배정'을 켜면 가입 승인과 팀 배정도 할 수 있어요.")
        else:
            lines.append("④ 내가 가진 권한까지만 근무자에게 줄 수 있어요."
                         + (" 가입 승인과 팀 배정은 내가 맡은 팀으로만 할 수 있어요." if me.can_assign_team else
                            " 가입 승인과 팀 배정은 총관리자에게 '팀 배정' 권한을 받아야 해요."))
        hint = QLabel("\n".join(lines))
        hint.setWordWrap(True)
        hint.setObjectName("hintBox")
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(px(44))
        style_table(self.table)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.setColumnHidden(COLS.index(ASSIGN_COL_LABEL), not me.is_super)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        lay.setSpacing(14)
        lay.addWidget(page_header("근무자 관리", "가입 승인, 팀 배정, 사람별 권한을 정해요"))
        lay.addWidget(hint)
        lay.addWidget(self.table, 1)

    # ---------------------------------------------------------------- 권한 판단
    def _can_edit(self, p: Profile) -> bool:
        me = self.repo.me
        if p.id == me.id or p.role == "super":
            return False
        if me.is_super:
            return True
        if p.role == "admin":
            return False
        if p.role == "pending":
            return me.can_assign_team
        return bool(p.teams) and all(t in me.teams for t in p.teams)

    def _can_change_team(self) -> bool:
        me = self.repo.me
        return me.is_super or (me.role == "admin" and me.can_assign_team)

    def _team_choices(self):
        me = self.repo.me
        return [t for t in self.repo.teams if me.is_super or t.id in me.teams]

    def _team_text(self, ids: list[int]) -> str:
        names = {t.id: t.name for t in self.repo.teams}
        return ", ".join(names.get(i, f"팀#{i}") for i in ids) or "팀 없음"

    # ---------------------------------------------------------------- 표
    def refresh(self) -> None:
        order = {"super": 0, "admin": 1, "worker": 2, "pending": 3}
        self.workers = sorted(self.repo.list_workers(), key=lambda p: order.get(p.role, 9))
        me = self.repo.me
        self.table.setRowCount(len(self.workers))
        for r, p in enumerate(self.workers):
            row = _Row(p)
            editable = self._can_edit(p)
            name = QTableWidgetItem(p.display_name)
            if not editable:
                name.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(r, 0, name)
            login = QTableWidgetItem(short_login(p.login))
            login.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(r, 1, login)

            # 역할
            role = QComboBox()
            roles = ["admin", "worker", "pending"] if me.is_super else ["worker", "pending"]
            if p.role not in roles:
                roles = [p.role] + roles
            for k in roles:
                role.addItem(ROLES[k], k)
            role.setCurrentIndex(roles.index(p.role))
            role.setEnabled(editable and p.role != "super")
            row.role = role
            self.table.setCellWidget(r, 2, _padded(role))

            # 팀
            if p.role == "super":
                self.table.setCellWidget(r, 3, _padded(muted("모든 팀")))
            else:
                tb = QPushButton(self._team_text(p.teams))
                tb.setCursor(Qt.PointingHandCursor)
                tb.setEnabled(editable and self._can_change_team())
                tb.setToolTip("눌러서 팀을 고르세요" if tb.isEnabled() else
                              ("팀을 바꾸려면 '팀 배정' 권한이 있어야 해요" if editable else ""))
                tb.clicked.connect(lambda _=False, row=row: self._pick_teams(row))
                row.team_btn = tb
                self.table.setCellWidget(r, 3, _padded(tb))

            # 권한
            for c, (attr, _label) in enumerate(PERMS, start=FIRST_PERM_COL):
                cb = QCheckBox()
                cb.setChecked(True if p.role == "super" else getattr(p, attr))
                cb.perm = attr
                self.table.setCellWidget(r, c, _centered(cb))
                row.checks.append(cb)
            assign = QCheckBox()
            assign.setChecked(p.role == "super" or p.can_assign_team)
            assign.setToolTip("관리자가 가입 승인과 팀 배정을 할 수 있게 해요 (맡은 팀으로만)")
            row.assign = assign
            self.table.setCellWidget(r, COLS.index(ASSIGN_COL_LABEL), _centered(assign))

            role.currentIndexChanged.connect(lambda _=0, row=row: self._enable(row))
            self._enable(row)

            if p.id == me.id:
                save = muted("나")
            elif not editable:
                save = muted("-")
            else:
                save = button("저장", "primary")
                save.clicked.connect(lambda _=False, r=r, row=row: self._save(r, row))
            self.table.setCellWidget(r, len(COLS) - 1, _padded(save))
        self.restyle()

    def _enable(self, row: _Row) -> None:
        me = self.repo.me
        editable = self._can_edit(row.p)
        role = row.role.currentData()
        for cb in row.checks:
            cb.setEnabled(editable and role in ("admin", "worker") and me.can(cb.perm))
        row.assign.setEnabled(editable and me.is_super and role == "admin")

    def _pick_teams(self, row: _Row) -> None:
        multi = row.role.currentData() == "admin"
        dlg = TeamPickDialog(self._team_choices(), row.teams, multi, self)
        if dlg.exec():
            row.teams = dlg.value()
            row.team_btn.setText(self._team_text(row.teams))

    def restyle(self) -> None:
        self.table.verticalHeader().setDefaultSectionSize(px(44))
        # 열 제목 글자가 잘리지 않게: 기본 너비와 '제목 글자 폭 + 여백' 중 큰 값
        hf = QFont(self.table.horizontalHeader().font())
        hf.setPixelSize(px(13))
        hf.setBold(True)
        fm = QFontMetrics(hf)
        for c, w in enumerate([110, 100, 120, 130] + [72] * len(PERMS) + [72, 80]):
            self.table.setColumnWidth(c, max(px(w), fm.horizontalAdvance(COLS[c]) + px(24)))

    def _save(self, r: int, row: _Row) -> None:
        p = row.p
        q = copy.copy(p)
        q.display_name = self.table.item(r, 0).text().strip() or p.display_name
        q.role = row.role.currentData()
        q.teams = [] if q.role == "pending" else list(row.teams)
        if q.role == "worker" and len(q.teams) != 1:
            QMessageBox.warning(self, "팀 확인", "근무자는 팀을 하나 정해야 해요. '팀' 칸을 눌러 고르세요.")
            return
        if q.role == "admin" and not q.teams:
            QMessageBox.warning(self, "팀 확인", "관리자가 맡을 팀을 하나 이상 정하세요. '팀' 칸을 눌러 고르세요.")
            return
        for cb in row.checks:
            setattr(q, cb.perm, cb.isChecked() and q.role in ("admin", "worker"))
        q.can_assign_team = row.assign.isChecked() and q.role == "admin"
        if run_safely(self, self.repo.save_profile, q):
            try:
                self.repo.grant_missing_keys()  # 새로 들어온 팀의 열쇠를 바로 넘겨준다
            except RepoError:
                pass
            self.refresh()
            self.changed.emit()
