import os
from datetime import datetime, timedelta

import pytest

from app import sheets
from app.service import (Config, DuplicateTask, GuardError, InvalidTransition, Service)
from app.states import *  # noqa
from app.states import ALL, TRANSITIONS
from app.vmos import FakeVmos


class Clock:
    def __init__(self):
        self.t = datetime(2026, 10, 26, 9, 0, 0)

    def __call__(self):
        return self.t

    def adv(self, **kw):
        self.t += timedelta(**kw)


@pytest.fixture
def env(tmp_path):
    video = tmp_path / "v1.mp4"
    video.write_bytes(b"x" * 1000)
    clock = Clock()
    cfg = Config(min_gap_min=0, max_posts_per_day=50)
    svc = Service(str(tmp_path / "t.db"), cfg, clock)
    svc.upsert_account("A", "@shopA", "PAD1", label="VMOS-A")
    svc.upsert_account("B", "shopB", "PAD1")
    svc.upsert_account("C", "shopC", "PAD2")
    svc.add_video("v1", str(video))
    svc.add_video("v2", str(video))
    return svc, clock, FakeVmos(), tmp_path


def run_to_needs_operator(svc, vm, pad=None):
    t = svc.start_next(pad)
    assert t["status"] == PREPARING
    return svc.prepare(vm, t["id"])


def force(svc, tid, status, **cols):
    from app import db
    with db.tx(svc.db_path) as c:
        sets = ", ".join(["status=?"] + [f"{k}=?" for k in cols])
        c.execute(f"UPDATE tasks SET {sets} WHERE id=?", [status, *cols.values(), tid])


def test_semua_transisi_tidak_sah_ditolak(env):
    svc, clock, vm, _ = env
    t = svc.create_task("shopA", "v1")
    for frm in ALL:
        for to in ALL:
            if to == PREPARING or (frm, to) in TRANSITIONS:
                continue
            force(svc, t["id"], frm, prev_status=None)
            with pytest.raises(InvalidTransition):
                svc.transition(t["id"], to, "op", "x", confirmed_username="shopA", evidence="e")


def test_jalur_bahagia_dan_pembersihan_setelah_jeda(env):
    svc, clock, vm, _ = env
    t = svc.create_task("shopA", "v1")
    t = run_to_needs_operator(svc, vm)
    path = t["device_file_path"]
    assert ("PAD1", path) in vm.files
    assert "task_%d" % t["id"] in path
    with pytest.raises(GuardError):  # username salah
        svc.transition(t["id"], VERIFIED, "op", confirmed_username="shopB", evidence="ss.png")
    with pytest.raises(GuardError):  # tanpa bukti
        svc.transition(t["id"], VERIFIED, "op", confirmed_username="shopA")
    t = svc.transition(t["id"], VERIFIED, "op", confirmed_username="@ShopA", evidence="ss.png")
    assert t["cleanup_status"] == "PENDING"
    assert svc.run_cleanup(vm) == [(t["id"], "WAIT")]
    assert ("PAD1", path) in vm.files          # belum dihapus sebelum jeda aman
    clock.adv(seconds=301)
    assert svc.run_cleanup(vm) == [(t["id"], "DONE")]
    assert ("PAD1", path) not in vm.files
    assert vm.rescans == [("PAD1", path)]
    assert svc.get_task(t["id"])["cleanup_status"] == "DONE"
    # kunci device lepas setelah pembersihan
    svc.create_task("shopB", "v1")
    assert svc.start_next("PAD1")["username"] == "shopb"


def test_satu_tugas_aktif_per_device_dan_prioritas_shop_sama(env):
    svc, clock, vm, _ = env
    a1 = svc.create_task("shopA", "v1")
    b1 = svc.create_task("shopB", "v1")
    a2 = svc.create_task("shopA", "v2")
    t = run_to_needs_operator(svc, vm, "PAD1")
    assert t["id"] == a1["id"]
    assert svc.start_next("PAD1") is None      # device terkunci
    svc.transition(t["id"], VERIFIED, "op", confirmed_username="shopA", evidence="e")
    clock.adv(seconds=301)
    svc.run_cleanup(vm)
    nxt = svc.start_next("PAD1")
    assert nxt["id"] == a2["id"]               # shopA didahulukan, bukan shopB


def test_review_required_tidak_menghapus_dan_tidak_memblokir_device_lain(env):
    svc, clock, vm, _ = env
    svc.create_task("shopA", "v1")
    svc.create_task("shopC", "v1")
    t = run_to_needs_operator(svc, vm, "PAD1")
    t = svc.transition(t["id"], REVIEW_REQUIRED, "op", "tidak yakin")
    clock.adv(hours=2)
    assert svc.run_cleanup(vm) == []
    assert ("PAD1", t["device_file_path"]) in vm.files
    assert svc.start_next("PAD1") is None      # device PAD1 tetap terkunci
    other = svc.start_next("PAD2")             # device lain tetap jalan
    assert other["username"] == "shopc"
    with pytest.raises(GuardError):            # penyelesaian wajib bukti+catatan
        svc.transition(t["id"], VERIFIED, "op")


def test_blokir_akun_yang_sama_di_antrean(env):
    svc, clock, vm, _ = env
    svc.create_task("shopA", "v1")
    svc.create_task("shopA", "v2")
    t = run_to_needs_operator(svc, vm, "PAD1")
    svc.transition(t["id"], REVIEW_REQUIRED, "op", "ragu")
    from app import db
    with db.tx(svc.db_path) as c:              # simulasi device dilepas
        c.execute("DELETE FROM device_locks")
    assert svc.start_next("PAD1") is None      # akun masih REVIEW_REQUIRED


def test_restart_memindahkan_tugas_berjalan_ke_review(env):
    svc, clock, vm, tmp = env
    svc.create_task("shopA", "v1")
    svc.create_task("shopC", "v1")
    t1 = run_to_needs_operator(svc, vm, "PAD1")
    t2 = svc.start_next("PAD2")                # PREPARING
    svc2 = Service(svc.db_path, svc.cfg, clock)  # "restart"
    moved = svc2.recover_on_startup()
    assert sorted(moved) == sorted([t1["id"], t2["id"]])
    assert svc2.get_task(t1["id"])["status"] == REVIEW_REQUIRED
    assert svc2.get_task(t2["id"])["status"] == REVIEW_REQUIRED
    assert svc2.start_next() is None           # tidak kembali ke QUEUED otomatis


def test_timeout_operator(env):
    svc, clock, vm, _ = env
    svc.create_task("shopA", "v1")
    t = run_to_needs_operator(svc, vm)
    clock.adv(minutes=29)
    assert svc.sweep_timeouts() == []
    clock.adv(minutes=2)
    assert svc.sweep_timeouts() == [t["id"]]
    assert svc.get_task(t["id"])["status"] == REVIEW_REQUIRED


def test_duplikat_dan_retry(env):
    svc, clock, vm, _ = env
    t = svc.create_task("shopA", "v1", batch="b1")
    with pytest.raises(DuplicateTask):
        svc.create_task("shopA", "v1", batch="b1")
    t = run_to_needs_operator(svc, vm)
    svc.transition(t["id"], FAILED, "op")
    # tugas lain untuk akun+video sama sedang VERIFIED -> retry diblokir
    other = svc.create_task("shopA", "v1", batch="b2")
    force(svc, other["id"], VERIFIED)
    with pytest.raises(GuardError):
        svc.transition(t["id"], QUEUED, "op")
    force(svc, other["id"], CANCELLED)
    r = svc.transition(t["id"], QUEUED, "op")
    assert r["attempt"] == 2


def test_pause_resume(env):
    svc, clock, vm, _ = env
    t = run_to_needs_operator(svc, vm) if svc.create_task("shopA", "v1") else None
    p = svc.transition(t["id"], PAUSED, "op")
    assert p["prev_status"] == NEEDS_OPERATOR
    with pytest.raises(InvalidTransition):
        svc.transition(t["id"], QUEUED, "op")
    assert svc.transition(t["id"], NEEDS_OPERATOR, "op")["status"] == NEEDS_OPERATOR


def test_push_gagal_membersihkan_file_parsial(env):
    svc, clock, vm, _ = env
    svc.create_task("shopA", "v1")
    vm.fail_push = True
    t = svc.start_next()
    with pytest.raises(RuntimeError):
        svc.prepare(vm, t["id"])
    t = svc.get_task(t["id"])
    assert t["status"] == FAILED and t["cleanup_status"] == "PENDING"
    assert svc.run_cleanup(vm) == [(t["id"], "DONE")]  # FAILED: tanpa jeda
    assert vm.files == {}


def test_cleanup_gagal_retry_lalu_tandai_gagal_tanpa_ubah_verified(env):
    svc, clock, vm, _ = env
    svc.create_task("shopA", "v1")
    t = run_to_needs_operator(svc, vm)
    svc.transition(t["id"], VERIFIED, "op", confirmed_username="shopA", evidence="e")
    clock.adv(seconds=400)
    vm.fail_delete = True
    assert svc.run_cleanup(vm) == [(t["id"], "RETRY")]
    assert svc.run_cleanup(vm) == [(t["id"], "RETRY")]
    assert svc.run_cleanup(vm) == [(t["id"], "FAILED")]
    t = svc.get_task(t["id"])
    assert t["status"] == VERIFIED and t["cleanup_status"] == "FAILED"
    assert svc.report()["cleanup_attention"] == [
        {"pad_code": "PAD1", "cleanup_status": "FAILED", "n": 1}]


def test_hapus_dianggap_gagal_bila_file_masih_ada(env):
    svc, clock, vm, _ = env
    svc.create_task("shopA", "v1")
    t = run_to_needs_operator(svc, vm)
    svc.transition(t["id"], VERIFIED, "op", confirmed_username="shopA", evidence="e")
    clock.adv(seconds=400)
    vm.delete_noop = True
    assert svc.run_cleanup(vm) == [(t["id"], "RETRY")]


def test_path_tidak_aman_tidak_pernah_dihapus(env):
    svc, clock, vm, _ = env
    svc.create_task("shopA", "v1")
    t = run_to_needs_operator(svc, vm)
    svc.transition(t["id"], VERIFIED, "op", confirmed_username="shopA", evidence="e")
    force(svc, t["id"], VERIFIED, device_file_path="/sdcard/DCIM/foto_pribadi.jpg")
    vm.files[("PAD1", "/sdcard/DCIM/foto_pribadi.jpg")] = 5
    clock.adv(seconds=400)
    assert svc.run_cleanup(vm) == [(t["id"], "FAILED")]
    assert ("PAD1", "/sdcard/DCIM/foto_pribadi.jpg") in vm.files


def test_batas_frekuensi_per_akun(tmp_path):
    clock = Clock()
    svc = Service(str(tmp_path / "r.db"), Config(min_gap_min=60, max_posts_per_day=2), clock)
    v = tmp_path / "v.mp4"; v.write_bytes(b"1")
    svc.upsert_account("A", "shopA", "PAD1")
    for i in range(3):
        svc.add_video(f"v{i}", str(v)); svc.create_task("shopA", f"v{i}")
    vm = FakeVmos()
    t = svc.start_next(); svc.prepare(vm, t["id"])
    svc.transition(t["id"], VERIFIED, "op", confirmed_username="shopA", evidence="e")
    clock.adv(seconds=400); svc.run_cleanup(vm)
    assert svc.start_next() is None            # jeda 60 menit belum lewat
    clock.adv(minutes=61)
    t = svc.start_next(); assert t is not None
    svc.prepare(vm, t["id"])
    svc.transition(t["id"], VERIFIED, "op", confirmed_username="shopA", evidence="e")
    clock.adv(seconds=400); svc.run_cleanup(vm); clock.adv(minutes=61)
    assert svc.start_next() is None            # batas 2/hari tercapai


def test_sheets_validasi_dan_tidak_membaca_kolom_sensitif(tmp_path):
    p = tmp_path / "a.csv"
    p.write_text("KODE,USERNAME,PAD CODE,VMOS,PASSWORD,COOKIE\n"
                 "A,@x,PAD1,V1,rahasia,ck\n"
                 "B,y,PAD1,V1,rahasia,ck\n"
                 "A,z,PAD2,V2,rahasia,ck\n"      # KODE ganda
                 "C,@X,PAD2,V2,rahasia,ck\n"     # USERNAME ganda
                 "D,,PAD3,V3,rahasia,ck\n"       # kosong
                 "E,w,PAD9,V9,rahasia,ck\n",     # tidak ada di API
                 encoding="utf-8")
    rows = sheets.load_csv(str(p))
    assert all(set(r) == set(sheets.ALLOWED) for r in rows)
    valid, problems = sheets.validate(rows, api_pad_codes={"PAD1", "PAD2", "PAD3"})
    assert [r["KODE"] for r in valid] == ["A", "B"]
    assert len(problems) == 4


def test_parse_row_range():
    assert sheets.parse_row_range("2-50") == (2, 50)
    assert sheets.parse_row_range("10:30") == (10, 30)
    assert sheets.parse_row_range("25") == (25, 25)
    assert sheets.parse_row_range("") == (None, None)
    assert sheets.parse_row_range(None) == (None, None)


def test_vmos_adapter_readiness():
    from app.vmos import HttpVmosAdapter
    empty_adapter = HttpVmosAdapter(access_key="", secret_key="")
    assert empty_adapter.ready is False

    ready_adapter = HttpVmosAdapter(access_key="my_ak", secret_key="my_sk")
    assert ready_adapter.ready is True


def test_timezone_rollover(tmp_path):
    # Simulasikan jam 18:00 UTC (01:00 WIB hari berikutnya dengan offset 7 jam)
    clock = Clock()
    clock.t = datetime(2026, 10, 26, 16, 59, 0)  # 23:59 WIB pada 2026-10-26
    svc = Service(str(tmp_path / "tz.db"), Config(min_gap_min=0, max_posts_per_day=1, timezone_offset_hours=7), clock)
    v = tmp_path / "v.mp4"; v.write_bytes(b"1")
    svc.upsert_account("A", "shopA", "PAD1")
    svc.add_video("v1", str(v))
    svc.add_video("v2", str(v))
    svc.create_task("shopA", "v1")
    svc.create_task("shopA", "v2")

    vm = FakeVmos()
    t1 = svc.start_next()
    assert t1 is not None
    svc.prepare(vm, t1["id"])
    svc.transition(t1["id"], VERIFIED, "op", confirmed_username="shopA", evidence="e")

    # Masih hari yang sama di WIB (23:59 WIB) -> batas 1/hari habis
    assert svc.start_next() is None

    # Majukan waktu 301 detik (melewati jeda pembersihan dan berganti hari di WIB)
    clock.adv(seconds=301)
    svc.run_cleanup(vm)

    # Kuota harian ter-reset karena hari lokal di WIB sudah berganti, dan device lock sudah lepas
    t2 = svc.start_next()
    assert t2 is not None
    assert t2["video_id"] == "v2"
