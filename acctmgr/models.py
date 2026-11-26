"""데이터 모델과 상태 계산 규칙."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

GAMES = ("메랜", "플래닛")
PROVIDERS = ("넥슨", "구글", "네이버")

STATUS_AVAILABLE = "사용가능"
STATUS_IN_USE = "사용중"
STATUS_BANNED = "정지"
STATUS_WITHDRAWN = "탈퇴"


def norm_login(login_id: str) -> str:
    """중복 판단용 아이디 키: 앞뒤 공백과 대소문자를 무시한다."""
    return (login_id or "").strip().lower()


@dataclass
class Ban:
    banned: bool = False
    until: str = ""  # 해제일 YYYY-MM-DD, 비어 있으면 기한 없음

    def active(self, today: str | None = None) -> bool:
        if not self.banned:
            return False
        if not self.until:
            return True
        return self.until >= (today or date.today().isoformat())

    def label(self, game: str) -> str:
        if not self.active():
            return ""
        return f"{game}정지" + (f"~{self.until}" if self.until else "")


@dataclass
class Character:
    game: str
    nickname: str = ""
    level_job: str = ""
    id: int | None = None

    def text(self) -> str:
        return f"{self.nickname} {self.level_job}".strip()


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
    tag: str = ""  # 메월닉
    mr_ban: Ban = field(default_factory=Ban)
    pl_ban: Ban = field(default_factory=Ban)
    withdrawn: bool = False
    note: str = ""
    characters: list[Character] = field(default_factory=list)
    version: int = 0
    worker_id: str | None = None  # 담당 근무자 (클라우드)
    location: Location | None = None  # 조회 시 채워짐

    def chars(self, game: str) -> list[Character]:
        return [c for c in self.characters if c.game == game]

    def char_summary(self, game: str) -> str:
        return ", ".join(c.text() for c in self.chars(game) if c.text())

    def main_char(self) -> str:
        for game in GAMES:
            s = self.char_summary(game)
            if s:
                return f"[{game}] {s}"
        return ""

    def ban_labels(self) -> list[str]:
        out = []
        for game, ban in (("메랜", self.mr_ban), ("플래닛", self.pl_ban)):
            lab = ban.label(game)
            if lab:
                out.append(lab)
        return out

    @property
    def status(self) -> str:
        if self.withdrawn:
            return STATUS_WITHDRAWN
        if self.location:
            return STATUS_IN_USE
        if self.mr_ban.active() and self.pl_ban.active():
            return STATUS_BANNED
        return STATUS_AVAILABLE

    @property
    def assignable(self) -> bool:
        return self.status == STATUS_AVAILABLE

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

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def can(self, perm: str) -> bool:
        return self.is_admin or (self.role == "worker" and bool(getattr(self, perm, False)))
