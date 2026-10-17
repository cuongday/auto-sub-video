import sys, types
import pytest
from fastapi.testclient import TestClient
from autosub import api, config, gpu, store
from autosub.tts import vieneu_tts

@pytest.fixture(autouse=True)
def _fresh():
    gpu.cuda_info.cache_clear(); vieneu_tts.reset_pool()
    yield
    gpu.cuda_info.cache_clear(); vieneu_tts.reset_pool()

def fake_torch(monkeypatch, cuda="12.6", available=True, cap=(8, 6), vram_gb=8, name="RTX 3060"):
    t = types.ModuleType("torch")
    t.__version__ = "2.14.1+cu126" if cuda else "2.14.1+cpu"
    t.version = types.SimpleNamespace(cuda=cuda)
    props = types.SimpleNamespace(name=name, major=cap[0], minor=cap[1], total_memory=int(vram_gb * (1 << 30)))
    t.cuda = types.SimpleNamespace(is_available=lambda: available, get_device_properties=lambda i: props)
    monkeypatch.setitem(sys.modules, "torch", t)
    monkeypatch.setattr(gpu.importlib.util, "find_spec", lambda m: object())

def test_resolve_cpu_build_falls_back(monkeypatch):
    fake_torch(monkeypatch, cuda=None)
    assert gpu.resolve("auto") == ("cpu", "")
    dev, note = gpu.resolve("cuda")
    assert dev == "cpu" and "PyTorch bản CPU" in note
    assert gpu.resolve("cpu") == ("cpu", "")

@pytest.mark.parametrize("kw,why", [({"available": False}, "Không thấy GPU"), ({"cap": (3, 5), "name": "GT 730"}, "quá cũ"),
                                     ({"vram_gb": 2}, "VRAM")])
def test_unusable_gpus(monkeypatch, kw, why):
    fake_torch(monkeypatch, **kw)
    info = gpu.cuda_info()
    assert not info["available"] and why in info["reason"]
    assert gpu.resolve("cuda")[0] == "cpu"

def test_good_gpu_is_used(monkeypatch):
    fake_torch(monkeypatch)
    assert gpu.cuda_info()["available"] and gpu.cuda_info()["vram_gb"] == 8.0
    assert gpu.resolve("auto") == ("cuda", "") and gpu.resolve("cuda") == ("cuda", "")

def test_pool_builds_on_the_chosen_device_and_switches(monkeypatch):
    fake_torch(monkeypatch)
    made = []
    monkeypatch.setattr(vieneu_tts, "_new_instance", lambda device, threads=0: (made.append(device), object())[1])
    monkeypatch.setattr(config, "VIENEU_DEVICE", "auto")
    with vieneu_tts._Borrow():
        pass
    with vieneu_tts._Borrow():            # reused from the pool
        pass
    assert made == ["cuda"] and vieneu_tts.workers() == config.VIENEU_GPU_WORKERS
    store.save_app_settings({"vieneu_device": "cpu"})   # the web setting wins over .env
    vieneu_tts._REQ[:] = ["", 0.0]                       # (the API resets this when the setting changes)
    with vieneu_tts._Borrow():
        pass
    assert made == ["cuda", "cpu"] and vieneu_tts.workers() == config.VOICE_WORKERS

def test_api_setting_and_status(monkeypatch):
    fake_torch(monkeypatch, cuda=None)
    with TestClient(api.app) as c:
        assert c.get("/api/app-settings").json()["vieneu_device"] == config.VIENEU_DEVICE
        assert c.put("/api/app-settings", json={"vieneu_device": "cuda"}).json()["vieneu_device"] == "cuda"
        g = c.get("/api/gpu").json()
        assert g["requested"] == "cuda" and g["device"] == "cpu" and g["note"]
        assert c.put("/api/app-settings", json={"vieneu_device": "tpu"}).status_code == 422
