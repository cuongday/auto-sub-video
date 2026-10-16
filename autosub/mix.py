"""Place fitted voice lines on the timeline and mix them over the background stem."""
from pathlib import Path
import numpy as np
import soundfile as sf
from . import media, proc

SR = 44100
FADE = int(0.01 * SR)

def build_voice_track(items: list[tuple[float, Path]], duration: float) -> np.ndarray:
    track = np.zeros(int(round(duration * SR)), dtype=np.float32)
    ramp = np.linspace(0, 1, FADE, dtype=np.float32)
    for start, path in items:
        pcm, sr = sf.read(path, dtype="float32", always_2d=True)
        pcm = pcm.mean(axis=1)
        if sr != SR:
            pcm = media.decode_mono(path, SR)
        if len(pcm) > 2 * FADE:
            pcm = pcm.copy(); pcm[:FADE] *= ramp; pcm[-FADE:] *= ramp[::-1]
        a = int(round(start * SR))
        if a >= len(track):
            continue
        n = min(len(pcm), len(track) - a)
        track[a:a + n] += pcm[:n]
    return track

def mix(voice_raw: Path, bg: Path | None, out_voice: Path, out_m4a: Path, bg_volume_db: float, duration: float,
        cancel=None, duck_db: float | None = None) -> None:
    """voice.wav = loudness-normalized voice; mix.m4a = voice + background (gain bg_volume_db), limited.
    duck_db: also lower the background by about this much while the voice speaks (used when the background
    is the original audio, i.e. still contains the original speech)."""
    out_voice, out_m4a = Path(out_voice), Path(out_m4a)
    tmp_voice = out_voice.with_name(out_voice.stem + ".tmp.wav")
    proc.run_ffmpeg(["-i", str(voice_raw), "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", str(SR), "-ac", "1",
                     "-t", f"{duration:.3f}", "-c:a", "pcm_s16le", str(tmp_voice)], cancel=cancel)
    tmp_voice.replace(out_voice)
    tmp_mix = out_m4a.with_name(out_m4a.stem + ".tmp.m4a")
    if bg is not None and duck_db is not None:
        ratio = max(2.0, min(20.0, 10 ** (-duck_db / 20)))       # compression ratio giving roughly duck_db of reduction
        graph = (f"[1:a]volume={bg_volume_db}dB,aresample={SR}[bg];"
                 f"[0:a]aresample={SR},pan=stereo|c0=c0|c1=c0,asplit=2[vo][key];"
                 f"[bg][key]sidechaincompress=threshold=0.003:ratio={ratio:.1f}:attack=20:release=400:makeup=1[ducked];"
                 "[vo][ducked]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]")
        args = ["-i", str(out_voice), "-i", str(bg), "-filter_complex", graph, "-map", "[a]"]
    elif bg is not None:
        graph = (f"[1:a]volume={bg_volume_db}dB,aresample={SR}[bg];[0:a]aresample={SR},pan=stereo|c0=c0|c1=c0[vo];"
                 "[vo][bg]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]")
        args = ["-i", str(out_voice), "-i", str(bg), "-filter_complex", graph, "-map", "[a]"]
    else:
        args = ["-i", str(out_voice), "-af", "pan=stereo|c0=c0|c1=c0"]
    proc.run_ffmpeg([*args, "-t", f"{duration:.3f}", "-c:a", "aac", "-b:a", "192k", str(tmp_mix)], cancel=cancel)
    tmp_mix.replace(out_m4a)
