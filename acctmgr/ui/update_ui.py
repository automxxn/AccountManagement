"""업데이트 안내 창과 진행 표시."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog

from .. import updater
from ..version import __version__


def offer(parent, info: updater.UpdateInfo) -> bool:
    """업데이트를 권하고, 설치를 시작했으면 True (호출한 쪽은 프로그램을 끝내야 함)."""
    notes = info.notes.strip()
    text = f"새 버전 {info.version}이(가) 나왔어요. (지금 버전 {__version__})\n\n"
    if notes:
        text += notes[:800] + "\n\n"
    text += "지금 업데이트할까요? 업데이트하면 프로그램이 자동으로 다시 시작돼요."
    box = QMessageBox(QMessageBox.Information, "업데이트", text, parent=parent)
    yes = box.addButton("지금 업데이트", QMessageBox.AcceptRole)
    box.addButton("나중에", QMessageBox.RejectRole)
    box.exec()
    if box.clickedButton() is not yes:
        return False

    dlg = QProgressDialog("업데이트 파일을 내려받는 중...", "취소", 0, 100, parent)
    dlg.setWindowTitle("업데이트")
    dlg.setWindowModality(Qt.ApplicationModal)
    dlg.setMinimumDuration(0)
    dlg.setValue(0)

    def progress(got: int, total: int) -> bool:
        if total:
            dlg.setValue(min(99, got * 100 // total))
            dlg.setLabelText(f"업데이트 파일을 내려받는 중... {got // (1 << 20)} / {total // (1 << 20)} MB")
        QApplication.processEvents()
        return not dlg.wasCanceled()

    try:
        updater.install(info, progress)
    except updater.UpdateError as e:
        dlg.close()
        QMessageBox.warning(parent, "업데이트 실패", f"{e}\n\n직접 받으려면: {info.page}")
        return False
    dlg.setValue(100)
    return True


def startup_check() -> bool:
    """시작할 때 확인. 설치를 시작했으면 True."""
    if not updater.is_frozen():
        return False
    updater.cleanup()
    info = updater.check()
    return bool(info) and offer(None, info)


def manual_check(parent) -> bool:
    """메뉴에서 확인. 설치를 시작했으면 True."""
    if not updater.is_frozen():
        QMessageBox.information(parent, "업데이트 확인",
                                f"지금 버전: {__version__}\n개발 모드(파이썬으로 실행)에서는 자동 업데이트를 하지 않아요.")
        return False
    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        info = updater.check()
    finally:
        QApplication.restoreOverrideCursor()
    if not info:
        QMessageBox.information(parent, "업데이트 확인", f"최신 버전을 쓰고 있어요. ({__version__})")
        return False
    return offer(parent, info)
