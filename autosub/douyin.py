"""Douyin: list a channel's videos, fetch video info and download videos.

Douyin's web API needs signed requests, so a headless Chromium on douyin.com makes the API calls from
inside the page (the page signs them); the video files themselves are plain CDN URLs downloaded with
urllib. Without login a channel lists only its first page (~10-20 videos); logging in by scanning a QR
with the Douyin app unlocks the full list. The login cookies are kept in MinIO (douyin/session.json)."""
import asyncio
import json
import re
import threading
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from .storage import get_store, read_json, write_json

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
SESSION_KEY = "douyin/session.json"
BASE_Q = {"device_platform": "webapp", "aid": "6383", "channel": "channel_pc_web", "version_code": "290100",
          "version_name": "29.1.0", "cookie_enabled": "true", "platform": "PC", "pc_client_type": "1"}
DETAIL_ATTEMPTS = 3       # the first signed call sometimes gets a 403 with an empty body
MAX_PAGES = 40            # 40 x ~18 videos; plenty for a channel
_VIDEO_ID = re.compile(r"(?:/video/|/note/|modal_id=|aweme_id=)(\d{15,22})")
_SEC_UID = re.compile(r"/user/([A-Za-z0-9_\-]{20,})")
_SHORT = re.compile(r"https?://v\.douyin\.com/[A-Za-z0-9_\-]+/?")
_LOCK = threading.Lock()  # one browser at a time
CACHE_TTL = 20 * 60       # play URLs from a lookup stay valid for a while; reuse them instead of a new browser
_CACHE: dict[str, tuple[float, "VideoItem"]] = {}
_CACHE_LOCK = threading.Lock()

class DouyinError(Exception):
    pass

@dataclass
class VideoItem:
    id: str
    title: str
    duration: float          # seconds (0 for image posts)
    cover: str
    created: int             # unix time
    width: int = 0
    height: int = 0
    size: int = 0            # bytes of the best stream
    is_images: bool = False
    play_urls: list[str] = field(default_factory=list)

    def public(self) -> dict:
        d = asdict(self); d.pop("play_urls"); return d

# ---------------------------------------------------------------- parsing (pure)

def parse_url(text: str) -> tuple[str, str]:
    """('video', aweme_id) | ('user', sec_uid) | ('short', url). Accepts shared text with a link inside."""
    text = text.strip()
    if m := _VIDEO_ID.search(text):
        return "video", m.group(1)
    if m := _SEC_UID.search(text):
        return "user", m.group(1)
    if m := _SHORT.search(text):
        return "short", m.group(0)
    if re.fullmatch(r"\d{15,22}", text):
        return "video", text
    raise DouyinError("Không nhận ra link Douyin (cần link video, link kênh /user/... hoặc link v.douyin.com)")

def pick_stream(video: dict) -> tuple[list[str], int, int, int]:
    """Highest resolution, then highest bitrate, H.264 preferred: (urls, width, height, size)."""
    rates = [b for b in video.get("bit_rate") or [] if (b.get("play_addr") or {}).get("url_list")]
    if rates:
        def key(b):
            pa = b["play_addr"]
            return (pa.get("height") or 0, 0 if b.get("is_h265") else 1, b.get("bit_rate") or 0)
        best = max(rates, key=key)["play_addr"]
        return best["url_list"], best.get("width") or 0, best.get("height") or 0, best.get("data_size") or 0
    pa = video.get("play_addr") or {}
    return pa.get("url_list") or [], video.get("width") or 0, video.get("height") or 0, pa.get("data_size") or 0

def to_item(aweme: dict) -> VideoItem:
    v = aweme.get("video") or {}
    urls, w, h, size = pick_stream(v)
    cover = ((v.get("cover") or v.get("origin_cover") or {}).get("url_list") or [""])[0]
    return VideoItem(id=str(aweme.get("aweme_id")), title=(aweme.get("desc") or "").strip(),
                     duration=round((aweme.get("duration") or v.get("duration") or 0) / 1000, 1), cover=cover,
                     created=int(aweme.get("create_time") or 0), width=w, height=h, size=size,
                     is_images=bool(aweme.get("images")), play_urls=urls)

def safe_name(title: str, vid: str, limit: int = 60) -> str:
    t = re.sub(r"#\S+", "", title)                      # drop hashtags
    t = re.sub(r"[\\/:*?\"<>|\r\n\t]+", " ", t).strip(" .")
    t = re.sub(r"\s+", " ", t)[:limit].strip()
    return f"{t or 'douyin'}_{vid}.mp4"

def remember(items) -> None:
    now = time.time()
    with _CACHE_LOCK:
        for it in items:
            _CACHE[it.id] = (now, it)
        for k in [k for k, (t, _) in _CACHE.items() if now - t > CACHE_TTL]:
            del _CACHE[k]

def cached(aweme_id: str) -> "VideoItem | None":
    with _CACHE_LOCK:
        hit = _CACHE.get(aweme_id)
    return hit[1] if hit and time.time() - hit[0] <= CACHE_TTL else None

# ---------------------------------------------------------------- session (MinIO)

def load_session() -> list[dict]:
    return read_json(get_store(), SESSION_KEY, default={}).get("cookies", [])

def save_session(cookies: list[dict]) -> None:
    write_json(get_store(), SESSION_KEY, {"cookies": cookies, "saved": time.time()})

def clear_session() -> None:
    get_store().delete(SESSION_KEY)

def logged_in() -> bool:
    return any(c.get("name") in ("sessionid", "sessionid_ss") and c.get("value") for c in load_session())

# ---------------------------------------------------------------- browser

def _run(coro):
    with _LOCK:
        return asyncio.run(coro)

async def _open(p, url: str):
    from playwright.async_api import Error as PwError
    try:
        browser = await p.chromium.launch(headless=True)
    except PwError as e:
        raise DouyinError(f"Không mở được trình duyệt chạy ngầm: {e}") from e
    ctx = await browser.new_context(locale="zh-CN", user_agent=UA, viewport={"width": 1366, "height": 860})
    cookies = load_session()
    if cookies:
        await ctx.add_cookies(cookies)
    page = await ctx.new_page()
    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    await page.wait_for_timeout(4000)
    return browser, ctx, page

_FETCH = """async ([path, q]) => {
  const r = await fetch(path + '?' + new URLSearchParams(q), {credentials: 'include'});
  const t = await r.text();
  try { return JSON.parse(t); } catch (e) { return {__empty: true, status: r.status}; }
}"""

_NO_INFO = "Không lấy được thông tin video (video bị xoá, riêng tư hoặc Douyin chặn tạm thời)"

async def _videos(ids: list[str]) -> dict[str, "VideoItem | DouyinError"]:
    """Details of several videos from one browser page (one launch instead of one per video)."""
    from playwright.async_api import async_playwright
    out: dict[str, VideoItem | DouyinError] = {}
    async with async_playwright() as p:
        browser, _, page = await _open(p, f"https://www.douyin.com/video/{ids[0]}")
        try:
            for i, aweme_id in enumerate(ids):
                if i:
                    await page.wait_for_timeout(300)
                out[aweme_id] = DouyinError(_NO_INFO)
                for attempt in range(DETAIL_ATTEMPTS):
                    j = await page.evaluate(_FETCH, ["/aweme/v1/web/aweme/detail/", {**BASE_Q, "aweme_id": aweme_id}])
                    if j and j.get("aweme_detail"):
                        out[aweme_id] = to_item(j["aweme_detail"])
                        break
                    if not (j or {}).get("__empty"):
                        break               # a real answer without the video: deleted or private
                    await page.wait_for_timeout(1500 * (attempt + 1))   # 403 while the page is still warming up
        finally:
            await browser.close()
    return out

async def _resolve_short(url: str) -> tuple[str, str]:
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser, _, page = await _open(p, url)
        try:
            final = page.url
        finally:
            await browser.close()
    return parse_url(final)

async def _channel(sec_uid: str, progress=None) -> dict:
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser, _, page = await _open(p, f"https://www.douyin.com/user/{sec_uid}")
        try:
            items, cursor, more, pages, blocked, name = [], "0", True, 0, False, ""
            while more and pages < MAX_PAGES:
                j = await page.evaluate(_FETCH, ["/aweme/v1/web/aweme/post/",
                                                 {**BASE_Q, "sec_user_id": sec_uid, "max_cursor": cursor, "count": "18"}])
                pages += 1
                batch = (j or {}).get("aweme_list") or []
                if pages == 1 and batch:
                    name = ((batch[0].get("author") or {}).get("nickname") or "").strip()
                if not batch and (j or {}).get("has_more") is None:
                    blocked = True          # Douyin answers later pages with an empty body when not logged in
                    break
                items += [to_item(a) for a in batch]
                more = bool((j or {}).get("has_more")) and bool(batch)
                cursor = str((j or {}).get("max_cursor") or "0")
                if progress:
                    progress(len(items))
                await page.wait_for_timeout(600)
            if not name:
                name = re.sub(r"的抖音.*$", "", await page.title()).strip()
        finally:
            await browser.close()
    seen, unique = set(), []
    for it in items:
        if it.id not in seen:
            seen.add(it.id); unique.append(it)
    return {"sec_uid": sec_uid, "name": name, "items": unique, "complete": not more and not blocked,
            "logged_in": logged_in()}

def videos_info(ids: list[str]) -> dict[str, "VideoItem | DouyinError"]:
    if not ids:
        return {}
    out = _run(_videos(list(dict.fromkeys(ids))))
    remember([v for v in out.values() if isinstance(v, VideoItem)])
    return out

def video_info(aweme_id: str) -> VideoItem:
    it = videos_info([aweme_id])[aweme_id]
    if isinstance(it, DouyinError):
        raise it
    return it

def resolve(text: str) -> tuple[str, str]:
    kind, val = parse_url(text)
    if kind == "short":
        kind, val = _run(_resolve_short(val))
    return kind, val

def channel(sec_uid: str, progress=None) -> dict:
    ch = _run(_channel(sec_uid, progress))
    remember(ch["items"])
    return ch

# ---------------------------------------------------------------- QR login

class Login:
    """Holds a headless page showing Douyin's login QR until the user scans it (or it times out)."""
    TIMEOUT = 180

    def __init__(self):
        self.state = "starting"      # starting | waiting | done | failed | expired
        self.qr: str | None = None   # data: URL of the QR image
        self.error: str | None = None
        self._stop = threading.Event()
        # its own event loop and browser, outside _LOCK: waiting up to TIMEOUT for a scan must not
        # block channel lookups and downloads meanwhile
        threading.Thread(target=lambda: asyncio.run(self._main()), daemon=True).start()

    def cancel(self):
        self._stop.set()

    async def _main(self):
        from playwright.async_api import async_playwright
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                ctx = await browser.new_context(locale="zh-CN", user_agent=UA, viewport={"width": 1366, "height": 860})
                page = await ctx.new_page()
                # the "my profile" page asks a logged-out visitor to log in, with the QR as a data: image
                await page.goto("https://www.douyin.com/user/self", wait_until="domcontentloaded", timeout=45000)
                t0 = time.time()
                while time.time() - t0 < self.TIMEOUT and not self._stop.is_set():
                    qr = await page.evaluate("""() => {
                        for (const i of document.querySelectorAll('img')) {
                            const r = i.getBoundingClientRect();
                            if (r.width >= 120 && r.width <= 320 && Math.abs(r.width - r.height) < 6 && i.src.startsWith('data:image'))
                                return i.src;
                        }
                        return null;
                    }""")
                    if qr:
                        self.qr, self.state = qr, "waiting"
                    cookies = await ctx.cookies("https://www.douyin.com")
                    if any(c["name"] in ("sessionid", "sessionid_ss") and c["value"] for c in cookies):
                        save_session(cookies)
                        self.state = "done"
                        break
                    await page.wait_for_timeout(1500)
                else:
                    self.state = "expired" if not self._stop.is_set() else "failed"
                await browser.close()
        except Exception as e:  # noqa: BLE001
            self.state, self.error = "failed", str(e)

# ---------------------------------------------------------------- download

def open_stream(item: VideoItem):
    """Open the first mirror that answers: (response, total bytes). The caller closes the response."""
    if item.is_images:
        raise DouyinError("Bài này là album ảnh, không có video")
    if not item.play_urls:
        raise DouyinError("Không có link tải video")
    last: Exception | None = None
    for url in item.play_urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://www.douyin.com/"})
            r = urllib.request.urlopen(req, timeout=30)
            return r, int(r.headers.get("Content-Length") or item.size or 0)
        except Exception as e:  # noqa: BLE001  (expired mirror, network)
            last = e
    raise DouyinError(f"Tải video lỗi: {last}")

def download(item: VideoItem, dest: Path, progress=None, cancel: threading.Event | None = None) -> Path:
    """Stream the best stream to dest (tries each mirror URL); writes dest.part then renames."""
    if item.is_images:
        raise DouyinError("Bài này là album ảnh, không có video")
    if not item.play_urls:
        raise DouyinError("Không có link tải video")
    dest = Path(dest); dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    last: Exception | None = None
    for url in item.play_urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://www.douyin.com/"})
            with urllib.request.urlopen(req, timeout=30) as r, tmp.open("wb") as f:
                total = int(r.headers.get("Content-Length") or item.size or 0)
                done = 0
                while chunk := r.read(1 << 20):
                    if cancel is not None and cancel.is_set():
                        raise DouyinError("Đã huỷ")
                    f.write(chunk); done += len(chunk)
                    if progress and total:
                        progress(done / total)
            tmp.replace(dest)
            return dest
        except DouyinError:
            tmp.unlink(missing_ok=True)
            raise
        except Exception as e:  # noqa: BLE001  (expired mirror, network)
            last = e
            tmp.unlink(missing_ok=True)
    raise DouyinError(f"Tải video lỗi: {last}")

__all__ = ["DouyinError", "VideoItem", "Login", "cached", "channel", "download", "logged_in", "clear_session", "open_stream",
           "parse_url", "pick_stream", "remember", "resolve", "safe_name", "to_item", "video_info", "videos_info", "json"]
