@echo off
title SpaceRPG4 Setup
echo.
echo ========================================
echo   SpaceRPG4 Celestial Atlas - Setup
echo ========================================
echo.

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python not found! Please install Python 3.9+
    echo https://www.python.org/downloads/
    pause
    exit /b 1
)
echo [OK] Python detected

echo.
echo Installing dependencies...
pip install easyocr opencv-python "numpy<2" Pillow requests scikit-image -q
echo [OK] Dependencies installed
echo.

echo ========================================
echo   1. OCR Scene Detector (auto Bar/Trade)
echo   2. OCR Tool (manual select + AI)
echo   3. Open Star Map (browser)
echo ========================================
echo.
set /p choice="Enter 1, 2, or 3: "

if "%choice%"=="1" (
    echo.
    echo Starting OCR Scene Detector...
    echo Make sure MuMu emulator is running!
    echo.
    python ocr_scene_detector.py
    pause
) else if "%choice%"=="2" (
    echo.
    echo Starting OCR Tool...
    echo Make sure MuMu emulator is running!
    echo.
    python ocr_tool.py
    pause
) else if "%choice%"=="3" (
    echo Opening star map...
    start "" "spacerpg4_map.html"
) else (
    echo Invalid choice. Exiting.
    pause
)
