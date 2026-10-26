@echo off
title Rilis Pembaruan Shopee Video VMOS
cd /d "%~dp0"

echo ========================================================
echo     SHOPEE VIDEO VMOS - OTOMASI RILIS ONLINE
echo ========================================================
echo.

set /p NEW_VER="Masukkan nomor versi baru (contoh 1.0.1): "
if "%NEW_VER%"=="" (
    echo [ERROR] Nomor versi tidak boleh kosong.
    pause
    exit /b 1
)

set /p NOTES="Masukkan catatan pembaruan / fitur baru: "
if "%NOTES%"=="" (
    set NOTES=Pembaruan performa dan perbaikan fitur Shopee Video VMOS v%NEW_VER%
)

echo.
echo Memulai proses otomasi rilis versi v%NEW_VER%...
python release_manager.py release %NEW_VER% "%NOTES%"

if errorlevel 1 (
    echo.
    echo [ERROR] Proses rilis gagal.
    pause
    exit /b 1
)

echo.
echo ========================================================
echo     RILIS SELESAI & UPDATE ONLINE SUDAH AKTIF!
echo ========================================================
pause
