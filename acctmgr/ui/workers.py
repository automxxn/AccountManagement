"""근무자 관리 탭 (클라우드, 관리자 전용): 승인, 역할, 권한 켜고 끄기."""
from __future__ import annotations

import copy

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..models import PERMS, ROLES, Profile
from .common import button, muted, page_header, run_safely
from ..cloud import LOGIN_DOMAIN

COLS = ["이름", "아이디", "역할"] + [label for _, label in PERMS] + [""]


def _padded(w: QWidget) -> QWidget:
    box = QWidget()
    lay = QHBoxLayout(box)
    lay.setContentsMargins(6, 4, 6, 4)
    lay.addWidget(w)
    return box


def short_login(login: str) -> str:
    suffix = "@" + LOGIN_DOMAIN
    return login[: -len(suffix)] if login.endswith(suffix) else login


class WorkersTab(QWidget):
    changed = Signal()

    def __init__(self, repo):
        super().__init__()
        self.setObjectName("page")
        self.repo = repo
        self.workers: list[Profile] = []
        hint = QLabel("① 근무자가 프로그램에서 '처음 사용해요 (가입 요청)'으로 가입하면 여기에 '승인 대기'로 나타나요.\n"
                      "② 역할을 '근무자'로 바꾸고 권한을 체크한 뒤 저장하세요.\n"
                      "③ 컴퓨터/계정 수정 창의 '담당 근무자'에서 맡길 것을 정하세요. 근무자는 담당 컴퓨터와 담당 계정만 볼 수 있어요.")
        hint.setWordWrap(True)
        hint.setStyleSheet("background:#FFFFFF; border:1px solid #E4E6EA; border-radius:10px; padding:12px 14px; color:#3D4450;")
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.table.setShowGrid(False)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(False)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        lay.setSpacing(14)
        lay.addWidget(page_header("근무자 관리", "가입 승인과 근무자별 권한을 정해요"))
        lay.addWidget(hint)
        lay.addWidget(self.table, 1)

    def refresh(self) -> None:
        self.workers = self.repo.list_workers()
        self.table.setRowCount(len(self.workers))
        for r, p in enumerate(self.workers):
            name = QTableWidgetItem(p.display_name)
            self.table.setItem(r, 0, name)
            login = QTableWidgetItem(short_login(p.login))
            login.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(r, 1, login)
            role = QComboBox()
            for k, v in ROLES.items():
                role.addItem(v, k)
            role.setCurrentIndex(list(ROLES).index(p.role))
            self.table.setCellWidget(r, 2, _padded(role))
            checks = []
            for c, (attr, _label) in enumerate(PERMS, start=3):
                cb = QCheckBox()
                cb.setChecked(getattr(p, attr))
                w = QWidget()
                l = QHBoxLayout(w)
                l.setContentsMargins(0, 0, 0, 0)
                l.setAlignment(Qt.AlignCenter)
                l.addWidget(cb)
                self.table.setCellWidget(r, c, w)
                checks.append(cb)
            role.currentIndexChanged.connect(lambda _=0, role=role, checks=checks: [
                cb.setEnabled(role.currentData() == "worker") for cb in checks])
            for cb in checks:
                cb.setEnabled(p.role == "worker")
            if p.id == self.repo.me.id:
                role.setEnabled(False)
                save = muted("나")
            else:
                save = button("저장", "primary")
                save.clicked.connect(lambda _=False, r=r, p=p, role=role, checks=checks: self._save(r, p, role, checks))
            self.table.setCellWidget(r, len(COLS) - 1, _padded(save))
        for c, w in enumerate([180, 160, 140] + [120] * len(PERMS) + [100]):
            self.table.setColumnWidth(c, w)

    def _save(self, r: int, p: Profile, role: QComboBox, checks: list[QCheckBox]) -> None:
        q = copy.copy(p)
        q.display_name = self.table.item(r, 0).text().strip() or p.display_name
        q.role = role.currentData()
        for (attr, _), cb in zip(PERMS, checks):
            setattr(q, attr, cb.isChecked() and q.role == "worker")
        if run_safely(self, self.repo.save_profile, q):
            self.refresh()
            self.changed.emit()
