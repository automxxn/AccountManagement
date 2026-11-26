"""시작 흐름: 연결 방식 선택 → (클라우드) 로그인 → 팀 암호 풀기."""
from __future__ import annotations

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QProgressBar, QRadioButton, QVBoxLayout, QWidget,
)

from ..cloud import CloudRepository
from ..crypto import protect_key, unprotect_key
from ..db import Repository, RepoError
from .common import T, button, muted, px

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


def _token_key(url: str) -> str:
    return "refresh_token/" + url


def save_auto_login(url: str, refresh_token: str | None) -> None:
    """자동 로그인이 켜져 있으면 로그인 유지 토큰을 이 PC의 Windows 계정으로 잠가서 저장한다."""
    s = settings()
    if refresh_token and s.value("auto_login", False, type=bool):
        s.setValue(_token_key(url), protect_key(refresh_token.encode("utf-8")))


def clear_auto_login(url: str) -> None:
    s = settings()
    s.setValue("auto_login", False)
    s.remove(_token_key(url))


def stored_token(url: str) -> str | None:
    s = settings()
    if not s.value("auto_login", False, type=bool):
        return None
    raw = s.value(_token_key(url), "")
    data = unprotect_key(raw) if raw else None
    return data.decode("utf-8") if data else None


class LoginDialog(QDialog):
    def __init__(self, repo: CloudRepository, parent=None, message: str = ""):
        super().__init__(parent)
        self.repo = repo
        self.setWindowTitle("로그인")
        self.resize(px(420), px(280))
        s = settings()
        self.login = QLineEdit(s.value("last_login", ""))
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.Password)
        self.name = QLineEdit()
        self.name.setPlaceholderText("변경 기록에 보일 이름")
        self.pw2 = QLineEdit()
        self.pw2.setEchoMode(QLineEdit.Password)
        self.auto = QCheckBox("자동 로그인 (다음부터 이 PC에서는 바로 로그인)")
        self.auto.setChecked(s.value("auto_login", True, type=bool))
        form = QFormLayout()
        form.addRow("아이디", self.login)
        form.addRow("비밀번호", self.pw)
        self.name_label, self.pw2_label = QLabel("이름"), QLabel("비밀번호 확인")
        form.addRow(self.name_label, self.name)
        form.addRow(self.pw2_label, self.pw2)
        form.addRow("", self.auto)

        # 아래 버튼 줄: [연결 설정] ……… [☐ 가입 요청] [로그인] [종료]
        self.signup = QCheckBox("가입 요청")
        self.signup.setObjectName("checkButton")
        self.signup.setCursor(Qt.PointingHandCursor)
        self.signup.setToolTip("처음 사용하면 체크하고 이름과 비밀번호 확인을 입력하세요")
        self.signup.toggled.connect(self._toggle)
        self.ok_btn = button("로그인", "primary", self._go)
        self.ok_btn.setDefault(True)
        btns = QHBoxLayout()
        btns.addWidget(button("연결 설정", "", self._connection))
        btns.addStretch(1)
        btns.addWidget(self.signup)
        btns.addWidget(self.ok_btn)
        btns.addWidget(button("종료", "", self.reject))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(px(20), px(16), px(20), px(16))
        if message:
            m = QLabel(message)
            m.setWordWrap(True)
            m.setStyleSheet(f"color:{T('danger')};")
            lay.addWidget(m)
        lay.addLayout(form)
        lay.addStretch(1)
        lay.addLayout(btns)
        self._toggle(False)
        (self.pw if self.login.text() else self.login).setFocus()

    def _connection(self) -> None:
        if ConnectionDialog(self).exec():
            self.done(2)  # 설정이 바뀌었으니 처음부터 다시

    def _toggle(self, on: bool) -> None:
        for w in (self.name, self.pw2, self.name_label, self.pw2_label):
            w.setVisible(on)
        self.ok_btn.setText("가입 요청 보내기" if on else "로그인")

    def _go(self) -> None:
        login, pw = self.login.text().strip(), self.pw.text()
        if not login or not pw:
            QMessageBox.warning(self, "확인 필요", "아이디와 비밀번호를 입력하세요.")
            return
        s = settings()
        s.setValue("auto_login", self.auto.isChecked())
        if not self.auto.isChecked():
            clear_auto_login(self.repo.url)
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
        s.setValue("last_login", login)
        self.accept()


class AutoLoginDialog(QDialog):
    """저장된 정보로 잠깐(1초) 뒤에 자동 로그인. 그 사이 '직접 로그인'을 누르면 멈춘다."""

    WAIT_MS = 1000

    def __init__(self, repo: CloudRepository, token: str, parent=None):
        super().__init__(parent)
        self.repo = repo
        self.token = token
        self.error = ""
        self.setWindowTitle("자동 로그인")
        self.resize(px(380), px(150))
        who = settings().value("last_login", "") or "저장된 계정"
        lay = QVBoxLayout(self)
        lay.setContentsMargins(px(20), px(16), px(20), px(16))
        self.msg = QLabel(f"<b>{who}</b> 계정으로 자동 로그인할게요…")
        lay.addWidget(self.msg)
        self.bar = QProgressBar()
        self.bar.setRange(0, self.WAIT_MS)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(px(6))
        lay.addWidget(self.bar)
        lay.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        self.cancel_btn = button("직접 로그인", "", self.reject, "자동 로그인을 멈추고 로그인 창을 열어요")
        row.addWidget(self.cancel_btn)
        lay.addLayout(row)
        self._t = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(50)

    def _tick(self) -> None:
        self._t += 50
        self.bar.setValue(min(self._t, self.WAIT_MS))
        if self._t >= self.WAIT_MS:
            self.timer.stop()
            self.cancel_btn.setEnabled(False)
            self.msg.setText("로그인 중…")
            QApplication.processEvents()
            try:
                self.repo.sign_in_with_token(self.token)
            except RepoError as e:
                self.error = str(e)
                self.reject()
                return
            self.accept()

    def reject(self) -> None:
        self.timer.stop()
        super().reject()


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
    message = ""
    try_auto = True
    while True:
        if s.value("mode") != "cloud":
            return Repository()
        repo = CloudRepository(s.value("url"), s.value("anon_key"))
        repo.on_session = lambda token, url=repo.url: save_auto_login(url, token)
        token = stored_token(repo.url) if try_auto else None
        try_auto = False
        if token:
            auto = AutoLoginDialog(repo, token)
            if auto.exec():
                break
            if auto.error:
                clear_auto_login(repo.url)
                s.setValue("auto_login", True)  # 다시 로그인하면 또 저장되게
                message = auto.error
        result = LoginDialog(repo, message=message).exec()
        message = ""
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
