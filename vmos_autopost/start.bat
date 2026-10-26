@echo off
title Shopee Video VMOS
cd /d "%~dp0"

echo ===================================================
echo     MEMBUKA SHOPEE VIDEO - VMOS AUTOPOST
echo ===================================================
echo.

rem Tutup instance Electron lama yang tersangkut di background jika ada
taskkill /f /im electron.exe >nul 2>&1

if not exist .venv (
    echo Membuat virtual environment Python...
    python -m venv .venv
)

call .venv\Scripts\activate.bat

if not exist .venv\installed.flag (
    echo Memeriksa dependensi Python...
    python -m pip install -q -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Gagal memasang dependensi Python.
        pause
        exit /b 1
    )
    echo ok > .venv\installed.flag
)

cd desktop
if not exist node_modules (
    echo Memasang dependensi desktop...
    call npm install
)

set AUTOPOST_PYTHON=%~dp0.venv\Scripts\python.exe
if not defined AUTOPOST_DRYRUN ( set AUTOPOST_DRYRUN=0 )

echo Memulai aplikasi Shopee Video VMOS...
call npm start

if errorlevel 1 (
    echo.
    echo [ERROR] Terjadi kesalahan saat menjalankan aplikasi.
    pause
)
