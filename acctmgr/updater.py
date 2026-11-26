"""GitHub Releases 기반 자동 업데이트.

1. 최신 릴리스 확인: GET /repos/{GITHUB_REPO}/releases/latest
2. 더 높은 버전이면 AM.exe(예전 릴리스는 AccountManagement.exe)를 exe 옆에 '.new'로 내려받고 SHA-256을 확인
3. 실행 중인 exe를 '.old'로 이름 바꾸고(Windows는 실행 중인 exe의 이름 변경을 허용) 새 파일을 그 자리에 둔 뒤 다시 실행
4. 다음 실행 때 '.old' 파일을 지운다
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import time
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import httpx

from .selfname import LEGACY_NAME, NEW_NAME, current_exe
from .version import GITHUB_REPO, __version__

ASSET_NAME = NEW_NAME            # 릴리스에는 예전 버전이 받을 수 있게 AccountManagement.exe도 같이 올린다
UA = {"User-Agent": "AM-updater", "Accept": "application/vnd.github+json"}


class UpdateError(Exception):
    pass


@dataclass
class UpdateInfo:
    version: str
    url: str
    sha256: str
    notes: str
    size: int
    page: str


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def parse_version(v: str) -> tuple[int, ...]:
    nums = [int(x) for x in re.findall(r"\d+", v)[:3]]
    return tuple(nums + [0] * (3 - len(nums)))


def check(timeout: float = 6.0, current: str = __version__) -> UpdateInfo | None:
    """새 버전이 있으면 정보를, 없거나 확인할 수 없으면 None."""
    try:
        r = httpx.get(f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
                      headers=UA, timeout=timeout, follow_redirects=True)
    except httpx.HTTPError:
        return None
    if r.status_code != 200:
        return None
    j = r.json()
    tag = j.get("tag_name", "")
    if parse_version(tag) <= parse_version(current):
        return None
    assets = {a["name"]: a for a in j.get("assets", [])}
    name = ASSET_NAME if ASSET_NAME in assets else LEGACY_NAME
    exe = assets.get(name)
    if not exe:
        return None
    sha = (exe.get("digest") or "").removeprefix("sha256:")
    if not sha and f"{name}.sha256" in assets:
        try:
            s = httpx.get(assets[f"{name}.sha256"]["browser_download_url"], headers=UA,
                          timeout=timeout, follow_redirects=True)
            sha = s.text.strip().split()[0] if s.status_code == 200 else ""
        except httpx.HTTPError:
            sha = ""
    return UpdateInfo(version=tag.lstrip("v"), url=exe["browser_download_url"], sha256=sha.lower(),
                      notes=j.get("body") or "", size=exe.get("size", 0), page=j.get("html_url", ""))


def download(info: UpdateInfo, dest: Path, progress: Callable[[int, int], bool] | None = None) -> Path:
    """dest에 내려받고 해시를 확인한다. progress(받은 바이트, 전체)가 False를 돌려주면 취소."""
    tmp = dest.with_name(dest.name + ".part")
    h = hashlib.sha256()
    got = 0
    try:
        with httpx.stream("GET", info.url, headers={"User-Agent": UA["User-Agent"]},
                          timeout=60, follow_redirects=True) as r:
            if r.status_code != 200:
                raise UpdateError(f"내려받기 실패 (HTTP {r.status_code})")
            total = int(r.headers.get("content-length") or info.size or 0)
            with open(tmp, "wb") as f:
                for chunk in r.iter_bytes(1 << 16):
                    f.write(chunk)
                    h.update(chunk)
                    got += len(chunk)
                    if progress and progress(got, total) is False:
                        raise UpdateError("업데이트를 취소했어요.")
    except httpx.HTTPError:
        tmp.unlink(missing_ok=True)
        raise UpdateError("업데이트 파일을 내려받지 못했어요. 인터넷 연결을 확인하세요.")
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    if info.sha256 and h.hexdigest() != info.sha256:
        tmp.unlink(missing_ok=True)
        raise UpdateError("내려받은 파일이 손상됐어요(해시 불일치). 다시 시도하세요.")
    try:
        _replace(tmp, dest)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise UpdateError("내려받은 파일을 다른 프로그램(백신 등)이 잡고 있어요. 잠시 후 다시 시도하세요.")
    return dest


def _replace(src: Path, dst: Path, tries: int = 40, delay: float = 0.25) -> None:
    """파일 이름 바꾸기. 막 받은 exe는 백신(Windows Defender 등)이 몇 초 동안 검사하며 잡고 있을 수 있어
    잠깐씩 기다리며 다시 시도한다 (최대 약 10초)."""
    for i in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(delay)


def swap(exe: Path, new_file: Path) -> None:
    """실행 중인 exe를 새 파일로 바꾼다."""
    old = exe.with_name(exe.name + ".old")
    try:
        old.unlink(missing_ok=True)
        _replace(exe, old)
    except PermissionError:
        new_file.unlink(missing_ok=True)
        raise UpdateError(f"'{exe.parent}' 폴더에 쓸 권한이 없어요. 프로그램을 바탕화면이나 문서 폴더로 옮겨서 실행하세요.")
    try:
        _replace(new_file, exe)
    except OSError:
        _replace(old, exe)  # 되돌리기
        raise UpdateError("새 파일로 바꾸지 못했어요. 다시 시도하세요.")


def restart(exe: Path) -> None:
    env = dict(os.environ)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"  # 새 프로세스가 이전 실행의 임시 폴더를 쓰지 않게
    subprocess.Popen([str(exe)], env=env, close_fds=True,
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))


def install(info: UpdateInfo, progress=None) -> None:
    """내려받기 → 교체 → 재시작. 호출한 쪽은 곧바로 프로그램을 끝내야 한다."""
    if not is_frozen():
        raise UpdateError("개발 모드(파이썬으로 실행)에서는 자동 업데이트를 하지 않아요.")
    exe = current_exe()
    new_file = download(info, exe.with_name(exe.name + ".new"), progress)
    swap(exe, new_file)
    restart(exe)


def cleanup() -> None:
    """지난 업데이트에서 남은 파일 정리."""
    if not is_frozen():
        return
    exe = current_exe()
    for name in {exe.name, LEGACY_NAME}:     # 이름을 AM.exe로 바꾸기 전 업데이트에서 남은 파일도
        for suffix in (".old", ".new", ".new.part"):
            try:
                exe.with_name(name + suffix).unlink(missing_ok=True)
            except OSError:
                pass
