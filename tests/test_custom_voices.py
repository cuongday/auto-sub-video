import numpy as np
import pytest
import soundfile as sf
from autosub import voices
from autosub.storage import get_store

def wav(path, seconds=3.0, sr=24000):
    t = np.arange(int(sr * seconds)) / sr
    sf.write(path, (0.3 * np.sin(2 * np.pi * 180 * t)).astype(np.float32), sr)
    return path

def test_create_list_get_delete(tmp_path):
    v = voices.create("Giong-Thu", wav(tmp_path / "r.wav", 9), gender="female", note="test")
    assert v.id == "custom:Giong-Thu" and v.duration == pytest.approx(9, abs=0.05)
    assert get_store().stat("voices/Giong-Thu/ref.wav") is not None
    assert [x.name for x in voices.list_voices()] == ["Giong-Thu"]
    p = voices.ref_path("custom:Giong-Thu", tmp_path / "cache")
    assert p.exists() and sf.info(p).samplerate == 24000
    voices.delete("Giong-Thu")
    assert voices.list_voices() == [] and get_store().list("voices/") == []

def test_trims_long_reference_and_rejects_bad_input(tmp_path):
    v = voices.create("Long", wav(tmp_path / "l.wav", 40))
    assert v.duration <= voices.MAX_SECONDS + 0.05
    with pytest.raises(voices.VoiceError):
        voices.create("Short", wav(tmp_path / "s.wav", 1.0))
    with pytest.raises(voices.VoiceError):
        voices.create("bad/name", wav(tmp_path / "b.wav", 5))
    with pytest.raises(voices.VoiceError):
        voices.create("Long", wav(tmp_path / "d.wav", 5))          # duplicate
    voices.create("Long", wav(tmp_path / "d.wav", 5), overwrite=True)

def test_clip_window(tmp_path):
    v = voices.create("Win", wav(tmp_path / "w.wav", 30), start=10, length=8)
    assert v.duration == pytest.approx(8, abs=0.05)

def test_is_custom():
    assert voices.is_custom("custom:A") and not voices.is_custom("Trúc Ly") and not voices.is_custom("")

def test_source_on_read_only_dir(tmp_path):
    src_dir = tmp_path / "ro"; src_dir.mkdir()
    wav(src_dir / "r.wav", 6)
    src_dir.chmod(0o555)
    try:
        assert voices.create("RO", src_dir / "r.wav").duration > 5
        assert sorted(p.name for p in src_dir.iterdir()) == ["r.wav"]
    finally:
        src_dir.chmod(0o755)
