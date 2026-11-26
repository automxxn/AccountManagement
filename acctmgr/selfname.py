"""프로그램 이름 'AM'.

예전 이름(AccountManagement.exe)으로 켜지면 (예전 버전이 자동 업데이트로 새 버전을 받은 경우)
실행 중인 exe 이름을 AM.exe로 바꾸고, 그 exe를 가리키던 바로가기(바탕화면·시작 메뉴·작업표시줄 고정)를 고친다.
시작 메뉴에는 'AM' 바로가기를 만들어 둔다 → Windows 검색에 'AM'만 쳐도 나옴.
로그인·설정을 저장하는 폴더 이름(%APPDATA%\\AccountManagement)은 그대로 둔다 (다시 로그인할 필요 없게).
"""
from __future__ import annotations

import base64
import os
import subprocess
import sys
from pathlib import Path

NEW_NAME = "AM.exe"
LEGACY_NAME = "AccountManagement.exe"
_exe_override: Path | None = None


def current_exe() -> Path:
    """지금 실행 중인 exe의 실제 경로 (켜진 뒤 이름을 바꿨으면 바뀐 경로)."""
    return _exe_override or Path(sys.executable)


def _marker() -> Path:
    base = Path(os.environ.get("APPDATA") or str(Path.home()))
    return base / "AccountManagement" / "shortcut_done.txt"


def migrate() -> None:
    """exe로 실행할 때만. 실패해도 프로그램은 그대로 켜진다."""
    global _exe_override
    if not getattr(sys, "frozen", False) or sys.platform != "win32":
        return
    from .logsetup import log
    exe = Path(sys.executable)
    old = None
    if exe.name.lower() == LEGACY_NAME.lower():
        new = exe.with_name(NEW_NAME)
        if not new.exists():
            try:
                os.replace(exe, new)          # Windows는 실행 중인 exe의 이름 바꾸기를 허용
                _exe_override = new
                old = exe
                log.info("프로그램 이름 변경: %s → %s", exe.name, new.name)
            except OSError as e:
                log.warning("프로그램 이름을 AM.exe로 바꾸지 못함: %s", e)
    target = current_exe()
    m = _marker()
    try:
        done = m.read_text(encoding="utf-8").strip() == str(target)
    except OSError:
        done = False
    start_lnk = Path(os.environ.get("APPDATA") or "") / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "AM.lnk"
    if done and old is None and start_lnk.exists():
        return
    try:
        fix_shortcuts(str(old) if old else "", str(target), wait=False)
        m.parent.mkdir(parents=True, exist_ok=True)
        m.write_text(str(target), encoding="utf-8")
    except Exception as e:  # noqa: BLE001 - 바로가기는 못 고쳐도 프로그램은 켜져야 함
        log.warning("바로가기 고치기 실패: %s", e)


SCRIPT = r"""
$ErrorActionPreference = 'SilentlyContinue'
$old = '__OLD__'; $new = '__NEW__'
$sh = New-Object -ComObject WScript.Shell
$dirs = __DIRS__
if ($old -ne '') {
  foreach ($d in $dirs) {
    if (-not $d -or -not (Test-Path -LiteralPath $d)) { continue }
    Get-ChildItem -LiteralPath $d -Filter *.lnk -Recurse -Depth 3 | ForEach-Object {
      try {
        $l = $sh.CreateShortcut($_.FullName)
        if ($l.TargetPath -and ($l.TargetPath -ieq $old)) {
          $l.TargetPath = $new
          $l.WorkingDirectory = Split-Path -Parent $new
          $l.IconLocation = "$new,0"
          $l.Save()
          if ($_.BaseName -like 'AccountManagement*') {
            $dest = Join-Path $_.DirectoryName 'AM.lnk'
            if (-not (Test-Path -LiteralPath $dest)) { Rename-Item -LiteralPath $_.FullName -NewName 'AM.lnk' }
          }
        }
      } catch {}
    }
  }
}
# 시작 메뉴 'AM' 바로가기 (Windows 검색에 'AM'으로 나오게)
$p = Join-Path __PROGRAMS__ 'AM.lnk'
$l = $sh.CreateShortcut($p)
if ($l.TargetPath -ine $new) {
  $l.TargetPath = $new
  $l.WorkingDirectory = Split-Path -Parent $new
  $l.IconLocation = "$new,0"
  $l.Description = 'AM - 계정·작업장 관리'
  $l.Save()
}
"""


def _ps_quote(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def fix_shortcuts(old: str, new: str, dirs: list[str] | None = None, programs: str | None = None,
                  wait: bool = False) -> None:
    """old exe를 가리키는 바로가기를 new로 고치고, 시작 메뉴에 AM.lnk를 둔다 (PowerShell, 창 없이)."""
    if dirs is None:
        dirs_ps = ("@([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('CommonDesktopDirectory'), "
                   "[Environment]::GetFolderPath('Programs'), "
                   "(Join-Path $env:APPDATA 'Microsoft\\Internet Explorer\\Quick Launch\\User Pinned\\TaskBar'))")
    else:
        dirs_ps = "@(" + ", ".join(_ps_quote(d) for d in dirs) + ")"
    prog_ps = _ps_quote(programs) if programs else "([Environment]::GetFolderPath('Programs'))"
    script = (SCRIPT.replace("'__OLD__'", _ps_quote(old)).replace("'__NEW__'", _ps_quote(new))
              .replace("__DIRS__", dirs_ps).replace("__PROGRAMS__", prog_ps))
    enc = base64.b64encode(script.encode("utf-16-le")).decode()
    p = subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                          "-EncodedCommand", enc],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if wait:
        p.wait(120)
