"""작업장 화면: 컴퓨터를 한 줄에 한 대씩 나열하고, 오른쪽 패널에서 자리 정보 확인/계정 넣기."""
from __future__ import annotations

import copy

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from ..models import GAMES, PC, PROVIDERS, Account, owner_rule_violation
from .common import (
    StatCard, T, badge, button, copy_text, label, muted, page_header, px, run_safely, vline,
)
from .dialogs import AccountDialog, PcDialog

PC_FILTERS = ["모든 컴퓨터", "빈 자리가 있는 컴퓨터", "정지 계정이 있는 컴퓨터"]
MIN_SLOTS = 2  # 컴퓨터마다 기본 자리 수 (이 밑으로는 줄일 수 없음)


def _repolish(w: QWidget) -> None:
    w.style().unpolish(w)
    w.style().polish(w)


def _shrinkable(w: QLabel) -> QLabel:
    """좁으면 글자를 잘라서라도 줄 폭을 지킨다."""
    w.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    w.setMinimumWidth(0)
    return w


def char_line(acc: Account, compact: bool = False) -> str:
    """'메랜: 닉 104 프리 · 플래닛: 없음' (게임별 대표 캐릭터). compact면 캐릭터 있는 게임만."""
    parts = []
    for game in GAMES:
        m = acc.main(game)
        more = len(acc.chars(game)) - 1
        if m:
            parts.append(f"{game}: {m.text()}" + (f" 외 {more}" if more > 0 else ""))
        elif not compact:
            parts.append(f"{game}: 없음")
    return "   ·   ".join(parts) if parts else "캐릭터 없음"


class SlotWidget(QFrame):
    """자리 한 줄: [번호] 명의자 [유형] 아이디 ……… 메랜/플래닛 대표 캐릭터 [정지]"""
    clicked = Signal(int, int)        # pc_id, slot
    double_clicked = Signal(int, int)

    def __init__(self, pc: PC, slot: int, acc: Account | None, selected: bool, hidden: bool = False):
        super().__init__()
        self.pc_id, self.slot = pc.id, slot
        self.setObjectName("slot")
        self.setProperty("empty", acc is None and not hidden)
        self.setProperty("locked", hidden)
        self.setProperty("selected", selected)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(px(44))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(px(12), px(6), px(12), px(6))
        lay.setSpacing(px(8))
        lay.addWidget(label(str(slot), "slotNo"))

        if hidden or acc is None:
            text = "다른 담당자의 계정 사용 중" if hidden else "비어 있음 · 눌러서 계정 넣기"
            lay.addWidget(label(text, "slotLocked" if hidden else "slotHint"))
            lay.addStretch(1)
            return

        owner = label(acc.owner or acc.contact or "(명의자 없음)", "owner")
        owner.setMinimumWidth(px(70))
        lay.addWidget(owner)
        lay.addWidget(badge(acc.provider, "info"))
        lid = _shrinkable(muted(acc.login_id))
        lay.addWidget(lid, 2)
        chars = _shrinkable(label(char_line(acc, compact=True), "slotChars"))
        tip = [f"{'★ ' if i == 0 else '   '}[{c.game}] {c.text()}" for g in GAMES for i, c in enumerate(acc.chars(g))]
        chars.setToolTip(chr(10).join(tip))
        lay.addWidget(chars, 3)
        for lab in acc.ban_labels():
            lay.addWidget(badge(lab.split("~")[0], "ban"))

    def mousePressEvent(self, e):
        self.clicked.emit(self.pc_id, self.slot)

    def mouseDoubleClickEvent(self, e):
        self.double_clicked.emit(self.pc_id, self.slot)


class PcRow(QFrame):
    def __init__(self, pc: PC, accs: dict[int, Account], selected: tuple | None, owner: "WorkplaceTab"):
        super().__init__()
        self.setObjectName("pcRow")
        self.setProperty("active", bool(selected and selected[0] == pc.id))
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(16)
        can_edit = owner.repo.me.is_admin or owner.repo.me.can("can_edit_pc")

        info = QWidget()
        info.setFixedWidth(px(200))
        il = QVBoxLayout(info)
        il.setContentsMargins(0, 0, 0, 0)
        il.setSpacing(3)
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(label(str(pc.no), "pcNo"))
        head.addWidget(label(pc.name or "(이름 없음)", "pcName"), 1)
        il.addLayout(head)
        for k, v in (("LD", pc.ld_cloud), ("AnyDesk", pc.anydesk_id), ("리모트T", pc.remote_t)):
            if v:
                il.addWidget(muted(f"{k}  {v}"))
        il.addStretch(1)
        bottom = QHBoxLayout()
        bottom.setSpacing(6)
        if owner.worker_names:
            if pc.worker_id:
                bottom.addWidget(badge("담당 " + owner.worker_names.get(pc.worker_id, "?"), "worker"))
            else:
                bottom.addWidget(badge("담당 없음", "info"))
        bottom.addStretch(1)
        bottom.addWidget(button("수정" if can_edit else "정보", "ghost", lambda: owner.edit_pc(pc)))
        il.addLayout(bottom)
        lay.addWidget(info)
        lay.addWidget(vline())

        # 자리는 위아래로 한 줄씩
        col = QVBoxLayout()
        col.setSpacing(px(6))
        for i, aid in enumerate(pc.slots, start=1):
            w = SlotWidget(pc, i, accs.get(aid) if aid else None, selected == (pc.id, i),
                           hidden=bool(aid) and aid not in accs)
            w.clicked.connect(owner.select_slot)
            w.double_clicked.connect(owner.open_slot)
            col.addWidget(w)
        if can_edit:
            tools = QHBoxLayout()
            tools.setSpacing(4)
            tools.addStretch(1)
            tools.addWidget(button("+ 자리 추가", "ghost", lambda: owner.change_slots(pc, +1),
                                   "이 컴퓨터에 계정 자리를 하나 더 만들어요"))
            if pc.slot_count > MIN_SLOTS:
                tools.addWidget(button("- 마지막 자리 삭제", "ghost", lambda: owner.change_slots(pc, -1),
                                       "맨 아래 자리를 없애요 (비어 있을 때만)"))
            col.addLayout(tools)
        col.addStretch(1)
        lay.addLayout(col, 1)


class WorkplaceTab(QWidget):
    changed = Signal()

    def __init__(self, repo):
        super().__init__()
        self.setObjectName("page")
        self.repo = repo
        self.pcs: list[PC] = []
        self.accs: dict[int, Account] = {}
        self.selected: tuple[int, int] | None = None
        self.worker_names: dict[str | None, str] = {}  # 클라우드 관리자에게만 담당자 표시

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(16)
        root.addWidget(page_header("작업장", "컴퓨터마다 어떤 계정이 들어 있는지 보고, 빈 자리에 계정을 넣어요"))

        stats = QHBoxLayout()
        stats.setSpacing(12)
        self.stat_pc = StatCard("컴퓨터")
        self.stat_empty = StatCard("빈 자리", "accent")
        self.stat_avail = StatCard("넣을 수 있는 계정", "success")
        self.stat_ban = StatCard("양쪽 게임 모두 정지", "danger")
        for s in (self.stat_pc, self.stat_empty, self.stat_avail, self.stat_ban):
            stats.addWidget(s)
        root.addLayout(stats)

        body = QHBoxLayout()
        body.setSpacing(20)

        # 왼쪽: 도구 막대 + 컴퓨터 목록
        left = QVBoxLayout()
        left.setSpacing(10)
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("컴퓨터 번호, 이름, 명의자, 아이디, 닉네임으로 찾기")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._render_cards)
        self.filter = QComboBox()
        self.filter.addItems(PC_FILTERS)
        self.filter.currentIndexChanged.connect(self._render_cards)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.filter)
        if repo.me.is_admin:
            bar.addWidget(button("+ 컴퓨터 추가", "primary", lambda: self.edit_pc(None)))
        left.addLayout(bar)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left.addWidget(self.scroll, 1)
        body.addLayout(left, 1)

        # 오른쪽: 자리 패널
        self.panel = QFrame()
        self.panel.setObjectName("panel")
        self.panel.setFixedWidth(px(380))
        pl = QVBoxLayout(self.panel)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(0)
        head = QFrame()
        head.setObjectName("panelHead")
        hl = QVBoxLayout(head)
        hl.setContentsMargins(20, 16, 20, 14)
        hl.setSpacing(2)
        self.panel_title = label("자리를 선택하세요", "title")
        self.panel_sub = muted("")
        self.panel_sub.setWordWrap(True)
        hl.addWidget(self.panel_title)
        hl.addWidget(self.panel_sub)
        pl.addWidget(head)
        self.panel_body = QWidget()
        self.panel_lay = QVBoxLayout(self.panel_body)
        self.panel_lay.setContentsMargins(20, 16, 20, 18)
        self.panel_lay.setSpacing(10)
        pl.addWidget(self.panel_body, 1)
        body.addWidget(self.panel)
        root.addLayout(body, 1)

    # ---------------------------------------------------------------- 데이터
    def refresh(self) -> None:
        self.pcs = self.repo.list_pcs()
        self.accs = {a.id: a for a in self.repo.list_accounts()}
        if self.repo.is_cloud and self.repo.me.is_admin:
            self.worker_names = {w.id: w.display_name for w in self.repo.list_workers()}
        if self.selected:
            pc = self._pc(self.selected[0])
            if not pc or self.selected[1] > len(pc.slots):
                self.selected = None
        self.stat_pc.set(len(self.pcs))
        self.stat_empty.set(sum(1 for p in self.pcs for x in p.slots if x is None))
        self.stat_avail.set(sum(1 for a in self.accs.values() if a.assignable))
        self.stat_ban.set(sum(1 for a in self.accs.values() if a.both_banned))
        self._render_cards()
        self._render_panel()

    def restyle(self) -> None:
        """테마/배율이 바뀌었을 때 받아 둔 데이터로 다시 그린다 (서버 조회 없음)."""
        self.panel.setFixedWidth(px(380))
        self._render_cards()
        self._render_panel()

    def _pc(self, pc_id: int) -> PC | None:
        return next((p for p in self.pcs if p.id == pc_id), None)

    def _after_change(self) -> None:
        self.refresh()
        self.changed.emit()

    # ---------------------------------------------------------------- 목록
    def _render_cards(self) -> None:
        pos = self.scroll.verticalScrollBar().value()
        host = QWidget()
        host.setObjectName("scrollHost")
        lay = QVBoxLayout(host)
        lay.setContentsMargins(0, 0, 6, 0)
        lay.setSpacing(10)
        q = self.search.text().strip().lower()
        mode = self.filter.currentIndex()
        n = 0
        for pc in self.pcs:
            accs = [self.accs[a] for a in pc.slots if a and a in self.accs]
            if q:
                hay = f"{pc.no} {pc.name} {pc.ld_cloud} {pc.anydesk_id}".lower() + " ".join(a.search_text() for a in accs)
                if q not in hay:
                    continue
            if mode == 1 and None not in pc.slots:
                continue
            if mode == 2 and not any(a.ban_labels() for a in accs):
                continue
            lay.addWidget(PcRow(pc, self.accs, self.selected, self))
            n += 1
        if n == 0:
            empty = muted("조건에 맞는 컴퓨터가 없어요." if self.pcs else
                          "아직 컴퓨터가 없어요. 엑셀을 가져오거나 컴퓨터를 추가하세요.")
            empty.setObjectName("emptyText")
            empty.setAlignment(Qt.AlignCenter)
            lay.addWidget(empty)
        lay.addStretch(1)
        self.scroll.setWidget(host)
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
        L = self.panel_lay
        if not self.selected:
            self.panel_title.setText("자리를 선택하세요")
            self.panel_sub.setText("왼쪽 목록에서 자리를 누르세요.")
            for line in ("· 빈 자리를 누르면 넣을 수 있는 계정만 보여요.",
                         "· 계정이 든 자리를 누르면 정보와 빼기/옮기기가 나와요.",
                         "· 자리를 두 번 누르면 계정 수정 창이 열려요."):
                t = QLabel(line)
                t.setWordWrap(True)
                t.setObjectName("help")
                L.addWidget(t)
            L.addStretch(1)
            return
        pc = self._pc(self.selected[0])
        slot = self.selected[1]
        aid = pc.slots[slot - 1] if pc and slot <= len(pc.slots) else None
        self.panel_title.setText(f"{pc.no}번 컴퓨터 · {slot}자리")
        if aid and aid in self.accs:
            self.panel_sub.setText(pc.name)
            self._render_occupied(self.accs[aid])
        elif aid:
            self.panel_sub.setText("다른 담당자의 계정이 들어 있어요.")
            t = QLabel("이 자리의 계정 정보는 볼 수 없어요. 빼거나 바꾸려면 관리자에게 요청하세요.")
            t.setWordWrap(True)
            L.addWidget(t)
            L.addStretch(1)
        else:
            self.panel_sub.setText("빈 자리예요. 넣을 계정을 고르세요.")
            self._render_picker()

    def _field(self, grid: QGridLayout, row: int, name: str, value: str, copy: str | None = None) -> None:
        k = muted(name)
        k.setFixedWidth(px(72))
        v = QLabel(value or "-")
        v.setWordWrap(True)
        v.setTextInteractionFlags(Qt.TextSelectableByMouse)
        grid.addWidget(k, row, 0, Qt.AlignTop)
        grid.addWidget(v, row, 1)
        if copy is not None:
            grid.addWidget(button("복사", "ghost", lambda: copy_text(copy), "클립보드에 복사"), row, 2, Qt.AlignTop)

    def _render_occupied(self, a: Account) -> None:
        L = self.panel_lay
        top = QHBoxLayout()
        top.addWidget(label(a.owner or "(명의자 없음)", "title"))
        top.addWidget(badge(a.provider, "info"))
        top.addStretch(1)
        L.addLayout(top)
        bans = a.ban_labels()
        if bans:
            br = QHBoxLayout()
            for lab in bans:
                br.addWidget(badge(lab, "ban"))
            br.addStretch(1)
            L.addLayout(br)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        rows = [("아이디", a.login_id, a.login_id), ("비밀번호", "●" * 8 if a.password else "", a.password),
                ("연락처", a.contact, None), ("메월코드", a.tag, None),
                ("메랜", a.char_summary("메랜"), None), ("플래닛", a.char_summary("플래닛"), None)]
        if a.note:
            rows.append(("비고", a.note, None))
        for i, (k, v, c) in enumerate(rows):
            self._field(grid, i, k, v, c)
        grid.setColumnStretch(1, 1)
        L.addLayout(grid)
        L.addStretch(1)
        can_edit = self.repo.me.can("can_edit_account")
        L.addWidget(button("계정 수정" if can_edit else "계정 정보 보기", "primary" if can_edit else "",
                           lambda: self.open_slot(*self.selected)))
        acts = QHBoxLayout()
        acts.addWidget(button("다른 자리로 옮기기", "", lambda: self._move(a)), 1)
        acts.addWidget(button("자리에서 빼기", "danger", lambda: self._unassign(a)), 1)
        L.addLayout(acts)

    def _render_picker(self) -> None:
        L = self.panel_lay
        self.pick_search = QLineEdit()
        self.pick_search.setPlaceholderText("명의자, 아이디, 닉네임으로 찾기")
        self.pick_search.setClearButtonEnabled(True)
        L.addWidget(self.pick_search)
        fl = QHBoxLayout()
        self.pick_provider = QComboBox()
        self.pick_provider.addItems(["모든 유형"] + list(PROVIDERS))
        self.pick_ban = QComboBox()
        self.pick_ban.addItems(["정지 계정 포함", "정지 없는 계정만", "메랜 가능한 계정", "플래닛 가능한 계정"])
        fl.addWidget(self.pick_provider, 1)
        fl.addWidget(self.pick_ban, 1)
        L.addLayout(fl)
        self.pick_show_blocked = QCheckBox("명의자 규칙 때문에 못 넣는 계정도 보기")
        L.addWidget(self.pick_show_blocked)
        self.pick_count = muted()
        self.pick_count.setWordWrap(True)
        L.addWidget(self.pick_count)
        self.pick_list = QListWidget()
        self.pick_list.setObjectName("pickList")
        self.pick_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.pick_list.setWordWrap(True)
        self.pick_list.itemDoubleClicked.connect(lambda _: self._assign_selected())
        L.addWidget(self.pick_list, 1)
        L.addWidget(button("이 자리에 넣기", "primary", self._assign_selected))
        self.pick_search.textChanged.connect(self._fill_picker)
        self.pick_provider.currentTextChanged.connect(self._fill_picker)
        self.pick_ban.currentTextChanged.connect(self._fill_picker)
        self.pick_show_blocked.toggled.connect(self._fill_picker)
        self._fill_picker()

    def _fill_picker(self) -> None:
        self.pick_list.clear()
        q = self.pick_search.text().strip().lower()
        prov = self.pick_provider.currentText()
        ban_mode = self.pick_ban.currentIndex()
        show_blocked = self.pick_show_blocked.isChecked()
        all_accs = list(self.accs.values())
        target_pc = self.selected[0] if self.selected else None
        n = blocked = 0
        for a in sorted(all_accs, key=lambda x: (x.owner, x.login_id)):
            if not a.assignable:
                continue
            if prov != "모든 유형" and a.provider != prov:
                continue
            if q and q not in a.search_text():
                continue
            if ban_mode == 1 and a.ban_labels():
                continue
            if ban_mode == 2 and a.mr_ban.active():
                continue
            if ban_mode == 3 and a.pl_ban.active():
                continue
            why = owner_rule_violation(a, target_pc, all_accs) if target_pc else None
            if why:
                blocked += 1
                if not show_blocked:
                    continue
            lines = [f"{a.owner or a.contact or '(명의자 없음)'}   [{a.provider}] {a.login_id}", char_line(a)]
            if why:
                lines.append(f"넣을 수 없음: {why}")
            text = chr(10).join(lines)
            it = QListWidgetItem(text)
            it.setData(Qt.UserRole, a.id)
            if why:
                it.setFlags(Qt.NoItemFlags)  # 고를 수 없게
                it.setForeground(QColor(T("faint")))
                it.setToolTip(why)
            else:
                n += 1
            self.pick_list.addItem(it)
        msg = f"넣을 수 있는 계정 {n}개"
        if blocked:
            msg += f"  ·  명의자 규칙으로 제외 {blocked}개"
        self.pick_count.setText(msg)
        self.pick_count.setToolTip("어느 자리에도 없고, 탈퇴하지 않았고, 명의자 규칙(같은 명의 최대 2개 · 같은 컴퓨터에만)에 맞는 계정")
        if self.pick_list.count() == 0:
            it = QListWidgetItem("조건에 맞는 계정이 없어요")
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
        if QMessageBox.question(self, "자리에서 빼기",
                                f"{a.location.text()}에서 {a.login_id} 계정을 뺄까요?\n계정은 '사용가능'으로 돌아가요.") \
                == QMessageBox.Yes:
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

    def change_slots(self, pc: PC, delta: int) -> None:
        """자리 추가(+1) / 맨 아래 자리 삭제(-1). 최소 MIN_SLOTS개."""
        new = pc.slot_count + delta
        if new < MIN_SLOTS:
            return
        if delta < 0 and pc.slots and pc.slots[-1] is not None:
            QMessageBox.information(self, "자리 삭제",
                                    f"맨 아래 {pc.slot_count}자리에 계정이 들어 있어요. 먼저 빼거나 옮긴 뒤 삭제하세요.")
            return
        q = copy.deepcopy(pc)
        q.slot_count = new
        if run_safely(self, self.repo.save_pc, q):
            self._after_change()
        else:
            self.refresh()

    def edit_pc(self, pc: PC | None) -> None:
        next_no = max((p.no for p in self.pcs), default=0) + 1
        dlg = PcDialog(self.repo, pc, next_no, self)
        if dlg.exec():
            if dlg.deleted:
                self.selected = None
            self._after_change()
