from unittest.mock import MagicMock, patch
from app.auto_poster import ShopeeAutoPoster, clean_adb_text
from app.states import VERIFIED


def test_clean_adb_text():
    assert clean_adb_text("Hello World") == "Hello%sWorld"
    assert clean_adb_text("Promo & Diskon!") == "Promo%s\\&%sDiskon!"
    # Non-ascii like emojis stripped
    assert clean_adb_text("Best Seller ✨ Video 🚀") == "Best%sSeller%sVideo"


@patch("time.sleep")
def test_auto_poster_run_task(mock_sleep):
    mock_vmos = MagicMock()
    mock_vmos._get_target_serial.return_value = "127.0.0.1:5555"
    mock_vmos._run_adb.return_value = (0, "mCurrentFocus=Window{123 com.shopee.my/Home}", "")

    mock_svc = MagicMock()
    mock_svc.get_task.return_value = {
        "id": 1,
        "username": "purwantowwilliams",
        "pad_code": "AC32010950523",
        "caption": "Test Caption #shopee",
        "product_link": "https://shopee.com.my/product/123/456",
        "device_file_path": "/sdcard/Movies/autopost/task_1/video.mp4"
    }

    poster = ShopeeAutoPoster(mock_vmos, mock_svc)
    res = poster.run_task(1)

    assert res["status"] == "success"
    assert res["task_id"] == 1
    assert res["pad_code"] == "AC32010950523"
    assert res["username"] == "purwantowwilliams"

    mock_svc.transition.assert_called_once()
    args, kwargs = mock_svc.transition.call_args
    assert args[0] == 1
    assert args[1] == VERIFIED
    assert kwargs["confirmed_username"] == "purwantowwilliams"


@patch("time.sleep")
def test_auto_poster_cancellation(mock_sleep):
    from app.auto_poster import cancel_task_execution
    mock_vmos = MagicMock()
    mock_vmos._get_target_serial.return_value = "127.0.0.1:5555"
    mock_vmos._run_adb.return_value = (0, "", "")

    mock_svc = MagicMock()
    mock_svc.get_task.return_value = {
        "id": 99,
        "username": "purwantowwilliams",
        "pad_code": "AC32010950523",
        "status": "QUEUED"
    }

    poster = ShopeeAutoPoster(mock_vmos, mock_svc)
    cancel_task_execution(99)
    res = poster.run_task(99)
    assert res["status"] == "cancelled"
    # Pastikan adb dipanggil untuk force-stop dan keyevent 3
    mock_vmos._run_adb.assert_any_call(["-s", "127.0.0.1:5555", "shell", "am", "force-stop", "com.shopee.my"], timeout=30)
    mock_vmos._run_adb.assert_any_call(["-s", "127.0.0.1:5555", "shell", "input", "keyevent", "3"], timeout=30)

