"""全局统一异常捕获：业务异常基类、友好文案与全局钩子。

约定：
- 可预期的业务异常继承 AppError，其 message 可直接展示给用户；
- 未预料的异常由全局钩子记录完整堆栈，界面只展示通用提示，避免暴露技术细节。
"""
from __future__ import annotations

import logging
import sys
import threading

logger = logging.getLogger(__name__)

GENERIC_MESSAGE = "操作未能完成，请稍后重试。详细信息已记录到 networth.log。"


class AppError(Exception):
    """可预期业务异常基类，message 面向用户。"""


class AppValidationError(AppError, ValueError):
    """输入校验失败。"""


class AppRuntimeError(AppError, RuntimeError):
    """运行期业务失败（数据库、文件、外部命令等）。"""


def friendly_message(exc: BaseException) -> str:
    """把异常转换为可直接展示的中文文案。"""
    if isinstance(exc, AppError):
        return str(exc).strip() or GENERIC_MESSAGE
    return GENERIC_MESSAGE


def report_exception(exc: BaseException, context: str = "") -> str:
    """记录异常日志并返回展示文案。"""
    logger.error("%s：%s", context or "操作失败", exc, exc_info=exc)
    return friendly_message(exc)


def _show_error_dialog(title: str, text: str) -> None:
    from PySide6.QtCore import QThread
    from PySide6.QtWidgets import QApplication, QMessageBox

    app = QApplication.instance()
    if app is None or QThread.currentThread() is not app.thread():
        return
    box = QMessageBox()
    box.setWindowTitle(title)
    box.setIcon(QMessageBox.Icon.Critical)
    box.setText(text)
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.button(QMessageBox.StandardButton.Ok).setText("知道了")
    box.exec()


def _excepthook(exc_type, exc, tb) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc, tb)
        return
    logger.critical("未捕获异常", exc_info=(exc_type, exc, tb))
    _show_error_dialog("程序出现异常", friendly_message(exc))


def _thread_excepthook(args) -> None:
    if args.exc_type is SystemExit:
        return
    logger.critical(
        "后台线程未捕获异常（%s）",
        getattr(args.thread, "name", "unknown"),
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )


def install_global_exception_handler() -> None:
    """安装 sys / threading 全局异常钩子，重复调用安全。"""
    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook
