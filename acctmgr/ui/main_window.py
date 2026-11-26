from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QFileDialog, QHeaderView, QInputDialog, QMainWindow, QMessageBox,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from ..db import Repository, RepoError
from ..importer import import_workbook, snapshot
from ..models import ROLES
from ..version import __version__
from .accounts import AccountsTab
from .update_ui import manual_check
from .connect import ConnectionDialog, settings
from .workers import WorkersTab
from .workplace import WorkplaceTab

POLL_MS = 8000


class HistoryTab(QWidget):
    def __init__(self, repo):
        super().__init__()
        self.repo = repo
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["시각", "작업자", "작업", "내용"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        lay = QVBoxLayout(self)
        lay.addWidget(self.table)

    def refresh(self) -> None:
        rows = self.repo.list_log()
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, key in enumerate(("at", "actor", "action", "detail")):
                self.table.setItem(r, c, QTableWidgetItem(str(row[key])))
        self.table.resizeColumnsToContents()


class MainWindow(QMainWindow):
    def __init__(self, repo):
        super().__init__()
        self.repo = repo
        self.cloud = repo.is_cloud
        me = repo.me
        if not self.cloud:
            repo.actor = settings().value("actor", "") or self._ask_actor(first=True)
        self._update_title()
        self.resize(1400, 860)

        self.work = WorkplaceTab(repo)
        self.accounts = AccountsTab(repo)
        self.history = HistoryTab(repo)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.work, "작업장")
        self.tabs.addTab(self.accounts, "계정")
        self.tabs.addTab(self.history, "변경 기록")
        self.workers_tab = None
        if self.cloud and me.is_admin:
            self.workers_tab = WorkersTab(repo)
            self.tabs.addTab(self.workers_tab, "근무자 관리")
            self.workers_tab.changed.connect(self._after_change)
        self.tabs.currentChanged.connect(lambda _: self._refresh_current())
        self.setCentralWidget(self.tabs)
        self.work.changed.connect(self._after_change)
        self.accounts.changed.connect(self._after_change)

        menu = self.menuBar().addMenu("파일")
        if me.is_admin:
            act = QAction("엑셀에서 가져오기...", self)
            act.triggered.connect(self._import)
            menu.addAction(act)
        if self.cloud and me.is_admin:
            up = QAction("이 PC의 로컬 데이터를 클라우드로 올리기...", self)
            up.triggered.connect(self._upload_local)
            menu.addAction(up)
        if not self.cloud:
            act2 = QAction("작업자 이름 바꾸기...", self)
            act2.triggered.connect(lambda: (self._ask_actor(), self._update_title()))
            menu.addAction(act2)
        conn = QAction("연결 설정... (다시 시작 필요)", self)
        conn.triggered.connect(self._connection)
        menu.addAction(conn)
        upd = QAction(f"업데이트 확인... (지금 v{__version__})", self)
        upd.triggered.connect(self._check_update)
        menu.addAction(upd)
        menu.addSeparator()
        quit_act = QAction("종료", self)
        quit_act.triggered.connect(self.close)
        menu.addAction(quit_act)
        refresh = QAction("새로고침 (F5)", self)
        refresh.setShortcut("F5")
        refresh.triggered.connect(self.refresh_all)
        self.menuBar().addAction(refresh)

        self._last_change = None
        self.refresh_all()
        if self.cloud:
            self.timer = QTimer(self)
            self.timer.timeout.connect(self._poll)
            self.timer.start(POLL_MS)
        if me.is_admin and repo.is_empty():
            QMessageBox.information(self, "시작하기", "아직 데이터가 없어요.\n파일 메뉴에서 엑셀을 가져오거나 로컬 데이터를 올리세요.")

    # ---------------------------------------------------------------- 공통
    def _ask_actor(self, first: bool = False) -> str:
        name, ok = QInputDialog.getText(self, "작업자 이름", "변경 기록에 남길 이름을 입력하세요.",
                                        text="" if first else self.repo.actor)
        name = name.strip() if ok and name.strip() else (self.repo.actor or "관리자")
        settings().setValue("actor", name)
        self.repo.actor = name
        return name

    def _update_title(self) -> None:
        where = "클라우드" if self.cloud else "이 PC"
        role = ROLES.get(self.repo.me.role, "") if self.cloud else "관리자"
        self.setWindowTitle(f"AccountManagement v{__version__} — {self.repo.actor} ({role}) · {where}")

    def _safe(self, fn) -> None:
        try:
            fn()
        except RepoError as e:
            self.statusBar().showMessage(f"새로고침 실패: {e}", 10000)

    def _refresh_current(self) -> None:
        self._safe(self.tabs.currentWidget().refresh)

    def refresh_all(self) -> None:
        def go():
            for t in (self.work, self.accounts, self.history, self.workers_tab):
                if t:
                    t.refresh()
            self._last_change = self.repo.last_change()
        self._safe(go)

    def _after_change(self) -> None:
        # 지금 탭은 이미 새로 그렸으니 나머지만
        def go():
            for t in (self.work, self.accounts, self.history, self.workers_tab):
                if t and t is not self.tabs.currentWidget():
                    t.refresh()
            self._last_change = self.repo.last_change()
        self._safe(go)

    def _poll(self) -> None:
        if QApplication.activeModalWidget():
            return  # 수정 창이 열려 있을 때는 건드리지 않는다
        try:
            n = self.repo.last_change()
        except RepoError as e:
            self.statusBar().showMessage(f"서버 연결 확인 중: {e}", 10000)
            return
        if n != self._last_change:
            self.refresh_all()
            self.statusBar().showMessage("다른 사람이 바꾼 내용을 반영했어요.", 5000)

    def _check_update(self) -> None:
        if manual_check(self):
            QApplication.quit()

    def _connection(self) -> None:
        if ConnectionDialog(self).exec():
            QMessageBox.information(self, "연결 설정", "저장했어요. 프로그램을 다시 시작하면 적용돼요.")

    # ---------------------------------------------------------------- 데이터 넣기
    def _confirm_replace(self) -> bool:
        if self.repo.is_empty():
            return True
        where = "클라우드" if self.cloud else "프로그램"
        return QMessageBox.question(
            self, "데이터 바꾸기",
            f"지금 {where}에 있는 계정, 컴퓨터, 배정 정보를 모두 지우고 새 내용으로 바꿀까요?\n(변경 기록은 남아요)"
        ) == QMessageBox.Yes

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "엑셀 파일 선택", "", "Excel (*.xlsx)")
        if not path or not self._confirm_replace():
            return
        try:
            report = import_workbook(path, self.repo)
        except Exception as e:  # 엑셀 형식 문제는 그대로 보여준다
            QMessageBox.critical(self, "가져오기 실패", str(e))
            return
        self.refresh_all()
        QMessageBox.information(self, "가져오기 완료", report.text())

    def _upload_local(self) -> None:
        local = Repository()
        if local.is_empty():
            QMessageBox.information(self, "로컬 데이터 올리기", "이 PC에 저장된 로컬 데이터가 없어요.")
            return
        accounts, pcs, links = snapshot(local)
        if QMessageBox.question(
                self, "로컬 데이터 올리기",
                f"이 PC의 데이터(계정 {len(accounts)}개, 컴퓨터 {len(pcs)}대, 배정 {len(links)}건)를 클라우드로 올릴까요?\n"
                "담당자는 모두 '지정 안 함'으로 올라가요.") != QMessageBox.Yes:
            return
        if not self._confirm_replace():
            return
        try:
            n = self.repo.bulk_import(accounts, pcs, links)
        except RepoError as e:
            QMessageBox.warning(self, "올리기 실패", str(e))
            return
        self.refresh_all()
        QMessageBox.information(self, "올리기 완료", f"계정 {len(accounts)}개, 컴퓨터 {len(pcs)}대, 배정 {n}건을 올렸어요.")
