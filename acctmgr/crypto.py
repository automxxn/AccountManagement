"""비밀번호 암호화.

클라우드에는 계정 비번과 AnyDesk 비번을 '팀 열쇠'로 암호화한 값만 올린다. 팀마다 열쇠가 다르다.
- 총관리자의 팀 암호 → scrypt로 256비트 키 생성 (salt는 서버 app_settings에 저장).
  이 키로 각 팀 열쇠를 잠가 둔다 (1팀은 예전부터 이 키 자체가 팀 열쇠).
- 관리자/근무자는 개인 열쇠(X25519)로 잠긴 팀 열쇠를 받아서 푼다 (아래 seal/unseal)
- 각 값은 AES-GCM으로 암호화: "enc1:" + base64(nonce 12바이트 + 암호문)
- 이 PC에서 한 번 입력한 키는 Windows DPAPI로 잠가서 저장(같은 Windows 사용자만 풀 수 있음)
"""
from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes as wt
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

PREFIX = "enc1:"
CHECK_TEXT = "acctmgr-team-key-ok"


def new_salt() -> str:
    return base64.b64encode(os.urandom(16)).decode()


def derive_key(passphrase: str, salt_b64: str) -> bytes:
    kdf = Scrypt(salt=base64.b64decode(salt_b64), length=32, n=2 ** 15, r=8, p=1)
    return kdf.derive(passphrase.encode("utf-8"))


class Cipher:
    def __init__(self, key: bytes):
        self._aes = AESGCM(key)
        self.key = key

    def encrypt(self, text: str) -> str:
        if not text:
            return ""
        nonce = os.urandom(12)
        ct = self._aes.encrypt(nonce, text.encode("utf-8"), None)
        return PREFIX + base64.b64encode(nonce + ct).decode()

    def decrypt(self, value: str) -> str:
        if not value or not value.startswith(PREFIX):
            return value or ""
        raw = base64.b64decode(value[len(PREFIX):])
        try:
            return self._aes.decrypt(raw[:12], raw[12:], None).decode("utf-8")
        except InvalidTag:
            return "(복호화 실패: 팀 암호가 다름)"

    def check_token(self) -> str:
        return self.encrypt(CHECK_TEXT)

    def verify(self, token: str) -> bool:
        return self.decrypt(token) == CHECK_TEXT

    # 열쇠(바이트)를 이 열쇠로 잠그고 풀기 (팀 열쇠를 팀 암호나 로그인 비밀번호로 잠글 때)
    def wrap(self, data: bytes) -> str:
        return self.encrypt(base64.b64encode(data).decode())

    def unwrap(self, box: str) -> bytes | None:
        if not box or not box.startswith(PREFIX):
            return None
        raw = base64.b64decode(box[len(PREFIX):])
        try:
            return base64.b64decode(self._aes.decrypt(raw[:12], raw[12:], None))
        except (InvalidTag, ValueError):
            return None


def new_key() -> bytes:
    return os.urandom(32)


# ---------------------------------------------------------------- 개인 열쇠 (X25519)
# 각 사람은 열쇠 한 쌍을 가진다. 공개 열쇠는 서버에 올리고, 비공개 열쇠는 본인 PC(DPAPI)와
# 서버(로그인 비밀번호로 잠가서)에만 둔다. 관리자는 팀 열쇠를 그 사람의 공개 열쇠로 잠가서 넘겨준다.
SEAL_PREFIX = "seal1:"


def new_keypair() -> tuple[bytes, str]:
    """(비공개 열쇠 32바이트, 공개 열쇠 base64)"""
    priv = X25519PrivateKey.generate()
    raw = priv.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                             serialization.NoEncryption())
    return raw, public_of(raw)


def public_of(private_raw: bytes) -> str:
    pub = X25519PrivateKey.from_private_bytes(private_raw).public_key()
    return base64.b64encode(pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()


def _seal_key(shared: bytes, eph_pub: bytes, recipient_pub: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                info=b"acctmgr-seal" + eph_pub + recipient_pub).derive(shared)


def seal(data: bytes, recipient_public_b64: str) -> str:
    """recipient만 열 수 있게 잠근다 (일회용 열쇠 + X25519 + AES-GCM)."""
    recipient = base64.b64decode(recipient_public_b64)
    eph = X25519PrivateKey.generate()
    eph_pub = eph.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    key = _seal_key(eph.exchange(X25519PublicKey.from_public_bytes(recipient)), eph_pub, recipient)
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, data, None)
    return SEAL_PREFIX + base64.b64encode(eph_pub + nonce + ct).decode()


def unseal(sealed: str, private_raw: bytes) -> bytes | None:
    if not sealed or not sealed.startswith(SEAL_PREFIX):
        return None
    try:
        raw = base64.b64decode(sealed[len(SEAL_PREFIX):])
        eph_pub, nonce, ct = raw[:32], raw[32:44], raw[44:]
        priv = X25519PrivateKey.from_private_bytes(private_raw)
        mine = base64.b64decode(public_of(private_raw))
        key = _seal_key(priv.exchange(X25519PublicKey.from_public_bytes(eph_pub)), eph_pub, mine)
        return AESGCM(key).decrypt(nonce, ct, None)
    except (InvalidTag, ValueError):
        return None


# ---------------------------------------------------------------- PC 실행기용 잠금 (P-256)
# 각 PC의 LD CLOUD 실행기(C#, .NET Framework)가 풀 수 있는 방식: Windows CNG의 P-256 ECDH.
# 공유 비밀 Z → k = SHA256(Z), 암호 열쇠 = HMAC(k, "enc"), 확인 열쇠 = HMAC(k, "mac")
# 결과: "pcseal1:" + base64(일회용 공개 X(32) + Y(32) + iv(16) + AES-256-CBC 암호문 + HMAC-SHA256(iv + 암호문)(32))
PC_SEAL_PREFIX = "pcseal1:"


def pc_seal(data: bytes, agent_public_b64: str) -> str:
    import hashlib
    import hmac as _hmac

    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.ciphers import Cipher as _C, algorithms, modes

    raw = base64.b64decode(agent_public_b64)
    if len(raw) != 64:
        raise ValueError("실행기 공개 열쇠 형식이 잘못됐어요.")
    peer = ec.EllipticCurvePublicNumbers(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"),
                                         ec.SECP256R1()).public_key()
    eph = ec.generate_private_key(ec.SECP256R1())
    z = eph.exchange(ec.ECDH(), peer)
    k = hashlib.sha256(z).digest()
    enc_key = _hmac.new(k, b"enc", hashlib.sha256).digest()
    mac_key = _hmac.new(k, b"mac", hashlib.sha256).digest()
    iv = os.urandom(16)
    padder = padding.PKCS7(128).padder()
    body = padder.update(data) + padder.finalize()
    e = _C(algorithms.AES(enc_key), modes.CBC(iv)).encryptor()
    ct = e.update(body) + e.finalize()
    tag = _hmac.new(mac_key, iv + ct, hashlib.sha256).digest()
    nums = eph.public_key().public_numbers()
    epub = nums.x.to_bytes(32, "big") + nums.y.to_bytes(32, "big")
    return PC_SEAL_PREFIX + base64.b64encode(epub + iv + ct + tag).decode()


# ---------------------------------------------------------------- Windows DPAPI
class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> _Blob:
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _dpapi(data: bytes, protect: bool) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    inp, out = _blob(data), _Blob()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    ok = fn(ctypes.byref(inp), None, None, None, None, 0x01, ctypes.byref(out))  # CRYPTPROTECT_UI_FORBIDDEN
    if not ok:
        raise OSError("DPAPI 실패")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


def protect_key(key: bytes) -> str:
    return base64.b64encode(_dpapi(key, True)).decode()


def unprotect_key(stored: str) -> bytes | None:
    try:
        return _dpapi(base64.b64decode(stored), False)
    except Exception:
        return None
