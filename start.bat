@echo off
chcp 65001 >nul
setlocal enableextensions
cd /d "%~dp0"
title USDT Arbitrage Monitor - local only

echo ================================================================
echo   پایش فرصت آربیتراژ - اجرای محلی
echo   این برنامه فقط داده عمومی می خواند و هیچ سفارشی ثبت نمی کند.
echo ================================================================
echo.

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo [خطا] پایتون پیدا نشد.
  echo Python 3.10 or newer is required. Install it from https://www.python.org/downloads/windows/
  echo During setup tick "Add python.exe to PATH", then run this file again.
  echo.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo ساخت محیط پایتون برای اولین اجرا... / Creating the Python environment...
  %PY% -m venv .venv
  if errorlevel 1 (
    echo [خطا] ساخت محیط ناموفق بود. / Could not create the virtual environment.
    pause
    exit /b 1
  )
)

set "VENV_PY=.venv\Scripts\python.exe"

"%VENV_PY%" -c "import fastapi, uvicorn, httpx" >nul 2>nul
if errorlevel 1 (
  echo نصب پیش نیازها... / Installing requirements, this takes a minute...
  "%VENV_PY%" -m pip install --upgrade pip >nul
  "%VENV_PY%" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo [خطا] نصب پیش نیازها ناموفق بود. اینترنت را بررسی کنید.
    echo Could not install requirements. Check your internet connection.
    pause
    exit /b 1
  )
)

if not exist ".env" (
  if exist ".env.example" copy /y ".env.example" ".env" >nul
)

echo.
echo آدرس برنامه: http://127.0.0.1:8000
echo برای بستن برنامه این پنجره را ببندید یا Ctrl+C بزنید.
echo The browser will open in a few seconds. Close this window to stop the app.
echo.

start "" /b cmd /c "timeout /t 5 >nul & start "" http://127.0.0.1:8000"

"%VENV_PY%" -m app --host 127.0.0.1 --port 8000

echo.
echo برنامه متوقف شد. / The app has stopped.
pause
