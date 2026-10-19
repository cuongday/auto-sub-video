"""Client for the public vsmov.com movie API (stdlib only)."""
import functools
import json
import re
import shutil
import struct
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from . import proc
from .douyin import UA
from .models import Episode, MovieMeta, SubTrack

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

# ---- embed page / HLS download ----
# The embed page is a JW Player whose HLS segments are a small PNG followed by MPEG-TS packets.

@dataclass
class Embed:
    base_url: str
    video_hash: str
    master_url: str
    subtitles: list[SubTrack]

def _js_str(name: str, html: str) -> str:
    m = re.search(rf'\b{name}\s*[:=]\s*"([^"]*)"', html)
    return m.group(1) if m else ""

def parse_embed(html: str) -> Embed:
    base, vhash = _js_str("baseUrl", html).rstrip("/"), _js_str("videoHash", html)
    if not vhash:
        raise VsmovError("Không đọc được trang phát của vsmov")
    signed = _js_str("signedMasterUrl", html)
    on = re.search(r"enableSignedUrl:\s*(true|false)", html)
    master = signed if on and on.group(1) == "true" and signed else f"{base}/stream/{vhash}/master.m3u8"
    subs = []
    m = re.search(r"subtitles:\s*(\[.*\])\s*,?\s*$", html, re.M)
    if m:
        try:
            subs = json.loads(m.group(1))
        except ValueError:
            subs = []
    tracks = [SubTrack(code=_str(t.get("code")), url=base + t["url"])
              for t in subs if isinstance(t, dict) and isinstance(t.get("url"), str) and t["url"]]
    return Embed(base, vhash, master, tracks)

def pick_variant(master_text: str, master_url: str) -> str:
    lines = [ln.strip() for ln in master_text.splitlines()]
    variants = []  # (height, bandwidth, uri)
    for i, ln in enumerate(lines):
        if not ln.startswith("#EXT-X-STREAM-INF:"):
            continue
        uri = next((x for x in lines[i + 1:] if x and not x.startswith("#")), None)
        if uri is None:
            continue
        res, bw = re.search(r"RESOLUTION=\d+x(\d+)", ln), re.search(r"BANDWIDTH=(\d+)", ln)
        variants.append((int(res.group(1)) if res else 0, int(bw.group(1)) if bw else 0, uri))
    if not variants:
        return master_url  # already a media playlist
    fit = [v for v in variants if 0 < v[0] <= 1080]
    best = max(fit) if fit else max(variants, key=lambda v: v[1])
    return urllib.parse.urljoin(master_url, best[2])

def segment_urls(playlist_text: str, playlist_url: str) -> list[str]:
    return [urllib.parse.urljoin(playlist_url, ln.strip()) for ln in playlist_text.splitlines()
            if ln.strip() and not ln.startswith("#")]

_PNG_SIG = b"\x89PNG\r\n\x1a\n"

def strip_png(data: bytes) -> bytes:
    start = 0
    if data.startswith(_PNG_SIG):
        start = len(_PNG_SIG)
        while start + 8 <= len(data):
            n, kind = struct.unpack(">I4s", data[start:start + 8])
            start += 12 + n  # length, type, data, CRC
            if kind == b"IEND":
                break
    i = data.find(b"\x47", start)
    while 0 <= i and i + 376 < len(data):
        if data[i + 188] == data[i + 376] == 0x47:  # three TS sync bytes in a row
            return data[i:]
        i = data.find(b"\x47", i + 1)
    raise VsmovError("Đoạn video không đúng định dạng")

def _fetch(url: str, headers: dict | None = None, timeout: float = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def fetch_subtitle(url: str, embed_url: str) -> str:
    try:
        return _fetch(url, {"Referer": embed_url}).decode("utf-8-sig", "replace")
    except OSError as e:
        raise VsmovError(f"Không tải được phụ đề vsmov: {e}") from e

def download(embed_url: str, dest: Path, progress=None, cancel: threading.Event | None = None, workers: int = 8) -> Embed:
    dest = Path(dest)
    try:
        e = parse_embed(_fetch(embed_url).decode("utf-8", "replace"))
        hdr = {"Referer": embed_url, "Origin": e.base_url}
        text = _fetch(e.master_url, hdr).decode("utf-8", "replace")
        pl_url = pick_variant(text, e.master_url)
        if pl_url != e.master_url:
            text = _fetch(pl_url, hdr).decode("utf-8", "replace")
    except OSError as ex:
        raise VsmovError(f"Không kết nối được vsmov: {ex}") from ex
    urls = segment_urls(text, pl_url)
    if not urls:
        raise VsmovError("Không tìm thấy đoạn video nào")
    total = len(urls)
    seg_dir = dest.parent / f".vsmov-{e.video_hash}"
    part = dest.with_name(dest.name + ".ts.part")
    tmp = dest.with_name(dest.stem + ".tmp.mp4")

    def one(n: int, url: str):
        for attempt in range(3):
            if cancel is not None and cancel.is_set():
                raise VsmovError("Đã huỷ")
            try:
                data = strip_png(_fetch(url, hdr, timeout=60))
                break
            except (OSError, VsmovError) as ex:
                if attempt == 2:
                    raise VsmovError(f"Tải đoạn {n}/{total} lỗi: {ex}") from ex
                time.sleep(attempt + 1)
        (seg_dir / f"{n:05d}.ts").write_bytes(data)

    try:
        seg_dir.mkdir(parents=True, exist_ok=True)
        with ThreadPoolExecutor(workers) as pool:
            futs = [pool.submit(one, n, u) for n, u in enumerate(urls, 1)]
            try:
                for done, f in enumerate(as_completed(futs), 1):
                    f.result()
                    if progress:
                        progress(done / total)
                    if cancel is not None and cancel.is_set():
                        raise VsmovError("Đã huỷ")
            except BaseException:
                for f in futs:
                    f.cancel()
                raise
        with open(part, "wb") as out:
            for n in range(1, total + 1):
                with open(seg_dir / f"{n:05d}.ts", "rb") as f:
                    shutil.copyfileobj(f, out)
        try:
            proc.run_ffmpeg(["-i", str(part), "-c", "copy", "-bsf:a", "aac_adtstoasc", str(tmp)], cancel=cancel)
        except proc.Cancelled as ex:
            raise VsmovError("Đã huỷ") from ex
        tmp.replace(dest)
    finally:
        shutil.rmtree(seg_dir, ignore_errors=True)
        part.unlink(missing_ok=True)
        tmp.unlink(missing_ok=True)
    return e
