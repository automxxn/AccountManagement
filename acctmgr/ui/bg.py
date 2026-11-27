"""서버 일을 화면 뒤(따로 도는 한 줄짜리 작업 줄)에서 처리한다.

화면(Qt)은 한 번에 한 가지만 해서, 서버를 기다리는 동안은 클릭·스크롤이 멈춘다 (요청 1번에 0.1~0.3초).
그래서 서버 요청은 여기로 보내고, 결과가 오면 화면 쪽에서 ok(결과) / fail(오류)을 부른다.

- 작업은 들어온 순서대로 하나씩 한다 (넣기 → 다시 읽기 순서가 뒤바뀌지 않게).
- 이 PC 저장소(로컬 모드)는 다른 줄에서 쓰면 안 되므로 그 자리에서 바로 한다.
"""
from __future__ import annotations

import queue
import threading
import time

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from .. import logsetup


class Runner(QObject):
    _done = Signal(object)

    def __init__(self):
        super().__init__()
        self._q: queue.Queue = queue.Queue()
        self.pending = 0
        self._done.connect(self._finish)   # 다른 줄에서 보내면 화면 줄에서 받는다 (Qt가 알아서 넘김)
        threading.Thread(target=self._loop, name="am-bg", daemon=True).start()

    def run(self, repo, fn, ok=None, fail=None) -> None:
        """fn()을 뒤에서 돌리고, 끝나면 화면 쪽에서 ok(결과) 또는 fail(오류)."""
        if not getattr(repo, "is_cloud", False):
            try:
                res = fn()
            except Exception as e:   # noqa: BLE001 — 화면 쪽 fail로 넘긴다
                self._call(fail, e, failed=True)
                return
            self._call(ok, res)
            return
        self.pending += 1
        self._q.put((fn, ok, fail))

    def _loop(self) -> None:
        while True:
            fn, ok, fail = self._q.get()
            try:
                res, good = fn(), True
            except Exception as e:   # noqa: BLE001
                res, good = e, False
            try:
                self._done.emit((ok, fail, good, res))
            except RuntimeError:   # 프로그램이 닫히는 중 (받을 화면이 이미 없음)
                return

    def _finish(self, item) -> None:
        ok, fail, good, res = item
        self.pending -= 1
        self._call(ok if good else fail, res, failed=not good)

    @staticmethod
    def _call(cb, arg, failed: bool = False) -> None:
        if cb is None:
            if failed:
                logsetup.log.warning("뒤에서 한 서버 작업 실패: %s", arg)
            return
        try:
            cb(arg)
        except RuntimeError as e:   # 그 사이에 창/화면이 닫힌 경우
            logsetup.log.info("결과를 받을 화면이 없어요: %s", e)

    def wait(self, timeout: float = 30.0) -> bool:
        """(테스트·종료용) 남은 작업이 다 끝날 때까지 기다린다."""
        end = time.monotonic() + timeout
        app = QApplication.instance()
        while self.pending and time.monotonic() < end:
            if app:
                app.processEvents()
            time.sleep(0.005)
        if app:
            app.processEvents()
        return self.pending == 0


_runner: Runner | None = None


def bg() -> Runner:
    global _runner
    if _runner is None:
        _runner = Runner()
    return _runner


def reload_async(page) -> None:
    """메뉴 하나를 뒤에서 다시 읽고(page.fetch), 다 읽으면 그린다(page.show_data)."""
    def fail(e):
        logsetup.log.warning("다시 읽기 실패: %s", e)
    bg().run(page.repo, page.fetch, page.show_data, fail)
