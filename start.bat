@echo off
REM ── One-click launcher for the Delhi Transit Journey Planner ──────────────
REM Double-click this file to start the app. It opens the backend, waits for
REM it to be ready, then opens the app in your browser.

cd /d "%~dp0"

if not exist "venv\Scripts\activate.bat" (
    echo [ERROR] venv not found. Create it first:  python -m venv venv
    pause
    exit /b 1
)

echo Starting the backend...
start "Transit Backend (keep open)" cmd /k "venv\Scripts\activate && python manage.py runserver"

echo Waiting for the backend to come up...
timeout /t 5 /nobreak >nul

echo Opening the app in your browser...
start "" "http://localhost:8000"

echo.
echo ============================================================
echo  App is starting at  http://localhost:8000
echo  A "Transit Backend" window opened - KEEP IT OPEN.
echo  Close that window to stop the app.
echo ============================================================
echo.
pause
