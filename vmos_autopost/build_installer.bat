@echo off
title Build Installer Shopee Video VMOS
cd /d "%~dp0"
echo ========================================================
echo   KOMPILASI STANDALONE INSTALLER SHOPEE VIDEO VMOS
echo ========================================================
echo.
echo 1. Memeriksa dependensi Python...
call .venv\Scripts\activate.bat
python -m pip install -q pyinstaller
echo.
echo 2. Mengompilasi backend server ke binary mandiri (PyInstaller)...
.venv\Scripts\pyinstaller.exe --noconfirm --onedir --name "backend" --add-data "app/static;app/static" --add-data "adb;adb" --hidden-import "uvicorn.logging" --hidden-import "uvicorn.loops" --hidden-import "uvicorn.loops.auto" --hidden-import "uvicorn.protocols" --hidden-import "uvicorn.protocols.http" --hidden-import "uvicorn.protocols.http.auto" --hidden-import "uvicorn.protocols.http.h11_impl" --hidden-import "uvicorn.lifespan" --hidden-import "uvicorn.lifespan.on" --hidden-import "anyio._backends._asyncio" --distpath "desktop\backend" server.py
if errorlevel 1 (
    echo [ERROR] Gagal mengompilasi backend.
    pause
    exit /b 1
)
echo.
echo 3. Mengemas aplikasi Electron ke berkas Setup .exe (NSIS ^& Portable)...
cd desktop
call npm run dist
if errorlevel 1 (
    echo [ERROR] Gagal mengemas installer desktop.
    pause
    exit /b 1
)
cd ..
if not exist "..\dist" mkdir "..\dist"
copy /y "desktop\dist\Shopee Video VMOS Setup 1.0.0.exe" "..\dist\"
copy /y "desktop\dist\Shopee-Video-VMOS-Portable-v1.0.0.exe" "..\dist\"
echo.
echo ========================================================
echo   SUKSES! Berkas installer tersimpan di:
echo   dist\Shopee Video VMOS Setup 1.0.0.exe
echo   dist\Shopee-Video-VMOS-Portable-v1.0.0.exe
echo ========================================================
pause
