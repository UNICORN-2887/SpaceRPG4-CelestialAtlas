@echo off
echo ADB Connection Test
echo ===================

echo.
echo Make sure MuMu emulator is running!
echo You can find adb.exe at MuMu installation folder.
echo Example: D:\Program Files\Mumu Player 12\nx_main\adb.exe
echo.

set ADB=
set /p ADB="ADB path: "
if "%ADB%"=="" (
    echo ERROR: ADB path is required!
    pause
    exit /b
)

echo.
"%ADB%" devices 2>nul
if %errorlevel% neq 0 (
    echo ERROR: Cannot run ADB. Check the path.
    pause
    exit /b
)

echo.
echo Found devices above. Testing screenshot...
echo.

set DEV=emulator-5554
echo Trying device: %DEV%
"%ADB%" -s %DEV% shell echo TEST_OK 2>nul
if %errorlevel% equ 0 (
    echo [SUCCESS] Connected to %DEV%!
    pause
    exit /b
)

echo.
set DEV=127.0.0.1:16384
echo Trying device: %DEV%
"%ADB%" connect %DEV% >nul 2>nul
"%ADB%" -s %DEV% shell echo TEST_OK 2>nul
if %errorlevel% equ 0 (
    echo [SUCCESS] Connected to %DEV%!
    pause
    exit /b
)

echo.
echo [FAILED] Cannot connect to MuMu.
echo Please check:
echo   1. MuMu emulator is running
echo   2. In MuMu: Settings - Other - ADB debugging is ON
echo   3. Try running: adb kill-server then adb start-server
pause
