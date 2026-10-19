"""Test doubles for the slow / networked engines."""
import json
import re
from pathlib import Path
import numpy as np
import soundfile as sf
from autosub.models import Word

class FakeLLM:
    """Translates every requested id to 'VI <source>'; `hook(prompt, schema) -> dict|None` can override."""
    name = "fake"; model = "fake-1"

    def __init__(self, hook=None):
        self.prompts: list[str] = []
        self.hook = hook

    def generate_json(self, prompt, schema, temperature=0.3):
        self.prompts.append(prompt)
        if self.hook:
            r = self.hook(prompt, schema)
            if r is not None:
                return r
        if "summary" in schema["properties"]:
            return {"summary": "Một đoạn phim", "genre_tone": "đời thường",
                    "characters": [{"name": "小明", "vi_name": "Tiểu Minh", "addressing": "tôi/cậu"}],
                    "glossary": [{"source": "公园", "vi": "công viên"}]}
        items = json.loads(prompt[prompt.rindex("<<<ITEMS") + 8: prompt.rindex("ITEMS>>>")])
        return {"items": [{"id": it["id"], "vi": f"VI {it['source']}"} for it in items]}

class FakeTTS:
    """Writes a 220 Hz tone lasting 0.08 s per character / rate (native rate support)."""
    name = "fake"; native_rate = True

    def __init__(self, sec_per_char=0.08, fail_on: str | None = None):
        self.calls: list[tuple[str, float]] = []
        self.spc = sec_per_char
        self.fail_on = fail_on

    def synthesize(self, text, out: Path, voice="", rate=1.0, ref_audio=None):
        if self.fail_on and self.fail_on in text:
            raise RuntimeError("tts down")
        self.calls.append((text, rate, voice))
        sr = 24000
        n = int(sr * len(text) * self.spc / rate)
        pcm = 0.3 * np.sin(2 * np.pi * 220 * np.arange(n) / sr).astype(np.float32)
        pcm = np.concatenate([np.zeros(sr // 10, np.float32), pcm, np.zeros(sr // 10, np.float32)])
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        sf.write(out, pcm, sr)
        return Path(out)

    def voices(self):
        return [{"id": "v", "label": "V"}]

class FakeASR:
    def __init__(self, text="你好世界。今天天气很好！我们去公园吧。"):
        self.text = text; self.calls = 0; self.speakers = False

    def transcribe(self, wav16k, progress=None):
        self.calls += 1
        words, t, spk = [], 0.2, 0
        for c in self.text:
            words.append(Word(text=c, start=round(t, 3), end=round(t + 0.15, 3), speaker=spk if self.speakers else None))
            t += 0.15
            if c in "。！":
                t += 0.5; spk = 1 - spk
        return words

def fake_separate(calls: list | None = None):
    def sep(audio_wav, out_dir, progress=None, cancel=None):
        import shutil
        if calls is not None:
            calls.append(1)
        out_dir = Path(out_dir)
        v, nv = out_dir / "vocals.wav", out_dir / "no_vocals.wav"
        shutil.copyfile(audio_wav, v); shutil.copyfile(audio_wav, nv)
        return v, nv
    return sep

def ids_in(prompt: str) -> list[int]:
    return [int(m) for m in re.findall(r'"id": (\d+)', prompt[prompt.rindex("<<<ITEMS"):])]

def review_llm_hook(prompt, schema):
    """Answers for the review-phim prompts, keyed on the schema's top-level properties."""
    props = schema["properties"]
    if "events" in props:                                  # chunk summary: everything inside SPAN a b
        a, b = map(float, re.search(r"SPAN (\S+) (\S+)", prompt).groups())
        q = (b - a) / 4
        return {"summary": "Tiểu Minh lên đường.", "characters": ["Tiểu Minh"],
                "events": [{"start": a + q, "end": b - q, "text": "Tiểu Minh rời nhà"}],
                "highlights": [{"start": a + q, "end": a + 2 * q, "text": "Câu thoại đắt giá"}]}
    if "blocks" in props:                                  # script: TARGET n syllables, 3 s scenes inside RANGE a b
        n = int(re.search(r"TARGET (\d+)", prompt).group(1))
        a, b = map(float, re.search(r"RANGE (\S+) (\S+)", prompt).groups())
        sizes = [n // 4] * 3 + [n - 3 * (n // 4)]
        return {"blocks": [{"kind": k, "text": " ".join(["chữ"] * m),
                            "scenes": [{"start": a + i * (b - a) / 4, "end": min(b, a + i * (b - a) / 4 + 3)}],
                            "source_start": a, "source_end": b}
                           for i, (k, m) in enumerate(zip(["hook", "mo_dau", "than", "ket"], sizes))]}
    if "entry" in props:
        return {"entry": {"summary": "Tiểu Minh lên đường.", "ending": "Tiểu Minh rời nhà", "open_threads": [],
                          "hooks": []},
                "characters": [{"name": "Tiểu Minh", "aliases": [], "role": "nhân vật chính", "relations": "",
                                "arc": ""}], "voice": ""}
    if "text" in props:
        return {"text": "Viết lại"}
    if "characters" in props and "summary" not in props:
        return {"characters": [{"name": "Tiểu Minh", "aliases": ["小明"], "role": "nhân vật chính"}]}
    return None
