@echo off
chcp 65001 >nul
REM ============================================================
REM weldAI 一键打包脚本（生成单文件 exe）
REM 用法：scripts\build_exe.bat
REM 产物：dist\weldAI.exe
REM ============================================================

echo [1/3] 清理旧产物...
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build

echo [2/3] 执行 PyInstaller 打包...
pyinstaller build.spec --noconfirm
if errorlevel 1 (
    echo ❌ 打包失败
    exit /b 1
)

echo [3/3] 验证产物...
if exist dist\weldAI.exe (
    echo ✓ 打包成功
    for %%I in (dist\weldAI.exe) do echo   weldAI.exe  %%~zI bytes
    echo.
    echo 产物路径: dist\weldAI.exe
    echo 双击即可运行，无需安装 Python。
) else (
    echo ❌ 未找到产物 dist\weldAI.exe
    exit /b 1
)
