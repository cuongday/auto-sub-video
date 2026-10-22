"""Real Whisper on a clip that switches from Vietnamese to Chinese (downloads on first run). make test-slow"""
import pytest
from autosub import media
from autosub.asr import get_asr
from tests.test_slow_engines import _edge

pytestmark = pytest.mark.slow

def test_dubbed_film_keeps_both_languages(tmp_path):
    vi = _edge("Tinh quyết định lập một đội bóng đá Thiếu Lâm cùng các sư huynh.", "vi-VN-NamMinhNeural", tmp_path / "vi.mp3")
    zh = _edge("你要是不喜欢看的话，你可以走开。", "zh-CN-YunxiNeural", tmp_path / "zh.mp3")
    both = tmp_path / "both.wav"
    media.proc.run(["ffmpeg", "-v", "error", "-i", str(vi), "-i", str(zh), "-filter_complex",
                    "[0:a]apad=pad_dur=2[a];[a][1:a]concat=n=2:v=0:a=1", "-ar", "16000", "-ac", "1", str(both)])
    words = get_asr("vi", "small").transcribe(both)
    text = " ".join(w.text for w in words)
    assert "đội bóng" in text.lower() and "喜欢" in text
    assert [w.start for w in words] == sorted(w.start for w in words)
