import pytest
from autosub import config, storage

@pytest.fixture(autouse=True)
def _memory_store(tmp_path, monkeypatch):
    """Every test gets an empty in-memory object store and its own scratch dir."""
    monkeypatch.setattr(config, "WORK_DIR", tmp_path / "work")
    st = storage.MemoryStore()
    storage.set_store(st)
    yield st
    storage.set_store(None)
