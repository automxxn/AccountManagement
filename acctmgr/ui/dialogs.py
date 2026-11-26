from __future__ import annotations

import copy
import re

from PySide6.QtCore import QDateTime, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateTimeEdit, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ..db import Repository, RepoError
from ..models import GAMES, PC, PROVIDERS, Account, Ban, Character, join_level_job, split_level_job
from .common import T, copy_text, muted, px, style_table

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}( \d{2}:\d{2})?$")  # 해제 시각 (시간은 없어도 됨)


def section(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("sectionTitle")
    return lab


class PasswordField(QWidget):
    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit(text)
        self.edit.setEchoMode(QLineEdit.Password)
        show = QPushButton("보기")
        show.setCheckable(True)
        show.toggled.connect(lambda on: (self.edit.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password),
                                         show.setText("가리기" if on else "보기")))
        cp = QPushButton("복사")
        cp.clicked.connect(lambda: copy_text(self.edit.text()))
        lay.addWidget(self.edit, 1)
        lay.addWidget(show)
        lay.addWidget(cp)

    def text(self) -> str:
        return self.edit.text()


class BanField(QWidget):
    """[☐ 정지] [2027-06-14 15:30 ▾달력] [☐ 기한 없음]
    - ▾ 버튼: 달력에서 년/월/일 선택
    - 년·월·일·시·분 중 한 부분을 누르고 마우스 휠이나 ↑↓ 키로 하나씩 조절, 숫자 직접 입력도 가능
    """

    FMT = "yyyy-MM-dd HH:mm"

    def __init__(self, ban: Ban, parent=None):
        super().__init__(parent)
        self.original = ban
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(px(8))
        self.check = QCheckBox("정지")
        self.check.setChecked(ban.banned)
        self.until = QDateTimeEdit()
        self.until.setDisplayFormat(self.FMT)
        self.until.setCalendarPopup(True)
        self.until.setKeyboardTracking(True)
        self.until.setToolTip("▾ 버튼: 달력에서 날짜 고르기 · 년/월/일/시/분을 누르고 휠이나 ↑↓로 조절 · 숫자 직접 입력")
        self.until.calendarWidget().setGridVisible(True)
        if ban.until:
            u = ban.until_full()
            self.until.setDateTime(QDateTime.fromString(u, self.FMT))
        else:
            self.until.setDateTime(QDateTime.currentDateTime().addDays(7))
        self._start = self.until.dateTime()
        self.until.setCurrentSection(QDateTimeEdit.DaySection)
        self.no_limit = QCheckBox("기한 없음")
        self.no_limit.setChecked(ban.banned and not ban.until)
        self.check.toggled.connect(self._sync)
        self.no_limit.toggled.connect(self._sync)
        lay.addWidget(self.check)
        lay.addWidget(self.until, 1)
        lay.addWidget(self.no_limit)
        self._sync()

    def _sync(self) -> None:
        on = self.check.isChecked()
        self.no_limit.setEnabled(on)
        self.until.setEnabled(on and not self.no_limit.isChecked())

    def value(self) -> Ban:
        if not self.check.isChecked():
            return Ban(False, "")
        if self.no_limit.isChecked():
            return Ban(True, "")
        if self.original.until and self.until.dateTime() == self._start:
            return Ban(True, self.original.until)  # 손대지 않았으면 원래 값 그대로
        return Ban(True, self.until.dateTime().toString(self.FMT))


class CharacterEditor(QWidget):
    """한 게임의 캐릭터 목록 편집기. 맨 위 줄이 대표 캐릭터. 레벨과 직업은 따로 입력한다."""

    COLS = ["", "닉네임", "레벨", "직업"]

    def __init__(self, game: str, chars: list[Character], editable: bool = True, parent=None):
        super().__init__(parent)
        self.game = game
        self.editable = editable
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Fixed)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.Fixed)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setColumnWidth(0, px(56))
        self.table.setColumnWidth(2, px(70))
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(px(34))
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        style_table(self.table)
        if not editable:
            self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        for c in chars:
            self._append(c.nickname, c.level, c.job)

        head = QHBoxLayout()
        head.addWidget(section(f"{game} 캐릭터"))
        head.addStretch(1)
        self.count = muted()
        head.addWidget(self.count)
        btns = QHBoxLayout()
        btns.setSpacing(6)
        self.b_add = QPushButton("+ 추가")
        self.b_add.clicked.connect(self._add)
        self.b_main = QPushButton("대표로 지정")
        self.b_main.setToolTip("선택한 캐릭터를 대표로 바꿔요. 대표는 작업장과 계정 표에 보여요.")
        self.b_main.clicked.connect(self._make_main)
        self.b_del = QPushButton("삭제")
        self.b_del.setObjectName("danger")
        self.b_del.clicked.connect(self._delete)
        for b in (self.b_add, self.b_main, self.b_del):
            b.setEnabled(editable)
        btns.addWidget(self.b_add)
        btns.addWidget(self.b_main)
        btns.addStretch(1)
        btns.addWidget(self.b_del)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addLayout(head)
        lay.addWidget(self.table, 1)
        lay.addLayout(btns)
        self._mark()

    def _append(self, nick: str = "", level: str = "", job: str = "") -> int:
        r = self.table.rowCount()
        self.table.insertRow(r)
        mark = QTableWidgetItem("")
        mark.setFlags(mark.flags() & ~Qt.ItemIsEditable)
        mark.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(r, 0, mark)
        self.table.setItem(r, 1, QTableWidgetItem(nick))
        lv = QTableWidgetItem(level)
        lv.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(r, 2, lv)
        self.table.setItem(r, 3, QTableWidgetItem(job))
        return r

    def _mark(self) -> None:
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            it.setText("대표" if r == 0 else "")
            it.setForeground(QColor(T("accent_text")))
            f = it.font()
            f.setBold(True)
            it.setFont(f)
        n = self.table.rowCount()
        self.count.setText(f"{n}개" if n else "없음")

    def _rows(self) -> list[tuple[str, str, str]]:
        def t(r, c):
            it = self.table.item(r, c)
            return it.text() if it else ""
        return [(t(r, 1), t(r, 2), t(r, 3)) for r in range(self.table.rowCount())]

    def _add(self) -> None:
        r = self._append()
        self._mark()
        self.table.setCurrentCell(r, 1)
        self.table.editItem(self.table.item(r, 1))

    def _make_main(self) -> None:
        r = self.table.currentRow()
        if r <= 0:
            return
        rows = self._rows()
        rows.insert(0, rows.pop(r))
        for i, vals in enumerate(rows):
            for c, v in enumerate(vals, start=1):
                self.table.item(i, c).setText(v)
        self.table.setCurrentCell(0, 1)
        self._mark()

    def _delete(self) -> None:
        r = self.table.currentRow()
        if r >= 0:
            self.table.removeRow(r)
            self._mark()

    def value(self) -> list[Character]:
        out = []
        for nick, level, job in self._rows():
            level = level.strip()
            if level and not level.isdigit():
                # 레벨 칸에 '104프리'처럼 섞어 적었으면 나눠서 저장
                lv, jb = split_level_job(level)
                level, job = lv, (jb + " " + job).strip()
            lj = join_level_job(level, job)
            if nick.strip() or lj:
                out.append(Character(self.game, nick.strip(), lj))
        return out


class CharacterDialog(QDialog):
    """계정 표에서 캐릭터 칸을 눌렀을 때 여는 창: 그 게임의 캐릭터 추가/수정/삭제, 대표 변경."""

    def __init__(self, repo: Repository, acc: Account, game: str, parent=None):
        super().__init__(parent)
        self.repo = repo
        self.acc = copy.deepcopy(acc)
        self.game = game
        can = repo.me.can("can_edit_account")
        self.setWindowTitle(f"{game} 캐릭터 — {acc.owner or acc.login_id}")
        self.resize(px(620), px(440))
        self.editor = CharacterEditor(game, self.acc.chars(game), can)
        box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        box.button(QDialogButtonBox.Save).setText("저장")
        box.button(QDialogButtonBox.Save).setObjectName("primary")
        box.button(QDialogButtonBox.Save).setEnabled(can)
        box.button(QDialogButtonBox.Cancel).setText("닫기")
        box.accepted.connect(self._save)
        box.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.addWidget(muted(f"[{acc.provider}] {acc.login_id}" + ("" if can else "  ·  수정 권한이 없어서 보기만 할 수 있어요")))
        lay.addWidget(self.editor, 1)
        lay.addWidget(box)

    def _save(self) -> None:
        self.acc.set_chars(self.game, self.editor.value())
        try:
            self.repo.save_account(self.acc)
        except RepoError as e:
            QMessageBox.warning(self, "저장 안 됨", str(e))
            return
        self.accept()


def worker_combo(repo, current: str | None) -> QComboBox | None:
    """클라우드 관리자에게만 담당자 선택 상자를 만들어 준다."""
    if not (repo.is_cloud and repo.me.is_admin):
        return None
    box = QComboBox()
    box.addItem("지정 안 함 (관리자만 봄)", None)
    try:
        workers = [w for w in repo.list_workers() if w.role == "worker"]
    except RepoError:
        workers = []
    for w in workers:
        box.addItem(w.display_name, w.id)
    idx = box.findData(current)
    box.setCurrentIndex(idx if idx >= 0 else 0)
    return box


class AccountDialog(QDialog):
    def __init__(self, repo: Repository, acc: Account | None = None, parent=None):
        super().__init__(parent)
        self.repo = repo
        self.acc = copy.deepcopy(acc) if acc else Account()
        self.can_save = repo.me.can("can_edit_account" if acc else "can_add_account")
        self.setWindowTitle(("계정 수정" if self.can_save else "계정 정보") if acc else "계정 추가")
        a = self.acc

        form = QFormLayout()
        self.worker = worker_combo(repo, a.worker_id)
        if self.worker:
            form.addRow("담당 근무자", self.worker)
        self.owner = QLineEdit(a.owner)
        self.contact = QLineEdit(a.contact)
        self.provider = QComboBox()
        self.provider.setEditable(True)
        self.provider.addItems(PROVIDERS)
        self.provider.setCurrentText(a.provider)
        self.login = QLineEdit(a.login_id)
        self.pw = PasswordField(a.password)
        self.tag = QLineEdit(a.tag)
        self.mr_ban = BanField(a.mr_ban)
        self.pl_ban = BanField(a.pl_ban)
        self.withdrawn = QCheckBox("탈퇴한 계정 (자리에서 빠지고 배정할 수 없어요)")
        self.withdrawn.setChecked(a.withdrawn)
        self.note = QPlainTextEdit(a.note)
        self.note.setFixedHeight(70)
        form.addRow(section("명의자"))
        form.addRow("이름", self.owner)
        form.addRow("연락처", self.contact)
        form.addRow(section("로그인"))
        form.addRow("유형", self.provider)
        form.addRow("아이디 *", self.login)
        form.addRow("비밀번호", self.pw)
        form.addRow("메월코드", self.tag)
        form.addRow(section("상태"))
        form.addRow("메랜정지", self.mr_ban)
        form.addRow("플래닛정지", self.pl_ban)
        form.addRow("", self.withdrawn)
        form.addRow(section("메모"))
        form.addRow("비고", self.note)

        self.editors = {g: CharacterEditor(g, a.chars(g), self.can_save) for g in GAMES}

        box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        box.button(QDialogButtonBox.Save).setText("저장")
        box.button(QDialogButtonBox.Save).setObjectName("primary")
        box.button(QDialogButtonBox.Cancel).setText("취소")
        box.accepted.connect(self._save)
        box.rejected.connect(self.reject)
        box.button(QDialogButtonBox.Save).setEnabled(self.can_save)

        self.resize(px(1080), px(680))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        if not self.can_save:
            lay.addWidget(muted("수정 권한이 없어서 보기만 할 수 있어요. (비번 보기/복사는 돼요)"))
        if a.location:
            lay.addWidget(muted(f"현재 위치: {a.location.text()}"))
        cols = QHBoxLayout()
        cols.setSpacing(24)
        left = QWidget()
        left.setLayout(form)
        left.setFixedWidth(px(470))
        cols.addWidget(left)
        right = QVBoxLayout()
        right.setSpacing(12)
        for g in GAMES:
            right.addWidget(self.editors[g], 1)
        cols.addLayout(right, 1)
        lay.addLayout(cols, 1)
        lay.addWidget(box)

    def _save(self) -> None:
        a = self.acc
        if self.worker:
            a.worker_id = self.worker.currentData()
        a.owner = self.owner.text()
        a.contact = self.contact.text()
        a.provider = self.provider.currentText().strip()
        a.login_id = self.login.text()
        a.password = self.pw.text()
        a.tag = self.tag.text()
        a.mr_ban = self.mr_ban.value()
        a.pl_ban = self.pl_ban.value()
        for b in (a.mr_ban, a.pl_ban):
            if b.until and not DATE_RE.match(b.until):
                QMessageBox.warning(self, "확인 필요", "정지 해제일은 2027-06-14 형식으로 입력하세요.")
                return
        a.withdrawn = self.withdrawn.isChecked()
        a.note = self.note.toPlainText().strip()
        a.characters = []
        for g in GAMES:
            a.characters += self.editors[g].value()
        if a.withdrawn and a.location:
            if QMessageBox.question(self, "탈퇴 처리",
                                    f"이 계정은 {a.location.text()}에 들어 있어요. 탈퇴로 바꾸면 자리에서 빠져요. 계속할까요?") \
                    != QMessageBox.Yes:
                return
        try:
            self.repo.save_account(a)
        except RepoError as e:
            QMessageBox.warning(self, "저장 안 됨", str(e))
            return
        self.accept()


class PcDialog(QDialog):
    def __init__(self, repo: Repository, pc: PC | None = None, next_no: int = 1, parent=None):
        super().__init__(parent)
        self.repo = repo
        self.pc = copy.deepcopy(pc) if pc else PC(no=next_no)
        self.deleted = False
        p = self.pc
        self.can_save = repo.me.is_admin or (pc is not None and repo.me.can("can_edit_pc"))
        self.setWindowTitle(("컴퓨터 수정" if self.can_save else "컴퓨터 정보") if pc else "컴퓨터 추가")
        self.resize(px(460), px(460))

        form = QFormLayout()
        self.worker = worker_combo(repo, p.worker_id)
        if self.worker:
            form.addRow("담당 근무자", self.worker)
        self.no = QSpinBox()
        self.no.setRange(1, 9999)
        self.no.setValue(p.no)
        self.name = QLineEdit(p.name)
        self.remote_t = QLineEdit(p.remote_t)
        self.anydesk = QLineEdit(p.anydesk_id)
        self.anydesk_pw = PasswordField(p.anydesk_pw)
        self.vpn = QLineEdit(p.vpn)
        self.ld = QLineEdit(p.ld_cloud)
        self.slots = QSpinBox()
        self.slots.setRange(1, 20)
        self.slots.setValue(p.slot_count)
        self.note = QPlainTextEdit(p.note)
        self.note.setFixedHeight(60)
        form.addRow(section("컴퓨터"))
        form.addRow("번호", self.no)
        form.addRow("이름", self.name)
        form.addRow("자리 수", self.slots)
        form.addRow(section("원격 접속"))
        form.addRow("리모트T", self.remote_t)
        form.addRow("AnyDesk", self.anydesk)
        form.addRow("AnyDesk 비번", self.anydesk_pw)
        form.addRow("VPN 세팅", self.vpn)
        form.addRow("LD클라우드", self.ld)
        form.addRow(section("메모"))
        form.addRow("비고", self.note)

        box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        box.button(QDialogButtonBox.Save).setText("저장")
        box.button(QDialogButtonBox.Save).setObjectName("primary")
        box.button(QDialogButtonBox.Cancel).setText("취소")
        box.accepted.connect(self._save)
        box.rejected.connect(self.reject)
        box.button(QDialogButtonBox.Save).setEnabled(self.can_save)
        lay = QVBoxLayout(self)
        if not self.can_save:
            lay.addWidget(muted("수정 권한이 없어서 보기만 할 수 있어요."))
        lay.addLayout(form)
        bottom = QHBoxLayout()
        if pc and repo.me.is_admin:
            dele = QPushButton("컴퓨터 삭제")
            dele.clicked.connect(self._delete)
            bottom.addWidget(dele)
        bottom.addStretch(1)
        bottom.addWidget(box)
        lay.addLayout(bottom)

    def _save(self) -> None:
        p = self.pc
        if self.worker:
            p.worker_id = self.worker.currentData()
        p.no = self.no.value()
        p.name = self.name.text()
        p.remote_t = self.remote_t.text()
        p.anydesk_id = self.anydesk.text()
        p.anydesk_pw = self.anydesk_pw.text()
        p.vpn = self.vpn.text()
        p.ld_cloud = self.ld.text()
        p.slot_count = self.slots.value()
        p.note = self.note.toPlainText().strip()
        try:
            self.repo.save_pc(p)
        except RepoError as e:
            QMessageBox.warning(self, "저장 안 됨", str(e))
            return
        self.accept()

    def _delete(self) -> None:
        used = sum(1 for x in self.pc.slots if x)
        msg = f"{self.pc.title()} 컴퓨터를 삭제할까요?"
        if used:
            msg += f"\n들어 있는 계정 {used}개는 사용가능으로 돌아가요."
        if QMessageBox.question(self, "컴퓨터 삭제", msg) == QMessageBox.Yes:
            try:
                self.repo.delete_pc(self.pc.id)
            except RepoError as e:
                QMessageBox.warning(self, "삭제 안 됨", str(e))
                return
            self.deleted = True
            self.accept()
