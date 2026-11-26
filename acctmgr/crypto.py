"""비밀번호 암호화.

클라우드에는 계정 비번과 AnyDesk 비번을 '팀 암호'로 암호화한 값만 올린다.
- 팀 암호 → scrypt로 256비트 키 생성 (salt는 서버 app_settings에 저장)
- 각 값은 AES-GCM으로 암호화: "enc1:" + base64(nonce 12바이트 + 암호문)
- 이 PC에서 한 번 입력한 키는 Windows DPAPI로 잠가서 저장(같은 Windows 사용자만 풀 수 있음)
"""
from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes as wt
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
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
