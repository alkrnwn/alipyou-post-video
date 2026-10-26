"""Adapter VMOS Cloud dan ADB.

Mendukung komunikasi ke VMOS Cloud Phone via API resmi VMOS Cloud + SSH Tunnel ADB,
atau langsung melalui perangkat ADB yang sudah tersambung di PC.

Kredensial dibaca dari environment variables atau file .env:
  - VMOS_ACCESS_KEY
  - VMOS_SECRET_KEY
  - VMOS_BASE_URL (default: https://api.vmoscloud.com)
  - ADB_PATH (opsional: path executable adb)
"""
import hashlib
import json
import os
import re
import select
import shutil
import socketserver
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from pathlib import Path


def _load_env_file():
    """Baca file .env secara ringan jika ada, kecuali saat test berjalan."""
    if "pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ:
        return
    candidates = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parent.parent / ".env",
        Path(__file__).resolve().parent.parent.parent / ".env",
    ]
    for p in candidates:
        if p.is_file():
            try:
                for line in p.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k, v = k.strip(), v.strip()
                        if k and k not in os.environ:
                            os.environ[k] = v
            except Exception:
                pass
            break


def save_env_file(access_key, secret_key, base_url="https://api.vmoscloud.com"):
    """Simpan atau perbarui file .env di lokasi project."""
    if "pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ:
        return
    candidates = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parent.parent / ".env",
        Path(__file__).resolve().parent.parent.parent / ".env",
    ]
    env_path = candidates[1]
    existing = {}
    if env_path.is_file():
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    existing[k.strip()] = v.strip()
        except Exception:
            pass

    existing["VMOS_ACCESS_KEY"] = (access_key or "").strip()
    existing["VMOS_SECRET_KEY"] = (secret_key or "").strip()
    if base_url:
        existing["VMOS_BASE_URL"] = (base_url or "").strip().rstrip("/")

    lines = [f"{k}={v}" for k, v in existing.items()]
    try:
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception:
        pass


_load_env_file()


class VmosAdapter(ABC):
    ready = True

    def update_credentials(self, access_key=None, secret_key=None, base_url=None):
        pass

    def test_connection(self, access_key=None, secret_key=None, base_url=None):
        return {"ok": True, "msg": "Adapter siap."}

    @abstractmethod
    def list_devices(self):
        """Kembalikan list ID device (PAD CODE) dan statusnya."""

    @abstractmethod
    def push_file(self, pad_code, local_path, remote_path):
        """Kirim file ke device."""

    @abstractmethod
    def file_size(self, pad_code, remote_path):
        """Ukuran file di device dalam byte, atau None bila tidak ada."""

    @abstractmethod
    def delete_file(self, pad_code, remote_path):
        """Hapus tepat satu file di device."""

    def rescan_media(self, pad_code, remote_path):
        """Best-effort: bersihkan entri galeri. Default tidak melakukan apa pun."""
        return None

    def get_screenshot(self, pad_code):
        """Ambil tangkapan layar emulator (PNG bytes) jika didukung."""
        return None


class HttpVmosAdapter(VmosAdapter):
    """Adapter VMOS Cloud API resmi + ADB."""

    def __init__(self, access_key=None, secret_key=None, base_url=None, adb_path=None):
        if access_key is None:
            self.access_key = os.environ.get("VMOS_ACCESS_KEY", "").strip()
        else:
            self.access_key = str(access_key).strip()

        if secret_key is None:
            self.secret_key = os.environ.get("VMOS_SECRET_KEY", "").strip()
        else:
            self.secret_key = str(secret_key).strip()

        if base_url is None:
            self.base_url = os.environ.get("VMOS_BASE_URL", "https://api.vmoscloud.com").strip().rstrip("/")
        else:
            self.base_url = str(base_url).strip().rstrip("/")


        # Deteksi adb
        custom_adb = adb_path or os.environ.get("ADB_PATH", "")
        if custom_adb and os.path.isfile(custom_adb):
            self.adb_path = custom_adb
        else:
            candidates = [
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "adb", "adb.exe"),
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "adb", "adb.exe"),
                os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "adb", "adb.exe"),
                os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "adb.exe"),
                getattr(sys, "_MEIPASS", "") and os.path.join(getattr(sys, "_MEIPASS", ""), "adb", "adb.exe"),
                r"C:\Users\Administrator\AppData\Roaming\TungTungPoster\adb.exe",
            ]
            found = False
            for c in candidates:
                if c and os.path.isfile(c):
                    self.adb_path = os.path.abspath(c)
                    found = True
                    break
            if not found:
                self.adb_path = shutil.which("adb") or "adb"

        # Tunnel SSH per pad_code: pad_code -> {'serial': str, 'port': int, 'client': paramiko, 'server': server}
        self.tunnels = {}
        self.lock = threading.Lock()

        # Siap bila kredensial tersedia
        self.ready = bool(self.access_key and self.secret_key)

    def update_credentials(self, access_key=None, secret_key=None, base_url=None):
        if access_key is not None:
            self.access_key = str(access_key).strip()
            os.environ["VMOS_ACCESS_KEY"] = self.access_key
        if secret_key is not None:
            self.secret_key = str(secret_key).strip()
            os.environ["VMOS_SECRET_KEY"] = self.secret_key
        if base_url is not None:
            self.base_url = str(base_url).strip().rstrip("/")
            os.environ["VMOS_BASE_URL"] = self.base_url
        self.ready = bool(self.access_key and self.secret_key)

    def test_connection(self, access_key=None, secret_key=None, base_url=None):
        ak = (access_key if access_key is not None else self.access_key).strip()
        sk = (secret_key if secret_key is not None else self.secret_key).strip()
        burl = (base_url if base_url is not None else self.base_url).strip().rstrip("/")

        if not ak or not sk:
            return {
                "ok": False,
                "msg": "Access Key ID dan Secret Access Key tidak boleh kosong.",
                "code": 400
            }

        ts = str(int(time.time()))
        path = "/vcpcloud/api/padApi/openOnlineAdb"
        body = {"padCodes": ["__conn_test__"], "openStatus": 1}
        body_str = json.dumps(body, separators=(",", ":"))
        sign_str = f"{sk}{ts}{path}{body_str}"
        sign = hashlib.sha256(sign_str.encode("utf-8")).hexdigest().lower()

        headers = {
            "Content-Type": "application/json",
            "X-Access-Key": ak,
            "X-Timestamp": ts,
            "X-Sign": sign,
        }
        url = f"{burl}{path}"
        req = urllib.request.Request(url, data=body_str.encode("utf-8"), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                code = data.get("code")
                if code in (200, 0, 2020):
                    return {
                        "ok": True,
                        "msg": "Koneksi ke API VMOS Cloud Berhasil! Kredensial Valid.",
                        "code": code
                    }
                return {
                    "ok": True,
                    "msg": f"Terhubung ke VMOS Cloud: {data.get('msg', 'OK')}",
                    "code": code
                }
        except urllib.error.HTTPError as e:
            try:
                err_data = json.loads(e.read().decode("utf-8", errors="replace"))
                msg = err_data.get("msg", "")
                code = err_data.get("code")
                if "invalid key" in msg.lower() or code == 2031:
                    return {"ok": False, "msg": "Access Key ID tidak valid atau tidak terdaftar di VMOS Cloud.", "code": code}
                if "signature" in msg.lower() or code == 2019:
                    return {"ok": False, "msg": "Secret Access Key salah (verifikasi tanda tangan gagal).", "code": code}
                return {"ok": False, "msg": f"VMOS API menolak request ({e.code}): {msg}", "code": code}
            except Exception:
                return {"ok": False, "msg": f"HTTP Error {e.code}: {e.reason}", "code": e.code}
        except Exception as e:
            return {"ok": False, "msg": f"Gagal menghubungi server VMOS Cloud: {str(e)}", "code": 500}


    def call_api(self, path, body=None):
        """Kirim request terotentikasi ke API VMOS Cloud."""
        if not self.access_key or not self.secret_key:
            raise RuntimeError("VMOS_ACCESS_KEY dan VMOS_SECRET_KEY belum diisi.")

        ts = str(int(time.time()))
        body_str = json.dumps(body, separators=(",", ":")) if body is not None else ""
        sign_str = f"{self.secret_key}{ts}{path}{body_str}"
        sign = hashlib.sha256(sign_str.encode("utf-8")).hexdigest().lower()

        headers = {
            "Content-Type": "application/json",
            "X-Access-Key": self.access_key,
            "X-Timestamp": ts,
            "X-Sign": sign,
        }
        url = f"{self.base_url}{path}"
        req = urllib.request.Request(url, data=body_str.encode("utf-8"), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"VMOS API HTTP {e.code}: {err_body}")
        except Exception as e:
            raise RuntimeError(f"Gagal menghubungi VMOS API: {e}")

    def _run_adb(self, args, timeout=30):
        cmd = [self.adb_path] + [str(a) for a in args]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return res.returncode, res.stdout, res.stderr

    def _get_target_serial(self, pad_code):
        """Dapatkan serial ADB untuk pad_code tertentu (bisa berupa pad_code langsung atau 127.0.0.1:port)."""
        with self.lock:
            if pad_code in self.tunnels:
                serial = self.tunnels[pad_code]["serial"]
                _, out_chk, _ = self._run_adb(["devices"])
                if f"{serial}\tdevice" in out_chk or f"{serial} device" in out_chk:
                    return serial
                try:
                    self.tunnels[pad_code]["server"].shutdown()
                    self.tunnels[pad_code]["server"].server_close()
                    self.tunnels[pad_code]["client"].close()
                except Exception:
                    pass
                del self.tunnels[pad_code]

            # Cek apakah pad_code sudah langsung terdeteksi di adb devices
            _, out, _ = self._run_adb(["devices"])
            lines = [line.strip() for line in out.splitlines()[1:] if line.strip()]
            for line in lines:
                parts = line.split()
                if len(parts) >= 2 and parts[1] == "device":
                    serial = parts[0]
                    if pad_code.lower() in serial.lower() or serial.lower() in pad_code.lower():
                        return serial

            # Bila belum, hubungkan via VMOS Cloud Online ADB Tunnel
            try:
                import paramiko
            except ImportError:
                # Jika paramiko belum terpasang, coba sambungkan langsung jika pad_code adalah host:port
                if ":" in pad_code:
                    self._run_adb(["connect", pad_code])
                    return pad_code
                raise RuntimeError(
                    f"Device {pad_code} belum tersambung via ADB. Pasang paramiko untuk membuka tunnel otomatis."
                )

            # Buka online ADB via API VMOS
            self.call_api("/vcpcloud/api/padApi/openOnlineAdb", {"padCodes": [pad_code], "openStatus": 1})
            res_adb = self.call_api("/vcpcloud/api/padApi/adb", {"padCode": pad_code, "enable": True})
            data = res_adb.get("data", {})
            command = data.get("command")
            key = data.get("key")

            if not command:
                raise RuntimeError(f"Gagal mendapatkan info ADB tunnel VMOS: {res_adb.get('msg', 'no command')}")

            match = re.search(r"(\w+)@([^\s]+)\s+-p\s+(\d+)\s+-L\s+(\d+):([^:]+):(\d+)", command)
            if not match:
                raise RuntimeError(f"Format perintah SSH tidak dikenali: {command}")

            user, host, ssh_port, local_port, remote_host, remote_port = match.groups()
            ssh_port = int(ssh_port)
            local_port = int(local_port)
            remote_port = int(remote_port)

            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(host, port=ssh_port, username=user, password=key, timeout=15,
                           look_for_keys=False, allow_agent=False)
            transport = client.get_transport()

            class ForwardServer(socketserver.ThreadingTCPServer):
                daemon_threads = True
                allow_reuse_address = True
                ssh_transport = transport

            class Handler(socketserver.BaseRequestHandler):
                def handle(self):
                    try:
                        chan = self.server.ssh_transport.open_channel(
                            "direct-tcpip",
                            (remote_host, remote_port),
                            self.request.getpeername(),
                        )
                    except Exception:
                        return
                    if chan is None:
                        return

                    def pipe(src, dst):
                        try:
                            while True:
                                data = src.recv(8192)
                                if not data:
                                    break
                                dst.sendall(data)
                        except Exception:
                            pass
                        finally:
                            try:
                                src.close()
                            except Exception:
                                pass
                            try:
                                dst.close()
                            except Exception:
                                pass

                    t1 = threading.Thread(target=pipe, args=(self.request, chan), daemon=True)
                    t2 = threading.Thread(target=pipe, args=(chan, self.request), daemon=True)
                    t1.start()
                    t2.start()
                    t1.join()
                    t2.join()

            server = ForwardServer(("127.0.0.1", local_port), Handler)
            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start()

            time.sleep(0.5)
            target_serial = f"127.0.0.1:{local_port}"
            self._run_adb(["disconnect", target_serial])
            self._run_adb(["connect", target_serial])
            for _ in range(12):
                time.sleep(0.5)
                _, out_dev, _ = self._run_adb(["devices"])
                if f"{target_serial}\tdevice" in out_dev or f"{target_serial} device" in out_dev:
                    break

            self.tunnels[pad_code] = {
                "serial": target_serial,
                "port": local_port,
                "client": client,
                "server": server,
            }
            return target_serial

    def list_devices(self):
        """Daftar device yang terhubung via ADB."""
        code, out, _ = self._run_adb(["devices"])
        if code != 0:
            return []
        devices = []
        for line in out.splitlines()[1:]:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                devices.append(parts[0])
        return devices

    def push_file(self, pad_code, local_path, remote_path):
        target = self._get_target_serial(pad_code)
        # Pastikan folder tujuan ada
        remote_dir = "/".join(remote_path.replace("\\", "/").rstrip("/").split("/")[:-1])
        if remote_dir:
            self._run_adb(["-s", target, "shell", "mkdir", "-p", f"'{remote_dir}'"])

        code, _, err = self._run_adb(["-s", target, "push", local_path, remote_path], timeout=120)
        if code != 0:
            raise RuntimeError(f"Gagal push file ke device {pad_code}: {err.strip()}")

    def file_size(self, pad_code, remote_path):
        target = self._get_target_serial(pad_code)
        # Gunakan stat -c %s
        clean_path = remote_path.replace("'", "'\\''")
        code, out, _ = self._run_adb(
            ["-s", target, "shell", f"stat -c %s '{clean_path}' 2>/dev/null || wc -c < '{clean_path}' 2>/dev/null"]
        )
        if code != 0:
            return None
        out = out.strip()
        if out.isdigit():
            return int(out)
        return None

    def delete_file(self, pad_code, remote_path):
        target = self._get_target_serial(pad_code)
        clean_path = remote_path.replace("'", "'\\''")
        self._run_adb(["-s", target, "shell", "rm", "-f", f"'{clean_path}'"])

    def rescan_media(self, pad_code, remote_path):
        target = self._get_target_serial(pad_code)
        clean_path = remote_path.replace("'", "'\\''")
        self._run_adb(
            ["-s", target, "shell", "am", "broadcast", "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
             "-d", f"file://{clean_path}"]
        )
        fname = os.path.basename(remote_path)
        self._run_adb([
            "-s", target, "shell", "content", "insert",
            "--uri", "content://media/external/video/media",
            "--bind", f"_data:s:{clean_path}",
            "--bind", "mime_type:s:video/mp4",
            "--bind", f"title:s:{fname}",
            "--bind", f"_display_name:s:{fname}"
        ])

    def get_screenshot(self, pad_code):
        try:
            target = self._get_target_serial(pad_code)
            cmd = [self.adb_path, "-s", target, "exec-out", "screencap", "-p"]
            res = subprocess.run(cmd, capture_output=True, timeout=12)
            if res.returncode == 0 and len(res.stdout) > 200:
                return res.stdout
        except Exception:
            pass
        return None


class FakeVmos(VmosAdapter):
    """Untuk uji dan dry-run lokal. Menyimpan 'file device' di memori."""

    def __init__(self):
        self.files = {}  # (pad_code, path) -> size
        self.fail_push = False
        self.fail_delete = False
        self.delete_noop = False  # delete 'sukses' tapi file tetap ada
        self.rescans = []
        self.access_key = "FAKE_AK"
        self.secret_key = "FAKE_SK"
        self.base_url = "https://api.vmoscloud.com"
        self.ready = True

    def update_credentials(self, access_key=None, secret_key=None, base_url=None):
        if access_key is not None:
            self.access_key = access_key
        if secret_key is not None:
            self.secret_key = secret_key
        if base_url is not None:
            self.base_url = base_url
        self.ready = bool(self.access_key and self.secret_key)

    def test_connection(self, access_key=None, secret_key=None, base_url=None):
        ak = access_key if access_key is not None else self.access_key
        sk = secret_key if secret_key is not None else self.secret_key
        if not ak or not sk:
            return {"ok": False, "msg": "Access Key ID dan Secret Access Key tidak boleh kosong.", "code": 400}
        return {"ok": True, "msg": "Koneksi simulasi berhasil (Mode Uji / Dry-Run).", "code": 200}


    def list_devices(self):
        return sorted({p for p, _ in self.files})

    def push_file(self, pad_code, local_path, remote_path):
        import os
        if self.fail_push:
            self.files[(pad_code, remote_path)] = 1  # file parsial
            raise RuntimeError("push gagal (simulasi)")
        self.files[(pad_code, remote_path)] = os.path.getsize(local_path)

    def file_size(self, pad_code, remote_path):
        return self.files.get((pad_code, remote_path))

    def delete_file(self, pad_code, remote_path):
        if self.fail_delete:
            raise RuntimeError("delete gagal (simulasi)")
        if not self.delete_noop:
            self.files.pop((pad_code, remote_path), None)

    def rescan_media(self, pad_code, remote_path):
        self.rescans.append((pad_code, remote_path))
