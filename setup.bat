@echo off
chcp 65001 >nul
title SpaceRPG4 星图工具 - 一键安装

echo.
echo ╔══════════════════════════════════════╗
echo ║   🚀 SpaceRPG4 Celestial Atlas      ║
echo ║   本地环境一键配置                    ║
echo ╚══════════════════════════════════════╝
echo.

:: 检查 Python
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo ❌ 未检测到 Python！请先安装 Python 3.9+
    echo    https://www.python.org/downloads/
    pause
    exit /b 1
)
echo ✅ Python 已检测到

:: 安装依赖
echo.
echo 📦 正在安装 Python 依赖...
pip install easyocr opencv-python numpy Pillow requests -q
if %errorlevel% neq 0 (
    echo ⚠️ pip 安装失败，请尝试手动运行: pip install -r requirements.txt
)

echo.
echo ✅ 依赖安装完成！
echo.
echo ╔══════════════════════════════════════╗
echo ║  请选择要启动的功能:                 ║
echo ║  1. OCR场景检测器 (自动识别Bar/Trade)║
echo ║  2. OCR框选工具 (手动框选+AI分析)    ║
echo ║  3. 仅打开星图网页                    ║
echo ╚══════════════════════════════════════╝
echo.
set /p choice="请输入选项 (1/2/3): "

if "%choice%"=="1" (
    echo.
    echo 🔌 正在启动 OCR 场景检测器...
    echo ⚠️ 请确保 MuMu 模拟器已启动！
    echo.
    python ocr_scene_detector.py
) else if "%choice%"=="2" (
    echo.
    echo 🔍 正在启动 OCR 框选工具...
    echo ⚠️ 请确保 MuMu 模拟器已启动！
    echo.
    python ocr_tool.py
) else (
    echo.
    echo 🗺️ 正在打开星图网页...
    start spacerpg4_map.html
)

pause
