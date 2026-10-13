"""Read-only browsing of the host folder mounted at HOST_ROOT, to pick videos by path.
Paths are relative to the root; hidden entries and anything resolving outside the root are refused."""
from pathlib import Path
from . import config

VIDEO_EXT = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".flv", ".m4v", ".ts"}

class BrowseError(Exception):
    pass

def available() -> bool:
    return config.HOST_ROOT.is_dir()

def _root() -> Path:
    if not available():
        raise BrowseError("Chưa gắn thư mục máy vào app (HOST_ROOT trong .env)")
    return config.HOST_ROOT.resolve()

def resolve(rel: str) -> Path:
    """Absolute path for `rel` inside the root, following symlinks; refuses escapes and hidden parts."""
    root = _root()
    rel = (rel or "").strip().strip("/")
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if any(p == ".." or p.startswith(".") for p in parts):
        raise BrowseError("Đường dẫn không hợp lệ")
    p = (root / Path(*parts)).resolve() if parts else root
    if p != root and root not in p.parents:
        raise BrowseError("Đường dẫn nằm ngoài thư mục được phép")
    if not p.exists():
        raise BrowseError(f"Không tìm thấy: {rel}")
    return p

def rel_of(p: Path) -> str:
    return str(p.relative_to(_root())) if p != _root() else ""

def list_dir(rel: str) -> dict:
    d = resolve(rel)
    if not d.is_dir():
        raise BrowseError("Không phải thư mục")
    root = _root()
    dirs, files = [], []
    try:
        entries = sorted(d.iterdir(), key=lambda e: e.name.lower())
    except PermissionError:
        raise BrowseError("Không có quyền đọc thư mục này")
    for e in entries:
        if e.name.startswith("."):
            continue
        try:
            real = e.resolve()
            if real != root and root not in real.parents:      # symlink pointing outside the root
                continue
            if real.is_dir():
                dirs.append({"name": e.name, "path": f"{rel_of(d)}/{e.name}".lstrip("/")})
            elif real.is_file() and e.suffix.lower() in VIDEO_EXT:
                files.append({"name": e.name, "path": f"{rel_of(d)}/{e.name}".lstrip("/"),
                              "size": real.stat().st_size, "mtime": real.stat().st_mtime})
        except OSError:
            continue
    here = rel_of(d)
    parent = None if not here else ("" if "/" not in here else here.rsplit("/", 1)[0])
    return {"path": here, "parent": parent, "dirs": dirs, "files": files}

def video_file(rel: str) -> Path:
    p = resolve(rel)
    if not p.is_file() or p.suffix.lower() not in VIDEO_EXT:
        raise BrowseError("Không phải file video")
    return p
