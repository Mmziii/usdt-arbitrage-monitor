@echo off
chcp 65001 >nul
setlocal enableextensions
cd /d "%~dp0"
title USDT Arbitrage Monitor - local only

echo ================================================================
echo   مانیتور آربیتراژ USDT - اجرای محلی
echo   این برنامه فقط داده عمومی می‌خواند و به هیچ حساب کاربری
echo   یا کلید API دسترسی ندارد. هیچ سفارشی ثبت نمی‌شود.
echo ================================================================
echo.

rem UTF-8 for every file the app opens, even when Windows uses another code page.
set "PYTHONUTF8=1"

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

%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 (
  echo [خطا] نسخه پایتون نصب‌شده قدیمی است. نسخه ۳.۱۰ یا جدیدتر لازم است.
  echo Installed version:
  %PY% -V
  echo Install a newer Python from https://www.python.org/downloads/windows/
  echo.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo ساخت محیط پایتون برای بار اول... / Creating the Python environment...
  %PY% -m venv .venv
  if errorlevel 1 (
    echo [خطا] ساخت محیط مجازی ناموفق بود. / Could not create the virtual environment.
    echo اگر پوشه .venv نیمه‌کاره مانده، آن را پاک کنید و دوباره اجرا کنید.
    echo If a broken .venv is left over, delete it and run this file again.
    pause
    exit /b 1
  )
)

set "VENV_PY=.venv\Scripts\python.exe"

"%VENV_PY%" -c "import fastapi, uvicorn, httpx" >nul 2>nul
if errorlevel 1 (
  echo نصب پیش‌نیازها... / Installing requirements, this takes a minute...
  "%VENV_PY%" -m pip install --upgrade pip >nul
  "%VENV_PY%" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo [خطا] نصب پیش‌نیازها ناموفق بود. اینترنت را بررسی کنید.
    echo Could not install requirements. Check your internet connection.
    echo If pypi.org is blocked in your network, install from a mirror you trust:
    echo   .venv\Scripts\python.exe -m pip install -r requirements.txt -i https://YOUR-MIRROR/simple
    pause
    exit /b 1
  )
)

if not exist ".env" (
  if exist ".env.example" copy /y ".env.example" ".env" >nul
)

rem Pick the first free port; an occupied 8000 must not stop the app.
set "PORT="
for %%P in (8000 8001 8002 8003) do (
  if not defined PORT (
    "%VENV_PY%" -c "import socket, sys; c = socket.socket(); c.settimeout(0.5); sys.exit(0 if c.connect_ex(('127.0.0.1', int(sys.argv[1]))) else 1)" %%P >nul 2>nul && set "PORT=%%P"
  )
)
if not defined PORT (
  echo [خطا] پورت‌های ۸۰۰۰ تا ۸۰۰۳ آزاد نیستند.
  echo Ports 8000-8003 are all busy. Close the other program and run this file again.
  pause
  exit /b 1
)
if not "%PORT%"=="8000" (
  echo [توجه] پورت ۸۰۰۰ مشغول بود؛ برنامه روی پورت %PORT% اجرا می‌شود.
  echo Port 8000 was busy, so the app uses port %PORT%.
)

echo.
echo آدرس برنامه: http://127.0.0.1:%PORT%
echo برای بستن برنامه این پنجره را ببندید یا Ctrl+C بزنید.
echo The browser will open in a few seconds. Close this window to stop the app.
echo.

start "" /b cmd /c "ping -n 6 127.0.0.1 >nul & explorer.exe http://127.0.0.1:%PORT%"

"%VENV_PY%" -m app --host 127.0.0.1 --port %PORT%

echo.
echo برنامه متوقف شد. / The app has stopped.
pause
