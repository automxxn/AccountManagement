"""배포용 exe에 들어가는 연결 정보 (Supabase 주소와 anon 키).

빌드할 때 GitHub Secrets(SUPABASE_URL, SUPABASE_ANON_KEY)로 _build_defaults.py가 만들어진다.
이 파일은 저장소에 올리지 않는다 (.gitignore). 들어 있으면 연결 설정 창 없이 바로 클라우드 로그인 창이 뜬다.
"""
from __future__ import annotations

try:
    from ._build_defaults import SUPABASE_ANON_KEY, SUPABASE_URL
except ImportError:
    SUPABASE_URL = SUPABASE_ANON_KEY = ""


def built_in() -> tuple[str, str] | None:
    """exe에 들어 있는 (주소, anon 키). 없으면 None (개발용 실행 등)."""
    if SUPABASE_URL and SUPABASE_ANON_KEY:
        return SUPABASE_URL, SUPABASE_ANON_KEY
    return None
