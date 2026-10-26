---
name: "vmos-auto-release"
description: "Aturan agen otomatis untuk merilis pembaruan Shopee Video VMOS ke GitHub Releases dan memicu update online ke seluruh komputer pengguna."
alwaysApply: true
---

# Shopee Video VMOS Auto-Release & Online Updater Agent

Aturan ini aktif setiap kali pengguna meminta pembaruan aplikasi, rilis versi baru, atau update installer (misalnya: "rilis update", "update versi baru", "upload update online", dsb).

## Alur Kerja Otomatis Agen (Zero Manual Effort)

Ketika pengguna meminta rilis/update:
1. **Verifikasi Pengujian**: Pastikan semua unit test lulus dengan menjalankan:
   ```powershell
   python -m pytest vmos_autopost/tests
   ```
2. **Tentukan Versi Baru**:
   - Jika pengguna menyebut versi (misal `1.0.1`), gunakan versi tersebut.
   - Jika tidak menyebutkan, naikkan nomor patch secara otomatis (misal `1.0.0` -> `1.0.1`).
3. **Eksekusi Otomasi Rilis Penuh**:
   Jalankan satu perintah otomatis:
   ```powershell
   python release_manager.py release <version> "<catatan_pembaruan>"
   ```
   Perintah ini akan secara otomatis:
   - Memperbarui nomor versi di `package.json`, `app/main.py`, dan `app/static/app.js`.
   - Mengompilasi backend mandiri via PyInstaller (`backend.exe`).
   - Mengemas installer Windows via electron-builder (`Setup .exe`, `Portable .exe`, dan `latest.yml`).
   - Melakukan git commit dan git tag versi (misal `v1.0.1`).
   - Mendorong (push) commit dan tag ke GitHub `alkrnwn/alipyou-post-video`.
   - Mengunggah berkas installer baru ke GitHub Releases API.
4. **Konfirmasi ke Pengguna**:
   Beri tahu pengguna bahwa versi baru telah terbit di GitHub Releases dan seluruh pengguna aplikasi akan menerima notifikasi update online saat membuka aplikasi.
