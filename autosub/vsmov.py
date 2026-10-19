"""Client for the public vsmov.com movie API (stdlib only)."""
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


def _items(d: dict) -> list[dict]:
    # two shapes: {"items": [...]} and {"data": {"items": [...]}}
    return d.get("items") or (d.get("data") or {}).get("items") or []


def _rating(it: dict) -> float | None:
    try:
        return float((it.get("tmdb") or {}).get("vote_average"))
    except (TypeError, ValueError):
        return None


def _page(d: dict, page: int) -> Page:
    cards = [Card(it.get("slug", ""), it.get("name", ""), it.get("origin_name", ""), it.get("year"),
                  it.get("poster_url", ""), it.get("thumb_url", ""), _rating(it)) for it in _items(d)]
    pg = d.get("pagination") or (d.get("data") or {}).get("params", {}).get("pagination") or {}
    return Page(cards, int(pg.get("currentPage") or page), int(pg.get("totalPages") or 1))


def latest(page: int = 1) -> Page:
    return _page(_get("danh-sach/phim-moi-cap-nhat", page=page), page)


def search(keyword: str, page: int = 1, limit: int = 24) -> Page:
    return _page(_get("tim-kiem", keyword=keyword, page=page, limit=limit), page)


def listing(kind: Literal["phim-le", "phim-bo", "the-loai", "quoc-gia"], slug: str = "", page: int = 1) -> Page:
    path = f"danh-sach/{kind}" if kind in ("phim-le", "phim-bo") else f"{kind}/{slug}"
    return _page(_get(path, page=page), page)


def filters() -> dict[str, list[dict]]:
    def load(path):
        return [{"name": i["name"], "slug": i["slug"]} for i in _items(_get(path))]
    return {"genres": load("the-loai"), "countries": load("quoc-gia")}


def movie(slug: str) -> MovieDetail:
    d = _get(f"phim/{urllib.parse.quote(slug)}")
    m = d.get("movie")
    if not m:
        raise VsmovError("Không tìm thấy phim trên vsmov")
    meta = MovieMeta(
        slug=m.get("slug", slug), name=m.get("name", ""), origin_name=m.get("origin_name", ""),
        year=m.get("year"), type=m.get("type", "single"), poster_url=m.get("poster_url", ""),
        thumb_url=m.get("thumb_url", ""), time=m.get("time", ""), lang=m.get("lang", ""),
        content=m.get("content", ""), actors=m.get("actor") or [], directors=m.get("director") or [],
        categories=[c["name"] for c in m.get("category") or []],
        countries=[c["name"] for c in m.get("country") or []])
    servers = [Server(" ".join(s.get("server_name", "").split()),
                      [Episode(name=e.get("name", ""), slug=e.get("slug", ""), embed=e.get("link_embed", ""))
                       for e in s.get("server_data") or []])
               for s in d.get("episodes") or []]
    servers = [s for s in servers if s.episodes]
    default = next((s.name for s in servers if "4K" not in s.name), servers[0].name if servers else "")
    return MovieDetail(meta, servers, default)
