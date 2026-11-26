"""시작 흐름: 연결 방식 선택 → (클라우드) 로그인 → 팀 암호 풀기."""
from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QMessageBox, QRadioButton,
    QVBoxLayout, QWidget,
)

from ..cloud import CloudRepository
from ..crypto import protect_key, unprotect_key
from ..db import Repository, RepoError
from .common import muted

SETTINGS = ("AccountManagement", "AccountManagement")
OLD_SETTINGS = ("계정관리", "계정관리")  # 이름을 바꾸기 전 설정


def settings() -> QSettings:
    s = QSettings(*SETTINGS)
    if not s.allKeys():
        old = QSettings(*OLD_SETTINGS)
        for k in old.allKeys():
            s.setValue(k, old.value(k))
    return s


class ConnectionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("연결 설정")
        self.resize(520, 300)
        s = settings()
        self.local = QRadioButton("이 PC에만 저장 (혼자 사용)")
        self.cloud = QRadioButton("클라우드 (여러 명이 같이 사용)")
        (self.cloud if s.value("mode", "local") == "cloud" else self.local).setChecked(True)
        self.url = QLineEdit(s.value("url", ""))
        self.url.setPlaceholderText("https://xxxx.supabase.co")
        self.key = QLineEdit(s.value("anon_key", ""))
        self.key.setPlaceholderText("anon public 키")
        form = QFormLayout()
        form.addRow("Project URL", self.url)
        form.addRow("anon 키", self.key)
        self.cloud_box = QWidget()
        self.cloud_box.setLayout(form)
        self.cloud.toggled.connect(self.cloud_box.setEnabled)
        self.cloud_box.setEnabled(self.cloud.isChecked())
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.button(QDialogButtonBox.Ok).setText("확인")
        box.button(QDialogButtonBox.Cancel).setText("취소")
        box.accepted.connect(self._ok)
        box.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(self.local)
        lay.addWidget(self.cloud)
        lay.addWidget(self.cloud_box)
        hint = muted("URL과 키는 관리자에게 받으세요. (Supabase 프로젝트 → Settings → API)")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        lay.addStretch(1)
        lay.addWidget(box)

    def _ok(self) -> None:
        s = settings()
        if self.cloud.isChecked():
            url, key = self.url.text().strip(), self.key.text().strip()
            if not url.startswith("https://") or not key:
                QMessageBox.warning(self, "확인 필요", "Project URL(https://로 시작)과 anon 키를 입력하세요.")
                return
            s.setValue("mode", "cloud")
            s.setValue("url", url)
            s.setValue("anon_key", key)
        else:
            s.setValue("mode", "local")
        self.accept()


class LoginDialog(QDialog):
    def __init__(self, repo: CloudRepository, parent=None):
        super().__init__(parent)
        self.repo = repo
        self.setWindowTitle("로그인")
        self.resize(380, 260)
        self.login = QLineEdit(settings().value("last_login", ""))
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.Password)
        self.signup = QCheckBox("처음 사용해요 (가입 요청)")
        self.name = QLineEdit()
        self.name.setPlaceholderText("변경 기록에 보일 이름")
        self.pw2 = QLineEdit()
        self.pw2.setEchoMode(QLineEdit.Password)
        form = QFormLayout()
        form.addRow("아이디", self.login)
        form.addRow("비밀번호", self.pw)
        form.addRow("", self.signup)
        self.name_label, self.pw2_label = QLabel("이름"), QLabel("비밀번호 확인")
        form.addRow(self.name_label, self.name)
        form.addRow(self.pw2_label, self.pw2)
        self.signup.toggled.connect(self._toggle)
        self._toggle(False)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.ok_btn = box.button(QDialogButtonBox.Ok)
        self.ok_btn.setText("로그인")
        box.button(QDialogButtonBox.Cancel).setText("종료")
        box.accepted.connect(self._go)
        box.rejected.connect(self.reject)
        conn = box.addButton("연결 설정", QDialogButtonBox.ResetRole)
        conn.clicked.connect(self._connection)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(box)
        (self.pw if self.login.text() else self.login).setFocus()

    def _connection(self) -> None:
        if ConnectionDialog(self).exec():
            self.done(2)  # 설정이 바뀌었으니 처음부터 다시

    def _toggle(self, on: bool) -> None:
        for w in (self.name, self.pw2, self.name_label, self.pw2_label):
            w.setVisible(on)
        if hasattr(self, "ok_btn"):
            self.ok_btn.setText("가입 요청" if on else "로그인")

    def _go(self) -> None:
        login, pw = self.login.text().strip(), self.pw.text()
        if not login or not pw:
            QMessageBox.warning(self, "확인 필요", "아이디와 비밀번호를 입력하세요.")
            return
        try:
            if self.signup.isChecked():
                if pw != self.pw2.text():
                    QMessageBox.warning(self, "확인 필요", "비밀번호 확인이 달라요.")
                    return
                if not self.name.text().strip():
                    QMessageBox.warning(self, "확인 필요", "이름을 입력하세요.")
                    return
                self.repo.sign_up(login, pw, self.name.text())
            else:
                self.repo.sign_in(login, pw)
        except RepoError as e:
            QMessageBox.warning(self, "로그인 실패", str(e))
            return
        settings().setValue("last_login", login)
        self.accept()


class PassphraseDialog(QDialog):
    def __init__(self, create: bool, parent=None):
        super().__init__(parent)
        self.create = create
        self.setWindowTitle("팀 암호 정하기" if create else "팀 암호 입력")
        self.resize(420, 220)
        self.p1 = QLineEdit()
        self.p1.setEchoMode(QLineEdit.Password)
        self.p2 = QLineEdit()
        self.p2.setEchoMode(QLineEdit.Password)
        form = QFormLayout()
        form.addRow("팀 암호", self.p1)
        if create:
            form.addRow("한 번 더", self.p2)
        text = ("계정 비번은 이 팀 암호로 잠가서 클라우드에 올려요. 근무자도 처음 한 번 이 암호를 입력해야 비번을 볼 수 있어요.\n"
                "잃어버리면 저장된 비번을 풀 수 없으니 꼭 따로 적어두세요. (8자 이상)") if create else \
            "관리자에게 받은 팀 암호를 입력하세요. 이 PC에서는 한 번만 입력하면 돼요."
        hint = muted(text)
        hint.setWordWrap(True)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.button(QDialogButtonBox.Ok).setText("확인")
        box.button(QDialogButtonBox.Cancel).setText("종료")
        box.accepted.connect(self._ok)
        box.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(hint)
        lay.addLayout(form)
        lay.addWidget(box)

    def _ok(self) -> None:
        if self.create and (len(self.p1.text()) < 8 or self.p1.text() != self.p2.text()):
            QMessageBox.warning(self, "확인 필요", "8자 이상으로 정하고, 두 칸을 똑같이 입력하세요.")
            return
        if not self.p1.text():
            return
        self.accept()

    def value(self) -> str:
        return self.p1.text()


def _unlock(repo: CloudRepository) -> bool:
    s = settings()
    store_key = "team_key/" + repo.url
    info = repo.team_key_info()
    if info is None:
        if not repo.me.is_admin:
            QMessageBox.information(None, "준비 중", "관리자가 아직 팀 암호를 정하지 않았어요. 잠시 후 다시 실행하세요.")
            return False
        dlg = PassphraseDialog(create=True)
        if not dlg.exec():
            return False
        key = repo.create_team_key(dlg.value())
        s.setValue(store_key, protect_key(key))
        return True
    stored = s.value(store_key, "")
    key = unprotect_key(stored) if stored else None
    if key and repo.unlock(key):
        return True
    while True:
        dlg = PassphraseDialog(create=False)
        if not dlg.exec():
            return False
        key = repo.unlock_with_passphrase(dlg.value())
        if key:
            s.setValue(store_key, protect_key(key))
            return True
        QMessageBox.warning(None, "팀 암호", "팀 암호가 맞지 않아요.")


def start_repository():
    """연결 방식에 맞는 저장소를 준비한다. 사용자가 취소하면 None."""
    s = settings()
    if not s.value("mode", ""):
        if not ConnectionDialog().exec():
            return None
    while True:
        if s.value("mode") != "cloud":
            return Repository()
        repo = CloudRepository(s.value("url"), s.value("anon_key"))
        result = LoginDialog(repo).exec()
        if result == 2:
            continue
        if not result:
            return None
        break
    if repo.me.role == "pending":
        QMessageBox.information(None, "승인 대기",
                                f"{repo.me.display_name}님, 가입 요청이 접수됐어요.\n관리자가 승인하면 사용할 수 있어요.")
        return None
    try:
        if not _unlock(repo):
            return None
    except RepoError as e:
        QMessageBox.warning(None, "오류", str(e))
        return None
    return repo
