"""작업장 화면: 컴퓨터 카드와 자리, 오른쪽에 자리 상세/계정 고르기 패널."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QScrollArea, QSplitter, QVBoxLayout, QWidget,
)

from ..db import Repository
from ..models import PC, PROVIDERS, STATUS_AVAILABLE, STATUS_BANNED, Account
from .common import badge, copy_text, muted, run_safely
from .dialogs import AccountDialog, PcDialog


class SlotWidget(QFrame):
    clicked = Signal(int, int)        # pc_id, slot
    double_clicked = Signal(int, int)

    def __init__(self, pc: PC, slot: int, acc: Account | None, selected: bool):
        super().__init__()
        self.pc_id, self.slot = pc.id, slot
        self.setObjectName("slot")
        self.setProperty("empty", acc is None)
        self.setProperty("selected", selected)
        self.setCursor(Qt.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 5, 8, 5)
        if acc is None:
            lab = muted(f"+ {slot}자리 비어있음")
            lay.addStretch(1)
            lay.addWidget(lab)
            lay.addStretch(1)
            return
        col = QVBoxLayout()
        col.setSpacing(0)
        top = QLabel(f"{acc.owner or '(명의자 없음)'}  <span style='color:#6B6A64;font-size:11px'>{acc.provider} · {acc.login_id}</span>")
        col.addWidget(top, 0, Qt.AlignLeft)
        sub = muted(acc.main_char() or "캐릭터 없음")
        col.addWidget(sub, 0, Qt.AlignLeft)
        lay.addLayout(col, 1)
        for lab in acc.ban_labels():
            lay.addWidget(badge(lab.split("~")[0], "ban"), 0, Qt.AlignVCenter)

    def mousePressEvent(self, e):
        self.clicked.emit(self.pc_id, self.slot)

    def mouseDoubleClickEvent(self, e):
        self.double_clicked.emit(self.pc_id, self.slot)


class PcCard(QFrame):
    def __init__(self, pc: PC, accs: dict[int, Account], selected: tuple | None, owner: "WorkplaceTab"):
        super().__init__()
        self.setObjectName("pcCard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 10)
        lay.setSpacing(5)
        head = QHBoxLayout()
        title = QLabel(pc.title())
        title.setObjectName("title")
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(muted(pc.ld_cloud))
        if owner.worker_names:
            head.addWidget(badge(owner.worker_names.get(pc.worker_id, "담당 없음"), "사용중" if pc.worker_id else "탈퇴"))
        can_edit = owner.repo.me.is_admin or owner.repo.me.can("can_edit_pc")
        edit = QPushButton("수정" if can_edit else "정보")
        edit.setFixedWidth(44)
        edit.clicked.connect(lambda: owner.edit_pc(pc))
        head.addWidget(edit)
        lay.addLayout(head)
        info = " · ".join(x for x in (f"AnyDesk {pc.anydesk_id}" if pc.anydesk_id else "",
                                      f"리모트T {pc.remote_t}" if pc.remote_t else "") if x)
        if info:
            lay.addWidget(muted(info))
        for i, aid in enumerate(pc.slots, start=1):
            w = SlotWidget(pc, i, accs.get(aid) if aid else None, selected == (pc.id, i))
            w.clicked.connect(owner.select_slot)
            w.double_clicked.connect(owner.open_slot)
            lay.addWidget(w)


class WorkplaceTab(QWidget):
    changed = Signal()

    def __init__(self, repo: Repository):
        super().__init__()
        self.repo = repo
        self.pcs: list[PC] = []
        self.accs: dict[int, Account] = {}
        self.selected: tuple[int, int] | None = None
        self.worker_names: dict[str | None, str] = {}  # 클라우드 관리자에게만 담당자 표시

        # 요약 + 검색
        self.metrics = {}
        top = QHBoxLayout()
        for key, label in (("pc", "컴퓨터"), ("empty", "빈 자리"), ("avail", "사용가능 계정"), ("ban", "양쪽 정지 계정")):
            box = QFrame()
            box.setObjectName("metricBox")
            bl = QVBoxLayout(box)
            bl.setContentsMargins(12, 6, 12, 6)
            bl.addWidget(muted(label))
            v = QLabel("0")
            v.setObjectName("metric")
            bl.addWidget(v)
            self.metrics[key] = v
            top.addWidget(box)
        self.search = QLineEdit()
        self.search.setPlaceholderText("컴퓨터 번호, 이름, 명의자, 아이디, 닉네임 검색")
        self.search.textChanged.connect(self._render_cards)
        bar = QHBoxLayout()
        bar.addWidget(self.search, 1)
        if repo.me.is_admin:
            add_pc = QPushButton("컴퓨터 추가")
            add_pc.clicked.connect(lambda: self.edit_pc(None))
            bar.addWidget(add_pc)

        # 카드 영역 (_render_cards가 채움)
        scroll = self.scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # 오른쪽 패널
        self.panel = QFrame()
        self.panel.setObjectName("panel")
        self.panel.setMinimumWidth(330)
        self.panel.setMaximumWidth(460)
        self.panel_lay = QVBoxLayout(self.panel)

        split = QSplitter()
        split.addWidget(scroll)
        split.addWidget(self.panel)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        split.setCollapsible(0, False)
        split.setSizes([1000, 380])

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addLayout(bar)
        lay.addWidget(split, 1)

    # ---------------------------------------------------------------- 데이터
    def refresh(self) -> None:
        self.pcs = self.repo.list_pcs()
        self.accs = {a.id: a for a in self.repo.list_accounts()}
        if self.repo.is_cloud and self.repo.me.is_admin:
            self.worker_names = {w.id: w.display_name for w in self.repo.list_workers()}
        if self.selected and not self._pc(self.selected[0]):
            self.selected = None
        self.metrics["pc"].setText(str(len(self.pcs)))
        self.metrics["empty"].setText(str(sum(1 for p in self.pcs for x in p.slots if x is None)))
        self.metrics["avail"].setText(str(sum(1 for a in self.accs.values() if a.status == STATUS_AVAILABLE)))
        self.metrics["ban"].setText(str(sum(1 for a in self.accs.values() if a.status == STATUS_BANNED)))
        self._render_cards()
        self._render_panel()

    def _pc(self, pc_id: int) -> PC | None:
        return next((p for p in self.pcs if p.id == pc_id), None)

    def _after_change(self) -> None:
        self.refresh()
        self.changed.emit()

    # ---------------------------------------------------------------- 카드
    def _columns(self) -> int:
        return max(1, (self.scroll.viewport().width() - 10) // 330)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._columns() != getattr(self, "_last_cols", None):
            self._render_cards()

    def _render_cards(self) -> None:
        # 카드 영역을 통째로 새로 만든다 (스크롤 위치는 유지)
        pos = self.scroll.verticalScrollBar().value()
        self.cards_host = QWidget()
        self.grid = QGridLayout(self.cards_host)
        self.grid.setSpacing(10)
        self.grid.setAlignment(Qt.AlignTop)
        q = self.search.text().strip().lower()
        cols = self._last_cols = self._columns()
        n = 0
        for pc in self.pcs:
            if q:
                hay = f"{pc.no} {pc.name} {pc.ld_cloud} {pc.anydesk_id}".lower()
                hay += " ".join(self.accs[a].search_text() for a in pc.slots if a and a in self.accs)
                if q not in hay:
                    continue
            self.grid.addWidget(PcCard(pc, self.accs, self.selected, self), n // cols, n % cols)
            n += 1
        if n == 0:
            self.grid.addWidget(muted("표시할 컴퓨터가 없어요. 엑셀을 가져오거나 컴퓨터를 추가하세요."), 0, 0)
        for c in range(cols):
            self.grid.setColumnStretch(c, 1)
        self.scroll.setWidget(self.cards_host)  # 이전 위젯은 스크롤 영역이 지운다
        self.scroll.verticalScrollBar().setValue(pos)

    # ---------------------------------------------------------------- 패널
    def _clear_panel(self) -> None:
        def clear(layout):
            while layout.count():
                item = layout.takeAt(0)
                w = item.widget()
                if w:
                    w.setParent(None)
                    w.deleteLater()
                elif item.layout():
                    clear(item.layout())
        clear(self.panel_lay)

    def _render_panel(self) -> None:
        self._clear_panel()
        self._fill_panel()
        for lab in self.panel.findChildren(QLabel):
            lab.setWordWrap(True)

    def _fill_panel(self) -> None:
        L = self.panel_lay
        if not self.selected:
            t = QLabel("자리를 선택하세요")
            t.setObjectName("title")
            L.addWidget(t)
            L.addWidget(muted("빈 자리를 누르면 넣을 수 있는 계정만 보여요.\n계정이 든 자리를 누르면 정보와 빼기/옮기기가 나와요."))
            L.addStretch(1)
            return
        pc = self._pc(self.selected[0])
        slot = self.selected[1]
        aid = pc.slots[slot - 1] if pc and slot <= len(pc.slots) else None
        t = QLabel(f"{pc.no}번 컴퓨터 {slot}자리")
        t.setObjectName("title")
        L.addWidget(t)
        if aid and aid in self.accs:
            self._render_occupied(self.accs[aid])
        else:
            self._render_picker()

    def _render_occupied(self, a: Account) -> None:
        L = self.panel_lay
        L.addWidget(QLabel(f"<b>{a.owner or '(명의자 없음)'}</b>  {a.contact}"))
        L.addWidget(muted(f"{a.provider} · 메월닉 {a.tag or '-'}"))
        row = QHBoxLayout()
        row.addWidget(QLabel(a.login_id), 1)
        b1 = QPushButton("아이디 복사")
        b1.clicked.connect(lambda: copy_text(a.login_id))
        b2 = QPushButton("비번 복사")
        b2.clicked.connect(lambda: copy_text(a.password))
        row.addWidget(b1)
        row.addWidget(b2)
        L.addLayout(row)
        for game in ("메랜", "플래닛"):
            chars = a.chars(game)
            L.addWidget(muted(f"{game}: " + (", ".join(c.text() for c in chars) if chars else "캐릭터 없음")))
        bans = a.ban_labels()
        if bans:
            br = QHBoxLayout()
            for lab in bans:
                br.addWidget(badge(lab, "ban"))
            br.addStretch(1)
            L.addLayout(br)
        if a.note:
            n = muted("비고: " + a.note)
            n.setWordWrap(True)
            L.addWidget(n)
        acts = QHBoxLayout()
        e = QPushButton("계정 수정" if self.repo.me.can("can_edit_account") else "계정 정보")
        e.clicked.connect(lambda: self.open_slot(*self.selected))
        m = QPushButton("다른 자리로 옮기기")
        m.clicked.connect(lambda: self._move(a))
        u = QPushButton("빼기")
        u.clicked.connect(lambda: self._unassign(a))
        acts.addWidget(e)
        acts.addWidget(m)
        acts.addWidget(u)
        L.addLayout(acts)
        L.addStretch(1)

    def _render_picker(self) -> None:
        L = self.panel_lay
        L.addWidget(muted("넣을 수 있는 계정만 보여요 (미배정, 탈퇴 아님, 양쪽 게임 모두 정지는 아님)"))
        fl = QHBoxLayout()
        self.pick_search = QLineEdit()
        self.pick_search.setPlaceholderText("명의자, 아이디, 닉네임")
        self.pick_provider = QComboBox()
        self.pick_provider.addItems(["전체"] + list(PROVIDERS))
        self.pick_ban = QComboBox()
        self.pick_ban.addItems(["정지 포함", "정지 없는 계정만", "메랜 가능", "플래닛 가능"])
        fl.addWidget(self.pick_search, 1)
        fl.addWidget(self.pick_provider)
        L.addLayout(fl)
        L.addWidget(self.pick_ban)
        self.pick_list = QListWidget()
        self.pick_list.itemDoubleClicked.connect(lambda _: self._assign_selected())
        L.addWidget(self.pick_list, 1)
        btn = QPushButton("이 자리에 넣기")
        btn.clicked.connect(self._assign_selected)
        L.addWidget(btn)
        self.pick_search.textChanged.connect(self._fill_picker)
        self.pick_provider.currentTextChanged.connect(self._fill_picker)
        self.pick_ban.currentTextChanged.connect(self._fill_picker)
        self._fill_picker()

    def _fill_picker(self) -> None:
        self.pick_list.clear()
        q = self.pick_search.text().strip().lower()
        prov = self.pick_provider.currentText()
        ban_mode = self.pick_ban.currentText()
        for a in sorted(self.accs.values(), key=lambda x: (x.owner, x.login_id)):
            if not a.assignable:
                continue
            if prov != "전체" and a.provider != prov:
                continue
            if q and q not in a.search_text():
                continue
            if ban_mode == "정지 없는 계정만" and a.ban_labels():
                continue
            if ban_mode == "메랜 가능" and a.mr_ban.active():
                continue
            if ban_mode == "플래닛 가능" and a.pl_ban.active():
                continue
            text = f"{a.owner or '(명의자 없음)'}  [{a.provider}] {a.login_id}\n    {a.main_char() or '캐릭터 없음'}"
            if a.ban_labels():
                text += "   ※ " + ", ".join(a.ban_labels())
            it = QListWidgetItem(text)
            it.setData(Qt.UserRole, a.id)
            self.pick_list.addItem(it)
        if self.pick_list.count() == 0:
            it = QListWidgetItem("조건에 맞는 사용가능 계정이 없어요")
            it.setFlags(Qt.NoItemFlags)
            self.pick_list.addItem(it)

    # ---------------------------------------------------------------- 동작
    def select_slot(self, pc_id: int, slot: int) -> None:
        self.selected = (pc_id, slot)
        self._render_cards()
        self._render_panel()

    def open_slot(self, pc_id: int, slot: int) -> None:
        pc = self._pc(pc_id)
        aid = pc.slots[slot - 1] if pc else None
        if aid and aid in self.accs:
            if AccountDialog(self.repo, self.accs[aid], self).exec():
                self._after_change()
        else:
            self.select_slot(pc_id, slot)

    def _assign_selected(self) -> None:
        it = self.pick_list.currentItem()
        aid = it.data(Qt.UserRole) if it else None
        if not aid or not self.selected:
            QMessageBox.information(self, "계정 선택", "넣을 계정을 목록에서 고르세요.")
            return
        if run_safely(self, self.repo.assign, self.selected[0], self.selected[1], aid):
            self._after_change()
        else:
            self.refresh()

    def _unassign(self, a: Account) -> None:
        if QMessageBox.question(self, "빼기", f"{a.location.text()}에서 {a.login_id} 계정을 뺄까요?") == QMessageBox.Yes:
            run_safely(self, self.repo.unassign, a.location.pc_id, a.location.slot)
            self._after_change()

    def _move(self, a: Account) -> None:
        empties = [(p, i) for p in self.pcs for i, x in enumerate(p.slots, start=1) if x is None]
        if not empties:
            QMessageBox.information(self, "옮기기", "빈 자리가 없어요.")
            return
        labels = [f"{p.no}번 컴퓨터 {i}자리  ({p.name})" for p, i in empties]
        choice, ok = QInputDialog.getItem(self, "다른 자리로 옮기기", f"{a.login_id} 계정을 옮길 자리", labels, 0, False)
        if ok:
            p, i = empties[labels.index(choice)]
            if run_safely(self, self.repo.move, a.id, p.id, i):
                self.selected = (p.id, i)
            self._after_change()

    def edit_pc(self, pc: PC | None) -> None:
        next_no = max((p.no for p in self.pcs), default=0) + 1
        dlg = PcDialog(self.repo, pc, next_no, self)
        if dlg.exec():
            if dlg.deleted:
                self.selected = None
            self._after_change()
