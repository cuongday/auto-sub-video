"""Split speech from music/effects with Demucs (htdemucs, two stems) as a child process."""
import re
import shutil
import sys
import tempfile
from pathlib import Path
from . import proc

_PCT = re.compile(r"(\d{1,3})%\|")

def available() -> bool:
    import importlib.util
    return importlib.util.find_spec("demucs") is not None

def separate(audio_wav: Path, out_dir: Path, progress=None, cancel=None) -> tuple[Path, Path]:
    if not available():
        raise RuntimeError("Chưa cài Demucs: make setup-full")
    out_dir = Path(out_dir)
    with tempfile.TemporaryDirectory(dir=out_dir, prefix=".demucs-") as tmp:
        def on_line(line: str):
            m = _PCT.findall(line)
            if progress and m:
                progress(int(m[-1]) / 100)
        proc.run([sys.executable, "-m", "demucs", "-n", "htdemucs", "--two-stems", "vocals", "-d", "cpu",
                  "-o", tmp, "--filename", "{stem}.{ext}", str(audio_wav)], cancel=cancel, on_line=on_line)
        found = {p.name: p for p in Path(tmp).rglob("*.wav")}
        if "vocals.wav" not in found or "no_vocals.wav" not in found:
            raise RuntimeError("Demucs không tạo ra vocals.wav/no_vocals.wav")
        vocals, rest = out_dir / "vocals.wav", out_dir / "no_vocals.wav"
        shutil.move(str(found["vocals.wav"]), vocals)
        shutil.move(str(found["no_vocals.wav"]), rest)
    return vocals, rest
