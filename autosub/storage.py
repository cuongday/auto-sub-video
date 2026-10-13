"""Object storage for all job data (MinIO in the app, an in-memory store in tests).

Keys are '/'-separated paths inside one bucket: jobs/<id>/..., tts-cache/..., presets.json.
Processing tools need real files, so steps work in a local scratch dir (see workdir.py) and
sync through get_file/put_file; small JSON documents are read and written directly."""
import io
import json
import mimetypes
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterator, Protocol

class StorageError(Exception):
    """Storage unreachable or misconfigured (shown to the user)."""

@dataclass
class ObjInfo:
    key: str
    size: int
    etag: str

class Store(Protocol):
    def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None: ...
    def get_bytes(self, key: str) -> bytes | None: ...
    def put_file(self, key: str, path: Path) -> None: ...
    def get_file(self, key: str, path: Path) -> bool: ...
    def stat(self, key: str) -> ObjInfo | None: ...
    def list(self, prefix: str) -> list[ObjInfo]: ...
    def delete(self, key: str) -> None: ...
    def delete_prefix(self, prefix: str) -> None: ...
    def open_range(self, key: str, start: int, length: int | None) -> Iterator[bytes]: ...
    def ping(self) -> None: ...

def content_type(key: str) -> str:
    return mimetypes.guess_type(key)[0] or "application/octet-stream"

# ---------------------------------------------------------------- helpers

def read_json(st: Store, key: str, default=None):
    data = st.get_bytes(key)
    return default if data is None else json.loads(data.decode("utf-8"))

def write_json(st: Store, key: str, value) -> None:
    st.put_bytes(key, json.dumps(value, ensure_ascii=False, indent=1).encode("utf-8"), "application/json")

# ---------------------------------------------------------------- in-memory (tests)

class MemoryStore:
    def __init__(self):
        self._d: dict[str, bytes] = {}
        self._lock = threading.Lock()
        self._n = 0

    def _info(self, key: str, data: bytes) -> ObjInfo:
        return ObjInfo(key, len(data), f"{hash(data) & 0xFFFFFFFF:08x}-{len(data)}")

    def put_bytes(self, key, data, content_type="application/octet-stream"):
        with self._lock:
            self._d[key] = bytes(data)

    def get_bytes(self, key):
        with self._lock:
            return self._d.get(key)

    def put_file(self, key, path):
        self.put_bytes(key, Path(path).read_bytes())

    def get_file(self, key, path):
        data = self.get_bytes(key)
        if data is None:
            return False
        path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".part")
        tmp.write_bytes(data); os.replace(tmp, path)
        return True

    def stat(self, key):
        data = self.get_bytes(key)
        return None if data is None else self._info(key, data)

    def list(self, prefix):
        with self._lock:
            return [self._info(k, v) for k, v in sorted(self._d.items()) if k.startswith(prefix)]

    def delete(self, key):
        with self._lock:
            self._d.pop(key, None)

    def delete_prefix(self, prefix):
        with self._lock:
            for k in [k for k in self._d if k.startswith(prefix)]:
                del self._d[k]

    def open_range(self, key, start, length):
        data = self.get_bytes(key) or b""
        end = len(data) if length is None else start + length
        yield data[start:end]

    def ping(self):
        pass

# ---------------------------------------------------------------- MinIO

class MinioStore:
    CHUNK = 1 << 20

    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket: str, secure: bool = False):
        from minio import Minio
        self.bucket = bucket
        self.client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
        self._ready = False
        self._lock = threading.Lock()

    def _err(self, e: Exception) -> StorageError:
        return StorageError(f"MinIO lỗi: {e}")

    def ensure_bucket(self, wait: float = 30.0) -> None:
        """Create the bucket if needed, retrying while MinIO starts up."""
        if self._ready:
            return
        with self._lock:
            if self._ready:
                return
            deadline = time.monotonic() + wait
            while True:
                try:
                    if not self.client.bucket_exists(self.bucket):
                        self.client.make_bucket(self.bucket)
                    self._ready = True
                    return
                except Exception as e:  # noqa: BLE001  (connection refused while MinIO boots)
                    if time.monotonic() >= deadline:
                        raise self._err(e) from e
                    time.sleep(1.0)

    def _not_found(self, e: Exception) -> bool:
        from minio.error import S3Error
        return isinstance(e, S3Error) and e.code in ("NoSuchKey", "NoSuchObject", "NotFound")

    def put_bytes(self, key, data, content_type="application/octet-stream"):
        self.ensure_bucket()
        try:
            self.client.put_object(self.bucket, key, io.BytesIO(data), len(data), content_type=content_type)
        except Exception as e:  # noqa: BLE001
            raise self._err(e) from e

    def get_bytes(self, key):
        self.ensure_bucket()
        try:
            r = self.client.get_object(self.bucket, key)
        except Exception as e:  # noqa: BLE001
            if self._not_found(e):
                return None
            raise self._err(e) from e
        try:
            return r.read()
        finally:
            r.close(); r.release_conn()

    def put_file(self, key, path):
        self.ensure_bucket()
        try:
            self.client.fput_object(self.bucket, key, str(path), content_type=content_type(key))
        except Exception as e:  # noqa: BLE001
            raise self._err(e) from e

    def get_file(self, key, path):
        self.ensure_bucket()
        path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".part")
        try:
            self.client.fget_object(self.bucket, key, str(tmp))
        except Exception as e:  # noqa: BLE001
            tmp.unlink(missing_ok=True)
            if self._not_found(e):
                return False
            raise self._err(e) from e
        os.replace(tmp, path)
        return True

    def stat(self, key):
        self.ensure_bucket()
        try:
            o = self.client.stat_object(self.bucket, key)
        except Exception as e:  # noqa: BLE001
            if self._not_found(e):
                return None
            raise self._err(e) from e
        return ObjInfo(key, o.size or 0, (o.etag or "").strip('"'))

    def list(self, prefix):
        self.ensure_bucket()
        try:
            return [ObjInfo(o.object_name, o.size or 0, (o.etag or "").strip('"'))
                    for o in self.client.list_objects(self.bucket, prefix=prefix, recursive=True)]
        except Exception as e:  # noqa: BLE001
            raise self._err(e) from e

    def delete(self, key):
        self.ensure_bucket()
        try:
            self.client.remove_object(self.bucket, key)
        except Exception as e:  # noqa: BLE001
            if not self._not_found(e):
                raise self._err(e) from e

    def delete_prefix(self, prefix):
        from minio.deleteobjects import DeleteObject
        objs = [DeleteObject(o.key) for o in self.list(prefix)]
        if not objs:
            return
        try:
            for err in self.client.remove_objects(self.bucket, objs):
                raise StorageError(f"MinIO không xoá được {err.name}: {err.message}")
        except StorageError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._err(e) from e

    def open_range(self, key, start, length):
        self.ensure_bucket()
        try:
            r = self.client.get_object(self.bucket, key, offset=start, length=length or 0)
        except Exception as e:  # noqa: BLE001
            raise self._err(e) from e
        try:
            yield from r.stream(self.CHUNK)
        finally:
            r.close(); r.release_conn()

    def ping(self):
        self._ready = False
        self.ensure_bucket(wait=3.0)

# ---------------------------------------------------------------- the active store

_STORE: list[Store] = []

def get_store() -> Store:
    if not _STORE:
        from . import config
        if not config.MINIO_ENDPOINT:
            raise StorageError("Thiếu MINIO_ENDPOINT (chạy app bằng docker compose)")
        _STORE.append(MinioStore(config.MINIO_ENDPOINT, config.MINIO_ACCESS_KEY, config.MINIO_SECRET_KEY,
                                 config.MINIO_BUCKET, config.MINIO_SECURE))
    return _STORE[0]

def set_store(st: Store | None) -> None:
    """Tests swap in a MemoryStore."""
    _STORE.clear()
    if st is not None:
        _STORE.append(st)

def file_stream(st: Store, key: str, start: int = 0, length: int | None = None) -> Iterator[bytes]:
    return st.open_range(key, start, length)

__all__ = ["BinaryIO", "MemoryStore", "MinioStore", "ObjInfo", "Store", "StorageError", "get_store", "set_store",
           "read_json", "write_json", "content_type", "file_stream"]
