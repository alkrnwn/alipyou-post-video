# Shopee Video · VMOS Auto-Post

Aplikasi otomatisasi posting Shopee Video berbasis **VMOS Cloud Phone** dengan antarmuka desktop modern (FastAPI + Electron), terintegrasi dengan scraper produk Shopee, generator prompt Google Flow (ALIPYOU), dan sistem eksekusi Auto-Pilot berurutan.

---

## 🌟 Fitur Utama

- **🚀 Auto-Pilot Posting Berurutan:**
  - Menjalankan antrean posting akun satu per satu secara otomatis.
  - Mengunduh video Flow, transfer ke ponsel cloud VMOS via ADB.
  - Membuka Shopee, beralih profil toko (*switch shop*), dan mempublikasikan video.
  - Menonton video selama 2 menit untuk membangun impresi awal, lalu melakukan *force-stop* aplikasi Shopee.
  - Jeda otomatis 60 detik antar tugas dengan tombol *Skip* (Lewati Jeda).
  - Pembatalan tugas seketika yang langsung menghentikan proses Shopee di ponsel cloud.

- **🎬 Studio Operator (Bahan & Kuncian Prompt):**
  - Tempel link produk Shopee untuk mengambil foto produk resolusi tinggi, ID produk, ID toko, narasi/voiceover, dan kuncian prompt video AI (ALIPYOU) yang siap disalin ke Google Flow.
  - Unduh foto produk 1-klik langsung ke folder PC.

- **🌐 Kredensial VMOS Cloud Dinamis:**
  - Input Access Key ID dan Secret Access Key langsung dari menu Pengaturan tanpa harus mengedit file `.env` atau merestart aplikasi.
  - Dilengkapi fitur pengujian koneksi (*Test Connection*) ke API VMOS Cloud.

- **📊 Sinkronisasi Google Sheets:**
  - Muat dan perbarui puluhan akun Shopee serta pad code VMOS langsung dari tautan spreadsheet Google Docs.
  - Pembersihan database lama secara bersih (*fresh update*) dan filter akun aktif.

- **🖥️ Tampilan Modern, Responsif & Full-Width:**
  - Layout *full-width* yang memanfaatkan seluruh ruang monitor layar lebar.
  - Dashboard interaktif dengan metrik live akun, antrean, dan status VMOS.
  - Menu pencarian instan pada Riwayat Tugas dan transisi status.

- **🧹 Manajemen Penyimpanan & Log Aktivitas:**
  - Pemantauan pemakaian memori database SQLite, file cache video lokal, dan file log.
  - Tombol pembersih cache video lokal 1-klik.
  - Penampil log sistem langsung (*Live Log Viewer*).

---

## 📋 Prasyarat Sistem

1. **Sistem Operasi:** Windows 10 / 11 (64-bit)
2. **Python:** Versi 3.10 ke atas ([Download Python](https://www.python.org/downloads/))
3. **Node.js:** Versi 18 ke atas ([Download Node.js](https://nodejs.org/))

---

## 🚀 Cara Menjalankan

### Cara Cepat (Rekomendasi Windows)
Cukup klik ganda (double-click) file:
```cmd
start.bat
```
Skrip ini akan otomatis:
1. Menyiapkan Python Virtual Environment (`.venv`).
2. Memasang pustaka Python dari `requirements.txt`.
3. Memasang dependensi Electron (`npm install`).
4. Membuka jendela aplikasi desktop Shopee Video VMOS.

---

### Cara Manual (CLI / Terminal)

1. **Masuk ke direktori proyek:**
   ```bash
   cd vmos_autopost
   ```

2. **Buat dan aktifkan Virtual Environment Python:**
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   ```

3. **Pasang dependensi Python:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Jalankan Backend FastAPI:**
   ```bash
   uvicorn app.main:app_factory --factory --host 127.0.0.1 --port 8000
   ```
   Aplikasi web dapat diakses di browser: `http://127.0.0.1:8000`

5. **(Opsional) Jalankan Desktop Electron:**
   ```bash
   cd desktop
   npm install
   npm start
   ```

---

## 🧪 Menjalankan Pengujian (Testing)

Proyek ini dilengkapi dengan 32 unit test otomatis:
```bash
python -m pytest vmos_autopost\tests
```

---

## 🔒 Keamanan & Lisensi

- File konfigurasi rahasia (`.env`), file database (`autopost.db`), log, dan video sementara diabaikan oleh `.gitignore` untuk melindungi privasi akun dan token API Anda.
- Hak cipta milik pengembang. Gunakan secara bijak sesuai ketentuan platform terkait.
