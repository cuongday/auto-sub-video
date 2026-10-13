"""Store contract against a real MinIO in a throwaway container (make test-minio)."""
import shutil
import socket
import subprocess
import time
import uuid
import pytest
from autosub.storage import MemoryStore, MinioStore, read_json, write_json

pytestmark = pytest.mark.minio
IMAGE = "minio/minio:RELEASE.2025-09-07T16-13-09Z"

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]

@pytest.fixture(scope="module")
def minio_endpoint():
    if not shutil.which("docker"):
        pytest.skip("docker not available")
    port, name = _free_port(), f"autosub-test-minio-{uuid.uuid4().hex[:6]}"
    subprocess.run(["docker", "run", "-d", "--rm", "--name", name, "-p", f"127.0.0.1:{port}:9000",
                    "-e", "MINIO_ROOT_USER=test", "-e", "MINIO_ROOT_PASSWORD=testtesttest", IMAGE, "server", "/data"],
                   check=True, capture_output=True)
    try:
        yield f"127.0.0.1:{port}"
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)

@pytest.fixture(params=["memory", "minio"])
def st(request):
    if request.param == "memory":
        return MemoryStore()
    ep = request.getfixturevalue("minio_endpoint")
    s = MinioStore(ep, "test", "testtesttest", f"b{uuid.uuid4().hex[:8]}")
    s.ensure_bucket(wait=30)
    return s

def test_bytes_and_json(st):
    assert st.get_bytes("nope") is None and st.stat("nope") is None
    write_json(st, "jobs/a/job.json", {"x": "Tiếng Việt"})
    assert read_json(st, "jobs/a/job.json") == {"x": "Tiếng Việt"}
    info = st.stat("jobs/a/job.json")
    assert info.size > 0 and info.etag

def test_files_list_and_delete_prefix(st, tmp_path):
    src = tmp_path / "big.bin"; src.write_bytes(bytes(range(256)) * 4096)      # 1 MiB
    st.put_file("jobs/a/audio.wav", src)
    st.put_bytes("jobs/a/tts/seg_0001.wav", b"1")
    st.put_bytes("jobs/b/job.json", b"{}")
    assert st.get_file("jobs/a/audio.wav", tmp_path / "out" / "a.wav")
    assert (tmp_path / "out" / "a.wav").read_bytes() == src.read_bytes()
    assert not st.get_file("jobs/a/missing", tmp_path / "x")
    assert [o.key for o in st.list("jobs/a/")] == ["jobs/a/audio.wav", "jobs/a/tts/seg_0001.wav"]
    st.delete_prefix("jobs/a/")
    assert st.list("jobs/a/") == [] and st.get_bytes("jobs/b/job.json") == b"{}"
    st.delete("jobs/b/job.json"); st.delete("jobs/b/job.json")              # idempotent

def test_range_reads(st):
    data = bytes(range(256)) * 100
    st.put_bytes("v.mp4", data)
    assert b"".join(st.open_range("v.mp4", 10, 20)) == data[10:30]
    assert b"".join(st.open_range("v.mp4", 25000, None)) == data[25000:]

def test_etag_changes_when_content_changes(st):
    st.put_bytes("k", b"one")
    a = st.stat("k").etag
    st.put_bytes("k", b"two")
    assert st.stat("k").etag != a

def test_unreachable_minio_raises_storage_error():
    from autosub.storage import StorageError
    s = MinioStore(f"127.0.0.1:{_free_port()}", "x", "y", "b")
    t0 = time.monotonic()
    with pytest.raises(StorageError):
        s.ensure_bucket(wait=1.0)
    assert time.monotonic() - t0 < 15
