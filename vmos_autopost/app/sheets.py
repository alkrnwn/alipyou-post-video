"""Pembaca data akun dari CSV atau Google Sheets (hanya kolom yang dibutuhkan)."""
import csv
import time

ALLOWED = ["KODE", "USERNAME", "PAD CODE", "VMOS", "STATUS"]
REQUIRED = ["KODE", "USERNAME", "PAD CODE"]


def _clean(rows):
    """rows: list of dict (header -> nilai). Buang semua kolom di luar ALLOWED."""
    out = []
    for r in rows:
        norm = {str(k).strip().upper(): (v or "").strip() for k, v in r.items() if k}
        out.append({k: norm.get(k, "") for k in ALLOWED})
    return out


def load_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return _clean(list(csv.DictReader(f)))


def parse_row_range(row_range_str):
    """Parse range seperti '2-50', '2:50', atau '50' -> (start_row, end_row)."""
    if not row_range_str or not str(row_range_str).strip():
        return None, None
    s = str(row_range_str).strip().replace(":", "-").replace(" ", "")
    if "-" in s:
        parts = s.split("-", 1)
        start = int(parts[0]) if parts[0].isdigit() else None
        end = int(parts[1]) if parts[1].isdigit() else None
        return start, end
    elif s.isdigit():
        n = int(s)
        return n, n
    return None, None


def load_google_sheet_url(url, start_row=None, end_row=None):
    """Ambil data Google Sheets langsung dari URL (Share: Anyone with the link can view)."""
    import io
    import re
    import urllib.error
    import urllib.request

    url = (url or "").strip()
    if not url:
        raise ValueError("URL Google Sheet tidak boleh kosong")

    # Ambil Spreadsheet ID
    m_id = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url)
    if not m_id:
        raise ValueError("Format URL Google Sheets tidak valid. Harus mengandung /spreadsheets/d/<ID>/")
    sheet_id = m_id.group(1)

    # Ambil GID jika ada (spesifik tab sheet)
    m_gid = re.search(r"[#&?]gid=([0-9]+)", url)
    gid = m_gid.group(1) if m_gid else "0"

    export_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}&_t={int(time.time() * 1000)}"
    req = urllib.request.Request(
        export_url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            text = resp.read().decode("utf-8-sig", errors="replace")
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise RuntimeError(
                "Tidak dapat mengakses Google Sheet. Pastikan akses Share di Google Sheet "
                "diatur ke 'Anyone with the link can view' (Siapa saja yang memiliki link)."
            )
        raise RuntimeError(f"Gagal mengambil Google Sheet (HTTP {e.code}): {e.reason}")
    except Exception as e:
        raise RuntimeError(f"Gagal mengunduh sheet: {e}")

    reader = csv.DictReader(io.StringIO(text))
    cleaned = _clean(list(reader))

    if start_row is not None or end_row is not None:
        out = []
        for idx, r in enumerate(cleaned, start=2):  # Baris 1 = header, data mulai dari baris 2
            if start_row is not None and idx < start_row:
                continue
            if end_row is not None and idx > end_row:
                continue
            out.append(r)
        return out

    return cleaned


def load_google_sheet(spreadsheet_id, range_a1, service_account_file):
    """Akses baca saja. Butuh: google-api-python-client, google-auth.
    BELUM DIUJI di sini (tidak ada akses jaringan/kredensial); uji di PC Anda."""
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    creds = Credentials.from_service_account_file(
        service_account_file,
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
    svc = build("sheets", "v4", credentials=creds, cache_discovery=False)
    vals = svc.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range=range_a1).execute().get("values", [])
    if not vals:
        return []
    header = [h.strip().upper() for h in vals[0]]
    rows = [dict(zip(header, r + [""] * (len(header) - len(r)))) for r in vals[1:]]
    return _clean(rows)


def validate(rows, api_pad_codes=None, filter_active_only=False):
    """Kembalikan (baris_valid, masalah). Tidak melempar error untuk baris buruk."""
    valid, problems = [], []
    seen_kode, seen_user = {}, {}
    for i, r in enumerate(rows, start=2):  # baris 1 = header
        miss = [k for k in REQUIRED if not r.get(k)]
        if miss:
            problems.append((i, f"kolom wajib kosong: {', '.join(miss)}"))
            continue
        status_val = (r.get("STATUS") or "").strip().upper()
        if filter_active_only and status_val in ("PERMANEN", "BANNED", "NONAKTIF", "OFF"):
            problems.append((i, f"Dilewati: akun berstatus {status_val}"))
            continue
        user = r["USERNAME"].lstrip("@").lower()
        if r["KODE"] in seen_kode:
            problems.append((i, f"KODE ganda (juga di baris {seen_kode[r['KODE']]})"))
            continue
        if user in seen_user:
            problems.append((i, f"USERNAME ganda (juga di baris {seen_user[user]})"))
            continue
        if api_pad_codes is not None and r["PAD CODE"] not in api_pad_codes:
            problems.append((i, f"PAD CODE {r['PAD CODE']} tidak ada di daftar device API"))
            continue
        seen_kode[r["KODE"]] = i
        seen_user[user] = i
        valid.append(r)
    return valid, problems


def sync(service, rows, api_pad_codes=None, replace=True, clear_old_tasks=False, filter_active_only=False):
    valid, problems = validate(rows, api_pad_codes, filter_active_only=filter_active_only)
    if replace and hasattr(service, "replace_accounts"):
        service.replace_accounts(valid, clear_old_tasks=clear_old_tasks)
    else:
        for r in valid:
            service.upsert_account(r["KODE"], r["USERNAME"], r["PAD CODE"], label=r.get("VMOS") or None, status_akun=r.get("STATUS") or None)
    return {"synced": len(valid), "problems": problems}
