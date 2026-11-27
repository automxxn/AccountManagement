"""PC 조종 탭 (클라우드): 각 컴퓨터의 LD CLOUD 실행기에 명령을 보내고, 실행기 설정을 바꾸고, 새 실행기를 연결한다.

- 실행기는 각 PC에서 트레이에 떠 있고, 몇 초 안에 명령을 받아 실행한 뒤 결과와 진행 로그를 올린다.
- A 로그인 = 그 컴퓨터 1자리 계정, B 로그인 = 2자리 계정 (작업장 프로그램이 그 PC만 열 수 있게 잠가서 보내 둠).
"""
from __future__ import annotations

import re

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QMenu,
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout, QLineEdit,
    QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QScrollArea, QSpinBox, QSplitter, QStackedWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..db import RepoError
from ..models import AGENT_KINDS, COMMAND_STATUS, GAMES, Agent
from .common import (
    T, FlowLayout, ToggleSwitch, button, fit_columns, group, muted, page_header, px, run_safely, style_table,
    wheel_only_when_focused, zoom_rows,
)
from . import sheet as _sheet
from .pcboard import PcBoard
from .sheet import SheetNav

COLS = ["", "번호", "컴퓨터", "실행기", "실행기 팀 (코드)", "지금 상태", "A (1자리)", "B (2자리)", "마지막 명령", "결과", ""]
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


def _secs(v: float | None) -> str:
    if v is None:
        return ""
    v = max(0.0, v)
    return f"{v:.1f}초" if v < 10 else (f"{int(v)}초" if v < 120 else f"{int(v // 60)}분 {int(v % 60)}초")


def _took(c: dict) -> str:
    """'받기 0.3초 · 실행 2초' (받기 = 보낸 뒤 PC가 가져가기까지)."""
    parts = []
    if c.get("pickup_s") is not None:
        parts.append("받기 " + _secs(c["pickup_s"]))
    if c.get("run_s") is not None:
        parts.append("실행 " + _secs(c["run_s"]))
    return " · ".join(parts)


def _agent_cloud(ag: Agent) -> str:
    """그 PC 실행기가 여는 클라우드 이름 ('이름 #ID' → 이름)."""
    return ((ag.state.get("cfg") or {}).get("cloud") or "").split(" #")[0].strip()


def cloud_id(c: str | None) -> str:
    """'클라우드22번 #5421329' → '5421329' (LD 기기 번호, 이름이 바뀌어도 그대로)."""
    c = c or ""
    return c.split("#", 1)[1].strip() if "#" in c else ""


def cloud_sort_key(c: str):
    """'클라우드2 …' < '클라우드10 …' 처럼 숫자 순서."""
    m = re.match(r"^(\D*)(\d+)", c or "")
    return (m.group(1), int(m.group(2)), c) if m else (c or "", 0, c or "")


def cloud_number(c: str | None) -> int | None:
    """'클라우드22번 쉬렐 #5421329' → 22"""
    m = re.match(r"^\D*(\d+)", (c or "").split(" #")[0])
    return int(m.group(1)) if m else None


def suggest_pc(cloud: str, pcs: list, linked: set, avoid: set = frozenset(), macs=()):
    """이 클라우드를 여는 실행기를 어느 컴퓨터에 연결하면 좋을지 추천. (pc, 이유) 또는 (None, '').

    1) 그 클라우드를 정해 둔 컴퓨터 (다른 실행기가 붙어 있어도 추천 → 바꾸기)
    2) 예전에 그 클라우드였던 컴퓨터 (초기화하기 전 값을 기억해 둔 것)
    3) 클라우드 번호와 컴퓨터 번호가 같은, 실행기 없는 컴퓨터
    """
    macs = set(macs or ())
    for p in pcs:
        if p.id not in avoid and getattr(p, "mac", "") and p.mac in macs:
            return p, "이 PC의 MAC이 고정된 컴퓨터"
    # 다른 PC의 MAC으로 고정된 컴퓨터는 클라우드가 같아도 추천하지 않는다
    avoid = set(avoid) | {p.id for p in pcs if getattr(p, "mac", "") and p.mac not in macs}
    cid = cloud_id(cloud)
    if cid:
        for p in pcs:
            if p.id not in avoid and cloud_id((p.agent_settings or {}).get("cloud")) == cid:
                return p, "이 클라우드를 정해 둔 컴퓨터" + (" (다른 실행기가 붙어 있음 → 바꾸기)" if p.id in linked else "")
        for p in pcs:
            if p.id not in avoid and cloud_id((p.agent_settings or {}).get("prev_cloud")) == cid:
                return p, "예전에 이 클라우드였던 컴퓨터" + (" (다른 실행기가 붙어 있음 → 바꾸기)" if p.id in linked else "")
    n = cloud_number(cloud)
    if n is not None:
        for p in pcs:
            if p.id not in avoid and p.no == n and p.id not in linked and not (p.agent_settings or {}).get("cloud"):
                return p, f"클라우드 번호({n})와 컴퓨터 번호가 같음 — 맞는지 확인하세요"
    return None, ""


def suggest_cloud(pc, devices: list, used: set) -> tuple:
    """클라우드가 안 정해진 컴퓨터에 추천할 클라우드. (클라우드, 이유) 또는 ('', '')."""
    prev = (pc.agent_settings or {}).get("prev_cloud") or ""
    if prev and cloud_id(prev) not in used:
        same = next((d for d in devices if cloud_id(d) == cloud_id(prev)), prev)
        return same, "예전에 이 컴퓨터가 쓰던 클라우드"
    for d in devices:
        if cloud_number(d) == pc.no and cloud_id(d) not in used:
            return d, "컴퓨터 번호와 같은 번호의 클라우드 — 맞는지 확인하세요"
    return "", ""


def reset_pc_launcher(repo, pc, agent: Agent | None) -> None:
    """이 컴퓨터의 실행기 초기화: 정해 둔 클라우드를 지우고(그래야 같은 컴퓨터로 다시 자동 연결되지 않음)
    연결된 실행기를 떼어낸다. 떼어낸 실행기는 연결 대기로 돌아간다.
    지운 클라우드는 'prev_cloud'로 기억해 두고 다음에 추천할 때만 쓴다 (자동 연결에는 안 씀)."""
    s = dict(pc.agent_settings or {})
    if "cloud" in s:
        s["prev_cloud"] = s.pop("cloud")
        repo.set_agent_settings(pc.id, s)
        pc.agent_settings = s
    if agent is not None:
        repo.link_agent(agent.user_id, None)      # 연결을 풀면 서버가 그 컴퓨터의 MAC 고정도 지움
    elif getattr(pc, "mac", ""):
        repo.set_pc_mac(pc.id, "")


def kind_label(kind: str, arg: str = "") -> str:
    """'AMP 실행' + 게임 → 'AMP 실행 (메랜)'"""
    name = AGENT_KINDS.get(kind, kind)
    return f"{name} ({arg})" if arg else name


def _item(text: str, center: bool = False) -> QTableWidgetItem:
    it = QTableWidgetItem(text)
    it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
    if center:
        it.setTextAlignment(Qt.AlignCenter)
    return it


class AgentSettingsDialog(QDialog):
    """실행기 설정 (PC에서는 바꿀 수 없고 여기서만 바꾼다).

    bulk에 컴퓨터 여러 대를 주면 '같은 설정 적용' 창: 열 클라우드와 프로그램 위치(컴퓨터마다 다름)는 빼고
    나머지 값을 그 컴퓨터들에 똑같이 저장한다. 처음 보이는 값은 첫 번째 컴퓨터 것.
    """

    def __init__(self, repo, pc, agent: Agent | None, parent=None, bulk: list | None = None,
                 all_pcs: list | None = None, linked: set | None = None, devices: list | None = None):
        super().__init__(parent)
        self.repo, self.pc, self.agent = repo, pc, agent
        self.linked = linked or set()
        self.bulk = bulk
        self.unlinked = False
        self.setWindowTitle(f"같은 설정 적용 - {len(bulk)}대" if bulk else f"실행기 설정 - {pc.no}. {pc.name}")
        self.resize(px(620), px(560 if bulk else 640))
        cur = dict((agent.state.get("cfg") if agent else None) or {})  # PC에 지금 저장된 값
        cur.update(pc.agent_settings or {})                              # 여기서 정한 값이 우선
        self.cloud = QComboBox()
        self.cloud.setEditable(True)
        items = sorted(set(devices or []) | set(agent.devices if agent else []), key=cloud_sort_key)
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
        wheel_only_when_focused(self.cloud, self.wait)
        self.checks = {}
        form = QFormLayout()
        if not bulk:
            crow = QHBoxLayout()
            crow.addWidget(self.cloud, 1)
            crow.addWidget(self._cmd_btn("목록 다시 읽기", "reload_devices", "그 PC의 실행기가 LD CLOUD 기기 목록을 다시 읽어요"))
            form.addRow("열 클라우드", crow)
            opens = ((agent.state.get("cfg") or {}).get("cloud") if agent else "") or ""
            form.addRow("", muted(f"실행기가 지금 여는 클라우드: {opens.split(' #')[0] or '(아직 없음)'}  "
                                  "— 작업장 LD클라우드 칸에는 이 값이 보여요"))
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
        if not bulk:
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
                form.addRow(f"{key} 위치" + (" (구분 없음)" if key == "AMP" else ""), row)
            # 게임별 AMP: 같은 PC에 메랜용/플래닛용 AMP가 따로 있을 때 어느 것을 켤지
            found = [x for x in (cur.get("amp_found") or []) if x]
            chosen = dict(cur.get("amp_paths") or {})
            frow = QHBoxLayout()
            self.amp_found_label = muted(f"그 PC에서 찾은 AMP {len(found)}개" if found else "아직 안 찾음 → [AMP 모두 찾기]")
            frow.addWidget(self.amp_found_label, 1)
            frow.addWidget(self._cmd_btn("AMP 모두 찾기", "amp_find", "그 PC에서 AMP.exe를 모두 찾아요 (1~2분). 끝나면 이 창을 다시 여세요"))
            form.addRow("게임별 AMP", frow)
            self.amp_games = {}
            for g in GAMES:
                c = QComboBox()
                c.addItem("(정하지 않음)", "")
                items = list(found)
                if chosen.get(g) and chosen[g] not in items:
                    items.append(chosen[g])
                for x in items:
                    c.addItem(x, x)
                c.setCurrentIndex(max(c.findData(chosen.get(g, "")), 0))
                wheel_only_when_focused(c)
                self.amp_games[g] = c
                grow = QHBoxLayout()
                grow.addWidget(c, 1)
                grow.addWidget(button("폴더 열기", "", lambda _=False, g=g: self._send("amp_folder", g),
                                      "그 PC 화면에 이 게임 AMP 폴더를 띄워요"))
                form.addRow(f"  {g} AMP", grow)
        self.cmd_msg = muted("")

        lay = QVBoxLayout(self)
        if bulk:
            names = ", ".join(f"{p.no}. {p.name}" for p in bulk[:12]) + (f" 외 {len(bulk) - 12}대" if len(bulk) > 12 else "")
            note = QLabel(f"<b>{len(bulk)}대</b>에 아래 값을 똑같이 저장해요: {names}<br>"
                          "열 클라우드와 프로그램 위치는 컴퓨터마다 달라서 바뀌지 않아요. "
                          f"처음 보이는 값은 {pc.no}. {pc.name}의 설정이에요.")
            note.setWordWrap(True)
            note.setObjectName("hintBox")
            lay.addWidget(note)
        elif agent is None:
            lay.addWidget(muted("이 컴퓨터에 연결된 실행기가 아직 없어요. 설정은 저장해 두면 연결될 때 적용돼요."))
        else:
            lay.addWidget(muted(f"실행기: {agent.machine} · v{agent.version} · {_ago(agent.seconds_ago)}"))
        lay.addLayout(form)
        if agent is not None and repo.me.can("can_link_agent") and not bulk:
            # 잘못 연결했거나 컴퓨터 자리가 바뀌었을 때: 이 실행기를 다른 컴퓨터로 옮기기
            box_m = QGroupBox("이 실행기를 다른 컴퓨터로 옮기기 (잘못 연결했거나 자리가 바뀌었을 때)")
            mrow = QHBoxLayout(box_m)
            self.move_to = QComboBox()
            self.move_to.addItem("옮길 컴퓨터 고르기...", None)
            for p in (all_pcs or []):
                if p.id != pc.id:
                    self.move_to.addItem(f"{p.no}. {p.name}" + ("  (실행기 있음 → 바꾸기)" if p.id in (linked or set()) else ""), p.id)
            wheel_only_when_focused(self.move_to)
            others = [p for p in (all_pcs or []) if p.id != pc.id]
            target, why = suggest_pc(((agent.state.get("cfg") or {}).get("cloud") or ""), others, self.linked)
            if target is not None:
                self.move_to.setCurrentIndex(max(self.move_to.findData(target.id), 0))
                self.move_to.setToolTip("추천 이유: " + why)
            mrow.addWidget(self.move_to, 1)
            mrow.addWidget(button("옮기기", "", self._move, "이 실행기를 고른 컴퓨터 줄에 연결해요"))
            lay.addWidget(box_m)
            if target is not None:
                lay.addWidget(muted("추천: " + why))
        lay.addWidget(self.cmd_msg)
        lay.addStretch(1)
        row = QHBoxLayout()
        if agent is not None and repo.me.can("can_link_agent") and not bulk:
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

    def _send(self, kind: str, arg: str = "") -> None:
        if self.agent is None:
            return
        if kind == "amp_find":
            self._amp_cid = None
        if run_safely(self, self.repo.send_command, self.pc.id, kind, arg):
            if kind == "amp_find":
                self._watch_amp_find()
            self.cmd_msg.setText(f"[{kind_label(kind, arg)}] 명령을 보냈어요. 결과는 PC 조종 화면의 명령 기록에 나와요 "
                                 "(위치 값은 몇 초 뒤 이 창을 다시 열면 바뀌어요).")

    def _watch_amp_find(self) -> None:
        """AMP 모두 찾기를 보낸 뒤: 실행기가 찾기를 마치면 게임별 AMP 목록을 저절로 채운다 (창을 다시 안 열어도)."""
        self._amp_tries = 0
        self._amp_timer = QTimer(self)
        self._amp_timer.timeout.connect(self._poll_amp_found)
        self._amp_timer.start(3000)
        self.cmd_msg.setText("그 PC에서 AMP를 찾는 중이에요 (1~2분). 끝나면 아래 목록이 저절로 채워져요.")

    def _poll_amp_found(self) -> None:
        self._amp_tries += 1
        try:
            cmds = self.repo.list_commands([self.pc.id], limit=5)
            last = next((c for c in cmds if c["kind"] == "amp_find"), None)
            if last is None or last["status"] in ("queued", "running"):
                if self._amp_tries > 80:
                    self._amp_timer.stop()
                    self.cmd_msg.setText("아직 끝나지 않았어요. 잠시 뒤 이 창을 다시 열어 보세요.")
                return
            self._amp_timer.stop()
            ag = next((a for a in self.repo.list_agents() if a.user_id == self.agent.user_id), None)
            found = [x for x in (((ag.state.get("cfg") or {}).get("amp_found")) if ag else []) or [] if x]
            for g, c in getattr(self, "amp_games", {}).items():
                cur = c.currentData()
                c.clear()
                c.addItem("(정하지 않음)", "")
                for x in found:
                    c.addItem(x, x)
                i = c.findData(cur)
                c.setCurrentIndex(i if i >= 0 else 0)
            self.amp_found_label.setText(f"그 PC에서 찾은 AMP {len(found)}개" if found else "AMP를 찾지 못했어요")
            self.cmd_msg.setText(last.get("result", "") or "")
        except RepoError as e:
            self.cmd_msg.setText(f"확인 중: {e}")

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
        games = getattr(self, "amp_games", None)
        if games:
            v["amp_paths"] = {g: c.currentData() or "" for g, c in games.items()}
        return v

    def _save(self) -> None:
        if self.bulk:
            self._save_bulk()
            return
        if not self.value()["cloud"]:
            QMessageBox.warning(self, "확인 필요", "열 클라우드를 고르세요.")
            return
        if run_safely(self, self.repo.set_agent_settings, self.pc.id, self.value()):
            self.accept()

    def _save_bulk(self) -> None:
        common = self.value()
        common.pop("cloud", None)  # 열 클라우드는 컴퓨터마다 다르므로 그대로 둠
        common.pop("amp_paths", None)  # 게임별 AMP 위치도 컴퓨터마다 다름
        if QMessageBox.question(self, "같은 설정 적용", f"{len(self.bulk)}대에 같은 설정을 저장할까요?") != QMessageBox.Yes:
            return
        errors = []
        for p in self.bulk:
            s = dict(p.agent_settings or {})
            s.update(common)
            try:
                self.repo.set_agent_settings(p.id, s)
            except RepoError as e:
                errors.append(f"{p.no}. {p.name}: {e}")
        if errors:
            QMessageBox.warning(self, "일부 못 저장함", "\n".join(errors[:15]))
        self.accept()

    def _move(self) -> None:
        target = self.move_to.currentData()
        if target is None:
            QMessageBox.information(self, "옮기기", "옮길 컴퓨터를 고르세요.")
            return
        name = self.move_to.currentText().replace("  (실행기 있음 → 바꾸기)", "")
        msg = (f"'{self.agent.machine}' 실행기를 [{self.pc.no}. {self.pc.name}] → [{name}]으로 옮길까요?\n"
               f"[{name}]의 실행기 설정(열 클라우드 등)과 자리 계정을 쓰게 돼요.")
        if target in self.linked:
            msg += f"\n\n[{name}]에 연결돼 있던 실행기는 연결 대기로 돌아가요."
        if QMessageBox.question(self, "실행기 옮기기", msg) != QMessageBox.Yes:
            return
        if run_safely(self, self.repo.link_agent, self.agent.user_id, target):
            try:
                self.repo.sync_pc_creds()  # 새 자리 계정을 그 실행기에 보내 둠
            except RepoError:
                pass
            self.unlinked = True
            self.accept()

    def _unlink(self) -> None:
        if QMessageBox.question(self, "연결 끊기", f"'{self.agent.machine}' 실행기를 이 컴퓨터에서 떼어낼까요?\n"
                                "이 컴퓨터에 정해 둔 클라우드도 지워서 다시 자동으로 붙지 않게 해요.\n"
                                "떼어낸 실행기는 연결 대기로 돌아가요.") != QMessageBox.Yes:
            return
        if run_safely(self, reset_pc_launcher, self.repo, self.pc, self.agent):
            self.unlinked = True
            self.accept()


class CloudAssignDialog(QDialog):
    """컴퓨터마다 LD 클라우드를 목록에서 고른다 (예전 실행기 설정의 '열 클라우드'처럼).
    정해 두면 그 클라우드를 여는 실행기가 켜질 때 그 컴퓨터에 자동으로 연결되고, 연결된 실행기는 그 클라우드를 연다."""

    NONE = "(정하지 않음)"

    def __init__(self, repo, pcs: list, agents: dict, devices: list, parent=None):
        super().__init__(parent)
        self.repo, self.pcs = repo, pcs
        self.setWindowTitle("컴퓨터별 클라우드 정하기")
        self.resize(px(860), px(720))
        hint = QLabel("컴퓨터마다 LD 클라우드를 고르세요. 그 클라우드를 여는 실행기가 켜지면 자동으로 그 컴퓨터에 연결되고,\n"
                      "이미 연결된 실행기는 여기서 고른 클라우드를 열게 바뀌어요. 같은 클라우드를 두 컴퓨터에 고를 수는 없어요.\n"
                      "오른쪽에 '추천'이 붙은 줄은 제가 미리 골라 둔 값이에요 (예전 값이나 같은 번호). 아니면 바꾸거나 '(정하지 않음)'으로 두세요.")
        hint.setWordWrap(True)
        hint.setObjectName("hintBox")
        self.table = QTableWidget(len(pcs), 5)
        self.table.setHorizontalHeaderLabels(["번호", "컴퓨터", "지금 여는 클라우드", "정할 클라우드", ""])
        self.table.verticalHeader().setVisible(False)
        style_table(self.table)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setDefaultSectionSize(px(40))
        self.nav = SheetNav(self.table, "zoom_clouds", self._fit)
        self.combos = {}
        self.before = {}
        # 이미 쓰이는 클라우드 (정해 둔 것 + 실행기가 여는 것) → 추천에서 뺌
        used = {cloud_id((p.agent_settings or {}).get("cloud")) for p in pcs} | \
               {cloud_id(((a.state.get("cfg") or {}).get("cloud"))) for a in agents.values()}
        used.discard("")
        for r, pc in enumerate(pcs):
            self.table.setItem(r, 0, _item(str(pc.no), True))
            self.table.setItem(r, 1, _item(pc.name))
            ag = agents.get(pc.id)
            now = ((ag.state.get("cfg") or {}).get("cloud") or "") if ag else ""
            it = _item(now.split(" #")[0] if now else ("(실행기 없음)" if ag is None else "(정해지지 않음)"))
            if not now:
                it.setForeground(QColor(T("muted")))
            self.table.setItem(r, 2, it)
            cur = (pc.agent_settings or {}).get("cloud") or now
            why = ""
            if not cur:
                cur, why = suggest_cloud(pc, devices, used)
                if cur:
                    used.add(cloud_id(cur))
            c = QComboBox()
            c.addItem(self.NONE, "")
            items = list(devices)
            if cur and cur not in items:
                items.append(cur)
            for d in sorted(items, key=cloud_sort_key):
                c.addItem(d, d)
            c.setCurrentIndex(max(c.findData(cur), 0) if cur else 0)
            wheel_only_when_focused(c)
            self.combos[pc.id] = c
            self.before[pc.id] = "" if why else (cur or "")   # 추천으로 채운 것은 저장할 때 바뀐 것으로 본다
            tag = _item("추천" if why else "")
            if why:
                tag.setToolTip(why)
                tag.setForeground(QColor(T("accent")))
                c.setToolTip("추천 이유: " + why)
            self.table.setItem(r, 4, tag)
            box = QWidget()
            bl = QHBoxLayout(box)
            bl.setContentsMargins(4, 2, 4, 2)
            bl.addWidget(c)
            self.table.setCellWidget(r, 3, box)
        self._fit()
        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Save).setText("저장")
        btns.button(QDialogButtonBox.Cancel).setText("취소")
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(hint)
        lay.addWidget(self.table, 1)
        lay.addWidget(btns)

    def _fit(self) -> None:
        if hasattr(self, "combos"):
            self.table.verticalHeader().setDefaultSectionSize(zoom_rows(self.nav, 40))
            fit_columns(self.table, mins={3: 290}, caps={2: 260})

    def value(self) -> dict:
        return {pid: c.currentData() or "" for pid, c in self.combos.items()}

    def _save(self) -> None:
        v = self.value()
        used = {}
        for pc in self.pcs:
            cid = cloud_id(v[pc.id])
            if cid:
                if cid in used:
                    other = used[cid]
                    QMessageBox.warning(self, "같은 클라우드", f"{v[pc.id].split(' #')[0]} 을(를) {other.no}번과 {pc.no}번에 같이 골랐어요.\n"
                                        "한 컴퓨터에만 고르세요.")
                    return
                used[cid] = pc
        changed = [pc for pc in self.pcs if v[pc.id] != self.before[pc.id]]
        errors = []
        for pc in changed:
            s = dict(pc.agent_settings or {})
            if v[pc.id]:
                s["cloud"] = v[pc.id]
            else:
                s.pop("cloud", None)
            try:
                self.repo.set_agent_settings(pc.id, s)
            except RepoError as e:
                errors.append(f"{pc.no}. {pc.name}: {e}")
        if errors:
            QMessageBox.warning(self, "일부 못 저장함", "\n".join(errors[:15]))
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
        self.pending_choice: dict[str, int] = {}   # 연결 대기 실행기별로 내가 고른 컴퓨터 (새로고침해도 유지)
        self._suggest: dict[str, int] = {}          # 실행기별 추천 컴퓨터
        self._why: dict[str, str] = {}
        self._pending_key = None
        self.displaced: dict[str, int] = {}         # 새 실행기로 바꾸면서 밀려난 실행기 → 밀려난 컴퓨터 id

        hint = QLabel("각 컴퓨터의 LD CLOUD 실행기에 명령을 보내요. 체크한 컴퓨터에 한 번에 보낼 수 있어요.\n"
                      "A 로그인 = 그 컴퓨터 1자리 계정, B 로그인 = 2자리 계정. 실행기 설정은 오른쪽 [설정]에서만 바꿔요.")
        hint.setWordWrap(True)
        hint.setObjectName("hintBox")

        # 버튼 줄: 창이 좁으면 덩어리 단위로 다음 줄로 넘어감 (잘리지 않게)
        bar = FlowLayout(spacing=px(8))
        self.all_box = QCheckBox("전체 선택")
        self.all_box.toggled.connect(self._check_all)
        self.sel_label = muted("선택한 컴퓨터 0대에:")
        bar.addWidget(group(self.all_box, self.sel_label, spacing=px(12)))
        bar.addWidget(group(*[button(AGENT_KINDS[kind], "primary" if kind.startswith("login") else "",
                                     lambda _=False, k=kind: self._send_checked(k))
                              for kind in ("start", "restart", "close", "login_a", "login_b")],
                            button("중지", "danger", lambda: self._send_checked("stop"),
                                   "하던 작업을 멈추고 기다리는 명령을 취소해요")))
        bar2 = FlowLayout(spacing=px(8))
        amp = []
        for kind in ("amp_run", "amp_stop"):
            b = button(AGENT_KINDS[kind], "", None, "어느 게임의 AMP인지 골라요 (실행기 [설정]에서 게임별 AMP를 정해 둬야 해요)")
            m = QMenu(b)
            m.aboutToShow.connect(lambda k=kind, menu=m: self._fill_amp_menu(k, menu))   # 팀마다 게임이 달라서 열 때마다 채움
            b.setMenu(m)
            amp.append(b)
        bar2.addWidget(group("다른 프로그램:", *amp,
                             *[button(AGENT_KINDS[kind], "", lambda _=False, k=kind: self._send_checked(k))
                               for kind in ("map_run", "map_stop")]))
        wb = button("실행기 창", "", None, "체크한 컴퓨터의 실행기 창을 화면에 띄우거나 트레이로 보내요 (그 PC에 들어가지 않아도 돼요)")
        wm = QMenu(wb)
        wm.addAction("창 열기 (화면에 띄우기)", lambda: self._send_checked("window_show"))
        wm.addAction("트레이로 보내기 (창 숨기기)", lambda: self._send_checked("window_hide"))
        wb.setMenu(wm)
        bar2.addWidget(group("실행기:", button("실행기 다시 켜기", "", lambda: self._send_checked("restart_agent"),
                                              "실행기를 껐다가 다시 켜요. 새 버전이 있으면 이때 업데이트돼요"), wb))
        bar2.addWidget(group(
            button("선택한 컴퓨터에 같은 설정", "", self._bulk_settings,
                   "체크한 컴퓨터들의 실행기 설정을 한 번에 똑같이 바꿔요 (열 클라우드는 제외)"),
            button("컴퓨터별 클라우드 정하기", "primary", self._clouds,
                   "컴퓨터마다 LD 클라우드를 목록에서 골라요. 그 클라우드를 여는 실행기가 켜지면 자동으로 연결돼요")))
        manage = []
        if repo.me.can("can_link_agent"):
            manage.append(button("선택한 컴퓨터 MAC 고정", "", self._fix_mac_checked,
                                 "체크한 컴퓨터에 지금 연결된 실행기 PC의 MAC을 고정해요. 그 뒤로 그 PC의 실행기는 "
                                 "다시 깔아도 항상 그 컴퓨터로 연결되고, 다른 PC 실행기는 그 컴퓨터로 자동 연결되지 않아요"))
        if repo.me.is_admin or (repo.me.can("can_link_agent") and repo.me.can("can_control_pc")):
            manage.append(button("선택한 컴퓨터 실행기 초기화", "danger", self._reset_checked,
                                 "체크한 컴퓨터의 정한 클라우드를 지우고 실행기 연결을 끊어요. 실행기는 연결 대기로 돌아가요"))
        if manage:
            bar2.addWidget(group(*manage))

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
        self.nav = SheetNav(self.table, "zoom_pc", self.restyle)

        # 아래: 고른 컴퓨터의 명령 기록과 진행 로그
        self.hist_title = muted("컴퓨터를 고르면 명령 기록과 진행 로그가 보여요.")
        self.hist = QTableWidget(0, 6)
        self.hist.setHorizontalHeaderLabels(["보낸 시각", "명령", "보낸 사람", "상태", "걸린 시간", "결과"])
        self.hist.verticalHeader().setVisible(False)
        style_table(self.hist)
        self.hist.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.hist.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.hist.horizontalHeader().setStretchLastSection(True)
        self.hist.itemSelectionChanged.connect(self._show_log)
        self.hist_nav = SheetNav(self.hist, "zoom_pc_hist", self.restyle)
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
        ph = FlowLayout(spacing=px(10))
        self.pend_title = QLabel("<b>연결 대기 실행기</b>")
        ph.addWidget(group(self.pend_title, QLabel("— 어느 컴퓨터인지 골라 [연결]을 누르면 그 PC의 MAC이 그 컴퓨터에 고정돼요.")))
        self.update_old_btn = button("예전 실행기 모두 업데이트", "primary", self._update_old,
                                     "MAC 모름으로 나오는(예전 버전) 연결 대기 실행기를 다시 켜서 새 버전으로 바꿔요. "
                                     "새 버전이 되면 MAC이 보여요")
        ph.addWidget(self.update_old_btn)
        self.show_linked = QCheckBox("연결된 실행기도 같이 보기 (어디에 붙어 있는지 확인·옮기기)")
        self.show_linked.toggled.connect(lambda _on: self._redraw_pending())
        ph.addWidget(self.show_linked)
        pl.addLayout(ph)
        if repo.me.is_super:
            tb = QHBoxLayout()
            self.pend_all = QCheckBox("전체 선택")
            self.pend_all.toggled.connect(self._pend_check_all)
            tb.addWidget(self.pend_all)
            tb.addSpacing(px(12))
            tb.addWidget(muted("선택한 실행기를 팀으로:"))
            self.bulk_team = QComboBox()
            wheel_only_when_focused(self.bulk_team)
            tb.addWidget(self.bulk_team)
            tb.addWidget(muted("또는 실행 코드"))
            self.bulk_code = QLineEdit()
            self.bulk_code.setPlaceholderText("예: K7M2QX")
            self.bulk_code.setMaximumWidth(px(110))
            tb.addWidget(self.bulk_code)
            tb.addWidget(button("적용", "primary", self._bulk_team, "체크한 실행기들을 고른 팀(또는 코드의 팀)으로 정해요"))
            tb.addStretch(1)
            pl.addLayout(tb)
        self.pend = QTableWidget(0, 8)
        self.pend.setHorizontalHeaderLabels(["MAC · PC 이름 (윈도우)", "버전", "그 PC가 여는 클라우드", "마지막 연락",
                                             "연결할 컴퓨터 (눌러서 고르기)", "", "팀", "선택"])
        self.pend.setColumnHidden(6, not repo.me.is_super)
        self.pend.setColumnHidden(7, not repo.me.is_super)
        self.pend_checked: set[str] = set()
        self.pend.verticalHeader().setVisible(False)
        style_table(self.pend)
        self.pend.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.pend.setSelectionMode(QAbstractItemView.NoSelection)
        self.pend.horizontalHeader().setStretchLastSection(True)
        self.pend_nav = SheetNav(self.pend, "zoom_pc_pend", self.restyle)
        pl.addWidget(self.pend)

        # 현황판 (카드) 보기: 표와 같은 내용을 컴퓨터마다 블록 하나로
        self.board = PcBoard(self)
        self.legend = QLabel()
        self.legend.setTextFormat(Qt.RichText)
        self.legend.setWordWrap(True)   # 좁은 창에서 창 폭을 늘리지 않게
        board_page = QWidget()
        bpl = QVBoxLayout(board_page)
        bpl.setContentsMargins(0, 0, 0, 0)
        bpl.setSpacing(px(8))
        bpl.addWidget(self.legend)
        bpl.addWidget(self.board, 1)
        self.view = QStackedWidget()
        self.view.addWidget(self.table)
        self.view.addWidget(board_page)

        split = QSplitter(Qt.Vertical)
        split.addWidget(self.view)
        split.addWidget(bottom)
        split.setChildrenCollapsible(False)
        self.table.setMinimumHeight(px(260))
        bottom.setMinimumHeight(px(180))
        # 화면 전체가 스크롤되므로, 연결 대기 목록이 길어져도 위 표·명령 기록은 이 높이 아래로 줄어들지 않는다
        split.setMinimumHeight(px(640))
        split.setSizes([420, 220])

        # 화면 전체를 아래로 스크롤 (표 위에서 휠 = 그 표 안에서만, 표 밖에서 휠 = 화면 전체)
        content = QWidget()
        page = QScrollArea()
        page.setWidgetResizable(True)
        page.setWidget(content)
        page.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)   # 버튼 줄은 줄바꿈되므로 보통은 안 생김
        self.page_scroll = page
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(page)

        lay = QVBoxLayout(content)
        lay.setContentsMargins(28, 24, 28, 20)
        lay.setSpacing(12)
        # 보기 전환: 표 ↔ 현황판 (밀어서), 현황판은 가로 몇 칸인지
        st = _sheet.settings()
        board_on = st.value("pc_view", "table") == "board"
        self.view_switch = ToggleSwitch(board_on)
        self.view_switch.setToolTip("표로 보기 ↔ 컴퓨터마다 블록으로 보는 현황판")
        lt, lb = QLabel("표"), QLabel("현황판")
        for lab, on in ((lt, False), (lb, True)):
            lab.setCursor(Qt.PointingHandCursor)
            lab.mousePressEvent = lambda _e, v=on: self.view_switch.setChecked(v)
        self.view_labels = (lt, lb)
        self.view_switch.toggled.connect(self._set_view)
        self.cols_box = QComboBox()
        self.cols_box.addItem("자동", 0)
        for n in range(2, 11):
            self.cols_box.addItem(str(n), n)
        try:
            want = int(st.value("pc_board_cols", 0) or 0)
        except (TypeError, ValueError):
            want = 0
        self.cols_box.setCurrentIndex(max(0, self.cols_box.findData(want)))
        self.board.fixed_cols = want if self.cols_box.findData(want) > 0 else 0
        self.cols_box.currentIndexChanged.connect(self._set_cols)
        wheel_only_when_focused(self.cols_box)
        self.cols_group = group("가로", self.cols_box, "칸")
        lay.addWidget(page_header("PC 조종", "LD CLOUD 실행기에 명령을 보내고 상태를 봐요",
                                  [group(lt, self.view_switch, lb, spacing=px(8)), self.cols_group,
                                   button("새로고침", "", self.refresh)]))
        lay.addWidget(hint)
        lay.addWidget(muted("표 위에서 휠 = 그 표 안에서 이동, Ctrl+휠 = 표 크기, 휠 버튼 누른 채 끌기 = 이동 (표마다 따로 기억).  "
                            "표 밖에서 휠 = 화면 전체를 위아래로"))
        lay.addLayout(bar)
        lay.addLayout(bar2)
        lay.addWidget(split, 1)
        lay.addWidget(self.pending_box)
        self._set_view(board_on, save=False)


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
        tid = getattr(self.repo, "team_id", None)
        self.pending = [a for a in agents if a.pc_id is None
                        and (a.team_id == tid or (a.team_id is None and self.repo.me.is_super))]
        if getattr(self, "show_linked", None) is not None and self.show_linked.isChecked():
            # 연결된 실행기도: 이 팀 컴퓨터에 붙은 것 (총관리자는 다른 팀 컴퓨터에 붙은 것까지)
            no = {p.id: p.no for p in self.pcs}
            linked = [a for a in agents if a.pc_id is not None and (a.pc_id in mine or self.repo.me.is_super)]
            linked.sort(key=lambda a: (a.pc_id not in no, no.get(a.pc_id, 0), a.machine))
            self.pending = self.pending + linked
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
                st = _item("실행기 없음" + (f"\nMAC {pc.mac} 기다리는 중" if pc.mac else ""))
                st.setForeground(gray)
                if pc.mac:
                    st.setToolTip(f"이 컴퓨터는 MAC {pc.mac} 실행기로 고정돼 있어요. 그 PC에서 실행기가 켜지면 자동으로 연결돼요.\n"
                                  "다른 PC로 바꾸려면 연결 대기에서 그 실행기를 이 컴퓨터에 [연결]하세요.")
                now = _item("")
                team = _item("-")
                team.setForeground(gray)
            else:
                team = self._team_cell(ag, red)
                live = (ag.state or {}).get("realtime")
                speed = "" if not ag.online or live is None else ("  · 즉시" if live else "  · 20초마다")
                if ag.online and (ag.state or {}).get("window") is not None:
                    speed += "  · 창 열림" if ag.state.get("window") else "  · 트레이"
                st = _item(("● 켜짐" if ag.online else "● 꺼짐 (" + _ago(ag.seconds_ago) + ")") + speed
                           + "\n" + self._mac_line(ag, pc))
                st.setForeground(green if ag.online else gray)
                tip = (f"MAC: {ag.mac or '(모름 — 예전 실행기. 다시 켜면 새 버전이 알려 줘요)'}\n"
                       + ("이 컴퓨터에 MAC 고정됨: 이 PC 실행기는 다시 깔아도 항상 이 컴퓨터로 연결돼요"
                          if pc.mac and pc.mac in ag.macs else
                          "아직 MAC이 고정되지 않았어요. 맞는 PC면 체크하고 [선택한 컴퓨터 MAC 고정]")
                       + f"\nWindows PC 이름: {ag.machine}\n실행기 버전: v{ag.version}")
                if live is not None:
                    tip += "\n" + ("실시간 연결됨: 명령이 바로 전달돼요" if live else
                                    "실시간 연결이 안 돼서 20초마다 명령을 확인해요 (실행기 다시 켜기로 다시 시도)")
                st.setToolTip(tip)
                s = ag.state or {}
                now = _item((("▶ " + s.get("job", "")) if s.get("busy") else s.get("last", "")) or "")
                now.setToolTip(s.get("last", ""))
            t.setItem(r, 3, st)
            t.setItem(r, 4, team)
            t.setItem(r, 5, now)
            for c, slot in ((6, 1), (7, 2)):
                aid = pc.slots[slot - 1] if len(pc.slots) >= slot else None
                t.setItem(r, c, _item(self.acc_names.get(aid, "") if aid else "-"))
            last = (self.commands.get(pc.id) or [None])[0]
            if last:
                kind = _item(f"{kind_label(last['kind'], last.get('arg', ''))} · {COMMAND_STATUS.get(last['status'], '')}")
                kind.setToolTip(f"{last['created_at']} {last.get('created_name', '')}")
                if last["status"] == "failed":
                    kind.setForeground(red)
                res = _item(last.get("result", ""))
                res.setToolTip(last.get("result", ""))
            else:
                kind, res = _item(""), _item("")
            t.setItem(r, 8, kind)
            t.setItem(r, 9, res)
            t.setCellWidget(r, 10, self._settings_btn(pc))
            if pc.id == sel:
                t.selectRow(r)
        t.blockSignals(False)
        self.sel_label.setText(f"선택한 컴퓨터 {len(self.checked)}대에:")
        self._render_board()
        self._render_pending()
        self._render_history()
        self.restyle()

    @staticmethod
    def _mac_line(ag: Agent, pc=None) -> str:
        if not ag.mac:
            return f"{ag.machine} (예전 실행기 · MAC 모름)"
        if pc is None:
            return ag.mac
        return ag.mac + ("  · 고정" if pc.mac and pc.mac in ag.macs else "  · MAC 미확인")

    def _team_cell(self, ag: Agent, red: QColor) -> QTableWidgetItem:
        """연결된 실행기가 어느 팀으로 등록돼 있는지 + 그 팀의 지금 실행 코드."""
        teams = {t.id: t for t in self.repo.teams}
        mine = getattr(self.repo, "team_id", None)
        tm = teams.get(ag.team_id)
        name = tm.name if tm else ("팀 없음" if ag.team_id is None else "다른 팀")
        code = (tm.join_code or "") if tm else ""
        cell = _item(name + (f"\n코드 {code}" if code else ""))
        tip = ("이 실행기는 '" + name + "' 팀으로 등록돼 있어요." + (f" 이 팀의 지금 실행 코드: {code}" if code else "")
               + "\n실행 코드는 실행기를 팀에 처음 넣을 때만 써요. 이미 연결된 실행기는 컴퓨터의 팀을 그대로 따라가서 "
                 "코드를 다시 넣을 필요가 없어요. (팀 관리에서 새 코드를 만들어도 이미 연결된 실행기는 그대로예요)")
        if ag.team_id != mine:
            cur = teams.get(mine).name if teams.get(mine) else "이 팀"
            cell = _item(f"⚠ {name}\n컴퓨터는 {cur}")
            cell.setForeground(red)
            tip = (f"실행기 팀({name})과 컴퓨터 팀({cur})이 달라요. 연결 대기에서 다시 연결하면 컴퓨터 팀으로 맞춰져요.")
        cell.setToolTip(tip)
        return cell

    def _settings_btn(self, pc) -> QWidget:
        w = QWidget()
        l = QHBoxLayout(w)
        l.setContentsMargins(4, 2, 4, 2)
        l.addWidget(button("설정", "", lambda _=False, p=pc: self._settings(p)))
        return w

    def restyle(self) -> None:
        self.table.verticalHeader().setDefaultSectionSize(zoom_rows(getattr(self, "nav", None), 40))
        # 글자가 잘리지 않게 내용에 맞추되, 긴 글(지금 상태, 계정, 결과)은 너무 넓어지지 않게 (전체는 툴팁)
        fit_columns(self.table, mins={0: 36, 3: 150}, caps={4: 200, 5: 260, 6: 230, 7: 230, 8: 200, 9: 320})
        self.hist.verticalHeader().setDefaultSectionSize(zoom_rows(getattr(self, "hist_nav", None), 30))
        fit_columns(self.hist, mins={0: 120}, caps={5: 420})
        self.pend.verticalHeader().setDefaultSectionSize(zoom_rows(getattr(self, "pend_nav", None), 40))
        fit_columns(self.pend, mins={4: 300, 6: 110, 7: 50}, caps={2: 280, 6: 180})
        self._fit_pend_height()

    def _fit_pend_height(self) -> None:
        """연결 대기 표는 줄을 모두 보여 준다 (안에서 스크롤하지 않고, 길어지면 화면 전체가 스크롤됨)."""
        p = self.pend
        rows = p.verticalHeader().length() if p.rowCount() else p.verticalHeader().defaultSectionSize()
        bar = p.horizontalScrollBar().sizeHint().height()
        p.setFixedHeight(rows + p.horizontalHeader().sizeHint().height() + 2 * p.frameWidth() + bar + px(2))

    def _toggle(self, pc_id: int, on: bool) -> None:
        (self.checked.add if on else self.checked.discard)(pc_id)
        self.sel_label.setText(f"선택한 컴퓨터 {len(self.checked)}대에:")
        card = self.board.cards.get(pc_id)
        if card:
            card.set_checked(on)

    # ---------------------------------------------------------------- 현황판
    def _set_view(self, board: bool, save: bool = True) -> None:
        self.view.setCurrentIndex(1 if board else 0)
        self.cols_group.setVisible(board)
        for lab, on in zip(self.view_labels, (False, True)):
            lab.setStyleSheet(f"color:{T('ink') if on == board else T('muted')};"
                              + ("font-weight:bold;" if on == board else ""))
        if self.view_switch.isChecked() != board:
            self.view_switch.setChecked(board)
        if save:
            _sheet.settings().setValue("pc_view", "board" if board else "table")

    def _set_cols(self, _i: int) -> None:
        n = self.cols_box.currentData() or 0
        _sheet.settings().setValue("pc_board_cols", n)
        self.board.set_fixed_cols(n)

    def _card_check(self, pc_id: int, on: bool) -> None:
        """카드에서 체크 → 표의 체크칸도 같이."""
        (self.checked.add if on else self.checked.discard)(pc_id)
        self.sel_label.setText(f"선택한 컴퓨터 {len(self.checked)}대에:")
        for r, pc in enumerate(self.pcs):
            if pc.id == pc_id:
                w = self.table.cellWidget(r, 0)
                cb = w.findChild(QCheckBox) if w else None
                if cb is not None and cb.isChecked() != on:
                    cb.blockSignals(True)
                    cb.setChecked(on)
                    cb.blockSignals(False)
                break

    def _card_pick(self, pc_id: int) -> None:
        """카드를 누르면 아래에 그 컴퓨터의 명령 기록."""
        self.current_pc = pc_id
        for r, pc in enumerate(self.pcs):
            if pc.id == pc_id:
                self.table.blockSignals(True)
                self.table.selectRow(r)
                self.table.blockSignals(False)
                break
        self._render_history()

    def _render_board(self) -> None:
        n = self.board.render()
        dot = lambda key, sym, text, k: (f"<span style='color:{T(key)}'>{sym}</span> {text} <b>{n[k]}</b>")
        self.legend.setText("&nbsp;&nbsp;&nbsp;".join([
            dot("success", "●", "켜짐", "on"), dot("accent_text", "●", "작업 중", "busy"),
            dot("danger", "●", "꺼짐", "off"), dot("faint", "○", "실행기 없음", "none"),
        ]) + f"&nbsp;&nbsp;&nbsp;<span style='color:{T('muted')}'>· 카드 누르기 = 체크(명령 대상) + 아래에 명령 기록 · 휠 = 위아래, Shift+휠 = 좌우, 휠 버튼 누른 채 끌기 = 상하좌우</span>")

    def _check_all(self, on: bool) -> None:
        self.checked = {p.id for p in self.pcs} if on else set()
        self._render()

    def _row_selected(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if rows:
            self.current_pc = self.table.item(rows[0].row(), 1).data(Qt.UserRole)
            self.board.set_current(self.current_pc)
            self._render_history()

    # ---------------------------------------------------------------- 명령
    def _fill_amp_menu(self, kind: str, m: QMenu) -> None:
        m.clear()
        for g in GAMES:
            m.addAction(f"{g} AMP", lambda g=g: self._send_checked(kind, g))
        m.addSeparator()
        m.addAction("게임 구분 없이 (AMP가 하나뿐일 때)" if kind == "amp_run" else "모든 AMP",
                    lambda: self._send_checked(kind, ""))

    def _send_checked(self, kind: str, arg: str = "") -> None:
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
                self, "PC 조종", f"{len(targets)}대에 [{kind_label(kind, arg)}] 명령을 보낼까요?") != QMessageBox.Yes:
            return
        errors = []
        try:
            self.repo.sync_pc_creds()  # 로그인 전에 자리 계정이 최신인지
        except RepoError:
            pass
        for p in targets:
            try:
                self.repo.send_command(p.id, kind, arg)
            except RepoError as e:
                errors.append(f"{p.no}. {p.name}: {e}")
        errors += [f"{p.no}. {p.name}: 연결된 실행기가 없음" for p in no_agent]
        self._tick()
        if errors:
            QMessageBox.warning(self, "일부 못 보냄", "\n".join(errors[:15]))

    def _fix_mac_checked(self) -> None:
        targets = [p for p in self.pcs if p.id in self.checked]
        if not targets:
            QMessageBox.information(self, "MAC 고정", "MAC을 고정할 컴퓨터를 체크하세요.")
            return
        ok = [(p, self.agents[p.id]) for p in targets if p.id in self.agents and self.agents[p.id].mac]
        skip = [p for p in targets if not (p.id in self.agents and self.agents[p.id].mac)]
        if not ok:
            QMessageBox.information(self, "MAC 고정", "체크한 컴퓨터에 MAC을 알려 준 실행기가 없어요.\n"
                                    "실행기가 없거나 예전 실행기예요. 예전 실행기는 [실행기 다시 켜기]를 누르면 새 버전으로 바뀌어요.")
            return
        lines = "\n".join(f"  {p.no}. {p.name} ← {a.mac} ({a.machine})" for p, a in ok[:20])
        if len(ok) > 20:
            lines += f"\n  외 {len(ok) - 20}대"
        if skip:
            lines += "\n\n빼는 컴퓨터 (실행기 없음 또는 예전 실행기): " + ", ".join(str(p.no) for p in skip[:30])
        if QMessageBox.question(
                self, "MAC 고정",
                f"{len(ok)}대를 지금 연결된 실행기 PC의 MAC으로 고정할까요?\n\n{lines}\n\n"
                "그 PC 앞에서 실행기 창 둘째 줄의 MAC과 번호가 맞는지 먼저 확인하세요.") != QMessageBox.Yes:
            return
        errors = []
        for p, a in ok:
            try:
                self.repo.set_pc_mac(p.id, a.mac)
            except RepoError as e:
                errors.append(f"{p.no}. {p.name}: {e}")
        self.refresh()
        self._say(f"MAC 고정: {len(ok) - len(errors)}대")
        if errors:
            QMessageBox.warning(self, "일부 못 함", "\n".join(errors[:15]))

    def _reset_checked(self) -> None:
        targets = [p for p in self.pcs if p.id in self.checked]
        if not targets:
            QMessageBox.information(self, "실행기 초기화", "초기화할 컴퓨터를 체크하세요.")
            return
        linked = [p for p in targets if p.id in self.agents]
        lines = "\n".join(f"  {p.no}. {p.name}" + (f" ← {self.agents[p.id].machine}" if p.id in self.agents else "")
                          for p in targets[:20]) + (f"\n  외 {len(targets) - 20}대" if len(targets) > 20 else "")
        if QMessageBox.question(
                self, "실행기 초기화",
                f"{len(targets)}대의 정한 클라우드를 지우고, 연결된 실행기 {len(linked)}개를 떼어낼까요?\n\n{lines}\n\n"
                "떼어낸 실행기는 연결 대기로 돌아가요. 그다음 [컴퓨터별 클라우드 정하기]로 다시 정하거나 "
                "연결 대기에서 직접 [연결]하세요.") != QMessageBox.Yes:
            return
        errors = []
        for p in targets:
            try:
                reset_pc_launcher(self.repo, p, self.agents.get(p.id))
            except RepoError as e:
                errors.append(f"{p.no}. {p.name}: {e}")
        self.checked = set()
        self.all_box.setChecked(False)
        self.refresh()
        if errors:
            QMessageBox.warning(self, "일부 못 함", "\n".join(errors[:15]))

    def _all_devices(self) -> list:
        devs = set()
        for a in list(self.agents.values()) + list(self.pending):
            devs.update(d for d in a.devices if d and not d.startswith("("))
        return sorted(devs, key=cloud_sort_key)

    def _clouds(self) -> None:
        devs = self._all_devices()
        if not devs:
            QMessageBox.information(self, "클라우드 정하기", "아직 LD 클라우드 목록이 없어요. 실행기가 하나라도 켜지면 목록이 올라와요.")
            return
        dlg = CloudAssignDialog(self.repo, self.pcs, self.agents, devs, self)
        if dlg.exec():
            self.refresh()

    def _bulk_settings(self) -> None:
        targets = [p for p in self.pcs if p.id in self.checked]
        if len(targets) < 1:
            QMessageBox.information(self, "같은 설정", "설정을 바꿀 컴퓨터를 체크하세요.")
            return
        first = targets[0]
        dlg = AgentSettingsDialog(self.repo, first, self.agents.get(first.id), self, bulk=targets)
        if dlg.exec():
            self.refresh()

    def _settings(self, pc) -> None:
        dlg = AgentSettingsDialog(self.repo, pc, self.agents.get(pc.id), self, all_pcs=self.pcs, linked=set(self.agents),
                                  devices=self._all_devices())
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
            vals = [c["created_at"], kind_label(c["kind"], c.get("arg", "")), c.get("created_name", ""),
                    COMMAND_STATUS.get(c["status"], c["status"]), _took(c), c.get("result", "")]
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
        linked_mode = hasattr(self, "show_linked") and self.show_linked.isChecked()
        show = self.repo.me.can("can_link_agent") and (bool(self.pending) or linked_mode)
        self.pending_box.setVisible(show)
        if not show:
            self.pend.setRowCount(0)      # 다음에 다시 보일 때 예전 줄이 섞이지 않게
            self._pending_key = None
            return
        taken = set(self.agents)
        # MAC·버전이 바뀌어도(예전 실행기가 업데이트되면) 줄을 다시 그린다
        key = (tuple((a.user_id, a.pc_id, a.mac, a.version) for a in self.pending), tuple((p.id, p.mac) for p in self.pcs), tuple(sorted(taken)))
        if key != self._pending_key and self._picking():
            # 컴퓨터를 고르는 중(목록이 열려 있거나 그 칸을 누른 상태)이면 다 고를 때까지 새로 만들지 않는다
            return
        if key == self._pending_key:
            # 같은 목록이면 칸을 다시 만들지 않는다 (고르던 상자가 닫히거나 바뀌지 않게). 마지막 연락만 갱신
            for r, ag in enumerate(self.pending):
                self.pend.setItem(r, 3, _item(_ago(ag.seconds_ago)))
            return
        self._pending_key = key
        waiting = [a for a in self.pending if a.pc_id is None]
        old = [a for a in waiting if not a.mac]
        self.pend_title.setText(f"<b>연결 대기 실행기 {len(waiting)}개</b>" + (f" (예전 버전 {len(old)}개)" if old else ""))
        self.update_old_btn.setVisible(bool(old))
        self._plan_suggestions(taken)
        if self.repo.me.is_super and hasattr(self, "bulk_team"):
            cur = self.bulk_team.currentData()
            self.bulk_team.clear()
            for t in self.repo.teams:
                self.bulk_team.addItem(t.name, t.id)
            i = self.bulk_team.findData(cur if cur is not None else self.repo.team_id)
            self.bulk_team.setCurrentIndex(max(i, 0))
        self.pend.setRowCount(len(self.pending))
        same_pc = {a.machine: p for p, a in self.agents.items()}
        same_mac = {m: p for p, a in self.agents.items() for m in a.macs}
        pc_label = {p.id: f"{p.no}. {p.name}" for p in self.pcs}
        for r, ag in enumerate(self.pending):
            head = ag.mac or "MAC 모름 (예전 실행기)"
            mc = _item(f"{head}\n{ag.machine}")
            mc.setToolTip(f"MAC: {ag.mac or '모름'}\nWindows PC 이름: {ag.machine}\n"
                          "실행기 창 둘째 줄에도 같은 MAC이 보여요. 그 PC 앞에서 맞는지 확인하세요.")
            gone = self.displaced.get(ag.user_id)
            dup = next((same_mac[m] for m in ag.macs if m in same_mac and same_mac[m] != ag.pc_id), None)
            if ag.pc_id is not None:
                where = pc_label.get(ag.pc_id, "다른 팀 컴퓨터")
                mc = _item(f"{head}\n{ag.machine} · 지금 {where}")
                pcx = next((p for p in self.pcs if p.id == ag.pc_id), None)
                fixed = pcx is not None and pcx.mac and pcx.mac in ag.macs
                mc.setToolTip(f"지금 {where}에 연결돼 있어요" + (" (MAC 고정됨)" if fixed else " (MAC 미확인)")
                              + ".\n다른 컴퓨터를 골라 [연결]하면 옮겨지고, 같은 컴퓨터로 [연결]하면 MAC이 고정돼요.")
                if not fixed:
                    mc.setForeground(QColor("#D97706"))
            elif gone is not None:
                mc = _item(f"{head}\n{ag.machine} ({pc_label.get(gone, '?')}에서 풀림)")
                mc.setForeground(QColor("#D97706"))
                mc.setToolTip("방금 다른 실행기로 바꾸면서 연결이 풀린 실행기예요. 이 실행기가 원래 있어야 할 컴퓨터를 고르세요.\n"
                              "'그 PC가 여는 클라우드'는 풀리기 전 컴퓨터 설정에서 받은 값이라 맞지 않을 수 있어요.")
            elif dup is not None or (not ag.mac and ag.machine in same_pc):
                where = pc_label.get(dup if dup is not None else same_pc[ag.machine], "?")
                mc = _item(f"{head}\n{ag.machine} (같은 PC가 {where}에 연결됨)")
                mc.setForeground(QColor("#D97706"))
                mc.setToolTip("같은 PC(같은 MAC 또는 같은 Windows 이름)의 실행기가 이미 다른 컴퓨터 자리에 연결돼 있어요.\n"
                              "같은 PC에서 실행기를 두 번(다른 폴더에서) 켰거나 다시 설치했을 수 있어요. "
                              "쓰지 않는 쪽은 [지우기]로 지우세요.")
            self.pend.setItem(r, 0, mc)
            self.pend.setItem(r, 1, _item(ag.version))
            opens = _agent_cloud(ag)
            oc = _item(opens or "(정해지지 않음)")
            oc.setToolTip("그 PC 실행기가 여는 클라우드예요. [컴퓨터별 클라우드 정하기]에서 이 클라우드를 정해 둔 컴퓨터가 있으면 "
                          "자동으로 연결돼요.\n" + (self._why.get(ag.user_id) or ""))
            if not opens:
                oc.setForeground(QColor(T("muted")))
            self.pend.setItem(r, 2, oc)
            self.pend.setItem(r, 3, _item(_ago(ag.seconds_ago)))
            combo = QComboBox()
            combo.addItem("컴퓨터 고르기...", None)
            for p in self.pcs:
                chosen_cloud = ((p.agent_settings or {}).get("cloud") or "").split(" #")[0]
                note = ("  (지금 연결)" if p.id == ag.pc_id else
                        "  (실행기 있음 → 바꾸기)" if p.id in taken else
                        "  (다른 MAC 고정)" if p.mac and p.mac not in ag.macs else "")
                combo.addItem(f"{p.no}. {p.name}" + (f"  · {chosen_cloud}" if chosen_cloud else "") + note, p.id)
            wheel_only_when_focused(combo)  # 지나가다 휠을 굴려도 바뀌지 않게
            chosen = self.pending_choice.get(ag.user_id)
            idx = combo.findData(chosen) if chosen is not None else -1
            if idx < 0 and ag.pc_id is not None:
                idx = combo.findData(ag.pc_id)
            if idx < 0:
                idx = self._guess_index(ag, combo, taken)
            combo.setCurrentIndex(idx)
            combo.setToolTip(self._why.get(ag.user_id, "") or "추천할 컴퓨터가 없어요. 직접 고르세요.")
            combo.currentIndexChanged.connect(lambda _i, a=ag, c=combo: self.pending_choice.__setitem__(a.user_id, c.currentData()))
            self.pend.setCellWidget(r, 4, combo)
            w = QWidget()
            l = QHBoxLayout(w)
            l.setContentsMargins(4, 2, 4, 2)
            l.addWidget(button("연결", "primary", lambda _=False, a=ag, c=combo: self._link(a, c),
                               "고른 컴퓨터에 연결하고 이 PC의 MAC을 그 컴퓨터에 고정해요"))
            if ag.pc_id is None:
                l.addWidget(button("추천 다시", "", lambda _=False, a=ag, c=combo: self._reguess(a, c),
                                   "MAC이나 그 PC 실행기가 알려 준 LD 클라우드로 맞는 컴퓨터를 다시 골라요"))
                l.addWidget(button("지우기", "", lambda _=False, a=ag: self._forget(a), "잘못 등록된 실행기를 목록에서 지워요"))
            l.addStretch(1)
            self.pend.setCellWidget(r, 5, w)
            if self.repo.me.is_super and ag.pc_id is not None:
                tn = next((t.name for t in self.repo.teams if t.id == ag.team_id), "")
                self.pend.setItem(r, 6, _item(tn))
                self.pend.removeCellWidget(r, 6)
                self.pend.removeCellWidget(r, 7)
            elif self.repo.me.is_super:
                ck = QCheckBox()
                ck.setChecked(ag.user_id in self.pend_checked)
                ck.toggled.connect(lambda on, a=ag: (self.pend_checked.add if on else self.pend_checked.discard)(a.user_id))
                ckw = QWidget()
                ckl = QHBoxLayout(ckw)
                ckl.setContentsMargins(0, 0, 0, 0)
                ckl.setAlignment(Qt.AlignCenter)
                ckl.addWidget(ck)
                self.pend.setCellWidget(r, 7, ckw)
                tc = QComboBox()
                tc.addItem("(팀 정하기)", None)
                for t in self.repo.teams:
                    tc.addItem(t.name, t.id)
                tc.setCurrentIndex(max(tc.findData(ag.team_id), 0) if ag.team_id is not None else 0)
                tc.setToolTip("이 실행기가 어느 팀 PC인지. 정하면 그 팀 관리자에게도 보여요 (LD 목록으로 자동으로 못 정했을 때)")
                wheel_only_when_focused(tc)
                tc.activated.connect(lambda _i, a=ag, c=tc: self._set_team(a, c.currentData()))
                self.pend.setCellWidget(r, 6, tc)
        self._fit_pend_height()

    def _picking(self) -> bool:
        """연결 대기 표에서 컴퓨터를 고르는 중인지: 고르기 목록이 열려 있을 때만.
        (칸에 커서만 남아 있는 것까지 고르는 중으로 보면, 연결한 뒤에도 목록이 안 바뀐 것처럼 보였음)"""
        for r in range(self.pend.rowCount()):
            c = self.pend.cellWidget(r, 4)
            if isinstance(c, QComboBox) and c.view().isVisible():
                return True
        return False

    def _redraw_pending(self) -> None:
        """연결/지우기를 한 뒤: 고르는 중 여부와 상관없이 연결 대기 목록을 바로 새로 그린다."""
        self._pending_key = None
        self.setFocus()
        self._tick()

    def _say(self, text: str) -> None:
        w = self.window()
        if hasattr(w, "statusBar"):
            w.statusBar().showMessage(text, 8000)

    def _plan_suggestions(self, taken: set) -> None:
        """연결 대기 실행기마다 추천 컴퓨터를 정한다 (두 실행기에 같은 컴퓨터를 추천하지 않게)."""
        self._suggest, self._why = {}, {}
        used = set()
        # 확실한 것(정해 둔 클라우드)부터 정하도록: 그런 컴퓨터가 있는 실행기를 먼저
        order = sorted([a for a in self.pending if a.pc_id is None], key=lambda a: 0 if any(
            cloud_id((p.agent_settings or {}).get("cloud")) == cloud_id((a.state.get("cfg") or {}).get("cloud"))
            for p in self.pcs) else 1)
        for ag in order:
            gone = self.displaced.get(ag.user_id)
            pc, why = suggest_pc((ag.state.get("cfg") or {}).get("cloud") or "", self.pcs, taken,
                                 used | ({gone} if gone is not None else set()), ag.macs)
            if pc is not None:
                used.add(pc.id)
                self._suggest[ag.user_id] = pc.id
                self._why[ag.user_id] = "추천 이유: " + why

    def _guess_index(self, ag: Agent, combo: QComboBox, taken: set) -> int:
        """그 PC 실행기가 지금 여는 클라우드(또는 PC 이름)와 맞는 컴퓨터. 없으면 0(고르기)."""
        pid = getattr(self, "_suggest", {}).get(ag.user_id)
        i = combo.findData(pid) if pid is not None else -1
        return i if i > 0 else 0

    def _reguess(self, ag: Agent, combo: QComboBox) -> None:
        self.pending_choice.pop(ag.user_id, None)
        self._plan_suggestions(set(self.agents))
        combo.blockSignals(True)
        combo.setCurrentIndex(self._guess_index(ag, combo, set(self.agents)))
        combo.blockSignals(False)

    def _link(self, ag: Agent, combo: QComboBox) -> None:
        pid = combo.currentData()
        if pid is None:
            QMessageBox.information(self, "연결", "연결할 컴퓨터를 고르세요.")
            return
        target = next((p for p in self.pcs if p.id == pid), None)
        if pid == ag.pc_id:
            if target is not None and target.mac and target.mac in ag.macs:
                QMessageBox.information(self, "연결", "이미 이 컴퓨터에 연결돼 있고 MAC도 고정돼 있어요.")
                return
            if not ag.mac:
                QMessageBox.information(self, "연결", "예전 실행기라 MAC을 몰라요. [실행기 다시 켜기]로 새 버전이 되면 MAC을 고정할 수 있어요.")
                return
        elif pid in self.agents and QMessageBox.question(
                self, "연결", "이 컴퓨터에는 이미 실행기가 있어요. 새 실행기로 바꿀까요?") != QMessageBox.Yes:
            return
        elif ag.pc_id is not None and QMessageBox.question(
                self, "연결", f"이 실행기는 지금 다른 컴퓨터에 연결돼 있어요. {target.no if target else ''}번으로 옮길까요?\n"
                "(원래 컴퓨터는 실행기 없음이 되고, 그 컴퓨터의 MAC 고정도 풀려요)") != QMessageBox.Yes:
            return
        old = self.agents.get(pid)
        if run_safely(self, self.repo.link_agent, ag.user_id, pid):
            self.pending_choice.pop(ag.user_id, None)
            self.displaced.pop(ag.user_id, None)
            if old is not None and old.user_id != ag.user_id:
                # 원래 붙어 있던 실행기는 연결이 풀려 연결 대기로 온다. 그 실행기는 이 컴퓨터 설정(클라우드)을 받아 두었으니
                # 같은 컴퓨터를 또 추천하면 서로 자리만 바꾸게 되므로, 그 컴퓨터는 추천에서 뺀다
                self.displaced[old.user_id] = pid
                self.pending_choice.pop(old.user_id, None)
            try:
                self.repo.sync_pc_creds()
            except RepoError:
                pass
            self._redraw_pending()
            pc = next((p for p in self.pcs if p.id == pid), None)
            msg = (f"연결했어요: {ag.mac or ag.machine} → {pc.no}. {pc.name}" if pc else "연결했어요.") + (
                " (MAC 고정)" if ag.mac else "")
            if old is not None and old.user_id != ag.user_id:
                msg += (f"\n\n원래 이 컴퓨터에 있던 실행기({old.machine})는 연결이 풀려서 연결 대기 목록으로 옮겼어요. "
                        "그 실행기가 원래 있어야 할 컴퓨터를 골라 연결하세요. (주황색으로 표시돼요)")
                QMessageBox.information(self, "연결", msg)
            self._say(msg.split("\n")[0])

    def _update_old(self) -> None:
        old = [a for a in self.pending if a.pc_id is None and not a.mac]
        if not old:
            return
        names = ", ".join(a.machine for a in old[:12]) + (f" 외 {len(old) - 12}개" if len(old) > 12 else "")
        if QMessageBox.question(
                self, "예전 실행기 업데이트",
                f"연결 대기 중인 예전 실행기 {len(old)}개를 다시 켤까요?\n{names}\n\n"
                "다음 확인 때(최대 20초쯤) 그 PC의 실행기가 꺼졌다 켜지면서 새 버전으로 바뀌고, 그다음부터 MAC이 보여요.\n"
                "LD 작업 중인 실행기는 다시 켜지 않아요 (끝난 뒤 다시 누르세요).") != QMessageBox.Yes:
            return
        errors = []
        for a in old:
            try:
                self.repo.request_agent_restart(a.user_id)
            except RepoError as e:
                errors.append(f"{a.machine}: {e}")
        self._say(f"예전 실행기 {len(old) - len(errors)}개에 다시 켜기를 보냈어요. 1분쯤 뒤 MAC이 보여요.")
        if errors:
            QMessageBox.warning(self, "일부 못 함", "\n".join(errors[:15]))

    def _pend_check_all(self, on: bool) -> None:
        self.pend_checked = {a.user_id for a in self.pending if a.pc_id is None} if on else set()
        self._redraw_pending()

    def _bulk_team(self) -> None:
        chosen = [a for a in self.pending if a.user_id in self.pend_checked and a.pc_id is None]
        if not chosen:
            QMessageBox.information(self, "팀 정하기", "팀을 정할 실행기를 체크하세요 (오른쪽 '선택' 칸).")
            return
        code = self.bulk_code.text().strip().upper()
        if code:
            team = next((t for t in self.repo.teams if (t.join_code or "").upper() == code), None)
            if team is None:
                QMessageBox.warning(self, "팀 정하기", "그 실행 코드의 팀이 없어요. 팀 관리에서 코드를 확인하세요.")
                return
        else:
            team = next((t for t in self.repo.teams if t.id == self.bulk_team.currentData()), None)
        if team is None:
            return
        if QMessageBox.question(self, "팀 정하기", f"실행기 {len(chosen)}개를 '{team.name}' 팀으로 정할까요?") != QMessageBox.Yes:
            return
        errors = []
        for a in chosen:
            try:
                self.repo.set_agent_team(a.user_id, team.id)
            except RepoError as e:
                errors.append(f"{a.machine}: {e}")
        self.pend_checked = set()
        self.bulk_code.clear()
        if self.pend_all.isChecked():
            self.pend_all.blockSignals(True)
            self.pend_all.setChecked(False)
            self.pend_all.blockSignals(False)
        self._say(f"실행기 {len(chosen) - len(errors)}개를 '{team.name}' 팀으로 정했어요"
                  + ("" if team.id == self.repo.team_id else " (그 팀을 고르면 보여요)"))
        self._redraw_pending()
        if errors:
            QMessageBox.warning(self, "일부 못 함", "\n".join(errors[:15]))

    def _set_team(self, ag: Agent, team_id) -> None:
        if team_id is None or team_id == ag.team_id:
            return
        if run_safely(self, self.repo.set_agent_team, ag.user_id, team_id):
            name = next((t.name for t in self.repo.teams if t.id == team_id), "")
            self._say(f"{ag.machine} → {name} 실행기로 정했어요" + ("" if team_id == self.repo.team_id else " (그 팀을 고르면 보여요)"))
            self._redraw_pending()

    def _forget(self, ag: Agent) -> None:
        if QMessageBox.question(self, "지우기", f"'{ag.machine}' 실행기를 목록에서 지울까요?\n"
                                "그 PC의 실행기가 다시 켜지면 또 나타나요.") != QMessageBox.Yes:
            return
        if run_safely(self, self.repo.forget_agent, ag.user_id):
            self.pending_choice.pop(ag.user_id, None)
            self._redraw_pending()
