import pytest
from autosub import douyin

def test_parse_url():
    assert douyin.parse_url("https://www.douyin.com/video/7695737946679314786?x=1") == ("video", "7695737946679314786")
    assert douyin.parse_url("https://www.douyin.com/user/MS4wLjABAAAAbVICJsWY6yp15i5IhqNCVdAX34M?from=x")[0] == "user"
    assert douyin.parse_url("https://www.douyin.com/user/self?modal_id=7692515734157939811") == ("video", "7692515734157939811")
    shared = "7.94 复制打开抖音，看看【土豆的作品】日常 https://v.douyin.com/iAbC123x/ s@a.bc 02/19"
    assert douyin.parse_url(shared) == ("short", "https://v.douyin.com/iAbC123x/")
    assert douyin.parse_url("7692515734157939811") == ("video", "7692515734157939811")
    with pytest.raises(douyin.DouyinError):
        douyin.parse_url("https://youtube.com/watch?v=1")

def test_pick_stream_prefers_resolution_then_h264_then_bitrate():
    video = {"bit_rate": [
        {"bit_rate": 3000, "is_h265": 1, "play_addr": {"height": 1920, "width": 1080, "data_size": 9, "url_list": ["h265"]}},
        {"bit_rate": 2500, "is_h265": 0, "play_addr": {"height": 1920, "width": 1080, "data_size": 8, "url_list": ["h264"]}},
        {"bit_rate": 9000, "is_h265": 0, "play_addr": {"height": 1280, "width": 720, "data_size": 7, "url_list": ["hd"]}},
        {"bit_rate": 9999, "play_addr": {"url_list": []}},
    ]}
    assert douyin.pick_stream(video) == (["h264"], 1080, 1920, 8)
    assert douyin.pick_stream({"play_addr": {"url_list": ["x"], "data_size": 3}, "width": 2, "height": 4}) == (["x"], 2, 4, 3)

def test_to_item_and_safe_name():
    it = douyin.to_item({"aweme_id": 123456789012345678, "desc": "Hôm nay #vlog #iphone", "duration": 557834,
                         "create_time": 1790000000, "images": None,
                         "video": {"cover": {"url_list": ["c.jpg"]}, "play_addr": {"url_list": ["v.mp4"]}}})
    assert it.id == "123456789012345678" and it.duration == 557.8 and it.cover == "c.jpg" and not it.is_images
    assert douyin.safe_name(it.title, it.id) == "Hôm nay_123456789012345678.mp4"
    assert douyin.safe_name('a/b:c*"d', "1") == "a b c d_1.mp4"
    assert douyin.safe_name("", "9") == "douyin_9.mp4"
    assert "play_urls" not in it.public()

def test_session_roundtrip():
    assert douyin.logged_in() is False
    douyin.save_session([{"name": "sessionid", "value": "abc", "domain": ".douyin.com", "path": "/"}])
    assert douyin.logged_in() is True
    douyin.clear_session()
    assert douyin.logged_in() is False

def test_download_tries_mirrors(tmp_path, monkeypatch):
    import io, urllib.request
    calls = []
    class R(io.BytesIO):
        headers = {"Content-Length": "6"}
        def __enter__(self): return self
        def __exit__(self, *a): pass
    def fake(req, timeout):
        calls.append(req.full_url)
        if "bad" in req.full_url:
            raise OSError("403")
        return R(b"ftypmp")
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    it = douyin.VideoItem(id="1", title="t", duration=1, cover="", created=0, play_urls=["http://bad/1", "http://good/1"])
    out = douyin.download(it, tmp_path / "a.mp4")
    assert out.read_bytes() == b"ftypmp" and calls == ["http://bad/1", "http://good/1"]
    with pytest.raises(douyin.DouyinError):
        douyin.download(douyin.VideoItem(id="2", title="", duration=0, cover="", created=0, is_images=True), tmp_path / "b.mp4")
