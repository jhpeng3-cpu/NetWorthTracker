"""开发用热重启入口：保存 .py 后自动重启应用。

用法（在项目根目录，使用虚拟环境解释器）::

    .\\venv\\Scripts\\python.exe dev_run.py

仅用于开发调试；打包或正式运行仍使用 main.py。
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parent
ENTRY = ROOT / "main.py"
WATCH_SUFFIXES = {".py"}
IGNORE_PARTS = {
    "__pycache__",
    ".git",
    ".idea",
    ".venv",
    "venv",
    "build",
    "dist",
    ".trae",
}
POLL_SECONDS = 0.8
DEBOUNCE_SECONDS = 0.4


def snapshot() -> Dict[str, float]:
    """记录所有待监视 Python 文件的修改时间。"""
    stamps: Dict[str, float] = {}
    for path in ROOT.rglob("*"):
        if path.suffix not in WATCH_SUFFIXES or not path.is_file():
            continue
        if any(part in IGNORE_PARTS for part in path.parts):
            continue
        try:
            stamps[str(path)] = path.stat().st_mtime
        except OSError:
            continue
    return stamps


def start_app() -> subprocess.Popen:
    print("启动应用…", flush=True)
    return subprocess.Popen([sys.executable, str(ENTRY)], cwd=str(ROOT))


def stop_app(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def describe(changed: List[str], removed: List[str]) -> str:
    names = [Path(path).relative_to(ROOT).as_posix() for path in changed + removed]
    if len(names) <= 4:
        return "、".join(names)
    return "、".join(names[:4]) + f" 等 {len(names)} 个文件"


def main() -> int:
    print(f"热重启已启用，监视 {ROOT} 下的 *.py；按 Ctrl+C 退出。", flush=True)
    process = start_app()
    stamps = snapshot()
    try:
        while True:
            time.sleep(POLL_SECONDS)
            current = snapshot()
            changed = [
                path for path, stamp in current.items() if stamps.get(path) != stamp
            ]
            removed = [path for path in stamps if path not in current]
            if changed or removed:
                time.sleep(DEBOUNCE_SECONDS)
                current = snapshot()
                print(f"检测到变更：{describe(changed, removed)}，重启应用…", flush=True)
                stop_app(process)
                process = start_app()
                stamps = current
                continue
            stamps = current
            if process.poll() is not None:
                print("应用已退出，停止监视。", flush=True)
                return process.returncode or 0
    except KeyboardInterrupt:
        print("\n收到退出信号，关闭应用…", flush=True)
        stop_app(process)
        return 0


if __name__ == "__main__":
    sys.exit(main())
