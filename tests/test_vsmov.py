import io
import json
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from autosub import vsmov
from autosub.vsmov import VsmovError

DATA = Path(__file__).parent / "data" / "vsmov"
SINGLE = "avengers-4-hoi-ket-178544376755563"
SERIES = "7-ngay-ben-nhau"
TRAILER = "kiem-dinh-thuc-te-hau-truong-sieu-mau-nuoc-my-phan-1"


@pytest.fixture(autouse=True)
def fake_api(monkeypatch):
    routes = {
        "/api/tim-kiem": "tim-kiem", "/api/danh-sach/phim-moi-cap-nhat": "latest",
        "/api/the-loai/bi-an": "the-loai-bi-an", "/api/the-loai": "the-loai", "/api/quoc-gia": "quoc-gia",
        f"/api/phim/{SINGLE}": "phim-single", f"/api/phim/{SERIES}": "phim-series", f"/api/phim/{TRAILER}": "phim-trailer",
    }
    seen = []

    def urlopen(req, timeout=None):
        seen.append((req, timeout))
        path = urllib.parse.urlparse(req.full_url).path
        return io.BytesIO((DATA / f"{routes[path]}.json").read_bytes())

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    return seen


def test_search_parses_cards_and_pagination(fake_api):
    p = vsmov.search("avengers", limit=2)
    c = p.items[0]
    assert c.origin_name == "Avengers: Endgame" and c.rating == 8.2 and c.year == 2019 and p.total_pages == 5
    req, timeout = fake_api[0]
    assert req.get_header("User-agent") and timeout == 20 and "keyword=avengers" in req.full_url


def test_latest_and_listing():
    assert vsmov.latest().total_pages > 1
    assert vsmov.listing("the-loai", "bi-an").items


def test_movie_single_default_server_skips_4k():
    d = vsmov.movie(SINGLE)
    assert d.meta.type == "single" and d.meta.origin_name == "Avengers: Endgame"
    assert d.meta.categories[0] == "Phiêu Lưu" and d.meta.countries == ["Âu Mỹ"] and d.meta.directors == ["Anthony Russo", "Joe Russo"]
    assert [s.name for s in d.servers] == ["Vietsub #1", "4K"]
    assert d.default_server == "Vietsub #1" and d.servers[0].episodes[0].slug == "tap-full"
    assert d.servers[0].episodes[0].embed.startswith("https://")


def test_movie_series_episodes_in_order():
    d = vsmov.movie(SERIES)
    assert d.meta.type == "series"
    assert [e.slug for e in d.servers[0].episodes][:3] == ["tap-1", "tap-2", "tap-3"]


def test_trailer_only_movie_has_no_servers():
    d = vsmov.movie(TRAILER)
    assert d.servers == [] and d.default_server == ""


def test_filters_reads_data_items_shape():
    f = vsmov.filters()
    assert {"name": "Bí Ẩn", "slug": "bi-an"} in f["genres"] and f["countries"]


def test_network_error_is_vsmov_error(monkeypatch):
    def boom(*a, **k):
        raise OSError("down")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    with pytest.raises(VsmovError, match="Không kết nối được vsmov"):
        vsmov.search("x")


def test_bad_json_is_vsmov_error(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b"<html>"))
    with pytest.raises(VsmovError):
        vsmov.latest()
