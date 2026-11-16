"""把耗时操作放到 QThreadPool，避免阻塞界面。"""
from __future__ import annotations

from typing import Callable, Optional, Set

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from app.utils.exceptions import report_exception

# PySide6 中 QThreadPool 不会持有 Python QRunnable 的强引用，
# 必须在任务结束前保留引用，否则对象会被 GC 回收导致任务不执行。
_ACTIVE_WORKERS: Set["Worker"] = set()


class WorkerSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class Worker(QRunnable):
    def __init__(self, fn: Callable[[], object]):
        super().__init__()
        self._fn = fn
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self._fn()
        except Exception as exc:  # noqa: BLE001 - 需要把错误送回 UI 线程
            self.signals.failed.emit(report_exception(exc, "后台任务失败"))
        else:
            self.signals.finished.emit(result)


def run_async(
    fn: Callable[[], object],
    on_success: Callable[[object], None],
    on_error: Optional[Callable[[str], None]] = None,
    pool: Optional[QThreadPool] = None,
) -> Worker:
    worker = Worker(fn)
    _ACTIVE_WORKERS.add(worker)

    def release(_result: object = None) -> None:
        _ACTIVE_WORKERS.discard(worker)

    worker.signals.finished.connect(on_success)
    if on_error is not None:
        worker.signals.failed.connect(on_error)
    worker.signals.finished.connect(release)
    worker.signals.failed.connect(release)
    (pool or QThreadPool.globalInstance()).start(worker)
    return worker
