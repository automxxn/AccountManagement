"""PC 조종 '현황판' 보기: 컴퓨터마다 블록(카드) 하나. 카드를 누르면 체크(명령 보낼 대상) + 아래에 명령 기록.

표 보기와 같은 데이터(AgentsTab.pcs / agents / commands / checked)를 그대로 쓴다.
카드는 컴퓨터 목록이 바뀔 때만 새로 만들고, 몇 초마다는 글자와 색만 바꾼다 (깜빡임 없게).
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from ..models import COMMAND_STATUS
from .common import T, button, px

CARD_W = 236   # 가로 '자동'일 때 카드 하나의 대략 폭 (화면 배율 반영 전)


class ElidedLabel(QLabel):
    """칸보다 긴 글은 '…'로 줄여서 한 줄로 (전체는 툴팁)."""

    def __init__(self, text: str = "", name: str = ""):
        super().__init__(text)
        if name:
            self.setObjectName(name)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(1)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setPen(self.palette().color(self.foregroundRole()))
        r = self.contentsRect()
        p.drawText(r, int(Qt.AlignLeft | Qt.AlignVCenter),
                   self.fontMetrics().elidedText(self.text(), Qt.ElideRight, r.width()))


def _repolish(w: QWidget, **props) -> None:
    changed = False
    for k, v in props.items():
        if w.property(k) != v:
            w.setProperty(k, v)
            changed = True
    if changed:
        w.style().unpolish(w)
        w.style().polish(w)
        w.update()


def _color(lab: QLabel, key: str | None, bold: bool = False) -> None:
    css = (f"color:{T(key)};" if key else "") + ("font-weight:bold;" if bold else "")
    if lab.styleSheet() != css:
        lab.setStyleSheet(css)


class PcCard(QFrame):
    def __init__(self, board: "PcBoard", pc_id: int):
        super().__init__()
        self.board = board
        self.pc_id = pc_id
        self.setObjectName("pcCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumWidth(px(170))
        v = QVBoxLayout(self)
        v.setContentsMargins(px(12), px(10), px(12), px(10))
        v.setSpacing(px(5))

        top = QHBoxLayout()
        top.setSpacing(px(6))
        self.box = QCheckBox()
        self.box.setToolTip("체크하면 위 버튼(시작·로그인 등)이 이 컴퓨터에도 가요. 카드 아무 데나 눌러도 돼요")
        self.box.toggled.connect(lambda on: board.on_check(self.pc_id, on))
        self.no = QLabel()
        self.no.setObjectName("cardNo")
        self.name = ElidedLabel("", "cardName")
        self.set_btn = button("설정", "", lambda: board.on_settings(self.pc_id), "이 컴퓨터의 실행기 설정")
        self.set_btn.setObjectName("cardBtn")
        top.addWidget(self.box)
        top.addWidget(self.no)
        top.addWidget(self.name, 1)
        top.addWidget(self.set_btn)
        v.addLayout(top)

        self.state = ElidedLabel()
        v.addWidget(self.state)

        slots = QHBoxLayout()
        slots.setSpacing(px(6))
        self.slot_names = []
        self.slot_tags = []
        for tag in ("A · 1자리", "B · 2자리"):
            f = QFrame()
            f.setObjectName("cardSlot")
            sl = QVBoxLayout(f)
            sl.setContentsMargins(px(8), px(5), px(8), px(6))
            sl.setSpacing(px(1))
            t = QLabel(tag)
            t.setObjectName("cardTag")
            n = ElidedLabel("", "cardAcc")
            self.slot_tags.append(t)
            sl.addWidget(t)
            sl.addWidget(n)
            slots.addWidget(f, 1)
            self.slot_names.append(n)
        v.addLayout(slots)

        self.now = ElidedLabel()
        v.addWidget(self.now)
        line = QFrame()
        line.setObjectName("cardLine")
        line.setFixedHeight(1)
        v.addWidget(line)
        self.last = ElidedLabel("", "cardSmall")
        self.res = ElidedLabel("", "cardSmall")
        v.addWidget(self.last)
        v.addWidget(self.res)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.LeftButton:
            self.board.on_pick(self.pc_id)
            self.box.toggle()
            e.accept()
            return
        super().mousePressEvent(e)

    def set_checked(self, on: bool) -> None:
        if self.box.isChecked() != on:
            self.box.blockSignals(True)
            self.box.setChecked(on)
            self.box.blockSignals(False)
        _repolish(self, checked=on)

    def set_current(self, on: bool) -> None:
        _repolish(self, current=on)


class PcBoard(QScrollArea):
    """카드들을 가로 N칸으로 깔아 둔다 (N = '자동'이면 창 폭에 맞춰)."""

    def __init__(self, tab):
        super().__init__()
        self.tab = tab
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        host = QWidget()
        host.setObjectName("scrollHost")
        self.grid = QGridLayout(host)
        self.grid.setContentsMargins(0, 0, px(4), 0)
        self.grid.setSpacing(px(10))
        self.grid.setAlignment(Qt.AlignTop)
        self.setWidget(host)
        self.cards: dict[int, PcCard] = {}
        self.order: list[int] = []
        self.fixed_cols = 0      # 0 = 자동
        self._cols = 0
        self.current: int | None = None

    # ------------------------------------------------------------ 배치
    def cols(self) -> int:
        if self.fixed_cols:
            return self.fixed_cols
        sp = self.grid.spacing()
        w = self.viewport().width() - px(4)
        return max(1, (w + sp) // (px(CARD_W) + sp))

    def set_fixed_cols(self, n: int) -> None:
        self.fixed_cols = n
        self._place(force=True)

    def _place(self, force: bool = False) -> None:
        n = self.cols()
        if n == self._cols and not force:
            return
        old = max(self._cols, 1)
        self._cols = n
        while self.grid.count():
            self.grid.takeAt(0)
        for c in range(max(old, n)):
            self.grid.setColumnStretch(c, 1 if c < n else 0)
        for i, pid in enumerate(self.order):
            self.grid.addWidget(self.cards[pid], i // n, i % n)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._place()

    def set_pcs(self, ids: list[int]) -> None:
        if ids == self.order:
            return
        for pid in list(self.cards):
            if pid not in ids:
                card = self.cards.pop(pid)
                card.setParent(None)
                card.deleteLater()
        for pid in ids:
            if pid not in self.cards:
                self.cards[pid] = PcCard(self, pid)
        self.order = list(ids)
        self._place(force=True)

    # ------------------------------------------------------------ 카드 → 탭
    def on_check(self, pc_id: int, on: bool) -> None:
        self.cards[pc_id].set_checked(on)
        self.tab._card_check(pc_id, on)

    def on_pick(self, pc_id: int) -> None:
        self.set_current(pc_id)
        self.tab._card_pick(pc_id)

    def on_settings(self, pc_id: int) -> None:
        pc = next((p for p in self.tab.pcs if p.id == pc_id), None)
        if pc:
            self.tab._settings(pc)

    def set_current(self, pc_id: int | None) -> None:
        self.current = pc_id
        for pid, card in self.cards.items():
            card.set_current(pid == pc_id)

    # ------------------------------------------------------------ 내용
    def render(self) -> dict:
        """카드 내용을 지금 상태로. 켜짐/작업 중/꺼짐/없음 개수를 돌려준다."""
        tab = self.tab
        self.set_pcs([p.id for p in tab.pcs])
        counts = {"on": 0, "busy": 0, "off": 0, "none": 0}
        mine = getattr(tab.repo, "team_id", None)
        for pc in tab.pcs:
            card = self.cards[pc.id]
            card.no.setText(f"{pc.no:02d}" if isinstance(pc.no, int) else str(pc.no))
            card.name.setText(pc.name)
            card.name.setToolTip(pc.name)
            ag = tab.agents.get(pc.id)
            s = (ag.state or {}) if ag else {}
            if ag is None:
                key, text = "none", "○ 실행기 없음" + (f" · MAC {pc.mac} 기다리는 중" if pc.mac else "")
                tip = ("이 컴퓨터에 연결된 실행기가 없어요."
                       + (f"\nMAC {pc.mac} 실행기가 켜지면 자동으로 연결돼요." if pc.mac else ""))
                color = "faint"
            else:
                bits = []
                if ag.online:
                    key = "busy" if s.get("busy") else "on"
                    bits.append("● 작업 중" if key == "busy" else "● 켜짐")
                    if s.get("realtime") is False:
                        bits.append("20초마다")
                    if s.get("window") is not None:
                        bits.append("창 열림" if s.get("window") else "트레이")
                    color = "accent_text" if key == "busy" else "success"
                else:
                    key = "off"
                    bits.append("● 꺼짐 (" + _ago_short(ag.seconds_ago) + ")")
                    color = "danger"
                if ag.team_id != mine:
                    bits.append("⚠ 실행기 팀 다름")
                text = " · ".join(bits)
                tip = (f"MAC: {ag.mac or '(모름 — 예전 실행기)'}"
                       + ("  (이 컴퓨터에 고정됨)" if pc.mac and pc.mac in ag.macs else "  (MAC 미확인)")
                       + f"\nWindows PC 이름: {ag.machine}\n실행기 버전: v{ag.version}")
            counts[key] += 1
            card.state.setText(text)
            card.state.setToolTip(tip)
            _color(card.state, color, bold=True)
            _repolish(card, off=(key in ("off", "none")))

            for i, lab in enumerate(card.slot_names):
                aid = pc.slots[i] if len(pc.slots) > i else None
                name = tab.acc_names.get(aid, "") if aid else ""
                game, login = "", name
                if name.startswith("[") and "] " in name:   # "[게임] 아이디" → 게임은 작은 글씨로, 칸엔 아이디만
                    game, login = name[1:].split("] ", 1)
                card.slot_tags[i].setText(("A" if i == 0 else "B") + (f" · {game}" if game else f" · {i + 1}자리"))
                lab.setText(login or "비어 있음")
                lab.setToolTip(name)
                _color(lab, None if name else "faint")

            if s.get("busy"):
                card.now.setText("▶ " + (s.get("job") or "작업 중"))
                _color(card.now, "accent_text")
            else:
                card.now.setText(s.get("last") or ("대기" if ag and ag.online else " "))
                _color(card.now, "ink2")
            card.now.setToolTip(s.get("last", ""))

            last = (tab.commands.get(pc.id) or [None])[0]
            if last:
                from .agents import kind_label   # 순환 import 피하기
                st = COMMAND_STATUS.get(last["status"], "")
                card.last.setText(f"마지막: {kind_label(last['kind'], last.get('arg', ''))} · {st}")
                card.last.setToolTip(f"{last['created_at']} {last.get('created_name', '')}")
                card.res.setText(last.get("result", "") or " ")
                card.res.setToolTip(last.get("result", ""))
                _color(card.last, "danger" if last["status"] == "failed" else "muted")
                _color(card.res, "danger" if last["status"] == "failed" else "muted")
            else:
                card.last.setText("마지막: 보낸 명령 없음")
                card.last.setToolTip("")
                card.res.setText(" ")
                _color(card.last, "faint")
            card.set_checked(pc.id in tab.checked)
            card.set_current(pc.id == tab.current_pc)
        return counts


def _ago_short(sec) -> str:
    if sec is None:
        return "연락 없음"
    sec = int(sec)
    if sec < 60:
        return f"{sec}초 전"
    if sec < 3600:
        return f"{sec // 60}분 전"
    if sec < 86400:
        return f"{sec // 3600}시간 전"
    return f"{sec // 86400}일 전"
