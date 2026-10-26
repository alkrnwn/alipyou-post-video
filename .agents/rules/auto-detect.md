---
name: "auto-detect-project-stack"
description: "Instruksi untuk mendeteksi bahasa pemrograman dan framework secara otomatis, lalu mengaktifkan skill yang sesuai."
alwaysApply: true
---

# Auto-Detect Project Stack & Activate Skills

## Instruksi Utama

Kamu adalah Agent yang WAJIB mendeteksi secara otomatis bahasa pemrograman, framework, dan tools yang digunakan di setiap proyek — baik proyek baru maupun proyek lama yang sudah berjalan.

## Aturan Deteksi Otomatis

### 1. Scan File Konfigurasi Proyek
Saat pertama kali bekerja di sebuah proyek, lakukan scan terhadap file-file berikut untuk menentukan stack teknologi:

| File / Pattern | Indikasi Stack |
|---|---|
| `package.json` | Node.js / JavaScript / TypeScript |
| `tsconfig.json` | TypeScript |
| `next.config.*` | Next.js |
| `nuxt.config.*` | Nuxt.js / Vue |
| `vite.config.*` | Vite |
| `angular.json` | Angular |
| `svelte.config.*` | SvelteKit / Svelte |
| `requirements.txt`, `pyproject.toml`, `setup.py` | Python |
| `Pipfile` | Python (Pipenv) |
| `manage.py` | Django |
| `Cargo.toml` | Rust |
| `go.mod` | Go |
| `pom.xml`, `build.gradle` | Java |
| `Gemfile` | Ruby / Rails |
| `composer.json` | PHP / Laravel |
| `pubspec.yaml` | Flutter / Dart |
| `Dockerfile`, `docker-compose.yml` | Docker |
| `.swift`, `Package.swift` | Swift |
| `*.sol` | Solidity |
| `tailwind.config.*` | Tailwind CSS |
| `supabase/` | Supabase |

### 2. Scan Kode yang Sudah Ada
- Periksa ekstensi file dominan (`.py`, `.ts`, `.tsx`, `.go`, `.rs`, dll.)
- Periksa import/require statements untuk menentukan library yang digunakan
- Periksa folder structure (misal `app/`, `pages/`, `components/`, `src/`)

### 3. Aktifkan Skill yang Sesuai
Setelah mendeteksi stack, gunakan skill yang tersedia di `.agents/skills/` sesuai teknologi yang terdeteksi. Contoh mapping:

- **Next.js + TypeScript** → Aktifkan skill: `nextjs`, `typescript`, `react`
- **Python + FastAPI** → Aktifkan skill: `python`, `fastapi`
- **Flutter** → Aktifkan skill: `flutter-app-expert-cursorrules-prompt-file`
- **Vue + Nuxt** → Aktifkan skill: `vue`, `vue-3-nuxt-3-development-cursorrules-prompt-file`
- **Go** → Aktifkan skill: `go`
- **Rust** → Aktifkan skill: `rust`, `rust-general`
- **Laravel** → Aktifkan skill: `laravel-php-83-cursorrules-prompt-file`

### 4. Aturan Perlindungan Kode Lama
⚠️ **PENTING**: Saat bekerja di proyek yang sudah ada:

1. **JANGAN** mengubah konfigurasi yang sudah berjalan tanpa diminta
2. **JANGAN** meng-upgrade dependency secara sepihak
3. **JANGAN** mengubah struktur folder yang sudah mapan
4. **JANGAN** mengganti pattern/arsitektur yang sudah digunakan
5. **SELALU** pertahankan style/convention yang sudah ada di codebase
6. **SELALU** tanyakan dulu sebelum melakukan perubahan breaking
7. **SELALU** backup atau buat branch baru sebelum perubahan besar

### 5. Prioritas Skill
Jika terdeteksi multiple framework/library, aktifkan semua skill yang relevan dengan urutan prioritas:
1. Framework utama (Next.js, Django, Laravel, dll.)
2. Bahasa pemrograman (TypeScript, Python, Go, dll.)
3. UI Framework (Tailwind, Chakra UI, dll.)
4. State management (Redux, Zustand, Pinia, dll.)
5. Testing framework (Jest, Playwright, Cypress, dll.)
6. DevOps tools (Docker, Kubernetes, dll.)

### 6. Logging Deteksi
Setiap kali mendeteksi stack baru, informasikan ke user:
```
🔍 Terdeteksi stack:
  - Framework: [nama framework]
  - Bahasa: [bahasa pemrograman]
  - Tools: [tools tambahan]
  - Skills diaktifkan: [list skill]
```
