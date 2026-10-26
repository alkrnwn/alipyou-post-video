import asyncio
import dataclasses
import hmac
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import sheets
from .service import (Config, DuplicateTask, GuardError, InvalidTransition,
                      NotFound, Service)
from .states import CANCELLED, FAILED, NEEDS_OPERATOR, PREPARING, QUEUED, VERIFIED
from .vmos import FakeVmos, HttpVmosAdapter

STATIC = Path(__file__).parent / "static"


class TaskIn(BaseModel):
    username: str
    video_id: Optional[str] = None
    video_url: Optional[str] = None
    batch: str = ""
    caption: Optional[str] = None
    product_link: Optional[str] = None
    prompt: Optional[str] = None


class ShopeeExtractIn(BaseModel):
    url: str
    category: Optional[str] = "Random"
    model: Optional[str] = None


class DownloadImageIn(BaseModel):
    url: str
    filename: Optional[str] = None
    open_folder: bool = True


class OperatorTaskIn(BaseModel):
    username: str
    video_url: str
    batch: str = ""
    caption: Optional[str] = None
    product_link: Optional[str] = None
    prompt: Optional[str] = None
    auto_start: bool = False


class VideoIn(BaseModel):
    id: str
    master_path: str
    checksum: Optional[str] = None


class TransitionIn(BaseModel):
    to: str
    actor: str = "operator"
    reason: str = ""
    confirmed_username: Optional[str] = None
    evidence: Optional[str] = None
    video_post_id: Optional[str] = None


class SyncCsvIn(BaseModel):
    path: str


class SyncUrlIn(BaseModel):
    url: str
    row_range: Optional[str] = None
    clear_previous: bool = False
    filter_active_only: bool = False


class SyncSheetsIn(BaseModel):
    spreadsheet_id: str
    range_a1: str = "A:D"
    service_account_file: str


class BatchIn(BaseModel):
    usernames: List[str]
    video_id: str
    batch: str = ""
    caption: Optional[str] = None


class StartIn(BaseModel):
    pad_code: Optional[str] = None


class VmosConfigIn(BaseModel):
    access_key: str
    secret_key: str
    base_url: Optional[str] = "https://api.vmoscloud.com"


class VmosTestIn(BaseModel):
    access_key: Optional[str] = None
    secret_key: Optional[str] = None
    base_url: Optional[str] = None



def create_app(db_path=None, config=None, vmos=None, background=True):
    svc = Service(db_path or os.environ.get("AUTOPOST_DB", "autopost.db"), config)
    vm = vmos or (FakeVmos() if os.environ.get("AUTOPOST_DRYRUN") == "1" else HttpVmosAdapter())

    # Muat kredensial VMOS tersimpan dari DB bila ada
    saved_ak = svc.get_setting("vmos_access_key")
    saved_sk = svc.get_setting("vmos_secret_key")
    saved_burl = svc.get_setting("vmos_base_url")
    if saved_ak and saved_sk:
        if hasattr(vm, "update_credentials"):
            vm.update_credentials(saved_ak, saved_sk, saved_burl)

    token = os.environ.get("AUTOPOST_TOKEN", "")

    # Inisialisasi logging terstruktur berotasi ke file
    db_dir = os.path.dirname(os.path.abspath(svc.db_path))
    logs_dir = os.path.join(db_dir, "logs")
    log_file = os.path.join(logs_dir, "autopost.log")
    try:
        os.makedirs(logs_dir, exist_ok=True)
        import logging
        from logging.handlers import RotatingFileHandler
        root_logger = logging.getLogger()
        if not any(isinstance(h, RotatingFileHandler) for h in root_logger.handlers):
            rfh = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
            rfh.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s"))
            root_logger.addHandler(rfh)
            if root_logger.level > logging.INFO:
                root_logger.setLevel(logging.INFO)
    except Exception:
        pass

    async def maintenance_loop():
        while True:
            try:
                await asyncio.to_thread(svc.sweep_timeouts)
                await asyncio.to_thread(svc.prune_local_cache, 2)
                if vm.ready:
                    await asyncio.to_thread(svc.run_cleanup, vm)
            except Exception:
                pass  # jangan matikan loop; detail ada di cleanup_log/riwayat
            await asyncio.sleep(30)

    @asynccontextmanager
    async def lifespan(app):
        svc.recover_on_startup()
        task = asyncio.create_task(maintenance_loop()) if background else None
        yield
        if task:
            task.cancel()

    app = FastAPI(title="Shopee Video VMOS - antrean", lifespan=lifespan)

    @app.middleware("http")
    async def security(request: Request, call_next):
        host = request.headers.get("host", "").rsplit(":", 1)[0]
        if host not in ("127.0.0.1", "localhost"):
            return JSONResponse({"detail": "host ditolak"}, status_code=403)
        p = request.url.path
        if token and not (p == "/" or p.startswith("/static/")):
            if not hmac.compare_digest(request.headers.get("x-token", ""), token):
                return JSONResponse({"detail": "token salah"}, status_code=403)
        response = await call_next(request)
        if p == "/" or p.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

    def guard(fn):
        try:
            return fn()
        except NotFound as e:
            raise HTTPException(404, str(e))
        except DuplicateTask as e:
            raise HTTPException(409, str(e))
        except (InvalidTransition, GuardError) as e:
            raise HTTPException(409, str(e))
        except NotImplementedError as e:
            raise HTTPException(501, str(e))
        except Exception as e:
            raise HTTPException(500, f"{type(e).__name__}: {str(e)[:200]}")

    @app.post("/sync/csv")
    def sync_csv(body: SyncCsvIn):
        return sheets.sync(svc, sheets.load_csv(body.path))

    @app.post("/sync/url")
    def sync_url(body: SyncUrlIn):
        try:
            start_row, end_row = sheets.parse_row_range(body.row_range)
            rows = sheets.load_google_sheet_url(body.url, start_row=start_row, end_row=end_row)
            res = sheets.sync(
                svc,
                rows,
                replace=True,
                clear_old_tasks=body.clear_previous,
                filter_active_only=body.filter_active_only,
            )
            res["range"] = f"Baris {start_row or 2} - {end_row or 'akhir'}" if (start_row or end_row) else "Semua baris"
            return res
        except Exception as e:
            raise HTTPException(400, str(e))

    @app.post("/api/reset-all")
    def reset_all():
        return svc.reset_all_data()

    @app.post("/sync/sheets")
    def sync_sheets(body: SyncSheetsIn):
        try:
            rows = sheets.load_google_sheet(body.spreadsheet_id, body.range_a1, body.service_account_file)
            return sheets.sync(svc, rows)
        except (ImportError, ModuleNotFoundError) as e:
            raise HTTPException(
                400,
                f"Modul Google API belum terpasang ({getattr(e, 'name', 'google')}). "
                "Jalankan: pip install google-api-python-client google-auth"
            )
        except Exception as e:
            raise HTTPException(400, f"Gagal membaca Google Sheets: {e}")

    @app.post("/videos")
    def add_video(body: VideoIn):
        svc.add_video(body.id, body.master_path, body.checksum)
        return {"ok": True}

    @app.post("/tasks")
    def create_task(body: TaskIn):
        video_id = body.video_id
        if not video_id and body.video_url:
            import hashlib
            vid_hash = hashlib.md5(body.video_url.encode()).hexdigest()[:10]
            video_id = f"flow_{vid_hash}"
            svc.add_video(video_id, body.video_url)
        elif not video_id:
            raise HTTPException(400, "video_id atau video_url wajib diisi")
        return guard(lambda: svc.create_task(
            body.username, video_id, body.batch, body.caption,
            product_link=body.product_link, prompt=body.prompt
        ))

    @app.post("/api/shopee/extract")
    def shopee_extract(body: ShopeeExtractIn):
        try:
            from .shopee_scraper import extract_product_details
            return extract_product_details(body.url, category=body.category or "Random")
        except Exception as e:
            raise HTTPException(400, f"Gagal mengekstrak produk: {e}")

    @app.post("/api/shopee/download-image")
    def shopee_download_image(body: DownloadImageIn):
        try:
            from .shopee_scraper import download_image_to_pc
            return download_image_to_pc(body.url, filename=body.filename, open_folder=body.open_folder)
        except Exception as e:
            raise HTTPException(400, f"Gagal mengunduh foto: {e}")

    @app.get("/api/shopee/image-proxy")
    def shopee_image_proxy(url: str):
        import httpx
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Referer": "https://shopee.co.id/"
            }
            with httpx.Client(follow_redirects=True, timeout=15.0) as client:
                r = client.get(url, headers=headers)
                return Response(
                    content=r.content,
                    media_type=r.headers.get("content-type", "image/jpeg"),
                    headers={"Content-Disposition": 'attachment; filename="foto_produk.jpg"'}
                )
        except Exception as e:
            raise HTTPException(400, f"Gagal proxy gambar: {e}")

    @app.post("/api/tasks/operator")
    def create_operator_task(body: OperatorTaskIn):
        import hashlib, time
        vid_hash = hashlib.md5(body.video_url.strip().encode()).hexdigest()[:10]
        video_id = f"flow_{vid_hash}"
        svc.add_video(video_id, body.video_url.strip())
        
        # Batch operator: gunakan batch unik jika tidak disediakan agar akun yang sama bisa membuat tugas berulang kali
        ts = int(time.time())
        batch = body.batch.strip() if body.batch else f"op_{ts}"
        try:
            task = svc.create_task(
                body.username, video_id, batch, body.caption,
                product_link=body.product_link, prompt=body.prompt
            )
        except DuplicateTask:
            ms_batch = f"{batch}_{int(time.time() * 1000)}"
            task = svc.create_task(
                body.username, video_id, ms_batch, body.caption,
                product_link=body.product_link, prompt=body.prompt
            )
        return {"ok": True, "task": task}

    @app.get("/tasks")
    def list_tasks(status: Optional[str] = None):
        return svc.list_tasks(status)

    @app.get("/tasks/{task_id}/history")
    def history(task_id: int):
        return svc.history(task_id)

    @app.get("/api/tasks/{task_id}/screenshot")
    def get_task_screenshot(task_id: int):
        try:
            task = svc.get_task(task_id)
        except NotFound:
            raise HTTPException(404, "Tugas tidak ditemukan")
        if not task:
            raise HTTPException(404, "Tugas tidak ditemukan")
        pad_code = task.get("pad_code") or ""
        username = task.get("username") or ""
        status = task.get("status") or ""

        if hasattr(vm, "get_screenshot") and pad_code:
            png = vm.get_screenshot(pad_code)
            if png:
                return Response(content=png, media_type="image/png")

        status_color = "#f59e0b" if status in ("NEEDS_OPERATOR", "REVIEW_REQUIRED") else "#10b981"
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="220" height="390" viewBox="0 0 220 390">'
            f'<rect width="220" height="390" rx="20" fill="#0f172a"/>'
            f'<rect x="8" y="8" width="204" height="374" rx="14" fill="#1e293b"/>'
            f'<circle cx="110" cy="20" r="4" fill="#475569"/>'
            f'<rect x="18" y="36" width="184" height="28" rx="6" fill="#334155"/>'
            f'<text x="110" y="55" font-family="sans-serif" font-size="11" font-weight="bold" text-anchor="middle" fill="#cbd5e1">VMOS: {pad_code}</text>'
            f'<circle cx="110" cy="140" r="32" fill="{status_color}" fill-opacity="0.15"/>'
            f'<text x="110" y="148" font-family="sans-serif" font-size="28" text-anchor="middle" fill="{status_color}">📱</text>'
            f'<text x="110" y="200" font-family="sans-serif" font-size="13" font-weight="bold" text-anchor="middle" fill="#ffffff">@{username}</text>'
            f'<text x="110" y="222" font-family="sans-serif" font-size="11" text-anchor="middle" fill="{status_color}">Status: {status}</text>'
            f'<rect x="24" y="250" width="172" height="42" rx="6" fill="#0f172a" fill-opacity="0.6"/>'
            f'<text x="110" y="268" font-family="sans-serif" font-size="10" text-anchor="middle" fill="#94a3b8">Emulator Layar Aktif</text>'
            f'<text x="110" y="282" font-family="sans-serif" font-size="9" text-anchor="middle" fill="#64748b">Tangkapan layar emulator VMOS</text>'
            f'<line x1="85" y1="365" x2="135" y2="365" stroke="#475569" stroke-width="3" stroke-linecap="round"/>'
            f'</svg>'
        )
        return Response(content=svg.encode("utf-8"), media_type="image/svg+xml")

    @app.post("/queue/start-next")
    def start_next(body: StartIn):
        if not vm.ready:
            raise HTTPException(409, "Adapter VMOS belum siap. Isi app/vmos.py, atau set "
                                     "AUTOPOST_DRYRUN=1 untuk uji tanpa VMOS.")
        return svc.start_next(body.pad_code) or {"task": None}

    @app.post("/queue/process-next")
    def process_next(body: Optional[StartIn] = None):
        """Ambil tugas antrean berikutnya, unduh/siapkan video ke VMOS, dan jalankan auto-post sampai tuntas."""
        if not vm.ready:
            raise HTTPException(409, "Adapter VMOS belum siap.")
        pad_code = body.pad_code if body else None

        # 1. Cek apakah ada tugas yang sudah di tahap NEEDS_OPERATOR
        task_needs = svc.get_next_needs_operator(pad_code)
        if task_needs:
            task_id = task_needs["id"]
            username = task_needs["username"]
            target_pad = task_needs["pad_code"]
            from .auto_poster import ShopeeAutoPoster
            poster = ShopeeAutoPoster(vm, svc)
            try:
                poster.run_task(task_id)
                has_more = svc.count_pending_tasks(pad_code) > 0
                return {
                    "ok": True,
                    "task_id": task_id,
                    "username": username,
                    "pad_code": target_pad,
                    "status": "VERIFIED",
                    "has_more": has_more
                }
            except Exception as e:
                err_msg = str(e)
                try:
                    svc.transition(task_id, FAILED, actor="autoposter", reason=f"Gagal auto-post: {err_msg[:120]}")
                except Exception:
                    pass
                try:
                    svc.force_unlock(target_pad)
                except Exception:
                    pass
                has_more = svc.count_pending_tasks(pad_code) > 0
                return {
                    "ok": False,
                    "task_id": task_id,
                    "username": username,
                    "pad_code": target_pad,
                    "status": "FAILED",
                    "error": err_msg,
                    "has_more": has_more
                }

        # 2. Ambil tugas QUEUED berikutnya
        next_task = svc.start_next(pad_code)
        if not next_task or not next_task.get("id"):
            return {"ok": True, "task_id": None, "message": "Tidak ada tugas antrean tersisa", "has_more": False}

        task_id = next_task["id"]
        username = next_task["username"]
        target_pad = next_task["pad_code"]

        try:
            # 3. Siapkan video Flow -> download ke PC cache & push ke VMOS
            svc.prepare(vm, task_id)

            # 4. Jalankan auto-posting (buka Shopee -> switch shop -> post -> tonton 2 menit -> force close -> verified -> cleanup)
            from .auto_poster import ShopeeAutoPoster
            poster = ShopeeAutoPoster(vm, svc)
            poster.run_task(task_id)

            has_more = svc.count_pending_tasks(pad_code) > 0
            return {
                "ok": True,
                "task_id": task_id,
                "username": username,
                "pad_code": target_pad,
                "status": "VERIFIED",
                "has_more": has_more
            }
        except Exception as e:
            err_msg = str(e)
            try:
                svc.transition(task_id, FAILED, actor="autoposter", reason=f"Gagal proses: {err_msg[:120]}")
            except Exception:
                pass
            try:
                svc.force_unlock(target_pad)
            except Exception:
                pass
            has_more = svc.count_pending_tasks(pad_code) > 0
            return {
                "ok": False,
                "task_id": task_id,
                "username": username,
                "pad_code": target_pad,
                "status": "FAILED",
                "error": err_msg,
                "has_more": has_more
            }

    @app.get("/accounts")
    def accounts():
        return svc.list_accounts()

    @app.get("/videos")
    def videos():
        return svc.list_videos()

    @app.post("/tasks/batch")
    def tasks_batch(body: BatchIn):
        return guard(lambda: svc.create_tasks_batch(body.usernames, body.video_id,
                                                    body.batch, body.caption))

    @app.get("/config")
    def config_view():
        return {**dataclasses.asdict(svc.cfg), "adapter_ready": vm.ready,
                "dry_run": isinstance(vm, FakeVmos)}

    @app.get("/api/vmos/config")
    def get_vmos_config():
        ak = getattr(vm, "access_key", "") or svc.get_setting("vmos_access_key", "") or ""
        sk = getattr(vm, "secret_key", "") or svc.get_setting("vmos_secret_key", "") or ""
        burl = getattr(vm, "base_url", "https://api.vmoscloud.com") or svc.get_setting("vmos_base_url", "https://api.vmoscloud.com")
        connected_devs = []
        if hasattr(vm, "list_devices"):
            try:
                connected_devs = vm.list_devices()
            except Exception:
                pass
        return {
            "access_key": ak,
            "secret_key": sk,
            "base_url": burl,
            "ready": bool(vm.ready),
            "dry_run": isinstance(vm, FakeVmos),
            "adb_path": getattr(vm, "adb_path", "adb"),
            "connected_devices": connected_devs
        }

    @app.post("/api/vmos/test")
    def test_vmos_connection(body: VmosTestIn):
        if hasattr(vm, "test_connection"):
            return vm.test_connection(body.access_key, body.secret_key, body.base_url)
        return {"ok": True, "msg": "Adapter siap."}

    @app.post("/api/vmos/config")
    def set_vmos_config(body: VmosConfigIn):
        ak = body.access_key.strip()
        sk = body.secret_key.strip()
        burl = (body.base_url or "https://api.vmoscloud.com").strip().rstrip("/")
        if not ak or not sk:
            raise HTTPException(400, "Access Key ID dan Secret Access Key tidak boleh kosong.")

        if hasattr(vm, "update_credentials"):
            vm.update_credentials(ak, sk, burl)

        svc.set_setting("vmos_access_key", ak)
        svc.set_setting("vmos_secret_key", sk)
        svc.set_setting("vmos_base_url", burl)

        try:
            from .vmos import save_env_file
            save_env_file(ak, sk, burl)
        except Exception:
            pass

        return {
            "ok": True,
            "msg": "Pengaturan API VMOS berhasil disimpan dan diaktifkan!",
            "adapter_ready": vm.ready
        }


    @app.post("/tasks/{task_id}/start")
    def start_task(task_id: int):
        if not vm.ready:
            raise HTTPException(409, "Adapter VMOS belum siap.")
        return guard(lambda: svc.start_task(task_id, force=True))

    @app.post("/tasks/{task_id}/run-full")
    def run_task_full(task_id: int):
        """Jalankan tugas dari awal sampai selesai tanpa intervensi operator:
        Unduh video -> Push ke VMOS -> Buka Shopee -> Switch Shop -> Post -> Tonton 2 Menit -> Force Close -> Verified -> Cleanup.
        """
        if not vm.ready:
            raise HTTPException(409, "Adapter VMOS belum siap.")

        t = svc.get_task(task_id)
        pad_code = t.get("pad_code")
        username = t.get("username")
        status = t.get("status")

        try:
            # 1. Jika masih QUEUED, kunci perangkat dan pindah ke PREPARING
            if status == QUEUED:
                svc.start_task(task_id, force=True)
                status = PREPARING

            # 2. Jika PREPARING, unduh video Flow & push ke VMOS
            if status == PREPARING:
                svc.prepare(vm, task_id)
                status = NEEDS_OPERATOR

            # 3. Jalankan Auto-Poster end-to-end
            from .auto_poster import ShopeeAutoPoster
            poster = ShopeeAutoPoster(vm, svc)
            res = poster.run_task(task_id)

            if isinstance(res, dict) and res.get("status") == "cancelled":
                return {
                    "ok": False,
                    "task_id": task_id,
                    "username": username,
                    "pad_code": pad_code,
                    "status": "CANCELLED",
                    "message": f"Tugas #{task_id} dibatalkan oleh operator."
                }

            return {
                "ok": True,
                "task_id": task_id,
                "username": username,
                "pad_code": pad_code,
                "status": "VERIFIED",
                "message": f"Berhasil posting & verifikasi tugas #{task_id}"
            }
        except Exception as e:
            err_msg = str(e)
            if "dibatalkan" not in err_msg.lower():
                try:
                    svc.transition(task_id, FAILED, actor="autoposter", reason=f"Gagal: {err_msg[:120]}")
                except Exception:
                    pass
            if pad_code:
                svc.force_unlock(pad_code)
            raise HTTPException(500, f"Gagal memproses tugas #{task_id} (@{username}): {err_msg}")

    @app.post("/tasks/{task_id}/prepare")
    def prepare(task_id: int):
        return guard(lambda: svc.prepare(vm, task_id))

    @app.post("/tasks/{task_id}/auto-post")
    def auto_post(task_id: int):
        if not vm.ready:
            raise HTTPException(409, "Adapter VMOS belum siap.")
        from .auto_poster import ShopeeAutoPoster
        poster = ShopeeAutoPoster(vm, svc)
        try:
            return poster.run_task(task_id)
        except Exception as e:
            raise HTTPException(500, f"Gagal auto-post task #{task_id}: {e}")

    @app.post("/tasks/{task_id}/cancel")
    def cancel_task(task_id: int, body: Optional[dict] = None):
        reason = (body.get("reason") if body else None) or "Dibatalkan oleh operator"
        from .auto_poster import cancel_task_execution
        cancel_task_execution(task_id)

        t = svc.get_task(task_id)
        pad_code = t.get("pad_code")
        if pad_code and hasattr(vm, "_get_target_serial"):
            try:
                serial = vm._get_target_serial(pad_code)
                if serial:
                    vm._run_adb(["-s", serial, "shell", "am", "force-stop", "com.shopee.my"])
                    vm._run_adb(["-s", serial, "shell", "input", "keyevent", "3"])
            except Exception:
                pass

        res = guard(lambda: svc.transition(task_id, CANCELLED, "operator", reason))
        if pad_code:
            svc.force_unlock(pad_code)
        return {"ok": True, "task": res}

    @app.post("/tasks/{task_id}/transition")
    def transition(task_id: int, body: TransitionIn):
        if body.to == CANCELLED:
            from .auto_poster import cancel_task_execution
            cancel_task_execution(task_id)
            t = svc.get_task(task_id)
            pad_code = t.get("pad_code")
            if pad_code and hasattr(vm, "_get_target_serial"):
                try:
                    serial = vm._get_target_serial(pad_code)
                    if serial:
                        vm._run_adb(["-s", serial, "shell", "am", "force-stop", "com.shopee.my"])
                        vm._run_adb(["-s", serial, "shell", "input", "keyevent", "3"])
                except Exception:
                    pass
            res = guard(lambda: svc.transition(
                task_id, body.to, body.actor, body.reason or "Dibatalkan oleh operator",
                confirmed_username=body.confirmed_username,
                evidence=body.evidence, video_post_id=body.video_post_id))
            if pad_code:
                svc.force_unlock(pad_code)
            return res

        return guard(lambda: svc.transition(
            task_id, body.to, body.actor, body.reason,
            confirmed_username=body.confirmed_username,
            evidence=body.evidence, video_post_id=body.video_post_id))

    @app.post("/tasks/{task_id}/cleanup/request")
    def request_cleanup(task_id: int):
        return guard(lambda: svc.request_cleanup(task_id))

    @app.post("/maintenance/run")
    def maintenance():
        out = {"timeouts": svc.sweep_timeouts()}
        out["cleanup"] = svc.run_cleanup(vm) if vm.ready else "adapter belum siap"
        return out

    @app.get("/report")
    def report():
        return svc.report()

    @app.get("/api/storage/stats")
    def storage_stats():
        return svc.get_storage_stats()

    @app.post("/api/storage/clean-cache")
    def clean_cache():
        return svc.clear_all_video_cache()

    @app.get("/api/logs/recent")
    def recent_logs(limit: int = 150):
        if not os.path.isfile(log_file):
            return {"lines": [], "file": log_file}
        try:
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                all_lines = f.readlines()
            return {"lines": [line.strip() for line in all_lines[-limit:]], "file": log_file}
        except Exception as e:
            return {"lines": [f"Gagal membaca log: {e}"], "file": log_file}


    app.state.service = svc
    return app


def app_factory():
    return create_app()
