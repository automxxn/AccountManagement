"""기존 엑셀(작업장시트, IDPW)을 불러온다.

규칙 (사용자와 합의):
- IDPW의 '플래닛정지' 열은 실제로 메랜정지, '아르테일' 열은 실제로 플래닛정지, '1열'은 버린다.
- IDPW 닉네임: H/I(닉네임/레벨직업(메랜))가 채워져 있으면 H/I=메랜, J/K=플래닛.
  H/I가 비어 있으면 J/K를 메랜으로 읽는다(예전 행의 쓰임새).
- 같은 계정이 작업장시트에도 있으면 작업장시트 값이 최신이므로 그 값으로 덮어쓴다(빈 칸은 덮어쓰지 않음).
- 닉네임/직업 칸에 여러 캐릭터가 ',' 또는 '/'로 들어 있으면 캐릭터 여러 개로 나눈다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .models import PC, Account, Ban, Character, norm_login

WORK_SHEET = "작업장시트"
IDPW_SHEET = "IDPW"

PHONE = re.compile(r"\(?(01\d)[-\s]?(\d{3,4})[-\s]?(\d{4})\)?")
DOT_DATE = re.compile(r"(\d{4})\s*[.\-/]\s*(\d{1,2})\s*[.\-/]\s*(\d{1,2})")


@dataclass
class ImportReport:
    accounts: int = 0
    pcs: int = 0
    assignments: int = 0
    characters: int = 0
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def text(self) -> str:
        lines = [
            f"계정 {self.accounts}개, 컴퓨터 {self.pcs}대, 배정 {self.assignments}건, 캐릭터 {self.characters}개를 가져왔어요.",
        ]
        if self.notes:
            lines.append("")
            lines.append("정리한 내용:")
            lines += [f"  · {n}" for n in self.notes]
        if self.warnings:
            lines.append("")
            lines.append("확인이 필요한 내용:")
            lines += [f"  · {w}" for w in self.warnings]
        return "\n".join(lines)


def s(v) -> str:
    """셀 값을 문자열로. 정수인 float는 소수점 없이."""
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m-%d")
    return str(v).strip()


def fmt_anydesk(v) -> str:
    txt = s(v)
    digits = re.sub(r"\D", "", txt)
    if digits and len(digits) >= 9 and re.fullmatch(r"[\d\s.E+]+", txt):
        return f"{int(digits):,}".replace(",", " ")
    return txt


def split_name(raw) -> tuple[str, str]:
    """'홍길동01012345678' → ('홍길동', '010-1234-5678')"""
    txt = s(raw)
    m = PHONE.search(txt)
    if m:
        name = (txt[: m.start()] + txt[m.end():]).strip(" ()")
        return name, f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    if txt.isdigit() and len(txt) >= 8:
        if len(txt) == 10 and txt.startswith("10"):  # 엑셀이 앞의 0을 지운 휴대폰 번호
            txt = "0" + txt
            return "", f"{txt[:3]}-{txt[3:7]}-{txt[7:]}"
        return "", txt
    return txt, ""


def parse_ban(v) -> tuple[Ban | None, str]:
    """정지 칸 값 → (Ban 또는 None, 비고로 옮길 텍스트)."""
    if v is None or s(v) == "":
        return None, ""
    if isinstance(v, (datetime, date)):
        return Ban(True, v.strftime("%Y-%m-%d")), ""
    if isinstance(v, (int, float)):
        d = date(1899, 12, 30) + timedelta(days=int(v))
        return Ban(True, d.isoformat()), ""
    txt = s(v)
    m = DOT_DATE.search(txt)
    if m:
        try:
            return Ban(True, date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()), ""
        except ValueError:
            pass
    if txt == "정지":
        return Ban(True, ""), ""
    if "전화" in txt:
        return Ban(True, ""), txt
    return None, txt


def split_chars(game: str, nick, job) -> list[Character]:
    nicks = [x.strip() for x in re.split(r"[,/]", s(nick))] if s(nick) else []
    jobs = [x.strip() for x in re.split(r"[,/]", s(job))] if s(job) else []
    n = max(len(nicks), len(jobs))
    out = []
    for i in range(n):
        nk = nicks[i] if i < len(nicks) else ""
        jb = jobs[i] if i < len(jobs) else ""
        if nk or jb:
            out.append(Character(game, nk, jb))
    return out


def _add_note(acc: Account, text: str) -> None:
    text = text.strip()
    if text and text not in acc.note:
        acc.note = (acc.note + "\n" + text).strip() if acc.note else text


def read_idpw(ws, report: ImportReport) -> dict[tuple[str, str], Account]:
    accs: dict[tuple[str, str], Account] = {}
    for r in range(3, ws.max_row + 1):
        row = [ws.cell(r, c).value for c in range(1, 16)]  # A..O
        login = s(row[4])
        if not login:
            if any(s(x) for x in row[2:]):
                report.warnings.append(f"IDPW {r}행: 아이디가 없어서 건너뜀 ({s(row[2])})")
            continue
        owner, contact = split_name(row[2])
        acc = Account(owner=owner, contact=contact, provider=s(row[3]) or "넥슨",
                      login_id=login, password=s(row[5]), tag=s(row[6]))
        h, i, j, k = row[7], row[8], row[9], row[10]
        if s(h) or s(i):
            acc.characters += split_chars("메랜", h, i) + split_chars("플래닛", j, k)
        else:
            acc.characters += split_chars("메랜", j, k)
        for game, col in (("메랜", row[11]), ("플래닛", row[12])):
            ban, extra = parse_ban(col)
            if ban:
                setattr(acc, "mr_ban" if game == "메랜" else "pl_ban", ban)
            if extra:
                _add_note(acc, f"[{game}정지] {extra}" if ban else f"[{game}정지 칸] {extra}")
        memo = s(row[14])
        if memo:
            _add_note(acc, memo)
            if "탈퇴" in memo or "탈외" in memo:
                acc.withdrawn = True
        key = (acc.provider, norm_login(login))
        if key in accs:
            prev = accs[key]
            for f in ("owner", "contact", "password", "tag"):
                if not getattr(prev, f) and getattr(acc, f):
                    setattr(prev, f, getattr(acc, f))
            if not prev.characters:
                prev.characters = acc.characters
            if acc.note:
                _add_note(prev, acc.note)
            report.notes.append(f"IDPW {r}행: [{acc.provider}] {login} 중복 행을 하나로 합침")
            continue
        accs[key] = acc
    return accs


def read_work(ws, accs: dict[tuple[str, str], Account], report: ImportReport):
    """작업장시트 → (PC 목록, [(pc_no, slot, account_key)])"""
    pcs: dict[int, PC] = {}
    links: list[tuple[int, int, tuple[str, str]]] = []
    by_login: dict[str, list[tuple[str, str]]] = {}
    for key in accs:
        by_login.setdefault(key[1], []).append(key)

    for r in range(6, ws.max_row + 1):
        row = [ws.cell(r, c).value for c in range(1, 19)]  # A..R
        no_txt = s(row[0])
        if not no_txt:
            continue
        try:
            no = int(float(no_txt))
        except ValueError:
            report.warnings.append(f"작업장 {r}행: 번호 '{no_txt}'를 읽을 수 없어서 건너뜀")
            continue
        pc = pcs.get(no)
        if pc is None:
            pc = PC(no=no, name=s(row[1]), remote_t=s(row[2]), anydesk_id=fmt_anydesk(row[3]),
                    anydesk_pw=s(row[4]), vpn=s(row[5]), ld_cloud=s(row[6]), slot_count=0)
            pcs[no] = pc
        elif s(row[6]) and s(row[6]) not in pc.ld_cloud:
            pc.ld_cloud = f"{pc.ld_cloud} / {s(row[6])}" if pc.ld_cloud else s(row[6])
        pc.slot_count += 1
        slot = pc.slot_count

        login = s(row[9])
        if not login:
            continue
        provider = s(row[8]) or "넥슨"
        key = (provider, norm_login(login))
        acc = accs.get(key)
        if acc is None:
            cands = by_login.get(norm_login(login), [])
            if len(cands) == 1:
                old = cands[0]
                acc = accs.pop(old)
                acc.provider = provider
                accs[key] = acc
                by_login[norm_login(login)] = [key]
                report.notes.append(f"{login}: 유형을 작업장시트 기준 '{provider}'(으)로 바꿈 (IDPW는 '{old[0]}')")
            elif len(cands) > 1:
                report.warnings.append(f"작업장 {r}행: {login}이(가) IDPW에 유형별로 여러 개라 [{provider}]와 맞는 것이 없음, 새로 만듦")
            if acc is None:
                acc = Account(provider=provider, login_id=login)
                accs[key] = acc
                by_login.setdefault(norm_login(login), []).append(key)
                report.notes.append(f"작업장 {r}행: {login}은(는) IDPW에 없어서 새 계정으로 추가")

        # 작업장시트 값이 최신 → 빈 칸이 아니면 덮어씀
        owner, contact = split_name(row[7])
        if owner:
            acc.owner = owner
        if contact:
            acc.contact = contact
        if s(row[10]):
            acc.password = s(row[10])
        if s(row[11]):
            acc.tag = s(row[11])
        mr_chars = split_chars("메랜", row[12], row[13])
        if mr_chars:
            acc.characters = [c for c in acc.characters if c.game != "메랜"] + mr_chars
        pl_nick = row[14]
        if s(pl_nick) == "정지":
            acc.pl_ban = Ban(True, acc.pl_ban.until if acc.pl_ban.banned else "")
            pl_nick = None
        pl_chars = split_chars("플래닛", pl_nick, row[15])
        if pl_chars:
            acc.characters = [c for c in acc.characters if c.game != "플래닛"] + pl_chars
        for game, col in (("메랜", row[16]), ("플래닛", row[17])):
            ban, extra = parse_ban(col)
            attr = "mr_ban" if game == "메랜" else "pl_ban"
            if ban:
                cur = getattr(acc, attr)
                # '정지'만 적힌 경우 IDPW의 해제일은 유지
                if not ban.until and cur.banned and cur.until:
                    ban = cur
                setattr(acc, attr, ban)
            if extra:
                _add_note(acc, f"[{game}정지] {extra}" if ban else f"[{game}정지 칸] {extra}")
        links.append((no, slot, key))
    return list(pcs.values()), links


def snapshot(repo) -> tuple[list[Account], list[PC], list[tuple[int, int, int]]]:
    """저장소의 현재 데이터를 bulk_import에 넣을 수 있는 모양으로 꺼낸다 (로컬 → 클라우드 올리기용)."""
    accounts = repo.list_accounts()
    index = {a.id: i for i, a in enumerate(accounts)}
    pcs = repo.list_pcs()
    links = [(p.no, slot, index[aid]) for p in pcs for slot, aid in enumerate(p.slots, start=1)
             if aid in index]
    return accounts, pcs, links


def import_workbook(path: str, repo) -> ImportReport:
    """repo: db.Repository 또는 cloud.CloudRepository (bulk_import 사용)"""
    from openpyxl import load_workbook

    report = ImportReport()
    wb = load_workbook(path, data_only=True, read_only=False)
    for name in (WORK_SHEET, IDPW_SHEET):
        if name not in wb.sheetnames:
            raise ValueError(f"엑셀에 '{name}' 시트가 없어요.")
    accs = read_idpw(wb[IDPW_SHEET], report)
    pcs, links = read_work(wb[WORK_SHEET], accs, report)

    keys = list(accs)
    acc_list = [accs[k] for k in keys]
    index = {k: i for i, k in enumerate(keys)}
    report.characters = sum(len([c for c in a.characters if c.text()]) for a in acc_list)
    link_rows = []
    for no, slot, key in links:
        acc = accs[key]
        if acc.withdrawn:
            report.warnings.append(f"{no}번 컴퓨터 {slot}자리: {acc.login_id}은(는) 탈퇴 계정이라 넣지 않음")
            continue
        link_rows.append((no, slot, index[key]))
    report.assignments = repo.bulk_import(acc_list, sorted(pcs, key=lambda p: p.no), link_rows)
    if report.assignments < len(link_rows):
        report.warnings.append(f"배정 {len(link_rows) - report.assignments}건은 같은 계정이 다른 자리에도 있어서 한 곳만 넣음")
    report.accounts = len(accs)
    report.pcs = len(pcs)
    mixed = sum(1 for a in accs.values() if "[메랜정지 칸]" in a.note or "[플래닛정지 칸]" in a.note)
    if mixed:
        report.notes.append(f"정지 칸에 날짜가 아닌 글자가 적힌 계정 {mixed}개: 정지로 보지 않고 비고로 옮김")
    return report
