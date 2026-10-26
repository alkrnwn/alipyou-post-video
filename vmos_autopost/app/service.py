import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from . import db
from .states import *  # noqa: F401,F403
from .states import (ALL, CANCELLED, FAILED, NEEDS_OPERATOR, PAUSED, PREPARING,
                     QUEUED, REVIEW_REQUIRED, TERMINAL, TRANSITIONS, VERIFIED)


class InvalidTransition(Exception):
    pass


class GuardError(Exception):
    pass


class DuplicateTask(Exception):
    pass


class NotFound(Exception):
    pass


@dataclass
class Config:
    cleanup_delay_s: int = 300       # jeda aman setelah VERIFIED sebelum video dihapus
    cleanup_max_attempts: int = 3
    operator_timeout_min: int = 30   # NEEDS_OPERATOR -> REVIEW_REQUIRED
    max_posts_per_day: int = int(os.environ.get("AUTOPOST_MAX_PER_DAY", "30"))       # per username
    min_gap_sec: Optional[int] = None
    min_gap_min: float = float(os.environ.get("AUTOPOST_MIN_GAP_MIN", "1.0"))       # default 1.0 menit = 60 detik jeda
    device_dir: str = "/sdcard/Movies/autopost"
    timezone_offset_hours: int = 7   # default WIB (UTC+7)


def norm_username(u):
    return (u or "").strip().lstrip("@").lower()


def _default_clock():
    return datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _parse(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")


class Service:
    def __init__(self, db_path, config=None, clock=None):
        self.db_path = db_path
        self.cfg = config or Config()
        self.clock = clock or _default_clock
        db.init(db_path)

    # ---------- util ----------
    def _now(self):
        return _iso(self.clock())

    def _get(self, c, task_id):
        r = c.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not r:
            raise NotFound(f"tugas {task_id} tidak ditemukan")
        return dict(r)

    def get_task(self, task_id):
        with db.read(self.db_path) as c:
            return self._get(c, task_id)

    def list_tasks(self, status=None):
        with db.read(self.db_path) as c:
            if status:
                rows = c.execute("SELECT * FROM tasks WHERE status=? ORDER BY id", (status,))
            else:
                rows = c.execute("SELECT * FROM tasks ORDER BY id")
            return [dict(r) for r in rows]

    def history(self, task_id):
        with db.read(self.db_path) as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM task_history WHERE task_id=? ORDER BY id", (task_id,))]

    # ---------- data master ----------
    def upsert_device(self, pad_code, label=None):
        with db.tx(self.db_path) as c:
            c.execute("INSERT INTO devices(pad_code,label) VALUES(?,?) "
                      "ON CONFLICT(pad_code) DO UPDATE SET label=excluded.label",
                      (pad_code, label))

    def replace_accounts(self, valid_rows, clear_old_tasks=False):
        valid_users = {norm_username(r["USERNAME"]) for r in valid_rows}
        with db.tx(self.db_path) as c:
            if clear_old_tasks:
                c.execute("DELETE FROM task_history")
                c.execute("DELETE FROM cleanup_log")
                c.execute("DELETE FROM device_locks")
                c.execute("DELETE FROM tasks")
                c.execute("DELETE FROM accounts")
            else:
                if valid_users:
                    placeholders = ",".join("?" for _ in valid_users)
                    c.execute(
                        f"DELETE FROM accounts WHERE username NOT IN (SELECT username FROM tasks) "
                        f"AND username NOT IN ({placeholders})",
                        list(valid_users),
                    )
                else:
                    c.execute("DELETE FROM accounts WHERE username NOT IN (SELECT username FROM tasks)")

            for r in valid_rows:
                username = norm_username(r["USERNAME"])
                c.execute(
                    "INSERT INTO devices(pad_code,label) VALUES(?,?) "
                    "ON CONFLICT(pad_code) DO UPDATE SET label=COALESCE(excluded.label,label)",
                    (r["PAD CODE"], r.get("VMOS") or None),
                )
                c.execute(
                    "INSERT INTO accounts(username,kode,pad_code,label,status_akun) VALUES(?,?,?,?,?) "
                    "ON CONFLICT(username) DO UPDATE SET kode=excluded.kode, pad_code=excluded.pad_code, "
                    "label=excluded.label, status_akun=excluded.status_akun",
                    (username, r["KODE"], r["PAD CODE"], r.get("VMOS") or None, r.get("STATUS") or None),
                )

    def get_setting(self, key: str, default: str = None) -> str:
        return db.get_setting(self.db_path, key, default)

    def set_setting(self, key: str, value: str):
        db.set_setting(self.db_path, key, value)

    def reset_all_data(self):
        with db.tx(self.db_path) as c:
            c.execute("DELETE FROM task_history")
            c.execute("DELETE FROM cleanup_log")
            c.execute("DELETE FROM device_locks")
            c.execute("DELETE FROM tasks")
            c.execute("DELETE FROM accounts")
        return {"ok": True, "message": "Semua data akun dan tugas berhasil dikosongkan"}

    def upsert_account(self, kode, username, pad_code, label=None, status_akun=None):
        username = norm_username(username)
        with db.tx(self.db_path) as c:
            c.execute("INSERT INTO devices(pad_code,label) VALUES(?,?) "
                      "ON CONFLICT(pad_code) DO UPDATE SET label=COALESCE(excluded.label,label)",
                      (pad_code, label))
            c.execute("INSERT INTO accounts(username,kode,pad_code,label,status_akun) VALUES(?,?,?,?,?) "
                      "ON CONFLICT(username) DO UPDATE SET kode=excluded.kode, "
                      "pad_code=excluded.pad_code, label=excluded.label, status_akun=excluded.status_akun",
                      (username, kode, pad_code, label, status_akun))

    def add_video(self, video_id, master_path, checksum=None):
        with db.tx(self.db_path) as c:
            c.execute("INSERT OR REPLACE INTO videos(id,master_path,checksum) VALUES(?,?,?)",
                      (video_id, master_path, checksum))

    def list_accounts(self):
        import re
        with db.read(self.db_path) as c:
            rows = [dict(r) for r in c.execute(
                "SELECT a.username, a.kode, a.pad_code, COALESCE(a.label, d.label) AS label, a.status_akun, d.current_username "
                "FROM accounts a JOIN devices d ON d.pad_code=a.pad_code")]
            def _num(x):
                m = re.search(r'\d+', x.get('kode', ''))
                return (0, int(m.group())) if m else (1, x.get('kode', ''))
            rows.sort(key=_num)
            return rows

    def list_videos(self):
        with db.read(self.db_path) as c:
            return [dict(r) for r in c.execute("SELECT * FROM videos ORDER BY id")]

    def create_tasks_batch(self, usernames, video_id, batch="", caption=None, product_link=None, prompt=None):
        created, errors = [], []
        for u in usernames:
            try:
                created.append(self.create_task(u, video_id, batch, caption, product_link=product_link, prompt=prompt))
            except (GuardError, DuplicateTask) as e:
                errors.append({"username": u, "error": str(e)})
        return {"created": created, "errors": errors}

    # ---------- tugas ----------
    def create_task(self, username, video_id, batch="", caption=None, actor="operator", product_link=None, prompt=None):
        username = norm_username(username)
        with db.tx(self.db_path) as c:
            a = c.execute("SELECT * FROM accounts WHERE username=?", (username,)).fetchone()
            if not a:
                raise GuardError(f"akun {username} tidak ada / pemetaan perangkat tidak ditemukan")
            if not c.execute("SELECT 1 FROM videos WHERE id=?", (video_id,)).fetchone():
                raise GuardError(f"video {video_id} tidak terdaftar")
            now = self._now()
            try:
                cur = c.execute(
                    "INSERT INTO tasks(username,pad_code,video_id,batch,caption,product_link,prompt,status,created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (username, a["pad_code"], video_id, batch, caption, product_link, prompt, QUEUED, now))
            except sqlite3.IntegrityError:
                raise DuplicateTask("tugas untuk (akun, video, batch) ini sudah ada")
            tid = cur.lastrowid
            self._history(c, tid, None, QUEUED, actor, "dibuat")
            return self._get(c, tid)

    def _history(self, c, task_id, frm, to, actor, reason):
        c.execute("INSERT INTO task_history(task_id,from_status,to_status,actor,reason,at) "
                  "VALUES(?,?,?,?,?,?)", (task_id, frm, to, actor, reason or "", self._now()))

    def _rate_ok(self, c, username, exclude_id):
        now = self.clock()
        rows = c.execute(
            "SELECT started_at FROM tasks WHERE username=? AND id!=? AND started_at IS NOT NULL "
            "AND status IN ('PREPARING','NEEDS_OPERATOR','PAUSED','REVIEW_REQUIRED','VERIFIED')",
            (username, exclude_id)).fetchall()
        tz_delta = timedelta(hours=self.cfg.timezone_offset_hours)
        today = (now + tz_delta).strftime("%Y-%m-%d")
        starts_raw = [_parse(r["started_at"]) for r in rows]
        starts_local = [s + tz_delta for s in starts_raw]
        if sum(1 for s in starts_local if s.strftime("%Y-%m-%d") == today) >= self.cfg.max_posts_per_day:
            return False
        gap = timedelta(seconds=self.cfg.min_gap_sec) if self.cfg.min_gap_sec is not None else timedelta(seconds=int(self.cfg.min_gap_min * 60))
        if starts_raw and now - max(starts_raw) < gap:
            return False
        return True

    def start_next(self, pad_code=None, actor="worker"):
        """Ambil tugas QUEUED berikutnya, kunci perangkat, ubah ke PREPARING."""
        with db.tx(self.db_path) as c:
            locked = {r["pad_code"] for r in c.execute("SELECT pad_code FROM device_locks")}
            blocked_users = {r["username"] for r in c.execute(
                "SELECT username FROM tasks WHERE status=?", (REVIEW_REQUIRED,))}
            current = {r["pad_code"]: r["current_username"] for r in c.execute("SELECT * FROM devices")}
            sql = "SELECT * FROM tasks WHERE status=?"
            args = [QUEUED]
            if pad_code:
                sql += " AND pad_code=?"
                args.append(pad_code)
            rows = [dict(r) for r in c.execute(sql, args)]
            # utamakan shop yang sedang aktif di device supaya pergantian shop minimal
            rows.sort(key=lambda t: (0 if current.get(t["pad_code"]) == t["username"] else 1, t["id"]))
            for t in rows:
                if t["pad_code"] in locked or t["username"] in blocked_users:
                    continue
                if not self._rate_ok(c, t["username"], t["id"]):
                    continue
                now = self._now()
                c.execute("INSERT INTO device_locks(pad_code,task_id,locked_at) VALUES(?,?,?)",
                          (t["pad_code"], t["id"], now))
                c.execute("UPDATE tasks SET status=?, started_at=?, finished_at=NULL WHERE id=?",
                          (PREPARING, now, t["id"]))
                self._history(c, t["id"], QUEUED, PREPARING, actor, "diambil worker")
                return self._get(c, t["id"])
        return None

    def start_task(self, task_id, actor="operator", force=True):
        """Mulai tugas spesifik: kunci perangkat, ubah status ke PREPARING."""
        with db.tx(self.db_path) as c:
            t = self._get(c, task_id)
            if t["status"] != QUEUED:
                raise GuardError(f"tugas #{task_id} berstatus {t['status']}, bukan QUEUED")
            locked = {r["pad_code"] for r in c.execute("SELECT pad_code FROM device_locks")}
            if t["pad_code"] in locked:
                raise GuardError(f"perangkat {t['pad_code']} sedang dipakai tugas lain")
            if not force and not self._rate_ok(c, t["username"], t["id"]):
                raise GuardError(f"jeda waktu posting untuk @{t['username']} belum terpenuhi")
            now = self._now()
            c.execute("INSERT INTO device_locks(pad_code,task_id,locked_at) VALUES(?,?,?)",
                      (t["pad_code"], t["id"], now))
            c.execute("UPDATE tasks SET status=?, started_at=?, finished_at=NULL WHERE id=?",
                      (PREPARING, now, t["id"]))
            self._history(c, t["id"], QUEUED, PREPARING, actor, "dimulai operator")
            return self._get(c, t["id"])

    def count_pending_tasks(self, pad_code=None):
        with db.read(self.db_path) as c:
            sql = "SELECT COUNT(*) as cnt FROM tasks WHERE status IN (?, ?)"
            args = [QUEUED, NEEDS_OPERATOR]
            if pad_code:
                sql += " AND pad_code=?"
                args.append(pad_code)
            row = c.execute(sql, args).fetchone()
            return row["cnt"] if row else 0

    def get_next_needs_operator(self, pad_code=None):
        with db.read(self.db_path) as c:
            sql = "SELECT * FROM tasks WHERE status=?"
            args = [NEEDS_OPERATOR]
            if pad_code:
                sql += " AND pad_code=?"
                args.append(pad_code)
            row = c.execute(sql + " ORDER BY id LIMIT 1", args).fetchone()
            return dict(row) if row else None

    def transition(self, task_id, to, actor, reason="", *, confirmed_username=None,
                   evidence=None, video_post_id=None):
        if to == PREPARING:
            raise GuardError("PREPARING hanya lewat start_next()")
        with db.tx(self.db_path) as c:
            t = self._get(c, task_id)
            return self._do_transition(c, t, to, actor, reason,
                                       confirmed_username=confirmed_username,
                                       evidence=evidence, video_post_id=video_post_id)

    def _do_transition(self, c, t, to, actor, reason="", *, confirmed_username=None,
                       evidence=None, video_post_id=None, extra=None):
        frm = t["status"]
        if (frm, to) not in TRANSITIONS:
            raise InvalidTransition(f"{frm} -> {to} tidak diizinkan")
        if frm == PAUSED and to in (QUEUED, NEEDS_OPERATOR) and to != t["prev_status"]:
            raise InvalidTransition(f"PAUSED hanya bisa lanjut ke {t['prev_status']}")
        now = self._now()
        f = {"status": to}
        if reason:
            f["note"] = reason
        if to == PAUSED:
            f["prev_status"] = frm
        if to == NEEDS_OPERATOR:
            f["needs_operator_since"] = now
        if (frm, to) == (NEEDS_OPERATOR, VERIFIED):
            if norm_username(confirmed_username) != t["username"]:
                raise GuardError("konfirmasi USERNAME tidak cocok dengan akun tugas")
            if not evidence:
                raise GuardError("bukti posting wajib diisi")
        if (frm, to) == (REVIEW_REQUIRED, VERIFIED):
            if not evidence or not reason:
                raise GuardError("bukti dan catatan wajib saat menyelesaikan REVIEW_REQUIRED")
        if (frm, to) in ((REVIEW_REQUIRED, FAILED), (NEEDS_OPERATOR, CANCELLED)) and not reason:
            raise GuardError("catatan wajib diisi")
        if (frm, to) == (FAILED, QUEUED):
            if t["cleanup_status"] == "PENDING":
                raise GuardError("pembersihan file sebelumnya belum selesai")
            dup = c.execute(
                "SELECT id FROM tasks WHERE username=? AND video_id=? AND id!=? "
                "AND status IN ('REVIEW_REQUIRED','VERIFIED')",
                (t["username"], t["video_id"], t["id"])).fetchone()
            if dup:
                raise GuardError(f"tugas {dup['id']} untuk akun+video yang sama masih "
                                 "REVIEW_REQUIRED/VERIFIED; retry diblokir")
            f["attempt"] = t["attempt"] + 1
            f["finished_at"] = None
        if to == VERIFIED:
            f.update(verified_at=now, finished_at=now, evidence=evidence)
            if video_post_id:
                f["video_post_id"] = video_post_id
            f["cleanup_status"] = "PENDING" if t["device_file_path"] else "SKIPPED"
            f["cleanup_attempts"] = 0
        if to in (FAILED, CANCELLED):
            f["finished_at"] = now
            if to == CANCELLED and t["device_file_path"] and t["cleanup_status"] in ("NONE", "FAILED"):
                f["cleanup_status"] = "PENDING"
                f["cleanup_attempts"] = 0
        if extra:
            f.update(extra)
        sets = ", ".join(f"{k}=?" for k in f)
        c.execute(f"UPDATE tasks SET {sets} WHERE id=?", [*f.values(), t["id"]])
        self._history(c, t["id"], frm, to, actor, reason)
        if to in TERMINAL and f.get("cleanup_status", t["cleanup_status"]) != "PENDING":
            c.execute("DELETE FROM device_locks WHERE task_id=?", (t["id"],))
        return self._get(c, t["id"])

    # ---------- persiapan (kirim video ke device) ----------
    def prepare(self, vmos, task_id, actor="worker"):
        t = self.get_task(task_id)
        if t["status"] != PREPARING:
            raise GuardError("prepare hanya untuk tugas PREPARING")
        with db.read(self.db_path) as c:
            v = c.execute("SELECT * FROM videos WHERE id=?", (t["video_id"],)).fetchone()
        master_file = v["master_path"]
        if master_file.startswith("http://") or master_file.startswith("https://"):
            from .shopee_scraper import download_video_to_cache
            cache_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache", "videos")
            master_file = download_video_to_cache(master_file, cache_dir)
        remote = f"{self.cfg.device_dir}/task_{t['id']}/{os.path.basename(master_file)}"
        try:
            if not os.path.isfile(master_file):
                raise FileNotFoundError("master video tidak ditemukan di PC")
            expected = os.path.getsize(master_file)
            try:
                vmos.push_file(t["pad_code"], master_file, remote)
            except Exception:
                self._fail_prepare(task_id, actor, "push gagal", remote, pushed=True)
                raise
            size = vmos.file_size(t["pad_code"], remote)
            if size != expected:
                self._fail_prepare(task_id, actor, "ukuran file di device tidak cocok",
                                   remote, pushed=True)
                raise GuardError("verifikasi file di device gagal")

            # Rescan galeri & pastikan video muncul di DCIM/Camera Shopee (khusus adapter nyata)
            if hasattr(vmos, "_run_adb"):
                try:
                    target = vmos._get_target_serial(t["pad_code"])
                    dcim_remote = f"/sdcard/DCIM/Camera/{os.path.basename(master_file)}"
                    vmos._run_adb(["-s", target, "shell", "mkdir", "-p", "/sdcard/DCIM/Camera"])
                    vmos._run_adb(["-s", target, "shell", "cp", remote, dcim_remote])
                    vmos._run_adb(["-s", target, "shell", "am", "broadcast", "-a",
                                   "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
                                   "-d", f"file://{dcim_remote}"])
                    # Buka aplikasi Shopee di layar VMOS
                    vmos._run_adb(["-s", target, "shell", "monkey", "-p", "com.shopee.my",
                                   "-c", "android.intent.category.LAUNCHER", "1"])
                except Exception as e:
                    _log.warning(f"Rescan media / auto launch notice: {e}")
        except (FileNotFoundError,) as e:
            self._fail_prepare(task_id, actor, str(e), None, pushed=False)
            raise
        with db.tx(self.db_path) as c:
            t = self._get(c, task_id)
            res = self._do_transition(c, t, NEEDS_OPERATOR, actor, "materi siap",
                                      extra={"device_file_path": remote,
                                             "cleanup_status": "NONE", "cleanup_attempts": 0})
            c.execute("UPDATE devices SET current_username=? WHERE pad_code=?",
                      (t["username"], t["pad_code"]))
            return res

    def _fail_prepare(self, task_id, actor, reason, remote, pushed):
        extra = {}
        if pushed:
            extra = {"device_file_path": remote, "cleanup_status": "PENDING", "cleanup_attempts": 0}
        with db.tx(self.db_path) as c:
            t = self._get(c, task_id)
            if t["status"] == PREPARING:
                self._do_transition(c, t, FAILED, actor, reason, extra=extra)

    # ---------- pemulihan & timeout ----------
    def recover_on_startup(self):
        moved = []
        with db.tx(self.db_path) as c:
            rows = [dict(r) for r in c.execute(
                "SELECT * FROM tasks WHERE status IN (?,?) OR (status=? AND prev_status=?)",
                (PREPARING, NEEDS_OPERATOR, PAUSED, NEEDS_OPERATOR))]
            for t in rows:
                self._do_transition(c, t, REVIEW_REQUIRED, "system", "aplikasi restart saat tugas berjalan")
                moved.append(t["id"])
            # Bersihkan lock perangkat yang tersisa dari sesi sebelumnya agar perangkat tidak terkunci semu
            c.execute("DELETE FROM device_locks")
        return moved

    def sweep_timeouts(self):
        limit = self.clock() - timedelta(minutes=self.cfg.operator_timeout_min)
        moved = []
        with db.tx(self.db_path) as c:
            for t in [dict(r) for r in c.execute(
                    "SELECT * FROM tasks WHERE status=?", (NEEDS_OPERATOR,))]:
                if t["needs_operator_since"] and _parse(t["needs_operator_since"]) <= limit:
                    self._do_transition(c, t, REVIEW_REQUIRED, "system", "timeout menunggu operator")
                    moved.append(t["id"])
        return moved

    # ---------- pembersihan video di device & cache lokal ----------
    def prune_local_cache(self, max_age_days: int = 2) -> dict:
        """Bersihkan file video lokal di folder cache yang sudah melebihi batas hari."""
        cache_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache", "videos")
        if not os.path.isdir(cache_dir):
            return {"deleted": 0, "freed_bytes": 0}

        now_ts = time.time()
        max_age_sec = max_age_days * 86400
        deleted_count = 0
        freed_bytes = 0

        for fname in os.listdir(cache_dir):
            if not fname.endswith(".mp4"):
                continue
            fpath = os.path.join(cache_dir, fname)
            try:
                stat = os.stat(fpath)
                if now_ts - stat.st_mtime > max_age_sec:
                    size = stat.st_size
                    os.remove(fpath)
                    deleted_count += 1
                    freed_bytes += size
            except Exception:
                pass

        return {"deleted": deleted_count, "freed_bytes": freed_bytes}

    def clear_all_video_cache(self) -> dict:
        """Bersihkan seluruh file video di cache lokal."""
        cache_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache", "videos")
        if not os.path.isdir(cache_dir):
            return {"deleted": 0, "freed_bytes": 0}

        deleted_count = 0
        freed_bytes = 0
        for fname in os.listdir(cache_dir):
            if not fname.endswith(".mp4"):
                continue
            fpath = os.path.join(cache_dir, fname)
            try:
                stat = os.stat(fpath)
                size = stat.st_size
                os.remove(fpath)
                deleted_count += 1
                freed_bytes += size
            except Exception:
                pass
        return {"deleted": deleted_count, "freed_bytes": freed_bytes}

    def get_storage_stats(self) -> dict:
        """Dapatkan statistik ukuran database SQLite, folder cache, dan log."""
        db_size = 0
        if os.path.isfile(self.db_path):
            try:
                db_size = os.path.getsize(self.db_path)
                wal = self.db_path + "-wal"
                shm = self.db_path + "-shm"
                if os.path.isfile(wal):
                    db_size += os.path.getsize(wal)
                if os.path.isfile(shm):
                    db_size += os.path.getsize(shm)
            except Exception:
                pass

        cache_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache", "videos")
        cache_size = 0
        cache_files = 0
        if os.path.isdir(cache_dir):
            try:
                for fname in os.listdir(cache_dir):
                    fpath = os.path.join(cache_dir, fname)
                    if os.path.isfile(fpath):
                        cache_size += os.path.getsize(fpath)
                        cache_files += 1
            except Exception:
                pass

        logs_dir = os.path.join(os.path.dirname(os.path.abspath(self.db_path)), "logs")
        log_size = 0
        if os.path.isdir(logs_dir):
            try:
                for fname in os.listdir(logs_dir):
                    fpath = os.path.join(logs_dir, fname)
                    if os.path.isfile(fpath):
                        log_size += os.path.getsize(fpath)
            except Exception:
                pass

        return {
            "db_path": self.db_path,
            "db_size_bytes": db_size,
            "cache_dir": cache_dir,
            "cache_size_bytes": cache_size,
            "cache_files_count": cache_files,
            "logs_dir": logs_dir,
            "log_size_bytes": log_size
        }

    # ---------- pembersihan video di device ----------
    def request_cleanup(self, task_id, actor="operator"):
        with db.tx(self.db_path) as c:
            t = self._get(c, task_id)
            if t["status"] not in (FAILED, CANCELLED):
                raise GuardError("permintaan manual hanya untuk FAILED/CANCELLED")
            if not t["device_file_path"]:
                raise GuardError("tidak ada file di device untuk tugas ini")
            if t["cleanup_status"] in ("NONE", "FAILED"):
                c.execute("UPDATE tasks SET cleanup_status='PENDING', cleanup_attempts=0 WHERE id=?",
                          (task_id,))
                self._history(c, task_id, t["status"], t["status"], actor, "minta pembersihan")
            return self._get(c, task_id)

    def _safe_path(self, t):
        p = t["device_file_path"] or ""
        prefix = f"{self.cfg.device_dir}/task_{t['id']}/"
        return p.startswith(prefix) and ".." not in p and len(p) > len(prefix)

    def force_unlock(self, pad_code):
        """Lepaskan kunci perangkat paksa jika terjadi kegagalan agar antrean tidak macet."""
        with db.tx(self.db_path) as c:
            c.execute("DELETE FROM device_locks WHERE pad_code=?", (pad_code,))

    def run_cleanup(self, vmos, force=False):
        now = self.clock()
        with db.read(self.db_path) as c:
            rows = [dict(r) for r in c.execute(
                "SELECT * FROM tasks WHERE cleanup_status='PENDING' AND device_file_path IS NOT NULL "
                "AND status IN (?,?,?) ORDER BY id", (VERIFIED, FAILED, CANCELLED))]
        results = []
        for t in rows:
            if not force and t["status"] == VERIFIED and t["verified_at"]:
                if _parse(t["verified_at"]) + timedelta(seconds=self.cfg.cleanup_delay_s) > now:
                    results.append((t["id"], "WAIT"))
                    continue
            results.append((t["id"], self._cleanup_one(vmos, t)))
        return results

    def _cleanup_one(self, vmos, t):
        path = t["device_file_path"]
        if not self._safe_path(t):
            self._finish_cleanup(t, "FAILED", "path tidak aman, tidak dihapus")
            return "FAILED"
        detail = ""
        gone = False
        try:
            vmos.delete_file(t["pad_code"], path)
            # Bersihkan juga salinan galeri di /sdcard/DCIM/Camera/ jika ada
            if hasattr(vmos, "_run_adb"):
                try:
                    target = vmos._get_target_serial(t["pad_code"])
                    fname = os.path.basename(path)
                    dcim_path = f"/sdcard/DCIM/Camera/{fname}"
                    vmos._run_adb(["-s", target, "shell", f"rm -f '{dcim_path}'"])
                    vmos._run_adb(["-s", target, "shell", "am", "broadcast", "-a",
                                   "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
                                   "-d", f"file://{dcim_path}"])
                except Exception:
                    pass
            try:
                vmos.rescan_media(t["pad_code"], path)
            except Exception as e:  # best-effort
                detail = f"rescan media gagal: {type(e).__name__}"
            gone = vmos.file_size(t["pad_code"], path) is None
            if not gone:
                detail = "file masih ada setelah perintah hapus"
        except NotImplementedError:
            return "ADAPTER_NOT_READY"
        except Exception as e:
            detail = f"{type(e).__name__}: {str(e)[:150]}"
        if gone:
            self._finish_cleanup(t, "DONE", detail)
            return "DONE"
        attempts = t["cleanup_attempts"] + 1
        if attempts >= self.cfg.cleanup_max_attempts:
            self._finish_cleanup(t, "FAILED", detail, attempts)
            return "FAILED"
        with db.tx(self.db_path) as c:
            c.execute("UPDATE tasks SET cleanup_attempts=? WHERE id=?", (attempts, t["id"]))
            self._clog(c, t, "RETRY", detail)
        return "RETRY"

    def _clog(self, c, t, result, detail):
        c.execute("INSERT INTO cleanup_log(task_id,pad_code,path,result,detail,at) VALUES(?,?,?,?,?,?)",
                  (t["id"], t["pad_code"], t["device_file_path"], result, detail, self._now()))

    def _finish_cleanup(self, t, status, detail, attempts=None):
        with db.tx(self.db_path) as c:
            if attempts is None:
                attempts = t["cleanup_attempts"]
            c.execute("UPDATE tasks SET cleanup_status=?, cleanup_attempts=? WHERE id=?",
                      (status, attempts, t["id"]))
            self._clog(c, t, status, detail)
            c.execute("DELETE FROM device_locks WHERE task_id=?", (t["id"],))

    # ---------- laporan ----------
    def report(self):
        with db.read(self.db_path) as c:
            by_status = {s: 0 for s in ALL}
            for r in c.execute("SELECT status, COUNT(*) n FROM tasks GROUP BY status"):
                by_status[r["status"]] = r["n"]
            cleanup = [dict(r) for r in c.execute(
                "SELECT pad_code, cleanup_status, COUNT(*) n FROM tasks "
                "WHERE cleanup_status IN ('PENDING','FAILED') GROUP BY pad_code, cleanup_status")]
            return {"by_status": by_status, "cleanup_attention": cleanup}
