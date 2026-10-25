@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0.."

echo ============================================
echo   Celeste Dialogue DEMO - asset extraction
echo ============================================
echo.

if "%CELESTE_DIR%"=="" (
    set "CELESTE_DIR=E:\Programs\Steam\steamapps\common\Celeste"
)

if not exist "%CELESTE_DIR%\Content\Dialog\Simplified Chinese.txt" (
    echo [ERROR] Celeste install not found:
    echo         %CELESTE_DIR%
    echo.
    echo         Set CELESTE_DIR first, for example:
    echo         set CELESTE_DIR=D:\SteamLibrary\steamapps\common\Celeste
    exit /b 2
)

echo Game dir: %CELESTE_DIR%
echo.

echo [1/3] Extracting font / textbox / portrait textures ...
python tools\extract_textures.py --game-dir "%CELESTE_DIR%"
if errorlevel 1 goto :fail

echo.
echo [2/3] Extracting dialogue scenes (text + voice mapping) ...
python tools\extract_dialog.py --game-dir "%CELESTE_DIR%"
if errorlevel 1 goto :fail

echo.
echo [3/3] Rendering character voices with FMOD Studio ...
python tools\render_audio.py --game-dir "%CELESTE_DIR%"
if errorlevel 1 goto :fail

echo.
echo ============================================
echo   Done. Open index.html to run the DEMO.
echo ============================================
exit /b 0

:fail
echo.
echo [FAILED] Extraction aborted. See the error above.
exit /b 1
