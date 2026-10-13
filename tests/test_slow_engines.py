"""Real models (downloads on first run). make test-slow"""
from pathlib import Path
import pytest
import soundfile as sf
from autosub import media
from autosub.asr import get_asr
from autosub.separate import separate

pytestmark = pytest.mark.slow
SAMPLES = Path("/tmp/autosub-samples")

def _edge(text, voice, out):
    import asyncio, edge_tts
    asyncio.run(edge_tts.Communicate(text, voice).save(str(out)))
    return out

@pytest.fixture(scope="module")
def zh_wav(tmp_path_factory):
    d = tmp_path_factory.mktemp("zh")
    mp3 = _edge("小明，你今天怎么这么晚才来？对不起老师，路上堵车了。", "zh-CN-YunxiNeural", d / "zh.mp3")
    return media.to_16k_mono(mp3, d / "zh16.wav")

@pytest.fixture(scope="module")
def en_wav(tmp_path_factory):
    d = tmp_path_factory.mktemp("en")
    mp3 = _edge("Welcome back to the channel. Today we are going to build a small wooden table.", "en-US-GuyNeural", d / "en.mp3")
    return media.to_16k_mono(mp3, d / "en16.wav")

def test_funasr_zh(zh_wav):
    words = get_asr("zh").transcribe(zh_wav)
    text = "".join(w.text for w in words)
    assert "老师" in text and "堵车" in text
    assert words[0].start < words[-1].end

def test_whisper_en(en_wav):
    words = get_asr("en", "small").transcribe(en_wav)
    text = " ".join(w.text for w in words).lower()
    assert "wooden table" in text

def test_demucs(tmp_path, zh_wav):
    wav = media.extract_audio(zh_wav, tmp_path / "a.wav")
    v, nv = separate(wav, tmp_path)
    assert sf.info(v).duration > 2 and sf.info(nv).duration > 2
