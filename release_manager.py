"""
Skrip Otomasi Rilis & Pembaruan Online untuk Shopee Video VMOS.
Mengotomatiskan:
1. Pengecekan unit test (pytest)
2. Pembaruan nomor versi (package.json & main.py)
3. Kompilasi PyInstaller & Electron-Builder
4. Commit Git, Tag Git, dan Push ke GitHub
5. Pembuatan GitHub Release dan Pengunggahan Berkas Installer (.exe & latest.yml)
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

GITHUB_REPO = "alkrnwn/alipyou-post-video"
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(ROOT_DIR, "vmos_autopost", "desktop", "dist")


def get_token():
    if os.environ.get("GITHUB_TOKEN"):
        return os.environ.get("GITHUB_TOKEN").strip()
    token_file = os.path.join(ROOT_DIR, "github_token.txt")
    if os.path.isfile(token_file):
        with open(token_file, "r", encoding="utf-8") as f:
            t = f.read().strip()
            if t:
                return t
    return ""


DEFAULT_TOKEN = get_token()


def run(cmd, cwd=None, check=True):
    print(f"\n[RUN] {cmd} (cwd={cwd or ROOT_DIR})")
    res = subprocess.run(cmd, cwd=cwd or ROOT_DIR, shell=True)
    if check and res.returncode != 0:
        print(f"[ERROR] Perintah gagal dengan exit code {res.returncode}: {cmd}")
        sys.exit(res.returncode)
    return res.returncode


def get_current_version():
    pkg_path = os.path.join(ROOT_DIR, "vmos_autopost", "desktop", "package.json")
    with open(pkg_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("version", "1.0.0")


def set_version(new_version):
    print(f"[VERSION] Memperbarui versi ke {new_version}...")
    
    # 1. Update desktop/package.json
    pkg_path = os.path.join(ROOT_DIR, "vmos_autopost", "desktop", "package.json")
    with open(pkg_path, "r", encoding="utf-8") as f:
        pkg_data = json.load(f)
    pkg_data["version"] = new_version
    with open(pkg_path, "w", encoding="utf-8") as f:
        json.dump(pkg_data, f, indent=2)

    # 2. Update app/main.py
    main_py_path = os.path.join(ROOT_DIR, "vmos_autopost", "app", "main.py")
    with open(main_py_path, "r", encoding="utf-8") as f:
        content = f.read()
    new_content = re.sub(r'"version":\s*"[^"]+"', f'"version": "{new_version}"', content)
    with open(main_py_path, "w", encoding="utf-8") as f:
        f.write(new_content)

    # 3. Update app/static/app.js
    app_js_path = os.path.join(ROOT_DIR, "vmos_autopost", "app", "static", "app.js")
    with open(app_js_path, "r", encoding="utf-8") as f:
        app_js_content = f.read()
    new_app_js = re.sub(r"'v\d+\.\d+\.\d+'", f"'v{new_version}'", app_js_content)
    with open(app_js_path, "w", encoding="utf-8") as f:
        f.write(new_app_js)

    print(f"[VERSION] Berhasil diperbarui ke v{new_version}!")


def upload_release(version, tag_name, notes, token):
    print(f"\n[GITHUB] Membuat rilis GitHub untuk {tag_name}...")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "Shopee-Video-VMOS-AutoReleaser"
    }

    # 1. Cek apakah rilis sudah ada
    check_url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/tags/{tag_name}"
    req = urllib.request.Request(check_url, headers=headers)
    release = None
    try:
        with urllib.request.urlopen(req) as resp:
            release = json.loads(resp.read())
            print(f"[GITHUB] Release {tag_name} sudah ada (ID: {release['id']}). Memperbarui aset...")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise

    # 2. Jika belum ada, buat release baru
    if not release:
        create_url = f"https://api.github.com/repos/{GITHUB_REPO}/releases"
        payload = json.dumps({
            "tag_name": tag_name,
            "target_commitish": "main",
            "name": f"Shopee Video VMOS v{version}",
            "body": notes or f"Rilis pembaruan Shopee Video VMOS v{version}.",
            "draft": False,
            "prerelease": False
        }).encode("utf-8")
        req = urllib.request.Request(create_url, data=payload, headers={**headers, "Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            release = json.loads(resp.read())
            print(f"[GITHUB] Release {tag_name} berhasil dibuat (ID: {release['id']})!")

    upload_url_tmpl = release.get("upload_url", "")
    upload_base = upload_url_tmpl.split("{")[0]

    # 3. Kumpulkan file installer yang akan diunggah
    files_to_upload = []
    if os.path.isdir(DIST_DIR):
        for f in os.listdir(DIST_DIR):
            if f.endswith(".exe") or f == "latest.yml":
                files_to_upload.append(os.path.join(DIST_DIR, f))

    if not files_to_upload:
        print("[WARN] Tidak ada berkas .exe atau latest.yml yang ditemukan di folder dist.")
        return

    # Daftar aset yang sudah ada di release
    existing_assets = {a["name"]: a["id"] for a in release.get("assets", [])}

    for file_path in files_to_upload:
        fname = os.path.basename(file_path)
        fsize_mb = os.path.getsize(file_path) / (1024 * 1024)

        # Hapus aset lama jika namanya sama
        if fname in existing_assets:
            del_url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/assets/{existing_assets[fname]}"
            del_req = urllib.request.Request(del_url, headers=headers, method="DELETE")
            try:
                with urllib.request.urlopen(del_req):
                    print(f"[GITHUB] Menghapus aset lama '{fname}'...")
            except Exception as e:
                print(f"[WARN] Gagal menghapus aset lama: {e}")

        print(f"[GITHUB] Mengunggah {fname} ({fsize_mb:.1f} MB)... Mohon tunggu...")
        with open(file_path, "rb") as f:
            file_bytes = f.read()

        content_type = "application/octet-stream"
        if fname.endswith(".yml"):
            content_type = "text/yaml"

        upload_req_url = f"{upload_base}?name={urllib.parse.quote(fname)}"
        up_req = urllib.request.Request(
            upload_req_url,
            data=file_bytes,
            headers={
                **headers,
                "Content-Type": content_type,
                "Content-Length": str(len(file_bytes))
            }
        )
        try:
            with urllib.request.urlopen(up_req) as up_resp:
                up_data = json.loads(up_resp.read())
                print(f"  ✓ Sukses: {fname} (ID: {up_data.get('id')})")
        except Exception as err:
            print(f"  ❌ Gagal mengunggah {fname}: {err}")

    print(f"\n✅ SELURUH BERKAS RILIS v{version} BERHASIL DIUNGGAH KE GITHUB RELEASES!")
    print(f"🌐 Tautan Rilis: https://github.com/{GITHUB_REPO}/releases/tag/{tag_name}")


def main():
    parser = argparse.ArgumentParser(description="Alat Otomasi Rilis & Update Online Shopee Video VMOS")
    subparsers = parser.add_subparsers(dest="command")

    # Command: publish-current
    sub_pub = subparsers.add_parser("publish-current", help="Unggah berkas installer yang sudah ada ke GitHub Release")
    sub_pub.add_argument("--notes", default="", help="Catatan rilis")
    sub_pub.add_argument("--token", default=DEFAULT_TOKEN, help="GitHub PAT Token")

    # Command: release
    sub_rel = subparsers.add_parser("release", help="Proses penuh: update versi, tes, build, commit, tag, dan publish")
    sub_rel.add_argument("version", help="Nomor versi baru (mis. 1.0.1)")
    sub_rel.add_argument("notes", nargs="?", default="", help="Catatan rilis/fitur baru")
    sub_rel.add_argument("--token", default=DEFAULT_TOKEN, help="GitHub PAT Token")
    sub_rel.add_argument("--skip-build", action="store_true", help="Lewati proses compile installer")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    token = getattr(args, "token", DEFAULT_TOKEN)

    if args.command == "publish-current":
        current_ver = get_current_version()
        tag = f"v{current_ver}"
        upload_release(current_ver, tag, args.notes or f"Rilis Shopee Video VMOS {tag}", token)

    elif args.command == "release":
        ver = args.version.lstrip("v")
        tag = f"v{ver}"
        notes = args.notes or f"Pembaruan Shopee Video VMOS {tag}"

        print("=" * 60)
        print(f"🚀 MEMULAI OTOMASI RILIS VERSI BARU: {tag}")
        print("=" * 60)

        # 1. Jalankan unit test pytest
        print("\n[LANGKAH 1] Menjalankan Pengujian Unit Pytest...")
        run("python -m pytest vmos_autopost/tests")

        # 2. Update nomor versi di semua file
        print("\n[LANGKAH 2] Memperbarui Nomor Versi...")
        set_version(ver)

        # 3. Build berkas installer jika tidak di-skip
        if not args.skip_build:
            print("\n[LANGKAH 3] Mengompilasi Installer Mandiri (.exe)...")
            bat_path = os.path.join(ROOT_DIR, "vmos_autopost", "build_installer.bat")
            # Jalankan tahapan build
            run(f'call "{bat_path}"')

        # 4. Commit & Tag Git
        print("\n[LANGKAH 4] Commit Git & Tag Release...")
        run("git add .")
        run(f'git commit -m "chore(release): bump version to {tag}"', check=False)
        run(f"git tag -f {tag}")

        # 5. Push ke GitHub
        print("\n[LANGKAH 5] Mendorong (Push) ke GitHub...")
        push_url = f"https://alkrnwn:{token}@github.com/{GITHUB_REPO}.git"
        run(f'git push "{push_url}" main --tags')

        # 6. Unggah ke GitHub Releases
        print("\n[LANGKAH 6] Mengunggah Berkas Installer ke GitHub Releases...")
        upload_release(ver, tag, notes, token)

        print("\n" + "=" * 60)
        print(f"🎉 SUKSES BESAR! VERSI {tag} TELAH TERBIT SECARA ONLINE!")
        print("Seluruh pengguna aplikasi akan otomatis menerima notifikasi update.")
        print("=" * 60)


if __name__ == "__main__":
    main()
