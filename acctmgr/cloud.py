"""클라우드(Supabase) 저장소. db.Repository와 같은 메서드를 제공한다.

- 로그인: Supabase Auth (아이디만 입력하면 내부적으로 '아이디@LOGIN_DOMAIN' 이메일로 바꿔 쓴다)
- 읽기: REST(PostgREST) — 서버의 RLS가 볼 수 있는 행만 돌려준다
- 쓰기: RPC 함수 — 서버 함수가 권한을 검사한다 (supabase/schema.sql)
- 데이터는 팀별로 나뉜다. 지금 고른 팀(team_id)의 데이터만 읽고 쓴다.
- 비번/AnyDesk 비번은 팀 열쇠로 암호화해서 올리고, 받아올 때 푼다.
  총관리자는 팀 암호로 모든 팀 열쇠를 열고, 관리자/근무자는 개인 열쇠로 넘겨받은 팀 열쇠를 연다.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import httpx

from . import logsetup
from .crypto import Cipher, derive_key, new_key, new_keypair, new_salt, pc_seal, public_of, seal, unseal
from .db import ConflictError, RepoError, bans_from_json, bans_to_json
from .models import DEFAULT_GAMES, PC, Account, Agent, Ban, Character, Location, Profile, Team, launcher_type

LOGIN_DOMAIN = "acctmgr.app"


def to_email(login: str) -> str:
    login = login.strip()
    return login if "@" in login else f"{login}@{LOGIN_DOMAIN}"


class NeedPassword(RepoError):
    """이 PC에 개인 열쇠가 없어서 비밀번호로 다시 로그인해야 할 때."""


class CloudRepository:
    is_cloud = True

    def __init__(self, url: str, anon_key: str):
        self.url = url.rstrip("/")
        self.anon_key = anon_key.strip()
        self.http = httpx.Client(timeout=20)
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self.user_id: str | None = None
        self.me = Profile(display_name="", role="pending")
        self.on_session = None  # 로그인 유지 토큰이 바뀔 때마다 불러줌 (자동 로그인 저장용)
        self.teams: list[Team] = []          # 내가 볼 수 있는 팀
        self.team_id: int | None = None      # 지금 고른 팀
        self.ciphers: dict = {}              # 팀 id → 그 팀 열쇠
        self.master: Cipher | None = None    # 총관리자의 팀 암호 열쇠
        self.private_key: bytes | None = None  # 내 개인 열쇠(비공개)
        self._password: str | None = None    # 로그인 직후 개인 열쇠를 풀 때만 잠깐 기억

    @property
    def cipher(self) -> Cipher | None:
        return self.ciphers.get(self.team_id)

    @cipher.setter
    def cipher(self, c: Cipher | None) -> None:
        self.ciphers[self.team_id] = c

    @property
    def actor(self) -> str:
        return self.me.display_name

    @actor.setter
    def actor(self, _v) -> None:  # 클라우드에서는 로그인한 사람 이름을 쓴다
        pass

    # ------------------------------------------------------------------ HTTP
    def _headers(self) -> dict:
        h = {"apikey": self.anon_key, "Content-Type": "application/json"}
        if self.access_token:
            h["Authorization"] = f"Bearer {self.access_token}"
        return h

    def _request(self, method: str, path: str, *, retry: bool = True, **kw):
        try:
            r = self.http.request(method, self.url + path, headers=self._headers(), **kw)
        except httpx.HTTPError:
            raise RepoError("서버에 연결할 수 없어요. 인터넷 연결과 연결 설정(주소)을 확인하세요.")
        if r.status_code == 401 and retry and self.refresh_token and not path.startswith("/auth/"):
            self._refresh()
            return self._request(method, path, retry=False, **kw)
        if r.status_code >= 400:
            raise self._error(r)
        if not r.content:
            return None
        return r.json()

    @staticmethod
    def _error(r: httpx.Response) -> RepoError:
        try:
            j = r.json()
        except ValueError:
            j = {}
        msg = j.get("message") or j.get("msg") or j.get("error_description") or j.get("error") or r.text
        low = str(msg).lower()
        if "invalid login credentials" in low:
            return RepoError("아이디 또는 비밀번호가 틀렸어요.")
        if "already registered" in low or "already exists" in low:
            return RepoError("이미 가입된 아이디예요.")
        if "email not confirmed" in low:
            return RepoError("이메일 인증이 꺼져 있지 않아요. Supabase 설정에서 'Confirm email'을 꺼 주세요.")
        if "password should be" in low:
            return RepoError("비밀번호가 너무 짧아요. 6자 이상으로 정하세요.")
        if "먼저" in str(msg):
            return ConflictError(str(msg))
        return RepoError(str(msg))

    def _get(self, path: str, params: dict | None = None):
        return self._request("GET", "/rest/v1/" + path, params=params) or []

    def _rpc(self, fn: str, args: dict):
        return self._request("POST", "/rest/v1/rpc/" + fn, json=args)

    # ------------------------------------------------------------------ 로그인
    def _take_session(self, j: dict) -> None:
        if not j or not j.get("access_token"):
            raise RepoError("가입은 됐지만 바로 로그인되지 않았어요. Supabase 설정에서 'Confirm email'을 꺼 주세요.")
        self.access_token = j["access_token"]
        self.refresh_token = j.get("refresh_token")
        self.user_id = j.get("user", {}).get("id")
        if self.on_session and self.refresh_token:
            self.on_session(self.refresh_token)

    def sign_in(self, login: str, password: str) -> None:
        j = self._request("POST", "/auth/v1/token?grant_type=password",
                          json={"email": to_email(login), "password": password})
        self._take_session(j)
        self._password = password
        self.load_me()

    def sign_in_with_token(self, refresh_token: str) -> None:
        """저장해 둔 로그인 유지 토큰으로 로그인 (자동 로그인)."""
        self.refresh_token = refresh_token
        try:
            self._refresh()
        except RepoError:
            raise RepoError("자동 로그인 정보가 만료됐어요. 다시 로그인하세요.")
        self.load_me()

    def sign_up(self, login: str, password: str, display_name: str) -> None:
        j = self._request("POST", "/auth/v1/signup",
                          json={"email": to_email(login), "password": password,
                                "data": {"display_name": display_name.strip()}})
        self._take_session(j)
        self._password = password
        self.load_me()

    def _refresh(self) -> None:
        j = self._request("POST", "/auth/v1/token?grant_type=refresh_token",
                          json={"refresh_token": self.refresh_token}, retry=False)
        self._take_session(j)

    def load_me(self) -> Profile:
        rows = self._get("profiles", {"select": "*,team_members(team_id)", "id": f"eq.{self.user_id}"})
        if not rows:
            raise RepoError("프로필이 없어요. supabase/schema.sql을 먼저 실행했는지 확인하세요.")
        self.me = self._profile(rows[0])
        return self.me

    # ------------------------------------------------------------------ 총관리자의 팀 암호
    def team_key_info(self) -> tuple[str, str] | None:
        """(salt, 확인값). 총관리자만 읽을 수 있다."""
        rows = {r["key"]: r["value"] for r in self._get("app_settings", {"select": "key,value"})}
        if "key_salt" in rows and "key_check" in rows:
            return rows["key_salt"], rows["key_check"]
        return None

    def create_team_key(self, passphrase: str) -> bytes:
        salt = new_salt()
        key = derive_key(passphrase, salt)
        cipher = Cipher(key)
        self._rpc("set_team_key", {"p_salt": salt, "p_check": cipher.check_token()})
        self.master = cipher
        self._open_teams_as_super()
        return key

    def unlock(self, key: bytes) -> bool:
        info = self.team_key_info()
        if not info:
            return False
        cipher = Cipher(key)
        if cipher.verify(info[1]):
            self.master = cipher
            self._open_teams_as_super()
            return True
        return False

    def unlock_with_passphrase(self, passphrase: str) -> bytes | None:
        info = self.team_key_info()
        if not info:
            return None
        key = derive_key(passphrase, info[0])
        return key if self.unlock(key) else None

    def _open_teams_as_super(self) -> None:
        """팀 암호로 모든 팀 열쇠를 연다. 열쇠가 아직 없는 팀은 새로 만들어 저장한다."""
        m = self.master
        for _ in range(2):  # 새 열쇠를 저장했으면 한 번 더 읽어서 서버에 남은 값으로 맞춘다
            self.teams = self.list_teams()
            boxes = {r["team_id"]: r["box"] for r in self._get("team_master", {"select": "team_id,box"})}
            saved = False
            for t in self.teams:
                key = m.unwrap(boxes[t.id]) if t.id in boxes else None
                if key is None and t.key_check and m.verify(t.key_check):
                    key = m.key  # 1팀: 예전부터 팀 암호 열쇠 자체가 팀 열쇠
                    self._rpc("set_team_secret", {"p_id": t.id, "p_check": "", "p_box": m.wrap(key)})
                elif key is None and not t.key_check:
                    key = new_key()
                    self._rpc("set_team_secret", {"p_id": t.id, "p_check": Cipher(key).check_token(),
                                                  "p_box": m.wrap(key)})
                    saved = True
                    continue
                if key and Cipher(key).verify(t.key_check):
                    self.ciphers[t.id] = Cipher(key)
                else:
                    logsetup.log.warning("팀 열쇠를 열지 못함: %s", t.name)
            if not saved:
                break
        self._pick_team()

    # ------------------------------------------------------------------ 개인 열쇠 (관리자/근무자)
    def open_personal_key(self, stored_private: bytes | None) -> bytes:
        """내 개인 열쇠를 준비한다 (이 PC에 저장된 것 → 서버에 비밀번호로 잠긴 것 → 새로 만들기).
        이 PC에 저장할 비공개 열쇠를 돌려준다."""
        pw, self._password = self._password, None
        rows = self._get("user_keys", {"select": "public_key", "user_id": f"eq.{self.user_id}"})
        server_pub = rows[0]["public_key"] if rows else None
        sec = self._get("user_secrets", {"select": "salt,box", "user_id": f"eq.{self.user_id}"})
        sec = sec[0] if sec else {"salt": "", "box": ""}
        priv = stored_private if stored_private and server_pub == public_of(stored_private) else None
        if priv is None and server_pub and pw and sec["box"]:
            p = Cipher(derive_key(pw, sec["salt"])).unwrap(sec["box"])
            if p and public_of(p) == server_pub:
                priv = p
        if priv is None and server_pub and not pw:
            raise NeedPassword("이 PC에서는 처음이라 비밀번호로 한 번 로그인해야 해요.")
        if priv is None:
            priv, _pub = new_keypair()
            self._register_key(priv, pw)
        elif pw and not sec["box"]:
            self._register_key(priv, pw)  # 비밀번호를 알게 됐으니 다른 PC용 사본도 올려 둔다
        self.private_key = priv
        self._open_teams_as_member()
        return priv

    def _register_key(self, priv: bytes, pw: str | None) -> None:
        salt, box = "", ""
        if pw:
            salt = new_salt()
            box = Cipher(derive_key(pw, salt)).wrap(priv)
        self._rpc("register_key", {"p_public": public_of(priv), "p_salt": salt, "p_box": box})

    def _open_teams_as_member(self) -> None:
        self.teams = self.list_teams()
        mine = public_of(self.private_key)
        by_id = {t.id: t for t in self.teams}
        self.ciphers = {}
        for r in self._get("team_keys", {"select": "team_id,public_key,sealed", "user_id": f"eq.{self.user_id}"}):
            t = by_id.get(r["team_id"])
            if not t or r["public_key"] != mine:
                continue
            key = unseal(r["sealed"], self.private_key)
            if key and Cipher(key).verify(t.key_check):
                self.ciphers[t.id] = Cipher(key)
        self._pick_team()

    def reopen_keys(self) -> None:
        """팀이나 열쇠가 바뀌었을 수 있으니 다시 연다 (새로고침할 때)."""
        if self.master:
            self._open_teams_as_super()
        elif self.private_key:
            self._open_teams_as_member()

    def missing_key_teams(self) -> list[Team]:
        """속해 있지만 아직 열쇠를 못 받은 팀."""
        return [t for t in self.teams if t.id not in self.ciphers]

    def usable_teams(self) -> list[Team]:
        return [t for t in self.teams if t.id in self.ciphers]

    def _pick_team(self) -> None:
        usable = self.usable_teams()
        if not any(t.id == self.team_id for t in usable):
            self.team_id = usable[0].id if usable else None

    def grant_missing_keys(self) -> int:
        """내가 열쇠를 가진 팀의 사람들 중 아직 팀 열쇠를 못 받은 사람에게 넘겨준다. 넘겨준 수."""
        if not self.me.is_admin:
            return 0
        teams = [tid for tid in self.ciphers if tid is not None]
        if not teams:
            return 0
        ids = ",".join(str(t) for t in teams)
        members = self._get("team_members", {"select": "team_id,user_id", "team_id": f"in.({ids})"})
        pubs = {r["user_id"]: r["public_key"] for r in self._get("user_keys", {"select": "user_id,public_key"})}
        have = {(r["team_id"], r["user_id"]): r["public_key"]
                for r in self._get("team_keys", {"select": "team_id,user_id,public_key", "team_id": f"in.({ids})"})}
        n = 0
        for m in members:
            tid, uid = m["team_id"], m["user_id"]
            pub = pubs.get(uid)
            if uid == self.user_id or not pub or have.get((tid, uid)) == pub:
                continue
            try:
                self._rpc("grant_team_key", {"p_team": tid, "p_user": uid, "p_public": pub,
                                             "p_sealed": seal(self.ciphers[tid].key, pub)})
                n += 1
            except RepoError as e:
                logsetup.log.warning("팀 열쇠 넘겨주기 실패 (%s, %s): %s", tid, uid, e)
        return n

    # ------------------------------------------------------------------ 팀
    def list_teams(self) -> list[Team]:
        return [Team(r["id"], r["name"], list(r.get("games") or DEFAULT_GAMES), r.get("key_check", ""),
                     r.get("join_code") or "")
                for r in self._get("teams", {"select": "*", "order": "id"})]

    def new_join_code(self, team_id: int) -> str:
        code = str(self._rpc("new_join_code", {"p_team": team_id}) or "")
        self.teams = self.list_teams()
        return code

    def team(self) -> Team | None:
        return next((t for t in self.teams if t.id == self.team_id), None)

    def set_team(self, team_id: int) -> None:
        if team_id not in self.ciphers:
            raise RepoError("이 팀 열쇠가 아직 없어요.")
        self.team_id = team_id

    def create_team(self, name: str) -> int:
        if not self.master:
            raise RepoError("총관리자만 팀을 만들 수 있어요.")
        key = new_key()
        c = Cipher(key)
        tid = int(self._rpc("create_team", {"p_name": name, "p_check": c.check_token(),
                                            "p_box": self.master.wrap(key)}))
        self.ciphers[tid] = c
        self.teams = self.list_teams()
        return tid

    def rename_team(self, team_id: int, name: str) -> None:
        self._rpc("rename_team", {"p_id": team_id, "p_name": name})
        self.teams = self.list_teams()

    def delete_team(self, team_id: int) -> None:
        self._rpc("delete_team", {"p_id": team_id})
        self.ciphers.pop(team_id, None)
        self.teams = self.list_teams()
        self._pick_team()

    def team_counts(self) -> dict:
        """팀 id → (컴퓨터 수, 계정 수). 총관리자용."""
        out = {}
        for t in self.teams:
            pcs = self._get("pcs", {"select": "id", "team_id": f"eq.{t.id}"})
            accs = self._get("accounts", {"select": "id", "team_id": f"eq.{t.id}"})
            out[t.id] = (len(pcs), len(accs))
        return out

    def _team_filter(self) -> dict:
        return {"team_id": f"eq.{self.team_id if self.team_id is not None else -1}"}

    def _enc(self, text: str) -> str:
        if self.cipher is None:
            raise RepoError("이 팀 열쇠가 풀려 있지 않아요. 프로그램을 다시 시작하세요.")
        return self.cipher.encrypt(text)

    def _dec(self, text: str) -> str:
        return self.cipher.decrypt(text) if self.cipher else ""

    # ------------------------------------------------------------------ 변환
    @staticmethod
    def _profile(r: dict) -> Profile:
        return Profile(id=r["id"], login=r.get("login", ""), display_name=r.get("display_name", ""),
                       role=r.get("role", "pending"), can_add_account=r.get("can_add_account", False),
                       can_edit_account=r.get("can_edit_account", False),
                       can_delete_account=r.get("can_delete_account", False),
                       can_edit_pc=r.get("can_edit_pc", False),
                       can_view_workplace=r.get("can_view_workplace", True),
                       can_view_accounts=r.get("can_view_accounts", True),
                       can_assign_team=r.get("can_assign_team", False),
                       can_control_pc=r.get("can_control_pc", False),
                       can_add_pc=r.get("can_add_pc", False),
                       can_delete_pc=r.get("can_delete_pc", False),
                       teams=sorted(m["team_id"] for m in (r.get("team_members") or [])))

    def _account_payload(self, a: Account, encrypt: bool = True) -> dict:
        return {
            "id": a.id, "team_id": self.team_id, "version": a.version, "owner": a.owner, "contact": a.contact, "provider": a.provider,
            "login_id": a.login_id, "password": self._enc(a.password) if encrypt else a.password, "tag": a.tag,
            "mr_banned": a.mr_ban.banned, "mr_until": a.mr_ban.until,
            "pl_banned": a.pl_ban.banned, "pl_until": a.pl_ban.until,
            "withdrawn": a.withdrawn, "note": a.note, "worker_id": a.worker_id or "",
            "auth_blocked": a.auth_blocked, "other_bans": json.loads(bans_to_json(a.extra_bans)),
            "characters": [{"game": c.game, "nickname": c.nickname, "level_job": c.level_job}
                           for c in a.characters if c.text()],
        }

    def _pc_payload(self, p: PC) -> dict:
        return {"id": p.id, "team_id": self.team_id, "version": p.version, "no": p.no, "name": p.name, "remote_t": p.remote_t,
                "anydesk_id": p.anydesk_id, "anydesk_pw": self._enc(p.anydesk_pw), "vpn": p.vpn,
                "ld_cloud": p.ld_cloud, "slot_count": p.slot_count, "note": p.note, "worker_id": p.worker_id or ""}

    # ------------------------------------------------------------------ 읽기
    def list_pcs(self) -> list[PC]:
        pcs = {}
        for r in self._get("pcs", {"select": "*", "order": "no", **self._team_filter()}):
            pcs[r["id"]] = PC(id=r["id"], no=r["no"], name=r["name"], remote_t=r["remote_t"],
                              anydesk_id=r["anydesk_id"], anydesk_pw=self._dec(r["anydesk_pw"]), vpn=r["vpn"],
                              ld_cloud=r["ld_cloud"], slot_count=r["slot_count"], note=r["note"],
                              version=r["version"], worker_id=r["worker_id"], slots=[None] * r["slot_count"],
                              agent_settings=r.get("agent_settings") or {}, mac=r.get("mac") or "")
        for r in self._get("assignments", {"select": "pc_id,slot,account_id"}):
            p = pcs.get(r["pc_id"])
            if p and 1 <= r["slot"] <= len(p.slots):
                p.slots[r["slot"] - 1] = r["account_id"]
        return list(pcs.values())

    def list_accounts(self) -> list[Account]:
        rows = self._get("accounts", {"select": "*,characters(*)", "order": "owner,provider,login_key",
                                      **self._team_filter()})
        accs = {}
        for r in rows:
            chars = sorted(r.get("characters") or [], key=lambda c: (c["game"], c["sort"], c["id"]))
            accs[r["id"]] = Account(
                id=r["id"], owner=r["owner"], contact=r["contact"], provider=r["provider"], login_id=r["login_id"],
                password=self._dec(r["password"]), tag=r["tag"], mr_ban=Ban(r["mr_banned"], r["mr_until"]),
                pl_ban=Ban(r["pl_banned"], r["pl_until"]), withdrawn=r["withdrawn"], note=r["note"],
                version=r["version"], worker_id=r["worker_id"],
                delete_requested_at=(r.get("delete_requested_at") or "")[:16].replace("T", " "),
                auth_blocked=r.get("auth_blocked", False), extra_bans=bans_from_json(r.get("other_bans")),
                delete_requested_by=r.get("delete_requested_by"),
                characters=[Character(c["game"], c["nickname"], c["level_job"], c["id"]) for c in chars])
        pcs = {r["id"]: r for r in self._get("pcs", {"select": "id,no,name", **self._team_filter()})}
        for r in self._get("assignments", {"select": "pc_id,slot,account_id"}):
            a, p = accs.get(r["account_id"]), pcs.get(r["pc_id"])
            if a and p:
                a.location = Location(p["id"], p["no"], p["name"], r["slot"])
        return list(accs.values())

    def get_account(self, account_id: int) -> Account | None:
        return next((a for a in self.list_accounts() if a.id == account_id), None)

    def list_log(self, limit: int = 500) -> list[dict]:
        tid = self.team_id if self.team_id is not None else -1
        rows = self._get("audit_log", {"select": "at,actor,action,detail", "order": "id.desc", "limit": str(limit),
                                       "or": f"(team_id.eq.{tid},team_id.is.null)"})
        for r in rows:
            r["at"] = r["at"][:19].replace("T", " ")
        return rows

    def list_workers(self) -> list[Profile]:
        return [self._profile(r) for r in
                self._get("profiles", {"select": "*,team_members(team_id)", "order": "created_at"})
                if r.get("role") != "agent"]  # PC 실행기 계정은 사람 목록에서 뺀다

    def list_games(self) -> list[str]:
        if self.team_id is None:
            return list(DEFAULT_GAMES)
        rows = self._get("teams", {"select": "games", "id": f"eq.{self.team_id}"})
        games = list(rows[0].get("games") or []) if rows else []
        t = self.team()
        if t and games:
            t.games = games
        return games or list(DEFAULT_GAMES)

    def save_games(self, games: list[str]) -> None:
        self._rpc("set_games", {"p_team": self.team_id, "p": games})

    def last_change(self) -> int:
        if self.team_id is None:
            return 0
        return int(self._rpc("last_change", {"p_team": self.team_id}) or 0)

    def is_empty(self) -> bool:
        return not self._get("accounts", {"select": "id", "limit": "1", **self._team_filter()}) and \
            not self._get("pcs", {"select": "id", "limit": "1", **self._team_filter()})

    # ------------------------------------------------------------------ 쓰기
    def save_account(self, acc: Account, log: bool = True) -> int:
        if not acc.login_id.strip():
            raise RepoError("아이디를 입력하세요.")
        acc.id = int(self._rpc("save_account", {"p": self._account_payload(acc)}))
        acc.version += 1
        return acc.id

    def delete_account(self, account_id: int) -> None:
        """관리자는 바로 삭제, 근무자는 삭제 요청 (서버가 구분)."""
        self._rpc("delete_account", {"p_id": account_id})

    def approve_delete(self, account_id: int) -> None:
        self._rpc("approve_delete", {"p_id": account_id})

    def reject_delete(self, account_id: int) -> None:
        self._rpc("reject_delete", {"p_id": account_id})

    def save_pc(self, pc: PC, log: bool = True) -> int:
        pc.id = int(self._rpc("save_pc", {"p": self._pc_payload(pc)}))
        pc.version += 1
        return pc.id

    def delete_pc(self, pc_id: int) -> None:
        self._rpc("delete_pc", {"p_id": pc_id})

    def swap_pc_numbers(self, a_id: int, b_id: int) -> None:
        self._rpc("swap_pc_numbers", {"p_a": a_id, "p_b": b_id})

    def assign(self, pc_id: int, slot: int, account_id: int) -> None:
        self._rpc("assign_account", {"p_pc": pc_id, "p_slot": slot, "p_account": account_id})

    def unassign(self, pc_id: int, slot: int) -> None:
        self._rpc("unassign_slot", {"p_pc": pc_id, "p_slot": slot})

    def move(self, account_id: int, to_pc_id: int, to_slot: int) -> None:
        self._rpc("move_account", {"p_account": account_id, "p_pc": to_pc_id, "p_slot": to_slot})

    def save_profile(self, p: Profile) -> None:
        self._rpc("save_profile", {"p": {
            "id": p.id, "display_name": p.display_name, "role": p.role,
            "can_add_account": p.can_add_account, "can_edit_account": p.can_edit_account,
            "can_delete_account": p.can_delete_account, "can_edit_pc": p.can_edit_pc,
            "can_view_workplace": p.can_view_workplace, "can_view_accounts": p.can_view_accounts,
            "can_assign_team": p.can_assign_team, "can_control_pc": p.can_control_pc,
            "can_add_pc": p.can_add_pc, "can_delete_pc": p.can_delete_pc,
            "teams": list(p.teams)}})

    def bulk_import(self, accounts: list[Account], pcs: list[PC], links: list[tuple[int, int, int]]) -> int:
        """links: (pc_no, slot, accounts 리스트의 인덱스). 기존 데이터는 모두 지운다."""
        payload = {
            "accounts": [self._account_payload(a) for a in accounts],
            "pcs": [self._pc_payload(p) for p in pcs],
            "links": [{"pc_no": no, "slot": slot, "acc": idx} for no, slot, idx in links],
        }
        return int(self._rpc("import_data", {"p_team": self.team_id, "p": payload}) or 0)

    # ------------------------------------------------------------------ PC 실행기 (LD CLOUD 실행기)
    @staticmethod
    def _agent(r: dict) -> Agent:
        seen = r.get("last_seen")
        ago = None
        if seen:
            try:
                t = datetime.fromisoformat(seen.replace("Z", "+00:00"))
                ago = (datetime.now(timezone.utc) - t).total_seconds()
            except ValueError:
                pass
        return Agent(user_id=r["user_id"], pc_id=r.get("pc_id"), team_id=r.get("team_id"), machine=r.get("machine", ""),
                     version=r.get("version", ""), public_key=r.get("public_key", ""),
                     last_seen=(seen or "")[:19].replace("T", " "), seconds_ago=ago,
                     state=r.get("state") or {}, devices=list(r.get("devices") or []))

    def list_agents(self) -> list[Agent]:
        return [self._agent(r) for r in self._get("agents", {"select": "*", "order": "machine"})]

    def link_agent(self, agent_id: str, pc_id: int | None) -> None:
        self._rpc("link_agent", {"p_agent": agent_id, "p_pc": pc_id})

    def forget_agent(self, agent_id: str) -> None:
        self._rpc("forget_agent", {"p_agent": agent_id})

    def send_command(self, pc_id: int, kind: str, arg: str = "") -> int:
        """arg: 명령에 붙는 값 (예: AMP 실행 → 어느 게임의 AMP)."""
        return int(self._rpc("send_pc_command", {"p_pc": pc_id, "p_kind": kind, "p_arg": arg or ""}))

    def set_agent_team(self, agent_id: str, team_id: int | None) -> None:
        self._rpc("set_agent_team", {"p_agent": agent_id, "p_team": team_id})

    def list_commands(self, pc_ids: list[int], limit: int = 200) -> list[dict]:
        if not pc_ids:
            return []
        ids = ",".join(str(i) for i in pc_ids)
        rows = self._get("pc_commands", {"select": "*", "pc_id": f"in.({ids})", "order": "id.desc",
                                         "limit": str(limit)})
        for r in rows:
            t0, t1, t2 = (_parse_time(r.get(k)) for k in ("created_at", "started_at", "finished_at"))
            r["pickup_s"] = (t1 - t0).total_seconds() if t0 and t1 else None   # 보낸 뒤 PC가 받기까지
            r["run_s"] = (t2 - t1).total_seconds() if t1 and t2 else None      # PC에서 실행한 시간
            for k in ("created_at", "started_at", "finished_at"):
                r[k] = _local_time(r.get(k))
        return rows

    def request_agent_restart(self, agent_id: str) -> None:
        """연결 안 된 실행기 다시 켜기 (다음 확인 때 켜지면서 새 버전으로 업데이트)."""
        self._rpc("request_agent_restart", {"p_agent": agent_id})

    def set_pc_mac(self, pc_id: int, mac: str) -> None:
        """컴퓨터에 실행기 MAC 고정 ('' = 지움)."""
        self._rpc("set_pc_mac", {"p_pc": pc_id, "p_mac": mac or ""})

    def set_agent_settings(self, pc_id: int, settings: dict) -> None:
        self._rpc("set_agent_settings", {"p_pc": pc_id, "p": settings})

    def sync_pc_creds(self) -> int:
        """연결된 PC 실행기에 그 컴퓨터 1·2자리 계정(A·B)을 그 PC만 열 수 있게 잠가서 올린다. 올린/지운 수."""
        if not (self.me.is_admin or self.me.can("can_control_pc")) or not self.ciphers:
            return 0
        agents = [a for a in self.list_agents() if a.pc_id and a.public_key]
        if not agents:
            return 0
        pc_ids = ",".join(str(a.pc_id) for a in agents)
        pcs = {r["id"]: r["team_id"] for r in self._get("pcs", {"select": "id,team_id", "id": f"in.({pc_ids})"})}
        have = {(r["pc_id"], r["slot"]): r["fingerprint"]
                for r in self._get("pc_creds", {"select": "pc_id,slot,fingerprint", "pc_id": f"in.({pc_ids})"})}
        slots = {(r["pc_id"], r["slot"]): r["account_id"]
                 for r in self._get("assignments", {"select": "pc_id,slot,account_id", "pc_id": f"in.({pc_ids})"})
                 if r["slot"] in (1, 2)}
        acc_ids = ",".join(str(a) for a in set(slots.values())) or "0"
        accs = {r["id"]: r for r in self._get("accounts", {
            "select": "id,team_id,provider,login_id,password,version", "id": f"in.({acc_ids})"})}
        n = 0
        for ag in agents:
            team = pcs.get(ag.pc_id)
            cipher = self.ciphers.get(team)
            if cipher is None:
                continue
            for slot in (1, 2):
                acc = accs.get(slots.get((ag.pc_id, slot)))
                old = have.get((ag.pc_id, slot))
                try:
                    if acc is None:
                        if old is not None:
                            self._rpc("set_pc_creds", {"p_pc": ag.pc_id, "p_slot": slot, "p_sealed": "", "p_fp": ""})
                            n += 1
                        continue
                    fp = hashlib.sha256(f"{acc['id']}:{acc['version']}:{ag.public_key}".encode()).hexdigest()[:24]
                    if fp == old:
                        continue
                    body = json.dumps({"type": launcher_type(acc["provider"]), "id": acc["login_id"],
                                       "pw": cipher.decrypt(acc["password"])}, ensure_ascii=False).encode("utf-8")
                    self._rpc("set_pc_creds", {"p_pc": ag.pc_id, "p_slot": slot,
                                               "p_sealed": pc_seal(body, ag.public_key), "p_fp": fp})
                    n += 1
                except (RepoError, ValueError) as e:
                    logsetup.log.warning("PC 계정 올리기 실패 (%s, %s자리): %s", ag.pc_id, slot, e)
        return n


def _parse_time(v: str | None):
    if not v:
        return None
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None


def _local_time(v: str | None) -> str:
    """서버 시각(UTC) → 이 PC 시각 'MM-DD HH:MM:SS'."""
    if not v:
        return ""
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone().strftime("%m-%d %H:%M:%S")
    except ValueError:
        return v[:19]
