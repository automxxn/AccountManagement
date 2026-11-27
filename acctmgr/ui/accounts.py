"""계정 화면: 전체 계정 표, 상태별 필터, 추가/수정/삭제."""
from __future__ import annotations

import copy
import time
from collections import Counter

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemDelegate, QAbstractItemView, QApplication, QButtonGroup, QDialog, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget,
    QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..db import Repository, RepoError
from ..models import (
    DEFAULT_GAMES, GAMES, Character, set_games, STATUS_AUTH, STATUS_AVAILABLE, STATUS_BANNED, STATUS_IN_USE, STATUS_WITHDRAWN, Account, norm_login,
)
from .bg import bg, reload_async
from .common import FlowLayout, GridDelegate, button, copy_text, group, muted, page_header, px, run_safely, style_table
from .dialogs import AccountDialog, CharacterDialog
from .sheet import ACC_CHAR, ACCOUNT_COLUMNS, ID_ROLE, SheetNav, cap_widths, fill_account_cells, rebuild_columns

COLUMNS = ACCOUNT_COLUMNS
CHAR_COLS = ACC_CHAR     # 두 번 누르면 캐릭터 창

# 한 번 눌러서 그 칸만 바로 고칠 수 있는 열 (열 이름 → 계정 필드). 캐릭터 칸(닉, 레벨/직업)도 바로 고침.
INLINE_FIELDS = {"명의자": "owner", "연락처": "contact", "아이디": "login_id", "비밀번호": "password",
                 "메월코드": "tag", "비고": "note"}


def inline_target(col: int):
    """그 열을 바로 고칠 수 있으면 ('field', 필드) 또는 ('nick'/'lj', 게임), 아니면 None."""
    if not 0 <= col < len(ACCOUNT_COLUMNS):
        return None
    if col in ACC_CHAR:
        return ("nick" if ACCOUNT_COLUMNS[col].endswith("닉") else "lj", ACC_CHAR[col])
    name = ACCOUNT_COLUMNS[col]
    return ("field", INLINE_FIELDS[name]) if name in INLINE_FIELDS else None


def inline_value(a: Account, target) -> str:
    kind, key = target
    if kind == "field":
        return getattr(a, key) or ""
    cs = a.chars(key)
    if not cs:
        return ""
    return cs[0].nickname if kind == "nick" else cs[0].level_job


def inline_apply(a: Account, target, text: str) -> Account | None:
    """고친 값을 넣은 새 계정 (바뀐 게 없으면 None). 캐릭터 칸은 대표 캐릭터를 고친다 (없으면 새로)."""
    kind, key = target
    text = text if (kind == "field" and key in ("password", "note")) else text.strip()
    if inline_value(a, target) == text:
        return None
    q = copy.deepcopy(a)
    if kind == "field":
        setattr(q, key, text)
        return q
    cs = q.chars(key)
    if cs:
        if kind == "nick":
            cs[0].nickname = text
        else:
            cs[0].level_job = text
    else:
        q.characters.append(Character(key, text if kind == "nick" else "", text if kind == "lj" else ""))
    return q


class InlineDelegate(GridDelegate):
    """칸 바로 고치기. 고치는 칸을 곧바로 한 번 더 누르면(=두 번 클릭) 고치기를 그만두고 창을 연다."""

    def __init__(self, tab):
        super().__init__(tab.table)
        self.tab = tab
        self._opened = 0.0
        self._index = (0, 0)

    def createEditor(self, parent, option, index):
        ed = QLineEdit(parent)
        ed.setFrame(False)
        self._opened = time.monotonic()
        self._index = (index.row(), index.column())
        ed.installEventFilter(self)
        return ed

    def setEditorData(self, editor, index) -> None:
        editor.setText(self.tab._raw_value(index.row(), index.column()))
        editor.selectAll()

    def setModelData(self, editor, model, index) -> None:
        self.tab._commit_cell(index.row(), index.column(), editor.text())

    def eventFilter(self, obj, ev) -> bool:
        if isinstance(obj, QLineEdit) and ev.type() in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick)                 and time.monotonic() - self._opened < QApplication.doubleClickInterval() / 1000:
            r, c = self._index
            self.closeEditor.emit(obj, QAbstractItemDelegate.RevertModelCache)   # 저장하지 않고 닫기
            QTimer.singleShot(0, lambda: self.tab._open_dialog(r, c))
            return True
        return super().eventFilter(obj, ev)


def filter_names() -> list[str]:
    """필터 버튼: 상태 5가지 + 게임별 정지 + 중복 의심 + 삭제 요청 (게임 목록에 따라 바뀜)"""
    return (["전체", STATUS_AVAILABLE, STATUS_IN_USE, STATUS_BANNED, STATUS_AUTH, STATUS_WITHDRAWN]
            + [f"{g}정지" for g in GAMES] + ["중복 의심", "삭제 요청"])


class GamesDialog(QDialog):
    """게임 종류 관리: 추가하면 계정 표에 '○○닉', '○○ 레벨/직업', '○○정지' 열이 생긴다."""

    def __init__(self, games: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("게임 종류 관리")
        self.resize(px(420), px(380))
        self.games = list(games)
        self.list = QListWidget()
        self.list.setObjectName("pickList")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(px(20), px(16), px(20), px(16))
        hint = QLabel("게임을 추가하면 계정 표에 닉, 레벨/직업, 정지 열이 생기고, 작업장의 초록불/빨간불도 늘어나요.\n"
                      "메랜과 플래닛은 지울 수 없어요. 지운 게임의 캐릭터와 정지 정보는 지워지지 않고 숨겨지기만 해요.")
        hint.setWordWrap(True)
        hint.setObjectName("help")
        lay.addWidget(hint)
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        row.addWidget(button("+ 게임 추가", "", self._add))
        row.addWidget(button("선택한 게임 빼기", "danger", self._remove))
        row.addStretch(1)
        row.addWidget(button("저장", "primary", self.accept))
        row.addWidget(button("취소", "", self.reject))
        lay.addLayout(row)
        self._fill()

    def _fill(self) -> None:
        self.list.clear()
        for g in self.games:
            self.list.addItem(g + ("  (기본)" if g in DEFAULT_GAMES else ""))

    def _add(self) -> None:
        name, ok = QInputDialog.getText(self, "게임 추가", "게임 이름 (예: 아르테일)")
        name = name.strip()
        if not ok or not name:
            return
        if name in self.games:
            QMessageBox.information(self, "게임 추가", "이미 있는 게임이에요.")
            return
        self.games.append(name)
        self._fill()

    def _remove(self) -> None:
        r = self.list.currentRow()
        if r < 0:
            return
        g = self.games[r]
        if g in DEFAULT_GAMES:
            QMessageBox.information(self, "게임 빼기", "메랜과 플래닛은 뺄 수 없어요.")
            return
        if QMessageBox.question(self, "게임 빼기",
                                f"'{g}' 열을 계정 표에서 뺄까요?\n캐릭터와 정지 정보는 지워지지 않고, 다시 추가하면 보여요.") \
                == QMessageBox.Yes:
            self.games.pop(r)
            self._fill()


class AccountsTab(QWidget):
    changed = Signal()
    games_changed_signal = Signal()

    def __init__(self, repo: Repository):
        super().__init__()
        self.setObjectName("page")
        self.repo = repo
        self.accs: list[Account] = []
        self.show_pw = False
        self._edit_seq = 0     # 내가 고칠 때마다 +1 (뒤에서 읽어 온 예전 결과를 버리려고)
        self._busy_ops = 0     # 서버에 보내 놓고 답을 기다리는 내 고치기 수
        me = repo.me

        right = []
        if me.is_admin:
            right.append(button("게임 종류 관리", "", self._manage_games, "게임을 추가하면 닉/레벨직업/정지 열이 생겨요"))
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
        self.filter_group.idClicked.connect(lambda _: self._render())
        self.filter_btns: dict[str, QPushButton] = {}
        self.filters: list[str] = []
        frow = QHBoxLayout()
        frow.setSpacing(6)
        chips = QWidget()
        self.chip_row = FlowLayout(chips, spacing=6)   # 필터가 많으면 다음 줄로 (창을 좁혀도 잘리지 않게)
        frow.addWidget(chips, 1)
        self._build_filters()
        self.search = QLineEdit()
        self.search.setPlaceholderText("명의자, 아이디, 닉네임, 비고로 찾기")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(px(220))
        self.search.textChanged.connect(self._render)
        frow.addWidget(self.search)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)   # 바로 고치기는 한 번 누를 때 직접 연다

        style_table(self.table)
        self.table.setItemDelegate(InlineDelegate(self))
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
        self.table.cellDoubleClicked.connect(self._open_dialog)
        self.table.setMouseTracking(True)
        self.table.cellEntered.connect(
            lambda r, c: None if self.nav.drag else
            self.table.viewport().setCursor(Qt.IBeamCursor if self._can_inline(c) else Qt.ArrowCursor))
        self.nav = SheetNav(self.table, "table_zoom", self._render)  # Ctrl+휠 = 표 크기, 휠 누르고 끌기 = 이동

        # 아래 줄: 창이 좁으면 [표시 개수·표 크기] 덩어리와 버튼 덩어리가 두 줄로 나뉨 (잘리지 않게)
        brow = FlowLayout(spacing=px(10))
        self.count_label = muted()
        self.tzoom_btn = button("", "ghost", lambda: self.nav.set(1.0), "누르면 100%로")
        brow.addWidget(group(self.count_label, self.tzoom_btn, spacing=10))
        self.worker_names: dict = {}
        self.show_worker = False  # 담당 근무자 개념은 없앰 (근무자 관리의 보기 권한으로 대신)
        self.pw_btn = button("비번 보기")
        self.pw_btn.setCheckable(True)
        self.pw_btn.toggled.connect(self._toggle_pw)
        brow.addWidget(group(button("아이디 복사", "", lambda: self._copy("id")),
                             button("비번 복사", "", lambda: self._copy("pw")), self.pw_btn))
        edit = [button("수정" if me.can("can_edit_account") else "정보 보기", "", self._edit)]
        if me.can("can_delete_account"):
            edit.append(button("삭제" if me.is_admin else "삭제 요청", "danger", self._delete))
        if me.is_admin and repo.is_cloud:
            self.approve_btn = button("삭제 승인", "danger", self._approve, "근무자가 요청한 삭제를 확정해요 (되돌릴 수 없음)")
            self.reject_btn = button("삭제 거절", "", self._reject, "요청을 취소해서 근무자 화면에 다시 보이게 해요")
            edit += [self.approve_btn, self.reject_btn]
        brow.addWidget(group(*edit))

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

    def _build_filters(self) -> None:
        """필터 버튼을 (다시) 만든다. 게임이 추가되면 '○○정지' 버튼이 생긴다."""
        current = self.filters[self.filter_group.checkedId()] if self.filters and self.filter_group.checkedId() >= 0 else "전체"
        for b in list(self.filter_btns.values()):
            self.filter_group.removeButton(b)
            b.setParent(None)
            b.deleteLater()
        self.filter_btns.clear()
        self.filters = filter_names()
        for i, name in enumerate(self.filters):
            b = button(name, "chip")
            b.setCheckable(True)
            self.filter_group.addButton(b, i)
            self.filter_btns[name] = b
            self.chip_row.addWidget(b)
        (self.filter_btns.get(current) or self.filter_btns["전체"]).setChecked(True)

    def games_changed(self) -> None:
        """게임 목록이 바뀌었을 때: 필터 버튼과 표 열을 다시 만든다."""
        self._build_filters()
        if self.accs:
            self.show_data((self.accs, None))   # 받아 둔 데이터로 다시 그리기 (새 내용은 뒤에서 읽음)

    def _tests(self) -> dict:
        t = {
            "전체": lambda a: True,
            STATUS_AVAILABLE: lambda a: a.assignable,
            STATUS_IN_USE: lambda a: bool(a.location),
            STATUS_BANNED: lambda a: a.status == STATUS_BANNED,
            STATUS_AUTH: lambda a: a.auth_blocked,
            STATUS_WITHDRAWN: lambda a: a.withdrawn,
            "중복 의심": lambda a: a.id in self.dups,
            "삭제 요청": lambda a: a.delete_requested,
        }
        for g in GAMES:
            t[f"{g}정지"] = lambda a, g=g: a.ban(g).active()
        return t

    def _manage_games(self) -> None:
        dlg = GamesDialog(list(GAMES), self)
        if not dlg.exec() or dlg.games == list(GAMES):
            return
        if run_safely(self, self.repo.save_games, dlg.games):
            set_games(dlg.games)
            rebuild_columns()
            self.games_changed_signal.emit()

    def refresh(self) -> None:
        self.show_data(self.fetch())

    def _after_change(self) -> None:
        """저장한 뒤: 다시 읽기는 뒤에서 (화면이 멈추지 않게)."""
        self.changed.emit()
        reload_async(self)

    def fetch(self):
        """서버에서 읽기만 (뒤 작업 줄에서 불러도 됨). 읽기 시작할 때의 '내 고치기 번호'도 같이."""
        seq = self._edit_seq
        names = {w.id: w.display_name for w in self.repo.list_workers()} if self.show_worker else None
        return self.repo.list_accounts(), names, seq

    def show_data(self, data) -> None:
        accs, names = data[0], data[1]
        if len(data) > 2 and (data[2] != self._edit_seq or self._busy_ops):
            return   # 읽는 사이에 내가 또 고침 → 예전 결과 (화면엔 이미 새 내용이 있음)
        self.accs = accs
        if names is not None:
            self.worker_names = names
        keys = Counter(norm_login(a.login_id) for a in self.accs)
        self.dups = {a.id for a in self.accs if keys[norm_login(a.login_id)] > 1}
        tests = self._tests()
        n = {name: sum(1 for a in self.accs if tests[name](a)) for name in self.filters}
        self.filter_btns["삭제 요청"].setVisible(self.repo.me.is_admin and self.repo.is_cloud)
        req = n["삭제 요청"]
        self.req_banner.setVisible(bool(req) and self.repo.me.is_admin)
        self.req_banner.setText(f"<b>근무자가 삭제를 요청한 계정이 {req}개 있어요.</b> "
                                f"눌러서 확인하고, 계정을 고른 뒤 아래 <b>삭제 승인</b> 또는 <b>삭제 거절</b>을 누르세요.")
        for name, b in self.filter_btns.items():
            b.setText(f"{name} {n[name]}")
        self._render()

    def _visible(self) -> list[Account]:
        idx = self.filter_group.checkedId()
        f = self.filters[idx] if 0 <= idx < len(self.filters) else "전체"
        q = self.search.text().strip().lower()
        test = self._tests().get(f, lambda a: True)
        out = [a for a in self.accs if test(a) and (not q or q in a.search_text())]
        # 사용중 → 사용가능 → 정지 → 인증불가 → 탈퇴 순, 그 안에서는 명의자순
        order = {STATUS_IN_USE: 0, STATUS_AVAILABLE: 1, STATUS_BANNED: 2, STATUS_AUTH: 3, STATUS_WITHDRAWN: 4}
        out.sort(key=lambda a: (order.get(a.status, 9), a.owner, a.login_id))
        return out

    def _render(self) -> None:
        rows = self._visible()
        self.table.setSortingEnabled(False)
        if self.table.columnCount() != len(ACCOUNT_COLUMNS) or \
                self.table.horizontalHeaderItem(len(ACCOUNT_COLUMNS) - 1).text() != ACCOUNT_COLUMNS[-1]:
            self.table.setColumnCount(len(ACCOUNT_COLUMNS))
        self.table.setHorizontalHeaderLabels(ACCOUNT_COLUMNS)
        self.table.setRowCount(len(rows))
        bold = self.nav.bold_font()
        for r, a in enumerate(rows):
            fill_account_cells(self.table, r, 0, a, self.show_pw, self.worker_names, bold)
        self.table.setSortingEnabled(True)
        cap_widths(self.table, 0, self.nav.zoom)
        self.tzoom_btn.setText(self.nav.label())
        self.count_label.setText(f"{len(rows)}개 표시 · 칸을 한 번 누르면 그 칸만 바로 수정 (Enter = 저장, Esc = 취소) · 두 번 누르면 수정 창 (캐릭터 칸은 캐릭터 창)")

    # ---------------------------------------------------------------- 칸 바로 고치기
    def _row_account(self, r: int) -> Account | None:
        it = self.table.item(r, 0)
        aid = it.data(ID_ROLE) if it else None
        return next((x for x in self.accs if x.id == aid), None) if aid is not None else None

    def _can_inline(self, c: int) -> bool:
        return self.repo.me.can("can_edit_account") and inline_target(c) is not None

    def _cell_clicked(self, r: int, c: int) -> None:
        """한 번 누르면 그 칸만 바로 고치기 (고칠 수 없는 칸은 그 줄만 골라짐)."""
        if not self._can_inline(c):
            return
        a = self._row_account(r)
        if a is None or a.delete_requested:
            return
        it = self.table.item(r, c)
        if it is not None:
            self.table.editItem(it)

    def _raw_value(self, r: int, c: int) -> str:
        a, target = self._row_account(r), inline_target(c)
        return inline_value(a, target) if a and target else ""

    def _commit_cell(self, r: int, c: int, text: str) -> None:
        a, target = self._row_account(r), inline_target(c)
        if a is None or target is None:
            return
        aid = a.id
        QTimer.singleShot(0, lambda: self._save_inline(aid, target, text))   # 고치기 칸이 닫힌 뒤에

    def _save_inline(self, aid: int, target, text: str) -> None:
        """화면은 바로 바꾸고, 서버 저장은 뒤에서. 실패하면 알려 주고 서버 내용으로 되돌린다."""
        i = next((k for k, x in enumerate(self.accs) if x.id == aid), None)
        if i is None:
            return
        old = self.accs[i]
        q = inline_apply(old, target, text)
        if q is None:
            return
        if target == ("field", "login_id") and not q.login_id:
            QMessageBox.information(self, "아이디", "아이디는 비울 수 없어요.")
            self._render()
            return
        send = copy.deepcopy(q)            # 서버로 보낼 것 (지금 버전으로)
        q.version = old.version + 1        # 서버가 저장하면 버전이 1 오름 → 연달아 고쳐도 충돌 안 나게 미리 맞춤
        self.accs[i] = q
        self._edit_seq += 1
        self._busy_ops += 1
        self.show_data((self.accs, None))

        def ok(_r) -> None:
            self._busy_ops -= 1
            if not self._busy_ops:
                self._after_change()

        def fail(e) -> None:
            self._busy_ops -= 1
            self._edit_seq += 1
            QMessageBox.warning(self, "저장 안 됨", (str(e) if isinstance(e, RepoError) else f"오류: {e}")
                                + "\n\n서버에 저장되지 않아서 원래대로 되돌려요.")
            if not self._busy_ops:
                reload_async(self)
        bg().run(self.repo, lambda: self.repo.save_account(send), ok, fail)

    def _open_dialog(self, r: int, c: int) -> None:
        """두 번 누르면: 캐릭터 칸은 캐릭터 창, 나머지는 계정 수정 창."""
        a = self._row_account(r)
        if a is None:
            return
        self.table.selectRow(r)
        if c in CHAR_COLS:
            if CharacterDialog(self.repo, a, CHAR_COLS[c], self).exec():
                self._after_change()
            return
        if AccountDialog(self.repo, a, self).exec():
            self._after_change()

    def _current(self) -> Account | None:
        r = self.table.currentRow()
        if r < 0:
            return None
        it = self.table.item(r, 0)
        aid = it.data(ID_ROLE) if it else None
        return next((a for a in self.accs if a.id == aid), None)

    def _add(self) -> None:
        if AccountDialog(self.repo, None, self).exec():
            self._after_change()

    def _edit(self) -> None:
        a = self._current()
        if not a:
            return
        if AccountDialog(self.repo, a, self).exec():
            self._after_change()

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
                    self._after_change()
            return
        msg = f"[{a.provider}] {a.login_id} ({a.owner}) 계정을 삭제할까요?\n삭제하면 되돌릴 수 없어요."
        if a.location:
            msg += f"\n{a.location.text()}에서도 빠져요."
        msg += "\n\n그만 쓰는 계정이면 삭제 대신 '탈퇴'로 표시하는 방법도 있어요."
        if QMessageBox.question(self, "계정 삭제", msg) == QMessageBox.Yes:
            if run_safely(self, self.repo.delete_account, a.id):
                self._after_change()

    def _approve(self) -> None:
        a = self._current()
        if not a or not a.delete_requested:
            QMessageBox.information(self, "삭제 승인", "'삭제 요청' 상태인 계정을 고르세요.")
            return
        if QMessageBox.question(self, "삭제 승인",
                                f"[{a.provider}] {a.login_id} ({a.owner}) 계정을 완전히 삭제할까요?\n되돌릴 수 없어요.") \
                == QMessageBox.Yes and run_safely(self, self.repo.approve_delete, a.id):
            self._after_change()

    def _reject(self) -> None:
        a = self._current()
        if not a or not a.delete_requested:
            QMessageBox.information(self, "삭제 거절", "'삭제 요청' 상태인 계정을 고르세요.")
            return
        if run_safely(self, self.repo.reject_delete, a.id):
            QMessageBox.information(self, "삭제 거절",
                                    "삭제 요청을 거절했어요. 근무자 화면에 다시 보여요.\n"
                                    "원래 들어 있던 자리가 비어 있으면 그 자리로 되돌려 놓았어요.")
            self._after_change()

    def _copy(self, what: str) -> None:
        a = self._current()
        if a:
            copy_text(a.login_id if what == "id" else a.password)

    def _toggle_pw(self, on: bool) -> None:
        self.show_pw = on
        self.pw_btn.setText("비번 가리기" if on else "비번 보기")
        self._render()
