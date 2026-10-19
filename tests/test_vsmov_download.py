import http.client
import io
import struct
import subprocess
import threading
import urllib.error
import urllib.request
import zlib
from pathlib import Path

import pytest

from autosub import media, vsmov
from autosub.vsmov import VsmovError
from tests.fixtures import make_video

DATA = Path(__file__).parent / "data" / "vsmov"
EMBED = (DATA / "embed.html").read_text(encoding="utf-8")
HASH = "3c499dca-dbf3-44e2-9317-7b69d6af6147"
BASE = "https://v6.streamvsmov.com"
EMBED_URL = f"{BASE}/video/{HASH}"
MASTER = f"{BASE}/stream/{HASH}/master.m3u8"

def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

# 0x47 every 188 bytes inside the image: a scan that starts at 0 would lock onto it
PNG = (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
       + _chunk(b"tEXt", (b"\x47" + b"\x00" * 187) * 4) + _chunk(b"IEND", b""))
JUNK = b"\x00\x01" * 60  # the live site has bytes between IEND and the first TS packet

@pytest.fixture(scope="module")
def segs(tmp_path_factory):
    d = tmp_path_factory.mktemp("segs")
    clip = make_video(d / "clip.mp4", seconds=3, with_text=False)
    # make_video's GOP is longer than the clip, so re-encode with 1 s keyframes before cutting
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(clip), "-c:v", "libx264", "-preset", "ultrafast", "-g", "25",
                    "-c:a", "copy", "-f", "segment", "-segment_time", "1", str(d / "seg%d.ts")], check=True)
    out = [p.read_bytes() for p in sorted(d.glob("seg*.ts"), key=lambda p: int(p.stem[3:]))]
    assert len(out) == 3
    return out, media.probe(clip).duration

def test_parse_embed_unsigned_and_subtitles():
    e = vsmov.parse_embed(EMBED)
    assert e.base_url == BASE and e.video_hash == HASH and e.master_url == MASTER
    assert [s.code for s in e.subtitles] == ["vie", "eng"]
    assert e.subtitles[0].url == f"{BASE}/video/{HASH}/subtitle/vie_1785443679677_c0nzvu.vtt"

def test_parse_embed_prefers_signed_url():
    html = EMBED.replace("enableSignedUrl: false", "enableSignedUrl: true").replace(
        'signedMasterUrl: ""', 'signedMasterUrl: "https://x/s.m3u8?sig=1"')
    assert vsmov.parse_embed(html).master_url == "https://x/s.m3u8?sig=1"

def test_parse_embed_without_hash_fails():
    with pytest.raises(VsmovError, match="Không đọc được trang phát"):
        vsmov.parse_embed("<html></html>")

def test_pick_variant_highest_up_to_1080():
    master = ("#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=854x480\n480/index.m3u8\n"
              "#EXT-X-STREAM-INF:BANDWIDTH=5000000,RESOLUTION=1920x1080\n1080/index.m3u8\n"
              "#EXT-X-STREAM-INF:BANDWIDTH=15000000,RESOLUTION=3840x2160\n2160/index.m3u8\n")
    assert vsmov.pick_variant(master, "https://h/stream/x/master.m3u8") == "https://h/stream/x/1080/index.m3u8"
    only_4k = "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1,RESOLUTION=3840x2160\na.m3u8\n#EXT-X-STREAM-INF:BANDWIDTH=9\nb.m3u8\n"
    assert vsmov.pick_variant(only_4k, "https://h/m.m3u8") == "https://h/b.m3u8"
    media_pl = "#EXTM3U\n#EXTINF:6.0,\nseg1.png\n#EXT-X-ENDLIST\n"
    assert vsmov.pick_variant(media_pl, "https://h/m.m3u8") == "https://h/m.m3u8"

def test_segment_urls_absolute():
    pl = "#EXTM3U\n#EXTINF:6.0,\nhttps://cdn/a_1.png\n\n#EXTINF:6.0,\nb_2.png\n#EXT-X-ENDLIST\n"
    assert vsmov.segment_urls(pl, "https://h/s/master.m3u8") == ["https://cdn/a_1.png", "https://h/s/b_2.png"]

def test_strip_png_skips_image_with_fake_sync(segs):
    seg = segs[0][0]
    assert vsmov.strip_png(PNG + JUNK + seg) == seg

def test_strip_png_plain_ts_and_garbage(segs):
    seg = segs[0][0]
    assert vsmov.strip_png(seg) == seg
    with pytest.raises(VsmovError, match="không đúng định dạng"):
        vsmov.strip_png(PNG)

class _Truncated(io.BytesIO):
    def read(self, *a):
        raise http.client.IncompleteRead(b"G" * 10, 1000)

def _serve(monkeypatch, segs, fail: dict[int, int], truncated: dict[int, int] | None = None, on_fail=None):
    """embed -> master (already a media playlist) -> 3 png-wrapped segments.
    fail[n] / truncated[n] = times segment n raises URLError / returns a body cut short. Returns (requests, sleeps)."""
    truncated = truncated or {}
    pl = "#EXTM3U\n#EXT-X-TARGETDURATION:1\n" + "".join(
        f"#EXTINF:1.0,\nhttps://p25.streamvsmov.com/file/k/{HASH}/file-tiktok_{n}.png\n" for n in (1, 2, 3)) + "#EXT-X-ENDLIST\n"
    seen = []

    def urlopen(req, timeout=None):
        url = req.full_url
        seen.append(req)
        if url == EMBED_URL:
            return io.BytesIO(EMBED.encode())
        if url == MASTER:
            return io.BytesIO(pl.encode())
        n = int(url.rsplit("_", 1)[1].split(".")[0])
        if fail.get(n, 0):
            fail[n] -= 1
            if on_fail:
                on_fail()
            raise urllib.error.URLError("boom")
        if truncated.get(n, 0):
            truncated[n] -= 1
            return _Truncated()
        return io.BytesIO(PNG + JUNK + segs[n - 1])

    sleeps = []
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(vsmov.time, "sleep", sleeps.append)
    return seen, sleeps

def _leftovers(tmp_path):
    return [p.name for p in tmp_path.iterdir() if p.name.startswith(".vsmov-") or p.name.endswith(".part")]

def test_download_assembles_segments_in_order(tmp_path, monkeypatch, segs):
    seen, sleeps = _serve(monkeypatch, segs[0], {2: 1}, truncated={3: 1})
    ticks = []
    out = tmp_path / "movie.mp4"
    e = vsmov.download(EMBED_URL, out, progress=ticks.append, workers=3)
    assert e.video_hash == HASH and out.exists()
    info = media.probe(out)
    assert info.has_audio and abs(info.duration - segs[1]) < 0.5
    assert ticks[-1] == 1.0 and len(ticks) == 3
    assert _leftovers(tmp_path) == [] and not (tmp_path / "movie.tmp.mp4").exists()
    stream = [r for r in seen if r.full_url != EMBED_URL]
    assert all(r.get_header("Referer") == EMBED_URL and r.get_header("Origin") == BASE for r in stream)
    assert all(r.get_header("User-agent") for r in seen)
    assert sleeps == [1, 1]  # segment 2 (URLError) and segment 3 (IncompleteRead) each retried once

def test_download_fails_after_retries_names_segment(tmp_path, monkeypatch, segs):
    _, sleeps = _serve(monkeypatch, segs[0], {2: 99})
    with pytest.raises(VsmovError, match="Tải đoạn 2/3"):
        vsmov.download(EMBED_URL, tmp_path / "movie.mp4", workers=2)
    assert sleeps == [1, 2]
    assert _leftovers(tmp_path) == [] and not (tmp_path / "movie.mp4").exists()

def test_download_cancelled(tmp_path, monkeypatch, segs):
    _serve(monkeypatch, segs[0], {})
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(VsmovError, match="Đã huỷ"):
        vsmov.download(EMBED_URL, tmp_path / "movie.mp4", cancel=cancel)
    assert _leftovers(tmp_path) == []

def test_fetch_subtitle_sends_referer(monkeypatch):
    seen = []

    def urlopen(req, timeout=None):
        seen.append(req)
        return io.BytesIO("﻿WEBVTT\n\n1\n00:00:01.000 --> 00:00:02.000\nXin chào\n".encode())

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    text = vsmov.fetch_subtitle(f"{BASE}/video/{HASH}/subtitle/vie.vtt", EMBED_URL)
    assert text.startswith("WEBVTT") and "Xin chào" in text
    assert seen[0].get_header("Referer") == EMBED_URL

def test_download_cancel_interrupts_retry_wait(tmp_path, monkeypatch, segs):
    cancel = threading.Event()
    _, sleeps = _serve(monkeypatch, segs[0], {2: 99}, on_fail=cancel.set)
    with pytest.raises(VsmovError, match="Đã huỷ"):
        vsmov.download(EMBED_URL, tmp_path / "movie.mp4", cancel=cancel, workers=1)
    assert sleeps == []  # waited on the event, which was already set, instead of time.sleep
    assert _leftovers(tmp_path) == []

def test_truncated_embed_read_is_vsmov_error(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _Truncated())
    with pytest.raises(VsmovError, match="Không kết nối được vsmov"):
        vsmov.download(EMBED_URL, Path("unused.mp4"))
    with pytest.raises(VsmovError, match="Không tải được phụ đề"):
        vsmov.fetch_subtitle(f"{BASE}/x.vtt", EMBED_URL)
