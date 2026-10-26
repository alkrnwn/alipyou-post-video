import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.vmos import FakeVmos


def test_api_alur_lengkap(tmp_path):
    v = tmp_path / "v.mp4"; v.write_bytes(b"abc")
    csv = tmp_path / "a.csv"
    csv.write_text("KODE,USERNAME,PAD CODE,VMOS\nA,shopA,PAD1,V1\n", encoding="utf-8")
    app = create_app(str(tmp_path / "a.db"), vmos=FakeVmos(), background=False)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        assert c.post("/sync/csv", json={"path": str(csv)}).json()["synced"] == 1
        c.post("/videos", json={"id": "v1", "master_path": str(v)})
        tid = c.post("/tasks", json={"username": "shopA", "video_id": "v1"}).json()["id"]
        assert c.post("/tasks", json={"username": "shopA", "video_id": "v1"}).status_code == 409
        assert c.post("/queue/start-next", json={}).json()["status"] == "PREPARING"
        assert c.post(f"/tasks/{tid}/prepare").json()["status"] == "NEEDS_OPERATOR"
        bad = c.post(f"/tasks/{tid}/transition",
                     json={"to": "VERIFIED", "confirmed_username": "lain", "evidence": "x"})
        assert bad.status_code == 409
        ok = c.post(f"/tasks/{tid}/transition",
                    json={"to": "VERIFIED", "confirmed_username": "shopA", "evidence": "x"})
        assert ok.json()["cleanup_status"] == "PENDING"
        assert c.get("/report").json()["by_status"]["VERIFIED"] == 1


def test_ui_statis_token_dan_host(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOPOST_TOKEN", "rahasia")
    v = tmp_path / "v.mp4"; v.write_bytes(b"abc")
    app = create_app(str(tmp_path / "b.db"), vmos=FakeVmos(), background=False)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        assert "Shopee Video" in c.get("/").text
        assert c.get("/static/app.js").status_code == 200
        assert c.get("/report").status_code == 403                      # tanpa token
        h = {"X-Token": "rahasia"}
        assert c.get("/report", headers=h).status_code == 200
        c.post("/videos", json={"id": "v1", "master_path": str(v)}, headers=h)
        assert c.get("/videos", headers=h).json()[0]["id"] == "v1"
        assert c.get("/config", headers=h).json()["dry_run"] is True
    with TestClient(app, base_url="http://evil.example") as c:           # DNS rebinding
        assert c.get("/", headers={"X-Token": "rahasia"}).status_code == 403


def test_batch_tugas_banyak_akun_dan_start_next_butuh_adapter(tmp_path):
    from app.vmos import HttpVmosAdapter
    v = tmp_path / "v.mp4"; v.write_bytes(b"abc")
    csv = tmp_path / "a.csv"
    csv.write_text("KODE,USERNAME,PAD CODE,VMOS\nA,a,PAD1,V1\nB,b,PAD1,V1\nC,c,PAD2,V2\n", encoding="utf-8")
    app = create_app(str(tmp_path / "c.db"), vmos=HttpVmosAdapter(), background=False)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        c.post("/sync/csv", json={"path": str(csv)})
        assert len(c.get("/accounts").json()) == 3
        c.post("/videos", json={"id": "v1", "master_path": str(v)})
        r = c.post("/tasks/batch", json={"usernames": ["a", "b", "zzz"], "video_id": "v1", "batch": "x"}).json()
        assert len(r["created"]) == 2 and len(r["errors"]) == 1
        assert c.post("/queue/start-next", json={}).status_code == 409   # adapter belum siap


def test_sync_sheets_endpoint(tmp_path, monkeypatch):
    from app import sheets
    app = create_app(str(tmp_path / "d.db"), vmos=FakeVmos(), background=False)

    # Mock load_google_sheet
    def fake_load(spreadsheet_id, range_a1, service_account_file):
        return [
            {"KODE": "S1", "USERNAME": "gsheet_shop", "PAD CODE": "PAD1", "VMOS": "V1"}
        ]

    monkeypatch.setattr(sheets, "load_google_sheet", fake_load)

    with TestClient(app, base_url="http://127.0.0.1") as c:
        res = c.post("/sync/sheets", json={
            "spreadsheet_id": "sheet_123",
            "range_a1": "A:D",
            "service_account_file": "sa.json"
        })
        assert res.status_code == 200
        assert res.json()["synced"] == 1
        assert c.get("/accounts").json()[0]["username"] == "gsheet_shop"


def test_sync_url_endpoint(tmp_path, monkeypatch):
    from app import sheets
    app = create_app(str(tmp_path / "e.db"), vmos=FakeVmos(), background=False)

    def fake_load_url(url, start_row=None, end_row=None):
        assert "spreadsheets" in url
        assert start_row == 2
        assert end_row == 50
        return [
            {"KODE": "AK1", "USERNAME": "shop_url", "PAD CODE": "PAD9", "VMOS": "V9"}
        ]

    monkeypatch.setattr(sheets, "load_google_sheet_url", fake_load_url)

    with TestClient(app, base_url="http://127.0.0.1") as c:
        res = c.post("/sync/url", json={
            "url": "https://docs.google.com/spreadsheets/d/17bQC4dF0C3f21Y3IdCS50cVC4w87HvSjvnm2_IK4af8/edit?gid=898202278#gid=898202278",
            "row_range": "2-50"
        })
        assert res.status_code == 200
        assert res.json()["synced"] == 1
        assert res.json()["range"] == "Baris 2 - 50"
        assert c.get("/accounts").json()[0]["username"] == "shop_url"


def test_operator_task_dan_shopee_extract(tmp_path):
    csv = tmp_path / "a.csv"
    csv.write_text("KODE,USERNAME,PAD CODE,VMOS\nAKUN1,shop_op,PAD1,V1\n", encoding="utf-8")
    app = create_app(str(tmp_path / "op.db"), vmos=FakeVmos(), background=False)

    with TestClient(app, base_url="http://127.0.0.1") as c:
        c.post("/sync/csv", json={"path": str(csv)})

        # Test shopee extract (default random / acak)
        ext = c.post("/api/shopee/extract", json={"url": "https://shopee.co.id/product/123/456", "category": "Random"}).json()
        assert ext["success"] is True
        assert "kuncian_prompt" in ext
        assert "video_prompt" in ext["kuncian_prompt"]
        assert "voiceover" in ext["kuncian_prompt"]
        assert ext["kuncian_prompt"]["category"] in [
            "Premium UGC / Soft-Sell",
            "Review / Unboxing",
            "Problem-Solution",
            "Price & Value",
            "Lifestyle / Aspirational",
            "Curiosity / Trending",
            "POV / Product Only",
        ]

        # Test operator task creation
        flow_url = "https://flow.google.com/shared/video/6d909cf9-f45d-43e3-8363-24a4542b07b4"
        res = c.post("/api/tasks/operator", json={
            "username": "shop_op",
            "video_url": flow_url,
            "product_link": "https://shopee.co.id/product/123/456",
            "caption": ext["caption"],
            "prompt": ext["kuncian_prompt"]["video_prompt"]
        }).json()
        assert res["ok"] is True
        task = res["task"]
        assert task["username"] == "shop_op"
        assert task["product_link"] == "https://shopee.co.id/product/123/456"
        assert task["prompt"] == ext["kuncian_prompt"]["video_prompt"]
        assert task["status"] == "QUEUED"

        # Test download image endpoint
        from app import shopee_scraper
        def fake_download(image_url, filename=None, open_folder=False):
            return {"ok": True, "path": "C:\\Downloads\\test.jpg", "filename": "test.jpg", "size_kb": 50.0}
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(shopee_scraper, "download_image_to_pc", fake_download)
        dl_res = c.post("/api/shopee/download-image", json={"url": "https://example.com/foto.jpg", "open_folder": False}).json()
        assert dl_res["ok"] is True
        assert dl_res["filename"] == "test.jpg"
        monkeypatch.undo()


def test_reset_all_endpoint(tmp_path):
    csv = tmp_path / "a.csv"
    csv.write_text("KODE,USERNAME,PAD CODE,VMOS\nAKUN1,shop_rst,PAD1,V1\n", encoding="utf-8")
    app = create_app(str(tmp_path / "rst.db"), vmos=FakeVmos(), background=False)

    with TestClient(app, base_url="http://127.0.0.1") as c:
        c.post("/sync/csv", json={"path": str(csv)})
        assert len(c.get("/accounts").json()) == 1

        res = c.post("/api/reset-all")
        assert res.status_code == 200
        assert res.json()["ok"] is True
        assert len(c.get("/accounts").json()) == 0


def test_operator_task_same_account_different_product(tmp_path):
    csv = tmp_path / "a.csv"
    csv.write_text("KODE,USERNAME,PAD CODE,VMOS\nAKUN1,shop_repeat,PAD1,V1\n", encoding="utf-8")
    app = create_app(str(tmp_path / "rep.db"), vmos=FakeVmos(), background=False)

    with TestClient(app, base_url="http://127.0.0.1") as c:
        c.post("/sync/csv", json={"path": str(csv)})

        # Task 1: Product A with Video 1
        res1 = c.post("/api/tasks/operator", json={
            "username": "shop_repeat",
            "video_url": "https://flow.google.com/shared/video/abc",
            "product_link": "https://shopee.com.my/product/1/1",
            "caption": "Cap 1"
        })
        assert res1.status_code == 200
        assert res1.json()["ok"] is True

        # Task 2: Same account, same video, DIFFERENT product
        res2 = c.post("/api/tasks/operator", json={
            "username": "shop_repeat",
            "video_url": "https://flow.google.com/shared/video/abc",
            "product_link": "https://shopee.com.my/product/2/2",
            "caption": "Cap 2"
        })
        assert res2.status_code == 200
        assert res2.json()["ok"] is True
        assert res1.json()["task"]["id"] != res2.json()["task"]["id"]
        assert len(c.get("/tasks").json()) == 2


def test_queue_process_next_empty(tmp_path):
    app = create_app(str(tmp_path / "empty.db"), vmos=FakeVmos(), background=False)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        res = c.post("/queue/process-next", json={})
        assert res.status_code == 200
        assert res.json()["task_id"] is None
        assert res.json()["has_more"] is False


def test_vmos_config_dan_test_api(tmp_path):
    from app.vmos import HttpVmosAdapter
    db_path = str(tmp_path / "vmos_cfg.db")
    vm = HttpVmosAdapter(access_key="", secret_key="")
    assert vm.ready is False

    app = create_app(db_path, vmos=vm, background=False)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        # 1. Get initial config
        res_cfg = c.get("/api/vmos/config")
        assert res_cfg.status_code == 200
        data = res_cfg.json()
        assert data["ready"] is False
        assert data["access_key"] == ""

        # 2. Test connection with empty keys fails
        res_test_empty = c.post("/api/vmos/test", json={"access_key": "", "secret_key": ""})
        assert res_test_empty.status_code == 200
        assert res_test_empty.json()["ok"] is False

        # 3. Save config
        res_save = c.post("/api/vmos/config", json={
            "access_key": "AK_TEST_123",
            "secret_key": "SK_TEST_456",
            "base_url": "https://api.vmoscloud.com"
        })
        assert res_save.status_code == 200
        assert res_save.json()["ok"] is True
        assert res_save.json()["adapter_ready"] is True
        assert vm.ready is True
        assert vm.access_key == "AK_TEST_123"
        assert vm.secret_key == "SK_TEST_456"

        # 4. Config should reflect saved keys
        res_cfg2 = c.get("/api/vmos/config").json()
        assert res_cfg2["ready"] is True
        assert res_cfg2["access_key"] == "AK_TEST_123"
        assert res_cfg2["secret_key"] == "SK_TEST_456"

    # 5. New app instance should load saved keys from DB
    vm2 = HttpVmosAdapter(access_key="", secret_key="")
    app2 = create_app(db_path, vmos=vm2, background=False)
    with TestClient(app2, base_url="http://127.0.0.1") as c2:
        cfg = c2.get("/api/vmos/config").json()
        assert cfg["ready"] is True
        assert cfg["access_key"] == "AK_TEST_123"

    import os
    os.environ.pop("VMOS_ACCESS_KEY", None)
    os.environ.pop("VMOS_SECRET_KEY", None)


def test_storage_stats_dan_clean_cache(tmp_path):
    app = create_app(str(tmp_path / "storage.db"), vmos=FakeVmos(), background=False)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        res = c.get("/api/storage/stats")
        assert res.status_code == 200
        data = res.json()
        assert "db_size_bytes" in data
        assert "cache_size_bytes" in data

        res_clean = c.post("/api/storage/clean-cache")
        assert res_clean.status_code == 200
        assert "deleted" in res_clean.json()

        res_logs = c.get("/api/logs/recent")
        assert res_logs.status_code == 200
        assert "lines" in res_logs.json()


def test_task_screenshot_api(tmp_path):
    v = tmp_path / "v.mp4"
    v.write_bytes(b"dummy_video_bytes")
    csv = tmp_path / "a.csv"
    csv.write_text("KODE,USERNAME,PAD CODE,VMOS\nA1,shopee_test,PAD_TEST,V1\n", encoding="utf-8")
    app = create_app(str(tmp_path / "sc.db"), vmos=FakeVmos(), background=False)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        c.post("/sync/csv", json={"path": str(csv)})
        c.post("/videos", json={"id": "v1", "master_path": str(v)})
        tid = c.post("/tasks", json={"username": "shopee_test", "video_id": "v1"}).json()["id"]

        # 404 on nonexistent task
        assert c.get("/api/tasks/9999/screenshot").status_code == 404

        # 200 SVG fallback on existing task
        res = c.get(f"/api/tasks/{tid}/screenshot")
        assert res.status_code == 200
        assert "image/svg+xml" in res.headers["content-type"]
        assert b"shopee_test" in res.content
        assert b"PAD_TEST" in res.content





