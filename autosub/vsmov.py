"""Client for the public vsmov.com movie API (stdlib only)."""
import functools
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Literal

from .douyin import UA
from .models import Episode, MovieMeta

API = "https://vsmov.com/api"


class VsmovError(Exception):
    pass


@dataclass
class Card:
    slug: str
    name: str
    origin_name: str
    year: int | None
    poster: str
    thumb: str
    rating: float | None


@dataclass
class Page:
    items: list[Card]
    page: int
    total_pages: int


@dataclass
class Server:
    name: str
    episodes: list[Episode] = field(default_factory=list)


@dataclass
class MovieDetail:
    meta: MovieMeta
    servers: list[Server]
    default_server: str


def _get(path: str, **params) -> dict:
    q = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
    url = f"{API}/{path}" + (f"?{q}" if q else "")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except (OSError, ValueError) as e:  # URLError/HTTPError are OSError; bad JSON is ValueError
        raise VsmovError(f"Không kết nối được vsmov: {e}") from e


def _safe(fn):
    # malformed upstream shapes surface as VsmovError, not TypeError/AttributeError/...
    @functools.wraps(fn)
    def wrap(*a, **k):
        try:
            return fn(*a, **k)
        except (AttributeError, TypeError, KeyError, ValueError, OverflowError) as e:
            raise VsmovError(f"Dữ liệu vsmov không hợp lệ: {e}") from e
    return wrap


def _items(d: dict) -> list[dict]:
    # two shapes: {"items": [...]} and {"data": {"items": [...]}}
    return d.get("items") or (d.get("data") or {}).get("items") or []


def _str(v) -> str:
    return v if isinstance(v, str) else ""


def _int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError, OverflowError):
        return None


def _names(v) -> list[str]:
    return [_str(c.get("name")) for c in v or [] if isinstance(c, dict) and c.get("name")]


def _rating(it: dict) -> float | None:
    try:
        return float((it.get("tmdb") or {}).get("vote_average"))
    except (TypeError, ValueError, AttributeError):
        return None


def _page(d: dict, page: int) -> Page:
    cards = [Card(_str(it.get("slug")), _str(it.get("name")), _str(it.get("origin_name")), _int(it.get("year")),
                  _str(it.get("poster_url")), _str(it.get("thumb_url")), _rating(it))
             for it in _items(d) if isinstance(it, dict)]
    data = d.get("data") or {}
    pg = d.get("pagination") or (data.get("params") or {}).get("pagination") or {}
    return Page(cards, _int(pg.get("currentPage")) or page, _int(pg.get("totalPages")) or 1)


@_safe
def latest(page: int = 1) -> Page:
    return _page(_get("danh-sach/phim-moi-cap-nhat", page=page), page)


@_safe
def search(keyword: str, page: int = 1, limit: int = 24) -> Page:
    return _page(_get("tim-kiem", keyword=keyword, page=page, limit=limit), page)


@_safe
def listing(kind: Literal["phim-le", "phim-bo", "the-loai", "quoc-gia"], slug: str = "", page: int = 1) -> Page:
    slug = slug.strip()
    if kind in ("the-loai", "quoc-gia") and not slug:
        raise VsmovError("Thiếu thể loại/quốc gia để lọc phim")
    path = f"danh-sach/{kind}" if kind in ("phim-le", "phim-bo") else f"{kind}/{urllib.parse.quote(slug)}"
    return _page(_get(path, page=page), page)


@_safe
def filters() -> dict[str, list[dict]]:
    def load(path):
        return [{"name": _str(i.get("name")), "slug": _str(i.get("slug"))} for i in _items(_get(path)) if isinstance(i, dict)]
    return {"genres": load("the-loai"), "countries": load("quoc-gia")}


@_safe
def movie(slug: str) -> MovieDetail:
    d = _get(f"phim/{urllib.parse.quote(slug)}")
    m = d.get("movie")
    if not isinstance(m, dict) or not m:
        raise VsmovError("Không tìm thấy phim trên vsmov")
    meta = MovieMeta(
        slug=_str(m.get("slug")) or slug, name=_str(m.get("name")), origin_name=_str(m.get("origin_name")),
        year=_int(m.get("year")), type=_str(m.get("type")) or "single", poster_url=_str(m.get("poster_url")),
        thumb_url=_str(m.get("thumb_url")), time=_str(m.get("time")), lang=_str(m.get("lang")),
        content=_str(m.get("content")), actors=[_str(x) for x in m.get("actor") or [] if x],
        directors=[_str(x) for x in m.get("director") or [] if x],
        categories=_names(m.get("category")), countries=_names(m.get("country")))
    servers = [Server(" ".join(_str(s.get("server_name")).split()),
                      [Episode(name=_str(e.get("name")), slug=_str(e.get("slug")), embed=_str(e.get("link_embed")))
                       for e in s.get("server_data") or [] if isinstance(e, dict)])
               for s in d.get("episodes") or [] if isinstance(s, dict)]
    servers = [s for s in servers if s.episodes]
    default = next((s.name for s in servers if "4K" not in s.name), servers[0].name if servers else "")
    return MovieDetail(meta, servers, default)
