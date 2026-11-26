"""작업장 화면: 컴퓨터를 한 줄에 한 대씩 나열하고, 오른쪽 패널에서 자리 정보 확인/계정 넣기."""
from __future__ import annotations

import copy
import html

from PySide6.QtCore import QEvent, QItemSelection, QItemSelectionModel, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QKeySequence, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QSizePolicy, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from ..models import GAMES, PC, PROVIDERS, Account, owner_rule_violation
from .common import (
    GridDelegate, StatCard, T, badge, button, copy_text, label, muted, page_header, px, run_safely, style_table,
    vline,
)
from .dialogs import AccountDialog, CharacterDialog, PcDialog
from .sheet import ACC_CHAR, ACCOUNT_COLUMNS, GROUP_END_ROLE, SheetNav, cap_widths, fill_account_cells

PC_FILTERS = ["모든 컴퓨터", "빈 자리가 있는 컴퓨터", "정지 계정이 있는 컴퓨터"]
MIN_SLOTS = 2  # 컴퓨터마다 기본 자리 수 (이 밑으로는 줄일 수 없음)
PC_COLUMNS = ["번호", "컴퓨터", "LD클라우드", "AnyDesk", "AnyDesk 암호", "자리"]
PC_INFO_COLS = range(0, 5)  # 컴퓨터 정보 칸 (자리 줄끼리 세로로 합침)
EDIT_COLS = {1: "name", 2: "ld_cloud", 3: "anydesk_id", 4: "anydesk_pw"}  # 더블클릭으로 바로 수정, Ctrl+C/V
REAL_ROLE = Qt.UserRole + 2         # 가려진 칸(암호)의 실제 값
GAP_ROLE = Qt.UserRole + 3          # 컴퓨터 사이 간격 줄
GROUP_START_ROLE = Qt.UserRole + 4  # 컴퓨터 칸의 첫 줄 (위쪽 테두리)
OFF = len(PC_COLUMNS)  # 계정 열이 시작하는 위치


def all_headers() -> list[str]:
    """[컴퓨터 정보 | 자리 | 계정 열]. 계정 열은 게임 목록에 따라 바뀐다."""
    return PC_COLUMNS + ACCOUNT_COLUMNS


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


class SheetDelegate(GridDelegate):
    """작업장 시트 칸 그리기 + 바로 수정.
    - 간격 줄은 비워 두고, 블록(컴퓨터) 안쪽 칸만 바탕을 칠한다 (테두리는 BlockTable이 그림)
    - 수정할 때는 가려진 값(암호)이 아니라 실제 값을 보여주고, 끝나면 on_commit으로 저장한다
    """

    def __init__(self, parent, on_commit):
        super().__init__(parent)
        self.on_commit = on_commit

    def paint(self, painter, option, index) -> None:
        if index.data(GAP_ROLE):
            return  # 간격 줄: 아무것도 안 그림 → 페이지 바탕
        painter.fillRect(option.rect, QColor(T("table_bg")))  # 블록 안쪽 바탕
        super().paint(painter, option, index)

    def setEditorData(self, editor, index) -> None:
        real = index.data(REAL_ROLE)
        editor.setText(real if real is not None else (index.data() or ""))
        editor.selectAll()

    def setModelData(self, editor, model, index) -> None:
        self.on_commit(index.row(), index.column(), editor.text())


class BlockTable(QTableWidget):
    """컴퓨터마다 둥근 테두리 블록으로 묶어 그리는 표. 열은 맨 위 제목 줄과 그대로 맞는다."""

    RADIUS = 10

    def __init__(self, rows: int, cols: int):
        super().__init__(rows, cols)
        self.blocks: list[tuple[int, int]] = []  # (첫 줄, 마지막 줄)
        self.active_block: tuple[int, int] | None = None

    def paintEvent(self, e) -> None:
        super().paintEvent(e)
        cols = [c for c in range(self.columnCount()) if not self.isColumnHidden(c)]
        if not cols or not self.blocks:
            return
        left = self.columnViewportPosition(cols[0])
        right = self.columnViewportPosition(cols[-1]) + self.columnWidth(cols[-1])
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.Antialiasing)
        bg = QColor(T("bg"))
        rad = px(self.RADIUS)
        for a, b in self.blocks:
            top = self.rowViewportPosition(a)
            bottom = self.rowViewportPosition(b) + self.rowHeight(b)
            if bottom < 0 or top > self.viewport().height():
                continue
            rect = QRectF(left + 0.5, top + 0.5, right - left - 1, bottom - top - 1)
            outer = QPainterPath()
            outer.addRect(QRectF(rect).adjusted(-1, -1, 1, 1))
            rounded = QPainterPath()
            rounded.addRoundedRect(rect, rad, rad)
            p.fillPath(outer.subtracted(rounded), bg)  # 네 모서리를 둥글게 깎는다
            active = self.active_block == (a, b)
            p.setPen(QPen(QColor(T("accent") if active else T("group_line")), 2 if active else 1.2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(rect, rad, rad)
        p.end()


class WorkplaceTab(QWidget):
    changed = Signal()

    def __init__(self, repo):
        super().__init__()
        self.setObjectName("page")
        self.repo = repo
        self.pcs: list[PC] = []
        self.accs: dict[int, Account] = {}
        self.selected: tuple[int, int] | None = None
        self.selected_cell: tuple[int, int] | None = None  # (컴퓨터 id, 열): 컴퓨터 정보 칸 하나를 고른 경우
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
        self.stat_ban = StatCard("모든 게임 정지", "danger")
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
        self.pw_btn = button("비번 보기")
        self.pw_btn.setCheckable(True)
        self.pw_btn.toggled.connect(lambda on: (self.pw_btn.setText("비번 가리기" if on else "비번 보기"),
                                                self._render_cards()))
        bar.addWidget(self.pw_btn)
        if repo.me.is_admin:
            bar.addWidget(button("+ 컴퓨터 추가", "primary", lambda: self.edit_pc(None)))
        left.addLayout(bar)

        # 시트: [컴퓨터 정보 | 자리 | 계정 화면과 같은 열]
        self.show_worker = False  # 담당 근무자 개념은 없앰
        self.table = BlockTable(0, len(all_headers()))
        self.table.setHorizontalHeaderLabels(all_headers())
        # 선택은 직접 정한다: 컴퓨터 정보 칸은 그 칸 하나, 자리는 그 줄의 자리+계정 칸만
        self.table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        style_table(self.table)
        self.table.setItemDelegate(SheetDelegate(self.table, self._commit_pc_cell))
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.table.installEventFilter(self)  # Ctrl+C / Ctrl+V
        self.table.verticalHeader().setVisible(False)
        self.table.setWordWrap(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setStretchLastSection(True)
        hh.setDefaultAlignment(Qt.AlignCenter)
        self.table.cellClicked.connect(self._cell_clicked)
        self.table.cellDoubleClicked.connect(self._cell_double_clicked)
        self.table.setMouseTracking(True)
        self.table.cellEntered.connect(lambda r, c: None if self.nav.drag else self.table.viewport().setCursor(
            Qt.PointingHandCursor if (c - OFF) in ACC_CHAR else Qt.ArrowCursor))
        self._row_map: list[tuple[int, int] | None] = []  # 줄 → (컴퓨터 id, 자리), 간격 줄은 None
        self.nav = SheetNav(self.table, "work_table_zoom", self._render_cards,
                            extra_css=" QTableWidget { border: none; background: transparent; }")
        left.addWidget(self.table, 1)
        foot = QHBoxLayout()
        self.count_label = muted()
        foot.addWidget(self.count_label)
        foot.addSpacing(10)
        self.tzoom_btn = button("", "ghost", lambda: self.nav.set(1.0), "누르면 100%로")
        foot.addWidget(self.tzoom_btn)
        foot.addStretch(1)
        left.addLayout(foot)
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
        if self.selected_cell and not self._pc(self.selected_cell[0]):
            self.selected_cell = None
        self.stat_pc.set(len(self.pcs))
        self.stat_empty.set(sum(1 for p in self.pcs for x in p.slots if x is None))
        self.stat_avail.set(sum(1 for a in self.accs.values() if a.assignable))
        self.stat_ban.set(sum(1 for a in self.accs.values() if a.both_banned))
        self._render_cards()
        self._render_panel()

    def games_changed(self) -> None:
        """게임 목록이 바뀌었을 때: 열과 패널을 다시 그린다."""
        self._render_cards()
        self._render_panel()

    def restyle(self) -> None:
        """테마/배율이 바뀌었을 때 받아 둔 데이터로 다시 그린다 (서버 조회 없음)."""
        self.panel.setFixedWidth(px(380))
        self.nav.apply()  # 시트를 다시 그린다
        self._render_panel()

    def _pc(self, pc_id: int) -> PC | None:
        return next((p for p in self.pcs if p.id == pc_id), None)

    def _after_change(self) -> None:
        self.refresh()
        self.changed.emit()

    # ---------------------------------------------------------------- 목록
    def _visible_pcs(self) -> list[PC]:
        q = self.search.text().strip().lower()
        mode = self.filter.currentIndex()
        out = []
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
            out.append(pc)
        return out

    def _render_cards(self) -> None:
        """시트를 다시 그린다. 컴퓨터마다 자리 수만큼 줄을 만들고, 컴퓨터 정보 칸은 세로로 합친다."""
        t = self.table
        hpos, vpos = t.horizontalScrollBar().value(), t.verticalScrollBar().value()
        pcs = self._visible_pcs()
        t.clearSpans()
        t.clearContents()
        if t.columnCount() != len(all_headers()):
            t.setColumnCount(len(all_headers()))
        t.setHorizontalHeaderLabels(all_headers())
        t.setRowCount(sum(len(pc.slots) for pc in pcs) + len(pcs))
        bold = self.nav.bold_font()
        no_font = QFont(bold)
        no_font.setPixelSize(px(22 * self.nav.zoom))
        show_pw = self.pw_btn.isChecked()
        can_edit = self._can_edit_pc()
        ncols = t.columnCount()
        row_h = px(36 * self.nav.zoom)
        self._row_map = []
        r = 0
        blocks = []
        for k, pc in enumerate(pcs):
            if True:  # 블록 위 간격 줄
                gap = QTableWidgetItem("")
                gap.setFlags(Qt.NoItemFlags)
                gap.setData(GAP_ROLE, True)
                t.setItem(r, 0, gap)
                t.setSpan(r, 0, 1, ncols)
                t.setRowHeight(r, px(14))
                self._row_map.append(None)
                r += 1
            start = r
            n = len(pc.slots)
            for i, aid in enumerate(pc.slots, start=1):
                self._row_map.append((pc.id, i))
                t.setRowHeight(r, row_h)
                end = {GROUP_END_ROLE: False}
                if i == 1:
                    pw = pc.anydesk_pw if show_pw else ("●" * 6 if pc.anydesk_pw else "")
                    for c, v in enumerate([str(pc.no), pc.name, pc.ld_cloud, pc.anydesk_id, pw]):
                        it = QTableWidgetItem(v)
                        it.setTextAlignment(Qt.AlignCenter)
                        if c in EDIT_COLS:
                            it.setData(REAL_ROLE, getattr(pc, EDIT_COLS[c]))
                            it.setToolTip("더블클릭해서 바로 수정 · Ctrl+C 복사 · Ctrl+V 붙여넣기" if can_edit
                                          else "Ctrl+C 복사")
                        if c == 0:
                            it.setFont(no_font)  # 번호는 크게 (칸 너비는 그대로)
                            it.setForeground(QColor(T("accent_text")))
                        t.setItem(r, c, it)
                slot_it = QTableWidgetItem(str(i))
                slot_it.setTextAlignment(Qt.AlignCenter)
                t.setItem(r, OFF - 1, slot_it)
                acc = self.accs.get(aid) if aid else None
                if acc:
                    fill_account_cells(t, r, OFF, acc, show_pw, self.worker_names, bold, end)
                else:
                    it = QTableWidgetItem("다른 담당자의 계정 사용 중" if aid else "비어 있음  ·  눌러서 계정 넣기")
                    it.setForeground(QColor(T("muted") if aid else T("accent_text")))
                    t.setItem(r, OFF, it)
                    t.setSpan(r, OFF, 1, len(ACCOUNT_COLUMNS))
                # 바로 수정은 컴퓨터 정보 칸(EDIT_COLS)만
                for c in range(ncols):
                    it = t.item(r, c)
                    if it and not (can_edit and i == 1 and c in EDIT_COLS):
                        it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                r += 1
            blocks.append((start, r - 1))
            if n > 1:
                for c in PC_INFO_COLS:
                    t.setSpan(start, c, n, 1)
        t.blocks = blocks
        self._update_active_block()
        cap_widths(t, OFF, self.nav.zoom)
        # 합친 칸(컴퓨터 정보)은 자동 너비 계산에서 빠지므로 글자 길이로 직접 맞춘다
        fm = QFontMetrics(bold)
        pad = px(GridDelegate.PAD) * 2 + px(10)
        for c in range(OFF):
            texts = [all_headers()[c]] + [t.item(row, c).text() for row in range(t.rowCount())
                                        if t.item(row, c) and self._row_map[row]]
            t.setColumnWidth(c, max(fm.horizontalAdvance(x) for x in texts) + pad)
        self._apply_selection()
        t.horizontalScrollBar().setValue(hpos)
        t.verticalScrollBar().setValue(vpos)
        self.tzoom_btn.setText(self.nav.label())
        empty = sum(1 for pc in pcs for x in pc.slots if x is None)
        if pcs:
            self.count_label.setText(f"컴퓨터 {len(pcs)}대 표시 · 빈 자리 {empty}개")
        else:
            self.count_label.setText("조건에 맞는 컴퓨터가 없어요." if self.pcs else
                                     "아직 컴퓨터가 없어요. 엑셀을 가져오거나 컴퓨터를 추가하세요.")

    def _cell_clicked(self, r: int, c: int) -> None:
        if r >= len(self._row_map) or not self._row_map[r]:
            return
        pc_id, slot = self._row_map[r]
        pc = self._pc(pc_id)
        aid = pc.slots[slot - 1] if pc else None
        if c in PC_INFO_COLS:
            self.select_pc_cell(pc_id, c)
            return
        if (c - OFF) in ACC_CHAR and aid in self.accs:
            self.select_slot(pc_id, slot, c)
            if CharacterDialog(self.repo, self.accs[aid], ACC_CHAR[c - OFF], self).exec():
                self._after_change()
            return
        self.select_slot(pc_id, slot, c)

    def _row_of(self, pc_id: int, slot: int) -> int:
        return next((i for i, x in enumerate(self._row_map) if x == (pc_id, slot)), -1)

    def _apply_selection(self, cur_col: int | None = None) -> None:
        """선택 표시: 컴퓨터 정보 칸 하나, 또는 고른 자리 줄의 자리+계정 칸."""
        t = self.table
        hpos, vpos = t.horizontalScrollBar().value(), t.verticalScrollBar().value()
        sm = t.selectionModel()
        sm.clearSelection()
        model = t.model()
        if self.selected_cell:
            row = self._row_of(self.selected_cell[0], 1)
            if row >= 0:
                idx = model.index(row, self.selected_cell[1])
                sm.select(idx, QItemSelectionModel.Select)
                sm.setCurrentIndex(idx, QItemSelectionModel.NoUpdate)
        elif self.selected:
            row = self._row_of(*self.selected)
            if row >= 0:
                left, right = model.index(row, OFF - 1), model.index(row, OFF + len(ACCOUNT_COLUMNS) - 1)
                sm.select(QItemSelection(left, right), QItemSelectionModel.Select)
                col = cur_col if cur_col is not None and OFF - 1 <= cur_col < len(all_headers()) else OFF
                sm.setCurrentIndex(model.index(row, col), QItemSelectionModel.NoUpdate)
        # 선택만 바꾸고 보던 위치는 그대로 (자동 스크롤로 첫 열이 가려지지 않게)
        t.horizontalScrollBar().setValue(hpos)
        t.verticalScrollBar().setValue(vpos)
        t.viewport().update()

    def _update_active_block(self) -> None:
        pc_id = self.selected[0] if self.selected else (self.selected_cell[0] if self.selected_cell else None)
        t = self.table
        t.active_block = next(((a, b) for a, b in t.blocks
                               if pc_id is not None and self._row_map[a] and self._row_map[a][0] == pc_id), None)
        t.viewport().update()

    def select_pc_cell(self, pc_id: int, col: int) -> None:
        """컴퓨터 정보 칸 하나만 선택 (복사/바로 수정용). 오른쪽 패널에는 그 컴퓨터 도구를 보여준다."""
        self.selected = None
        self.selected_cell = (pc_id, col)
        self._update_active_block()
        self._apply_selection()
        self._render_panel()

    def _can_edit_pc(self) -> bool:
        return self.repo.me.is_admin or self.repo.me.can("can_edit_pc")

    def _cell_double_clicked(self, r: int, c: int) -> None:
        if r >= len(self._row_map) or not self._row_map[r]:
            return
        if c in EDIT_COLS and self._can_edit_pc():
            return  # 칸 안에서 바로 수정 (편집창이 열림)
        self.open_slot(*self._row_map[r])

    def _commit_pc_cell(self, row: int, col: int, text: str) -> None:
        """바로 수정/붙여넣기 결과를 저장한다. 표를 다시 그리므로 편집이 끝난 뒤에 실행한다."""
        if col not in EDIT_COLS or row >= len(self._row_map) or not self._row_map[row]:
            return
        pc_id, field = self._row_map[row][0], EDIT_COLS[col]
        QTimer.singleShot(0, lambda: self._save_pc_field(pc_id, field, text))

    def _save_pc_field(self, pc_id: int, field: str, value: str) -> None:
        pc = self._pc(pc_id)
        value = value.strip() if field != "anydesk_pw" else value
        if not pc or getattr(pc, field) == value:
            return
        q = copy.deepcopy(pc)
        setattr(q, field, value)
        if run_safely(self, self.repo.save_pc, q):
            self._after_change()
        else:
            self.refresh()

    def eventFilter(self, obj, ev) -> bool:
        if obj is self.table and ev.type() == QEvent.KeyPress:
            idx = self.table.currentIndex()
            if not idx.isValid():
                return False
            if ev.matches(QKeySequence.Copy):
                real = idx.data(REAL_ROLE)
                copy_text(real if real is not None else (idx.data() or ""))
                return True
            if ev.matches(QKeySequence.Paste):
                if idx.column() in EDIT_COLS and self._can_edit_pc():
                    text = (QApplication.clipboard().text() or "").splitlines()
                    self._commit_pc_cell(idx.row(), idx.column(), text[0] if text else "")
                return True
        return False

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
        if not self.selected and self.selected_cell and self._pc(self.selected_cell[0]):
            pc = self._pc(self.selected_cell[0])
            self.panel_title.setText(f"{pc.no}번 컴퓨터")
            self.panel_sub.setText(pc.name)
            self._pc_tools(pc)
            t = QLabel("· 칸을 더블클릭하면 바로 수정돼요.\n· Ctrl+C로 복사, Ctrl+V로 붙여넣기 할 수 있어요.\n"
                       "· 자리 줄을 누르면 그 자리의 계정 정보가 나와요.")
            t.setObjectName("help")
            t.setWordWrap(True)
            L.addWidget(t)
            L.addStretch(1)
            return
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
        self._pc_tools(pc)
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

    def _pc_tools(self, pc: PC) -> None:
        """패널 맨 위: 이 컴퓨터 수정, 자리 추가/삭제."""
        can_edit = self.repo.me.is_admin or self.repo.me.can("can_edit_pc")
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(button("컴퓨터 수정" if can_edit else "컴퓨터 정보", "", lambda: self.edit_pc(pc)))
        if can_edit:
            row.addWidget(button("+ 자리", "", lambda: self.change_slots(pc, +1), "이 컴퓨터에 계정 자리를 하나 더 만들어요"))
            if pc.slot_count > MIN_SLOTS:
                row.addWidget(button("- 자리", "", lambda: self.change_slots(pc, -1), "맨 아래 자리를 없애요 (비어 있을 때만)"))
        row.addStretch(1)
        self.panel_lay.addLayout(row)
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background:{T('line')};")
        self.panel_lay.addWidget(line)

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
                ] + [(g, a.char_summary(g), None) for g in GAMES]
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
        self.pick_ban.addItems(["정지 계정 포함", "정지 없는 계정만"] + [f"{g} 가능한 계정" for g in GAMES])
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
            if ban_mode >= 2 and a.ban(GAMES[ban_mode - 2]).active():
                continue
            why = owner_rule_violation(a, target_pc, all_accs) if target_pc else None
            if why:
                blocked += 1
                if not show_blocked:
                    continue
            # 보여줄 게임 줄: '메랜 가능' 필터면 메랜만, '플래닛 가능'이면 플래닛만, 그 외에는 둘 다
            games = [GAMES[ban_mode - 2]] if ban_mode >= 2 else list(GAMES)
            it = QListWidgetItem()
            it.setData(Qt.UserRole, a.id)
            card = self._pick_card(a, games, why)
            if why:
                it.setFlags(Qt.NoItemFlags)  # 고를 수 없게
                it.setToolTip(why)
            else:
                n += 1
            # 화면에 붙기 전이라 자동 크기가 작게 나오므로 줄 수로 높이를 직접 정한다
            f = QFont(self.font())
            f.setPixelSize(px(14))
            lines = 1 + len(games) + (2 if why else 0)
            it.setSizeHint(QSize(0, lines * QFontMetrics(f).lineSpacing() + (lines - 1) * px(2) + px(24)))
            self.pick_list.addItem(it)
            self.pick_list.setItemWidget(it, card)
        msg = f"넣을 수 있는 계정 {n}개"
        if blocked:
            msg += f"  ·  명의자 규칙으로 제외 {blocked}개"
        self.pick_count.setText(msg)
        self.pick_count.setToolTip("어느 자리에도 없고, 탈퇴하지 않았고, 명의자 규칙(같은 명의 최대 2개 · 같은 컴퓨터에만)에 맞는 계정")
        if self.pick_list.count() == 0:
            it = QListWidgetItem("조건에 맞는 계정이 없어요")
            it.setFlags(Qt.NoItemFlags)
            self.pick_list.addItem(it)

    def _pick_card(self, a: Account, games: list[str], why: str | None) -> QWidget:
        """오른쪽 목록 한 칸.
        1줄: 명의자 [유형] 아이디
        2~3줄: ● 메랜: 대표캐릭터 / ● 플래닛: 대표캐릭터  (초록 = 그 게임에 쓸 수 있음, 빨강 = 정지)
        """
        faint = T("faint")
        ink = faint if why else T("ink")
        sub = faint if why else T("muted")
        w = QWidget()
        w.setAttribute(Qt.WA_TransparentForMouseEvents)  # 클릭은 목록 칸이 받는다
        lay = QVBoxLayout(w)
        lay.setContentsMargins(px(2), px(2), px(2), px(2))
        lay.setSpacing(px(2))

        def rich(text: str) -> QLabel:
            lab = QLabel(text)
            lab.setTextFormat(Qt.RichText)
            lab.setStyleSheet("background: transparent;")
            return lab

        owner = html.escape(a.owner or a.contact or "(명의자 없음)")
        lay.addWidget(rich(f"<span style='color:{ink}; font-weight:bold'>{owner}</span>&nbsp;&nbsp;"
                           f"<span style='color:{sub}'>[{html.escape(a.provider)}]</span>&nbsp;"
                           f"<span style='color:{ink}'>{html.escape(a.login_id)}</span>"))
        for g in games:
            banned = a.ban(g).active()
            dot = faint if why else (T("danger") if banned else T("success"))
            m = a.main(g)
            more = len(a.chars(g)) - 1
            text = (m.text() + (f" 외 {more}" if more > 0 else "")) if m else "캐릭터 없음"
            lay.addWidget(rich(f"<span style='color:{dot}; font-size:{px(14)}px'>●</span>&nbsp;"
                               f"<span style='color:{sub}'>{g}:</span>&nbsp;"
                               f"<span style='color:{ink}'>{html.escape(text)}</span>"))
        if why:
            reason = rich(f"<span style='color:{T('danger')}'>넣을 수 없음: {html.escape(why)}</span>")
            reason.setWordWrap(True)
            lay.addWidget(reason)
        return w

    # ---------------------------------------------------------------- 동작
    def select_slot(self, pc_id: int, slot: int, col: int | None = None) -> None:
        self.selected = (pc_id, slot)
        self.selected_cell = None
        self._update_active_block()
        self._apply_selection(col)
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
