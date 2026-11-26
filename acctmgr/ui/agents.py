"""PC 조종 탭 (클라우드): 각 컴퓨터의 LD CLOUD 실행기에 명령을 보내고, 실행기 설정을 바꾸고, 새 실행기를 연결한다.

- 실행기는 각 PC에서 트레이에 떠 있고, 몇 초 안에 명령을 받아 실행한 뒤 결과와 진행 로그를 올린다.
- A 로그인 = 그 컴퓨터 1자리 계정, B 로그인 = 2자리 계정 (작업장 프로그램이 그 PC만 열 수 있게 잠가서 보내 둠).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout,
    QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from ..db import RepoError
from ..models import AGENT_KINDS, COMMAND_STATUS, Agent
from .common import T, button, muted, page_header, px, run_safely, style_table

COLS = ["", "번호", "컴퓨터", "실행기", "지금 상태", "A (1자리)", "B (2자리)", "마지막 명령", "결과", ""]
REFRESH_MS = 4000

# 실행기 설정 항목 (키, 이름, 기본값)
CHECKS = [
    ("reopen", "재시작 후 기다렸다가 다시 열기", True),
    ("minimize_ld", "작업이 끝나면 LD CLOUD 창 최소화", True),
    ("autostart_open", "윈도우 켜질 때 자동으로 클라우드 열기", True),
]
HOTKEYS = [("hk_open", "시작 단축키"), ("hk_restart", "재시작 단축키"), ("hk_a", "A 로그인 단축키"), ("hk_b", "B 로그인 단축키")]


def _ago(sec: float | None) -> str:
    if sec is None:
        return "연락 없음"
    sec = max(0, int(sec))
    if sec < 60:
        return f"{sec}초 전"
    if sec < 3600:
        return f"{sec // 60}분 전"
    if sec < 86400:
        return f"{sec // 3600}시간 전"
    return f"{sec // 86400}일 전"


def _item(text: str, center: bool = False) -> QTableWidgetItem:
    it = QTableWidgetItem(text)
    it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
    if center:
        it.setTextAlignment(Qt.AlignCenter)
    return it


class AgentSettingsDialog(QDialog):
    """실행기 설정 (PC에서는 바꿀 수 없고 여기서만 바꾼다)."""

    def __init__(self, repo, pc, agent: Agent | None, parent=None):
        super().__init__(parent)
        self.repo, self.pc, self.agent = repo, pc, agent
        self.unlinked = False
        self.setWindowTitle(f"실행기 설정 - {pc.no}. {pc.name}")
        self.resize(px(620), px(640))
        cur = dict((agent.state.get("cfg") if agent else None) or {})  # PC에 지금 저장된 값
        cur.update(pc.agent_settings or {})                              # 여기서 정한 값이 우선
        self.cloud = QComboBox()
        self.cloud.setEditable(True)
        items = list(agent.devices) if agent else []
        if cur.get("cloud") and cur["cloud"] not in items:
            items.insert(0, cur["cloud"])
        self.cloud.addItems(items)
        self.cloud.setCurrentText(cur.get("cloud", ""))
        self.cloud.lineEdit().setPlaceholderText("LD CLOUD 기기 (이름 #ID)")
        self.wait = QSpinBox()
        self.wait.setRange(10, 1800)
        self.wait.setSingleStep(1)  # 화살표/휠 한 번에 1초
        self.wait.setSuffix(" 초")
        self.wait.setMinimumWidth(px(130))
        self.wait.setValue(int((pc.agent_settings or {}).get("restart_wait") or 120))  # 처음엔 120초
        self.checks = {}
        form = QFormLayout()
        crow = QHBoxLayout()
        crow.addWidget(self.cloud, 1)
        crow.addWidget(self._cmd_btn("목록 다시 읽기", "reload_devices", "그 PC의 실행기가 LD CLOUD 기기 목록을 다시 읽어요"))
        form.addRow("열 클라우드", crow)
        if pc.ld_cloud:
            form.addRow("", muted(f"작업장의 LD클라우드 칸: {pc.ld_cloud}"))
        wrow = QHBoxLayout()
        wrow.addWidget(self.wait)
        wrow.addWidget(muted("재시작한 뒤 다시 열 때까지 기다리는 시간"))
        wrow.addStretch(1)
        form.addRow("재시작 대기", wrow)
        for key, label, default in CHECKS:
            cb = QCheckBox(label)
            cb.setChecked(bool(cur.get(key, default)))
            self.checks[key] = cb
            form.addRow("", cb)
        # 로그인 전에 먼저 재시작 (A/B 한 묶음 + 전체 선택)
        group = QGroupBox("로그인 전에 먼저 재시작")
        gl = QHBoxLayout(group)
        self.before_all = QCheckBox("전체")
        self.before_all.setTristate(False)
        gl.addWidget(self.before_all)
        gl.addSpacing(px(12))
        for key, label in (("restart_before_a", "A 로그인"), ("restart_before_b", "B 로그인")):
            cb = QCheckBox(label)
            cb.setChecked(bool(cur.get(key, False)))
            cb.toggled.connect(self._sync_all)
            self.checks[key] = cb
            gl.addWidget(cb)
        gl.addStretch(1)
        self.before_all.clicked.connect(self._set_all)
        self._sync_all()
        form.addRow("", group)
        self.hk_on = QCheckBox("단축키 사용 (PC에서 직접 누를 때)")
        self.hk_on.setChecked(bool(cur.get("hotkeys_on", False)))
        form.addRow("", self.hk_on)
        self.hk = {}
        for key, label in HOTKEYS:
            e = QLineEdit(cur.get(key, ""))
            e.setPlaceholderText("예: Ctrl+Alt+F1")
            self.hk[key] = e
            form.addRow(label, e)
        # 그 PC의 프로그램 위치 (실행기가 알려 준 값)
        ld = cur.get("ld_path", "")
        lrow = QHBoxLayout()
        lrow.addWidget(self._path_label(ld, "아직 못 찾음"), 1)
        lrow.addWidget(self._cmd_btn("자동으로 찾기", "find_ld", "그 PC에서 LD CLOUD 설치 위치를 다시 찾아요"))
        form.addRow("LD CLOUD 위치", lrow)
        for key in ("AMP", "MAP"):
            low = key.lower()
            row = QHBoxLayout()
            row.addWidget(self._path_label(cur.get(low + "_path", ""), "아직 없음 (한 번 실행하면 저장됨)"), 1)
            row.addWidget(self._cmd_btn("폴더 열기", low + "_folder", "그 PC 화면에 폴더(탐색기)를 띄워요"))
            row.addWidget(self._cmd_btn("지우기", low + "_clear", "지우면 다음 실행 때 그 PC에서 다시 찾아요"))
            form.addRow(f"{key} 위치", row)
        self.cmd_msg = muted("")

        lay = QVBoxLayout(self)
        if agent is None:
            lay.addWidget(muted("이 컴퓨터에 연결된 실행기가 아직 없어요. 설정은 저장해 두면 연결될 때 적용돼요."))
        else:
            lay.addWidget(muted(f"실행기: {agent.machine} · v{agent.version} · {_ago(agent.seconds_ago)}"))
        lay.addLayout(form)
        lay.addWidget(self.cmd_msg)
        lay.addStretch(1)
        row = QHBoxLayout()
        if agent is not None and repo.me.is_admin:
            row.addWidget(button("연결 끊기", "danger", self._unlink, "이 실행기를 이 컴퓨터에서 떼어내요"))
        row.addStretch(1)
        box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        box.button(QDialogButtonBox.Save).setText("저장")
        box.button(QDialogButtonBox.Cancel).setText("취소")
        box.accepted.connect(self._save)
        box.rejected.connect(self.reject)
        row.addWidget(box)
        lay.addLayout(row)

    def _path_label(self, path: str, empty: str) -> QLabel:
        lab = QLabel(path or empty)
        lab.setToolTip(path)
        lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lab.setMinimumWidth(px(200))
        if not path:
            lab.setStyleSheet(f"color:{T('muted')};")
        return lab

    def _cmd_btn(self, text: str, kind: str, tip: str):
        b = button(text, "", lambda: self._send(kind), tip)
        b.setEnabled(self.agent is not None)
        return b

    def _send(self, kind: str) -> None:
        if run_safely(self, self.repo.send_command, self.pc.id, kind):
            self.cmd_msg.setText(f"[{AGENT_KINDS[kind]}] 명령을 보냈어요. 결과는 PC 조종 화면의 명령 기록에 나와요 "
                                 "(위치 값은 몇 초 뒤 이 창을 다시 열면 바뀌어요).")

    def _before(self) -> list:
        return [self.checks["restart_before_a"], self.checks["restart_before_b"]]

    def _sync_all(self, *_):
        """A/B가 둘 다 켜졌으면 '전체'도 켜짐, 하나라도 꺼지면 꺼짐."""
        self.before_all.blockSignals(True)
        self.before_all.setChecked(all(cb.isChecked() for cb in self._before()))
        self.before_all.blockSignals(False)

    def _set_all(self, on: bool) -> None:
        for cb in self._before():
            cb.blockSignals(True)
            cb.setChecked(on)
            cb.blockSignals(False)
        self._sync_all()

    def value(self) -> dict:
        v = {"cloud": self.cloud.currentText().strip(), "restart_wait": self.wait.value(),
             "hotkeys_on": self.hk_on.isChecked()}
        for key, cb in self.checks.items():
            v[key] = cb.isChecked()
        for key, e in self.hk.items():
            v[key] = e.text().strip()
        return v

    def _save(self) -> None:
        if not self.value()["cloud"]:
            QMessageBox.warning(self, "확인 필요", "열 클라우드를 고르세요.")
            return
        if run_safely(self, self.repo.set_agent_settings, self.pc.id, self.value()):
            self.accept()

    def _unlink(self) -> None:
        if QMessageBox.question(self, "연결 끊기", f"'{self.agent.machine}' 실행기를 이 컴퓨터에서 떼어낼까요?\n"
                                "다시 연결하기 전까지 이 컴퓨터에는 명령을 보낼 수 없어요.") != QMessageBox.Yes:
            return
        if run_safely(self, self.repo.link_agent, self.agent.user_id, None):
            self.unlinked = True
            self.accept()


class AgentsTab(QWidget):
    def __init__(self, repo):
        super().__init__()
        self.setObjectName("page")
        self.repo = repo
        self.pcs = []
        self.agents: dict[int, Agent] = {}
        self.pending: list[Agent] = []
        self.commands: dict[int, list[dict]] = {}
        self.acc_names: dict[int, str] = {}
        self.checked: set[int] = set()
        self.current_pc: int | None = None

        hint = QLabel("각 컴퓨터의 LD CLOUD 실행기에 명령을 보내요. 체크한 컴퓨터에 한 번에 보낼 수 있어요.\n"
                      "A 로그인 = 그 컴퓨터 1자리 계정, B 로그인 = 2자리 계정. 실행기 설정은 오른쪽 [설정]에서만 바꿔요.")
        hint.setWordWrap(True)
        hint.setObjectName("hintBox")

        bar = QHBoxLayout()
        self.all_box = QCheckBox("전체 선택")
        self.all_box.toggled.connect(self._check_all)
        bar.addWidget(self.all_box)
        bar.addSpacing(12)
        self.sel_label = muted("선택한 컴퓨터 0대에:")
        bar.addWidget(self.sel_label)
        for kind in ("start", "restart", "close", "login_a", "login_b"):
            bar.addWidget(button(AGENT_KINDS[kind], "primary" if kind.startswith("login") else "",
                                 lambda _=False, k=kind: self._send_checked(k)))
        bar.addWidget(button("중지", "danger", lambda: self._send_checked("stop"), "하던 작업을 멈추고 기다리는 명령을 취소해요"))
        bar.addStretch(1)
        bar2 = QHBoxLayout()
        bar2.addSpacing(px(4))
        bar2.addWidget(muted("다른 프로그램:"))
        for kind in ("amp_run", "amp_stop", "map_run", "map_stop"):
            bar2.addWidget(button(AGENT_KINDS[kind], "", lambda _=False, k=kind: self._send_checked(k)))
        bar2.addSpacing(px(16))
        bar2.addWidget(muted("실행기:"))
        bar2.addWidget(button("실행기 다시 켜기", "", lambda: self._send_checked("restart_agent"),
                              "실행기를 껐다가 다시 켜요. 새 버전이 있으면 이때 업데이트돼요"))
        bar2.addStretch(1)

        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.verticalHeader().setVisible(False)
        style_table(self.table)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.itemSelectionChanged.connect(self._row_selected)

        # 아래: 고른 컴퓨터의 명령 기록과 진행 로그
        self.hist_title = muted("컴퓨터를 고르면 명령 기록과 진행 로그가 보여요.")
        self.hist = QTableWidget(0, 5)
        self.hist.setHorizontalHeaderLabels(["보낸 시각", "명령", "보낸 사람", "상태", "결과"])
        self.hist.verticalHeader().setVisible(False)
        style_table(self.hist)
        self.hist.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.hist.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.hist.horizontalHeader().setStretchLastSection(True)
        self.hist.itemSelectionChanged.connect(self._show_log)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("명령을 고르면 실행기가 보낸 진행 로그가 보여요.")
        bottom = QWidget()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(0, 8, 0, 0)
        bl.addWidget(self.hist_title)
        hs = QSplitter(Qt.Horizontal)
        hs.addWidget(self.hist)
        hs.addWidget(self.log)
        hs.setSizes([600, 400])
        bl.addWidget(hs, 1)

        # 연결 대기 실행기 (관리자)
        self.pending_box = QWidget()
        pl = QVBoxLayout(self.pending_box)
        pl.setContentsMargins(0, 8, 0, 0)
        pl.addWidget(QLabel("<b>연결 대기 실행기</b> — 새로 설치되거나 업데이트된 실행기예요. 어느 컴퓨터인지 골라 [연결]을 누르세요."))
        self.pend = QTableWidget(0, 5)
        self.pend.setHorizontalHeaderLabels(["PC 이름 (윈도우)", "버전", "마지막 연락", "연결할 컴퓨터", ""])
        self.pend.verticalHeader().setVisible(False)
        style_table(self.pend)
        self.pend.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.pend.setSelectionMode(QAbstractItemView.NoSelection)
        self.pend.horizontalHeader().setStretchLastSection(True)
        pl.addWidget(self.pend)

        split = QSplitter(Qt.Vertical)
        split.addWidget(self.table)
        split.addWidget(bottom)
        split.setSizes([520, 260])

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        lay.setSpacing(12)
        lay.addWidget(page_header("PC 조종", "LD CLOUD 실행기에 명령을 보내고 상태를 봐요",
                                  [button("새로고침", "", self.refresh)]))
        lay.addWidget(hint)
        lay.addLayout(bar)
        lay.addLayout(bar2)
        lay.addWidget(split, 1)
        lay.addWidget(self.pending_box)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)

    # ---------------------------------------------------------------- 데이터
    def showEvent(self, e) -> None:
        super().showEvent(e)
        self.timer.start(REFRESH_MS)

    def hideEvent(self, e) -> None:
        super().hideEvent(e)
        self.timer.stop()

    def refresh(self) -> None:
        """컴퓨터 목록과 계정 이름까지 다시 읽기 (페이지를 열 때, F5)."""
        self.pcs = self.repo.list_pcs()
        names = {}
        for a in self.repo.list_accounts():
            names[a.id] = f"[{a.provider}] {a.login_id}"
        self.acc_names = names
        try:
            self.repo.sync_pc_creds()
        except RepoError:
            pass
        self._tick()

    def _tick(self) -> None:
        """실행기 상태와 명령 기록만 다시 읽기 (몇 초마다)."""
        if not self.pcs and self.isVisible():
            pass
        try:
            agents = self.repo.list_agents()
            pc_ids = [p.id for p in self.pcs]
            cmds = self.repo.list_commands(pc_ids)
        except RepoError as e:
            self.hist_title.setText(f"서버 확인 중: {e}")
            return
        mine = {p.id for p in self.pcs}
        self.agents = {a.pc_id: a for a in agents if a.pc_id in mine}
        self.pending = [a for a in agents if a.pc_id is None]
        self.commands = {}
        for c in cmds:
            self.commands.setdefault(c["pc_id"], []).append(c)
        self._render()

    # ---------------------------------------------------------------- 표
    def _render(self) -> None:
        t = self.table
        sel = self.current_pc
        t.blockSignals(True)
        t.setRowCount(len(self.pcs))
        green, gray, red = QColor(T("success")), QColor(T("muted")), QColor(T("danger"))
        for r, pc in enumerate(self.pcs):
            cb = QCheckBox()
            cb.setChecked(pc.id in self.checked)
            cb.toggled.connect(lambda on, pid=pc.id: self._toggle(pid, on))
            box = QWidget()
            bl = QHBoxLayout(box)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setAlignment(Qt.AlignCenter)
            bl.addWidget(cb)
            t.setCellWidget(r, 0, box)
            no = _item(str(pc.no), True)
            no.setData(Qt.UserRole, pc.id)
            t.setItem(r, 1, no)
            t.setItem(r, 2, _item(pc.name))
            ag = self.agents.get(pc.id)
            if ag is None:
                st = _item("실행기 없음")
                st.setForeground(gray)
                now = _item("")
            else:
                st = _item(("● 켜짐" if ag.online else "● 꺼짐 (" + _ago(ag.seconds_ago) + ")") + f"  v{ag.version}")
                st.setForeground(green if ag.online else gray)
                s = ag.state or {}
                now = _item((("▶ " + s.get("job", "")) if s.get("busy") else s.get("last", "")) or "")
                now.setToolTip(s.get("last", ""))
            t.setItem(r, 3, st)
            t.setItem(r, 4, now)
            for c, slot in ((5, 1), (6, 2)):
                aid = pc.slots[slot - 1] if len(pc.slots) >= slot else None
                t.setItem(r, c, _item(self.acc_names.get(aid, "") if aid else "-"))
            last = (self.commands.get(pc.id) or [None])[0]
            if last:
                kind = _item(f"{AGENT_KINDS.get(last['kind'], last['kind'])} · {COMMAND_STATUS.get(last['status'], '')}")
                kind.setToolTip(f"{last['created_at']} {last.get('created_name', '')}")
                if last["status"] == "failed":
                    kind.setForeground(red)
                res = _item(last.get("result", ""))
                res.setToolTip(last.get("result", ""))
            else:
                kind, res = _item(""), _item("")
            t.setItem(r, 7, kind)
            t.setItem(r, 8, res)
            t.setCellWidget(r, 9, self._settings_btn(pc))
            if pc.id == sel:
                t.selectRow(r)
        t.blockSignals(False)
        self.sel_label.setText(f"선택한 컴퓨터 {len(self.checked)}대에:")
        self._render_pending()
        self._render_history()
        self.restyle()

    def _settings_btn(self, pc) -> QWidget:
        w = QWidget()
        l = QHBoxLayout(w)
        l.setContentsMargins(4, 2, 4, 2)
        l.addWidget(button("설정", "", lambda _=False, p=pc: self._settings(p)))
        return w

    def restyle(self) -> None:
        self.table.verticalHeader().setDefaultSectionSize(px(38))
        for c, w in enumerate([36, 50, 110, 160, 180, 150, 150, 140, 190, 70]):
            self.table.setColumnWidth(c, px(w))
        self.hist.verticalHeader().setDefaultSectionSize(px(30))
        for c, w in enumerate([120, 90, 90, 90]):
            self.hist.setColumnWidth(c, px(w))
        self.pend.verticalHeader().setDefaultSectionSize(px(40))
        for c, w in enumerate([180, 100, 100, 260]):
            self.pend.setColumnWidth(c, px(w))

    def _toggle(self, pc_id: int, on: bool) -> None:
        (self.checked.add if on else self.checked.discard)(pc_id)
        self.sel_label.setText(f"선택한 컴퓨터 {len(self.checked)}대에:")

    def _check_all(self, on: bool) -> None:
        self.checked = {p.id for p in self.pcs} if on else set()
        self._render()

    def _row_selected(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if rows:
            self.current_pc = self.table.item(rows[0].row(), 1).data(Qt.UserRole)
            self._render_history()

    # ---------------------------------------------------------------- 명령
    def _send_checked(self, kind: str) -> None:
        targets = [p for p in self.pcs if p.id in self.checked]
        if not targets and self.current_pc:
            targets = [p for p in self.pcs if p.id == self.current_pc]
        if not targets:
            QMessageBox.information(self, "PC 조종", "명령을 보낼 컴퓨터를 체크하거나 표에서 고르세요.")
            return
        no_agent = [p for p in targets if p.id not in self.agents]
        targets = [p for p in targets if p.id in self.agents]
        if not targets:
            QMessageBox.warning(self, "PC 조종", "고른 컴퓨터에 연결된 실행기가 없어요.")
            return
        if len(targets) > 1 and QMessageBox.question(
                self, "PC 조종", f"{len(targets)}대에 [{AGENT_KINDS[kind]}] 명령을 보낼까요?") != QMessageBox.Yes:
            return
        errors = []
        try:
            self.repo.sync_pc_creds()  # 로그인 전에 자리 계정이 최신인지
        except RepoError:
            pass
        for p in targets:
            try:
                self.repo.send_command(p.id, kind)
            except RepoError as e:
                errors.append(f"{p.no}. {p.name}: {e}")
        errors += [f"{p.no}. {p.name}: 연결된 실행기가 없음" for p in no_agent]
        self._tick()
        if errors:
            QMessageBox.warning(self, "일부 못 보냄", "\n".join(errors[:15]))

    def _settings(self, pc) -> None:
        dlg = AgentSettingsDialog(self.repo, pc, self.agents.get(pc.id), self)
        if dlg.exec():
            self.refresh()

    # ---------------------------------------------------------------- 아래 칸
    def _render_history(self) -> None:
        pc = next((p for p in self.pcs if p.id == self.current_pc), None)
        rows = self.commands.get(self.current_pc, []) if pc else []
        if pc:
            self.hist_title.setText(f"{pc.no}. {pc.name} — 최근 명령")
        keep = self.hist.currentRow()
        self.hist.blockSignals(True)
        self.hist.setRowCount(len(rows))
        for r, c in enumerate(rows):
            vals = [c["created_at"], AGENT_KINDS.get(c["kind"], c["kind"]), c.get("created_name", ""),
                    COMMAND_STATUS.get(c["status"], c["status"]), c.get("result", "")]
            for k, v in enumerate(vals):
                it = _item(v)
                it.setData(Qt.UserRole, c["id"])
                if c["status"] == "failed":
                    it.setForeground(QColor(T("danger")))
                self.hist.setItem(r, k, it)
        if rows:
            self.hist.selectRow(keep if 0 <= keep < len(rows) else 0)
        self.hist.blockSignals(False)
        self._show_log()

    def _show_log(self) -> None:
        r = self.hist.currentRow()
        rows = self.commands.get(self.current_pc, [])
        text = rows[r].get("log", "") if 0 <= r < len(rows) else ""
        if self.log.toPlainText() != text:
            self.log.setPlainText(text)
            self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def _render_pending(self) -> None:
        show = self.repo.me.is_admin and bool(self.pending)
        self.pending_box.setVisible(show)
        if not show:
            return
        taken = set(self.agents)
        self.pend.setRowCount(len(self.pending))
        for r, ag in enumerate(self.pending):
            self.pend.setItem(r, 0, _item(ag.machine))
            self.pend.setItem(r, 1, _item(ag.version))
            self.pend.setItem(r, 2, _item(_ago(ag.seconds_ago)))
            combo = QComboBox()
            combo.addItem("컴퓨터 고르기...", None)
            guess = None
            cloud = (ag.state.get("cfg") or {}).get("cloud", "")
            for p in self.pcs:
                combo.addItem(f"{p.no}. {p.name}" + ("  (실행기 있음)" if p.id in taken else ""), p.id)
                if guess is None and p.id not in taken and (
                        (p.ld_cloud and cloud and p.ld_cloud.strip() in cloud) or
                        (p.name and p.name.strip() and p.name.strip() in ag.machine)):
                    guess = combo.count() - 1
            if guess:
                combo.setCurrentIndex(guess)
            self.pend.setCellWidget(r, 3, combo)
            w = QWidget()
            l = QHBoxLayout(w)
            l.setContentsMargins(4, 2, 4, 2)
            l.addWidget(button("연결", "primary", lambda _=False, a=ag, c=combo: self._link(a, c)))
            l.addWidget(button("지우기", "", lambda _=False, a=ag: self._forget(a), "잘못 등록된 실행기를 목록에서 지워요"))
            l.addStretch(1)
            self.pend.setCellWidget(r, 4, w)
        self.pend.setFixedHeight(px(40) * min(len(self.pending), 4) + px(44))

    def _link(self, ag: Agent, combo: QComboBox) -> None:
        pid = combo.currentData()
        if pid is None:
            QMessageBox.information(self, "연결", "연결할 컴퓨터를 고르세요.")
            return
        if pid in self.agents and QMessageBox.question(
                self, "연결", "이 컴퓨터에는 이미 실행기가 있어요. 새 실행기로 바꿀까요?") != QMessageBox.Yes:
            return
        if run_safely(self, self.repo.link_agent, ag.user_id, pid):
            try:
                self.repo.sync_pc_creds()
            except RepoError:
                pass
            self._tick()

    def _forget(self, ag: Agent) -> None:
        if QMessageBox.question(self, "지우기", f"'{ag.machine}' 실행기를 목록에서 지울까요?\n"
                                "그 PC의 실행기가 다시 켜지면 또 나타나요.") != QMessageBox.Yes:
            return
        if run_safely(self, self.repo.forget_agent, ag.user_id):
            self._tick()
