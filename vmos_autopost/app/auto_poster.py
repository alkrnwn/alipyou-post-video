"""Auto-posting engine for Shopee Video on VMOS Cloud Phone instances.

Handles end-to-end automation via ADB:
1. Connecting to the exact pad_code assigned to the account.
2. Switching to the account shop using the in-app Search bar (button_ACTION_SEARCH -> input text -> select shopCard).
3. Opening Shopee Video camera -> Library -> Video Tab -> Selecting latest video -> Next.
4. Handling the editor screen -> Next (compressing/rendering).
5. On Publish screen (PublishVideoActivity):
   - Optional: Attaching product via Import URL (Chain link -> paste URL -> Select All -> Add).
   - Typing video caption.
   - Tapping Post button.
6. Verifying upload completion and updating task status in the SQLite DB.
"""

import logging
import re
import time
import xml.etree.ElementTree as ET

from .states import CANCELLED, FAILED, NEEDS_OPERATOR, VERIFIED

logger = logging.getLogger("autopost.auto_poster")

# Set task_id yang diminta dibatalkan oleh pengguna/operator
CANCELLED_TASKS = set()


def cancel_task_execution(task_id: int):
    """Tandai tugas agar langsung dihentikan oleh engine autopost."""
    CANCELLED_TASKS.add(task_id)


class TaskCancelledException(Exception):
    """Exception yang dilempar saat tugas dibatalkan oleh pengguna."""
    pass


def clean_adb_text(text: str) -> str:
    """Sanitize text for ADB `input text` command."""
    if not text:
        return ""
    # Filter non-ASCII characters to prevent ADB crashes
    ascii_only = re.sub(r"[^\x20-\x7E]", "", text)
    # Replace whitespace with %s
    words = ascii_only.split()
    sanitized_words = []
    for w in words:
        # Escape characters that have special meaning in shell
        w_esc = re.sub(r'([&|;$><`"\'\\#])', r"\\\1", w)
        sanitized_words.append(w_esc)
    return "%s".join(sanitized_words)


class ShopeeAutoPoster:
    def __init__(self, vmos_adapter, service):
        self.vmos = vmos_adapter
        self.service = service

    def _get_serial(self, pad_code: str) -> str:
        if not pad_code:
            raise ValueError("pad_code tidak boleh kosong.")
        serial = self.vmos._get_target_serial(pad_code)
        if not serial:
            raise RuntimeError(f"Gagal mendapatkan serial ADB untuk device {pad_code}")
        return serial

    def _run_adb(self, serial: str, args, timeout: int = 30):
        return self.vmos._run_adb(["-s", serial] + list(args), timeout=timeout)

    def _abort_device(self, serial: str):
        """Force stop Shopee dan kembalikan VMOS ke Home screen."""
        try:
            logger.info("Menghentikan paksa com.shopee.my dan kembali ke Home di VMOS...")
            self._run_adb(serial, ["shell", "am", "force-stop", "com.shopee.my"])
            self._run_adb(serial, ["shell", "input", "keyevent", "3"])
            self._run_adb(serial, ["shell", "rm", "-f", "/data/local/tmp/shopee_dump.xml"])
        except Exception:
            pass

    def _check_cancelled(self, task_id: int, serial: str):
        """Cek apakah tugas telah dibatalkan di memori atau database."""
        if task_id in CANCELLED_TASKS:
            logger.info(f"Tugas #{task_id} terdeteksi DIBATALKAN via memori! Menghentikan VMOS...")
            self._abort_device(serial)
            raise TaskCancelledException(f"Tugas #{task_id} dibatalkan oleh operator.")
        try:
            t = self.service.get_task(task_id)
            if t and t.get("status") == CANCELLED:
                logger.info(f"Tugas #{task_id} terdeteksi CANCELLED di database! Menghentikan VMOS...")
                self._abort_device(serial)
                raise TaskCancelledException(f"Tugas #{task_id} dibatalkan oleh operator.")
        except TaskCancelledException:
            raise
        except Exception:
            pass

    def _tap(self, serial: str, x: int, y: int, sleep_s: float = 1.5):
        self._run_adb(serial, ["shell", "input", "tap", str(x), str(y)])
        if sleep_s > 0:
            time.sleep(sleep_s)

    def _keyevent(self, serial: str, keycode: int, sleep_s: float = 1.0):
        self._run_adb(serial, ["shell", "input", "keyevent", str(keycode)])
        if sleep_s > 0:
            time.sleep(sleep_s)

    def _input_text(self, serial: str, text: str, sleep_s: float = 1.5):
        clean = clean_adb_text(text)
        if clean:
            self._run_adb(serial, ["shell", "input", "text", clean])
        if sleep_s > 0:
            time.sleep(sleep_s)

    def _get_focused_activity(self, serial: str) -> str:
        _, out, _ = self._run_adb(serial, ["shell", "dumpsys", "window", "displays"])
        for line in out.splitlines():
            if "mCurrentFocus" in line:
                return line.strip()
        return ""

    def _dump_ui(self, serial: str) -> str:
        self._run_adb(serial, ["shell", "uiautomator", "dump", "/data/local/tmp/shopee_dump.xml"])
        code, out, _ = self._run_adb(serial, ["shell", "cat", "/data/local/tmp/shopee_dump.xml"])
        return out if code == 0 else ""

    def ensure_shopee_foreground(self, serial: str):
        """Ensure Shopee Malaysia (com.shopee.my) is running and in foreground."""
        focus = self._get_focused_activity(serial)
        if "com.shopee.my" not in focus:
            logger.info("Membuka aplikasi Shopee...")
            self._run_adb(serial, ["shell", "monkey", "-p", "com.shopee.my", "-c", "android.intent.category.LAUNCHER", "1"])
            for _ in range(8):
                time.sleep(1.5)
                f = self._get_focused_activity(serial)
                if "com.shopee.my" in f:
                    break
            time.sleep(3.0)

    def switch_shop(self, serial: str, target_username: str) -> bool:
        """Switch to target shop using in-app search:
        button_ACTION_SEARCH -> type username -> tap suggestion -> tap shopCard.
        """
        norm_target = target_username.strip().lstrip("@").lower()
        logger.info(f"Memulai perpindahan akun ke @{norm_target}...")

        # 0. Tap 'Me' tab at bottom right (center 648, 1240) to ensure profile screen is visible
        self._tap(serial, 648, 1240, sleep_s=2.0)

        # 1. Tap Switch Shop (bounds roughly [548,210][680,238], center 614, 224)
        self._tap(serial, 614, 224, sleep_s=2.5)

        # 2. Tap search icon (button_ACTION_SEARCH at 672, 104)
        self._tap(serial, 672, 104, sleep_s=1.5)

        # 3. Focus search box and type username
        self._tap(serial, 300, 104, sleep_s=1.0)
        self._input_text(serial, norm_target, sleep_s=2.0)

        # 4. Hide keyboard
        self._keyevent(serial, 111, sleep_s=1.0)

        # 5. Check if search suggestion appeared and tap it (center 360, 200)
        self._tap(serial, 360, 200, sleep_s=2.5)

        # 6. Tap filtered shop card (bounds [0,160][720,288], center 360, 224)
        self._tap(serial, 360, 224, sleep_s=4.0)

        # Verify on profile
        focus = self._get_focused_activity(serial)
        logger.info(f"Selesai switch shop. Focus: {focus}")
        return True

    def open_video_picker(self, serial: str):
        """Navigate to Shopee Video -> Create Video -> Gallery Library -> Video tab."""
        logger.info("Membuka Shopee Video...")
        # 1. Tap Shopee Video button on profile (center 166, 480)
        self._tap(serial, 166, 480, sleep_s=3.0)

        # 2. Tap Create Video if on video landing page (bounds [184,232][648,272], center 416, 252)
        focus = self._get_focused_activity(serial)
        if "publishvideo" not in focus.lower() and "sszmediaactivity" not in focus.lower():
            logger.info("Menekan tombol Create Video pada (416, 252)...")
            self._tap(serial, 416, 252, sleep_s=3.5)
            # Pastikan masuk ke camera activity (SSZMediaActivity)
            for _ in range(3):
                focus = self._get_focused_activity(serial)
                if "sszmediaactivity" in focus.lower():
                    break
                self._tap(serial, 416, 252, sleep_s=2.5)

        # 3. Tap Library entrance in camera (bounds [523,964][627,1128], center 575, 1050)
        self._tap(serial, 575, 1050, sleep_s=3.0)

        # 4. Tap Video tab in Gallery (bounds [240,114][480,202], center 360, 158)
        self._tap(serial, 360, 158, sleep_s=2.0)

        # 5. Select first video checkbox (ll_check bounds [106,204][178,276], center 142, 240)
        self._tap(serial, 142, 240, sleep_s=1.5)

        # 6. Dismiss education tip dialog if present ('Upload Quality' OK button at 360, 1168)
        self._tap(serial, 360, 1168, sleep_s=1.0)

        # 7. Tap Next (1) button (bounds [547,1031][696,1087], center 621, 1059)
        self._tap(serial, 621, 1059, sleep_s=4.0)

    def proceed_editor(self, serial: str):
        """Tap Next on video editor screen (compressing/rendering video)."""
        logger.info("Melewati Video Editor...")
        # Next button on editor screen (bounds [552,1174][680,1230], center 616, 1202)
        self._tap(serial, 616, 1202, sleep_s=2.0)
        # Polling dinamis sampai PublishVideoActivity muncul (maksimal 10 detik)
        for _ in range(16):
            focus = self._get_focused_activity(serial).lower()
            if "publishvideo" in focus:
                break
            time.sleep(0.5)


    def fill_and_post(self, serial: str, caption: str = None, product_link: str = None, task_id: int = None):
        """On PublishVideoActivity:
        1. Menempel caption sesuai tugas akunnya (dan klik OK).
        2. Klik tambahkan produk -> paste URL produk -> impor dan add.
        3. Mengaktifkan AI generate label.
        4. Posting.
        """
        logger.info("Mengisi data postingan Shopee Video...")
        if task_id:
            self._check_cancelled(task_id, serial)
        product_attached = False

        # 1. Menempel caption sesuai tugas akunnya
        if caption and caption.strip():
            logger.info("Mengetik caption...")
            if task_id:
                self._check_cancelled(task_id, serial)
            # Tap caption field (bounds roughly [360,120][680,280], center 450, 180)
            self._tap(serial, 450, 180, sleep_s=1.0)

            # Batasi caption maksimal 150 karakter sesuai limit Shopee Video
            sanitized_cap = caption.strip()[:148]
            self._input_text(serial, sanitized_cap, sleep_s=1.5)

            # Konfirmasi caption dengan menekan tombol OK di pojok kanan atas (670, 72)
            self._tap(serial, 670, 72, sleep_s=1.5)
            # Sembunyikan keyboard agar tidak menutupi tombol produk atau post
            self._keyevent(serial, 111, sleep_s=0.5)

        # 2. Menautkan produk jika ada (Tap to add products -> Chain link -> Paste URL -> Import -> Checkbox -> Add)
        if product_link and product_link.strip():
            try:
                if task_id:
                    self._check_cancelled(task_id, serial)
                logger.info(f"Menautkan produk: {product_link}")
                # Tap 'Tap to add products' pill (center 600, 520)
                self._tap(serial, 600, 520, sleep_s=3.0)

                # Tap chain link icon (top-right at 665, 80)
                self._tap(serial, 665, 80, sleep_s=2.5)

                # Bersihkan kolom teks URL sebelumnya jika ada (tombol 'Clear all' di 622, 198)
                self._tap(serial, 622, 198, sleep_s=1.0)

                # Tap Product URL textarea (center 360, 300)
                self._tap(serial, 360, 300, sleep_s=1.0)

                # Input product link
                self._input_text(serial, product_link.strip(), sleep_s=1.5)

                # Sembunyikan keyboard agar tombol Import dan daftar hasil tidak tertutup
                self._keyevent(serial, 111, sleep_s=1.0)

                # Tap Import button (center 382, 659)
                self._tap(serial, 382, 659, sleep_s=4.0)

                # Periksa apakah produk berhasil diimpor ke dalam daftar
                ui_xml = self._dump_ui(serial)
                if "Comm rate" in ui_xml or "sold" in ui_xml or "[24,976][60,1012]" in ui_xml:
                    # Tap product item checkbox (center 42, 994)
                    self._tap(serial, 42, 994, sleep_s=1.0)
                    # Tap Add(1) button (center 456, 1157)
                    self._tap(serial, 456, 1157, sleep_s=3.0)
                    product_attached = True
                    logger.info("Produk berhasil dipilih dan ditautkan ke video!")
                else:
                    logger.warning(f"Produk {product_link} tidak muncul di Import List (link ditolak Shopee atau produk tidak eligible untuk affiliate video).")
                    product_attached = False
            except Exception as e:
                if isinstance(e, TaskCancelledException):
                    raise
                logger.warning(f"Gagal menautkan produk: {e}")
            finally:
                # Ensure we are back on Add Caption screen (PublishVideoActivity)
                for _ in range(3):
                    focus = self._get_focused_activity(serial)
                    if "publishvideo" in focus.lower():
                        break
                    self._keyevent(serial, 4, sleep_s=1.5)

        # 3. Mengaktifkan AI generate label
        if task_id:
            self._check_cancelled(task_id, serial)
        logger.info("Mengaktifkan AI-generated label...")
        # Jika produk terpasang, letak switch terdorong ke Y=1082 (center 660, 1082)
        # Jika tanpa produk, letak switch berada di Y=931 (center 650, 931)
        ai_switch_y = 1082 if product_attached else 931
        ai_switch_x = 660 if product_attached else 650
        self._tap(serial, ai_switch_x, ai_switch_y, sleep_s=2.0)

        # 4. Posting (Post button center 418, 1210)
        if task_id:
            self._check_cancelled(task_id, serial)
        logger.info("Menekan tombol Post...")
        self._tap(serial, 418, 1210, sleep_s=12.0)

        # 5. Tonton video selama 2 menit (120 detik) lalu force close
        self.wait_retention_watch(serial, duration_sec=120, task_id=task_id)

    def wait_retention_watch(self, serial: str, duration_sec: int = 120, task_id: int = None):
        """Membuka video yang baru diposting, menontonnya selama duration_sec detik, lalu force close Shopee."""
        # Tunggu hingga layar kembali dari PublishVideoActivity
        for _ in range(6):
            if task_id:
                self._check_cancelled(task_id, serial)
            focus = self._get_focused_activity(serial).lower()
            if "publishvideo" not in focus:
                break
            time.sleep(2.0)

        logger.info("Membuka video hasil posting di grid profil Shopee Video...")
        # Item video terbaru pada grid profil Shopee Video berada di (120, 650)
        self._tap(serial, 120, 650, sleep_s=3.0)

        logger.info(f"Menonton video selama {duration_sec} detik (retensi penonton)...")
        step = 5
        elapsed = 0
        while elapsed < duration_sec:
            if task_id:
                self._check_cancelled(task_id, serial)
            chunk = min(step, duration_sec - elapsed)
            time.sleep(chunk)
            elapsed += chunk
            rem = duration_sec - elapsed
            if rem > 0 and rem % 15 == 0:
                logger.info(f"Sedang memutar video Shopee... sisa {rem} detik")
        logger.info(f"Waktu tonton {duration_sec} detik selesai.")

        logger.info("Melakukan force close aplikasi Shopee (com.shopee.my)...")
        self._abort_device(serial)
        time.sleep(1.0)
        logger.info("Shopee berhasil di-force close.")

    def run_task(self, task_id: int) -> dict:
        """Run end-to-end automated posting for a specific task."""
        task = self.service.get_task(task_id)
        pad_code = task.get("pad_code")
        username = task.get("username")
        caption = task.get("caption") or ""
        product_link = task.get("product_link") or ""

        if not pad_code:
            raise ValueError(f"Task {task_id} tidak memiliki pad_code!")
        if not username:
            raise ValueError(f"Task {task_id} tidak memiliki username!")

        logger.info(f"=== Menjalankan Auto-Post Task #{task_id}: @{username} di {pad_code} ===")

        # 1. Connect ADB to assigned pad_code
        serial = self._get_serial(pad_code)

        try:
            self._check_cancelled(task_id, serial)

            # 2. Ensure Shopee is running
            self.ensure_shopee_foreground(serial)
            self._check_cancelled(task_id, serial)

            # 3. Check current screen state
            focus = self._get_focused_activity(serial).lower()
            if "publishvideo" in focus:
                logger.info("Device sudah di PublishVideoActivity. Melanjutkan pengisian data...")
                self.fill_and_post(serial, caption=caption, product_link=product_link, task_id=task_id)
            elif "multipleedit" in focus or "editpage" in focus:
                self._check_cancelled(task_id, serial)
                logger.info("Device di Video Editor. Melanjutkan ke Publish screen...")
                self.proceed_editor(serial)
                self.fill_and_post(serial, caption=caption, product_link=product_link, task_id=task_id)
            else:
                # Full flow: Switch Shop -> Pick Video -> Editor -> Publish
                self.switch_shop(serial, username)
                self._check_cancelled(task_id, serial)
                self.open_video_picker(serial)
                self._check_cancelled(task_id, serial)
                self.proceed_editor(serial)
                self._check_cancelled(task_id, serial)
                self.fill_and_post(serial, caption=caption, product_link=product_link, task_id=task_id)
        except TaskCancelledException:
            logger.info(f"Tugas #{task_id} berhasil dihentikan karena dibatalkan oleh pengguna.")
            self._abort_device(serial)
            try:
                self.service.force_unlock(pad_code)
            except Exception:
                pass
            return {
                "status": "cancelled",
                "task_id": task_id,
                "username": username,
                "pad_code": pad_code,
                "message": f"Tugas #{task_id} dibatalkan oleh operator."
            }
        except Exception as e:
            # Force close Shopee on error so device returns to a clean state
            self._abort_device(serial)
            raise e
        finally:
            CANCELLED_TASKS.discard(task_id)

        # 7. Update status to VERIFIED in DB
        try:
            self.service.transition(
                task_id,
                VERIFIED,
                actor="autoposter",
                reason="Auto-posted via VMOS ADB automation",
                confirmed_username=username,
                evidence="adb_auto_post_success",
                video_post_id=f"auto_{int(time.time())}"
            )
            logger.info(f"Task #{task_id} berhasil di-VERIFIED!")
        except Exception as e:
            logger.warning(f"Gagal memverifikasi status task #{task_id}: {e}")

        # 8. Trigger immediate cleanup & unlock
        try:
            self.service.run_cleanup(self.vmos, force=True)
        except Exception:
            pass

        return {
            "status": "success",
            "task_id": task_id,
            "username": username,
            "pad_code": pad_code,
            "message": f"Berhasil auto-posting video untuk @{username} pada {pad_code}"
        }
