"""저장소 계층.

지금은 로컬 SQLite를 쓰고, 나중에 같은 메서드를 가진 클라우드(Supabase) 저장소로 바꿔 끼운다.
화면 코드는 이 클래스의 메서드만 사용해야 한다.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from .models import (
    DEFAULT_GAMES, PC, Account, Ban, Character, Location, Profile, norm_login, owner_rule_violation,
)


def bans_to_json(bans: dict) -> str:
    return json.dumps({g: {"banned": b.banned, "until": b.until} for g, b in bans.items() if b.banned},
                      ensure_ascii=False)


def bans_from_json(raw) -> dict:
    data = json.loads(raw) if isinstance(raw, str) else (raw or {})
    return {g: Ban(bool(v.get("banned")), v.get("until") or "") for g, v in data.items()}

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id          INTEGER PRIMARY KEY,
    owner       TEXT NOT NULL DEFAULT '',
    contact     TEXT NOT NULL DEFAULT '',
    provider    TEXT NOT NULL DEFAULT '',
    login_id    TEXT NOT NULL,
    login_key   TEXT NOT NULL,
    password    TEXT NOT NULL DEFAULT '',
    tag         TEXT NOT NULL DEFAULT '',
    mr_banned   INTEGER NOT NULL DEFAULT 0,
    mr_until    TEXT NOT NULL DEFAULT '',
    pl_banned   INTEGER NOT NULL DEFAULT 0,
    pl_until    TEXT NOT NULL DEFAULT '',
    withdrawn   INTEGER NOT NULL DEFAULT 0,
    note        TEXT NOT NULL DEFAULT '',
    version     INTEGER NOT NULL DEFAULT 1,
    updated_at  TEXT NOT NULL DEFAULT '',
    UNIQUE (provider, login_key)
);
CREATE TABLE IF NOT EXISTS characters (
    id          INTEGER PRIMARY KEY,
    account_id  INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    game        TEXT NOT NULL,
    nickname    TEXT NOT NULL DEFAULT '',
    level_job   TEXT NOT NULL DEFAULT '',
    sort        INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS pcs (
    id          INTEGER PRIMARY KEY,
    no          INTEGER NOT NULL UNIQUE,
    name        TEXT NOT NULL DEFAULT '',
    remote_t    TEXT NOT NULL DEFAULT '',
    anydesk_id  TEXT NOT NULL DEFAULT '',
    anydesk_pw  TEXT NOT NULL DEFAULT '',
    vpn         TEXT NOT NULL DEFAULT '',
    ld_cloud    TEXT NOT NULL DEFAULT '',
    slot_count  INTEGER NOT NULL DEFAULT 2 CHECK (slot_count >= 1),
    note        TEXT NOT NULL DEFAULT '',
    version     INTEGER NOT NULL DEFAULT 1,
    updated_at  TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS assignments (
    pc_id       INTEGER NOT NULL REFERENCES pcs(id) ON DELETE CASCADE,
    slot        INTEGER NOT NULL,
    account_id  INTEGER NOT NULL UNIQUE REFERENCES accounts(id) ON DELETE CASCADE,
    assigned_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (pc_id, slot)
);
CREATE TABLE IF NOT EXISTS audit_log (
    id      INTEGER PRIMARY KEY,
    at      TEXT NOT NULL,
    actor   TEXT NOT NULL,
    action  TEXT NOT NULL,
    detail  TEXT NOT NULL DEFAULT ''
);
"""


class RepoError(Exception):
    """사용자에게 그대로 보여줄 수 있는 오류."""


class ConflictError(RepoError):
    pass


APP_NAME = "AccountManagement"
OLD_APP_DIR = "계정관리"  # 이름을 바꾸기 전 폴더


def default_db_path() -> Path:
    base = Path(os.environ.get("APPDATA") or str(Path.home()))
    p = base / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    db = p / "accounts.db"
    old = base / OLD_APP_DIR / "accounts.db"
    if not db.exists() and old.exists():
        import shutil
        shutil.copy2(old, db)  # 예전 데이터를 새 위치로 복사 (원본은 백업으로 남김)
    return db


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Repository:
    """로컬(이 PC에만 저장) 저장소. 혼자 쓰므로 항상 관리자 권한."""

    is_cloud = False

    def __init__(self, path: str | Path | None = None, actor: str = "관리자"):
        self.path = Path(path) if path else default_db_path()
        self.actor = actor
        self.me = Profile()
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        # 나중에 생긴 칸 (예전 DB 파일에도 붙인다)
        for sql in ("ALTER TABLE accounts ADD COLUMN auth_blocked INTEGER NOT NULL DEFAULT 0",
                    "ALTER TABLE accounts ADD COLUMN other_bans TEXT NOT NULL DEFAULT '{}'",
                    "CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)"):
            try:
                self.conn.execute(sql)
            except sqlite3.OperationalError:
                pass
        self.conn.commit()

    # ------------------------------------------------------------------ 기록
    def _log(self, action: str, detail: str = "") -> None:
        self.conn.execute(
            "INSERT INTO audit_log(at, actor, action, detail) VALUES (?,?,?,?)",
            (_now(), self.actor, action, detail),
        )

    def list_log(self, limit: int = 500) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT at, actor, action, detail FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()

    # ------------------------------------------------------------------ 계정
    def _row_to_account(self, r: sqlite3.Row) -> Account:
        return Account(
            id=r["id"], owner=r["owner"], contact=r["contact"], provider=r["provider"],
            login_id=r["login_id"], password=r["password"], tag=r["tag"],
            mr_ban=Ban(bool(r["mr_banned"]), r["mr_until"]),
            pl_ban=Ban(bool(r["pl_banned"]), r["pl_until"]),
            withdrawn=bool(r["withdrawn"]), note=r["note"], version=r["version"],
            auth_blocked=bool(r["auth_blocked"]), extra_bans=bans_from_json(r["other_bans"]),
        )

    def list_accounts(self) -> list[Account]:
        accs = {r["id"]: self._row_to_account(r)
                for r in self.conn.execute("SELECT * FROM accounts ORDER BY owner, provider, login_key")}
        for c in self.conn.execute("SELECT * FROM characters ORDER BY account_id, game, sort, id"):
            a = accs.get(c["account_id"])
            if a:
                a.characters.append(Character(c["game"], c["nickname"], c["level_job"], c["id"]))
        for r in self.conn.execute(
            "SELECT a.account_id, a.slot, p.id AS pc_id, p.no, p.name FROM assignments a JOIN pcs p ON p.id = a.pc_id"
        ):
            a = accs.get(r["account_id"])
            if a:
                a.location = Location(r["pc_id"], r["no"], r["name"], r["slot"])
        return list(accs.values())

    def get_account(self, account_id: int) -> Account | None:
        for a in self.list_accounts():
            if a.id == account_id:
                return a
        return None

    def _check_dup(self, acc: Account) -> None:
        r = self.conn.execute(
            "SELECT id, owner FROM accounts WHERE provider=? AND login_key=? AND id IS NOT ?",
            (acc.provider, norm_login(acc.login_id), acc.id),
        ).fetchone()
        if r:
            raise RepoError(f"같은 아이디가 이미 있어요: [{acc.provider}] {acc.login_id.strip()} (명의자 {r['owner'] or '없음'})")

    def save_account(self, acc: Account, log: bool = True) -> int:
        if not acc.login_id.strip():
            raise RepoError("아이디를 입력하세요.")
        self._check_dup(acc)
        vals = (
            acc.owner.strip(), acc.contact.strip(), acc.provider.strip(), acc.login_id.strip(),
            norm_login(acc.login_id), acc.password, acc.tag.strip(),
            int(acc.mr_ban.banned), acc.mr_ban.until, int(acc.pl_ban.banned), acc.pl_ban.until,
            int(acc.withdrawn), acc.note, _now(), int(acc.auth_blocked), bans_to_json(acc.extra_bans),
        )
        with self.conn:
            if acc.id is None:
                cur = self.conn.execute(
                    """INSERT INTO accounts(owner, contact, provider, login_id, login_key, password, tag,
                       mr_banned, mr_until, pl_banned, pl_until, withdrawn, note, updated_at, auth_blocked, other_bans)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", vals)
                acc.id = cur.lastrowid
                acc.version = 1
                action = "계정 추가"
            else:
                cur = self.conn.execute(
                    """UPDATE accounts SET owner=?, contact=?, provider=?, login_id=?, login_key=?, password=?, tag=?,
                       mr_banned=?, mr_until=?, pl_banned=?, pl_until=?, withdrawn=?, note=?, updated_at=?,
                       auth_blocked=?, other_bans=?, version = version + 1
                       WHERE id=? AND version=?""", vals + (acc.id, acc.version))
                if cur.rowcount == 0:
                    raise ConflictError("다른 사람이 먼저 이 계정을 수정했어요. 최신 내용을 다시 불러온 뒤 수정하세요.")
                acc.version += 1
                action = "계정 수정"
            self.conn.execute("DELETE FROM characters WHERE account_id=?", (acc.id,))
            for i, c in enumerate(acc.characters):
                if c.nickname.strip() or c.level_job.strip():
                    self.conn.execute(
                        "INSERT INTO characters(account_id, game, nickname, level_job, sort) VALUES (?,?,?,?,?)",
                        (acc.id, c.game, c.nickname.strip(), c.level_job.strip(), i))
            if acc.withdrawn or acc.auth_blocked:
                # 탈퇴/인증불가 계정은 자리에서 자동으로 뺀다
                self.conn.execute("DELETE FROM assignments WHERE account_id=?", (acc.id,))
            if log:
                self._log(action, f"[{acc.provider}] {acc.login_id.strip()} ({acc.owner})")
        return acc.id

    def delete_account(self, account_id: int) -> None:
        a = self.get_account(account_id)
        if not a:
            return
        with self.conn:
            self.conn.execute("DELETE FROM accounts WHERE id=?", (account_id,))
            self._log("계정 삭제", f"[{a.provider}] {a.login_id} ({a.owner})")

    # ------------------------------------------------------------------ 컴퓨터
    def list_pcs(self) -> list[PC]:
        pcs = {}
        for r in self.conn.execute("SELECT * FROM pcs ORDER BY no"):
            pcs[r["id"]] = PC(
                id=r["id"], no=r["no"], name=r["name"], remote_t=r["remote_t"], anydesk_id=r["anydesk_id"],
                anydesk_pw=r["anydesk_pw"], vpn=r["vpn"], ld_cloud=r["ld_cloud"], slot_count=r["slot_count"],
                note=r["note"], version=r["version"], slots=[None] * r["slot_count"],
            )
        for r in self.conn.execute("SELECT pc_id, slot, account_id FROM assignments"):
            p = pcs.get(r["pc_id"])
            if p and 1 <= r["slot"] <= len(p.slots):
                p.slots[r["slot"] - 1] = r["account_id"]
        return list(pcs.values())

    def save_pc(self, pc: PC, log: bool = True) -> int:
        if pc.slot_count < 1:
            raise RepoError("자리 수는 1 이상이어야 해요.")
        dup = self.conn.execute("SELECT id FROM pcs WHERE no=? AND id IS NOT ?", (pc.no, pc.id)).fetchone()
        if dup:
            raise RepoError(f"{pc.no}번 컴퓨터가 이미 있어요.")
        if pc.id is not None:
            over = self.conn.execute(
                "SELECT slot FROM assignments WHERE pc_id=? AND slot>?", (pc.id, pc.slot_count)).fetchall()
            if over:
                raise RepoError("줄이려는 자리에 계정이 들어 있어요. 먼저 그 계정을 빼세요: "
                                + ", ".join(f"{r['slot']}자리" for r in over))
        vals = (pc.no, pc.name.strip(), pc.remote_t.strip(), pc.anydesk_id.strip(), pc.anydesk_pw,
                pc.vpn.strip(), pc.ld_cloud.strip(), pc.slot_count, pc.note, _now())
        with self.conn:
            if pc.id is None:
                cur = self.conn.execute(
                    """INSERT INTO pcs(no, name, remote_t, anydesk_id, anydesk_pw, vpn, ld_cloud, slot_count, note, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""", vals)
                pc.id = cur.lastrowid
                pc.version = 1
                action = "컴퓨터 추가"
            else:
                cur = self.conn.execute(
                    """UPDATE pcs SET no=?, name=?, remote_t=?, anydesk_id=?, anydesk_pw=?, vpn=?, ld_cloud=?,
                       slot_count=?, note=?, updated_at=?, version=version+1 WHERE id=? AND version=?""",
                    vals + (pc.id, pc.version))
                if cur.rowcount == 0:
                    raise ConflictError("다른 사람이 먼저 이 컴퓨터 정보를 수정했어요. 다시 불러온 뒤 수정하세요.")
                pc.version += 1
                action = "컴퓨터 수정"
            if log:
                self._log(action, pc.title())
        return pc.id

    def delete_pc(self, pc_id: int) -> None:
        r = self.conn.execute("SELECT no, name FROM pcs WHERE id=?", (pc_id,)).fetchone()
        if not r:
            return
        with self.conn:
            self.conn.execute("DELETE FROM pcs WHERE id=?", (pc_id,))
            self._log("컴퓨터 삭제", f"{r['no']}. {r['name']} (들어 있던 계정은 사용가능으로 돌아감)")

    # ------------------------------------------------------------------ 배정
    def _pc_label(self, pc_id: int, slot: int) -> str:
        r = self.conn.execute("SELECT no FROM pcs WHERE id=?", (pc_id,)).fetchone()
        return f"{r['no']}번 컴퓨터 {slot}자리" if r else f"컴퓨터#{pc_id} {slot}자리"

    def _acc_label(self, account_id: int) -> str:
        r = self.conn.execute("SELECT provider, login_id, owner FROM accounts WHERE id=?", (account_id,)).fetchone()
        return f"[{r['provider']}] {r['login_id']} ({r['owner']})" if r else f"계정#{account_id}"

    def assign(self, pc_id: int, slot: int, account_id: int) -> None:
        pc = self.conn.execute("SELECT slot_count FROM pcs WHERE id=?", (pc_id,)).fetchone()
        if not pc or not (1 <= slot <= pc["slot_count"]):
            raise RepoError("없는 자리예요. 새로고침 후 다시 시도하세요.")
        acc = self.conn.execute("SELECT withdrawn, auth_blocked FROM accounts WHERE id=?", (account_id,)).fetchone()
        if not acc:
            raise RepoError("없는 계정이에요. 새로고침 후 다시 시도하세요.")
        if acc["withdrawn"]:
            raise RepoError("탈퇴한 계정은 넣을 수 없어요.")
        if acc["auth_blocked"]:
            raise RepoError("인증불가 계정은 넣을 수 없어요.")
        where = self.conn.execute("SELECT pc_id, slot FROM assignments WHERE account_id=?", (account_id,)).fetchone()
        if where:
            raise RepoError(f"이 계정은 이미 {self._pc_label(where['pc_id'], where['slot'])}에 들어 있어요.")
        self._check_owner_rule(account_id, pc_id)
        try:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO assignments(pc_id, slot, account_id, assigned_at) VALUES (?,?,?,?)",
                    (pc_id, slot, account_id, _now()))
                self._log("배정", f"{self._pc_label(pc_id, slot)} ← {self._acc_label(account_id)}")
        except sqlite3.IntegrityError:
            raise RepoError("그 자리에 이미 다른 계정이 들어갔어요. 새로고침 후 다시 시도하세요.")

    def _check_owner_rule(self, account_id: int, pc_id: int) -> None:
        accs = self.list_accounts()
        acc = next((a for a in accs if a.id == account_id), None)
        why = owner_rule_violation(acc, pc_id, accs) if acc else None
        if why:
            raise RepoError(why)

    def unassign(self, pc_id: int, slot: int) -> None:
        r = self.conn.execute("SELECT account_id FROM assignments WHERE pc_id=? AND slot=?", (pc_id, slot)).fetchone()
        if not r:
            return
        with self.conn:
            self.conn.execute("DELETE FROM assignments WHERE pc_id=? AND slot=?", (pc_id, slot))
            self._log("빼기", f"{self._pc_label(pc_id, slot)} → {self._acc_label(r['account_id'])}")

    def move(self, account_id: int, to_pc_id: int, to_slot: int) -> None:
        src = self.conn.execute("SELECT pc_id, slot FROM assignments WHERE account_id=?", (account_id,)).fetchone()
        if not src:
            raise RepoError("이 계정은 어느 자리에도 없어요.")
        if self.conn.execute("SELECT 1 FROM assignments WHERE pc_id=? AND slot=?", (to_pc_id, to_slot)).fetchone():
            raise RepoError("옮길 자리에 이미 계정이 있어요.")
        self._check_owner_rule(account_id, to_pc_id)
        try:
            with self.conn:
                self.conn.execute("UPDATE assignments SET pc_id=?, slot=?, assigned_at=? WHERE account_id=?",
                                  (to_pc_id, to_slot, _now(), account_id))
                self._log("옮기기", f"{self._acc_label(account_id)}: {self._pc_label(src['pc_id'], src['slot'])}"
                                   f" → {self._pc_label(to_pc_id, to_slot)}")
        except sqlite3.IntegrityError:
            raise RepoError("옮길 자리에 이미 계정이 있어요. 새로고침 후 다시 시도하세요.")

    # ------------------------------------------------------------------ 기타
    def is_empty(self) -> bool:
        return not self.conn.execute("SELECT 1 FROM accounts UNION SELECT 1 FROM pcs LIMIT 1").fetchone()

    def approve_delete(self, account_id: int) -> None:
        self.delete_account(account_id)

    def reject_delete(self, account_id: int) -> None:
        pass

    def list_games(self) -> list[str]:
        r = self.conn.execute("SELECT value FROM app_settings WHERE key='games'").fetchone()
        return json.loads(r["value"]) if r else list(DEFAULT_GAMES)

    def save_games(self, games: list[str]) -> None:
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO app_settings(key, value) VALUES ('games', ?)",
                              (json.dumps(games, ensure_ascii=False),))
            self._log("게임 종류 변경", ", ".join(games))

    def last_change(self) -> int:
        return self.conn.execute("SELECT COALESCE(MAX(id), 0) FROM audit_log").fetchone()[0]

    def list_workers(self) -> list[Profile]:
        return []

    def save_profile(self, p: Profile) -> None:
        raise RepoError("근무자 관리는 클라우드 모드에서만 쓸 수 있어요.")

    def bulk_import(self, accounts: list[Account], pcs: list[PC], links: list[tuple[int, int, int]]) -> int:
        """기존 계정/컴퓨터/배정을 모두 지우고 새로 넣는다. links: (pc_no, slot, accounts 인덱스)"""
        with self.conn:
            for t in ("assignments", "characters", "accounts", "pcs"):
                self.conn.execute(f"DELETE FROM {t}")
        ids = [self.save_account(_fresh(a), log=False) for a in accounts]
        pc_ids = {p.no: self.save_pc(_fresh(p), log=False) for p in pcs}
        n = 0
        with self.conn:
            for no, slot, idx in links:
                if no in pc_ids:
                    cur = self.conn.execute(
                        "INSERT OR IGNORE INTO assignments(pc_id, slot, account_id, assigned_at) VALUES (?,?,?,?)",
                        (pc_ids[no], slot, ids[idx], _now()))
                    n += cur.rowcount
            self._log("데이터 가져오기", f"계정 {len(accounts)}개, 컴퓨터 {len(pcs)}대, 배정 {n}건")
        return n


def _fresh(obj):
    """다른 저장소에서 읽은 객체를 새로 넣을 수 있게 id/version을 비운 복사본."""
    import copy
    o = copy.deepcopy(obj)
    o.id = None
    o.version = 0
    if hasattr(o, "location"):
        o.location = None
    return o
