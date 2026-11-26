"""클라우드(Supabase) 저장소. db.Repository와 같은 메서드를 제공한다.

- 로그인: Supabase Auth (아이디만 입력하면 내부적으로 '아이디@LOGIN_DOMAIN' 이메일로 바꿔 쓴다)
- 읽기: REST(PostgREST) — 서버의 RLS가 볼 수 있는 행만 돌려준다
- 쓰기: RPC 함수 — 서버 함수가 권한을 검사한다 (supabase/schema.sql)
- 비번/AnyDesk 비번은 팀 암호로 암호화해서 올리고, 받아올 때 푼다
"""
from __future__ import annotations

import httpx

from .crypto import Cipher, derive_key, new_salt
from .db import ConflictError, RepoError
from .models import PC, Account, Ban, Character, Location, Profile

LOGIN_DOMAIN = "acctmgr.app"


def to_email(login: str) -> str:
    login = login.strip()
    return login if "@" in login else f"{login}@{LOGIN_DOMAIN}"


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
        self.cipher: Cipher | None = None
        self.on_session = None  # 로그인 유지 토큰이 바뀔 때마다 불러줌 (자동 로그인 저장용)

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
        self.load_me()

    def _refresh(self) -> None:
        j = self._request("POST", "/auth/v1/token?grant_type=refresh_token",
                          json={"refresh_token": self.refresh_token}, retry=False)
        self._take_session(j)

    def load_me(self) -> Profile:
        rows = self._get("profiles", {"select": "*", "id": f"eq.{self.user_id}"})
        if not rows:
            raise RepoError("프로필이 없어요. supabase/schema.sql을 먼저 실행했는지 확인하세요.")
        self.me = self._profile(rows[0])
        return self.me

    # ------------------------------------------------------------------ 팀 암호
    def team_key_info(self) -> tuple[str, str] | None:
        rows = {r["key"]: r["value"] for r in self._get("app_settings", {"select": "key,value"})}
        if "key_salt" in rows and "key_check" in rows:
            return rows["key_salt"], rows["key_check"]
        return None

    def create_team_key(self, passphrase: str) -> bytes:
        salt = new_salt()
        key = derive_key(passphrase, salt)
        cipher = Cipher(key)
        self._rpc("set_team_key", {"p_salt": salt, "p_check": cipher.check_token()})
        self.cipher = cipher
        return key

    def unlock(self, key: bytes) -> bool:
        info = self.team_key_info()
        if not info:
            return False
        cipher = Cipher(key)
        if cipher.verify(info[1]):
            self.cipher = cipher
            return True
        return False

    def unlock_with_passphrase(self, passphrase: str) -> bytes | None:
        info = self.team_key_info()
        if not info:
            return None
        key = derive_key(passphrase, info[0])
        return key if self.unlock(key) else None

    def _enc(self, text: str) -> str:
        if self.cipher is None:
            raise RepoError("팀 암호가 풀려 있지 않아요. 프로그램을 다시 시작하세요.")
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
                       can_edit_pc=r.get("can_edit_pc", False))

    def _account_payload(self, a: Account, encrypt: bool = True) -> dict:
        return {
            "id": a.id, "version": a.version, "owner": a.owner, "contact": a.contact, "provider": a.provider,
            "login_id": a.login_id, "password": self._enc(a.password) if encrypt else a.password, "tag": a.tag,
            "mr_banned": a.mr_ban.banned, "mr_until": a.mr_ban.until,
            "pl_banned": a.pl_ban.banned, "pl_until": a.pl_ban.until,
            "withdrawn": a.withdrawn, "note": a.note, "worker_id": a.worker_id or "",
            "characters": [{"game": c.game, "nickname": c.nickname, "level_job": c.level_job}
                           for c in a.characters if c.text()],
        }

    def _pc_payload(self, p: PC) -> dict:
        return {"id": p.id, "version": p.version, "no": p.no, "name": p.name, "remote_t": p.remote_t,
                "anydesk_id": p.anydesk_id, "anydesk_pw": self._enc(p.anydesk_pw), "vpn": p.vpn,
                "ld_cloud": p.ld_cloud, "slot_count": p.slot_count, "note": p.note, "worker_id": p.worker_id or ""}

    # ------------------------------------------------------------------ 읽기
    def list_pcs(self) -> list[PC]:
        pcs = {}
        for r in self._get("pcs", {"select": "*", "order": "no"}):
            pcs[r["id"]] = PC(id=r["id"], no=r["no"], name=r["name"], remote_t=r["remote_t"],
                              anydesk_id=r["anydesk_id"], anydesk_pw=self._dec(r["anydesk_pw"]), vpn=r["vpn"],
                              ld_cloud=r["ld_cloud"], slot_count=r["slot_count"], note=r["note"],
                              version=r["version"], worker_id=r["worker_id"], slots=[None] * r["slot_count"])
        for r in self._get("assignments", {"select": "pc_id,slot,account_id"}):
            p = pcs.get(r["pc_id"])
            if p and 1 <= r["slot"] <= len(p.slots):
                p.slots[r["slot"] - 1] = r["account_id"]
        return list(pcs.values())

    def list_accounts(self) -> list[Account]:
        rows = self._get("accounts", {"select": "*,characters(*)", "order": "owner,provider,login_key"})
        accs = {}
        for r in rows:
            chars = sorted(r.get("characters") or [], key=lambda c: (c["game"], c["sort"], c["id"]))
            accs[r["id"]] = Account(
                id=r["id"], owner=r["owner"], contact=r["contact"], provider=r["provider"], login_id=r["login_id"],
                password=self._dec(r["password"]), tag=r["tag"], mr_ban=Ban(r["mr_banned"], r["mr_until"]),
                pl_ban=Ban(r["pl_banned"], r["pl_until"]), withdrawn=r["withdrawn"], note=r["note"],
                version=r["version"], worker_id=r["worker_id"],
                characters=[Character(c["game"], c["nickname"], c["level_job"], c["id"]) for c in chars])
        pcs = {r["id"]: r for r in self._get("pcs", {"select": "id,no,name"})}
        for r in self._get("assignments", {"select": "pc_id,slot,account_id"}):
            a, p = accs.get(r["account_id"]), pcs.get(r["pc_id"])
            if a and p:
                a.location = Location(p["id"], p["no"], p["name"], r["slot"])
        return list(accs.values())

    def get_account(self, account_id: int) -> Account | None:
        return next((a for a in self.list_accounts() if a.id == account_id), None)

    def list_log(self, limit: int = 500) -> list[dict]:
        rows = self._get("audit_log", {"select": "at,actor,action,detail", "order": "id.desc", "limit": str(limit)})
        for r in rows:
            r["at"] = r["at"][:19].replace("T", " ")
        return rows

    def list_workers(self) -> list[Profile]:
        return [self._profile(r) for r in self._get("profiles", {"select": "*", "order": "created_at"})]

    def last_change(self) -> int:
        return int(self._rpc("last_change", {}) or 0)

    def is_empty(self) -> bool:
        return not self._get("accounts", {"select": "id", "limit": "1"}) and \
            not self._get("pcs", {"select": "id", "limit": "1"})

    # ------------------------------------------------------------------ 쓰기
    def save_account(self, acc: Account, log: bool = True) -> int:
        if not acc.login_id.strip():
            raise RepoError("아이디를 입력하세요.")
        acc.id = int(self._rpc("save_account", {"p": self._account_payload(acc)}))
        acc.version += 1
        return acc.id

    def delete_account(self, account_id: int) -> None:
        self._rpc("delete_account", {"p_id": account_id})

    def save_pc(self, pc: PC, log: bool = True) -> int:
        pc.id = int(self._rpc("save_pc", {"p": self._pc_payload(pc)}))
        pc.version += 1
        return pc.id

    def delete_pc(self, pc_id: int) -> None:
        self._rpc("delete_pc", {"p_id": pc_id})

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
            "can_delete_account": p.can_delete_account, "can_edit_pc": p.can_edit_pc}})

    def bulk_import(self, accounts: list[Account], pcs: list[PC], links: list[tuple[int, int, int]]) -> int:
        """links: (pc_no, slot, accounts 리스트의 인덱스). 기존 데이터는 모두 지운다."""
        payload = {
            "accounts": [self._account_payload(a) for a in accounts],
            "pcs": [self._pc_payload(p) for p in pcs],
            "links": [{"pc_no": no, "slot": slot, "acc": idx} for no, slot, idx in links],
        }
        return int(self._rpc("import_data", {"p": payload}) or 0)
