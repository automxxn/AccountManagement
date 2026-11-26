from __future__ import annotations

import copy
import re

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ..db import Repository, RepoError
from ..models import GAMES, PC, PROVIDERS, Account, Ban, Character
from .common import copy_text, muted

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


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
    def __init__(self, ban: Ban, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.check = QCheckBox("정지")
        self.check.setChecked(ban.banned)
        self.until = QLineEdit(ban.until)
        self.until.setPlaceholderText("해제일 2027-06-14 (비우면 기한 없음)")
        self.until.setEnabled(ban.banned)
        self.check.toggled.connect(self.until.setEnabled)
        lay.addWidget(self.check)
        lay.addWidget(self.until, 1)

    def value(self) -> Ban:
        return Ban(self.check.isChecked(), self.until.text().strip() if self.check.isChecked() else "")


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
        self.resize(620, 660)
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
        form.addRow("명의자", self.owner)
        form.addRow("연락처", self.contact)
        form.addRow("유형", self.provider)
        form.addRow("아이디 *", self.login)
        form.addRow("비밀번호", self.pw)
        form.addRow("메월닉", self.tag)
        form.addRow("메랜정지", self.mr_ban)
        form.addRow("플래닛정지", self.pl_ban)
        form.addRow("", self.withdrawn)
        form.addRow("비고", self.note)

        self.chars = QTableWidget(0, 3)
        self.chars.setHorizontalHeaderLabels(["게임", "닉네임", "레벨/직업"])
        self.chars.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.chars.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.chars.verticalHeader().setVisible(False)
        for c in a.characters:
            self._add_char_row(c)
        add_mr = QPushButton("+ 메랜 캐릭터")
        add_mr.clicked.connect(lambda: self._add_char_row(Character("메랜")))
        add_pl = QPushButton("+ 플래닛 캐릭터")
        add_pl.clicked.connect(lambda: self._add_char_row(Character("플래닛")))
        rm = QPushButton("선택 캐릭터 삭제")
        rm.clicked.connect(self._remove_char_row)
        btns = QHBoxLayout()
        btns.addWidget(add_mr)
        btns.addWidget(add_pl)
        btns.addStretch(1)
        btns.addWidget(rm)

        box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        box.button(QDialogButtonBox.Save).setText("저장")
        box.button(QDialogButtonBox.Cancel).setText("취소")
        box.accepted.connect(self._save)
        box.rejected.connect(self.reject)
        box.button(QDialogButtonBox.Save).setEnabled(self.can_save)
        for b in (add_mr, add_pl, rm):
            b.setEnabled(self.can_save)

        lay = QVBoxLayout(self)
        if not self.can_save:
            lay.addWidget(muted("수정 권한이 없어서 보기만 할 수 있어요. (비번 보기/복사는 돼요)"))
        if a.location:
            lay.addWidget(muted(f"현재 위치: {a.location.text()}"))
        lay.addLayout(form)
        lay.addWidget(QLabel("캐릭터"))
        lay.addWidget(self.chars, 1)
        lay.addLayout(btns)
        lay.addWidget(box)

    def _add_char_row(self, c: Character) -> None:
        r = self.chars.rowCount()
        self.chars.insertRow(r)
        game = QComboBox()
        game.addItems(GAMES)
        game.setCurrentText(c.game)
        self.chars.setCellWidget(r, 0, game)
        self.chars.setItem(r, 1, QTableWidgetItem(c.nickname))
        self.chars.setItem(r, 2, QTableWidgetItem(c.level_job))

    def _remove_char_row(self) -> None:
        rows = sorted({i.row() for i in self.chars.selectedIndexes()}, reverse=True)
        if not rows and self.chars.currentRow() >= 0:
            rows = [self.chars.currentRow()]
        for r in rows:
            self.chars.removeRow(r)

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
        for r in range(self.chars.rowCount()):
            game = self.chars.cellWidget(r, 0).currentText()
            nick = (self.chars.item(r, 1) or QTableWidgetItem("")).text()
            job = (self.chars.item(r, 2) or QTableWidgetItem("")).text()
            a.characters.append(Character(game, nick, job))
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
        self.resize(460, 440)

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
        form.addRow("번호", self.no)
        form.addRow("이름", self.name)
        form.addRow("리모트T", self.remote_t)
        form.addRow("AnyDesk", self.anydesk)
        form.addRow("AnyDesk 비번", self.anydesk_pw)
        form.addRow("VPN 세팅", self.vpn)
        form.addRow("LD클라우드", self.ld)
        form.addRow("자리 수", self.slots)
        form.addRow("비고", self.note)

        box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        box.button(QDialogButtonBox.Save).setText("저장")
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
