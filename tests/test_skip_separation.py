import numpy as np
import soundfile as sf
from autosub import media, store
from autosub.mix import SR, build_voice_track, mix
from autosub.storage import get_store
from tests.test_pipeline import Rig

def test_skip_separation_never_runs_demucs(tmp_path):
    rig = Rig(tmp_path)
    job = store.load(rig.job.id); job.settings.separate = False; store.save(job)
    job = rig.run(mode="auto")
    assert job.state == "done" and rig.sep_calls == [] and rig.asr.calls == 1
    names = store.names(job.id)
    assert "vocals16k.wav" in names and "no_vocals.wav" not in names and "output.mp4" in names

def test_toggling_separation_reruns_from_separate(tmp_path):
    rig = Rig(tmp_path)
    rig.run(mode="auto")
    job = store.load(rig.job.id); job.settings.separate = False; store.save(job)
    job = rig.run(mode="auto")
    assert job.state == "done" and len(rig.sep_calls) == 1          # not re-run, just skipped

def test_ducking_lowers_background_only_under_voice(tmp_path):
    dur = 4.0
    bg = tmp_path / "bg.wav"
    t = np.arange(int(SR * dur)) / SR
    sf.write(bg, np.stack([0.3 * np.sin(2 * np.pi * 300 * t)] * 2, axis=1).astype(np.float32), SR)
    line = tmp_path / "l.wav"
    sf.write(line, (0.3 * np.sin(2 * np.pi * 800 * np.arange(SR) / SR)).astype(np.float32), SR)
    raw = tmp_path / "raw.wav"
    sf.write(raw, build_voice_track([(2.0, line)], dur), SR)
    mix(raw, bg, tmp_path / "voice.wav", tmp_path / "mix.m4a", 0.0, dur, duck_db=-14.0)
    out = media.decode_mono(tmp_path / "mix.m4a", SR)
    bg_only = np.abs(np.fft.rfft(out[int(0.5 * SR):int(1.5 * SR)]))
    under = np.abs(np.fft.rfft(out[int(2.3 * SR):int(2.8 * SR)]))
    f = np.fft.rfftfreq(SR, 1 / SR); fu = np.fft.rfftfreq(int(0.5 * SR), 1 / SR)
    a = bg_only[np.argmin(np.abs(f - 300))] / SR
    b = under[np.argmin(np.abs(fu - 300))] / (0.5 * SR)
    assert 20 * np.log10(b / a) < -8          # background 300 Hz tone is ducked while the line plays

def test_prune_with_skipped_separation_rebuilds_audio_for_mix(tmp_path):
    from autosub import prune
    rig = Rig(tmp_path)
    job = store.load(rig.job.id); job.settings.separate = False; store.save(job)
    rig.run(mode="auto")
    prune.prune(rig.job.id)                       # removes audio.wav, which is the background here
    job = store.load(rig.job.id); job.settings.bg_volume_db = -3; store.save(job)
    job = rig.run(mode="auto")
    assert job.state == "done" and rig.sep_calls == []
