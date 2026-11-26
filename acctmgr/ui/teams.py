"""팀 관리 탭 (클라우드, 총관리자 전용): 팀 추가, 이름 바꾸기, 삭제.

팀마다 컴퓨터, 계정, 배정, 게임 종류, 변경 기록이 따로이고 다른 팀 데이터는 보이지 않는다.
사람을 팀에 넣고 빼는 것은 근무자 관리에서 한다.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QMessageBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from .common import button, fit_columns, page_header, px, run_safely, style_table

COLS = ["팀 이름", "관리자", "근무자", "컴퓨터", "계정", ""]


def _padded(w: QWidget) -> QWidget:
    box = QWidget()
    lay = QHBoxLayout(box)
    lay.setContentsMargins(6, 4, 6, 4)
    lay.setSpacing(6)
    lay.addWidget(w)
    return box


class TeamsTab(QWidget):
    changed = Signal()  # 팀이 추가/삭제/이름 변경됨

    def __init__(self, repo):
        super().__init__()
        self.setObjectName("page")
        self.repo = repo
        hint = QLabel("팀마다 컴퓨터, 계정, 게임 종류, 변경 기록이 따로예요. 다른 팀 사람에게는 이 팀 데이터가 보이지 않아요.\n"
                      "사람을 팀에 넣거나 관리자에게 팀을 맡기는 것은 '근무자 관리'에서 해요. "
                      "팀은 컴퓨터와 계정이 하나도 없을 때만 삭제할 수 있어요.")
        hint.setWordWrap(True)
        hint.setObjectName("hintBox")
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.verticalHeader().setVisible(False)
        style_table(self.table)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        lay.setSpacing(14)
        lay.addWidget(page_header("팀 관리", "팀을 만들고 이름을 바꾸거나 지워요",
                                  [button("+ 팀 추가", "primary", self._add)]))
        lay.addWidget(hint)
        lay.addWidget(self.table, 1)

    def refresh(self) -> None:
        repo = self.repo
        repo.teams = repo.list_teams()
        people = repo.list_workers()
        counts = repo.team_counts()
        self.table.setRowCount(len(repo.teams))
        for r, t in enumerate(repo.teams):
            name = QTableWidgetItem(t.name)
            name.setToolTip("두 번 눌러서 이름을 고친 뒤 '이름 저장'을 누르세요")
            self.table.setItem(r, 0, name)
            admins = [p.display_name for p in people if p.role == "admin" and t.id in p.teams]
            workers = [p for p in people if p.role == "worker" and t.id in p.teams]
            pcs, accs = counts.get(t.id, (0, 0))
            for c, text in ((1, ", ".join(admins) or "-"), (2, f"{len(workers)}명"), (3, f"{pcs}대"), (4, f"{accs}개")):
                it = QTableWidgetItem(text)
                it.setFlags(Qt.ItemIsEnabled)
                if c > 1:
                    it.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(r, c, it)
            box = QWidget()
            bl = QHBoxLayout(box)
            bl.setContentsMargins(6, 4, 6, 4)
            bl.setSpacing(6)
            bl.addWidget(button("이름 저장", "", lambda _=False, r=r, t=t: self._rename(r, t)))
            if pcs == 0 and accs == 0 and len(repo.teams) > 1:  # 비어 있는 팀만 지울 수 있다
                bl.addWidget(button("삭제", "danger", lambda _=False, t=t: self._delete(t)))
            bl.addStretch(1)
            self.table.setCellWidget(r, 5, box)
        self.restyle()

    def restyle(self) -> None:
        self.table.verticalHeader().setDefaultSectionSize(px(44))
        fit_columns(self.table, mins={0: 160, 1: 160}, caps={1: 420})

    def _add(self) -> None:
        name, ok = QInputDialog.getText(self, "팀 추가", "새 팀 이름")
        if not ok or not name.strip():
            return
        if run_safely(self, self.repo.create_team, name.strip()):
            self.refresh()
            self.changed.emit()
            QMessageBox.information(self, "팀 추가", f"'{name.strip()}' 팀을 만들었어요.\n"
                                    "왼쪽 위 팀 선택에서 이 팀으로 바꾼 뒤 컴퓨터와 계정을 넣으세요.\n"
                                    "사람은 '근무자 관리'에서 이 팀에 넣을 수 있어요.")

    def _rename(self, r: int, t) -> None:
        name = self.table.item(r, 0).text().strip()
        if not name or name == t.name:
            return
        if run_safely(self, self.repo.rename_team, t.id, name):
            self.refresh()
            self.changed.emit()

    def _delete(self, t) -> None:
        if QMessageBox.question(self, "팀 삭제",
                                f"'{t.name}' 팀을 삭제할까요?\n이 팀에만 속한 사람은 '승인 대기'로 돌아가요.") != QMessageBox.Yes:
            return
        if run_safely(self, self.repo.delete_team, t.id):
            self.refresh()
            self.changed.emit()
