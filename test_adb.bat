@echo off
echo ADB Connection Test
echo ===================
echo.

set /p ADB="Enter ADB path (e.g. D:\工程\MuMu Player 12\nx_main\adb.exe): "
set /p DEV="Enter device ID (or leave blank): "

if "%DEV%"=="" set DEV=emulator-5554

echo.
echo Testing with: "%ADB%" -s %DEV%
echo.

"%ADB%" devices
echo.

"%ADB%" -s %DEV% shell echo TEST_OK
if %errorlevel% equ 0 (
    echo [SUCCESS] ADB connection works!
) else (
    echo [FAILED] Cannot connect. Try:
    echo   1. Make sure MuMu emulator is running
    echo   2. Try device ID: 127.0.0.1:16384
    echo   3. Run: adb connect 127.0.0.1:16384
)
pause
