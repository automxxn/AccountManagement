"""총관리자 전용: 고른 근무자/관리자 시점으로 화면 보기 (문제 찾기용).

- 그 사람의 역할, 팀, 권한으로 메뉴·버튼·보이는 데이터를 거른다.
- 데이터는 총관리자 로그인으로 읽어 오므로 서버 권한과 100% 같지는 않다 (거의 같게 걸러서 보여줌).
- 보기 전용: 이 창에서는 아무것도 바꾸지 않는다 (실수로 총관리자 권한으로 바꾸는 일이 없게).
"""
from __future__ import annotations

import copy

from ..db import RepoError
from ..models import Profile

# 데이터를 바꾸는 저장소 함수들 → 이 창에서는 막는다
WRITES = {
    "save_account", "delete_account", "approve_delete", "reject_delete", "save_pc", "delete_pc", "assign", "unassign",
    "move", "save_profile", "save_games", "bulk_import", "link_agent", "forget_agent", "send_command",
    "set_agent_settings", "set_agent_team", "swap_pc_numbers", "create_team", "rename_team", "delete_team",
    "new_join_code", "create_team_key", "set_pc_mac", "request_agent_restart",
}


class ViewAsRepo:
    is_cloud = True

    def __init__(self, real, who: Profile):
        self._r = copy.copy(real)          # 팀 선택은 이 창 따로 (원래 창에 영향 없게)
        self._r.ciphers = dict(real.ciphers)
        self.me = copy.copy(who)
        self.real_me = real.me
        mine = set(who.teams)
        self._r.teams = [t for t in real.teams if t.id in mine]
        usable = [t for t in self._r.teams if t.id in real.ciphers]
        self._r.team_id = usable[0].id if usable else None

    # 기본은 진짜 저장소로 넘긴다 (읽기)
    def __getattr__(self, name):
        if name in WRITES:
            def blocked(*_a, **_k):
                raise RepoError("근무자 시점 보기에서는 아무것도 바꿀 수 없어요 (보기만 해요).")
            return blocked
        return getattr(self._r, name)

    @property
    def teams(self):
        return self._r.teams

    @property
    def team_id(self):
        return self._r.team_id

    @property
    def actor(self) -> str:
        return self.me.display_name

    def usable_teams(self):
        return [t for t in self._r.teams if t.id in self._r.ciphers]

    def team(self):
        return next((t for t in self._r.teams if t.id == self._r.team_id), None)

    def set_team(self, team_id: int) -> None:
        if team_id not in {t.id for t in self._r.teams}:
            raise RepoError("이 사람은 그 팀에 속해 있지 않아요.")
        self._r.set_team(team_id)

    # 열쇠/계정 넘겨주기 같은 관리 작업은 하지 않는다
    def reopen_keys(self) -> None:
        pass

    def grant_missing_keys(self) -> int:
        return 0

    def sync_pc_creds(self) -> int:
        return 0

    # 서버 권한 규칙과 비슷하게 거르기
    def list_accounts(self):
        accs = self._r.list_accounts()
        if self.me.role != "admin":
            accs = [a for a in accs if not a.delete_requested]   # 근무자는 삭제 요청 중인 계정을 못 봄
        return accs

    def get_account(self, account_id: int):
        return next((a for a in self.list_accounts() if a.id == account_id), None)

    def list_workers(self):
        people = self._r.list_workers()
        if self.me.role == "worker":
            return [p for p in people if p.id == self.me.id]
        mine = set(self.me.teams)
        return [p for p in people if p.id == self.me.id or set(p.teams) & mine
                or (p.role == "pending" and self.me.can_assign_team)]

    def list_log(self, limit: int = 500):
        rows = self._r.list_log(limit)
        if self.me.role == "worker":
            return [r for r in rows if r.get("actor") == self.me.display_name]
        return rows

    def list_agents(self):
        ags = self._r.list_agents()
        mine = set(self.me.teams)
        out = []
        for a in ags:
            if a.pc_id is None:
                if self.me.can("can_link_agent") and a.team_id in mine:
                    out.append(a)
            else:
                out.append(a)
        return out
