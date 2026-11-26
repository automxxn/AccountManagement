from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QFileDialog, QFrame, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
    QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox, QStackedWidget, QTableWidget,
    QTableWidgetItem, QToolButton, QVBoxLayout, QWidget,
)

from .. import logsetup
from ..db import Repository, RepoError
from ..importer import import_workbook, snapshot
from ..models import GAMES, ROLES, set_games
from ..version import __version__
from .accounts import AccountsTab
from .common import (
    ToggleSwitch, ZOOM_STEP, apply_appearance, button, label, muted, page_header, px, scale, style_table, theme,
)
from ..defaults import built_in
from .connect import ConnectionDialog, clear_auto_login, settings
from .update_ui import manual_check
from .teams import TeamsTab
from .workers import WorkersTab
from .sheet import rebuild_columns
from .workplace import WorkplaceTab

POLL_MS = 8000


class HistoryTab(QWidget):
    def __init__(self, repo):
        super().__init__()
        self.setObjectName("page")
        self.repo = repo
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        lay.setSpacing(16)
        lay.addWidget(page_header("변경 기록", "누가 언제 무엇을 바꿨는지 최근 500건을 보여줘요"))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["시각", "작업자", "작업", "내용"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)

        style_table(self.table)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(px(34))
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignCenter)
        lay.addWidget(self.table, 1)

    def restyle(self) -> None:
        self.table.verticalHeader().setDefaultSectionSize(px(34))
        self.table.resizeColumnsToContents()

    def refresh(self) -> None:
        rows = self.repo.list_log()
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, key in enumerate(("at", "actor", "action", "detail")):
                self.table.setItem(r, c, QTableWidgetItem(str(row[key])))
        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(0, max(self.table.columnWidth(0), 160))


class MainWindow(QMainWindow):
    def __init__(self, repo):
        super().__init__()
        self.repo = repo
        self.cloud = repo.is_cloud
        me = repo.me
        if not self.cloud:
            repo.actor = settings().value("actor", "") or self._ask_actor(first=True)
        self._update_title()
        self.resize(1480, 900)

        # 게임 종류 불러오기 (계정 표의 게임별 열이 여기에 맞춰 만들어짐)
        self._load_games()

        # 페이지
        self.work = WorkplaceTab(repo)
        self.accounts = AccountsTab(repo)
        self.history = HistoryTab(repo)
        self.workers_tab = WorkersTab(repo) if (self.cloud and me.is_admin) else None
        self.teams_tab = TeamsTab(repo) if (self.cloud and me.is_super) else None
        # 근무자는 근무자 관리에서 켜 준 메뉴만 보인다 (관리자는 전부)
        self.pages = []
        if me.can("can_view_workplace"):
            self.pages.append(("작업장", self.work))
        if me.can("can_view_accounts"):
            self.pages.append(("계정", self.accounts))
        self.pages.append(("변경 기록", self.history))
        if self.workers_tab:
            self.pages.append(("근무자 관리", self.workers_tab))
            self.workers_tab.changed.connect(self._after_change)
        if self.teams_tab:
            self.pages.append(("팀 관리", self.teams_tab))
            self.teams_tab.changed.connect(self._fill_team_box)
        self.stack = QStackedWidget()
        for _, w in self.pages:
            self.stack.addWidget(w)
        self.work.changed.connect(self._after_change)
        self.accounts.changed.connect(self._after_change)
        self.accounts.games_changed_signal.connect(self._games_changed)

        central = QWidget()
        h = QHBoxLayout(central)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        h.addWidget(self._sidebar())
        h.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self._last_change = None
        self.refresh_all()
        if self.cloud:
            self.timer = QTimer(self)
            self.timer.timeout.connect(self._poll)
            self.timer.start(POLL_MS)
        if me.is_super and repo.is_empty():
            QMessageBox.information(self, "시작하기", "아직 데이터가 없어요.\n왼쪽 아래 메뉴에서 엑셀을 가져오거나 로컬 데이터를 올리세요.")

    # ---------------------------------------------------------------- 사이드바
    def _sidebar(self) -> QFrame:
        side = self.side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(px(220))
        lay = QVBoxLayout(side)
        lay.setContentsMargins(14, 20, 14, 14)
        lay.setSpacing(6)
        lay.addWidget(label("AccountManagement", "appTitle"))
        lay.addWidget(label(f"v{__version__} · {'클라우드' if self.cloud else '이 PC에 저장'}", "appVersion"))
        lay.addSpacing(10)
        self.team_box = QComboBox()
        self.team_box.setToolTip("팀마다 컴퓨터, 계정, 게임 종류가 따로예요")
        self.team_box.currentIndexChanged.connect(self._team_chosen)
        if self.cloud:
            lay.addWidget(muted("팀"))
            lay.addWidget(self.team_box)
            self._fill_team_box()
        lay.addSpacing(10)

        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setCursor(Qt.PointingHandCursor)
        for name, _ in self.pages:
            it = QListWidgetItem(name)
            it.setSizeHint(QSize(0, px(40)))
            self.nav.addItem(it)
        self.nav.setCurrentRow(0)
        self.nav.currentRowChanged.connect(self._go)
        lay.addWidget(self.nav, 1)

        # 보기 설정: 다크 모드 스위치, 화면 배율
        pref = QFrame()
        pref.setObjectName("prefBox")
        pl = QVBoxLayout(pref)
        pl.setContentsMargins(12, 10, 12, 10)
        pl.setSpacing(8)
        row = QHBoxLayout()
        row.addWidget(QLabel("다크 모드"))
        row.addStretch(1)
        self.dark = ToggleSwitch(theme() == "dark")
        self.dark.setToolTip("밝은 화면 / 어두운 화면 전환")
        self.dark.toggled.connect(lambda on: self.set_appearance(theme_name="dark" if on else "light"))
        row.addWidget(self.dark)
        pl.addLayout(row)
        pl.addWidget(QLabel("화면 배율 (전체)"))
        zr = QHBoxLayout()
        zr.setSpacing(4)
        zr.addWidget(button("-", "zoom", lambda: self.set_appearance(zoom=scale() - ZOOM_STEP), "화면 전체를 작게"))
        self.zoom_btn = button(f"{round(scale() * 100)}%", "zoom", lambda: self.set_appearance(zoom=1.0), "누르면 100%로")
        zr.addWidget(self.zoom_btn, 1)
        zr.addWidget(button("+", "zoom", lambda: self.set_appearance(zoom=scale() + ZOOM_STEP), "화면 전체를 크게"))
        pl.addLayout(zr)
        lay.addWidget(pref)

        lay.addWidget(button("새로고침  (F5)", "", self.refresh_all))
        act = QAction(self)
        act.setShortcut("F5")
        act.triggered.connect(self.refresh_all)
        self.addAction(act)

        user = QFrame()
        user.setObjectName("userBox")
        ul = QVBoxLayout(user)
        ul.setContentsMargins(12, 10, 12, 10)
        ul.setSpacing(2)
        ul.addWidget(label(self.repo.actor or "-", "title"))
        role = ROLES.get(self.repo.me.role, "") if self.cloud else "관리자"
        ul.addWidget(muted(role))
        more = QToolButton()
        more.setText("메뉴 열기")
        more.setCursor(Qt.PointingHandCursor)
        more.setPopupMode(QToolButton.InstantPopup)
        more.setMenu(self._menu())
        more.setToolButtonStyle(Qt.ToolButtonTextOnly)
        more.setMinimumWidth(px(170))
        ul.addSpacing(6)
        ul.addWidget(more)
        lay.addWidget(user)
        return side

    # ---------------------------------------------------------------- 보기 설정
    def set_appearance(self, theme_name: str | None = None, zoom: float | None = None) -> None:
        apply_appearance(theme_name, zoom)
        s = settings()
        s.setValue("theme", theme())
        s.setValue("zoom", scale())
        self.zoom_btn.setText(f"{round(scale() * 100)}%")
        self.side.setFixedWidth(px(220))
        for i in range(self.nav.count()):
            self.nav.item(i).setSizeHint(QSize(0, px(40)))
        self.dark.updateGeometry()
        self.dark.update()
        for _, t in self.pages:
            t.restyle()

    def _menu(self) -> QMenu:
        m = QMenu(self)
        me = self.repo.me
        if me.is_super:
            m.addAction("엑셀에서 가져오기... (지금 팀으로)", self._import)
        if self.cloud and me.is_super:
            m.addAction("이 PC의 로컬 데이터를 클라우드로 올리기...", self._upload_local)
        if not self.cloud:
            m.addAction("작업자 이름 바꾸기...", lambda: (self._ask_actor(), self._update_title()))
        if not built_in() and (not self.cloud or me.is_super):
            m.addAction("연결 설정... (다시 시작 필요)", self._connection)
        if self.cloud:
            m.addAction("자동 로그인 끄기", self._auto_login_off)
        m.addSeparator()
        m.addAction(f"업데이트 확인... (지금 v{__version__})", self._check_update)
        m.addAction("오류 기록(로그) 폴더 열기", logsetup.open_log_folder)
        m.addSeparator()
        m.addAction("종료", self.close)
        return m

    def _go(self, row: int) -> None:
        if row < 0:
            return
        self.stack.setCurrentIndex(row)
        self._safe(self.stack.currentWidget().refresh)

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
        team = self.repo.team() if self.cloud else None
        if team:
            where += f" · {team.name}"
        self.setWindowTitle(f"AccountManagement v{__version__} — {self.repo.actor} ({role}) · {where}")

    def _safe(self, fn) -> None:
        try:
            fn()
        except RepoError as e:
            logsetup.log.warning("새로고침 실패: %s", e)
            self.statusBar().showMessage(f"새로고침 실패: {e}", 10000)

    def _load_games(self) -> bool:
        """서버(또는 이 PC)의 게임 목록을 읽어 적용. 바뀌었으면 True."""
        try:
            games = self.repo.list_games()
        except RepoError:
            return False
        before = list(GAMES)
        set_games(games)
        rebuild_columns()
        return list(GAMES) != before

    def _games_changed(self) -> None:
        self.accounts.games_changed()
        self.work.games_changed()
        self._after_change()

    # ---------------------------------------------------------------- 팀
    def _fill_team_box(self) -> None:
        if not self.cloud:
            return
        self.team_box.blockSignals(True)
        self.team_box.clear()
        for t in self.repo.usable_teams():
            self.team_box.addItem(t.name, t.id)
        i = self.team_box.findData(self.repo.team_id)
        self.team_box.setCurrentIndex(max(i, 0))
        self.team_box.setEnabled(self.team_box.count() > 1)
        self.team_box.blockSignals(False)

    def _team_chosen(self, _i: int) -> None:
        tid = self.team_box.currentData()
        if tid is None or tid == self.repo.team_id:
            return
        try:
            self.repo.set_team(tid)
        except RepoError as e:
            QMessageBox.warning(self, "팀", str(e))
            return
        self._update_title()
        self._load_games()
        self._games_changed()
        self.refresh_all()

    def refresh_all(self) -> None:
        if self.cloud:
            before = self.repo.team_id
            try:
                self.repo.reopen_keys()   # 팀이 추가/삭제되거나 열쇠를 새로 받았을 수 있음
                self.repo.grant_missing_keys()
            except RepoError as e:
                logsetup.log.warning("팀 열쇠 확인 실패: %s", e)
            self._fill_team_box()
            if self.repo.team_id is None and self.repo.usable_teams() == [] and hasattr(self.repo, "ciphers"):
                QMessageBox.information(self, "팀", "볼 수 있는 팀이 없어요. 프로그램을 다시 시작하세요.")
                QApplication.quit()
                return
            if self.repo.team_id != before:
                self._update_title()
        if self._load_games():  # 다른 PC에서 관리자가 게임을 추가한 경우
            self.accounts._build_filters()

        def go():
            for _, t in self.pages:
                t.refresh()
            self._last_change = self.repo.last_change()
        self._safe(go)

    def _after_change(self) -> None:
        def go():
            for _, t in self.pages:
                if t is not self.stack.currentWidget():
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

    def _auto_login_off(self) -> None:
        clear_auto_login(self.repo.url)
        QMessageBox.information(self, "자동 로그인", "자동 로그인을 껐어요. 다음에 켤 때는 비밀번호를 입력해야 해요.")

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
            f"지금 {where}{self._team_label()}에 있는 계정, 컴퓨터, 배정 정보를 모두 지우고 새 내용으로 바꿀까요?\n(변경 기록은 남아요)"
        ) == QMessageBox.Yes

    def _team_label(self) -> str:
        t = self.repo.team() if self.cloud else None
        return f"의 '{t.name}' 팀" if t else ""

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "엑셀 파일 선택", "", "Excel (*.xlsx)")
        if not path or not self._confirm_replace():
            return
        try:
            report = import_workbook(path, self.repo)
        except Exception as e:  # 엑셀 형식 문제는 그대로 보여준다
            logsetup.log.exception("엑셀 가져오기 실패")
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
