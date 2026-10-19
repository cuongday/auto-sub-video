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
    p = vsmov.latest()
    assert p.page == 1 and p.total_pages == 857 and p.items[0].slug == "7-ngay-ben-nhau"
    g = vsmov.listing("the-loai", "bi-an")
    assert g.page == 1 and g.total_pages == 129 and g.items[0].slug == "thu-tinh"


@pytest.mark.parametrize("kind", ["the-loai", "quoc-gia"])
def test_listing_requires_slug_for_genre_and_country(kind):
    with pytest.raises(VsmovError):
        vsmov.listing(kind, "  ")


def _serve(monkeypatch, obj):
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: io.BytesIO(json.dumps(obj).encode()))


def test_movie_null_fields_do_not_break(monkeypatch):
    _serve(monkeypatch, {"movie": {"name": "X", "slug": None, "origin_name": None, "year": "", "type": None,
                                   "poster_url": None, "thumb_url": None, "time": None, "lang": None, "content": None,
                                   "actor": None, "director": None, "category": [None, {"id": 1}, {"name": "A"}],
                                   "country": None},
                         "episodes": [{"server_name": None, "server_data": [{"name": None, "slug": None, "link_embed": None}]}]})
    d = vsmov.movie("s")
    assert d.meta.year is None and d.meta.time == "" and d.meta.slug == "s" and d.meta.type == "single"
    assert d.meta.categories == ["A"] and d.meta.countries == []
    assert d.servers[0].episodes[0].embed == ""


def test_malformed_pagination_does_not_break(monkeypatch):
    _serve(monkeypatch, {"items": [{"slug": "a", "name": "A", "year": "x", "tmdb": None}],
                         "pagination": {"currentPage": "?", "totalPages": None}})
    p = vsmov.latest(3)
    assert p.page == 3 and p.total_pages == 1 and p.items[0].year is None and p.items[0].rating is None
    _serve(monkeypatch, {"data": {"items": [], "params": None}})
    assert vsmov.latest().total_pages == 1


@pytest.mark.parametrize("fn,obj", [
    (lambda: vsmov.latest(), [1, 2]),
    (lambda: vsmov.filters(), [1]),
    (lambda: vsmov.movie("s"), []),
    (lambda: vsmov.latest(), {"data": 5}),
    (lambda: vsmov.latest(), {"items": 5}),
    (lambda: vsmov.movie("s"), {"movie": {"name": "X", "actor": 5}}),
    (lambda: vsmov.movie("s"), {"movie": {"name": "X"}, "episodes": 5}),
    (lambda: vsmov.movie("s"), {"movie": {"name": "X"}, "episodes": [{"server_data": 5}]}),
])
def test_garbage_shapes_are_vsmov_error(monkeypatch, fn, obj):
    _serve(monkeypatch, obj)
    with pytest.raises(VsmovError):
        fn()


def test_movie_not_found(monkeypatch):
    _serve(monkeypatch, {"status": False, "movie": None})
    with pytest.raises(VsmovError, match="Không tìm thấy phim"):
        vsmov.movie("nope")


def test_only_4k_server_is_default_fallback(monkeypatch):
    ep = {"name": "Full", "slug": "tap-full", "link_embed": "https://x"}
    _serve(monkeypatch, {"movie": {"name": "X"}, "episodes": [
        {"server_name": "4K  A", "server_data": [ep]}, {"server_name": "4K B", "server_data": [ep]}]})
    assert vsmov.movie("s").default_server == "4K A"


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
