"""데이터 모델과 상태 계산 규칙."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime

# 게임 종류: 관리자가 추가할 수 있다. 같은 리스트 객체를 고쳐서(set_games) 모든 화면이 같이 바뀌게 한다.
DEFAULT_GAMES = ("메랜", "플래닛")
GAMES: list[str] = list(DEFAULT_GAMES)
PROVIDERS = ("넥슨", "구글", "네이버")

# 계정 상태 5가지
STATUS_AVAILABLE = "사용가능"
STATUS_IN_USE = "사용중"
STATUS_BANNED = "정지"        # 모든 게임이 정지
STATUS_AUTH = "인증불가"       # 아이디/비번은 있지만 인증을 못 해서 못 씀 (탈퇴처럼 취급, 풀리면 다시 사용)
STATUS_WITHDRAWN = "탈퇴"


def set_games(games: list[str]) -> None:
    """게임 목록을 바꾼다 (메랜/플래닛은 항상 맨 앞에 남김)."""
    clean = []
    for g in list(DEFAULT_GAMES) + [x.strip() for x in games]:
        if g and g not in clean:
            clean.append(g)
    GAMES[:] = clean


def norm_login(login_id: str) -> str:
    """중복 판단용 아이디 키: 앞뒤 공백과 대소문자를 무시한다."""
    return (login_id or "").strip().lower()


@dataclass
class Ban:
    banned: bool = False
    until: str = ""  # 해제 시각 'YYYY-MM-DD HH:MM' (예전 데이터는 'YYYY-MM-DD'), 비어 있으면 기한 없음

    def until_full(self) -> str:
        """비교용 'YYYY-MM-DD HH:MM'. 날짜만 있으면 그날 끝(23:59)까지 정지로 본다."""
        u = (self.until or "").strip()
        return u if len(u) > 10 else (u + " 23:59" if u else "")

    def active(self, now: str | None = None) -> bool:
        if not self.banned:
            return False
        if not self.until:
            return True
        return self.until_full() >= (now or datetime.now().strftime("%Y-%m-%d %H:%M"))

    def label(self, game: str) -> str:
        if not self.active():
            return ""
        return f"{game}정지" + (f"~{self.until}" if self.until else "")


_LEVEL_RE = re.compile(r"^\s*(\d+)\s*(.*?)\s*$")


def split_level_job(text: str) -> tuple[str, str]:
    """'104프리' → ('104', '프리'), '메렌육성용' → ('', '메렌육성용')"""
    m = _LEVEL_RE.match(text or "")
    return (m.group(1), m.group(2)) if m else ("", (text or "").strip())


def join_level_job(level: str, job: str) -> str:
    """('104', '프리') → '104 프리' (레벨과 직업 사이 띄어쓰기)"""
    return " ".join(x for x in ((level or "").strip(), (job or "").strip()) if x)


def norm_level_job(text: str) -> str:
    return join_level_job(*split_level_job(text))


@dataclass
class Character:
    game: str
    nickname: str = ""
    level_job: str = ""  # 저장 형식: '104 프리'
    id: int | None = None

    @property
    def level(self) -> str:
        return split_level_job(self.level_job)[0]

    @property
    def job(self) -> str:
        return split_level_job(self.level_job)[1]

    @property
    def lj(self) -> str:
        """화면 표시용 레벨/직업 ('104 프리')"""
        return norm_level_job(self.level_job)

    def text(self) -> str:
        return f"{self.nickname} {self.lj}".strip()


@dataclass
class Location:
    pc_id: int
    pc_no: int
    pc_name: str
    slot: int

    def text(self) -> str:
        return f"{self.pc_no}번 컴퓨터 {self.slot}자리"


@dataclass
class Account:
    id: int | None = None
    owner: str = ""
    contact: str = ""
    provider: str = "넥슨"
    login_id: str = ""
    password: str = ""
    tag: str = ""  # 메월코드
    mr_ban: Ban = field(default_factory=Ban)
    pl_ban: Ban = field(default_factory=Ban)
    extra_bans: dict = field(default_factory=dict)  # 추가한 게임의 정지 {게임: Ban}
    withdrawn: bool = False
    auth_blocked: bool = False  # 인증불가
    note: str = ""
    characters: list[Character] = field(default_factory=list)
    version: int = 0
    worker_id: str | None = None  # 담당 근무자 (클라우드)
    delete_requested_at: str = ""          # 근무자가 삭제 요청한 시각 (관리자 승인 대기)
    delete_requested_by: str | None = None
    location: Location | None = None  # 조회 시 채워짐

    def chars(self, game: str) -> list[Character]:
        """그 게임의 캐릭터 목록. 맨 앞이 대표 캐릭터."""
        return [c for c in self.characters if c.game == game and c.text()]

    def main(self, game: str) -> Character | None:
        cs = self.chars(game)
        return cs[0] if cs else None

    def set_chars(self, game: str, chars: list[Character]) -> None:
        """그 게임의 캐릭터를 통째로 바꾼다 (chars[0]이 대표). 저장 순서는 게임 목록 순서."""
        by_game = {g: [c for c in self.characters if c.game == g] for g in {c.game for c in self.characters}}
        by_game[game] = list(chars)
        order = list(GAMES) + [g for g in by_game if g not in GAMES]
        self.characters = [c for g in order for c in by_game.get(g, [])]

    def ban(self, game: str) -> Ban:
        if game == "메랜":
            return self.mr_ban
        if game == "플래닛":
            return self.pl_ban
        return self.extra_bans.get(game) or Ban()

    def set_ban(self, game: str, ban: Ban) -> None:
        if game == "메랜":
            self.mr_ban = ban
        elif game == "플래닛":
            self.pl_ban = ban
        elif ban.banned:
            self.extra_bans[game] = ban
        else:
            self.extra_bans.pop(game, None)

    def char_summary(self, game: str) -> str:
        cs = self.chars(game)
        if len(cs) <= 1:
            return cs[0].text() if cs else ""
        return f"{cs[0].text()} (대표) 외 {len(cs) - 1}개"

    def main_char(self) -> str:
        """작업장 카드에 보일 한 줄: 게임별 대표 캐릭터."""
        parts = []
        for game in GAMES:
            m = self.main(game)
            if m:
                more = len(self.chars(game)) - 1
                parts.append(f"[{game}] {m.text()}" + (f" 외 {more}" if more else ""))
        return "  ".join(parts)

    def ban_labels(self) -> list[str]:
        return [lab for g in GAMES if (lab := self.ban(g).label(g))]

    @property
    def all_banned(self) -> bool:
        """모든 게임이 정지 (게임이 추가되고 그 게임은 정지가 아니면 False)."""
        return bool(GAMES) and all(self.ban(g).active() for g in GAMES)

    both_banned = all_banned  # 예전 이름

    @property
    def status(self) -> str:
        """계정 상태 5가지: 탈퇴 / 인증불가 / 정지(모든 게임) / 사용중 / 사용가능."""
        if self.withdrawn:
            return STATUS_WITHDRAWN
        if self.auth_blocked:
            return STATUS_AUTH
        if self.all_banned:
            return STATUS_BANNED
        return STATUS_IN_USE if self.location else STATUS_AVAILABLE

    @property
    def delete_requested(self) -> bool:
        return bool(self.delete_requested_at)

    @property
    def assignable(self) -> bool:
        """빈 자리에 넣을 수 있는지: 자리에 없고, 탈퇴/인증불가/모든 게임 정지/삭제 요청이 아님."""
        return (not self.location and not self.withdrawn and not self.auth_blocked
                and not self.all_banned and not self.delete_requested)

    @property
    def owner_key(self) -> str:
        """명의자 규칙에 쓰는 기준: 명의자 이름, 없으면 연락처. 둘 다 없으면 규칙 적용 안 함."""
        return (self.owner or "").strip() or (self.contact or "").strip()

    def search_text(self) -> str:
        parts = [self.owner, self.contact, self.provider, self.login_id, self.tag, self.note]
        parts += [c.text() for c in self.characters]
        return " ".join(parts).lower()


@dataclass
class PC:
    id: int | None = None
    no: int = 0
    name: str = ""
    remote_t: str = ""
    anydesk_id: str = ""
    anydesk_pw: str = ""
    vpn: str = ""
    ld_cloud: str = ""
    slot_count: int = 2
    note: str = ""
    version: int = 0
    worker_id: str | None = None  # 담당 근무자 (클라우드)
    slots: list[int | None] = field(default_factory=list)  # 자리별 account id

    def title(self) -> str:
        return f"{self.no}. {self.name}".strip()


PERMS = (
    ("can_view_workplace", "작업장 보기"),
    ("can_view_accounts", "계정 보기"),
    ("can_add_account", "계정 추가"),
    ("can_edit_account", "계정 정보 수정"),
    ("can_delete_account", "계정 삭제"),
    ("can_edit_pc", "컴퓨터 정보 수정"),
)
ROLES = {"admin": "관리자", "worker": "근무자", "pending": "승인 대기"}


@dataclass
class Profile:
    id: str | None = None
    login: str = ""
    display_name: str = "관리자"
    role: str = "admin"
    can_add_account: bool = True
    can_edit_account: bool = True
    can_delete_account: bool = True
    can_edit_pc: bool = True
    can_view_workplace: bool = True
    can_view_accounts: bool = True

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def can(self, perm: str) -> bool:
        return self.is_admin or (self.role == "worker" and bool(getattr(self, perm, False)))


MAX_PER_OWNER = 2  # 같은 명의자 계정은 작업장 전체에서 최대 2개, 그리고 같은 컴퓨터에만


def owner_rule_violation(acc: Account, target_pc_id: int, accounts: list[Account]) -> str | None:
    """acc를 target_pc_id 컴퓨터에 넣으면 명의자 규칙을 어기는지. 어기면 이유, 괜찮으면 None.

    규칙: 같은 명의자 계정은 작업장 전체에 최대 2개까지, 그리고 그 2개는 같은 컴퓨터에 있어야 한다.
    """
    key = acc.owner_key
    if not key:
        return None
    others = [a for a in accounts if a.id != acc.id and a.location and a.owner_key == key]
    if len(others) >= MAX_PER_OWNER:
        where = ", ".join(sorted({f"{a.location.pc_no}번" for a in others}))
        return f"명의자 '{key}'의 계정이 이미 {len(others)}개 들어가 있어요({where} 컴퓨터). 같은 명의 계정은 최대 {MAX_PER_OWNER}개까지예요."
    for a in others:
        if a.location.pc_id != target_pc_id:
            return (f"명의자 '{key}'의 계정이 이미 {a.location.pc_no}번 컴퓨터에 있어요. "
                    f"같은 명의 계정은 같은 컴퓨터에만 넣을 수 있어요.")
    return None
