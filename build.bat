@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo 未找到 venv\Scripts\python.exe，请先创建虚拟环境并安装依赖。
    pause
    exit /b 1
)

echo 正在打包，请稍候…
venv\Scripts\python.exe -m PyInstaller NetWorthTracker.spec --noconfirm
if errorlevel 1 (
    echo.
    echo 打包失败，请查看上方日志。
    pause
    exit /b 1
)

echo.
echo 打包完成：dist\NetWorthTracker\NetWorthTracker.exe
pause
